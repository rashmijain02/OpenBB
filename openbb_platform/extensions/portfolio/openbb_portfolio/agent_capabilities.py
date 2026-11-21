"""Widget capability inventory for the Workspace custom agent (#1272).

The copilot (:mod:`openbb_portfolio.copilot`) reads widget data only through
OpenBB Workspace's ``get_widget_data`` function call, and only for widgets the
host backend listed here. The inventory is built from the backend's own
``widgets.json`` so it cannot drift from what Workspace shows, plus an
explicit denial list for action widgets (paper orders, job triggers) that the
agent must never request, whatever their parameters.

A host backend registers its inventory on ``app.state`` under
:data:`openbb_portfolio.copilot.CAPABILITIES_STATE`; without one, the agent
stays text-only and ``/agents.json`` does not advertise widget access.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CHART = "chart"


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


def capabilities_from_manifest(
    widgets: Mapping[str, Mapping[str, Any]],
    denied: Mapping[str, str],
) -> dict[str, WidgetCapability]:
    """Build the agent inventory from a ``widgets.json`` mapping.

    Raises ``ValueError`` if ``denied`` names a widget the manifest does not
    have: a stale denial would otherwise silently stop protecting anything.
    """
    unknown = sorted(set(denied) - set(widgets))
    if unknown:
        raise ValueError(f"denied widgets not in the manifest: {', '.join(unknown)}")
    return {
        widget_id: WidgetCapability(
            widget_id=widget_id,
            name=str(widget.get("name") or widget_id),
            kind=str(widget.get("type") or "table"),
            endpoint=str(widget.get("endpoint") or "").lstrip("/"),
            denied_reason=denied.get(widget_id),
        )
        for widget_id, widget in widgets.items()
    }


__all__ = ["CHART", "WidgetCapability", "capabilities_from_manifest"]
