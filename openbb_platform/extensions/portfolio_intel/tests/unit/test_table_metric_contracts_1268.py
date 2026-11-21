"""Native Workspace table, metric, and Markdown contracts (#1268, batch B).

Workspace's widget schema is closed (``additionalProperties: false``), so the
Terminal manifests may not carry the viewer-only keys they used to:
``data.metricGlossary``, ``data.metric``, ``columnsDefs[].glossaryKey`` /
``valueLabels`` and ``data.table.rowLabels`` / ``rowLabelPatterns``.

- A column's glossary is the schema-native ``headerTooltip`` (the Local
  Viewer glossary record's one-line summary).
- Enum codes and row identifiers are labelled server-side, in the response.
- Metric widgets return Workspace metric cards: ``[{label, value}]``. Demo
  and unavailable states are explicit cards, never a silent ``0.0``.
- Revenue geography and business-line rows are in millions on every path.
- Terminal Markdown widgets never return blank text.

Every test runs with the provider tier table cleared, so the stub fallback
serves and no provider, network, or credential file is touched.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend import tier_calls
from openbb_portfolio_intel.widget_backend.contracts import collect_response_issues
from openbb_portfolio_intel.widget_backend.main import app

_UNIT = Path(__file__).resolve().parent
_BACKEND = _UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
_VIEWER = _UNIT.parents[2] / "portfolio" / "assets" / "local_viewer" / "index.html"
_DEBT = _UNIT / "fixtures" / "workspace_contract_debt.json"
_WIDGETS: dict[str, Any] = json.loads(
    (_BACKEND / "widgets.json").read_text(encoding="utf-8")
)
_CLIENT = TestClient(app)
_VIEWER_ONLY_KEYS = {"metricGlossary", "metric", "glossaryKey", "valueLabels"}
_VIEWER_ONLY_TABLE_KEYS = {"rowLabels", "rowLabelPatterns"}


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


def _get(url: str) -> Any:
    response = _CLIENT.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def _summary(key: str) -> str:
    """Return the Local Viewer glossary record's one-line summary."""
    viewer = _VIEWER.read_text(encoding="utf-8")
    marker = f"    {key}: Object.freeze({{"
    assert marker in viewer, key
    start = viewer.index(marker)
    record = viewer[start : viewer.index("    }),", start)]
    return record.split('summary: "', 1)[1].split('"', 1)[0]


def _column(widget_id: str, field: str) -> dict[str, Any]:
    columns = _WIDGETS[widget_id]["data"]["table"]["columnsDefs"]
    return next(column for column in columns if column["field"] == field)


# ---------------------------------------------------------------------------
# Manifest: no viewer-only keys, glossary as headerTooltip
# ---------------------------------------------------------------------------


def test_no_1268_debt_remains_in_the_baseline() -> None:
    """Batch B clears every #1268 entry; the other owners' entries stay."""
    issues = json.loads(_DEBT.read_text(encoding="utf-8"))["issues"]
    assert [entry for entry in issues if entry["tracking"] == "#1268"] == []
    assert {entry["tracking"] for entry in issues} <= {"#1270", "#1271"}


@pytest.mark.parametrize("widget_id", sorted(_WIDGETS))
def test_terminal_manifests_carry_no_viewer_only_keys(widget_id: str) -> None:
    """Table/metric/markdown manifests use only Workspace schema keys."""
    data = _WIDGETS[widget_id].get("data") or {}
    assert not set(data) & _VIEWER_ONLY_KEYS
    table = data.get("table") or {}
    assert not set(table) & _VIEWER_ONLY_TABLE_KEYS
    for column in table.get("columnsDefs") or []:
        assert not set(column) & _VIEWER_ONLY_KEYS, (widget_id, column)


