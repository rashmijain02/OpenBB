"""Native Workspace chart contracts for the Terminal chart widgets (#1268).

Ten ``type: chart`` widgets now return a Plotly figure
(``{"data": [...], "layout": {...}}``) by default. Each declares
``raw: true``, so Workspace calls the same endpoint with ``raw=true`` for the
raw view; that mode must return the pre-#1268 rows unchanged
(``fixtures/terminal_chart_rows_1268.json`` froze them before the change).

Figures never set ``layout.title`` (Workspace supplies the widget title). The
data state lives in ``layout.meta.state`` and, for demo/empty/unavailable, in
a layout annotation. Glossary keys ride on ``trace.meta.glossaryKey``.

Every test runs with the provider tier table cleared, so the stub fallback
serves and no provider, network, or credential file is touched.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS
from openbb_portfolio_intel.widget_backend.contracts import collect_response_issues
from openbb_portfolio_intel.widget_backend.main import app
from openbb_portfolio_intel.widget_backend.overview_charts import data_traces

_UNIT = Path(__file__).resolve().parent
_BACKEND = _UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
_VIEWER = _UNIT.parents[2] / "portfolio" / "assets" / "local_viewer" / "index.html"
_WIDGETS: dict[str, Any] = json.loads(
    (_BACKEND / "widgets.json").read_text(encoding="utf-8")
)
_ROWS: dict[str, list[dict[str, Any]]] = json.loads(
    (_UNIT / "fixtures" / "terminal_chart_rows_1268.json").read_text(encoding="utf-8")
)["responses"]
_CLIENT = TestClient(app)

# Widget id -> default URL (manifest defaults).
_DEFAULT_URLS = {
    "pi_xray_country": "/pi/xray/country?account_id=demo",
    "pi_risk_vol_chart": "/pi/risk/vol?account_id=demo",
    "pi_paper_performance": "/pi/paper/performance?account_id=demo",
    "pi_equity_financial_charts": "/pi/equity/financials?symbol=AAPL",
    "pi_equity_price_history": (
        "/pi/equity/price-history?symbol=AAPL&chart_type=line&range=6M"
    ),
    "pi_revenue_geography": "/pi/equity/revenue-geography?symbol=AAPL",
    "pi_revenue_business_line": "/pi/equity/revenue-business-line?symbol=AAPL",
    "pi_stock_ownership": "/pi/equity/stock-ownership?symbol=AAPL",
    "pi_price_target_history": "/pi/equity/price-target-history?symbol=AAPL",
    "pi_charting": "/pi/equity/charting?symbol=AAPL&window=3M",
}
_CHART_WIDGETS = sorted(_DEFAULT_URLS)
_ACCOUNT_URLS = {
    "pi_xray_country": "/pi/xray/country",
    "pi_risk_vol_chart": "/pi/risk/vol",
    "pi_paper_performance": "/pi/paper/performance",
}


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


def _raw(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}raw=true"


_PROVENANCE = ("data_state", "data_source", "data_as_of")


def _strip(rows: Any) -> Any:
    """Drop the #1269 provenance columns (asserted as strings) from raw rows."""
    assert isinstance(rows, list)
    for row in rows:
        assert all(isinstance(row[key], str) for key in _PROVENANCE), row
    return [{k: v for k, v in row.items() if k not in _PROVENANCE} for row in rows]


def _notes(figure: dict[str, Any]) -> str:
    return " ".join(a["text"] for a in figure["layout"].get("annotations", []))


def _traces(figure: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {trace["name"]: trace for trace in figure["data"]}


# ---------------------------------------------------------------------------
# Shared contract: figure by default, frozen rows with raw=true
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("widget_id", _CHART_WIDGETS)
def test_default_response_is_a_titleless_plotly_figure(widget_id: str) -> None:
    """Default is a non-empty Plotly figure with a state and no title."""
    url = _DEFAULT_URLS[widget_id]
    response = _CLIENT.get(url)
    figure = response.json()
    assert isinstance(figure, dict) and set(figure) == {"data", "layout"}, url
    assert figure["data"], f"{widget_id}: demo figure must carry traces"
    assert "title" not in figure["layout"], "Workspace supplies the title"
    assert figure["layout"]["meta"]["state"] == "demo"
    assert figure["layout"]["meta"]["source"] == "stub"
    assert "demo" in _notes(figure).lower(), "stub data must be labelled demo"
    issues = collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )
    assert not issues, issues


