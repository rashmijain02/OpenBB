"""Regression guard for the native OpenBB Workspace capability matrix."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts" / "build_portfolio_workspace_matrix.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "native_workspace_matrix.json"
BACKEND = (
    ROOT
    / "openbb_platform"
    / "extensions"
    / "portfolio_intel"
    / "openbb_portfolio_intel"
    / "widget_backend"
)


def _load_builder():
    """Load the inventory builder without requiring an OpenBB installation."""
    spec = importlib.util.spec_from_file_location("portfolio_workspace_matrix", SCRIPT)
    assert spec and spec.loader, f"missing matrix builder: {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_workspace_matrix_matches_checked_in_baseline() -> None:
    """The committed inventory must exactly represent the current manifests."""
    builder = _load_builder()
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == builder.build_matrix(
        BACKEND
    )


def test_native_workspace_matrix_has_complete_known_surface() -> None:
    """Known apps/widgets/placements cannot silently disappear from the baseline."""
    builder = _load_builder()
    matrix = builder.build_matrix(BACKEND)

    assert matrix["summary"] == {
        "apps": 3,
        "placements": 96,
        "widgets": 61,
        "types": {
            "chart": 14,
            "markdown": 14,
            "metric": 4,
            "table": 29,
        },
    }
    assert all(widget["endpointRegistered"] for widget in matrix["widgets"])
    assert matrix["unknownAppPlacements"] == []


def test_native_workspace_matrix_classifies_every_manifest_contract() -> None:
    """Every capability enters the repair plan with an explicit manifest class."""
    builder = _load_builder()
    matrix = builder.build_matrix(BACKEND)

    allowed = {
        "native-ready",
        "contract-repair",
        "provider-repair",
        "explicit-demo",
        "gate-required",
    }
    assert {widget["baselineState"] for widget in matrix["widgets"]} <= allowed
    assert not [
        widget["id"] for widget in matrix["widgets"] if not widget["baselineState"]
    ]


_PLOTLY_CHARTS = {
    # Native Plotly figure by default, raw rows with raw=true (#1267, #1268).
    "pi_brinson_attribution": "native-ready",
    "pi_charting": "native-ready",
    "pi_equity_financial_charts": "native-ready",
    "pi_equity_price_history": "native-ready",
    "pi_price_target_history": "native-ready",
    "pi_revenue_business_line": "native-ready",
    "pi_revenue_geography": "native-ready",
    "pi_stock_ownership": "native-ready",
    # Account-scoped demo widgets keep their demo classification.
    "pi_paper_performance": "explicit-demo",
    "pi_risk_vol_chart": "explicit-demo",
    "pi_xray_country": "explicit-demo",
    "pi_xray_sector": "explicit-demo",
}


def test_native_plotly_chart_widgets_are_recognised() -> None:
    """Plotly-figure endpoints count as native charts without ``data.chart``."""
    builder = _load_builder()
    by_id = {w["id"]: w for w in builder.build_matrix(BACKEND)["widgets"]}
    for widget_id, state in _PLOTLY_CHARTS.items():
        assert by_id[widget_id]["chart"]["plotly"] is True, widget_id
        assert by_id[widget_id]["baselineState"] == state, widget_id
    # TechTrade charts still return row envelopes (#1271): not Plotly yet.
    for widget_id in ("tt_segment_movers", "tt_simulate_result"):
        assert by_id[widget_id]["chart"]["plotly"] is False, widget_id
        assert by_id[widget_id]["baselineState"] == "contract-repair", widget_id


def test_plotly_route_detection_reads_the_decorator_and_raw_parameter() -> None:
    """Routes are Plotly when wrapped by ``plotly_chart`` or taking ``raw``."""
    builder = _load_builder()
    routes = builder._plotly_routes(BACKEND)  # pylint: disable=protected-access
    assert {"/pi/xray/sector", "/pi/attribution", "/pi/equity/charting"} <= routes
    assert "/tt/scan/segment-movers" not in routes
    assert "/pi/lookthrough/top25" not in routes
