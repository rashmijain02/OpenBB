"""Hermes run binding and delivery keys, and the ``pre_tool_call`` hook (#1341 T01).

The hook contract mirrors the pinned Hermes fork (710fa8a):
``hermes_cli/plugins.py::_get_pre_tool_call_directive_details`` calls every
``pre_tool_call`` callback with ``tool_name``, ``args``, ``task_id``,
``session_id``, ``tool_call_id``, ``turn_id``, ``api_request_id`` and
``middleware_trace``; a ``{"action": "modify", "args": {...}}`` return is
shallow-merged into the original arguments before dispatch. MCP tools are named
``mcp__<server>__<tool>`` (``tools/mcp_tool_schema.py``). All IDs are synthetic.
"""

# pylint: disable=import-outside-toplevel

import ast
import inspect
import re
from types import SimpleNamespace

import pytest
from openbb_agents.hermes_integration import binding
from openbb_agents.hermes_integration.binding import (
    binding_key_for_cron,
    binding_key_for_session,
    delivery_key,
    make_pre_tool_call,
)
from openbb_mcp_server.story_adapters.registry import RunBinding
from openbb_mcp_server.story_adapters.story_job_kinds import OPERATION_ID

SESSION = "synthetic-session-1"
CALL = "call_synthetic_0001"


def _hermes_kwargs(**overrides):
    """Exactly the keyword arguments Hermes passes to a pre_tool_call hook."""
    kwargs = {
        "task_id": "task-1",
        "session_id": SESSION,
        "tool_call_id": CALL,
        "turn_id": "turn-1",
        "api_request_id": "req-1",
        "middleware_trace": [],
    }
    kwargs.update(overrides)
    return kwargs


def _hermes_merge(args, directive):
    """Hermes' shallow merge of one modify directive (plugins.py, 710fa8a)."""
    if isinstance(directive, dict) and directive.get("action") == "modify":
        partial = directive.get("args")
        if isinstance(partial, dict) and partial:
            return {**args, **partial}
    return args


def test_binding_keys_from_session_and_tool_call():
    """Binding keys from session and tool call."""
    key = binding_key_for_session(SESSION, CALL)
    assert key == binding_key_for_session(SESSION, CALL)
    assert key.startswith("hs-") and len(key) == 35
    assert re.match(OPERATION_ID, key)
    assert key != binding_key_for_session(SESSION, "call_synthetic_0002")
    assert key != binding_key_for_session("synthetic-session-2", CALL)
    op = delivery_key(SESSION, CALL)
    assert op.startswith("hd-") and re.match(OPERATION_ID, op)
    assert op[3:] != key[3:]
    # Raw identifiers never appear in a key.
    assert SESSION not in key and CALL not in op
    RunBinding(harness="hermes", binding_key=key, origin="interactive")


def test_keys_are_unambiguous_across_field_boundaries():
    """Keys are unambiguous across field boundaries."""
    assert binding_key_for_session("a", "bc") != binding_key_for_session("ab", "c")
    assert binding_key_for_cron("j", "e1", "w") != binding_key_for_cron("j", "e", "1w")


def test_cron_execution_key_is_stable_per_execution():
    """Cron execution key is stable per execution."""
    key = binding_key_for_cron("job-1", "exec-1", "workflow:synthetic.x")
    assert key == binding_key_for_cron("job-1", "exec-1", "workflow:synthetic.x")
    assert key.startswith("hc-") and re.match(OPERATION_ID, key)
    assert key != binding_key_for_cron("job-1", "exec-2", "workflow:synthetic.x")
    assert key != binding_key_for_cron("job-2", "exec-1", "workflow:synthetic.x")
    assert key != binding_key_for_cron("job-1", "exec-1", "workflow:synthetic.y")


