"""Load-bearing Terminal terminology contracts for #1987 child widgets."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WIDGETS = _PACKAGE_ROOT / "openbb_portfolio_intel" / "widget_backend" / "widgets.json"
_VIEWER = _PACKAGE_ROOT.parent / "portfolio" / "assets" / "local_viewer" / "index.html"
_CLIENT = TestClient(app)


def _widgets() -> dict:
    return json.loads(_WIDGETS.read_text(encoding="utf-8"))


_PROVENANCE = ("data_state", "data_source", "data_as_of")


def _widget(widget_id: str) -> dict:
    """Return a widget without the #1269 provenance columns (tested separately)."""
    widget = _widgets()[widget_id]
    table = (widget.get("data") or {}).get("table") or {}
    if table.get("columnsDefs"):
        table["columnsDefs"] = [
            c for c in table["columnsDefs"] if c["field"] not in _PROVENANCE
        ]
    return widget


def _viewer_label_glossary() -> dict[str, str]:
    """Return the Local Viewer's rendered-label -> glossary-key map (#1268).

    Workspace manifests cannot carry ``metricGlossary``; the viewer keys help
    on the labels the backend renders (``metricLabelGlossaryData``).
    """
    text = _VIEWER.read_text(encoding="utf-8")
    start = text.index("function metricLabelGlossaryData()")
    body = text[start : text.index("    };", start)]
    return dict(re.findall(r'^\s+"([^"]+)": "([a-z0-9_]+)",$', body, re.MULTILINE))


def _summary(key: str) -> str:
    """Return the Local Viewer glossary record's one-line summary."""
    text = _VIEWER.read_text(encoding="utf-8")
    marker = f"    {key}: Object.freeze({{"
    start = text.index(marker)
    record = text[start : text.index("    }),", start)]
    return record.split('summary: "', 1)[1].split('"', 1)[0]


def _metric_labels(path: str) -> list[str]:
    response = _CLIENT.get(path)
    assert response.status_code == 200
    return [card["label"] for card in response.json()]


def test_1989_statement_period_headers_match_backend_semantics() -> None:
    columns = _widget("pi_financial_statements")["data"]["table"]["columnsDefs"]
    assert {column["field"]: column["headerName"] for column in columns} == {
        "line_item": "Line Item",
        "period_1": "Latest Period (millions)",
        "period_2": "Prior Period (millions)",
    }


def test_1998_lookthrough_fraction_uses_workspace_percent_formatter() -> None:
    column = next(
        column
        for column in _widget("pi_lookthrough_top25")["data"]["table"]["columnsDefs"]
        if column["field"] == "effective_weight"
    )
    assert column == {
        "field": "effective_weight",
        "headerName": "Effective Weight (%)",
        "headerTooltip": _summary("effective_weight"),
        "formatterFn": "normalizedPercent",
    }
    response = _CLIENT.get("/pi/lookthrough/top25?account_id=demo")
    assert response.status_code == 200
    assert response.json()[0]["effective_weight"] == 0.078


def test_widget_formatter_metadata_uses_workspace_supported_names() -> None:
    """Fractional values use normalizedPercent, never a viewer-only formatter."""

    def formatter_names(value: object) -> set[str]:
        if isinstance(value, dict):
            names: set[str] = set()
            for key, item in value.items():
                if key == "formatterFn" and isinstance(item, str):
                    names.add(item)
                if key == "formatters" and isinstance(item, dict):
                    names |= {name for name in item.values() if isinstance(name, str)}
                names |= formatter_names(item)
            return names
        if isinstance(value, list):
            return set().union(*(formatter_names(item) for item in value))
        return set()

    assert formatter_names(_widgets()) <= {"normalizedPercent", "percent"}


def test_1999_single_value_concentration_card_has_label_and_help_mapping() -> None:
    """#1268: the endpoint serves the card label; the viewer keys help on it."""
    assert "data" not in _widget("pi_concentration_gauge")
    labels = _metric_labels("/pi/concentration?account_id=demo")
    assert labels[0] == "Concentration (HHI)"
    assert _viewer_label_glossary()[labels[0]] == "herfindahl_hirschman_index"


