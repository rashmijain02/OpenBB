"""One provenance and provider-state model across every widget endpoint (#1269).

States: live, cached, demo, stale, partial, unavailable, forbidden. Each
widget type carries the state in a shape Workspace accepts:

- chart: ``layout.meta`` (state, source, asOf, reason) plus an annotation for
  every state but live; ``raw=true`` rows carry the table columns below;
- table: ``data_state`` / ``data_source`` / ``data_as_of`` string columns on
  every row (type-stable; Workspace shows every row key as a column);
- metric: a trailing ``Data State`` card ``"<State>: <reason>"``;
- markdown: a closing ``**Data state:** <State>`` line.

Headers ``X-PI-Data-State`` / ``X-PI-Data-Source`` come from the same
per-request record, never from the shared tier ledger. Auth denials stay
HTTP 401/403 with state ``forbidden`` and no data.

Every test clears the provider tier table, so no provider or network is used.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
_CLIENT = TestClient(app)
_STATES = {"live", "cached", "demo", "stale", "partial", "unavailable"}
_ROW_FIELDS = ("data_state", "data_source", "data_as_of")
_PRICE_URL = "/pi/equity/price-history?symbol={sym}&chart_type=line&range=6M"


@pytest.fixture(autouse=True)
def _stub_tiers_only() -> Iterator[None]:
    """Clear the provider dispatch table so every request uses the stub."""
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


def _codes(widget: dict[str, Any], body: Any, status: int = 200) -> set[str]:
    text = json.dumps(body)
    return {i.code for i in collect_response_issues("w", widget, status, text)}


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_state_model_has_exactly_the_seven_states() -> None:
    """One enum names every state; forbidden is never a body state."""
    from openbb_portfolio_intel.widget_backend import provenance as pv

    assert {s.value for s in pv.DataState} == _STATES | {"forbidden"}
    assert pv.BODY_STATES == _STATES


def test_provenance_renders_one_record_per_widget_type() -> None:
    """The same record renders as chart meta, row columns, card and Markdown."""
    from openbb_portfolio_intel.widget_backend import provenance as pv

    record = pv.Provenance(pv.DataState.STALE, "eod-snapshot", "old", "2026-09-11")
    assert record.meta() == {
        "state": "stale",
        "source": "eod-snapshot",
        "asOf": "2026-09-11",
        "reason": "old",
    }
    assert pv.Provenance.from_meta(record.meta()) == record
    assert record.row_fields() == {
        "data_state": "stale",
        "data_source": "eod-snapshot",
        "data_as_of": "2026-09-11",
    }
    assert record.metric_card() == {"label": "Data State", "value": "Stale: old"}
    assert "**Data state:** Stale" in record.markdown()
    unknown = pv.Provenance(pv.DataState.LIVE, "fmp_cached", "served")
    assert unknown.row_fields()["data_as_of"] == "unknown"
    assert "as of unknown" in unknown.markdown()


def test_tier_classification_is_shared() -> None:
    """stub -> demo, snapshot tier -> cached, any other tier -> live."""
    from openbb_portfolio_intel.widget_backend import provenance as pv

    assert pv.state_for_tier("stub") is pv.DataState.DEMO
    assert pv.state_for_tier("yfinance-snapshot") is pv.DataState.CACHED
    # Lead decision (#1269): fmp_cached serves persisted provider responses
    # whose age is not observable, so it is "cached"; only real provider
    # calls are "live".
    assert pv.state_for_tier("fmp_cached") is pv.DataState.CACHED
    assert pv.state_for_tier("fmp") is pv.DataState.LIVE
    assert pv.state_for_tier("sec") is pv.DataState.LIVE


def test_resolve_never_defaults_silently() -> None:
    """An endpoint that recorded nothing is a programming error, not a state."""
    from openbb_portfolio_intel.widget_backend import provenance as pv

    with pytest.raises(RuntimeError):
        pv.resolve(pv.RequestProvenance())


# ---------------------------------------------------------------------------
# Contract checker: a widget without a valid state fails
# ---------------------------------------------------------------------------

_TABLE = {"type": "table", "data": {"table": {"columnsDefs": [{"field": "a"}]}}}
_ROW_OK = {"a": 1, "data_state": "demo", "data_source": "stub", "data_as_of": "x"}
_META_OK = {"state": "live", "source": "fmp_cached", "asOf": "unknown", "reason": "r"}
_NOTE = {"text": "Demo data", "xref": "paper", "yref": "paper", "x": 0, "y": 0}


@pytest.mark.parametrize(
    ("widget", "body", "code"),
    [
        (_TABLE, [{"a": 1}], "response.state.table"),
        (_TABLE, [{**_ROW_OK, "data_state": "fake"}], "response.state.table"),
        (_TABLE, [_ROW_OK, {"a": 2}], "response.state.table"),
        ({"type": "chart"}, {"data": []}, "response.state.chart"),
        (
            {"type": "chart"},
            {"data": [], "layout": {"meta": {**_META_OK, "state": "bogus"}}},
            "response.state.chart",
        ),
        (
            {"type": "chart"},
            {"data": [], "layout": {"meta": {**_META_OK, "state": "demo"}}},
            "response.state.annotation",
        ),
        ({"type": "metric"}, [{"label": "x", "value": 1}], "response.state.metric"),
        (
            {"type": "metric"},
            [{"label": "Data State", "value": "Fine"}],
            "response.state.metric",
        ),
        ({"type": "markdown"}, "## Some text", "response.state.markdown"),
    ],
)
def test_response_checker_rejects_missing_or_invalid_state(
    widget: dict[str, Any], body: Any, code: str
) -> None:
    """Every widget type fails the contract without a valid data state."""
    assert code in _codes(widget, body)


def test_response_checker_accepts_valid_states() -> None:
    """Valid per-type state carriers raise no issue."""
    assert not _codes(_TABLE, [_ROW_OK])
    assert not _codes({"type": "chart"}, {"data": [], "layout": {"meta": _META_OK}})
    demo = {"data": [], "layout": {"meta": {**_META_OK, "state": "demo"}}}
    demo["layout"]["annotations"] = [_NOTE]
    assert not _codes({"type": "chart"}, demo)
    card = [{"label": "x", "value": 1}, {"label": "Data State", "value": "Demo: a"}]
    assert not _codes({"type": "metric"}, card)
    assert not _codes({"type": "markdown"}, "x\n\n**Data state:** Live - y.")


# ---------------------------------------------------------------------------
# Per-type representation, served by the real app
# ---------------------------------------------------------------------------


def _assert_rows_state(rows: list[dict[str, Any]], state: str, source: str) -> None:
    assert rows, "no rows"
    for row in rows:
        assert row["data_state"] == state
        assert row["data_source"] == source
        assert isinstance(row["data_as_of"], str)


def test_demo_table_rows_carry_type_stable_state_columns() -> None:
    """Stub-served table rows say demo/stub on every row, as strings."""
    rows = _CLIENT.get("/pi/equity/key-stats?symbol=AAPL").json()
    _assert_rows_state(rows, "demo", "stub")
    assert rows[0]["data_as_of"] == "unknown"


def test_fmp_cached_rows_are_cached_with_unknown_age() -> None:
    """fmp_cached rows are ``cached``, name the tier, and claim no as-of."""
    _TIER_CALLS[("equity/stock-splits", "fmp_cached")] = lambda **_k: [
        {"date": "2020-08-31", "numerator": 4, "denominator": 1, "ratio": "4:1"}
    ]
    response = _CLIENT.get("/pi/equity/stock-splits?symbol=AAPL")
    _assert_rows_state(response.json(), "cached", "fmp_cached")
    assert response.json()[0]["data_as_of"] == "unknown"
    assert response.headers["x-pi-data-state"] == "cached"
    assert response.headers["x-pi-data-source"] == "fmp_cached"
    assert response.headers["x-pi-data-as-of"] == "unknown"


def test_real_provider_tier_rows_are_live() -> None:
    """A provider tier that calls the provider (``fmp``) is ``live``."""
    _TIER_CALLS[("equity/stock-splits", "fmp")] = lambda **_k: [
        {"date": "2020-08-31", "numerator": 4, "denominator": 1, "ratio": "4:1"}
    ]
    response = _CLIENT.get("/pi/equity/stock-splits?symbol=AAPL")
    _assert_rows_state(response.json(), "live", "fmp")
    assert response.headers["x-pi-data-state"] == "live"


def test_local_backend_state_is_stamped_with_a_real_utc_time() -> None:
    """Backend-local state carries the UTC ISO-8601 time it was read."""
    from datetime import datetime, timedelta, timezone

    response = _CLIENT.get("/pi/context/symbol?symbol=AAPL")
    as_of = response.headers["x-pi-data-as-of"]
    stamped = datetime.fromisoformat(as_of)
    assert stamped.tzinfo is not None and stamped.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - stamped) < timedelta(minutes=5)
    assert f"as of {as_of}." in response.json()


def test_raw_chart_rows_keep_their_values_and_add_state_columns() -> None:
    """``raw=true`` rows are unchanged plus three string provenance columns."""
    figure = _CLIENT.get(_PRICE_URL.format(sym="AAPL")).json()
    rows = _CLIENT.get(_PRICE_URL.format(sym="AAPL") + "&raw=true").json()
    _assert_rows_state(rows, "demo", "stub")
    assert [row["close"] for row in rows] == figure["data"][0]["y"]
    assert {key for row in rows for key in row} == {"date", "close", *_ROW_FIELDS}


def test_chart_meta_carries_the_full_record() -> None:
    """Chart meta has state, source, asOf and reason; demo has an annotation."""
    figure = _CLIENT.get("/pi/attribution").json()
    meta = figure["layout"]["meta"]
    assert meta["state"] == "demo" and meta["source"] == "stub"
    assert meta["asOf"] == "unknown" and meta["reason"]
    assert figure["layout"]["annotations"]


def test_metric_and_markdown_state_match_the_header() -> None:
    """Metric card and Markdown line state the same state as the header."""
    metric = _CLIENT.get("/pi/risk/dashboard?account_id=demo")
    assert metric.json()[-1] == {
        "label": "Data State",
        "value": "Demo: synthetic sample book",
    }
    assert metric.headers["x-pi-data-state"] == "demo"
    markdown = _CLIENT.get("/pi/equity/header?symbol=AAPL")
    assert "**Data state:** Demo" in markdown.json()
    assert markdown.headers["x-pi-data-state"] == "demo"


_UNWIRED = {
    "pi_xray_sector": "/pi/xray/sector",
    "pi_xray_country": "/pi/xray/country",
    "pi_lookthrough_top25": "/pi/lookthrough/top25",
    "pi_concentration_gauge": "/pi/concentration",
    "pi_event_calendar": "/pi/events/calendar",
    "pi_smart_money_ribbon": "/pi/smart-money/ribbon",
    "pi_risk_dashboard": "/pi/risk/dashboard",
    "pi_risk_vol_chart": "/pi/risk/vol",
    "pi_paper_blotter": "/pi/paper/blotter",
    "pi_paper_performance": "/pi/paper/performance",
    "pi_paper_perf_kpis": "/pi/paper/perf-kpis",
    "pi_news_ribbon": "/pi/news",
    "pi_sentiment_gauge": "/pi/sentiment",
    "pi_alerts_panel": "/pi/alerts",
    "pi_book_context": "/pi/context/book",
}


@pytest.mark.parametrize("widget_id", sorted(_UNWIRED))
def test_unwired_account_is_unavailable_for_every_widget_type(widget_id: str) -> None:
    """A non-demo account is ``unavailable`` in body and header, never demo."""
    response = _CLIENT.get(f"{_UNWIRED[widget_id]}?account_id=NOT_WIRED")
    assert response.status_code == 200
    assert response.headers["x-pi-data-state"] == "unavailable"
    assert not collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )
    body = response.json()
    kind = _WIDGETS[widget_id]["type"]
    if kind == "table":
        assert {row["data_state"] for row in body} == {"unavailable"}
    elif kind == "chart":
        assert body["layout"]["meta"]["state"] == "unavailable"
    elif kind == "metric":
        assert body[-1]["value"].startswith("Unavailable:")
    else:
        assert "**Data state:** Unavailable" in body


# ---------------------------------------------------------------------------
# X-PI-Data-Source is per request (#1268 review)
# ---------------------------------------------------------------------------


def test_header_matches_meta_source_under_concurrent_requests(monkeypatch) -> None:
    """A concurrent live request cannot overwrite a demo request's header.

    Request A (AAPL) exhausts the chain, records ``stub``, then blocks in its
    stub body until request B (MSFT) has been served live by ``fmp_cached``.
    The old middleware read the shared ledger at response time and so sent
    A's figure (``meta.source == "stub"``) with header ``fmp_cached``.
    """

    def _tier(*, symbol: str, **_kwargs: Any) -> list[dict[str, Any]]:
        if symbol == "MSFT":
            return [{"date": "2026-08-06", "close": 312.41}]
        return []

    _TIER_CALLS[("equity/price-history", "fmp_cached")] = _tier
    a_in_stub = threading.Event()
    b_done = threading.Event()
    real_series = widgets_endpoints._demo_ohlc_series

    def _slow_series(symbol: str, days: int = 126) -> list[dict]:
        a_in_stub.set()  # A has already recorded "stub" for this path
        assert b_done.wait(timeout=30), "request B never finished"
        return real_series(symbol, days=days)

    monkeypatch.setattr(widgets_endpoints, "_demo_ohlc_series", _slow_series)
    results: dict[str, Any] = {}

    def _get_a() -> None:
        results["a"] = _CLIENT.get(_PRICE_URL.format(sym="AAPL"))

    thread = threading.Thread(target=_get_a)
    thread.start()
    try:
        assert a_in_stub.wait(timeout=30), "request A never reached its stub"
        results["b"] = _CLIENT.get(_PRICE_URL.format(sym="MSFT"))
    finally:
        b_done.set()
        thread.join(timeout=60)
    a, b = results["a"], results["b"]
    assert b.json()["layout"]["meta"]["source"] == "fmp_cached"
    assert b.headers["x-pi-data-source"] == "fmp_cached"
    assert a.json()["layout"]["meta"]["source"] == "stub"
    assert a.headers["x-pi-data-source"] == "stub"
    assert a.headers["x-pi-data-state"] == a.json()["layout"]["meta"]["state"]


# ---------------------------------------------------------------------------
# Forbidden: auth and permission denials stay errors, never demo data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/pi/equity/key-stats?symbol=AAPL",
        "/pi/xray/sector?account_id=demo",
        "/pi/risk/dashboard?account_id=demo",
        "/pi/equity/header?symbol=AAPL",
        "/tt/audit/journal?symbol=AAPL",
    ],
)
def test_auth_denial_is_401_forbidden_without_data(url: str) -> None:
    """A missing bearer token is a 401 with state forbidden and no rows."""
    from openbb_portfolio_intel.widget_backend import _shared

    with patch.object(_shared, "_AUTH_MODE", "required"), patch.object(
        _shared, "_AUTH_TOKEN", "t0ken"
    ):
        response = _CLIENT.get(url)
    assert response.status_code == 401
    assert response.headers["x-pi-data-state"] == "forbidden"
    assert "x-pi-data-source" not in response.headers
    assert set(response.json()) == {"detail"}


def test_permission_denial_is_403_forbidden_without_data(monkeypatch) -> None:
    """A non-demo basket without the operator opt-in is 403, not demo rows."""
    monkeypatch.delenv("PI_ALLOW_CROSS_USER_BASKET", raising=False)
    response = _CLIENT.get("/pi/equity/basket-analyst-consensus?basket_id=other")
    assert response.status_code == 403
    assert response.headers["x-pi-data-state"] == "forbidden"
    assert "AAPL" not in response.text


# ---------------------------------------------------------------------------
# Pie hover: stored weight, and partial when weights are unnormalised
# ---------------------------------------------------------------------------


def test_pie_hover_shows_the_stored_weight() -> None:
    """Weight pies show each stored weight, not only the share of the plot."""
    for url in ("/pi/xray/sector", "/pi/xray/country"):
        trace = _CLIENT.get(f"{url}?account_id=demo").json()["data"][0]
        assert "%{value" in trace["hovertemplate"], url
        assert "%{percent}" in trace["hovertemplate"], url


def test_unnormalised_weights_are_partial_in_figure_raw_and_header() -> None:
    """Weights summing to 90% of the book are ``partial`` everywhere."""
    _TIER_CALLS[("xray/country", "fmp_cached")] = lambda **_k: [
        {"country": "United States", "weight": 0.6},
        {"country": "Japan", "weight": 0.3},
    ]
    response = _CLIENT.get("/pi/xray/country?account_id=demo")
    meta = response.json()["layout"]["meta"]
    assert meta["state"] == "partial"
    assert meta["source"] == "fmp_cached"
    assert "90.0%" in meta["reason"]
    assert response.headers["x-pi-data-state"] == "partial"
    raw = _CLIENT.get("/pi/xray/country?account_id=demo&raw=true").json()
    assert {row["data_state"] for row in raw} == {"partial"}
    assert [row["weight"] for row in raw] == [0.6, 0.3]


# ---------------------------------------------------------------------------
# Stale / cached from snapshot metadata; health and provenance widgets
# ---------------------------------------------------------------------------


def test_snapshot_state_comes_from_snapshot_metadata() -> None:
    """No snapshot -> unavailable; stale/partial/fresh follow the metadata."""
    snap = widgets_endpoints._snapshot_provenance
    base = {"as_of_session": "2026-09-11", "badge": "EOD 2026-09-11"}
    assert snap({**base, "as_of_session": None}, False).state.value == "unavailable"
    stale = snap({**base, "is_stale": True, "is_partial": False}, True)
    assert (stale.state.value, stale.as_of) == ("stale", "2026-09-11")
    partial = snap({**base, "is_stale": True, "is_partial": True}, True)
    assert partial.state.value == "partial"
    fresh = snap({**base, "is_stale": False, "is_partial": False}, True)
    assert (fresh.state.value, fresh.source) == ("cached", "eod-snapshot")


def test_empty_snapshot_store_rows_are_unavailable(tmp_path: Path) -> None:
    """The loud-empty snapshot marker row is labelled unavailable."""
    from openbb_techtrade.snapshot.store import SqliteSnapshotStore

    store = SqliteSnapshotStore(tmp_path / "empty.db")
    with patch.object(widgets_endpoints, "_get_snapshot_store", return_value=store):
        rows = _CLIENT.get("/tt/audit/journal?symbol=NVDA").json()
        card = _CLIENT.get("/tt/position/plan-card?symbol=NVDA").json()
    store.close()
    _assert_rows_state(rows, "unavailable", "eod-snapshot")
    assert "**Data state:** Unavailable" in card


def test_provenance_widget_uses_the_endpoint_state_vocabulary() -> None:
    """The provenance strip names the state the endpoints report."""
    widgets_endpoints._TIER_IN_USE.clear()
    try:
        _CLIENT.get("/pi/equity/key-stats?symbol=AAPL")
        body = _CLIENT.get("/pi/context/provenance").json()
    finally:
        widgets_endpoints._TIER_IN_USE.clear()
    assert "**Data mode:** Demo" in body
    assert "**Data state:** Live" in body


def test_provider_health_without_probes_is_unavailable() -> None:
    """All-unknown probe rows are ``unavailable``, not success-shaped health."""
    widgets_endpoints._PROVIDER_HEALTH_CACHE.clear()

    async def _unknown(tier: str) -> Any:
        return widgets_endpoints.TierHealth(
            name=tier, status="unknown", latency_ms=0, note="probe_failed_cold_cache"
        )

    with patch.object(widgets_endpoints, "probe_tier", _unknown):
        rows = _CLIENT.get("/pi/health/providers").json()
    widgets_endpoints._PROVIDER_HEALTH_CACHE.clear()
    _assert_rows_state(rows, "unavailable", "health-probes")


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


def test_table_manifests_with_columns_declare_the_state_columns() -> None:
    """Tables that declare columns also label the three provenance columns."""
    for widget_id, widget in _WIDGETS.items():
        columns = ((widget.get("data") or {}).get("table") or {}).get("columnsDefs")
        if widget["type"] != "table" or not columns:
            continue
        fields = [column["field"] for column in columns]
        assert fields[-3:] == list(_ROW_FIELDS), widget_id
        state, source, as_of = columns[-3:]
        # Lead decision (#1269): state visible; source and as-of hidden with
        # a tooltip (Workspace's schema allows ``hide`` and ``headerTooltip``).
        assert not state.get("hide"), widget_id
        for column in (source, as_of):
            assert column.get("hide") is True, widget_id
            assert column.get("headerTooltip"), widget_id


def test_tables_without_columns_get_no_column_defs() -> None:
    """Widgets that never declared ``columnsDefs`` are not given any."""
    for widget_id in ("pi_price_performance", "pi_management_team", "tt_audit_journal"):
        table = (_WIDGETS[widget_id].get("data") or {}).get("table") or {}
        assert not table.get("columnsDefs"), widget_id
