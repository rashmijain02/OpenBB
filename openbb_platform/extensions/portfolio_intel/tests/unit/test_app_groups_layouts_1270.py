"""Native app groups, layouts, prompts and portable defaults (#1270).

The generic contract checks live in ``contracts.py`` (and
``test_workspace_contracts.py``). These tests pin the product decisions for
the three shipped apps: which widgets share the symbol and account context,
that every placement of a member carries its group, that presets agree with
the group defaults, that layouts use the grid sensibly, and that every widget
still works on its own from the Widget Gallery.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from openbb_portfolio_intel.widget_backend.contracts import APP_KEYS, GRID_COLUMNS

BACKEND = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)
WIDGETS: dict[str, Any] = json.loads(
    (BACKEND / "widgets.json").read_text(encoding="utf-8")
)
APPS: list[dict[str, Any]] = json.loads(
    (BACKEND / "apps.json").read_text(encoding="utf-8")
)
OVERVIEW = "custom-portfolio-intelligence-overview"
TERMINAL = "custom-portfolio-intelligence-terminal"
TECHTRADE = "custom-techtrade-desk"
ALL_APPS = (OVERVIEW, TERMINAL, TECHTRADE)
ACCOUNT_APPS = (OVERVIEW, TERMINAL)
# Discovery tables join the symbol group without a symbol param
# (third_party/workspace .../guides/review-app.md, "Click-through and discovery").
DISCOVERY = {TECHTRADE: {"tt_scan_table"}}
DEMO_ACCOUNT = "demo"
DEFAULT_SYMBOL = "AAPL"


def _app(app_id: str) -> dict[str, Any]:
    return next(a for a in APPS if a["id"] == app_id)


def _placements(app: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(tab_id, p) for tab_id, tab in app["tabs"].items() for p in tab["layout"]]


def _param_names(widget_id: str) -> set[str]:
    return {p["paramName"] for p in WIDGETS[widget_id].get("params", [])}


def _placed_with(app: dict[str, Any], param: str) -> set[str]:
    return {p["i"] for _tab, p in _placements(app) if param in _param_names(p["i"])}


def _group(app: dict[str, Any], group_type: str, param: str | None = None) -> dict:
    found = [
        g
        for g in app.get("groups", [])
        if g["type"] == group_type and (param is None or g.get("paramName") == param)
    ]
    assert len(found) == 1, f"{app['id']}: expected one {group_type} {param} group"
    return found[0]


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_app_uses_schema_native_keys_only(app_id: str) -> None:
    """App-level ``params`` / ``guidedTour`` moved into groups and prompts."""
    app = _app(app_id)
    assert set(app) <= APP_KEYS, sorted(set(app) - APP_KEYS)
    assert {"groups", "prompts", "description", "allowCustomization"} <= set(app)


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_app_offers_suggested_prompts(app_id: str) -> None:
    """Every app suggests at least three distinct, non-blank agent prompts."""
    prompts = _app(app_id)["prompts"]
    assert isinstance(prompts, list) and len(prompts) >= 3
    assert all(isinstance(p, str) and p.strip() == p and p for p in prompts)
    assert len(set(prompts)) == len(prompts)


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_symbol_group_links_every_symbol_widget(app_id: str) -> None:
    """One ticker group holds every symbol-driven widget plus discovery tables."""
    app = _app(app_id)
    group = _group(app, "ticker")
    expected = _placed_with(app, "symbol") | DISCOVERY.get(app_id, set())
    assert set(group["widgetIds"]) == expected
    assert group["defaultValue"] == DEFAULT_SYMBOL


@pytest.mark.parametrize("app_id", ACCOUNT_APPS)
def test_account_group_links_every_account_widget(app_id: str) -> None:
    """One static account group holds every account-scoped widget."""
    app = _app(app_id)
    group = _group(app, "param", "account_id")
    assert set(group["widgetIds"]) == _placed_with(app, "account_id")
    assert group["defaultValue"] == DEMO_ACCOUNT


def test_techtrade_has_no_account_scoped_widgets() -> None:
    """TechTrade needs no account group: none of its widgets take an account."""
    assert not _placed_with(_app(TECHTRADE), "account_id")


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_every_placement_of_a_member_carries_its_group(app_id: str) -> None:
    """A member placed on several tabs is linked on every tab, not just one."""
    app = _app(app_id)
    for group in app["groups"]:
        for tab_id, placement in _placements(app):
            if placement["i"] in group["widgetIds"]:
                assert group["name"] in placement.get(
                    "groups", []
                ), f"{app_id}.{tab_id}.{placement['i']} misses {group['name']}"


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_grouped_presets_agree_with_the_group_default(app_id: str) -> None:
    """A grouped placement never presets a different value than its group."""
    app = _app(app_id)
    by_name = {g["name"]: g for g in app["groups"]}
    for tab_id, placement in _placements(app):
        preset = placement.get("state", {}).get("params", {})
        for name in placement.get("groups", []):
            group = by_name[name]
            param = group.get("paramName", "symbol")
            if param in preset:
                assert (
                    preset[param] == group["defaultValue"]
                ), f"{app_id}.{tab_id}.{placement['i']}: {param}={preset[param]!r}"


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_every_tab_uses_the_full_grid_width(app_id: str) -> None:
    """No tab leaves its right-hand columns empty."""
    for tab_id, tab in _app(app_id)["tabs"].items():
        right = max(p["x"] + p["w"] for p in tab["layout"])
        assert right == GRID_COLUMNS, f"{app_id}.{tab_id} ends at column {right}"


# Minimum heights by widget type, in grid rows (review-app.md section 4:
# metrics 4-6, tables 8-15, charts 12-15; context bars are one-line markdown).
MIN_HEIGHT = {"metric": 4, "table": 6, "chart": 8, "markdown": 3}
MAX_METRIC_HEIGHT = 8
MIN_WIDTH = 8


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_placement_sizes_are_sensible(app_id: str) -> None:
    """Each placement is big enough for its widget type and not oversized."""
    for tab_id, placement in _placements(_app(app_id)):
        kind = WIDGETS[placement["i"]]["type"]
        where = f"{app_id}.{tab_id}.{placement['i']}"
        assert placement["w"] >= MIN_WIDTH, where
        assert placement["h"] >= MIN_HEIGHT[kind], where
        if kind == "metric":
            assert placement["h"] <= MAX_METRIC_HEIGHT, where


def _values(param: dict[str, Any]) -> list[Any]:
    return [param.get("value")] + [o.get("value") for o in param.get("options", [])]


def test_defaults_are_portable_demo_values() -> None:
    """Account and basket defaults are the synthetic demo everywhere."""
    for widget_id, widget in WIDGETS.items():
        for param in widget.get("params", []):
            if param["paramName"] in {"account_id", "basket_id"}:
                assert set(_values(param)) == {DEMO_ACCOUNT}, widget_id
    for app in APPS:
        for group in app["groups"]:
            if group.get("paramName") == "account_id":
                assert group["defaultValue"] == DEMO_ACCOUNT
        for tab_id, placement in _placements(app):
            preset = placement.get("state", {}).get("params", {})
            for name in ("account_id", "basket_id"):
                if name in preset:
                    assert preset[name] == DEMO_ACCOUNT, f"{tab_id}.{placement['i']}"


@pytest.mark.parametrize("widget_id", sorted(WIDGETS))
def test_widget_is_usable_alone_from_the_gallery(widget_id: str) -> None:
    """Outside any app, every param has a label and a selectable default.

    The hermetic endpoint probe (``test_workspace_endpoint_contracts.py``)
    calls every widget with exactly these defaults and no app state.
    """
    for param in WIDGETS[widget_id].get("params", []):
        name = param["paramName"]
        assert param.get("label") and "value" in param, f"{widget_id}.{name}"
        options = param.get("options")
        if options:
            assert param["value"] in [
                o["value"] for o in options
            ], f"{widget_id}.{name}"
        if name == "symbol":
            assert param["type"] == "ticker", f"{widget_id}.symbol must be ticker"
            assert param["value"] == DEFAULT_SYMBOL
        if name == "account_id":
            assert param["type"] == "text" and options, f"{widget_id}.account_id"


# Developer-facing markers that must never reach user-facing app text:
# notebook ids, issue / branch references, tracker ids, wiring notes.
INTERNAL_MARKERS = (
    r"\bNB\d+\b",
    r"#\d+",
    r"\bgh-\d+\b",
    r"\bbd-\w+",
    r"\bEPIC\b",
    r"\bT\d+\.\d+\b",
    r"\bTODO\b|\bFIXME\b",
    r"\buntil\b.*\bwired\b",
    r"\bnot (yet )?wired\b",
    r"\bstub(bed)?\b",
)


def test_internal_marker_patterns_catch_known_leaks() -> None:
    """The marker list flags the exact leaks a review found (and plain text passes)."""
    leaks = [
        "Ground yourself on a single symbol (NB01).",
        "demo basket only until basket input is wired.",
        "extended with X-Ray (EPIC #1634).",
    ]
    for text in leaks:
        assert any(re.search(p, text) for p in INTERNAL_MARKERS), text
    assert not any(
        re.search(p, "How is my portfolio split across sectors?")
        for p in INTERNAL_MARKERS
    )


@pytest.mark.parametrize("app_id", ALL_APPS)
def test_user_facing_app_text_has_no_internal_markers(app_id: str) -> None:
    """Prompts and the description read as plain language for Workspace users."""
    app = _app(app_id)
    for text in [*app["prompts"], app["description"]]:
        hits = [p for p in INTERNAL_MARKERS if re.search(p, text)]
        assert not hits, f"{app_id}: {hits} in {text!r}"
