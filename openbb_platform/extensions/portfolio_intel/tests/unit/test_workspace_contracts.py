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
    """Every tolerated violation names the repair issue that removes it.

    #1271 cleared the last entries. The empty ledger stays as the
    shrink-only guard: any new violation fails until it is fixed or
    recorded here against a named repair issue.
    """
    baseline = load_debt_baseline(DEBT)
    assert set(baseline.values()) <= TRACKERS
    assert baseline == {}, "the #1264 program debt is fully repaid"


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
    """The strict entry point passes the served manifests and fails loudly.

    Since #1271 the served manifests carry no debt, so strict validation
    passes; two injected violations are both reported.
    """
    widgets, apps = _manifests()
    assert validate_workspace_manifests(widgets, apps, routes=_routes()) == []
    widgets["tt_scan_table"]["dataKey"] = "rows"
    widgets["tt_segment_movers"]["dataKey"] = "rows"
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_workspace_manifests(widgets, apps, routes=_routes())
    assert {(i.code, i.path) for i in excinfo.value.issues} == {
        ("widget.unknown_key", "widgets.tt_scan_table.dataKey"),
        ("widget.unknown_key", "widgets.tt_segment_movers.dataKey"),
    }


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
        (
            lambda _w, a: _terminal(a)["tabs"]["financials"]["layout"][3].update(
                x=10, y=8
            ),
            "layout.overlap",
        ),
        (
            lambda _w, a: _terminal(a)["tabs"]["technicals"]["layout"][3]["state"][
                "params"
            ].update(chart_type="bars"),
            "layout.state.param.value",
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


def _add_range_group(app_def: dict[str, Any]) -> str:
    """Prepend a valid static group and mark one price-history placement.

    The app keeps its own groups; the new group takes the next free
    ``Group N`` name and is placed first so mutations can target
    ``groups[0]``.
    """
    name = f"Group {len(app_def.get('groups', [])) + 1}"
    app_def["groups"] = [
        {
            "name": name,
            "type": "param",
            "paramName": "range",
            "defaultValue": "3M",
            "widgetIds": ["pi_equity_price_history"],
        },
        *app_def.get("groups", []),
    ]
    slot = next(
        p
        for p in app_def["tabs"]["overview"]["layout"]
        if p["i"] == "pi_equity_price_history"
    )
    slot["groups"] = [*slot.get("groups", []), name]
    return name


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
    ticker = next(g for g in terminal["groups"] if g["type"] == "ticker")
    ticker["widgetIds"].append("pi_alerts_panel")
    for placement in terminal["tabs"]["alerts"]["layout"]:
        if placement["i"] == "pi_alerts_panel":
            placement["groups"] = [*placement.get("groups", []), ticker["name"]]
    assert "symbol" not in {
        p["paramName"] for p in widgets["pi_alerts_panel"]["params"]
    }
    assert _new_codes(widgets, apps) == set()


def _one_widget_manifest(
    param: dict[str, Any], group: dict[str, Any] | None = None, **slot: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a one-widget, one-tab manifest for focused validator tests."""
    widgets = {
        "w1": {
            "name": "W",
            "description": "d",
            "endpoint": "w1",
            "type": "markdown",
            "params": [param],
        }
    }
    placement: dict[str, Any] = {"i": "w1", "x": 0, "y": 0, "w": 20, "h": 8, **slot}
    app: dict[str, Any] = {
        "id": "custom-x",
        "name": "X",
        "groups": [],
        "tabs": {"t": {"id": "t", "name": "T", "layout": [placement]}},
    }
    if group is not None:
        app["groups"] = [{**group, "name": "Group 1", "widgetIds": ["w1"]}]
        placement["groups"] = ["Group 1"]
    return widgets, [app]


def test_ticker_group_rejects_a_text_symbol_param() -> None:
    """Workspace's ticker group only writes ``type: ticker`` params.

    ``updateWidgetGroupValues`` resolves the target via ``getTickerParamName``,
    which returns the first ``ticker``-typed param; a ``text`` symbol param is
    never updated, so the link silently does nothing.
    """
    text = {"paramName": "symbol", "type": "text", "value": "AAPL"}
    widgets, apps = _one_widget_manifest(text, {"type": "ticker"})
    codes = {i.code for i in collect_manifest_issues(widgets, apps)}
    assert "group.type.mismatch" in codes
    ticker = {"paramName": "symbol", "type": "ticker", "value": "AAPL"}
    widgets, apps = _one_widget_manifest(ticker, {"type": "ticker"})
    assert not collect_manifest_issues(widgets, apps)


def test_state_param_value_must_be_an_inline_option() -> None:
    """A preset value outside a dropdown's options cannot be selected."""
    param = {
        "paramName": "range",
        "type": "text",
        "value": "1M",
        "options": [{"label": "1M", "value": "1M"}, {"label": "1Y", "value": "1Y"}],
    }
    widgets, apps = _one_widget_manifest(param, state={"params": {"range": "5Y"}})
    codes = {i.code for i in collect_manifest_issues(widgets, apps)}
    assert codes == {"layout.state.param.value"}
    widgets, apps = _one_widget_manifest(param, state={"params": {"range": "1Y"}})
    assert not collect_manifest_issues(widgets, apps)


def test_group_default_must_be_an_inline_option() -> None:
    """A static group's defaultValue must be one of the members' options."""
    param = {
        "paramName": "account_id",
        "type": "text",
        "value": "demo",
        "options": [{"label": "Demo", "value": "demo"}],
    }
    group = {"type": "param", "paramName": "account_id", "defaultValue": "acct-9"}
    widgets, apps = _one_widget_manifest(param, group)
    codes = {i.code for i in collect_manifest_issues(widgets, apps)}
    assert codes == {"group.default.value"}
    group["defaultValue"] = "demo"
    widgets, apps = _one_widget_manifest(param, group)
    assert not collect_manifest_issues(widgets, apps)


def test_empty_options_accept_any_value() -> None:
    """``options: []`` accepts any value, as ``isValidParamOption`` does.

    Workspace's runtime check is ``options?.length === 0 || ...``, so an
    empty list is a valid ``param``-group target with any default or preset.
    """
    param = {"paramName": "region", "type": "text", "value": "", "options": []}
    group = {"type": "param", "paramName": "region", "defaultValue": "EU"}
    widgets, apps = _one_widget_manifest(
        param, group, state={"params": {"region": "US"}}
    )
    assert not collect_manifest_issues(widgets, apps)


def test_multi_select_values_are_checked_by_containment() -> None:
    """A multi-select value is valid when it contains an option value.

    ``isValidParamOption`` tests ``String(groupValue).includes(option.value)``
    for some option; a list value stringifies to its comma-joined items.
    """
    param = {
        "paramName": "sector",
        "type": "text",
        "value": "Tech",
        "multiSelect": True,
        "options": [
            {"label": "Tech", "value": "Tech"},
            {"label": "Energy", "value": "Energy"},
        ],
    }
    group = {"type": "param", "paramName": "sector", "defaultValue": "Tech,Energy"}
    widgets, apps = _one_widget_manifest(
        param, group, state={"params": {"sector": ["Tech", "Energy"]}}
    )
    assert not collect_manifest_issues(widgets, apps)
    group["defaultValue"] = "Utilities"
    widgets, apps = _one_widget_manifest(
        param, group, state={"params": {"sector": ["Utilities"]}}
    )
    codes = sorted(i.code for i in collect_manifest_issues(widgets, apps))
    assert codes == ["group.default.value", "layout.state.param.value"]
    # A list stringifies like JavaScript (comma-joined, no brackets or quotes).
    param["options"] = [{"label": "Tech + Energy", "value": "Tech,Energy"}]
    widgets, apps = _one_widget_manifest(
        param, state={"params": {"sector": ["Tech", "Energy"]}}
    )
    assert not collect_manifest_issues(widgets, apps)


def _two_slot_app(second: dict[str, int], reverse: bool = False) -> list[ContractIssue]:
    widgets, apps = _one_widget_manifest(
        {"paramName": "symbol", "type": "ticker", "value": "AAPL"}
    )
    widgets["w2"] = {**widgets["w1"], "endpoint": "w2"}
    layout = apps[0]["tabs"]["t"]["layout"]
    layout.append({"i": "w2", **second})
    if reverse:
        layout.reverse()
    return collect_manifest_issues(widgets, apps)


def test_overlapping_placements_in_one_tab_are_rejected() -> None:
    """Two items sharing any grid cell overlap; touching edges do not."""
    overlap = _two_slot_app({"x": 19, "y": 7, "w": 10, "h": 4})
    assert [i.code for i in overlap] == ["layout.overlap"]
    assert "w1" in overlap[0].message and "w2" in overlap[0].message
    for reverse in (False, True):
        assert not _two_slot_app({"x": 20, "y": 0, "w": 20, "h": 8}, reverse)
        assert not _two_slot_app({"x": 0, "y": 8, "w": 40, "h": 4}, reverse)


def test_same_coordinates_in_different_tabs_do_not_overlap() -> None:
    """The overlap check is per tab."""
    widgets, apps = _one_widget_manifest(
        {"paramName": "symbol", "type": "ticker", "value": "AAPL"}
    )
    apps[0]["tabs"]["u"] = copy.deepcopy(apps[0]["tabs"]["t"])
    apps[0]["tabs"]["u"]["id"] = "u"
    assert not collect_manifest_issues(widgets, apps)


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
