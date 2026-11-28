"""Workflow runner restart, resume and reconcile (#1341 T03).

Real in-process ``portfolio-ops`` server over a temporary run store; the only
seam is a pass-through invoker that counts calls, injects one crash or drops
one reply. Two real processes prove crash-and-resume end to end.
"""

# pylint: disable=import-outside-toplevel,redefined-outer-name

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from openbb_agents.hermes_integration.binding import binding_key_for_cron
from openbb_agents.hermes_integration.workflow_runner import (
    SYNTHETIC_WEIGHTS,
    StageResult,
    WorkflowRunResult,
    run_workflow,
)

AGENTS = Path(__file__).resolve().parents[3]
MCP_SERVER = AGENTS.parent / "mcp_server"
DOCUMENT = (
    AGENTS
    / "openbb_agents"
    / "hermes_integration"
    / "workflows"
    / "synthetic.concentration_review.workflow.json"
)
INPUTS = {"weights": dict(SYNTHETIC_WEIGHTS)}


class _Crash(BaseException):
    """Stands in for a killed process: escapes every ``except Exception``."""


class _Counting:
    """Pass-through invoker that counts calls and can drop one reply."""

    def __init__(self, inner, drop_reply_for=None):
        self.inner = inner
        self.calls = Counter()
        self.checkpoints = Counter()
        self.drop_reply_for = drop_reply_for

    async def call(self, server, tool, arguments):
        self.calls[tool] += 1
        reply = await self.inner.call(server, tool, arguments)
        if tool == "story_run_checkpoint":
            self.checkpoints[arguments["stage_id"]] += 1
            if arguments["stage_id"] == self.drop_reply_for:
                self.drop_reply_for = None
                raise ConnectionError("reply lost after the write landed")
        return reply


@pytest.fixture
def store(tmp_path, monkeypatch):
    """One temporary run store shared by every server built in a test."""
    path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(path))
    return path


def _session(scenario):
    """Run ``scenario(invoker_factory, live)`` against a fresh in-process server."""
    from fastmcp import Client
    from openbb_agents.hermes_integration.workflow_admit import (
        build_server,
        server_tool_hashes,
    )
    from openbb_agents.hermes_integration.workflow_runner import FastMcpInvoker

    async def main():
        server = build_server("portfolio-ops", principal="workflow-run")
        live = await server_tool_hashes(server, "portfolio-ops")
        async with Client(server) as client:
            return await scenario(FastMcpInvoker(client), live)

    return asyncio.run(main())


def _record(invoker, run_id):
    return invoker.call("platform", "story_run_get", {"run_id": run_id})


def _crash_after(stage):
    def hook(_run_id, stage_id):
        if stage_id == stage:
            raise _Crash(stage_id)

    return hook


def _crashed_run(document):
    """Start a run and crash it once ``concentration`` is checkpointed."""
    seen = {}

    def remember(run_id, stage_id):
        seen["run_id"] = run_id
        _crash_after("concentration")(run_id, stage_id)

    async def scenario(invoker, live):
        with pytest.raises(_Crash):
            await run_workflow(
                document, INPUTS, invoker, live_tools=live, after_stage=remember
            )

    _session(scenario)
    return seen["run_id"]


def test_resume_skips_checkpointed_stages(store):
    """A restarted runner reuses concentration and runs only what is left.

    The reused pure-math stage is recomputed, not read from a cache, and its
    checkpoint is not rewritten (#1342 T03 lead decision).
    """
    document = json.loads(DOCUMENT.read_text("utf-8"))
    run_id = _crashed_run(document)

    async def scenario(invoker, live):
        counting = _Counting(invoker)
        result = await run_workflow(
            document, INPUTS, counting, live_tools=live, resume_run_id=run_id
        )
        return result, counting, await _record(invoker, run_id)

    result, counting, record = _session(scenario)
    assert result.run_id == run_id
    assert [(s.stage_id, s.reused) for s in result.stages] == [
        ("concentration", True),
        ("construction", False),
        ("checkpoint", False),
    ]
    assert counting.calls["story_concentration"] == 1  # recomputed
    assert counting.calls["story_construction_targets"] == 1
    assert counting.calls["story_run_create"] == 0
    assert result.outcome == "succeeded" and result.succeeded
    assert record["state_version"] == 3  # one write per stage, none repeated
    with sqlite3.connect(store) as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_runs").fetchone()[0] == 1


