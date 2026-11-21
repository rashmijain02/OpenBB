"""Workspace agent policy for the Portfolio Intelligence widgets (#1272).

The custom agent (``openbb_portfolio.copilot``, mounted on this backend at
``/agents.json`` + ``/query``) may read any widget in this backend's
``widgets.json``, read-only, except the action widgets below. Those submit
or queue work (a paper order with ``confirm=true``, a backtest job); paper
and execution actions stay separately authorized in the widget itself and are
never driven by the model. The MCP exposure policy denies the same two
endpoints (rule ``deny-success-shaped-intelligence-stubs``); a unit test keeps
the two lists equal.
"""

import json
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


def build_agent_capabilities(
    manifest: Path = MANIFEST,
) -> dict[str, WidgetCapability]:
    """Return the agent's widget inventory for this backend's manifest."""
    widgets = json.loads(manifest.read_text(encoding="utf-8"))
    return capabilities_from_manifest(widgets, AGENT_DENIED_WIDGETS)


__all__ = ["AGENT_DENIED_WIDGETS", "MANIFEST", "build_agent_capabilities"]