# (widget, field) -> glossary record whose summary is the column header tooltip.
_GLOSSARY_COLUMNS = {
    ("pi_lookthrough_top25", "effective_weight"): "effective_weight",
    ("pi_event_calendar", "type"): "event_type",
    ("pi_smart_money_ribbon", "value_usd"): "transaction_value",
    ("pi_paper_blotter", "avg_price"): "average_execution_price",
    ("pi_alerts_panel", "kind"): "alert_type",
    ("pi_equity_complementary", "weight_pct"): "portfolio_weight",
    ("pi_equity_complementary", "value_usd"): "market_value",
    ("pi_equity_competitors", "change_pct"): "percentage_price_change",
    ("pi_earnings_history", "eps_actual"): "actual_eps",
    ("pi_earnings_history", "eps_estimate"): "estimated_eps",
    ("pi_earnings_history", "surprise_pct"): "earnings_surprise",
    ("pi_dividend_payment", "ex_date"): "ex_dividend_date",
    ("pi_dividend_payment", "amount"): "dividend_amount_per_share",
    ("pi_peer_multiples", "pe_ttm"): "pe_ttm",
    ("pi_peer_multiples", "pe_fwd"): "pe_forward",
    ("pi_peer_multiples", "ev_ebitda"): "ev_ebitda",
    ("pi_peer_multiples", "ps_ttm"): "ps_ttm",
    ("pi_basket_analyst_consensus", "avg_target"): "average_price_target",
    ("pi_basket_analyst_consensus", "consensus"): "consensus_rating",
}


@pytest.mark.parametrize(("widget_id", "field"), sorted(_GLOSSARY_COLUMNS), ids=str)
def test_glossary_columns_use_the_schema_native_header_tooltip(
    widget_id: str, field: str
) -> None:
    """The header tooltip is the curated glossary summary, verbatim."""
    key = _GLOSSARY_COLUMNS[(widget_id, field)]
    assert _column(widget_id, field)["headerTooltip"] == _summary(key)


def test_technicals_description_explains_the_pivot_rows() -> None:
    """The widget-level glossary that mattered moved into the description."""
    description = _WIDGETS["pi_equity_technicals"]["description"]
    for term in ("pivot", "resistance", "support"):
        assert term in description.lower()


# ---------------------------------------------------------------------------
# Server-side value and row labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "field", "labels", "codes"),
    [
        (
            "/pi/events/calendar?account_id=demo&horizon_days=14",
            "type",
            {"Earnings", "Ex-Dividend", "Form 8-K"},
            {"earnings", "ex_dividend", "form_8k"},
        ),
        (
            "/pi/smart-money/ribbon?account_id=demo",
            "kind",
            {"Insider Buy", "13F Increase", "Insider Sell"},
            {"insider_buy", "13F_increase", "insider_sell"},
        ),
        (
            "/pi/alerts?account_id=demo",
            "kind",
            {"Held-Security Form 8-K", "Upcoming Earnings", "Material News"},
            {"form_8k_for_held", "earnings_upcoming", "news_material"},
        ),
        (
            "/pi/equity/basket-analyst-consensus?basket_id=demo",
            "consensus",
            {"Buy", "Strong Buy"},
            {"BUY", "STRONG_BUY"},
        ),
    ],
)
def test_enum_codes_are_labelled_in_the_response(
    url: str, field: str, labels: set[str], codes: set[str]
) -> None:
    """Workspace shows the response value, so the response carries the label."""
    values = {row[field] for row in _get(url)}
    assert values == labels
    assert not values & codes


def test_event_calendar_unwired_account_says_information() -> None:
    """The placeholder row's code is labelled too."""
    rows = _get("/pi/events/calendar?account_id=NOT_WIRED&horizon_days=14")
    assert rows[0]["type"] == "Information"


def test_basket_consensus_does_not_mutate_the_demo_rows() -> None:
    """Labelling copies the rows; the shared demo rows keep their codes."""
    from openbb_portfolio_intel.widget_backend import widgets_endpoints

    demo = widgets_endpoints._DEMO_BASKET_CONSENSUS  # pylint: disable=protected-access
    before = [dict(row) for row in demo]
    _get("/pi/equity/basket-analyst-consensus?basket_id=demo")
    assert demo == before
    assert {row["consensus"] for row in demo} == {"BUY", "STRONG_BUY"}


