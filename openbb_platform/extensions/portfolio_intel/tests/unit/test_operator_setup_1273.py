# ruff: noqa: D103, S104, S105, S603
"""Portable connector and operator setup (#1273).

Discriminators:

- **CORS origins are operator-configurable** through
  ``PI_WIDGET_BACKEND_ALLOWED_ORIGINS`` with safe defaults; a wildcard,
  ``null`` or an origin with a path is rejected (credentials are allowed,
  so a wildcard would be unsafe).
- **Access logs never carry query values** (routed from #1269): uvicorn's
  access line for ``/pi/...?account_id=<id>&basket_id=<id>`` must not
  contain either id, on the real uvicorn server path.
- **Fail safe binding**: ``loopback-dev`` (unauthenticated) refuses any
  non-loopback host in the supported launcher.
- **Health and startup validation**: ``/health`` is bare liveness;
  ``/health/details`` (authenticated) reports auth mode, demo
  mode and the manifest verdict without secrets; startup logs manifest
  problems clearly.
- **Launcher status/stop** report without printing the token and never
  signal a process whose identity the backend did not confirm.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import pytest
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import (
    _app as backend_app,
    operator_config,
    serve,
)
from openbb_portfolio_intel.widget_backend.main import app

_CLIENT = TestClient(app)
_EXTENSION = Path(__file__).resolve().parents[2]
_REPO = _EXTENSION.parents[2]
_BACKEND = _EXTENSION / "openbb_portfolio_intel" / "widget_backend"
_DOC = _REPO / "docs" / "operations" / "portfolio-intelligence-operator-setup.md"

_SENTINEL_ACCOUNT = "SENTINELACCT7731"
_SENTINEL_BASKET = "SENTINELBASKET4419"
_SENTINEL_TOKEN = "sentinel-token-do-not-print-5521"


# ---------------------------------------------------------------------------
# CORS origin configuration
# ---------------------------------------------------------------------------


def test_default_origins_are_hosted_and_self_hosted_workspace() -> None:
    assert operator_config.allowed_origins({}) == [
        "https://pro.openbb.co",
        "http://127.0.0.1:1420",
    ]
    assert operator_config.allowed_origins(
        {"PI_WIDGET_BACKEND_ALLOWED_ORIGINS": "  "}
    ) == ["https://pro.openbb.co", "http://127.0.0.1:1420"]


def test_configured_origins_replace_defaults_and_normalize() -> None:
    env = {
        "PI_WIDGET_BACKEND_ALLOWED_ORIGINS": (
            "https://Workspace.Example.com/, http://localhost:1420"
        )
    }
    assert operator_config.allowed_origins(env) == [
        "https://workspace.example.com",
        "http://localhost:1420",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "null",
        "https://*.example.com",
        "workspace.example.com",
        "ftp://workspace.example.com",
        "https://workspace.example.com/app",
        "https://workspace.example.com?x=1",
        "https://user:pw@workspace.example.com",
    ],
)
def test_unsafe_origins_are_rejected(bad: str) -> None:
    with pytest.raises(operator_config.OperatorConfigError):
        operator_config.allowed_origins({"PI_WIDGET_BACKEND_ALLOWED_ORIGINS": bad})


def _run_backend_snippet(
    code: str, extra_env: dict[str, str]
) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PI_WIDGET_BACKEND_")
    }
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


_PREFLIGHT = """
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import _app
client = TestClient(_app.app)
for origin in ("https://workspace.example.com", "https://pro.openbb.co"):
    r = client.options("/health", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET"})
    print(origin, r.headers.get("access-control-allow-origin"))
"""


def test_backend_cors_uses_configured_origins() -> None:
    """The real app's CORS middleware honours the operator's origin list."""
    result = _run_backend_snippet(
        _PREFLIGHT,
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "loopback-dev",
            "PI_WIDGET_BACKEND_ALLOWED_ORIGINS": "https://workspace.example.com",
        },
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines())
    assert lines["https://workspace.example.com"] == "https://workspace.example.com"
    assert lines["https://pro.openbb.co"] == "None"


def test_backend_refuses_wildcard_origin_at_startup() -> None:
    result = _run_backend_snippet(
        "import openbb_portfolio_intel.widget_backend._app",
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "loopback-dev",
            "PI_WIDGET_BACKEND_ALLOWED_ORIGINS": "*",
        },
    )
    assert result.returncode != 0
    assert "PI_WIDGET_BACKEND_ALLOWED_ORIGINS" in result.stderr


# ---------------------------------------------------------------------------
# Access-log privacy (routed from #1269)
# ---------------------------------------------------------------------------


def test_redact_query_keeps_keys_and_drops_values() -> None:
    target = f"/pi/xray/sector?account_id={_SENTINEL_ACCOUNT}&basket_id={_SENTINEL_BASKET}&flag"
    redacted = operator_config.redact_query(target)
    assert _SENTINEL_ACCOUNT not in redacted
    assert _SENTINEL_BASKET not in redacted
    assert redacted.startswith("/pi/xray/sector?")
    assert "account_id=<redacted>" in redacted
    assert "basket_id=<redacted>" in redacted
    assert operator_config.redact_query("/widgets.json") == "/widgets.json"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_real_uvicorn_access_log_omits_account_and_basket_ids() -> None:
    """Serve the real app with uvicorn on loopback and read its access log."""
    import httpx  # pylint: disable=import-outside-toplevel
    import uvicorn  # pylint: disable=import-outside-toplevel

    port = _free_port()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="off", access_log=True
    )
    server = uvicorn.Server(config)
    handler = _ListHandler()
    access = logging.getLogger("uvicorn.access")
    access.addHandler(handler)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start"
        resp = httpx.get(
            f"http://127.0.0.1:{port}/widgets.json",
            params={"account_id": _SENTINEL_ACCOUNT, "basket_id": _SENTINEL_BASKET},
            timeout=30,
        )
        assert resp.status_code == 200
        deadline = time.monotonic() + 5
        while not handler.lines and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        access.removeHandler(handler)
    joined = "\n".join(handler.lines)
    assert "/widgets.json" in joined, joined
    assert _SENTINEL_ACCOUNT not in joined
    assert _SENTINEL_BASKET not in joined


def test_access_log_redaction_is_installed_once() -> None:
    access = logging.getLogger("uvicorn.access")
    before = [
        f
        for f in access.filters
        if isinstance(f, operator_config.AccessLogRedactionFilter)
    ]
    operator_config.install_access_log_redaction()
    after = [
        f
        for f in access.filters
        if isinstance(f, operator_config.AccessLogRedactionFilter)
    ]
    assert len(before) == 1
    assert len(after) == 1


# ---------------------------------------------------------------------------
# Fail-safe binding and launcher preflight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_loopback_dev_allows_loopback_hosts(host: str) -> None:
    assert operator_config.check_bind(host, "loopback-dev") is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "example.com"])
def test_loopback_dev_refuses_non_loopback_hosts(host: str) -> None:
    with pytest.raises(operator_config.OperatorConfigError, match="loopback-dev"):
        operator_config.check_bind(host, "loopback-dev")


def test_required_mode_warns_on_non_loopback_host() -> None:
    warning = operator_config.check_bind("0.0.0.0", "required")
    assert warning and "reverse proxy" in warning
    assert operator_config.check_bind("127.0.0.1", "required") is None


def test_preflight_reports_every_problem_without_the_token() -> None:
    errors, _ = operator_config.preflight(
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "required",
            "PI_DEMO_MODE": "sometimes",
            "PI_WIDGET_BACKEND_ALLOWED_ORIGINS": "*",
        },
        "127.0.0.1",
    )
    text = "\n".join(errors)
    assert "PI_WIDGET_BACKEND_TOKEN" in text
    assert "PI_DEMO_MODE" in text
    assert "PI_WIDGET_BACKEND_ALLOWED_ORIGINS" in text

    errors, _ = operator_config.preflight(
        {"PI_WIDGET_BACKEND_AUTH_MODE": "loopback-dev"}, "0.0.0.0"
    )
    assert any("loopback-dev" in e for e in errors)

    errors, _ = operator_config.preflight(
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "required",
            "PI_WIDGET_BACKEND_TOKEN": _SENTINEL_TOKEN,
        },
        "127.0.0.1",
    )
    assert errors == []


def test_launcher_run_refuses_non_loopback_in_loopback_dev(monkeypatch, capsys) -> None:
    called = []
    monkeypatch.setattr(serve, "_uvicorn_run", lambda **kw: called.append(kw))
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    code = serve.main(["run", "--host", "0.0.0.0", "--port", "6199"])
    assert code == 2
    assert called == []
    assert "loopback-dev" in capsys.readouterr().err


def test_launcher_start_refuses_non_loopback_in_loopback_dev(
    monkeypatch, tmp_path
) -> None:
    spawned = []
    monkeypatch.setattr(serve, "_spawn", lambda *a, **k: spawned.append(a))
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    code = serve.main(
        ["start", "--host", "0.0.0.0", "--state-dir", str(tmp_path), "--port", "6199"]
    )
    assert code == 2
    assert spawned == []


def test_launcher_run_starts_uvicorn_on_loopback(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(serve, "_uvicorn_run", lambda **kw: called.append(kw))
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
    monkeypatch.delenv("PI_WIDGET_BACKEND_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("PI_DEMO_MODE", raising=False)
    assert serve.main(["run", "--port", "6199"]) == 0
    assert called == [
        {
            "app": "openbb_portfolio_intel.widget_backend.main:app",
            "host": "127.0.0.1",
            "port": 6199,
            "reload": False,
        }
    ]


# ---------------------------------------------------------------------------
# Health endpoint and startup validation
# ---------------------------------------------------------------------------


_DETAIL_FIELDS = ("pid", "auth_mode", "demo_mode", "allowed_origins", "manifest")


def test_health_is_minimal_liveness() -> None:
    """Unauthenticated /health exposes no deployment detail (lead decision)."""
    resp = _CLIENT.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-store"
    body = resp.json()
    assert body == {"status": "ok"}
    for field in _DETAIL_FIELDS:
        assert field not in resp.text


def test_health_details_reports_modes_and_manifest_to_loopback_client() -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/health/details")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-store"
    body = resp.json()
    widgets = json.loads((_BACKEND / "widgets.json").read_text(encoding="utf-8"))
    apps = json.loads((_BACKEND / "apps.json").read_text(encoding="utf-8"))
    assert body["status"] == "ok"
    assert body["service"] == "portfolio-intel-widget-backend"
    assert body["pid"] == os.getpid()
    assert body["auth_mode"] == "loopback-dev"
    assert body["demo_mode"] == os.environ.get("PI_DEMO_MODE", "fallback")
    assert body["allowed_origins"] == backend_app._ALLOWED_ORIGINS
    manifest = body["manifest"]
    assert manifest["widgets"] == len(widgets)
    assert manifest["apps"] == len(apps)
    assert manifest["ok"] is True
    assert manifest["new"] == []


@pytest.mark.parametrize("host", ["192.168.1.20", "testclient"])
def test_health_details_refuses_non_loopback_client_in_loopback_dev(
    host: str,
) -> None:
    client = TestClient(app, client=(host, 50000))
    resp = client.get("/health/details")
    assert resp.status_code == 403
    for field in _DETAIL_FIELDS:
        assert field not in resp.text


_DETAILS_PROBE = """
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import _app
c = TestClient(_app.app, client=("127.0.0.1", 50000))
print(c.get("/health").status_code, c.get("/health").text)
print(c.get("/health/details").status_code)
print(c.get("/health/details", headers={"Authorization": "Bearer wrong"}).status_code)
ok = c.get("/health/details", headers={"Authorization": "Bearer TOKEN"})
print(ok.status_code, ok.json()["auth_mode"])
print(ok.text)
"""


def test_health_details_requires_token_in_required_mode() -> None:
    result = _run_backend_snippet(
        _DETAILS_PROBE.replace("TOKEN", _SENTINEL_TOKEN),
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "required",
            "PI_WIDGET_BACKEND_TOKEN": _SENTINEL_TOKEN,
        },
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.strip().splitlines()
    assert lines[0] == '200 {"status":"ok"}'
    assert lines[1] == "401"
    assert lines[2] == "401"
    assert lines[3] == "200 required"
    assert _SENTINEL_TOKEN not in lines[4]


def test_manifest_report_flags_new_issues_against_baseline(tmp_path) -> None:
    baseline = tmp_path / "debt.json"
    baseline.write_text(json.dumps({"issues": []}), encoding="utf-8")
    report = operator_config.manifest_report(
        {"pi_x": {"name": "X"}}, [], routes=set(), baseline=baseline
    )
    assert report["ok"] is False
    assert report["issues"] >= 1
    assert report["new"], report
    assert report["recorded_debt"] == 0


def test_startup_validation_logs_manifest_problems(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        backend_app,
        "_read_manifests",
        lambda: ({"pi_broken": {"name": "Broken"}}, []),
    )

    class _State:
        pass

    class _FakeApp:
        state = _State()
        routes: list = []

    with caplog.at_level(logging.WARNING, logger=backend_app.logger.name):
        report = backend_app._validate_manifests_on_startup(_FakeApp())
    assert report["ok"] is False
    assert _FakeApp.state.manifest_report is report
    messages = [
        r.getMessage()
        for r in caplog.records
        if "Workspace manifest validation" in r.getMessage()
    ]
    assert len(messages) == 1
    assert "pi_broken" in messages[0]
    assert "validate_portfolio_workspace_manifests.py" in messages[0]


def test_startup_validation_survives_unreadable_manifest(monkeypatch, caplog) -> None:
    def _boom():
        raise ValueError("bad json")

    monkeypatch.setattr(backend_app, "_read_manifests", _boom)

    class _State:
        pass

    class _FakeApp:
        state = _State()
        routes: list = []

    with caplog.at_level(logging.WARNING, logger=backend_app.logger.name):
        report = backend_app._validate_manifests_on_startup(_FakeApp())
    assert report == {"ok": False, "error": "manifest unreadable: ValueError"}
    assert any(
        "Workspace manifest validation failed" in r.getMessage() for r in caplog.records
    )


def test_lifespan_runs_startup_manifest_validation() -> None:
    import ast  # pylint: disable=import-outside-toplevel
    import inspect  # pylint: disable=import-outside-toplevel

    tree = ast.parse(inspect.getsource(backend_app._lifespan))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_validate_manifests_on_startup" in calls


# ---------------------------------------------------------------------------
# Launcher status / stop / start (#1273 review: SECURITY-1, CODE-1..3)
# ---------------------------------------------------------------------------

_HEALTH = {
    "status": "ok",
    "service": "portfolio-intel-widget-backend",
    "pid": 4242,
    "auth_mode": "required",
    "demo_mode": "off",
    "allowed_origins": ["https://pro.openbb.co"],
    "manifest": {
        "ok": True,
        "widgets": 61,
        "apps": 3,
        "issues": 5,
        "recorded_debt": 5,
        "new": [],
        "stale_baseline": [],
    },
}
_NONCE = "launch-nonce-for-tests"


def _write_record(state_dir: Path, **extra) -> Path:
    record = {
        "pid": 4242,
        "launcher_pid": 1111,
        "host": "127.0.0.1",
        "port": 6120,
        "nonce": _NONCE,
    }
    record.update(extra)
    path = state_dir / "backend-6120.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _details(payload):
    return lambda host, port, token=None, timeout=5.0: payload


@pytest.fixture
def ours(monkeypatch):
    """Make the server prove our nonce, with pid 4242 descending from 1111."""
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: True)
    monkeypatch.setattr(serve, "_process_parents", lambda: {4242: 1111, 1111: 1})


def test_status_reports_health_modes_manifest_without_token(
    monkeypatch, tmp_path, capsys, ours
) -> None:
    _write_record(tmp_path)
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    seen = []

    def _fetch(host, port, token=None, timeout=5.0):
        seen.append(token)
        return _HEALTH

    monkeypatch.setattr(serve, "fetch_details", _fetch)
    code = serve.main(["status", "--state-dir", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 0
    assert seen == [_SENTINEL_TOKEN], "status must authenticate with the token"
    assert "health: ok" in out.out
    assert "auth mode: required" in out.out
    assert "demo mode: off" in out.out
    assert "manifests: ok" in out.out
    assert _SENTINEL_TOKEN not in out.out + out.err


def test_status_fails_when_manifest_invalid(
    monkeypatch, tmp_path, capsys, ours
) -> None:
    _write_record(tmp_path)
    bad = json.loads(json.dumps(_HEALTH))
    bad["manifest"].update(ok=False, new=["widgets.x pi_x: broken"])
    monkeypatch.setattr(serve, "fetch_details", _details(bad))
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert "widgets.x pi_x: broken" in capsys.readouterr().out


def test_status_fails_when_unreachable(monkeypatch, tmp_path, capsys) -> None:
    _write_record(tmp_path)
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: None)
    monkeypatch.setattr(serve, "fetch_details", _details(None))
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert "health: unreachable" in capsys.readouterr().out


def test_status_reports_unauthorized_details(
    monkeypatch, tmp_path, capsys, ours
) -> None:
    _write_record(tmp_path)
    monkeypatch.setattr(serve, "fetch_details", _details(dict(serve.UNAUTHORIZED)))
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "health details: unauthorized" in out
    assert "auth mode" not in out


def test_status_never_sends_token_to_foreign_server(
    monkeypatch, tmp_path, capsys
) -> None:
    """A process that cannot prove the launch nonce never sees the token."""
    _write_record(tmp_path)
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: False)
    sent = []
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: sent.append(token) or _HEALTH,
    )
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert sent == []
    assert "not started by this launcher" in capsys.readouterr().out


def test_status_without_record_does_not_send_token(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    sent = []
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: sent.append(token) or _HEALTH,
    )
    monkeypatch.setattr(serve, "_liveness", lambda host, port, timeout=5.0: True)
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert sent == []
    assert "details not queried" in capsys.readouterr().out


def test_stop_refuses_when_details_unauthorized(
    monkeypatch, tmp_path, capsys, ours
) -> None:
    state = _write_record(tmp_path)
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "fetch_details", _details(dict(serve.UNAUTHORIZED)))
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == []
    assert state.exists()
    assert "refused this shell's credentials" in capsys.readouterr().err


def test_stop_refuses_foreign_server_on_port(monkeypatch, tmp_path, capsys) -> None:
    state = _write_record(tmp_path)
    killed, sent = [], []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: False)
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: sent.append(token) or _HEALTH,
    )
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == [] and sent == []
    assert state.exists()


def test_stop_refuses_when_backend_pid_does_not_match(
    monkeypatch, tmp_path, ours
) -> None:
    _write_record(tmp_path, pid=9999)
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == []


def test_stop_refuses_pid_outside_launcher_tree(monkeypatch, tmp_path, capsys) -> None:
    state = _write_record(tmp_path)
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: True)
    monkeypatch.setattr(serve, "_process_parents", lambda: {4242: 77, 77: 1})
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == []
    assert state.exists()
    assert "process tree" in capsys.readouterr().err


def test_stop_terminates_confirmed_backend(monkeypatch, tmp_path) -> None:
    state = _write_record(tmp_path)
    killed = []
    answers = iter([True, None])
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "_process_parents", lambda: {4242: 1111, 1111: 1})
    monkeypatch.setattr(
        serve, "_verify_instance", lambda h, p, n, timeout=5.0: next(answers, None)
    )
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert killed == [4242]
    assert not state.exists()


def test_stop_fails_and_keeps_record_when_backend_survives(
    monkeypatch, tmp_path, ours, capsys
) -> None:
    """CODE-2: still answering after SIGTERM + timeout is a failure."""
    state = _write_record(tmp_path)
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    monkeypatch.setattr(serve.time, "sleep", lambda _s: None)
    code = serve.main(["stop", "--state-dir", str(tmp_path), "--timeout", "0.2"])
    assert code == 1
    assert killed == [4242]
    assert state.exists()
    assert "still answering" in capsys.readouterr().err


def test_stop_with_unreachable_backend_signals_nothing(monkeypatch, tmp_path) -> None:
    state = _write_record(tmp_path)
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: None)
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert killed == []
    assert not state.exists()


class _Proc:
    pid = 1111

    def poll(self):
        return None


def _start_env(monkeypatch) -> None:
    monkeypatch.setattr(serve.time, "sleep", lambda _s: None)
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    monkeypatch.delenv("PI_WIDGET_BACKEND_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("PI_DEMO_MODE", raising=False)
    monkeypatch.setattr(serve, "_port_in_use", lambda host, port: False)


def test_start_records_server_pid_and_passes_nonce(monkeypatch, tmp_path) -> None:
    spawned = {}

    def _spawn(command, log_path, env):
        spawned["env"] = env
        return _Proc()

    answers = iter([None, True])
    monkeypatch.setattr(serve, "_spawn", _spawn)
    monkeypatch.setattr(
        serve, "_verify_instance", lambda h, p, n, timeout=5.0: next(answers, True)
    )
    monkeypatch.setattr(serve, "_process_parents", lambda: {4242: 1111, 1111: 1})
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    _start_env(monkeypatch)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 0
    record = json.loads((tmp_path / "backend-6120.json").read_text(encoding="utf-8"))
    assert record["pid"] == 4242
    assert record["launcher_pid"] == 1111
    assert record["nonce"] == spawned["env"][operator_config.INSTANCE_NONCE_ENV]
    assert len(record["nonce"]) >= 32
    assert _SENTINEL_TOKEN not in json.dumps(record)


def test_start_refuses_foreign_server_and_kills_own_tree(
    monkeypatch, tmp_path, capsys
) -> None:
    """A port answered by a foreign server never receives the token."""
    sent, killed = [], []
    monkeypatch.setattr(serve, "_spawn", lambda command, log_path, env: _Proc())
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: False)
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: sent.append(token) or _HEALTH,
    )
    monkeypatch.setattr(serve, "_process_parents", lambda: {2222: 1111, 1111: 1})
    monkeypatch.setattr(serve, "_terminate", killed.append)
    _start_env(monkeypatch)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 1
    assert sent == []
    assert set(killed) == {1111, 2222}
    assert not (tmp_path / "backend-6120.json").exists()
    assert "did not prove" in capsys.readouterr().err


def test_start_refuses_reported_pid_outside_launcher_tree(
    monkeypatch, tmp_path
) -> None:
    killed = []
    monkeypatch.setattr(serve, "_spawn", lambda command, log_path, env: _Proc())
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: True)
    monkeypatch.setattr(serve, "_process_parents", lambda: {4242: 77, 1111: 1})
    monkeypatch.setattr(serve, "fetch_details", _details(_HEALTH))
    monkeypatch.setattr(serve, "_terminate", killed.append)
    _start_env(monkeypatch)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 1
    assert 4242 not in killed
    assert not (tmp_path / "backend-6120.json").exists()


def test_start_timeout_kills_the_whole_process_tree(monkeypatch, tmp_path) -> None:
    """CODE-1: the venv redirector's grandchild server is killed too."""
    killed = []
    monkeypatch.setattr(serve, "_spawn", lambda command, log_path, env: _Proc())
    monkeypatch.setattr(serve, "_verify_instance", lambda h, p, n, timeout=5.0: None)
    monkeypatch.setattr(
        serve, "_process_parents", lambda: {2222: 1111, 3333: 2222, 1111: 1, 50: 1}
    )
    monkeypatch.setattr(serve, "_terminate", killed.append)
    _start_env(monkeypatch)
    code = serve.main(["start", "--state-dir", str(tmp_path), "--timeout", "0"])
    assert code == 1
    assert set(killed) == {1111, 2222, 3333}
    assert killed.index(3333) < killed.index(1111), "children before parents"


def test_kill_tree_kills_a_real_grandchild() -> None:
    """Real processes: parent -> grandchild; killing the tree ends both."""
    code = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(c.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
    )
    try:
        grandchild = int(parent.stdout.readline())
        assert serve._in_tree(grandchild, parent.pid, serve._process_parents())
        serve._kill_tree(parent.pid)
        parent.wait(timeout=15)
        deadline = time.monotonic() + 15
        while grandchild in serve._process_parents() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert grandchild not in serve._process_parents()
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.stdout.close()


# ---------------------------------------------------------------------------
# Private state directory and log (SECURITY-1)
# ---------------------------------------------------------------------------


def test_default_state_dir_is_per_user_not_shared_temp(monkeypatch, tmp_path) -> None:
    import tempfile  # pylint: disable=import-outside-toplevel

    path = serve._default_state_dir()
    assert not str(path).startswith(tempfile.gettempdir())
    assert path.name == "openbb-pi-widget-backend"


class _Stat:
    def __init__(self, mode: int, uid: int) -> None:
        self.st_mode = mode
        self.st_uid = uid


@pytest.mark.parametrize(
    ("mode", "uid", "reason"),
    [
        (0o040700, 0, "owner"),  # pre-planted by another user
        (0o040777, 1000, "mode"),  # world-writable
        (0o040750, 1000, "mode"),  # group-readable
        (0o120777, 1000, "symlink"),  # symlink to elsewhere
    ],
)
def test_posix_state_dir_checks_owner_mode_and_symlink(
    monkeypatch, tmp_path, mode, uid, reason
) -> None:
    monkeypatch.setattr(serve, "_IS_POSIX", True)
    monkeypatch.setattr(serve, "_getuid", lambda: 1000)
    monkeypatch.setattr(serve, "_lstat", lambda path: _Stat(mode, uid))
    with pytest.raises(serve.LauncherError, match=reason):
        serve.ensure_private_dir(tmp_path / "state")


def test_posix_state_dir_accepts_private_owned_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(serve, "_IS_POSIX", True)
    monkeypatch.setattr(serve, "_getuid", lambda: 1000)
    monkeypatch.setattr(serve, "_lstat", lambda path: _Stat(0o040700, 1000))
    assert serve.ensure_private_dir(tmp_path / "state") == tmp_path / "state"


def test_start_refuses_pre_planted_state_dir(monkeypatch, tmp_path, capsys) -> None:
    spawned = []
    monkeypatch.setattr(serve, "_IS_POSIX", True)
    monkeypatch.setattr(serve, "_getuid", lambda: 1000)
    monkeypatch.setattr(serve, "_lstat", lambda path: _Stat(0o040777, 0))
    monkeypatch.setattr(serve, "_spawn", lambda *a, **k: spawned.append(a))
    _start_env(monkeypatch)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 2
    assert spawned == []
    assert "refusing state directory" in capsys.readouterr().err


def test_start_refuses_symlinked_log(monkeypatch, tmp_path, capsys) -> None:
    log = tmp_path / "backend-6120.log"
    target = tmp_path / "elsewhere.txt"
    target.write_text("", encoding="utf-8")
    try:
        log.symlink_to(target)
    except OSError:  # Windows without symlink privilege
        real = serve._islink
        monkeypatch.setattr(serve, "_islink", lambda p: Path(p) == log or real(p))
    spawned = []
    monkeypatch.setattr(serve, "_spawn", lambda *a, **k: spawned.append(a))
    _start_env(monkeypatch)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 2
    assert spawned == []
    assert "symlink" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == ""


def test_open_private_refuses_symlink(monkeypatch, tmp_path) -> None:
    path = tmp_path / "backend-6120.json"
    monkeypatch.setattr(serve, "_islink", lambda p: Path(p) == path)
    with pytest.raises(serve.LauncherError, match="symlink"):
        serve._open_private(path, os.O_WRONLY | os.O_CREAT)
    assert not path.exists()


def test_open_private_creates_owner_only_file(tmp_path) -> None:
    path = tmp_path / "f.log"
    fd = serve._open_private(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.close(fd)
    if os.name != "nt":
        assert (path.stat().st_mode & 0o077) == 0


# ---------------------------------------------------------------------------
# Address families (CODE-3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "probe"),
    [
        ("0.0.0.0", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("::", "::1"),
        ("[::1]", "::1"),
        ("::1", "::1"),
        ("127.0.0.1", "127.0.0.1"),
    ],
)
def test_probe_host_is_family_aware(host: str, probe: str) -> None:
    assert serve._probe_host(host) == probe


def _ipv6_listener():
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.bind(("::1", 0))
    except OSError:
        sock.close()
        pytest.skip("cannot bind ::1")
    sock.listen(16)
    return sock


def test_port_in_use_detects_ipv6_listener() -> None:
    sock = _ipv6_listener()
    try:
        port = sock.getsockname()[1]
        assert serve._port_in_use("::1", port) is True
        assert serve._port_in_use("::", port) is True
    finally:
        sock.close()


def test_port_in_use_detects_ipv4_listener_for_dual_stack_bind() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(16)
        port = sock.getsockname()[1]
        assert serve._port_in_use("127.0.0.1", port) is True
        assert serve._port_in_use("::", port) is True
    assert serve._port_in_use("127.0.0.1", port) is False


# ---------------------------------------------------------------------------
# Per-launch instance proof (SECURITY-1)
# ---------------------------------------------------------------------------


def test_instance_proof_is_keyed_hmac() -> None:
    a = operator_config.instance_proof("nonce-a", "challenge-1")
    assert a == operator_config.instance_proof("nonce-a", "challenge-1")
    assert a != operator_config.instance_proof("nonce-b", "challenge-1")
    assert a != operator_config.instance_proof("nonce-a", "challenge-2")
    assert "nonce-a" not in a


_INSTANCE_PROBE = """
from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import _app, operator_config
import os
print(operator_config.INSTANCE_NONCE_ENV in os.environ)
c = TestClient(_app.app)
r = c.get("/health/instance", headers={operator_config.CHALLENGE_HEADER: "c" * 32})
print(r.status_code, r.json().get("proof") == operator_config.instance_proof("N" * 40, "c" * 32))
print(c.get("/health/instance").status_code)
"""


def test_backend_proves_launch_nonce_without_revealing_it() -> None:
    result = _run_backend_snippet(
        _INSTANCE_PROBE,
        {
            "PI_WIDGET_BACKEND_AUTH_MODE": "loopback-dev",
            "PI_WIDGET_BACKEND_INSTANCE_NONCE": "N" * 40,
        },
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "False", "nonce must be removed from the environment"
    assert lines[1] == "200 True"
    assert lines[2] == "404"
    assert "N" * 40 not in result.stdout


def test_backend_without_nonce_has_no_instance_proof() -> None:
    client = TestClient(app)
    resp = client.get(
        "/health/instance", headers={operator_config.CHALLENGE_HEADER: "c" * 32}
    )
    assert resp.status_code == 404


def test_verify_instance_against_real_backend(monkeypatch) -> None:
    """Real uvicorn on 127.0.0.1 with a nonce: right nonce passes, wrong fails."""
    import uvicorn  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(backend_app, "_INSTANCE_NONCE", "R" * 40)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert serve._verify_instance("127.0.0.1", port, "R" * 40) is True
        assert serve._verify_instance("127.0.0.1", port, "W" * 40) is False
    finally:
        server.should_exit = True
        thread.join(timeout=15)
    assert serve._verify_instance("127.0.0.1", port, "R" * 40, timeout=1) is None


# ---------------------------------------------------------------------------
# Operator doc is portable
# ---------------------------------------------------------------------------


def test_operator_doc_has_no_operator_specific_paths() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert not re.search(r"\b[A-Za-z]:[\\/]", text), "drive-letter path in doc"
    assert not re.search(r"/(home|Users)/[A-Za-z]", text), "home path in doc"
    for needle in (
        "PI_WIDGET_BACKEND_ALLOWED_ORIGINS",
        "PI_WIDGET_BACKEND_AUTH_MODE",
        "PI_WIDGET_BACKEND_TOKEN",
        "PI_DEMO_MODE",
        "/health",
        "validate_portfolio_workspace_manifests.py",
        "openbb_portfolio_intel.widget_backend.serve",
    ):
        assert needle in text, needle
