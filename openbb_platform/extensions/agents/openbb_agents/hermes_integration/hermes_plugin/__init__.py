"""OpenBB Hermes plugin: bind Hermes calls to OpenBB story runs (#1341).

Install into a Hermes home's plugin directory only in the owner's live
acceptance step (T04); nothing in OpenBB loads it. ``register`` wires the
pure ``binding.make_pre_tool_call`` hook to the plugin context's cron reader.
"""

from __future__ import annotations

from typing import Any

from openbb_agents.hermes_integration.binding import make_pre_tool_call


def register(ctx: Any) -> None:
    """Hermes plugin entry point: register the ``pre_tool_call`` hook."""
    reader = getattr(ctx, "current_cron_execution", None)
    ctx.register_hook(
        "pre_tool_call", make_pre_tool_call(reader if callable(reader) else None)
    )