def test_technical_rows_are_labelled_in_the_response() -> None:
    """Classic pivot codes become readable labels server-side."""
    rows = _get("/pi/equity/technicals?symbol=AAPL")
    assert [row["metric"] for row in rows] == [
        "Analyst Consensus",
        "Resistance 3",
        "Resistance 2",
        "Resistance 1",
        "Pivot",
        "Support 1",
        "Support 2",
        "Support 3",
        "ATM Implied Volatility Term Structure",
    ]


def test_forecast_rows_are_labelled_in_the_response() -> None:
    """Exact labels plus the rating and EPS-surprise patterns."""
    labels = [row["metric"] for row in _get("/pi/equity/analyst-forecasts?symbol=AAPL")]
    assert labels[:3] == [
        "12-Month Price Target",
        "Target Range",
        "Upside vs Current Price",
    ]
    assert labels[3:5] == [
        "Rating Distribution: Strong Buy / Buy",
        "Rating Distribution: Hold / Sell / Strong Sell",
    ]
    assert labels[5:7] == ["Q3 2025 EPS Surprise", "Q2 2025 EPS Surprise"]
    assert labels[7] == "Historical Revenue Estimate"


def test_whatif_rows_are_labelled_in_the_response() -> None:
    """Raw snake_case identifiers never reach the table."""
    rows = _get("/pi/whatif/card?symbol=AAPL&delta_shares=100")
    assert [row["metric"] for row in rows] == [
        "Symbol Weight (%)",
        "Sector Weight (%)",
        "Cash Weight (%)",
        "Beta vs SPY",
    ]


# ---------------------------------------------------------------------------
# Metric widgets: Workspace metric cards
# ---------------------------------------------------------------------------

_METRICS = {
    "pi_concentration_gauge": (
        "/pi/concentration",
        [("Concentration (HHI)", 0.2374)],
    ),
    "pi_risk_dashboard": (
        "/pi/risk/dashboard",
        [
            ("Annualized Volatility (%)", 18.4),
            ("1-Day 95% VaR (%)", -2.1),
            ("Beta vs SPY", 1.08),
        ],
    ),
    "pi_paper_perf_kpis": (
        "/pi/paper/perf-kpis",
        [
            ("Total Return (%)", 3.24),
            ("Annualized Sharpe Ratio", 1.42),
            ("Maximum Drawdown (%)", -1.87),
        ],
    ),
    "pi_sentiment_gauge": (
        "/pi/sentiment",
        [("News Sentiment Score (-1 to +1)", 0.62)],
    ),
}


@pytest.mark.parametrize("widget_id", sorted(_METRICS))
def test_metric_endpoint_returns_labelled_cards_and_a_demo_state(
    widget_id: str,
) -> None:
    """Demo values are cards with exact labels, followed by a demo state card."""
    path, expected = _METRICS[widget_id]
    response = _CLIENT.get(f"{path}?account_id=demo")
    cards = response.json()
    assert isinstance(cards, list)
    assert [(c["label"], c["value"]) for c in cards[:-1]] == expected
    assert cards[-1]["label"] == "Data State"
    assert cards[-1]["value"].startswith("Demo")
    assert all(set(card) == {"label", "value"} for card in cards)
    assert not collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )


@pytest.mark.parametrize("widget_id", sorted(_METRICS))
def test_metric_unwired_account_is_explicitly_unavailable(widget_id: str) -> None:
    """A non-demo account never shows a fabricated 0.0."""
    path, expected = _METRICS[widget_id]
    cards = _get(f"{path}?account_id=NOT_WIRED")
    assert [(c["label"], c["value"]) for c in cards[:-1]] == [
        (label, "Unavailable") for label, _value in expected
    ]
    assert cards[-1]["label"] == "Data State"
    assert cards[-1]["value"].startswith("Unavailable")
    assert "not wired" in cards[-1]["value"]


@pytest.mark.parametrize("widget_id", sorted(_METRICS))
def test_metric_descriptions_state_units_and_demo(widget_id: str) -> None:
    """The manifest description carries what ``data.metric`` used to."""
    description = _WIDGETS[widget_id]["description"].lower()
    assert "demo" in description


# ---------------------------------------------------------------------------
# Revenue units: millions on every path
# ---------------------------------------------------------------------------