def test_1993_technical_rows_match_actual_classic_pivot_strings() -> None:
    """#1268: Classic pivot codes are labelled server-side; help keys on labels."""
    response = _CLIENT.get("/pi/equity/technicals?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    expected = {
        "Analyst Consensus": "analyst_consensus",
        "Resistance 3": "resistance",
        "Resistance 2": "resistance",
        "Resistance 1": "resistance",
        "Pivot": "pivot",
        "Support 1": "support",
        "Support 2": "support",
        "Support 3": "support",
        "ATM Implied Volatility Term Structure": "atm_implied_volatility",
    }
    assert {row["metric"] for row in rows} == set(expected)
    glossary = _viewer_label_glossary()
    for label, key in expected.items():
        assert glossary[label] == key


def test_1996_forecast_endpoint_serves_rendered_labels() -> None:
    """#1268: forecast rows arrive labelled; no manifest row-label metadata."""
    widget = _widget("pi_equity_analyst_forecasts")
    response = _CLIENT.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert response.status_code == 200
    labels = {row["metric"] for row in response.json()}
    assert {
        "12-Month Price Target",
        "Target Range",
        "Upside vs Current Price",
        "Rating Distribution: Strong Buy / Buy",
        "Rating Distribution: Hold / Sell / Strong Sell",
        "Q3 2025 EPS Surprise",
        "Q2 2025 EPS Surprise",
        "Historical Revenue Estimate",
    } <= labels
    assert not {"rowLabels", "rowLabelPatterns"} & set(widget["data"]["table"])


def test_time_series_widgets_have_exact_labels_and_glossary_keys() -> None:
    """#1268 moved chart labels/glossary from manifest keys into the figures.

    Workspace's schema rejects ``data.chart`` / ``data.metricGlossary``, so
    series labels are Plotly trace names, the date axis is the x-axis, and each
    trace carries its glossary key in ``meta.glossaryKey``.
    """
    expected = {
        "/pi/equity/price-target-history?symbol=AAPL": {
            "Closing Price": "closing_price",
            "Analyst Price Target": "analyst_price_target",
        },
        "/pi/risk/vol?account_id=demo": {
            "20-Day Volatility (%)": "twenty_day_volatility",
            "60-Day Volatility (%)": "sixty_day_volatility",
        },
        "/pi/paper/performance?account_id=demo": {
            "Portfolio Equity": "portfolio_equity",
        },
    }
    text = _VIEWER.read_text(encoding="utf-8")
    for url, glossary in expected.items():
        response = _CLIENT.get(url)
        assert response.status_code == 200
        figure = response.json()
        assert figure["layout"]["xaxis"]["title"]["text"] == "Date"
        assert {
            trace["name"]: trace["meta"]["glossaryKey"] for trace in figure["data"]
        } == glossary
        for key in glossary.values():
            assert f"{key}: Object.freeze({{" in text
    for widget_id in (
        "pi_price_target_history",
        "pi_risk_vol_chart",
        "pi_paper_performance",
    ):
        assert "data" not in _widget(widget_id)


def test_glossary_records_are_specific_and_link_to_term_pages() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    assert "A curated portfolio-analysis term" not in text
    assert "financial-term-dictionary" not in text
    records = (
        "twelve_month_price_target",
        "target_range",
        "implied_upside",
        "rating_distribution",
        "eps_surprise",
        "revenue_estimate",
    )
    for key in records:
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert (
            "summary:" in record
            and "definition:" in record
            and "interpretation:" in record
        )
        assert 'source: "https://' in record


# Rendered rows/cards per widget whose labels come from the response (#1268).
_RESPONSE_LABEL_URLS = {
    "pi_equity_technicals": ("/pi/equity/technicals?symbol=AAPL", "metric"),
    "pi_equity_analyst_forecasts": (
        "/pi/equity/analyst-forecasts?symbol=AAPL",
        "metric",
    ),
    "pi_whatif_card": ("/pi/whatif/card?symbol=AAPL&delta_shares=100", "metric"),
    "pi_concentration_gauge": ("/pi/concentration?account_id=demo", "label"),
    "pi_risk_dashboard": ("/pi/risk/dashboard?account_id=demo", "label"),
    "pi_paper_perf_kpis": ("/pi/paper/perf-kpis?account_id=demo", "label"),
}


