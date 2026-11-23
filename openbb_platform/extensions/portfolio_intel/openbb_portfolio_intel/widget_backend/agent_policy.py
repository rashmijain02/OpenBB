"""Workspace agent policy for the Portfolio Intelligence widgets (#1272).

The custom agent (``openbb_portfolio.copilot``, mounted on this backend at
``/agents.json`` + ``/query``) may read widgets in this backend's
``widgets.json``, read-only. Access is safe by default: any widget that looks
like an action (``agent_capabilities.action_markers``: a ``confirm``
parameter, an execute / paper / backtest / order endpoint, a non-GET method)
is denied unless it is on ``AGENT_READ_ALLOWLIST``, so a newly added action
widget is never readable by accident.

``AGENT_DENIED_WIDGETS`` gives the reasons for the two known action widgets.
They submit or queue work (a paper order with ``confirm=true``, a backtest
job); paper and execution actions stay separately authorized in the widget
itself and are never driven by the model. The MCP exposure policy denies the
same two endpoints (rule ``deny-success-shaped-intelligence-stubs``); a unit
test keeps the two lists equal.

The inventory applies only to widgets whose Workspace ``origin`` is this
backend: the connector name, ``portfolio-intel`` by default (see the README),
or the comma-separated names in ``PI_AGENT_WIDGET_ORIGINS``.
"""

import json
import os
from pathlib import Path

from openbb_portfolio.agent_capabilities import (
    WidgetCapability,
    capabilities_from_manifest,
)

MANIFEST = Path(__file__).resolve().parent / "widgets.json"

AGENT_DENIED_WIDGETS: dict[str, str] = {
    "pi_paper_ticket": (
        "it places paper orders (confirm=true commits to the paper ledger)"
    ),
    "pi_backtest_button": "it queues a backtest job",
}

# Action-like by name or path, but read-only GETs that only display state.
AGENT_READ_ALLOWLIST: frozenset[str] = frozenset(
    {
        "pi_paper_blotter",  # recent paper orders, read from the ledger
        "pi_paper_performance",  # paper equity curve
        "pi_paper_perf_kpis",  # paper KPI cards
        "tt_execute_bridge",  # describes the execution gates; submits nothing
        "tt_execute_paper_status",  # paper engine snapshot
        "tt_order_legs",  # planned order legs of a TechTrade plan; places nothing
    }
)

DEFAULT_ORIGINS = ("portfolio-intel",)
ORIGINS_ENV = "PI_AGENT_WIDGET_ORIGINS"


def agent_widget_origins() -> frozenset[str]:
    """Return the Workspace connector names that identify this backend."""
    raw = os.getenv(ORIGINS_ENV, "")
    names = [name.strip() for name in raw.split(",") if name.strip()]
    return frozenset(name.casefold() for name in (names or DEFAULT_ORIGINS))


def build_agent_capabilities(
    manifest: Path = MANIFEST,
) -> dict[str, WidgetCapability]:
    """Return the agent's widget inventory for this backend's manifest."""
    widgets = json.loads(manifest.read_text(encoding="utf-8"))
    return capabilities_from_manifest(
        widgets, AGENT_DENIED_WIDGETS, allow=AGENT_READ_ALLOWLIST
    )


__all__ = [
    "AGENT_DENIED_WIDGETS",
    "AGENT_READ_ALLOWLIST",
    "DEFAULT_ORIGINS",
    "MANIFEST",
    "ORIGINS_ENV",
    "agent_widget_origins",
    "build_agent_capabilities",
]