def _absolute(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Return provider-style rows (absolute currency) for the stub's millions."""
    return [
        {"period_ending": "2025-09-27", key: row[key], "revenue": row["revenue"] * 1e6}
        for row in rows
    ]


@pytest.mark.parametrize(
    ("url", "shape", "provider_key", "row_key"),
    [
        (
            "/pi/equity/revenue-geography?symbol=AAPL&raw=true",
            tier_calls._shape_revenue_geography,  # pylint: disable=protected-access
            "region",
            "region",
        ),
        (
            "/pi/equity/revenue-business-line?symbol=AAPL&raw=true",
            tier_calls._shape_revenue_business_line,  # pylint: disable=protected-access
            "business_line",
            "segment",
        ),
    ],
)
def test_live_and_demo_revenue_rows_share_one_unit(
    url: str, shape: Any, provider_key: str, row_key: str
) -> None:
    """Provider rows in absolute currency shape to the stub's millions.

    Fails on mixed units: the same revenue figures must be equal whether the
    stub or the live shaper produced them.
    """
    demo = _get(url)
    provider = _absolute(
        [{provider_key: row[row_key], "revenue": row["revenue"]} for row in demo],
        provider_key,
    )
    live = shape(provider)
    assert [r[row_key] for r in live] == [r[row_key] for r in demo]
    assert [r["revenue"] for r in live] == pytest.approx([r["revenue"] for r in demo])


@pytest.mark.parametrize(
    ("widget_id", "url"),
    [
        ("pi_revenue_geography", "/pi/equity/revenue-geography?symbol=AAPL"),
        ("pi_revenue_business_line", "/pi/equity/revenue-business-line?symbol=AAPL"),
    ],
)
def test_revenue_unit_is_documented_in_hover_and_description(
    widget_id: str, url: str
) -> None:
    """The pie hover and the manifest say the values are in millions."""
    trace = _get(url)["data"][0]
    assert "millions" in trace["hovertemplate"]
    assert "millions" in _WIDGETS[widget_id]["description"]


# ---------------------------------------------------------------------------
# Markdown widgets: never blank, state explicit
# ---------------------------------------------------------------------------

_MARKDOWN_URLS = {
    "pi_symbol_context": "/pi/context/symbol?symbol=AAPL",
    "pi_book_context": "/pi/context/book?account_id=demo",
    "pi_paper_ticket": "/pi/paper/ticket?account_id=demo",
    "pi_whatif_diff": "/pi/whatif?symbol=AAPL&delta_shares=100",
    "pi_backtest_button": "/pi/backtest/oneclick?account_id=demo",
    "pi_equity_profile_header": "/pi/equity/header?symbol=AAPL",
    "pi_earnings_transcripts": "/pi/equity/earnings-transcripts?symbol=AAPL",
    "pi_data_provenance": "/pi/context/provenance",
}
# Context widgets name the shared parameter; they carry no data to label.
_CONTEXT_ONLY = {"pi_symbol_context", "pi_book_context"}
_STATE_WORDS = re.compile(
    r"\b(demo|stub|preview|sample|synthetic|unavailable|not available|no data)\b",
    re.IGNORECASE,
)


def test_every_terminal_markdown_widget_is_covered() -> None:
    """The URL table lists every Portfolio Intelligence Markdown widget."""
    markdown = {
        widget_id
        for widget_id, widget in _WIDGETS.items()
        if widget["type"] == "markdown" and widget_id.startswith("pi_")
    }
    assert markdown == set(_MARKDOWN_URLS)


@pytest.mark.parametrize("widget_id", sorted(_MARKDOWN_URLS))
def test_markdown_widgets_return_explicit_non_blank_text(widget_id: str) -> None:
    """Stub/demo Markdown says so in words; no widget returns a blank."""
    response = _CLIENT.get(_MARKDOWN_URLS[widget_id])
    text = response.json()
    assert isinstance(text, str) and text.strip()
    if widget_id not in _CONTEXT_ONLY:
        assert _STATE_WORDS.search(text), widget_id
    assert not collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )
