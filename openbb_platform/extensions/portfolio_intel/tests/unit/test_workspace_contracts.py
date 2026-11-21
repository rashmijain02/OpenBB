"""Mutation tests for native OpenBB Workspace manifest contracts (#1266)."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
# pylint: disable=wrong-import-position

from openbb_portfolio_intel.widget_backend.contracts import (  # noqa: E402
    ContractIssue,
    ManifestValidationError,
    collect_manifest_issues,
    compare_with_baseline,
    load_debt_baseline,
    validate_workspace_manifests,
)
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

BACKEND = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)
DEBT = Path(__file__).resolve().parent / "fixtures" / "workspace_contract_debt.json"
TRACKERS = {"#1267", "#1268", "#1269", "#1270", "#1271", "#1272"}


def _manifests() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return fresh copies of the checked-in Portfolio manifests."""
    widgets = json.loads((BACKEND / "widgets.json").read_text(encoding="utf-8"))
    apps = json.loads((BACKEND / "apps.json").read_text(encoding="utf-8"))
    return widgets, apps


def _routes() -> set[str]:
    """Return registered FastAPI routes for endpoint parity validation."""
    return {route.path for route in app.routes}


def _terminal(apps: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the Portfolio Intelligence Terminal app definition."""
    return next(a for a in apps if a["id"] == "custom-portfolio-intelligence-terminal")


def _manifest_debt() -> dict[tuple[str, str], str]:
    """Return the manifest section of the debt baseline."""
    return {
        **load_debt_baseline(DEBT, prefix="widgets."),
        **load_debt_baseline(DEBT, prefix="apps."),
    }


def _new_codes(widgets: dict[str, Any], apps: list[dict[str, Any]]) -> set[str]:
    """Return codes of issues that are not recorded debt (i.e. regressions)."""
    issues = collect_manifest_issues(widgets, apps, routes=_routes())
    new, _resolved = compare_with_baseline(issues, _manifest_debt())
    return {issue.code for issue in new}


def test_served_manifests_match_recorded_debt_exactly() -> None:
    """Served manifests may only carry recorded debt; fixed debt must be removed."""
    client = TestClient(app)
    widgets = client.get("/widgets.json").json()
    apps = client.get("/apps.json").json()
    issues = collect_manifest_issues(widgets, apps, routes=_routes())
    new, resolved = compare_with_baseline(issues, _manifest_debt())
    assert not new, f"new Workspace contract violations: {new}"
    assert not resolved, f"fixed debt still in baseline, remove it: {resolved}"


def test_debt_baseline_entries_are_owned_by_open_repair_issues() -> None:
    """Every tolerated violation names the repair issue that removes it."""
    baseline = load_debt_baseline(DEBT)
    assert baseline, "an empty baseline should be deleted, not kept"
    assert set(baseline.values()) <= TRACKERS


def test_baseline_comparison_reports_regressions_and_resolutions() -> None:
    """The shrink-only comparison flags both directions."""
    kept = ContractIssue("a", "x", "m")
    added = ContractIssue("b", "y", "m")
    new, resolved = compare_with_baseline(
        [kept, added], {("a", "x"): "#1268", ("c", "z"): "#1268"}
    )
    assert new == [added]
    assert resolved == [("c", "z")]


def test_validate_raises_with_every_issue() -> None:
    """The strict entry point fails loudly with structured issues."""
    widgets, apps = _manifests()
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_workspace_manifests(widgets, apps, routes=_routes())
    assert len(excinfo.value.issues) == len(_manifest_debt())


def test_minimal_valid_manifest_passes() -> None:
    """A schema-clean manifest validates to an empty list."""
    widgets = {
        "w1": {
            "name": "W",
            "description": "d",
            "endpoint": "w1",
            "type": "table",
            "gridData": {"w": 20, "h": 8},
            "data": {"table": {"columnsDefs": [{"field": "a", "headerName": "A"}]}},
            "params": [{"paramName": "symbol", "type": "ticker", "value": "AAPL"}],
        }
    }
    apps = [
        {
            "id": "custom-x",
            "name": "X",
            "groups": [{"name": "Group 1", "type": "ticker", "widgetIds": ["w1"]}],
            "tabs": {
                "t": {
                    "id": "t",
                    "name": "T",
                    "layout": [
                        {
                            "i": "w1",
                            "x": 20,
                            "y": 0,
                            "w": 20,
                            "h": 8,
                            "groups": ["Group 1"],
                        }
                    ],
                }
            },
        }
    ]
    assert not validate_workspace_manifests(widgets, apps, routes={"/w1"})


Mutation = Callable[[dict[str, Any], list[dict[str, Any]]], object]


def _set_column_header(widgets: dict[str, Any], _apps: Any) -> None:
    widgets["pi_lookthrough_top25"]["data"]["table"]["columnsDefs"][0].pop("headerName")


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda w, _a: w["pi_xray_sector"].pop("description"),
            "widget.required.description",
        ),
        (lambda w, _a: w["pi_xray_sector"].update(type="pie"), "widget.type"),
        (lambda w, _a: w["pi_xray_sector"].update(raw="yes"), "widget.raw"),
        (lambda w, _a: w["pi_xray_sector"].update(colour="red"), "widget.unknown_key"),
        (
            lambda w, _a: w["pi_symbol_context"].update(endpoint="pi/missing"),
            "widget.endpoint.missing",
        ),
        (_set_column_header, "widget.table.column.headerName"),
        (
            lambda w, _a: w["pi_symbol_context"]["params"][0].update(type="slider"),
            "widget.param.type",
        ),
        (
            lambda _w, a: _terminal(a)["tabs"]["overview"]["layout"][0].update(
                x=35, w=10
            ),
            "layout.width",
        ),
        (lambda _w, a: _terminal(a).update(id="terminal"), "app.id"),
        (lambda _w, a: _terminal(a).update(id="custom-"), "app.id"),
        (
            lambda w, _a: w["pi_lookthrough_top25"]["data"]["table"]["columnsDefs"][
                0
            ].update(tooltipText="x"),
            "widget.table.column.unknown_key",
        ),
    ],
)
def test_widget_and_layout_mutations_are_rejected(
    mutation: Mutation, expected_code: str
) -> None:
    """Each load-bearing contract mutation fails independently of recorded debt."""
    widgets, apps = _manifests()
    assert _new_codes(widgets, apps) == set()
    mutation(widgets, apps)
    assert expected_code in _new_codes(widgets, apps)


def _add_range_group(app_def: dict[str, Any], name: str = "Group 1") -> None:
    """Add a valid static group and mark one price-history placement."""
    app_def["groups"] = [
        {
            "name": name,
            "type": "param",
            "paramName": "range",
            "defaultValue": "3M",
            "widgetIds": ["pi_equity_price_history"],
        }
    ]
    slot = next(
        p
        for p in app_def["tabs"]["overview"]["layout"]
        if p["i"] == "pi_equity_price_history"
    )
    slot["groups"] = [name]


def test_valid_app_parameter_group_passes() -> None:
    """A widget, layout, and group with one static contract adds no issue."""
    widgets, apps = _manifests()
    _add_range_group(_terminal(apps))
    assert _new_codes(widgets, apps) == set()


def _drop_layout_group(app_def: dict[str, Any]) -> None:
    for tab in app_def["tabs"].values():
        for placement in tab["layout"]:
            placement.pop("groups", None)


@pytest.mark.parametrize(
    ("mutate_app", "expected_code"),
    [
        (
            lambda a: a["tabs"]["overview"]["layout"][0].update(i="not-a-widget"),
            "layout.widget.missing",
        ),
        (
            lambda a: a["tabs"]["overview"]["layout"][0]["state"]["params"].update(
                unknown_param="x"
            ),
            "layout.state.param",
        ),
        (
            lambda a: a["groups"][0].update(paramName="not_a_param"),
            "group.param.missing",
        ),
        (lambda a: a["groups"][0].update(type="endpointParam"), "group.type.mismatch"),
        (lambda a: a["groups"][0].update(type="slider"), "group.type"),
        (lambda a: a["groups"][0].update(name="Prices"), "group.name.convention"),
        (lambda a: a["groups"][0].pop("paramName"), "group.paramName"),
        (_drop_layout_group, "group.layout.missing"),
        (
            lambda a: a["tabs"]["overview"]["layout"][0].update(groups=["Group 9"]),
            "layout.group.missing",
        ),
    ],
)
def test_app_and_group_mutations_are_rejected(
    mutate_app: Callable[[dict[str, Any]], object], expected_code: str
) -> None:
    """Layout and group drift must fail against the actual widget param model."""
    widgets, apps = _manifests()
    terminal = _terminal(apps)
    _add_range_group(terminal)
    mutate_app(terminal)
    assert expected_code in _new_codes(widgets, apps)


def test_ticker_group_accepts_member_without_symbol_param() -> None:
    """Discovery widgets may join a symbol group without a symbol param."""
    widgets, apps = _manifests()
    terminal = _terminal(apps)
    terminal["groups"] = [
        {"name": "Group 1", "type": "ticker", "widgetIds": ["pi_alerts_panel"]}
    ]
    for placement in terminal["tabs"]["alerts"]["layout"]:
        if placement["i"] == "pi_alerts_panel":
            placement["groups"] = ["Group 1"]
    assert "symbol" not in {
        p["paramName"] for p in widgets["pi_alerts_panel"]["params"]
    }
    assert _new_codes(widgets, apps) == set()


def test_static_param_group_requires_inline_options() -> None:
    """A ``param`` group cannot bind a widget param that has no options."""
    widgets, apps = _manifests()
    _add_range_group(_terminal(apps))
    for param in widgets["pi_equity_price_history"]["params"]:
        if param["paramName"] == "range":
            param.pop("options")
    assert "group.type.mismatch" in _new_codes(widgets, apps)


def test_widget_param_option_endpoint_must_be_registered() -> None:
    """Dynamic dropdowns cannot point at a missing backend route."""
    widgets, apps = _manifests()
    symbol = widgets["pi_symbol_context"]["params"][0]
    symbol.update(type="endpoint", optionsEndpoint="/missing-options")
    assert "widget.param.options_endpoint.missing" in _new_codes(widgets, apps)


def test_mutation_inputs_are_isolated_from_the_source_fixture() -> None:
    """A test mutation cannot poison another validation call."""
    widgets, _apps = _manifests()
    original = copy.deepcopy(widgets)
    widgets["pi_xray_sector"]["name"] = "mutated"
    assert _manifests()[0] == original
