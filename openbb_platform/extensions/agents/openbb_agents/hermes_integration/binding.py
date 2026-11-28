"""Hermes run binding and delivery keys, and the ``pre_tool_call`` hook (#1341).

Hermes does not send its session or tool-call IDs to MCP servers; MCP calls
carry only the model's arguments. An OpenBB-owned Hermes plugin
(``hermes_plugin``) therefore derives hashed keys in-process, before dispatch,
and rewrites exactly two arguments of the story mutation tools:

- ``story_run_create``: ``binding`` = ``hs-`` + sha256(session, tool call)
  for an interactive turn, or ``hc-`` + sha256(cron job, execution, workflow)
  inside a cron fire, so one Hermes start or one cron execution binds to one
  OpenBB run.
- ``story_job_submit`` and ``story_paper_prepare``: ``operation_id`` = ``hd-``
  + sha256(session, tool call), so a transport re-delivery of the same call
  reuses the same delivery key.

Correctness never depends on this hook: the server stops logical duplicates on
bound runs by itself (``story_adapters.receipts``). The hook only adds the
Hermes correlation. It follows the pinned Hermes contract (fork 710fa8a,
``hermes_cli/plugins.py``): it is called with ``tool_name``, ``args`` and the
observability IDs as keywords, and a ``{"action": "modify", "args": {...}}``
return is shallow-merged into the arguments. Nothing here imports Hermes, and
raw Hermes identifiers never leave the process.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

KEY_HEX = 32
MCP_PREFIX = "mcp__"
RUN_CREATE = "story_run_create"
DELIVERY_KEYED = frozenset({"story_job_submit", "story_paper_prepare"})


def _key(prefix: str, *parts: str) -> str:
    canonical = json.dumps([prefix, *parts], separators=(",", ":"))
    return (
        prefix + "-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:KEY_HEX]
    )


def binding_key_for_session(session_id: str, tool_call_id: str) -> str:
    """Run binding key of one interactive Hermes ``story_run_create`` call."""
    return _key("hs", session_id, tool_call_id)


def binding_key_for_cron(job_id: str, execution_id: str, workflow_id: str) -> str:
    """Run binding key of one cron execution of one workflow."""
    return _key("hc", job_id, execution_id, workflow_id)


def delivery_key(session_id: str, tool_call_id: str) -> str:
    """Delivery (``operation_id``) key of one Hermes tool call."""
    return _key("hd", session_id, tool_call_id)


def story_tool(tool_name: Any) -> str | None:
    """Return the OpenBB tool name of a Hermes tool name, else ``None``.

    Hermes names MCP tools ``mcp__<server>__<tool>``; a bare name is accepted
    for direct registrations.
    """
    if not isinstance(tool_name, str):
        return None
    name = (
        tool_name.rsplit("__", 1)[-1] if tool_name.startswith(MCP_PREFIX) else tool_name
    )
    if name == RUN_CREATE or name in DELIVERY_KEYED:
        return name
    return None


def _cron_ids(
    current_cron_execution: Callable[[], Any] | None,
) -> tuple[str, str] | None:
    if current_cron_execution is None:
        return None
    try:
        execution = current_cron_execution()
    except Exception:  # pylint: disable=broad-exception-caught
        # A failing reader must not block the call: fall back to the
        # interactive key (the server still stops logical duplicates).
        logger.debug("cron execution reader failed; using the session key")
        return None
    job_id = getattr(execution, "job_id", None)
    execution_id = getattr(execution, "execution_id", None)
    if (
        isinstance(job_id, str)
        and job_id
        and isinstance(execution_id, str)
        and execution_id
    ):
        return job_id, execution_id
    return None


def make_pre_tool_call(
    current_cron_execution: Callable[[], Any] | None = None,
) -> Callable[..., dict[str, Any] | None]:
    """Return a Hermes ``pre_tool_call`` callback.

    ``current_cron_execution`` is the plugin context's reader
    (``ctx.current_cron_execution``); it returns the running cron execution or
    ``None``.
    """

    def pre_tool_call(  # pylint: disable=too-many-arguments,unused-argument
        *,
        tool_name: Any = None,
        args: Any = None,
        task_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        turn_id: str = "",
        api_request_id: str = "",
        **_: Any,
    ) -> dict[str, Any] | None:
        name = story_tool(tool_name)
        if name is None or not isinstance(args, dict):
            return None
        if not (isinstance(session_id, str) and session_id):
            return None
        if not (isinstance(tool_call_id, str) and tool_call_id):
            return None
        if name in DELIVERY_KEYED:
            return {
                "action": "modify",
                "args": {"operation_id": delivery_key(session_id, tool_call_id)},
            }
        cron = _cron_ids(current_cron_execution)
        story_id = args.get("story_id")
        if cron is not None and isinstance(story_id, str) and story_id:
            binding = {
                "harness": "hermes",
                "binding_key": binding_key_for_cron(cron[0], cron[1], story_id),
                "origin": "cron",
            }
        else:
            binding = {
                "harness": "hermes",
                "binding_key": binding_key_for_session(session_id, tool_call_id),
                "origin": "interactive",
            }
        return {"action": "modify", "args": {"binding": binding}}

    return pre_tool_call
