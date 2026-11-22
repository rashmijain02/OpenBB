"""Widget capability inventory for the Workspace custom agent (#1272).

The copilot (:mod:`openbb_portfolio.copilot`) reads widget data only through
OpenBB Workspace's ``get_widget_data`` function call, and only for widgets the
host backend listed here. The inventory is built from the backend's own
``widgets.json`` so it cannot drift from what Workspace shows.

Access is safe by default: a widget that looks like an action (a non-GET
``method``, a ``confirm`` parameter, or an execute / paper / backtest / order
endpoint segment or category) is denied unless the host explicitly allowlists
it as read-only. An explicit denial list gives specific reasons for known
action widgets (paper orders, job triggers).

A host backend registers its inventory on ``app.state`` under
:data:`openbb_portfolio.copilot.CAPABILITIES_STATE`; without one, the agent
stays text-only and ``/agents.json`` does not advertise widget access.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

CHART = "chart"

# Endpoint path segments and categories that mark a widget as an action.
ACTION_WORDS = frozenset(
    {
        "approve",
        "backtest",
        "cancel",
        "commit",
        "execute",
        "oneclick",
        "order",
        "orders",
        "paper",
        "rebalance",
        "submit",
        "ticket",
        "trade",
        "trigger",
        "write",
        "write-batch",
    }
)
ACTION_PARAMS = frozenset({"confirm", "confirmation", "execute", "commit", "dry_run"})
_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class WidgetCapability:
    """What the agent may do with one widget."""

    widget_id: str
    name: str
    kind: str
    endpoint: str
    denied_reason: str | None = None

    @property
    def readable(self) -> bool:
        """Return whether the agent may read this widget."""
        return self.denied_reason is None

    def input_args(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Return the arguments Workspace should fetch this widget with.

        The widget's current parameters are passed through unchanged; the
        agent never invents or overrides one. Chart widgets add ``raw=true``:
        Workspace's agent contract reads a chart's rows, never its Plotly
        figure, and the rows carry the ``data_state`` provenance columns.
        """
        args = dict(params)
        if self.kind == CHART:
            args["raw"] = True
        return args


def action_markers(widget: Mapping[str, Any]) -> list[str]:
    """Return why a manifest widget looks like an action (empty if it does not)."""
    markers: list[str] = []
    method = str(widget.get("method") or "GET").upper()
    if method != "GET":
        markers.append(f"method {method}")
    params = {
        str(param.get("paramName") or param.get("name") or "").lower()
        for param in widget.get("params") or []
        if isinstance(param, Mapping)
    }
    markers += [f"parameter {name}" for name in sorted(params & ACTION_PARAMS)]
    endpoint = str(widget.get("endpoint") or "").lower()
    segments = set(re.split(r"[/_]", endpoint)) | {endpoint.rsplit("/", 1)[-1]}
    markers += [f"endpoint {word}" for word in sorted(segments & ACTION_WORDS)]
    category = " ".join(
        str(widget.get(key) or "") for key in ("category", "subCategory")
    ).lower()
    words = set(_WORD_RE.findall(category))
    markers += [f"category {word}" for word in sorted(words & ACTION_WORDS)]
    return markers


def capabilities_from_manifest(
    widgets: Mapping[str, Mapping[str, Any]],
    denied: Mapping[str, str],
    allow: Collection[str] = (),
) -> dict[str, WidgetCapability]:
    """Build the agent inventory from a ``widgets.json`` mapping.

    ``denied`` gives explicit reasons; every other action-like widget (see
    :func:`action_markers`) is denied too unless it is in ``allow``. Raises
    ``ValueError`` if ``denied`` or ``allow`` names a widget the manifest does
    not have, or ``allow`` names one that is not action-like: a stale entry
    would otherwise silently stop meaning anything.
    """
    unknown = sorted((set(denied) | set(allow)) - set(widgets))
    if unknown:
        raise ValueError(f"widgets not in the manifest: {', '.join(unknown)}")
    needless = sorted(w for w in allow if not action_markers(widgets[w]))
    if needless:
        raise ValueError(
            f"allowlisted widgets are not action-like: {', '.join(needless)}"
        )
    inventory: dict[str, WidgetCapability] = {}
    for widget_id, widget in widgets.items():
        reason = denied.get(widget_id)
        markers = action_markers(widget)
        if reason is None and markers and widget_id not in allow:
            reason = (
                f"it looks like an action ({', '.join(markers)}) and is not on "
                "the agent's read-only allowlist"
            )
        inventory[widget_id] = WidgetCapability(
            widget_id=widget_id,
            name=str(widget.get("name") or widget_id),
            kind=str(widget.get("type") or "table"),
            endpoint=str(widget.get("endpoint") or "").lstrip("/"),
            denied_reason=reason,
        )
    return inventory


__all__ = [
    "ACTION_PARAMS",
    "ACTION_WORDS",
    "CHART",
    "WidgetCapability",
    "action_markers",
    "capabilities_from_manifest",
]
