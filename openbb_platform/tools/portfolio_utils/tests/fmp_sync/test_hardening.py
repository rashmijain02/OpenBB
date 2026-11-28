"""Review fixes for #1344: fail-closed edges found after T03. No DB, no network."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

import pytest
from portfolio_utils.fmp_sync import budget, locking, state
from portfolio_utils.fmp_sync.admission import load_map
from portfolio_utils.fmp_sync.budget import BudgetLedger, Limits
from portfolio_utils.fmp_sync.locking import LockRootRejected
from portfolio_utils.fmp_sync.outcome import Outcome

from .conftest import DISPOSABLE_DB
from .test_admission import _admit, world  # noqa: F401  (fixture)
from .test_dispatcher import LIMITS, harness  # noqa: F401  (fixture)
from .test_locking import holder, state_root  # noqa: F401  (fixtures)

WINDOWS = sys.platform == "win32"


# ------------------------------------------------------------------ CODE-4


def test_legacy_selector_dry_run_is_blocked_policy(harness):  # noqa: F811
    out = harness.run("dry_run", limits=None, map_kwargs={"legacy_selector": True})
    assert out.outcome is Outcome.BLOCKED_POLICY and out.exit_code == 40
    assert "LEGACY_SELECTOR_REQUIRES_EXECUTE" in out.findings
    assert harness.probes == [] and harness.sent == []


# ------------------------------------------------------------------ SECURITY-1


def test_holiday_step_never_imports_a_planted_module(tmp_path, monkeypatch):
    planted = tmp_path / "scripts"
    planted.mkdir()
    marker = tmp_path / "planted.marker"
    stub = f"open({str(marker)!r}, 'w').close()\n"
    (planted / "populate_market_holidays.py").write_text(
        stub + "def compute_us_holidays(a, b):\n    return []\n", encoding="utf-8"
    )
    (planted / "hashlib.py").write_text(stub, encoding="utf-8")
    monkeypatch.syspath_prepend(str(planted))
    monkeypatch.chdir(planted)
    monkeypatch.delitem(sys.modules, "populate_market_holidays", raising=False)

    import pymysql  # pylint: disable=import-outside-toplevel
    from openbb_fmp_cached.utils import (  # pylint: disable=import-outside-toplevel
        database,
    )
    from portfolio_utils import (  # pylint: disable=import-outside-toplevel
        fetch_position_history as tool,
    )

    rows: list = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def executemany(self, _sql, data):
            rows.extend(data)

        def execute(self, *_a, **_k):
            return 0

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            return None

        def close(self):
            return None

    class _Cfg:
        connection_params = {"host": "127.0.0.1"}

    monkeypatch.setattr(database, "DatabaseConfig", _Cfg)
    monkeypatch.setattr(pymysql, "connect", lambda **_k: _Conn())
    tool.ensure_market_holidays(2026, 2027, DISPOSABLE_DB)
    assert not marker.exists(), "a module planted on sys.path was imported"
    assert rows, "the holiday step did not run"


# ------------------------------------------------------------------ CODE-3


def _open_without_share_delete(path: Path):
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    # GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE (no DELETE), OPEN_EXISTING
    handle = k32.CreateFileW(str(path), 0x80000000, 0x3, None, 3, 0x80, None)
    assert handle not in (None, wintypes.HANDLE(-1).value)
    return k32, handle


@pytest.mark.skipif(not WINDOWS, reason="Windows sharing semantics")
def test_open_handle_without_share_delete_is_replace_failed(tmp_path):
    target = tmp_path / "status.json"
    target.write_text("{}", encoding="utf-8")
    k32, handle = _open_without_share_delete(target)
    seen: list = []

    def replace(src, dst):
        try:
            os.replace(src, dst)
        except OSError as error:
            seen.append(getattr(error, "winerror", None))
            raise

    try:
        result = state.atomic_write_json(
            target, {"a": 1}, replace_fn=replace, sleep_fn=lambda _s: None, attempts=2
        )
    finally:
        k32.CloseHandle(handle)
    assert seen == [5, 5]  # recorded: the held handle surfaces as WinError 5
    assert not result.ok and result.code == "STATE_REPLACE_FAILED"
    assert target.read_text(encoding="utf-8") == "{}"


@pytest.mark.skipif(not WINDOWS, reason="Windows attributes")
def test_read_only_target_is_acl_denied(tmp_path):
    target = tmp_path / "status.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o444)
    try:
        result = state.atomic_write_json(
            target, {"a": 1}, sleep_fn=lambda _s: None, attempts=2
        )
    finally:
        os.chmod(target, 0o666)
    assert not result.ok and result.code == "STATE_ACL_DENIED"


# ------------------------------------------------------------------ ledger


def test_unreadable_ledger_fails_closed_and_keeps_counters(harness):  # noqa: F811
    root = Path(os.environ["FMP_SYNC_STATE_ROOT"])
    limits, _ = Limits.from_map(LIMITS)
    day = BudgetLedger(root, "acct", limits, now_fn=harness.wall)._day_path(
        harness.wall()
    )
    day.parent.mkdir(parents=True, exist_ok=True)
    day.write_bytes(b"\x00not json")
    out = harness.run()
    assert out.outcome is Outcome.FAILED_INFRA and out.exit_code == 30
    assert "LEDGER_UNREADABLE" in out.findings
    assert harness.sent == []
    assert day.read_bytes() == b"\x00not json"  # never reset


def test_unreadable_defer_file_fails_closed(tmp_path):
    limits, _ = Limits.from_map(LIMITS)
    ledger = BudgetLedger(tmp_path, "acct", limits)
    ledger.dir.mkdir(parents=True)
    (ledger.dir / "defer.json").write_text("[1, 2", encoding="utf-8")
    with pytest.raises(budget.BudgetExhausted) as info:
        ledger.reserve()
    assert info.value.kind == "ledger_unreadable"


@pytest.mark.parametrize("label", ["..", ".", "a.b", "a/b", "a\\b", ""])
def test_account_label_must_be_a_safe_identifier(tmp_path, label):
    limits, _ = Limits.from_map(LIMITS)
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path, label, limits)
    data = {
        "schema_version": 1,
        "source_root": "s",
        "source_sha": "a" * 40,
        "interpreter": "v",
        "target": DISPOSABLE_DB,
        "target_class": "disposable",
        "profile_path": "p",
        "account_label": label,
    }
    path = tmp_path / "map.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_map(path)


# ------------------------------------------------------------------ state root


def test_drive_type_checked_after_resolve(monkeypatch, tmp_path):
    monkeypatch.setattr(locking, "_resolve", lambda _p: Path(r"\\server\share\s"))
    with pytest.raises(LockRootRejected, match="network"):
        locking.validate_state_root(tmp_path / "state")
    if WINDOWS:
        monkeypatch.setattr(locking, "_resolve", lambda _p: Path("Q:/fmp-sync"))
        monkeypatch.setattr(
            locking,
            "_drive_type",
            lambda root: locking.DRIVE_REMOTE if root.upper().startswith("Q") else 3,
        )
        with pytest.raises(LockRootRejected, match="network"):
            locking.validate_state_root(tmp_path / "state")


# ------------------------------------------------------------------ dotenv drift


@pytest.mark.parametrize(
    "key", ["HTTPS_PROXY", "HTTP_PROXY", "REQUESTS_CA_BUNDLE", "FMP_SYNC_STATE_ROOT"]
)
def test_import_drift_of_transport_and_state_keys(world, key):  # noqa: F811
    env: dict[str, str] = {}
    result = _admit(world, env=env, import_warmer_fn=lambda: env.update({key: "x"}))
    assert "DOTENV_DRIFT" in result.findings


@pytest.mark.parametrize("key", ["HTTPS_PROXY", "REQUESTS_CA_BUNDLE"])
def test_dotenv_file_drift_of_transport_keys(world, tmp_path, key):  # noqa: F811
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text(f"{key}=http://127.0.0.1:9\n", encoding="utf-8")
    result = _admit(world, env={}, dotenv_path=dotenv, import_warmer_fn=lambda: None)
    assert "DOTENV_DRIFT" in result.findings


# ------------------------------------------------------------------ lock_status


def test_lock_status_never_contends_for_the_byte_lock(
    holder, state_root, monkeypatch  # noqa: F811
):
    def _forbidden(_fd):
        raise AssertionError("lock_status must not take the byte lock")

    assert locking.lock_status(DISPOSABLE_DB, root=state_root) == "free"
    h = holder()
    monkeypatch.setattr(locking, "_os_try_lock", _forbidden)
    assert locking.lock_status(DISPOSABLE_DB, root=state_root) == "busy"
    h.release()
    assert locking.lock_status(DISPOSABLE_DB, root=state_root) == "free"


@pytest.mark.parametrize(
    "key", ["CURL_CA_BUNDLE", "SSL_CERT_FILE", "ALL_PROXY", "NO_PROXY", "FMP_API_KEY"]
)
def test_import_drift_of_tls_proxy_and_key_settings(world, key):  # noqa: F811
    """A warmer import that sets TLS / proxy / FMP-key settings is drift."""
    env: dict[str, str] = {}
    result = _admit(world, env=env, import_warmer_fn=lambda: env.update({key: "x"}))
    assert "DOTENV_DRIFT" in result.findings


def test_drift_snapshot_never_holds_raw_values():
    """The drift snapshot keeps presence + hash only, never the value."""
    from portfolio_utils.fmp_sync import (
        admission,
    )  # pylint: disable=import-outside-toplevel

    snap = admission._db_env(  # pylint: disable=protected-access
        {"FMP_API_KEY": "s3cr3t-key-value", "DB_PASSWORD": "pw-value-1"}
    )
    assert set(snap) == {"FMP_API_KEY", "DB_PASSWORD"}
    assert "s3cr3t-key-value" not in repr(snap) and "pw-value-1" not in repr(snap)
    assert snap != admission._db_env(  # pylint: disable=protected-access
        {"FMP_API_KEY": "other", "DB_PASSWORD": "pw-value-1"}
    )
