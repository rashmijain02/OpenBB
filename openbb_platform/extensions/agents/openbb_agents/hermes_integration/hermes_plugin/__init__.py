"""OpenBB Hermes plugin: bind Hermes calls to OpenBB story runs (#1341).

Install into a Hermes home's plugin directory only in the owner's live
acceptance step (T04); nothing in OpenBB loads it. ``register`` wires the
pure ``binding.make_pre_tool_call`` hook to the plugin context's cron reader.
"""

from __future__ import annotations

import os
from typing import Any

from openbb_agents.hermes_integration.binding import (
    DEFAULT_SERVER,
    SERVER_ENV,
    make_pre_tool_call,
)


def register(ctx: Any) -> None:
    """Hermes plugin entry point: register the ``pre_tool_call`` hook."""
    reader = getattr(ctx, "current_cron_execution", None)
    server = os.environ.get(SERVER_ENV, "").strip() or DEFAULT_SERVER
    ctx.register_hook(
        "pre_tool_call",
        make_pre_tool_call(reader if callable(reader) else None, server=server),
    )
