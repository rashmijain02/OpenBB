#!/usr/bin/env python3
"""Build a deterministic inventory of the Portfolio Workspace backend."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    """Read UTF-8 JSON with an actionable error."""
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _registered_routes(backend_dir: Path) -> set[str]:
    """Extract literal FastAPI GET/POST routes without importing the backend."""
    routes: set[str] = set()
    for path in (backend_dir / "main.py", backend_dir / "widgets_endpoints.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                route = _route_decorator_path(decorator)
                if route:
                    routes.add(route)
    return routes


def _route_decorator_path(decorator: ast.expr) -> str | None:
    """Return a literal app/router route path from one decorator."""
    if not isinstance(decorator, ast.Call):
        return None
    if not isinstance(decorator.func, ast.Attribute):
        return None
    if decorator.func.attr not in {"get", "post"} or not decorator.args:
        return None
    route = decorator.args[0]
    if not isinstance(route, ast.Constant) or not isinstance(route.value, str):
        return None
    return route.value


def _chart_mapping(widget: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest's explicit chart mapping, when present."""
    data = widget.get("data") or {}
    chart = data.get("chart") or widget.get("chart") or {}
    return {
        "raw": widget.get("raw") is True,
        "type": chart.get("type") or chart.get("chartType"),
        "labelColumn": chart.get("labelColumn") or chart.get("label"),
        "valueColumn": chart.get("valueColumn") or chart.get("value"),
    }


def _table_fields(widget: dict[str, Any]) -> list[str]:
    """Return table field names declared by the Workspace manifest."""
    data = widget.get("data") or {}
    table = data.get("table") or {}
    columns = table.get("columnsDefs") or []
    return [
        column["field"]
        for column in columns
        if isinstance(column, dict) and isinstance(column.get("field"), str)
    ]


def _metric_labels(widget: dict[str, Any]) -> list[str]:
    """Return metric labels declared by the Workspace manifest."""
    data = widget.get("data") or {}
    metric = data.get("metric") or {}
    labels = metric.get("labels") or {}
    if isinstance(labels, dict):
        return list(labels.values())
    return []


def _baseline_state(widget_id: str, widget: dict[str, Any]) -> str:
    """Classify the static manifest without claiming runtime provider behavior."""
    if "execute" in widget_id or widget_id == "pi_backtest_button":
        return "gate-required"

    parameters = widget.get("params") or []
    if any(
        isinstance(parameter, dict)
        and parameter.get("paramName") == "account_id"
        and parameter.get("value") == "demo"
        for parameter in parameters
    ):
        return "explicit-demo"

    widget_type = widget.get("type")
    if widget_type == "chart":
        mapping = _chart_mapping(widget)
        return (
            "native-ready"
            if mapping["raw"]
            and mapping["type"]
            and mapping["labelColumn"]
            and mapping["valueColumn"]
            else "contract-repair"
        )
    if widget_type == "table":
        return "native-ready" if _table_fields(widget) else "contract-repair"
    if widget_type == "metric":
        return "native-ready" if _metric_labels(widget) else "contract-repair"
    if widget_type == "markdown":
        return "native-ready"
    return "contract-repair"


def _app_tabs(app: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize app tabs while retaining their stable dictionary keys."""
    tabs = app.get("tabs") or {}
    if isinstance(tabs, dict):
        return [
            {
                "id": tab_id,
                "name": tab.get("name"),
                "layout": tab.get("layout") or [],
            }
            for tab_id, tab in tabs.items()
            if isinstance(tab, dict)
        ]
    if isinstance(tabs, list):
        return [
            {
                "id": tab.get("id"),
                "name": tab.get("name"),
                "layout": tab.get("layout") or [],
            }
            for tab in tabs
            if isinstance(tab, dict)
        ]
    return []


def build_matrix(backend_dir: Path) -> dict[str, Any]:
    """Build the deterministic native Workspace inventory for one backend."""
    widgets = _read_json(backend_dir / "widgets.json")
    apps = _read_json(backend_dir / "apps.json")
    routes = _registered_routes(backend_dir)

    if not isinstance(widgets, dict):
        raise TypeError("widgets.json must contain an object keyed by widget ID")
    if not isinstance(apps, list):
        raise TypeError("apps.json must contain an array of apps")

    placements: dict[str, list[dict[str, Any]]] = {
        widget_id: [] for widget_id in widgets
    }
    unknown_placements: list[dict[str, str]] = []
    app_rows: list[dict[str, Any]] = []
    placement_count = 0

    for app in apps:
        tabs = _app_tabs(app)
        for tab in tabs:
            for slot in tab["layout"]:
                placement_count += 1
                widget_id = slot.get("i")
                placement = {
                    "appId": app.get("id"),
                    "appName": app.get("name"),
                    "tabId": tab["id"],
                    "tabName": tab["name"],
                    "x": slot.get("x"),
                    "y": slot.get("y"),
                    "w": slot.get("w"),
                    "h": slot.get("h"),
                }
                if widget_id in placements:
                    placements[widget_id].append(placement)
                else:
                    unknown_placements.append(
                        {
                            "appId": str(app.get("id")),
                            "tabId": str(tab["id"]),
                            "widgetId": str(widget_id),
                        }
                    )
        app_rows.append(
            {
                "id": app.get("id"),
                "name": app.get("name"),
                "description": app.get("description"),
                "tabs": [
                    {
                        "id": tab["id"],
                        "name": tab["name"],
                        "placements": len(tab["layout"]),
                    }
                    for tab in tabs
                ],
                "groups": app.get("groups") or [],
                "params": app.get("params") or {},
            }
        )

    widget_rows: list[dict[str, Any]] = []
    for widget_id, widget in sorted(widgets.items()):
        endpoint = str(widget.get("endpoint") or "")
        endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        parameters = [
            {
                "name": parameter.get("paramName"),
                "type": parameter.get("type"),
                "default": parameter.get("value"),
                "show": parameter.get("show"),
            }
            for parameter in (widget.get("params") or [])
            if isinstance(parameter, dict)
        ]
        widget_rows.append(
            {
                "id": widget_id,
                "name": widget.get("name"),
                "type": widget.get("type"),
                "category": widget.get("category"),
                "endpoint": endpoint,
                "endpointRegistered": endpoint_path in routes,
                "source": widget.get("source"),
                "baselineState": _baseline_state(widget_id, widget),
                "parameters": parameters,
                "chart": (
                    _chart_mapping(widget) if widget.get("type") == "chart" else None
                ),
                "tableFields": (
                    _table_fields(widget) if widget.get("type") == "table" else []
                ),
                "metricLabels": (
                    _metric_labels(widget) if widget.get("type") == "metric" else []
                ),
                "placements": placements[widget_id],
            }
        )

    type_counts = Counter(str(widget.get("type")) for widget in widgets.values())
    return {
        "schemaVersion": 1,
        "summary": {
            "apps": len(apps),
            "placements": placement_count,
            "widgets": len(widgets),
            "types": dict(sorted(type_counts.items())),
        },
        "apps": app_rows,
        "widgets": widget_rows,
        "unknownAppPlacements": unknown_placements,
        "unplacedWidgets": [
            widget_id
            for widget_id, widget_placements in sorted(placements.items())
            if not widget_placements
        ],
    }


def main() -> None:
    """Generate or print the inventory."""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend-dir",
        type=Path,
        default=(
            root
            / "openbb_platform"
            / "extensions"
            / "portfolio_intel"
            / "openbb_portfolio_intel"
            / "widget_backend"
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    output = (
        json.dumps(
            build_matrix(args.backend_dir.resolve()),
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
