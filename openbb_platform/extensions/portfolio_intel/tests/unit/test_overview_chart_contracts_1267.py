"""Native Workspace chart contracts for the Portfolio Overview (#1267).

``pi_xray_sector`` and ``pi_brinson_attribution`` are ``type: chart`` widgets.
Workspace renders a chart endpoint's default response as a Plotly figure
(``{"data": [...], "layout": {...}}``) and, because both declare
``raw: true``, calls the same endpoint with ``raw=true`` when the user switches
to the raw view. These tests pin both modes, the explicit demo/unavailable
states, and the manifest keys Workspace's schema accepts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.contracts import collect_response_issues
from openbb_portfolio_intel.widget_backend.main import app

_BACKEND = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)
_WIDGETS: dict[str, Any] = json.loads(
    (_BACKEND / "widgets.json").read_text(encoding="utf-8")
)
_CLIENT = TestClient(app)

_DEMO_SECTORS = [
    ("Information Technology", 0.38),
    ("Healthcare", 0.22),
    ("Financials", 0.15),
    ("Consumer Discretionary", 0.12),
    ("Energy", 0.08),
    ("Other", 0.05),
]
_BRINSON_SERIES = [
    ("allocation", "Allocation Effect (%)", "allocation_effect"),
    ("selection", "Selection Effect (%)", "selection_effect"),
    ("interaction", "Interaction Effect (%)", "interaction_effect"),
    ("total", "Total Active Return (%)", "total_active_return"),
]


_PROVENANCE = ("data_state", "data_source", "data_as_of")


def _strip(rows: Any) -> Any:
    """Drop the #1269 provenance columns (asserted as strings) from raw rows."""
    assert isinstance(rows, list)
    for row in rows:
        assert all(isinstance(row[key], str) for key in _PROVENANCE), row
    return [{k: v for k, v in row.items() if k not in _PROVENANCE} for row in rows]


def _get(path: str) -> Any:
    response = _CLIENT.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _annotation_text(figure: dict[str, Any]) -> str:
    return " ".join(a["text"] for a in figure["layout"].get("annotations", []))


def _assert_contract_clean(widget_id: str, path: str) -> None:
    response = _CLIENT.get(path)
    issues = collect_response_issues(
        widget_id, _WIDGETS[widget_id], response.status_code, response.text
    )
    assert not issues, issues


# ---------------------------------------------------------------------------
# X-Ray sector
# ---------------------------------------------------------------------------


def test_xray_sector_default_is_a_plotly_pie_of_the_demo_rows() -> None:
    """Default response is one pie trace over the demo rows, labelled demo."""
    figure = _get("/pi/xray/sector?account_id=demo")
    assert set(figure) == {"data", "layout"}
    [trace] = figure["data"]
    assert trace["type"] == "pie"
    assert trace["labels"] == [sector for sector, _ in _DEMO_SECTORS]
    assert trace["values"] == [weight for _, weight in _DEMO_SECTORS]
    assert figure["layout"]["meta"]["state"] == "demo"
    # Workspace supplies the widget title (#1268); the state is an annotation.
    assert "title" not in figure["layout"]
    assert "demo" in _annotation_text(figure).lower()
    _assert_contract_clean("pi_xray_sector", "/pi/xray/sector?account_id=demo")


def test_xray_sector_raw_mode_keeps_the_sector_weight_rows() -> None:
    """``raw=true`` keeps the original ``{sector, weight}`` rows."""
    rows = _strip(_get("/pi/xray/sector?account_id=demo&raw=true"))
    assert rows == [{"sector": s, "weight": w} for s, w in _DEMO_SECTORS]


def test_xray_sector_unwired_account_is_an_explicit_unavailable_figure() -> None:
    """An unwired account is an explicit unavailable figure, not fake data."""
    figure = _get("/pi/xray/sector?account_id=NOT_WIRED_YET")
    assert figure["layout"]["meta"]["state"] == "unavailable"
    # No trace pretends to be data: the state is carried by meta + annotation.
    assert figure["data"] == []
    assert "title" not in figure["layout"]
    assert "account resolver not wired" in _annotation_text(figure)
    _assert_contract_clean("pi_xray_sector", "/pi/xray/sector?account_id=NOT_WIRED")
    rows = _get("/pi/xray/sector?account_id=NOT_WIRED_YET&raw=true")
    assert rows and rows[0]["weight"] == 0.0


# ---------------------------------------------------------------------------
# Brinson-Fachler attribution
# ---------------------------------------------------------------------------