@pytest.mark.parametrize(
    ("widget_id", "labels", "glossary"),
    [
        (
            "pi_equity_key_stats",
            {},
            {
                "Volume": "volume",
                "52-Week High": "fifty_two_week_high",
                "52-Week Low": "fifty_two_week_low",
            },
        ),
        (
            "pi_financial_statements",
            {
                "line_item": "Line Item",
                "period_1": "Latest Period (millions)",
                "period_2": "Prior Period (millions)",
            },
            {"Revenue": "revenue", "Free Cash Flow": "free_cash_flow"},
        ),
        (
            "pi_peer_multiples",
            {
                "symbol": "Symbol",
                "pe_ttm": "P/E (TTM)",
                "pe_fwd": "P/E (Forward)",
                "ev_ebitda": "EV/EBITDA",
                "ps_ttm": "P/S (TTM)",
            },
            {
                "P/E (TTM)": "pe_ttm",
                "P/E (Forward)": "pe_forward",
                "EV/EBITDA": "ev_ebitda",
                "P/S (TTM)": "ps_ttm",
            },
        ),
        (
            "pi_earnings_history",
            {
                "quarter": "Quarter",
                "eps_actual": "Actual EPS",
                "eps_estimate": "Estimated EPS",
                "surprise_pct": "Surprise (%)",
            },
            {
                "Actual EPS": "actual_eps",
                "Estimated EPS": "estimated_eps",
                "Surprise (%)": "earnings_surprise",
            },
        ),
        (
            "pi_dividend_payment",
            {
                "ex_date": "Ex-Dividend Date",
                "payment_date": "Payment Date",
                "amount": "Dividend Amount ($/share)",
            },
            {
                "Ex-Dividend Date": "ex_dividend_date",
                "Dividend Amount ($/share)": "dividend_amount_per_share",
            },
        ),
        (
            "pi_equity_technicals",
            {
                "Consensus": "Analyst Consensus",
                "R3 (Classic)": "Resistance 3",
                "P (Classic)": "Pivot",
                "S3 (Classic)": "Support 3",
            },
            {
                "Resistance 3": "resistance",
                "Pivot": "pivot",
                "Support 3": "support",
            },
        ),
        (
            "pi_equity_competitors",
            {
                "symbol": "Symbol",
                "name": "Company",
                "price": "Price",
                "change_pct": "Change (%)",
            },
            {"Change (%)": "percentage_price_change"},
        ),
        (
            "pi_equity_complementary",
            {
                "kind": "Asset Type",
                "id": "Identifier",
                "name": "Name",
                "weight_pct": "Portfolio Weight (%)",
                "value_usd": "Market Value ($)",
            },
            {
                "Portfolio Weight (%)": "portfolio_weight",
                "Market Value ($)": "market_value",
            },
        ),
        (
            "pi_equity_analyst_forecasts",
            {
                "1Y target (consensus)": "12-Month Price Target",
                "Target range": "Target Range",
                "Upside vs current": "Upside vs Current Price",
            },
            {
                "Rating Distribution: Strong Buy / Buy": "rating_distribution",
                "Q3 2025 EPS Surprise": "eps_surprise",
                "Historical Revenue Estimate": "revenue_estimate",
            },
        ),
        (
            "pi_basket_analyst_consensus",
            {
                "symbol": "Symbol",
                "avg_target": "Average Price Target",
                "buy": "Buy Ratings",
                "hold": "Hold Ratings",
                "sell": "Sell Ratings",
                "consensus": "Consensus Rating",
            },
            {
                "Average Price Target": "average_price_target",
                "Consensus Rating": "consensus_rating",
            },
        ),
        (
            "pi_lookthrough_top25",
            {
                "symbol": "Symbol",
                "name": "Holding",
                "effective_weight": "Effective Weight (%)",
                "rank": "Rank",
            },
            {"Effective Weight (%)": "effective_weight"},
        ),
        (
            "pi_concentration_gauge",
            {"value": "Concentration (HHI)"},
            {"Concentration (HHI)": "herfindahl_hirschman_index"},
        ),
        (
            "pi_risk_dashboard",
            {
                "vol_annualized": "Annualized Volatility (%)",
                "var_95_1d": "1-Day 95% VaR (%)",
                "beta_spy": "Beta vs SPY",
            },
            {
                "Annualized Volatility (%)": "annualized_volatility",
                "1-Day 95% VaR (%)": "one_day_var_95",
                "Beta vs SPY": "beta_vs_spy",
            },
        ),
        (
            "pi_whatif_card",
            {
                "symbol_weight_%": "Symbol Weight (%)",
                "sector_weight_%": "Sector Weight (%)",
                "cash_%": "Cash Weight (%)",
                "beta_spy": "Beta vs SPY",
            },
            {
                "Symbol Weight (%)": "symbol_weight",
                "Sector Weight (%)": "sector_weight",
                "Cash Weight (%)": "cash_weight",
                "Beta vs SPY": "beta_vs_spy",
            },
        ),
        (
            "pi_paper_perf_kpis",
            {
                "total_return_pct": "Total Return (%)",
                "sharpe_annualized": "Annualized Sharpe Ratio",
                "max_drawdown_pct": "Maximum Drawdown (%)",
            },
            {
                "Total Return (%)": "total_return",
                "Annualized Sharpe Ratio": "sharpe_ratio",
                "Maximum Drawdown (%)": "maximum_drawdown",
            },
        ),
        (
            "pi_paper_blotter",
            {
                "time": "Time",
                "symbol": "Symbol",
                "side": "Side",
                "qty": "Quantity",
                "status": "Status",
                "avg_price": "Average Execution Price",
            },
            {"Average Execution Price": "average_execution_price"},
        ),
        (
            "pi_smart_money_ribbon",
            {
                "symbol": "Symbol",
                "kind": "Activity Type",
                "actor": "Actor",
                "value_usd": "Transaction Value ($)",
                "date": "Date",
            },
            {"Transaction Value ($)": "transaction_value"},
        ),
    ],
)
def test_all_21_widgets_have_exact_label_and_glossary_contracts(
    widget_id: str, labels: dict[str, str], glossary: dict[str, str]
) -> None:
    """Labels are column headers or served row/card labels; help keys on them.

    #1268: the old raw-identifier keys of ``labels`` (e.g. ``R3 (Classic)``)
    no longer reach the client; only the rendered label is checked for them.
    """
    widget = _widget(widget_id)
    columns = ((widget.get("data") or {}).get("table") or {}).get("columnsDefs")
    if widget_id in _RESPONSE_LABEL_URLS:
        path, field = _RESPONSE_LABEL_URLS[widget_id]
        response = _CLIENT.get(path)
        assert response.status_code == 200
        served = {row[field] for row in response.json()}
        for label in labels.values():
            assert label in served, (widget_id, label)
    else:
        headers = {column["field"]: column["headerName"] for column in columns}
        for field, label in labels.items():
            assert headers[field] == label
    viewer = _viewer_label_glossary()
    for label, key in glossary.items():
        if label in viewer:
            assert viewer[label] == key, (widget_id, label)
        else:
            # Pattern-labelled forecast rows resolve in the viewer by pattern.
            assert widget_id == "pi_equity_analyst_forecasts", (widget_id, label)
            assert re.match(
                r"^(Rating Distribution: \S|Q[1-4] \d{4} EPS Surprise$)", label
            )


