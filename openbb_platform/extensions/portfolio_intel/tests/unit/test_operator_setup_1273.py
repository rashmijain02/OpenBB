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
# Launcher status / stop
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


def test_status_reports_health_modes_manifest_without_token(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    seen = []

    def _details(host, port, token=None, timeout=5.0):
        seen.append(token)
        return _HEALTH

    monkeypatch.setattr(serve, "fetch_details", _details)
    code = serve.main(["status", "--state-dir", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 0
    assert seen == [_SENTINEL_TOKEN], "status must authenticate with the token"
    assert "health: ok" in out.out
    assert "auth mode: required" in out.out
    assert "demo mode: off" in out.out
    assert "manifests: ok" in out.out
    assert _SENTINEL_TOKEN not in out.out + out.err


def test_status_fails_when_manifest_invalid(monkeypatch, tmp_path, capsys) -> None:
    bad = json.loads(json.dumps(_HEALTH))
    bad["manifest"].update(ok=False, new=["widgets.x pi_x: broken"])
    monkeypatch.setattr(
        serve, "fetch_details", lambda host, port, token=None, timeout=5.0: bad
    )
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert "widgets.x pi_x: broken" in capsys.readouterr().out


def test_status_fails_when_unreachable(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        serve, "fetch_details", lambda host, port, token=None, timeout=5.0: None
    )
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    assert "health: unreachable" in capsys.readouterr().out


def test_status_reports_unauthorized_details(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: dict(serve.UNAUTHORIZED),
    )
    assert serve.main(["status", "--state-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "health details: unauthorized" in out
    assert "auth mode" not in out


def test_stop_refuses_when_details_unauthorized(monkeypatch, tmp_path, capsys) -> None:
    state = tmp_path / "backend-6120.json"
    state.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 6120}), encoding="utf-8"
    )
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: dict(serve.UNAUTHORIZED),
    )
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == []
    assert state.exists()
    assert "refused this shell's credentials" in capsys.readouterr().err


def test_stop_refuses_when_backend_pid_does_not_match(monkeypatch, tmp_path) -> None:
    (tmp_path / "backend-6120.json").write_text(
        json.dumps({"pid": 9999, "host": "127.0.0.1", "port": 6120}), encoding="utf-8"
    )
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(
        serve, "fetch_details", lambda host, port, token=None, timeout=5.0: _HEALTH
    )
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 1
    assert killed == []


def test_stop_terminates_confirmed_backend(monkeypatch, tmp_path) -> None:
    state = tmp_path / "backend-6120.json"
    state.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 6120}), encoding="utf-8"
    )
    killed = []
    answers = iter([_HEALTH, None])
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: next(answers, None),
    )
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert killed == [4242]
    assert not state.exists()


def test_stop_with_unreachable_backend_signals_nothing(monkeypatch, tmp_path) -> None:
    state = tmp_path / "backend-6120.json"
    state.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 6120}), encoding="utf-8"
    )
    killed = []
    monkeypatch.setattr(serve, "_terminate", killed.append)
    monkeypatch.setattr(
        serve, "fetch_details", lambda host, port, token=None, timeout=5.0: None
    )
    assert serve.main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert killed == []
    assert not state.exists()


def test_start_records_server_pid_reported_by_health(monkeypatch, tmp_path) -> None:
    class _Proc:
        pid = 1111

        def poll(self):
            return None

    answers = iter([None, _HEALTH])
    monkeypatch.setattr(serve, "_spawn", lambda *a, **k: _Proc())
    monkeypatch.setattr(
        serve,
        "fetch_details",
        lambda host, port, token=None, timeout=5.0: next(answers, _HEALTH),
    )
    monkeypatch.setattr(serve.time, "sleep", lambda _s: None)
    monkeypatch.setenv("PI_WIDGET_BACKEND_AUTH_MODE", "required")
    monkeypatch.setenv("PI_WIDGET_BACKEND_TOKEN", _SENTINEL_TOKEN)
    monkeypatch.delenv("PI_WIDGET_BACKEND_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("PI_DEMO_MODE", raising=False)
    monkeypatch.setattr(serve, "_port_in_use", lambda host, port: False)
    assert serve.main(["start", "--state-dir", str(tmp_path)]) == 0
    record = json.loads((tmp_path / "backend-6120.json").read_text(encoding="utf-8"))
    assert record["pid"] == 4242
    assert record["launcher_pid"] == 1111
    assert _SENTINEL_TOKEN not in json.dumps(record)


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
