"""Safety harness for fmp_sync tests (#1344).

Every test here is hermetic: state and home directories are redirected to
``tmp_path``, DB/FMP environment is removed, and any attempt to open a MySQL
connection or a non-loopback socket fails the test. The live persistent store
(``openbb_fmp_cache_test``) and the old copy (``openbb_fmp_cache``) must never
reach a connection call.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

PROTECTED_DATABASES = ("openbb_fmp_cache", "openbb_fmp_cache_test")
HERE = Path(__file__).resolve().parent
HELPERS = HERE / "helpers"
PORTFOLIO_UTILS_ROOT = HERE.parents[1]
FIXTURES_1338 = (
    HERE.parents[3]
    / "extensions"
    / "agents"
    / "tests"
    / "hermes_integration"
    / "fixtures"
)
DISPOSABLE_DB = "obb_disposable_abcdef12"


def _is_loopback(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _fmp_sync_safety(monkeypatch, tmp_path):
    """Redirect state/home, strip DB env, and block MySQL plus non-loopback sockets."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FMP_SYNC_STATE_ROOT", str(tmp_path / "state"))
    for var in ("HOME", "USERPROFILE", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for var in list(__import__("os").environ):
        if var.startswith("DB_") or var in ("FMP_API_KEY", "FMP_CACHE_TEST_MODE"):
            monkeypatch.delenv(var, raising=False)

    attempts: list[dict] = []

    def _blocked_connect(*args, **kwargs):
        attempts.append({"args": args, "kwargs": kwargs})
        raise RuntimeError("fmp_sync tests must never open a MySQL connection")

    try:
        import pymysql  # pylint: disable=import-outside-toplevel

        monkeypatch.setattr(pymysql, "connect", _blocked_connect)
        monkeypatch.setattr(pymysql, "Connect", _blocked_connect, raising=False)
    except ImportError:  # pragma: no cover - pymysql is in the venv
        pass

    real_connect = socket.socket.connect

    def _guarded_connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(
            address
        ):
            attempts.append({"socket": True})
            raise RuntimeError("fmp_sync tests must never open a non-loopback socket")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    yield
    assert attempts == [], "a test attempted a MySQL or non-loopback connection"
    for attempt in attempts:  # pragma: no cover - documented invariant
        text = json.dumps(attempt, default=str)
        assert not any(name in text for name in PROTECTED_DATABASES)


@pytest.fixture
def child_env(monkeypatch):
    """Environment for child interpreters: current (sanitized) env + PYTHONPATH."""
    import os  # pylint: disable=import-outside-toplevel

    env = dict(os.environ)
    agents_root = HERE.parents[3] / "extensions" / "agents"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PORTFOLIO_UTILS_ROOT), str(agents_root), env.get("PYTHONPATH", "")]
    )
    return env


@pytest.fixture
def synthetic_settings(tmp_path):
    """Write a synthetic user_settings.json resolving to ``database``."""

    def _write(database: str | None, name: str = "user_settings.json") -> Path:
        src = FIXTURES_1338 / "settings" / "synthetic-user_settings.json"
        data = json.loads(src.read_text(encoding="utf-8"))
        if database is None:
            data["credentials"].pop("mysql_database", None)
        else:
            data["credentials"]["mysql_database"] = database
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def home_settings(synthetic_settings, tmp_path):
    """Place synthetic settings where ``DatabaseConfig`` / provenance look (tmp HOME)."""

    def _place(database: str | None) -> Path:
        path = synthetic_settings(database)
        target = tmp_path / "home" / ".openbb_platform" / "user_settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        return target

    return _place


@pytest.fixture
def python_exe() -> str:
    """The interpreter running the tests (used for real child processes)."""
    return sys.executable