def test_brinson_figure_carries_exact_labels_and_glossary_keys() -> None:
    """#1267 moved Brinson labels/glossary from manifest keys into the figure.

    Workspace's schema rejects ``data.chart`` / ``data.metricGlossary``, so the
    series labels are the Plotly trace names, the axis label is the x-axis
    title, and each trace carries its glossary key in ``meta.glossaryKey``.
    """
    response = _CLIENT.get("/pi/attribution?window=1Y&benchmark_symbol=SPY")
    assert response.status_code == 200
    figure = response.json()
    assert figure["layout"]["xaxis"]["title"]["text"] == "Sector"
    assert {
        trace["name"]: trace["meta"]["glossaryKey"] for trace in figure["data"]
    } == {
        "Allocation Effect (%)": "allocation_effect",
        "Selection Effect (%)": "selection_effect",
        "Interaction Effect (%)": "interaction_effect",
        "Total Active Return (%)": "total_active_return",
    }
    text = _VIEWER.read_text(encoding="utf-8")
    for trace in figure["data"]:
        assert f"{trace['meta']['glossaryKey']}: Object.freeze({{" in text


def test_1997_basket_consensus_columns_match_endpoint_shape() -> None:
    """The renderer must request only fields emitted by the endpoint."""
    widget = _widget("pi_basket_analyst_consensus")
    response = _CLIENT.get("/pi/equity/basket-analyst-consensus?basket_id=demo")
    assert response.status_code == 200
    rows = response.json()
    fields = {column["field"] for column in widget["data"]["table"]["columnsDefs"]}
    assert fields == {"symbol", "avg_target", "buy", "hold", "sell", "consensus"}
    assert all(fields <= set(row) for row in rows)
    assert "buy_hold_sell" not in fields
    # #1268: the response carries the display label, not the enum code.
    assert {row["consensus"] for row in rows} == {"Buy", "Strong Buy"}


