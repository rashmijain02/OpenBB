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