def test_lost_checkpoint_reply_reconciles_not_rewrites(store):
    """A checkpoint that landed but whose reply was lost is read back, not re-sent."""
    document = json.loads(DOCUMENT.read_text("utf-8"))

    async def scenario(invoker, live):
        counting = _Counting(invoker, drop_reply_for="construction")
        result = await run_workflow(document, INPUTS, counting, live_tools=live)
        return result, counting, await _record(invoker, result.run_id)

    result, counting, record = _session(scenario)
    assert [s.status for s in result.stages] == ["succeeded"] * 3
    assert counting.checkpoints["construction"] == 1
    assert record["state_version"] == 3
    assert result.succeeded


def test_resume_after_drift_is_blocked_not_succeeded(store):
    """A changed workflow document is never resumed into the old run."""
    document = json.loads(DOCUMENT.read_text("utf-8"))
    run_id = _crashed_run(document)
    drifted = {**document, "title": "Changed after the run started"}

    async def scenario(invoker, live):
        counting = _Counting(invoker)
        result = await run_workflow(
            drifted, INPUTS, counting, live_tools=live, resume_run_id=run_id
        )
        return result, counting

    result, counting = _session(scenario)
    assert result.outcome == "blocked"
    assert not result.succeeded
    assert all(s.status == "not_run" for s in result.stages)
    assert counting.calls["story_construction_targets"] == 0
    assert counting.calls["story_run_checkpoint"] == 0


def test_runner_succeeded_requires_outcome_succeeded():
    """All stages succeeded is not enough: the run outcome must agree (D3)."""
    stages = tuple(StageResult(s, "succeeded") for s in ("a", "b"))
    base = {
        "admitted": True,
        "workflow_id": "w",
        "workflow_manifest_sha256": "d",
        "manifest_version": "w@1",
        "run_id": "r",
        "stages": stages,
    }
    assert WorkflowRunResult(**base, outcome="succeeded").succeeded
    for outcome in ("partial", "cancelled", "blocked", None):
        assert not WorkflowRunResult(**base, outcome=outcome).succeeded


def test_cron_refire_same_execution_one_run(store):
    """D4: one cron execution is one run however often it fires."""
    first = binding_key_for_cron("job-1", "exec-1", "synthetic.concentration_review")
    again = binding_key_for_cron("job-1", "exec-1", "synthetic.concentration_review")
    other = binding_key_for_cron("job-1", "exec-2", "synthetic.concentration_review")
    assert first == again != other

    async def scenario(invoker, _live):
        runs = []
        for key in (first, again, other):
            reply = await invoker.call(
                "platform",
                "story_run_create",
                {
                    "story_id": "workflow:synthetic.concentration_review",
                    "binding": {
                        "harness": "hermes",
                        "binding_key": key,
                        "origin": "cron",
                    },
                },
            )
            runs.append(reply["run_id"])
        return runs

    runs = _session(scenario)
    assert runs[0] == runs[1] != runs[2]


# --- two real processes ----------------------------------------------------


def _env(tmp_path, fault=True):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH"}}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        OPENBB_STORY_RUN_STORE=str(tmp_path / "runs.sqlite"),
        PYTHONPATH=os.pathsep.join([str(AGENTS), str(MCP_SERVER)]),
    )
    if fault:
        env["OPENBB_HFP_FAULT_INJECTION"] = "1"
    else:
        env.pop("OPENBB_HFP_FAULT_INJECTION", None)
    return env