def _typed(value: Any) -> Any:
    """Pair every scalar with its JSON type, so ``2021`` != ``2021.0``."""
    if isinstance(value, dict):
        return {key: _typed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_typed(item) for item in value]
    return (type(value).__name__, value)


@pytest.mark.parametrize("url", sorted(_ROWS))
def test_raw_mode_returns_the_frozen_pre_1268_rows(url: str) -> None:
    """``raw=true`` returns exactly the rows (and JSON number types) of pre-#1268."""
    assert _typed(_strip(_get(_raw(url)))) == _typed(_ROWS[url])


# ---------------------------------------------------------------------------
# Pies: shares of a whole
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "label", "value"),
    [
        ("/pi/xray/country?account_id=demo", "country", "weight"),
        ("/pi/equity/revenue-geography?symbol=AAPL", "region", "revenue"),
        ("/pi/equity/revenue-business-line?symbol=AAPL", "segment", "revenue"),
        ("/pi/equity/stock-ownership?symbol=AAPL", "bucket", "pct"),
    ],
)
def test_share_widgets_are_one_pie_of_the_unchanged_rows(
    url: str, label: str, value: str
) -> None:
    """Labels and values are the row fields, in row order, unscaled."""
    rows = _ROWS[url]
    [trace] = _get(url)["data"]
    assert trace["type"] == "pie"
    assert trace["labels"] == [row[label] for row in rows]
    assert trace["values"] == [row[value] for row in rows]
    assert trace["sort"] is False
    assert "%{percent}" in trace["hovertemplate"]


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "series"),
    [
        (
            "/pi/risk/vol?account_id=demo",
            [
                ("vol_20d", "20-Day Volatility (%)", "twenty_day_volatility"),
                ("vol_60d", "60-Day Volatility (%)", "sixty_day_volatility"),
            ],
        ),
        (
            "/pi/paper/performance?account_id=demo",
            [("equity", "Portfolio Equity", "portfolio_equity")],
        ),
        (
            "/pi/equity/price-target-history?symbol=AAPL",
            [
                ("close", "Closing Price", "closing_price"),
                ("target", "Analyst Price Target", "analyst_price_target"),
            ],
        ),
        (
            "/pi/equity/price-history?symbol=AAPL&chart_type=line&range=6M",
            [("close", "Closing Price", "closing_price")],
        ),
    ],
)
def test_time_series_plot_each_row_field_as_a_dated_line(
    url: str, series: list[tuple[str, str, str]]
) -> None:
    """One scatter line per field, x = row dates, y = the unchanged values."""
    rows = _ROWS[url]
    figure = _get(url)
    assert [trace["name"] for trace in figure["data"]] == [s[1] for s in series]
    for trace, (field, _label, glossary_key) in zip(figure["data"], series):
        assert trace["type"] == "scatter"
        assert trace["x"] == [row["date"] for row in rows]
        assert trace["y"] == [row[field] for row in rows]
        assert trace["meta"] == {"glossaryKey": glossary_key}
    assert figure["layout"]["xaxis"]["type"] == "date"


def test_risk_vol_axis_is_percentage_points_not_fractions() -> None:
    """Rolling vol values are already percent (e.g. 16.0), labelled as %."""
    figure = _get("/pi/risk/vol?account_id=demo")
    assert "%" in figure["layout"]["yaxis"]["title"]["text"]
    assert all(value > 1 for value in figure["data"][0]["y"])
    assert "%" in figure["data"][0]["hovertemplate"]