def test_2007_smart_money_activity_labels_are_explicit() -> None:
    """#1268: activity types are labelled in the response."""
    response = _CLIENT.get("/pi/smart-money/ribbon?account_id=demo")
    assert response.status_code == 200
    assert {row["kind"] for row in response.json()} == {
        "Insider Buy",
        "13F Increase",
        "Insider Sell",
    }


def test_all_glossary_sources_are_https_non_generic_and_curated() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    sources = [
        source for source in __import__("re").findall(r'source: "([^"]+)"', text)
    ]
    assert len(sources) >= 64
    allowed_hosts = {
        "www.investopedia.com",
        "en.wikipedia.org",
        "www.cfainstitute.org",
    }
    for source in sources:
        parsed = urlparse(source)
        assert parsed.scheme == "https"
        assert parsed.netloc in allowed_hosts
        assert "financial-term-dictionary" not in parsed.path


def test_1991_earnings_surprise_help_uses_the_displayed_percentage_formula() -> None:
    """Both EPS-surprise help records must match the calculation behind Surprise (%)."""
    text = _VIEWER.read_text(encoding="utf-8")
    for key, label in (
        ("earnings_surprise", "Earnings Surprise"),
        ("eps_surprise", "EPS Surprise"),
    ):
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert (
            f'definition: "{label} (%) = (actual EPS - estimated EPS) / '
            'abs(estimated EPS) × 100."'
        ) in record


def test_2000_beta_glossary_uses_a_verified_beta_specific_reference() -> None:
    """Key-stat and portfolio beta help must cite the same beta reference."""
    text = _VIEWER.read_text(encoding="utf-8")
    expected_url = "https://en.wikipedia.org/wiki/Beta_(finance)"
    for key in ("beta", "beta_vs_spy"):
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert f'source: "{expected_url}"' in record


def test_dividend_payment_glossary_records_are_curated_and_https() -> None:
    text = _VIEWER.read_text(encoding="utf-8")
    for key, label, summary, source in (
        (
            "ex_dividend_date",
            "Ex-Dividend Date",
            "First trading day when a buyer is not entitled to the next dividend.",
            "https://www.investopedia.com/terms/e/ex-dividend.asp",
        ),
        (
            "dividend_amount_per_share",
            "Dividend Amount per Share",
            "Cash dividend declared for each share.",
            "https://www.investopedia.com/terms/d/dividend.asp",
        ),
    ):
        marker = f"{key}: Object.freeze({{"
        record = text[text.index(marker) : text.index("    }),", text.index(marker))]
        assert label in record
        assert summary in record
        assert f'source: "{source}"' in record


def test_2010_key_stats_columns_match_endpoint_shape() -> None:
    """Key-stat labels must be explicit without changing the endpoint rows."""
    widget = _widget("pi_equity_key_stats")
    response = _CLIENT.get("/pi/equity/key-stats?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Financial Metric"),
        ("value", "Value"),
    ]
    assert rows and all({"metric", "value"} <= set(row) for row in rows)