@pytest.mark.parametrize(
    "tool_name", ["mcp__openbb__story_job_submit", "story_job_submit"]
)
def test_hook_rewrites_only_story_mutation_tools(tool_name):
    """Hook rewrites only story mutation tools."""
    hook = make_pre_tool_call()
    args = {
        "run_id": "r1",
        "operation_id": "model-chosen",
        "kind": "story.backtest",
        "payload": {"x": 1},
    }
    directive = hook(tool_name=tool_name, args=dict(args), **_hermes_kwargs())
    assert directive == {
        "action": "modify",
        "args": {"operation_id": delivery_key(SESSION, CALL)},
    }
    merged = _hermes_merge(args, directive)
    assert {k: v for k, v in merged.items() if k != "operation_id"} == {
        k: v for k, v in args.items() if k != "operation_id"
    }

    prepare = hook(
        tool_name="mcp__openbb__story_paper_prepare",
        args={"sandbox_id": "s", "operation_id": "x", "action": "submit_batch"},
        **_hermes_kwargs(),
    )
    assert set(prepare["args"]) == {"operation_id"}

    for other in (
        "mcp__openbb__story_paper_apply",
        "mcp__openbb__story_artifact_table",
        "mcp__openbb__story_run_checkpoint",
        "mcp__openbb__story_job_cancel",
        "mcp__other__operation_tool",
        "terminal",
        "story_job_submit_extra",
    ):
        assert (
            hook(tool_name=other, args={"operation_id": "x"}, **_hermes_kwargs())
            is None
        )


def test_hook_sets_binding_on_run_create_and_keeps_other_args():
    """Hook sets binding on run create and keeps other args."""
    hook = make_pre_tool_call()
    args = {"story_id": "workflow:synthetic.x", "provider_mode": "fixture"}
    directive = hook(
        tool_name="mcp__openbb__story_run_create", args=args, **_hermes_kwargs()
    )
    assert directive == {
        "action": "modify",
        "args": {
            "binding": {
                "harness": "hermes",
                "binding_key": binding_key_for_session(SESSION, CALL),
                "origin": "interactive",
            }
        },
    }
    merged = _hermes_merge(args, directive)
    assert merged["story_id"] == args["story_id"]
    assert merged["provider_mode"] == "fixture"
    RunBinding(**merged["binding"])


def test_hook_uses_the_cron_execution_when_one_is_running():
    """Hook uses the cron execution when one is running."""
    execution = SimpleNamespace(job_id="job-1", execution_id="exec-1")
    hook = make_pre_tool_call(lambda: execution)
    args = {"story_id": "workflow:synthetic.x"}
    first = hook(tool_name="story_run_create", args=args, **_hermes_kwargs())
    refire = hook(
        tool_name="story_run_create",
        args=args,
        **_hermes_kwargs(session_id="cron-session-2", tool_call_id="call_9"),
    )
    assert first == refire
    assert first["args"]["binding"] == {
        "harness": "hermes",
        "binding_key": binding_key_for_cron("job-1", "exec-1", "workflow:synthetic.x"),
        "origin": "cron",
    }


def test_hook_without_ids_changes_nothing():
    """Hook without ids changes nothing."""
    hook = make_pre_tool_call()
    for kwargs in (_hermes_kwargs(session_id=""), _hermes_kwargs(tool_call_id="")):
        assert hook(tool_name="story_job_submit", args={}, **kwargs) is None
        assert (
            hook(tool_name="story_run_create", args={"story_id": "s"}, **kwargs) is None
        )


def test_hook_never_raises_on_odd_input():
    """Hook never raises on odd input."""

    def broken():
        raise RuntimeError("synthetic")

    hook = make_pre_tool_call(broken)
    assert hook(tool_name="story_run_create", args=None, **_hermes_kwargs()) is None
    assert hook(tool_name=None, args={}, **_hermes_kwargs()) is None
    # A broken cron reader falls back to the interactive key.
    directive = hook(
        tool_name="story_run_create", args={"story_id": "w"}, **_hermes_kwargs()
    )
    assert directive["args"]["binding"]["origin"] == "interactive"


def test_plugin_registers_the_hook_with_the_cron_reader():
    """Plugin registers the hook with the cron reader."""
    from openbb_agents.hermes_integration import hermes_plugin

    registered = {}
    execution = SimpleNamespace(job_id="job-1", execution_id="exec-1")

    class Ctx:
        """Minimal stand-in for Hermes' PluginContext (register_hook, cron reader)."""

        def register_hook(self, name, callback, **_):
            registered[name] = callback

        def current_cron_execution(self):
            return execution

    hermes_plugin.register(Ctx())
    assert set(registered) == {"pre_tool_call"}
    directive = registered["pre_tool_call"](
        tool_name="story_run_create", args={"story_id": "w"}, **_hermes_kwargs()
    )
    assert directive["args"]["binding"]["origin"] == "cron"


def test_binding_module_imports_nothing_from_hermes():
    """Binding module imports nothing from hermes."""
    tree = ast.parse(inspect.getsource(binding))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"hermes", "hermes_cli", "hermes_agent", "cron", "tools"}