def test_price_history_candle_mode_is_a_candlestick_with_a_volume_pane() -> None:
    """Candle rows become one OHLC candlestick plus volume bars on a lower axis."""
    url = "/pi/equity/price-history?symbol=AAPL&chart_type=candle&range=1M"
    rows = _ROWS[url]
    figure = _get(url)
    candle, volume = figure["data"]
    assert candle["type"] == "candlestick"
    assert candle["x"] == [row["date"] for row in rows]
    for field in ("open", "high", "low", "close"):
        assert candle[field] == [row[field] for row in rows]
    assert volume["type"] == "bar" and volume["yaxis"] == "y2"
    assert volume["y"] == [row["volume"] for row in rows]
    assert volume["meta"] == {"glossaryKey": "volume"}
    layout = figure["layout"]
    assert layout["xaxis"]["rangeslider"]["visible"] is False
    assert layout["yaxis2"]["domain"][1] < layout["yaxis"]["domain"][0]


def test_charting_overlays_moving_averages_and_puts_rsi_on_its_own_axis() -> None:
    """OHLC candles + SMA lines on price; RSI on a 0-100 lower pane."""
    url = "/pi/equity/charting?symbol=AAPL&window=3M"
    rows = _ROWS[url]
    figure = _get(url)
    traces = _traces(figure)
    candle = next(t for t in figure["data"] if t["type"] == "candlestick")
    for field in ("open", "high", "low", "close"):
        assert candle[field] == [row[field] for row in rows]
    assert traces["SMA 20"]["y"] == [row["sma20"] for row in rows]
    assert traces["SMA 50"]["y"] == [row["sma50"] for row in rows]
    rsi = traces["RSI 14"]
    assert rsi["y"] == [row["rsi14"] for row in rows]
    assert rsi["yaxis"] == "y2"
    assert traces["SMA 20"].get("yaxis", "y") == "y"
    assert figure["layout"]["yaxis2"]["range"] == [0, 100]
    assert "Relative Strength Index" in rsi["hovertemplate"]


def test_financials_are_grouped_bars_with_margin_on_a_right_axis() -> None:
    """Revenue/net income bars ($B, left) and net margin line (%, right)."""
    url = "/pi/equity/financials?symbol=AAPL"
    rows = _ROWS[url]
    figure = _get(url)
    expected = [
        ("revenue_b", "Revenue ($B)", "revenue_b", "bar", "y"),
        ("net_income_b", "Net Income ($B)", "net_income_b", "bar", "y"),
        ("net_margin_pct", "Net Margin (%)", "net_margin_pct", "scatter", "y2"),
    ]
    assert [t["name"] for t in figure["data"]] == [e[1] for e in expected]
    for trace, (field, _name, key, kind, axis) in zip(figure["data"], expected):
        assert trace["type"] == kind
        assert trace.get("yaxis", "y") == axis
        assert trace["x"] == [row["year"] for row in rows]
        assert trace["y"] == [row[field] for row in rows]
        assert trace["meta"] == {"glossaryKey": key}
    layout = figure["layout"]
    assert layout["barmode"] == "group"
    assert layout["xaxis"]["type"] == "category"
    assert "$B" in layout["yaxis"]["title"]["text"]
    assert "%" in layout["yaxis2"]["title"]["text"]
    assert layout["yaxis2"]["overlaying"] == "y"
    assert layout["yaxis2"]["side"] == "right"


def test_glossary_keys_exist_in_the_viewer_and_hover_carries_the_summary() -> None:
    """Every trace glossary key is a curated viewer record; hover explains it."""
    viewer = _VIEWER.read_text(encoding="utf-8")
    seen = 0
    for url in _DEFAULT_URLS.values():
        for trace in _get(url)["data"]:
            key = (trace.get("meta") or {}).get("glossaryKey")
            if not key:
                continue
            seen += 1
            marker = f"    {key}: Object.freeze({{"
            assert marker in viewer, key
            start = viewer.index(marker)
            record = viewer[start : viewer.index("    }),", start)]
            summary = record.split('summary: "', 1)[1].split('"', 1)[0]
            assert summary in trace["hovertemplate"], (key, summary)
    assert seen >= 8