def _module(tmp_path, module, *args, fault=True):
    return subprocess.run(
        [sys.executable, "-m", f"openbb_agents.hermes_integration.{module}", *args],
        cwd=tmp_path,
        env=_env(tmp_path, fault),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


RUNNER = ("--workflow", "synthetic.concentration_review", "--inputs", "synthetic")
RUNNER += ("--server", "portfolio-ops", "--format", "json")


def test_crash_flag_needs_the_fault_environment(tmp_path):
    """Without OPENBB_HFP_FAULT_INJECTION=1 the crash flag is a usage error."""
    done = _module(
        tmp_path, "workflow_runner", *RUNNER, "--crash-after", "x", fault=False
    )
    assert done.returncode == 3, done.stderr[-500:]


def test_two_process_crash_and_resume_one_outcome_per_operation(tmp_path):
    """Kill mid-workflow, resume in a new process, read one outcome from SQLite."""
    crashed = _module(
        tmp_path, "workflow_runner", *RUNNER, "--crash-after", "concentration"
    )
    assert crashed.returncode == 75, crashed.stderr[-2000:]
    run_id = json.loads(crashed.stdout.strip().splitlines()[0])["run_id"]

    resumed = _module(tmp_path, "workflow_runner", *RUNNER, "--resume", run_id)
    assert resumed.returncode == 0, resumed.stderr[-2000:]
    body = json.loads(resumed.stdout)
    assert body["run_id"] == run_id and body["outcome"] == "succeeded"
    assert [s["reused"] for s in body["stages"]] == [True, False, False]

    dump = _module(
        tmp_path, "run_receipts", "--run", run_id, "--principal", "workflow-run"
    )
    assert dump.returncode == 0, dump.stderr[-2000:]
    receipts = json.loads(dump.stdout)
    assert receipts["outcome"]["outcome"] == "succeeded"
    assert receipts["run"]["checkpoint_writes"] == 3
    assert receipts["run"]["stage_status"] == {
        "concentration": "succeeded",
        "construction": "succeeded",
        "checkpoint": "succeeded",
    }
    assert receipts["runs_in_store"] == 1
    assert str(tmp_path) not in dump.stdout  # hashes and states only, no paths


def test_run_receipts_unknown_run_exits_1(tmp_path):
    """An unknown run is reported, not invented."""
    done = _module(tmp_path, "run_receipts", "--run", "no-such-run")
    assert done.returncode == 1
    assert "unknown run" in done.stderr


# --- Run tools pinned and fail-closed outcome (#1341 CODE-5) -----------------


def test_shipped_workflow_pins_every_run_tool():
    """story_run_get and story_run_outcome are pinned like any capability."""
    from openbb_agents.hermes_integration import workflow_runner

    document = json.loads(DOCUMENT.read_text("utf-8"))
    pinned = {pin["tool"] for pin in document["capabilities"].values()}
    assert {"story_run_get", "story_run_outcome"} <= set(workflow_runner._RUN_TOOLS)
    assert set(workflow_runner._RUN_TOOLS) <= pinned


@pytest.mark.parametrize("tool", ["story_run_get", "story_run_outcome"])
def test_unpinned_run_read_tool_is_rejected(store, tool):
    """A workflow that does not pin a run read tool is refused, not run."""
    document = json.loads(DOCUMENT.read_text("utf-8"))
    document["capabilities"] = {
        key: pin for key, pin in document["capabilities"].items() if pin["tool"] != tool
    }

    async def scenario(invoker, live):
        return await run_workflow(document, INPUTS, invoker, live_tools=live)

    result = _session(scenario)
    assert not result.admitted
    assert not result.succeeded
    assert any(tool in r.detail for r in result.rejections)


def test_unavailable_outcome_fails_closed_with_a_code(store):
    """If story_run_outcome cannot be read, the run says so; never succeeded."""

    class _NoOutcome(_Counting):
        async def call(self, server, tool, arguments):
            if tool == "story_run_outcome":
                raise ConnectionError("outcome tool unreachable")
            return await super().call(server, tool, arguments)

    async def scenario(invoker, live):
        return await run_workflow(
            document, INPUTS, _NoOutcome(invoker), live_tools=live
        )

    document = json.loads(DOCUMENT.read_text("utf-8"))
    result = _session(scenario)
    assert all(s.status == "succeeded" for s in result.stages)
    assert not result.succeeded
    assert result.error is not None
    assert result.error.startswith("outcome_unavailable")
