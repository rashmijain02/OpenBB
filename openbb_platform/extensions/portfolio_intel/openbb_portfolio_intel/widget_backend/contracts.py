"""Validate OpenBB Workspace widget and app manifests (#1266).

Every rule here is grounded in the pinned OpenBB Workspace source
(``third_party/workspace``, Apache-2.0):

- widget schema: ``terminalpro/src/components/DataConnectors/WidgetsBuilder/
  widget-schema.json`` (``additionalProperties: false`` at widget, ``data``
  and ``data.table`` level);
- apps schema: ``terminalpro/apps-schema.json``;
- runtime notes: ``backend-api/backend/workspace_mcp/app_builder/resources``
  (group types, ``Group N`` names, 40-column grid).

Rules the pinned source does not establish are deliberately not enforced.
Cross-references a JSON schema cannot express (registered routes, group
membership, layout params) are validated on top of the schema rules.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from openbb_portfolio_intel.widget_backend.provenance import (
    BODY_STATES,
    DATA_STATE_LABEL,
    MARKDOWN_STATE_RE,
    METRIC_STATE_RE,
    ROW_FIELDS,
)

WIDGET_TYPES = frozenset(
    {
        "advanced_charting",
        "chart",
        "chart-highcharts",
        "chart-vegalite",
        "file_viewer",
        "html",
        "iframe",
        "live_grid",
        "markdown",
        "metric",
        "multi_file_viewer",
        "newsfeed",
        "note",
        "omni",
        "pdf",
        "ssrm_advanced",
        "ssrm_table",
        "table",
    }
)
WIDGET_KEYS = frozenset(
    {
        "category",
        "data",
        "dataUpdateDisplay",
        "defaultViz",
        "description",
        "disableRetrievalForCopilot",
        "endpoint",
        "fileEndpoint",
        "gridData",
        "groupById",
        "name",
        "params",
        "raw",
        "refetchInterval",
        "runButton",
        "showTitle",
        "source",
        "staleTime",
        "subCategory",
        "type",
        "widgetId",
        "widgetType",
        "wsEndpoint",
    }
)
WIDGET_REQUIRED = ("name", "description", "endpoint", "type")
DATA_KEYS = frozenset({"dataKey", "table", "wsRowIdColumn"})
TABLE_KEYS = frozenset(
    {"chartView", "columnsDefs", "enableCharts", "period", "showAll", "transpose"}
)
PARAM_TYPES = frozenset(
    {"boolean", "button", "date", "endpoint", "form", "number", "text", "ticker"}
)
APP_KEYS = frozenset(
    {
        "allowCustomization",
        "authentication",
        "description",
        "groups",
        "id",
        "img",
        "img_dark",
        "img_light",
        "mcpServers",
        "name",
        "prompts",
        "selected_agent",
        "tabs",
        "templateId",
    }
)
TAB_KEYS = frozenset({"id", "layout", "name"})
GROUP_KEYS = frozenset({"defaultValue", "name", "paramName", "type", "widgetIds"})
GROUP_TYPES = frozenset({"endpointParam", "param", "ticker"})
GROUP_NAME_RE = re.compile(r"^Group [1-9][0-9]*$")
APP_ID_RE = re.compile(r"^custom-.+")
COLUMN_KEYS = frozenset(
    {
        "aggFunc",
        "cellDataType",
        "chartDataType",
        "enableCellChangeWs",
        "field",
        "formatterFn",
        "headerName",
        "headerTooltip",
        "hide",
        "maxWidth",
        "minWidth",
        "pinned",
        "prefix",
        "renderFn",
        "renderFnParams",
        "rowGroup",
        "sparkline",
        "suffix",
        "width",
    }
)
GRID_COLUMNS = 40


@dataclass(frozen=True)
class ContractIssue:
    """One actionable manifest contract violation."""

    code: str
    path: str
    message: str

    def key(self) -> tuple[str, str]:
        """Return the stable identity used by the debt baseline."""
        return (self.code, self.path)


class ManifestValidationError(ValueError):
    """Raised when a Workspace manifest contract is invalid."""

    def __init__(self, issues: Iterable[ContractIssue]):
        """Store structured issues and a readable joined message."""
        self.issues = tuple(issues)
        self.error_codes = tuple(issue.code for issue in self.issues)
        detail = "; ".join(
            f"{issue.code} at {issue.path}: {issue.message}" for issue in self.issues
        )
        super().__init__(f"Invalid OpenBB Workspace manifest: {detail}")


class _Collector:
    """Accumulate issues with one consistent shape."""

    def __init__(self) -> None:
        self.issues: list[ContractIssue] = []

    def add(self, code: str, path: str, message: str) -> None:
        self.issues.append(ContractIssue(code=code, path=path, message=message))

    def unknown_keys(
        self, value: Mapping[str, Any], allowed: frozenset[str], code: str, path: str
    ) -> None:
        for key in sorted(set(value) - allowed):
            self.add(code, f"{path}.{key}", f"{key!r} is not in the Workspace schema")


def _route_path(path: str) -> str:
    """Normalize a manifest endpoint to the FastAPI route form."""
    return path if path.startswith("/") else f"/{path}"


def _is_int(value: Any) -> TypeGuard[int]:
    """Return True for real integers (bool is excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _params_by_name(widget: Any) -> dict[str, Mapping[str, Any]]:
    """Index one widget's parameters by paramName."""
    if not isinstance(widget, dict) or not isinstance(widget.get("params"), list):
        return {}
    return {
        param["paramName"]: param
        for param in widget["params"]
        if isinstance(param, dict) and isinstance(param.get("paramName"), str)
    }


def _validate_params(
    out: _Collector, path: str, widget: Mapping[str, Any], routes: set[str]
) -> None:
    """Validate widget parameter controls and dynamic option routes."""
    params = widget.get("params", [])
    if not isinstance(params, list):
        out.add("widget.params", f"{path}.params", "params must be an array")
        return
    names: set[str] = set()
    for index, param in enumerate(params):
        param_path = f"{path}.params[{index}]"
        if not isinstance(param, dict):
            out.add("widget.param", param_path, "param must be an object")
            continue
        name = param.get("paramName")
        if param.get("type") == "form" and name is None:
            pass  # the schema does not require paramName on form params
        elif not isinstance(name, str) or not name:
            out.add("widget.param.name", param_path, "paramName is required")
        elif name in names:
            out.add("widget.param.duplicate", param_path, f"duplicate {name!r}")
        else:
            names.add(name)
        param_type = param.get("type")
        if param_type not in PARAM_TYPES:
            out.add("widget.param.type", param_path, f"unsupported {param_type!r}")
        if "show" in param and not isinstance(param["show"], bool):
            out.add("widget.param.show", param_path, "show must be boolean")
        options = param.get("options")
        if options is not None:
            if not isinstance(options, list):
                out.add("widget.param.options", param_path, "options must be array")
            elif any(not isinstance(o, dict) or "label" not in o for o in options):
                out.add(
                    "widget.param.options.label",
                    param_path,
                    "every option needs a label",
                )
        if param_type == "endpoint":
            options_path = param.get("optionsEndpoint")
            if not isinstance(options_path, str) or not options_path:
                out.add(
                    "widget.param.options_endpoint",
                    param_path,
                    "endpoint params require optionsEndpoint",
                )
            elif routes and _route_path(options_path) not in routes:
                out.add(
                    "widget.param.options_endpoint.missing",
                    param_path,
                    f"optionsEndpoint {_route_path(options_path)!r} is not registered",
                )


def _validate_table(out: _Collector, path: str, table: Any) -> None:
    """Validate ``data.table`` against the schema's closed key set."""
    if not isinstance(table, dict):
        out.add("widget.table", path, "data.table must be an object")
        return
    out.unknown_keys(table, TABLE_KEYS, "widget.table.unknown_key", path)
    columns = table.get("columnsDefs")
    if columns is None:
        return
    if not isinstance(columns, list):
        out.add("widget.table.columns", path, "columnsDefs must be an array")
        return
    fields: set[str] = set()
    for index, column in enumerate(columns):
        column_path = f"{path}.columnsDefs[{index}]"
        if not isinstance(column, dict):
            out.add("widget.table.column", column_path, "column must be an object")
            continue
        out.unknown_keys(
            column, COLUMN_KEYS, "widget.table.column.unknown_key", column_path
        )
        for required in ("field", "headerName"):
            if not isinstance(column.get(required), str) or not column[required]:
                out.add(
                    f"widget.table.column.{required}",
                    column_path,
                    f"missing non-empty {required}",
                )
        field = column.get("field")
        if isinstance(field, str) and field:
            if field in fields:
                out.add(
                    "widget.table.column.duplicate",
                    column_path,
                    f"duplicate field {field!r}",
                )
            fields.add(field)


def _validate_widget(
    out: _Collector, widget_id: str, widget: Any, routes: set[str]
) -> None:
    """Validate one widget definition."""
    path = f"widgets.{widget_id}"
    if not isinstance(widget, dict):
        out.add("widget.object", path, "widget must be an object")
        return
    out.unknown_keys(widget, WIDGET_KEYS, "widget.unknown_key", path)
    for field in WIDGET_REQUIRED:
        if not isinstance(widget.get(field), str) or not widget[field]:
            out.add(f"widget.required.{field}", path, f"missing non-empty {field}")
    widget_type = widget.get("type")
    if widget_type not in WIDGET_TYPES:
        out.add("widget.type", path, f"unsupported widget type {widget_type!r}")
    if "raw" in widget and not isinstance(widget["raw"], bool):
        out.add("widget.raw", path, "raw must be boolean")
    endpoint = widget.get("endpoint")
    if (
        isinstance(endpoint, str)
        and endpoint
        and routes
        and _route_path(endpoint) not in routes
    ):
        out.add(
            "widget.endpoint.missing",
            path,
            f"endpoint {_route_path(endpoint)!r} is not registered",
        )
    grid = widget.get("gridData")
    if grid is not None:
        if not isinstance(grid, dict):
            out.add("widget.grid", path, "gridData must be an object")
        else:
            for field in ("w", "h"):
                value = grid.get(field)
                if not _is_int(value) or value <= 0:
                    out.add(
                        f"widget.grid.{field}",
                        path,
                        f"gridData.{field} must be a positive integer",
                    )
            if _is_int(grid.get("w")) and grid["w"] > GRID_COLUMNS:
                out.add("widget.grid.w", path, f"gridData.w exceeds {GRID_COLUMNS}")
    data = widget.get("data")
    if data is not None:
        if not isinstance(data, dict):
            out.add("widget.data", path, "data must be an object")
        else:
            out.unknown_keys(data, DATA_KEYS, "widget.data.unknown_key", f"{path}.data")
            if "table" in data:
                _validate_table(out, f"{path}.data.table", data["table"])
    _validate_params(out, path, widget, routes)


def _placements(app: Mapping[str, Any], widget_id: str) -> list[list[Any]]:
    """Return the ``groups`` list of every placement of one widget."""
    found: list[list[Any]] = []
    tabs = app.get("tabs")
    for tab in tabs.values() if isinstance(tabs, dict) else []:
        layout = tab.get("layout") if isinstance(tab, dict) else None
        for placement in layout if isinstance(layout, list) else []:
            if isinstance(placement, dict) and placement.get("i") == widget_id:
                groups = placement.get("groups") or []
                found.append(groups if isinstance(groups, list) else [])
    return found


def _validate_group_member(
    out: _Collector,
    path: str,
    group: Mapping[str, Any],
    widget_id: str,
    widget: Any,
) -> None:
    """Check one group member's widget param matches the group semantics.

    Ticker (symbol) groups may include widgets without a symbol param:
    the pinned app-builder guide lists discovery tables in the symbol group
    "even when they have no ``symbol`` param" (``guides/review-app.md``).
    """
    group_type = group.get("type")
    params = _params_by_name(widget)
    if group_type == "ticker":
        return
    param_name = group.get("paramName")
    param = params.get(str(param_name))
    if param is None:
        out.add(
            "group.param.missing",
            path,
            f"widget {widget_id!r} has no param {param_name!r}",
        )
        return
    if group_type == "endpointParam":
        if param.get("type") != "endpoint" or not param.get("optionsEndpoint"):
            out.add(
                "group.type.mismatch",
                path,
                f"endpointParam needs an endpoint param with optionsEndpoint "
                f"on {widget_id!r}",
            )
    elif param.get("type") == "endpoint" or not param.get("options"):
        out.add(
            "group.type.mismatch",
            path,
            f"param groups need a static param with inline options on {widget_id!r}",
        )


def _validate_groups(
    out: _Collector,
    path: str,
    app: Mapping[str, Any],
    widgets: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Validate parameter groups and return them indexed by name."""
    groups = app.get("groups", [])
    if not isinstance(groups, list):
        out.add("app.groups", f"{path}.groups", "groups must be an array")
        return {}
    by_name: dict[str, Mapping[str, Any]] = {}
    for index, group in enumerate(groups):
        group_path = f"{path}.groups[{index}]"
        if not isinstance(group, dict):
            out.add("group.object", group_path, "group must be an object")
            continue
        out.unknown_keys(group, GROUP_KEYS, "group.unknown_key", group_path)
        name = group.get("name")
        if not isinstance(name, str) or not name:
            out.add("group.name", group_path, "group name is required")
            continue
        if not GROUP_NAME_RE.match(name):
            out.add("group.name.convention", group_path, "use 'Group N' names")
        if name in by_name:
            out.add("group.duplicate", group_path, f"duplicate group {name!r}")
        by_name[name] = group
        group_type = group.get("type")
        if group_type not in GROUP_TYPES:
            out.add("group.type", group_path, f"unsupported type {group_type!r}")
            continue
        if group_type != "ticker" and not group.get("paramName"):
            out.add("group.paramName", group_path, f"{group_type} needs paramName")
        widget_ids = group.get("widgetIds")
        if not isinstance(widget_ids, list) or not widget_ids:
            out.add("group.widgetIds", group_path, "widgetIds must be non-empty")
            continue
        for widget_id in widget_ids:
            member_path = f"{group_path}.widgetIds.{widget_id}"
            if widget_id not in widgets:
                out.add("group.widget.missing", member_path, "unknown widget")
                continue
            if not any(name in placed for placed in _placements(app, widget_id)):
                out.add(
                    "group.layout.missing",
                    member_path,
                    f"no placement of {widget_id!r} carries group {name!r}",
                )
            _validate_group_member(
                out, member_path, group, widget_id, widgets[widget_id]
            )
    return by_name


def _validate_placement(
    out: _Collector,
    path: str,
    placement: Any,
    widgets: Mapping[str, Any],
    groups: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate one layout item on the 40-column grid."""
    if not isinstance(placement, dict):
        out.add("layout.object", path, "layout item must be an object")
        return
    widget_id = placement.get("i")
    if widget_id not in widgets:
        out.add("layout.widget.missing", path, f"unknown widget id {widget_id!r}")
    for field in ("x", "y", "w", "h"):
        value = placement.get(field)
        minimum = 1 if field in ("w", "h") else 0
        if not _is_int(value) or value < minimum:
            out.add(f"layout.{field}", path, f"{field} must be an integer >= {minimum}")
    x, w = placement.get("x"), placement.get("w")
    if _is_int(x) and _is_int(w) and (x >= GRID_COLUMNS or x + w > GRID_COLUMNS):
        out.add("layout.width", path, f"item exceeds the {GRID_COLUMNS}-column grid")
    layout_groups = placement.get("groups", [])
    if not isinstance(layout_groups, list):
        out.add("layout.groups", path, "groups must be an array")
        layout_groups = []
    for name in layout_groups:
        group = groups.get(name)
        if group is None:
            out.add("layout.group.missing", path, f"unknown group {name!r}")
        elif widget_id not in (group.get("widgetIds") or []):
            out.add(
                "layout.group.widget",
                path,
                f"widget {widget_id!r} is not a member of group {name!r}",
            )
    state = placement.get("state")
    if state is None:
        return
    if not isinstance(state, dict):
        out.add("layout.state", path, "state must be an object")
        return
    params = state.get("params")
    if params is None:
        return
    if not isinstance(params, dict):
        out.add("layout.state.params", path, "state.params must be an object")
        return
    allowed = _params_by_name(widgets.get(str(widget_id)))
    for name in params:
        if widget_id in widgets and name not in allowed:
            out.add(
                "layout.state.param",
                path,
                f"widget {widget_id!r} has no param {name!r}",
            )


def _validate_app(
    out: _Collector, index: int, app: Any, widgets: Mapping[str, Any]
) -> None:
    """Validate one app template, its groups, and all placements."""
    if not isinstance(app, dict):
        out.add("app.object", f"apps[{index}]", "app must be an object")
        return
    app_id = app.get("id")
    path = f"apps.{app_id}" if isinstance(app_id, str) and app_id else f"apps[{index}]"
    out.unknown_keys(app, APP_KEYS, "app.unknown_key", path)
    if not isinstance(app.get("name"), str) or not app["name"]:
        out.add("app.name", path, "missing non-empty name")
    if "id" in app and (not isinstance(app_id, str) or not APP_ID_RE.match(app_id)):
        out.add("app.id", path, "app ids must match ^custom-.+")
    if "allowCustomization" in app and not isinstance(app["allowCustomization"], bool):
        out.add("app.allow_customization", path, "allowCustomization must be boolean")
    groups = _validate_groups(out, path, app, widgets)
    tabs = app.get("tabs")
    if not isinstance(tabs, dict) or not tabs:
        out.add("app.tabs", path, "apps require a non-empty tabs object")
        return
    for tab_key, tab in tabs.items():
        tab_path = f"{path}.tabs.{tab_key}"
        if not isinstance(tab, dict):
            out.add("tab.object", tab_path, "tab must be an object")
            continue
        out.unknown_keys(tab, TAB_KEYS, "tab.unknown_key", tab_path)
        if not isinstance(tab.get("id"), str) or not isinstance(tab.get("name"), str):
            out.add("tab.required", tab_path, "tabs require string id and name")
        layout = tab.get("layout")
        if not isinstance(layout, list):
            out.add("layout.array", tab_path, "layout must be an array")
            continue
        for item_index, placement in enumerate(layout):
            _validate_placement(
                out, f"{tab_path}.layout[{item_index}]", placement, widgets, groups
            )


def collect_manifest_issues(
    widgets: Any, apps: Any, *, routes: Iterable[str] | None = None
) -> list[ContractIssue]:
    """Return every contract issue in the manifests (empty when valid)."""
    out = _Collector()
    registered = set(routes or [])
    if not isinstance(widgets, dict):
        out.add("widgets.object", "widgets", "widgets.json must contain an object")
        widgets = {}
    for widget_id, widget in widgets.items():
        _validate_widget(out, str(widget_id), widget, registered)
    if not isinstance(apps, list):
        out.add("apps.array", "apps", "apps.json must contain an array")
        apps = []
    for index, app in enumerate(apps):
        _validate_app(out, index, app, widgets)
    return out.issues


def validate_workspace_manifests(
    widgets: Any, apps: Any, *, routes: Iterable[str] | None = None
) -> list[ContractIssue]:
    """Return ``[]`` for valid manifests; raise with every issue otherwise."""
    issues = collect_manifest_issues(widgets, apps, routes=routes)
    if issues:
        raise ManifestValidationError(issues)
    return []


def load_debt_baseline(
    path: Path, *, prefix: str | None = None
) -> dict[tuple[str, str], str]:
    """Load recorded known debt as ``{(code, path): issue}``.

    ``prefix`` selects one section, e.g. ``"widgets."``/``"apps."`` for
    manifest debt or ``"responses."`` for endpoint debt.
    """
    entries = json.loads(path.read_text(encoding="utf-8"))["issues"]
    return {
        (entry["code"], entry["path"]): entry["tracking"]
        for entry in entries
        if prefix is None or entry["path"].startswith(prefix)
    }


def _reject_constant(token: str) -> Any:
    """Refuse NaN/Infinity, which Workspace's JSON parser cannot read."""
    raise ValueError(f"non-finite JSON constant {token}")


def _is_metric(value: Any) -> bool:
    return isinstance(value, dict) and "label" in value and "value" in value


def _row_state_ok(row: Mapping[str, Any]) -> bool:
    """Return True when a row carries the three provenance columns (#1269)."""
    return row.get("data_state") in BODY_STATES and all(
        isinstance(row.get(field), str) for field in ROW_FIELDS
    )


def _check_table(
    out: _Collector, path: str, widget: Mapping[str, Any], payload: Any
) -> None:
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        out.add("response.shape.table", path, "table must return an array of objects")
        return
    if not payload:
        out.add("response.empty", path, "table returned no rows (loud-empty rule)")
        return
    table = (widget.get("data") or {}).get("table") or {}
    present = {key for row in payload for key in row}
    no_data = all(row.get("data_state") == "unavailable" for row in payload)
    for column in [] if no_data else table.get("columnsDefs") or []:
        field = column.get("field") if isinstance(column, dict) else None
        if isinstance(field, str) and field not in present:
            out.add(
                "response.table.column_missing",
                f"{path}.{field}",
                f"declared column {field!r} is absent from every row",
            )
    if not all(_row_state_ok(row) for row in payload):
        out.add(
            "response.state.table",
            path,
            "every row needs data_state/data_source/data_as_of strings",
        )


def _check_chart(out: _Collector, path: str, payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        out.add("response.shape.chart", path, "chart must return a Plotly figure")
        return
    layout = payload.get("layout")
    layout = layout if isinstance(layout, dict) else {}
    meta = layout.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    state = meta.get("state")
    if state not in BODY_STATES or not isinstance(meta.get("source"), str):
        out.add("response.state.chart", path, "layout.meta needs a state and source")
    elif state != "live" and not layout.get("annotations"):
        out.add(
            "response.state.annotation",
            path,
            f"a {state} figure must say so in an annotation",
        )


def _check_metric(out: _Collector, path: str, payload: Any) -> None:
    valid = _is_metric(payload) or (
        isinstance(payload, list) and payload and all(map(_is_metric, payload))
    )
    if not valid:
        out.add("response.shape.metric", path, "metric needs {label, value}")
        return
    cards = payload if isinstance(payload, list) else [payload]
    if not any(
        card["label"] == DATA_STATE_LABEL
        and isinstance(card["value"], str)
        and METRIC_STATE_RE.match(card["value"])
        for card in cards
    ):
        out.add(
            "response.state.metric",
            path,
            "metric needs a 'Data State' card with '<State>: <reason>'",
        )


def collect_response_issues(
    widget_id: str, widget: Mapping[str, Any], status: int, body: str
) -> list[ContractIssue]:
    """Check one endpoint response against its widget type's contract.

    Shapes: table -> non-empty array of objects (covering every declared
    ``columnsDefs`` field); chart -> Plotly figure object with a ``data``
    array; markdown -> non-empty string; metric -> ``{label, value}`` object
    or a non-empty array of them. Bodies must be strict, finite JSON.

    A response of the right shape must also carry a valid data state (#1269):
    table rows the provenance columns, a chart ``layout.meta`` (plus an
    annotation unless live), a metric a ``Data State`` card, Markdown a
    ``**Data state:**`` line.
    """
    out = _Collector()
    path = f"responses.{widget_id}"
    if status != 200:
        out.add("response.status", path, f"HTTP {status}")
        return out.issues
    try:
        payload = json.loads(body, parse_constant=_reject_constant)
    except ValueError as exc:
        out.add("response.json", path, str(exc)[:120])
        return out.issues
    data_key = (widget.get("data") or {}).get("dataKey")
    if isinstance(data_key, str) and data_key and isinstance(payload, dict):
        # Workspace unwraps ``get(result, data.dataKey, result)`` at runtime.
        payload = payload.get(data_key, payload)
    widget_type = widget.get("type")
    if widget_type == "table":
        _check_table(out, path, widget, payload)
    elif widget_type == "chart":
        _check_chart(out, path, payload)
    elif widget_type == "markdown":
        if not isinstance(payload, str) or not payload.strip():
            out.add("response.shape.markdown", path, "markdown must return text")
        elif not MARKDOWN_STATE_RE.search(payload):
            out.add(
                "response.state.markdown",
                path,
                "markdown must state '**Data state:** <State>'",
            )
    elif widget_type == "metric":
        _check_metric(out, path, payload)
    return out.issues


def compare_with_baseline(
    issues: Iterable[ContractIssue], baseline: Mapping[tuple[str, str], str]
) -> tuple[list[ContractIssue], list[tuple[str, str]]]:
    """Return ``(new_issues, resolved_baseline_keys)``.

    New issues are regressions. Resolved keys must be removed from the
    baseline so it only shrinks; both lists must be empty for a pass.
    """
    issues = list(issues)
    current = {issue.key() for issue in issues}
    new = [issue for issue in issues if issue.key() not in baseline]
    resolved = sorted(key for key in baseline if key not in current)
    return new, resolved