# ---------------------------------------------------------------------------
# States: unavailable, live, empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("widget_id", sorted(_ACCOUNT_URLS))
def test_unwired_account_is_an_explicit_unavailable_figure(widget_id: str) -> None:
    """A non-demo account is a trace-free unavailable figure, not fake data."""
    url = f"{_ACCOUNT_URLS[widget_id]}?account_id=NOT_WIRED"
    response = _CLIENT.get(url)
    figure = response.json()
    assert data_traces(figure) == [] and figure["data"]
    assert figure["layout"]["meta"]["state"] == "unavailable"
    assert "title" not in figure["layout"]
    assert "not wired" in _notes(figure)
    assert not collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )
    assert _strip(_get(_raw(url))) == _ROWS[url]
    assert {r["data_state"] for r in _get(_raw(url))} == {"unavailable"}


def test_live_tier_rows_are_labelled_live_with_their_source() -> None:
    """Rows a live tier served carry state ``live`` and no demo annotation."""

    def _fake_tier(*, symbol: str) -> list[dict[str, Any]]:
        return [
            {"region": "Americas", "revenue": 10.0},
            {"region": "Europe", "revenue": 5.0},
        ]

    _TIER_CALLS[("equity/revenue-geography", "fmp_cached")] = _fake_tier
    figure = _get("/pi/equity/revenue-geography?symbol=AAPL")
    meta = figure["layout"]["meta"]
    assert (meta["state"], meta["source"], meta["asOf"]) == (
        "cached",  # #1269: fmp_cached is cached, as-of unknown
        "fmp_cached",
        "unknown",
    )
    assert "demo" not in _notes(figure).lower()
    assert figure["data"][0]["labels"] == ["Americas", "Europe"]
    assert _strip(_get("/pi/equity/revenue-geography?symbol=AAPL&raw=true")) == [
        {"region": "Americas", "revenue": 10.0},
        {"region": "Europe", "revenue": 5.0},
    ]


def test_empty_rows_render_an_explicit_empty_state() -> None:
    """No rows gives a trace-free figure with an explanation for every builder."""
    from openbb_portfolio_intel.widget_backend import terminal_charts as tc

    from openbb_portfolio_intel.widget_backend.provenance import (
        DataState,
        Provenance,
    )

    context = tc.ChartContext(
        params={"symbol": "AAPL", "account_id": "demo"},
        provenance=Provenance(DataState.DEMO, "stub", "sample"),
    )
    builders = [
        tc.xray_country_figure,
        tc.risk_vol_figure,
        tc.paper_performance_figure,
        tc.equity_financials_figure,
        tc.price_history_figure,
        tc.revenue_geography_figure,
        tc.revenue_business_line_figure,
        tc.stock_ownership_figure,
        tc.price_target_history_figure,
        tc.charting_figure,
    ]
    for build in builders:
        figure = build([], context)
        assert data_traces(figure) == [] and figure["data"], build.__name__
        # #1269: an empty result is "unavailable", never a success shape.
        assert figure["layout"]["meta"]["state"] == "unavailable", build.__name__
        assert "no " in _notes(figure).lower(), build.__name__
        assert "title" not in figure["layout"], build.__name__


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("widget_id", _CHART_WIDGETS)
def test_chart_manifest_uses_only_schema_keys(widget_id: str) -> None:
    """No ``data.chart`` / ``data.metricGlossary``; raw mode stays declared."""
    widget = _WIDGETS[widget_id]
    assert widget["type"] == "chart"
    assert widget["raw"] is True
    assert "help" not in widget
    assert not set(widget.get("data") or {}) - {"dataKey", "table", "wsRowIdColumn"}


def test_price_history_description_keeps_the_reading_guide_essentials() -> None:
    """The removed ``help`` text survives as description essentials."""
    description = _WIDGETS["pi_equity_price_history"]["description"]
    for phrase in ("closing price", "Candlestick", "high", "low", "volume", "demo"):
        assert phrase in description, phrase