def test_2011_technicals_columns_match_endpoint_shape() -> None:
    """Technical rows retain their endpoint fields under explicit headers."""
    widget = _widget("pi_equity_technicals")
    response = _CLIENT.get("/pi/equity/technicals?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Technical Indicator"),
        ("value", "Value"),
        ("note", "Interpretation"),
    ]
    assert rows and all({"metric", "value", "note"} <= set(row) for row in rows)


def test_2012_event_calendar_columns_and_values_match_endpoint_shape() -> None:
    """Calendar metadata must label the raw event types emitted by its endpoint."""
    widget = _widget("pi_event_calendar")
    response = _CLIENT.get("/pi/events/calendar?account_id=demo&horizon_days=14")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("symbol", "Symbol"),
        ("type", "Event Type"),
        ("date", "Event Date"),
        ("detail", "Details"),
    ]
    event_type = columns[1]
    assert event_type["headerTooltip"] == _summary("event_type")
    for account_id in ("demo", "fixture"):
        response = _CLIENT.get(
            f"/pi/events/calendar?account_id={account_id}&horizon_days=14"
        )
        assert response.status_code == 200
        assert {row["type"] for row in response.json()} <= {
            "Earnings",
            "Ex-Dividend",
            "Form 8-K",
            "Information",
        }


def test_2013_forecast_columns_match_endpoint_shape() -> None:
    """Forecast metadata must preserve the endpoint's metric/value/note rows."""
    widget = _widget("pi_equity_analyst_forecasts")
    response = _CLIENT.get("/pi/equity/analyst-forecasts?symbol=AAPL")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Forecast Measure"),
        ("value", "Value"),
        ("note", "Context"),
    ]
    assert rows and all({"metric", "value", "note"} <= set(row) for row in rows)


def test_2014_whatif_columns_match_endpoint_shape() -> None:
    """What-if presentation labels must preserve before/after endpoint values."""
    widget = _widget("pi_whatif_card")
    response = _CLIENT.get("/pi/whatif/card?symbol=AAPL&delta_shares=100")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("metric", "Portfolio Metric"),
        ("before", "Before Trade"),
        ("after", "After Trade"),
        ("delta", "Change"),
    ]
    assert rows and all(
        {"metric", "before", "after", "delta"} <= set(row) for row in rows
    )


def test_2015_alert_columns_and_values_match_endpoint_shape() -> None:
    """Alert labels must map the endpoint's explicit alert category values."""
    widget = _widget("pi_alerts_panel")
    response = _CLIENT.get("/pi/alerts?account_id=demo")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("severity", "Severity"),
        ("kind", "Alert Type"),
        ("symbol", "Symbol"),
        ("detail", "Details"),
    ]
    alert_type = columns[1]
    assert alert_type["headerTooltip"] == _summary("alert_type")
    assert {
        "Held-Security Form 8-K",
        "Upcoming Earnings",
        "Material News",
    } <= {row["kind"] for row in rows}


def test_2016_news_columns_match_endpoint_shape_without_glossary() -> None:
    """News operational fields are explicit labels, not glossary concepts."""
    widget = _widget("pi_news_ribbon")
    response = _CLIENT.get("/pi/news?account_id=demo&horizon_days=7")
    assert response.status_code == 200
    rows = response.json()
    columns = widget["data"]["table"]["columnsDefs"]
    assert [(column["field"], column["headerName"]) for column in columns] == [
        ("symbol", "Symbol"),
        ("when", "Published"),
        ("title", "Headline"),
        ("severity", "Severity"),
    ]
    assert all("headerTooltip" not in column for column in columns)
    assert rows and all(
        {"symbol", "when", "title", "severity"} <= set(row) for row in rows
    )


def test_2017_sentiment_label_and_glossary_match_endpoint_shape() -> None:
    """#1268: the endpoint serves the labelled card; the value is unchanged."""
    response = _CLIENT.get("/pi/sentiment?account_id=demo")
    assert response.status_code == 200
    card = response.json()[0]
    assert card["label"] == "News Sentiment Score (-1 to +1)"
    assert _viewer_label_glossary()[card["label"]] == "news_sentiment_score"
    assert -1 <= card["value"] <= 1
