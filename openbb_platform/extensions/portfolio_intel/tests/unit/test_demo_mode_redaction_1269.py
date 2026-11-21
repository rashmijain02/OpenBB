"""Explicit demo mode and redaction for the widget backend (#1269, plan 6.3/6.6).

Demo mode (``PI_DEMO_MODE``):

- ``off`` (opt-in): synthetic data is never served as a silent fallback.
  When no provider answers, the widget is ``unavailable`` with a reason and
  no sample values. Selecting the demo account/basket is an explicit choice
  and still shows the labelled synthetic book.
- ``fallback`` (default, lead decision round 3): the stub answers when no
  provider does, labelled ``demo``.
- ``only``: onboarding/tests; providers are skipped and every widget serves
  its labelled demo data.

Redaction: no response body, header, log line or figure text echoes an
account identifier, a credential, or an operator path. Synthetic sentinels
stand in for all three.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend import widgets_endpoints
from openbb_portfolio_intel.widget_backend.contracts import collect_response_issues
from openbb_portfolio_intel.widget_backend.main import app

_UNIT = Path(__file__).resolve().parent
_BACKEND = _UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
_WIDGETS: dict[str, Any] = json.loads(
    (_BACKEND / "widgets.json").read_text(encoding="utf-8")
)
_CLIENT = TestClient(app, raise_server_exceptions=False)
#: #1271 shape debt: no valid body shape yet, so no body state to check.
_SHAPE_DEBT = {"tt_segment_movers", "tt_scan_table", "tt_simulate_result"}


@pytest.fixture(autouse=True)
def _stub_tiers_only() -> Iterator[None]:
    """Clear the provider dispatch table so no provider answers."""
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


def _defaults(widget: dict[str, Any], **overrides: str) -> dict[str, str]:
    params = {
        p["paramName"]: p["value"]
        for p in widget.get("params", [])
        if p.get("value") not in (None, "")
    }
    for name, value in overrides.items():
        if name in params:
            params[name] = value
    return params


def _call(widget_id: str, **overrides: str) -> Any:
    widget = _WIDGETS[widget_id]
    return _CLIENT.get(
        "/" + widget["endpoint"].lstrip("/"), params=_defaults(widget, **overrides)
    )


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------


def test_demo_mode_defaults_to_fallback_and_rejects_unknown_values(
    monkeypatch,
) -> None:
    """The default is the labelled ``fallback``; ``off``/``only`` opt in; typos fail."""
    from openbb_portfolio_intel.widget_backend import provenance as pv

    monkeypatch.delenv("PI_DEMO_MODE", raising=False)
    assert pv.demo_mode() == "fallback"
    monkeypatch.setenv("PI_DEMO_MODE", "")
    assert pv.demo_mode() == "fallback"
    for value in ("fallback", "only", "OFF"):
        monkeypatch.setenv("PI_DEMO_MODE", value)
        assert pv.demo_mode() == value.lower()
    monkeypatch.setenv("PI_DEMO_MODE", "sometimes")
    with pytest.raises(RuntimeError):
        pv.demo_mode()


@pytest.mark.parametrize(
    ("widget_id", "kind"),
    [
        ("pi_equity_key_stats", "table"),
        ("pi_equity_profile_header", "markdown"),
        ("pi_equity_price_history", "chart"),
        ("pi_brinson_attribution", "chart"),
        ("pi_whatif_card", "table"),
    ],
)
def test_off_mode_serves_unavailable_not_sample_values(
    monkeypatch, widget_id: str, kind: str
) -> None:
    """With demo off and no provider, the widget says unavailable, no samples."""
    monkeypatch.setenv("PI_DEMO_MODE", "off")
    response = _call(widget_id)
    assert response.status_code == 200
    assert response.headers["x-pi-data-state"] == "unavailable"
    assert not collect_response_issues(
        widget_id, _WIDGETS[widget_id], 200, response.text
    )
    body = response.json()
    if kind == "table":
        assert len(body) == 1 and body[0]["data_state"] == "unavailable"
        assert "PI_DEMO_MODE" in body[0]["message"]
        assert set(body[0]) == {"message", "data_state", "data_source", "data_as_of"}
    elif kind == "markdown":
        assert body.startswith("**Unavailable:**")
        assert "$228.14" not in body  # the stub's sample price
    else:
        assert body["data"] == []
        assert body["layout"]["meta"]["state"] == "unavailable"
        raw = _CLIENT.get(
            "/" + _WIDGETS[widget_id]["endpoint"].lstrip("/"),
            params={**_defaults(_WIDGETS[widget_id]), "raw": "true"},
        ).json()
        assert [row["data_state"] for row in raw] == ["unavailable"]


def test_off_mode_still_serves_the_explicitly_selected_demo_account(
    monkeypatch,
) -> None:
    """Choosing ``account_id=demo`` is an explicit selection of the demo book."""
    monkeypatch.setenv("PI_DEMO_MODE", "off")
    response = _call("pi_risk_dashboard", account_id="demo")
    assert response.headers["x-pi-data-state"] == "demo"
    assert response.json()[-1]["value"].startswith("Demo:")
    figure = _call("pi_xray_sector", account_id="demo").json()
    assert figure["layout"]["meta"]["state"] == "demo"


def test_fallback_mode_labels_the_stub_demo(monkeypatch) -> None:
    """``fallback`` serves the stub when no provider answers, labelled demo."""
    monkeypatch.setenv("PI_DEMO_MODE", "fallback")
    response = _call("pi_equity_key_stats")
    assert response.headers["x-pi-data-state"] == "demo"
    assert {row["data_state"] for row in response.json()} == {"demo"}


def test_only_mode_skips_providers_and_serves_demo(monkeypatch) -> None:
    """``only`` never calls a provider tier, even a registered one."""
    calls: list[str] = []

    def _tier(**_kwargs: Any) -> list[dict[str, Any]]:
        calls.append("called")
        return [{"date": "2020-08-31", "numerator": 4, "denominator": 1}]

    _TIER_CALLS[("equity/stock-splits", "fmp_cached")] = _tier
    monkeypatch.setenv("PI_DEMO_MODE", "only")
    response = _call("pi_stock_splits")
    assert calls == []
    assert response.headers["x-pi-data-state"] == "demo"
    monkeypatch.setenv("PI_DEMO_MODE", "off")
    assert _call("pi_stock_splits").headers["x-pi-data-state"] == "cached"
    assert calls == ["called"]


@pytest.mark.parametrize("mode", ["off", "fallback", "only"])
def test_every_widget_keeps_a_valid_state_in_every_demo_mode(
    monkeypatch, mode: str
) -> None:
    """All 61 widgets pass the response contract in each demo mode."""
    monkeypatch.setenv("PI_DEMO_MODE", mode)
    failures = {}
    for widget_id, widget in _WIDGETS.items():
        if widget_id in _SHAPE_DEBT:
            continue
        response = _call(widget_id)
        issues = collect_response_issues(
            widget_id, widget, response.status_code, response.text
        )
        if issues or not response.headers.get("x-pi-data-state"):
            failures[widget_id] = [i.code for i in issues] or ["no state header"]
    assert not failures


# ---------------------------------------------------------------------------
# Redaction (plan 6.6)
# ---------------------------------------------------------------------------

_ACCOUNT = "ACCT-SENTINEL-4417"
_CREDENTIAL = "CRED-SENTINEL-9a8b7c"
_HOME_MARK = "OPERATOR-SENTINEL-HOME"
_CLIENT_LOGGERS = ("httpx", "httpcore")
#: Known exception, raised with the lead (#1269): TechTrade's snapshot store
#: logs the absolute SQLite fallback path once per store lookup, and its own
#: tests (``test_snapshot_store.py``) require that absolute path. It is
#: checked separately below so any *other* path leak still fails.
_STORE_LOGGER = "openbb_techtrade.snapshot.store"


@pytest.mark.parametrize("mode", ["off", "fallback"])
def test_no_response_header_or_log_echoes_identifiers_secrets_or_paths(
    monkeypatch, tmp_path: Path, caplog, mode: str
) -> None:
    """Sentinel account, credential and home path never leave the backend."""
    home = tmp_path / _HOME_MARK
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    for name in ("FMP_API_KEY", "FMP_CACHED_API_KEY", "PI_WIDGET_BACKEND_TOKEN"):
        monkeypatch.setenv(name, _CREDENTIAL)
    monkeypatch.setenv("PI_DEMO_MODE", mode)
    monkeypatch.setenv("PI_ALLOW_CROSS_USER_BASKET", "false")
    # Force a fresh snapshot-store lookup so its fallback path is logged now.
    monkeypatch.setattr(widgets_endpoints, "_SNAPSHOT_STORE_CACHE", None)
    seen: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for widget_id in _WIDGETS:
            response = _call(widget_id, account_id=_ACCOUNT, basket_id=_ACCOUNT)
            seen.append(response.text)
            seen.extend(f"{k}: {v}" for k, v in response.headers.items())
        # The test client's own request log (httpx/httpcore) echoes the URL
        # the test sent; every other logger is backend or dependency code.
        backend = [r for r in caplog.records if not r.name.startswith(_CLIENT_LOGGERS)]
        seen.extend(r.getMessage() for r in backend if r.name != _STORE_LOGGER)
        store_lines = [r.getMessage() for r in backend if r.name == _STORE_LOGGER]
    text = "\n".join(seen)
    for sentinel in (_ACCOUNT, _CREDENTIAL, _HOME_MARK, str(home)):
        assert sentinel not in text, f"leaked {sentinel!r}"
    assert backend, "the scan must observe the backend's logs"
    for line in store_lines:  # the documented exception carries no secrets
        assert _ACCOUNT not in line and _CREDENTIAL not in line


# ---------------------------------------------------------------------------
# Review fixes: basket errors, paper-status account, startup validation
# ---------------------------------------------------------------------------

_SNAPSHOT_ID = "SNAP-SENTINEL-0042"


class _SentinelStore:
    """Synthetic positions store whose only snapshot has cash rows only."""

    def latest_snapshot(self, user_id: str) -> dict[str, str] | None:
        return {"snapshot_id": _SNAPSHOT_ID} if user_id == _ACCOUNT else None

    def positions_for(self, snapshot_id: str) -> list[dict[str, Any]]:
        return [{"symbol": "SPAXX", "percent_of_account": 100.0}]


def _basket_leaks(monkeypatch, caplog, url: str, status: int) -> str:
    from openbb_portfolio_intel import basket_resolver

    monkeypatch.setenv("PI_ALLOW_CROSS_USER_BASKET", "true")
    real = basket_resolver.resolve_basket
    monkeypatch.setattr(
        widgets_endpoints,
        "resolve_basket",
        lambda basket_id: real(basket_id, store=_SentinelStore()),
    )
    with caplog.at_level(logging.DEBUG):
        response = _CLIENT.get(url)
    assert response.status_code == status
    logs = [r.getMessage() for r in caplog.records if not r.name.startswith("http")]
    return "\n".join(
        [response.text, *(f"{k}: {v}" for k, v in response.headers.items()), *logs]
    )


@pytest.mark.parametrize(
    "basket_id",
    [_ACCOUNT, "OTHER-SENTINEL-9"],  # snapshot without positions; no snapshot
)
def test_basket_404_returns_a_fixed_message(monkeypatch, caplog, basket_id) -> None:
    """Neither the basket/user id nor an internal snapshot id is echoed."""
    url = f"/pi/equity/basket-analyst-consensus?basket_id={basket_id}"
    text = _basket_leaks(monkeypatch, caplog, url, 404)
    for sentinel in (basket_id, _SNAPSHOT_ID):
        assert sentinel not in text, f"leaked {sentinel!r}"
    assert "basket_not_found" in text


def test_basket_400_does_not_echo_the_rejected_id(monkeypatch, caplog) -> None:
    """A malformed basket id is rejected without being reflected."""
    bad = "BAD SENTINEL<x>"
    url = f"/pi/equity/basket-analyst-consensus?basket_id={bad}"
    text = _basket_leaks(monkeypatch, caplog, url, 400)
    assert "SENTINEL" not in text


def test_paper_status_markdown_withholds_the_engine_account_id(monkeypatch) -> None:
    """The paper engine's account id never reaches the Markdown widget."""
    import types

    from openbb_techtrade.execution import paper_engine

    account = types.SimpleNamespace(
        account_id=_ACCOUNT, starting_cash=100000, cash=100000, realized_pl=0
    )
    engine = types.SimpleNamespace(
        is_initialized=lambda: True,
        get_account=lambda: account,
        get_positions=lambda: [],
        get_orders=lambda status=None: [],
        close=lambda: None,
    )
    monkeypatch.setenv("PI_PAPER_ENGINE", "mysql")
    monkeypatch.setattr(paper_engine, "get_default_engine", lambda **_k: engine)
    body = _CLIENT.get("/tt/execute/paper-status/markdown").json()
    assert "Paper Trading Engine" in body and "Starting cash" in body
    assert _ACCOUNT not in body
    assert "identifier withheld" in body


def test_invalid_demo_mode_fails_at_app_creation(tmp_path: Path) -> None:
    """Importing the backend with a bad ``PI_DEMO_MODE`` fails fast."""
    import subprocess
    import sys

    env = {
        **os.environ,
        "PI_DEMO_MODE": "sometimes",
        "PI_WIDGET_BACKEND_AUTH_MODE": "loopback-dev",
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
    }
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, fixed code
        [
            sys.executable,
            "-c",
            "import openbb_portfolio_intel.widget_backend.main",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert completed.returncode != 0
    assert "PI_DEMO_MODE" in completed.stderr


def test_invalid_demo_mode_fails_at_lifespan_startup(monkeypatch) -> None:
    """Server startup re-validates the mode before serving any request."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_SKIP_WARMUP", "1")
    monkeypatch.setenv("PI_DEMO_MODE", "sometimes")
    with pytest.raises(RuntimeError, match="PI_DEMO_MODE"):
        with TestClient(app):
            pass
    monkeypatch.setenv("PI_DEMO_MODE", "fallback")
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