def test_brinson_raw_mode_keeps_the_percentage_point_rows() -> None:
    """``raw=true`` keeps the percentage-point attribution rows."""
    rows = _strip(_get("/pi/attribution?window=1Y&benchmark_symbol=SPY&raw=true"))
    assert isinstance(rows, list) and rows
    assert set(rows[0]) == {"sector", "allocation", "selection", "interaction", "total"}
    assert rows[0]["sector"] == "S0"
    assert rows[0]["allocation"] == pytest.approx(-0.06843181714558489)


def test_brinson_default_is_a_plotly_figure_built_from_the_same_rows() -> None:
    """Each trace plots one row field unchanged, with its label and help key."""
    rows = _get("/pi/attribution?window=1Y&benchmark_symbol=SPY&raw=true")
    figure = _get("/pi/attribution?window=1Y&benchmark_symbol=SPY")
    assert set(figure) == {"data", "layout"}
    traces = figure["data"]
    assert [t["name"] for t in traces] == [label for _, label, _ in _BRINSON_SERIES]
    sectors = [row["sector"] for row in rows]
    for trace, (field, _label, glossary_key) in zip(traces, _BRINSON_SERIES):
        assert trace["x"] == sectors
        assert trace["y"] == [row[field] for row in rows]
        assert trace["meta"] == {"glossaryKey": glossary_key}
        assert trace["hovertemplate"].endswith("<extra></extra>")
    assert [t["type"] for t in traces] == ["bar", "bar", "bar", "scatter"]
    assert figure["layout"]["barmode"] == "relative"
    assert figure["layout"]["xaxis"]["title"]["text"] == "Sector"
    assert "percentage points" in figure["layout"]["yaxis"]["title"]["text"]
    _assert_contract_clean(
        "pi_brinson_attribution", "/pi/attribution?window=1Y&benchmark_symbol=SPY"
    )


def test_brinson_figure_labels_the_synthetic_demo_book_and_parameters() -> None:
    """The annotation says the book is synthetic and echoes the params.

    Workspace supplies the widget title, so the figure sets none (#1268).
    """
    figure = _get("/pi/attribution?window=3M&benchmark_symbol=QQQ")
    assert figure["layout"]["meta"]["state"] == "demo"
    assert "title" not in figure["layout"]
    note = _annotation_text(figure)
    assert "demo" in note.lower() and "3M" in note and "QQQ" in note
    assert "synthetic" in note.lower()


def test_brinson_hover_carries_the_glossary_summaries() -> None:
    """Hover text carries the glossary definitions Workspace users rely on."""
    figure = _get("/pi/attribution?window=1Y&benchmark_symbol=SPY")
    hovers = [trace["hovertemplate"] for trace in figure["data"]]
    assert "benchmark-relative segment weights" in hovers[0]
    assert "security selection within segments" in hovers[1]
    assert "Portfolio return minus benchmark return" in hovers[3]


# ---------------------------------------------------------------------------
# Shared figure states and manifest
# ---------------------------------------------------------------------------


def test_empty_brinson_rows_render_an_explicit_empty_state() -> None:
    """No rows gives a trace-free figure that says why."""
    from openbb_portfolio_intel.widget_backend.overview_charts import (
        brinson_attribution_figure,
    )

    from openbb_portfolio_intel.widget_backend.provenance import (
        DataState,
        Provenance,
    )

    figure = brinson_attribution_figure(
        [], Provenance(DataState.DEMO, "stub", "synthetic demo book")
    )
    assert figure["data"] == []
    # #1269: an empty result is "unavailable", never a success shape.
    assert figure["layout"]["meta"]["state"] == "unavailable"
    assert "no attribution rows" in _annotation_text(figure).lower()


@pytest.mark.parametrize("widget_id", ["pi_xray_sector", "pi_brinson_attribution"])
def test_overview_chart_manifest_uses_only_schema_keys(widget_id: str) -> None:
    """Only Workspace-schema ``data`` keys remain; raw mode stays declared."""
    widget = _WIDGETS[widget_id]
    assert widget["type"] == "chart"
    assert widget["raw"] is True
    assert "data" not in widget or not set(widget["data"]) - {
        "dataKey",
        "table",
        "wsRowIdColumn",
    }


def test_brinson_description_keeps_the_effect_definitions() -> None:
    """The removed glossary metadata survives as description text."""
    description = _WIDGETS["pi_brinson_attribution"]["description"]
    for label in (
        "Allocation Effect",
        "Selection Effect",
        "Interaction Effect",
        "Total Active Return",
        "percentage points",
        "raw",
    ):
        assert label in description, label
