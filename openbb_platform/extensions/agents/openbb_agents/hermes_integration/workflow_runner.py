"""Deterministic, notebook-free workflow executor (#1340-T03).

``run_workflow`` admits a workflow document against live tool hashes, creates a
digest-bound registry run, executes its stages in dependency order through a
``ToolInvoker`` and checkpoints each result. There is no retry, no fallback and
no LLM: the first failing stage ends the run and later stages are ``not_run``.
A rejected workflow never reaches the invoker.

Notebooks, kernels and ``notebook_guide`` are not part of this path; the
``--forbid-notebooks`` CLI flag proves it with an audit hook (``notebook_guard``).
Only the synthetic pure-math workflow is wired (CLAUDE.md Lead decision Q5).

Resume (#1341): ``--resume RUN_ID`` reloads the run, refuses it when the
admitted workflow digest differs from the run's (``blocked``: start a new run),
skips every stage whose checkpoint holds ``succeeded`` and an
``output_sha256`` (reported ``reused``) and runs the rest. A checkpoint whose
reply was lost is reconciled by reading the run back, never rewritten. The run
reports success only when the server's ``story_run_outcome`` says
``succeeded``. ``--crash-after STAGE`` (only with
``OPENBB_HFP_FAULT_INJECTION=1``) hard-exits with 75 after that stage's
checkpoint is durable, to prove restart.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openbb_mcp_server.utils.schema_digest import canonical_json_sha256

from openbb_agents.hermes_integration import notebook_guard
from openbb_agents.hermes_integration.admission import (
    Rejection,
    admit_workflow,
)
from openbb_agents.hermes_integration.workflow import WorkflowManifest
from openbb_agents.hermes_integration.workflow_admit import (
    _PROFILE_SERVER,
    _load_document,
    build_server,
    server_tool_hashes,
)

# Fixed synthetic weight map: twelve fictitious names summing to 1.
SYNTHETIC_WEIGHTS: Mapping[str, float] = {
    "SYN_A": 0.22,
    "SYN_B": 0.16,
    "SYN_C": 0.12,
    "SYN_D": 0.10,
    "SYN_E": 0.09,
    "SYN_F": 0.08,
    "SYN_G": 0.07,
    "SYN_H": 0.05,
    "SYN_I": 0.04,
    "SYN_J": 0.03,
    "SYN_K": 0.02,
    "SYN_L": 0.02,
}
# Basket x-ray (#1342, W2): single names plus one commodity trust, so the
# look-through stays opaque for the trust and makes zero provider calls.
SYNTHETIC_BASKET: tuple[tuple[str, float], ...] = (
    ("SYN-A", 0.18),
    ("SYN-B", 0.14),
    ("SYN-C", 0.12),
    ("SYN-D", 0.10),
    ("SYN-E", 0.08),
    ("SYN-F", 0.07),
    ("SYN-G", 0.06),
    ("SYN-H", 0.05),
    ("SYN-GLD", 0.20),
)
SYNTHETIC_COMMODITY_TRUSTS: tuple[str, ...] = ("SYN-GLD",)
_CHECKPOINT_TOOL = "story_run_checkpoint"
_CREATE_TOOL = "story_run_create"
_GET_TOOL = "story_run_get"
_OUTCOME_TOOL = "story_run_outcome"
FAULT_ENV = "OPENBB_HFP_FAULT_INJECTION"
CRASH_EXIT = 75
# Registry tools the runner calls itself; each must be pinned (schema + access)
# like any stage capability so drift and understated access are caught.
_RUN_TOOLS = (_CREATE_TOOL, _CHECKPOINT_TOOL, _GET_TOOL, _OUTCOME_TOOL)
_MAX_ERROR = 200


class ToolInvoker(Protocol):
    """Calls one MCP tool and returns its structured result."""

    async def call(
        self, server: str, tool: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Invoke ``tool`` on ``server`` with flat ``arguments``."""


class FastMcpInvoker:
    """Invoker over an open in-process ``fastmcp.Client``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def call(
        self, server: str, tool: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Call the tool; the logical ``server`` name is fixed by the client."""
        del server
        result = await self._client.call_tool(tool, dict(arguments))
        content = result.structured_content
        return content if content is not None else {"result": result.data}


@dataclass(frozen=True)
class StageResult:
    """Outcome of one stage."""

    stage_id: str
    status: str  # succeeded | failed | not_run
    tool: str | None = None
    output_sha256: str | None = None
    evidence_ids: tuple[str, ...] = ()
    error: str | None = None
    reused: bool = False


@dataclass(frozen=True)
class WorkflowRunResult:
    """What a workflow run did; ``outputs`` hold the (synthetic) tool results."""

    admitted: bool
    workflow_id: str | None
    workflow_manifest_sha256: str | None
    manifest_version: str | None
    run_id: str | None
    stages: tuple[StageResult, ...]
    rejections: tuple[Rejection, ...] = ()
    outputs: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    outcome: str | None = None

    @property
    def succeeded(self) -> bool:
        """Every stage ran to success and the server's run outcome agrees."""
        return (
            self.admitted
            and self.error is None
            and all(s.status == "succeeded" for s in self.stages)
            and self.outcome == "succeeded"
        )


def _ordered(manifest: WorkflowManifest) -> list[Any]:
    """Stages in dependency order, stable with respect to document order."""
    remaining = list(manifest.stages)
    done: set[str] = set()
    ordered: list[Any] = []
    while remaining:
        ready = next(s for s in remaining if set(s.depends_on) <= done)
        remaining.remove(ready)
        done.add(ready.id)
        ordered.append(ready)
    return ordered


def synthetic_inputs(workflow_id: str) -> dict[str, Any]:
    """Return the fixed synthetic inputs of a shipped workflow."""
    if workflow_id == "synthetic.basket_xray":
        return {
            "basket": [{"symbol": s, "weight": w} for s, w in SYNTHETIC_BASKET],
            "commodity_trusts": list(SYNTHETIC_COMMODITY_TRUSTS),
        }
    return {"weights": dict(SYNTHETIC_WEIGHTS)}


def _upstream(ctx: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the outputs this stage reads, in its declared input order."""
    outputs = ctx.get("outputs") or {}
    stage = ctx.get("stage")
    names = [i.from_stage for i in stage.inputs] if stage is not None else []
    return [outputs[n] for n in names if n in outputs]


def _weights(ctx: Mapping[str, Any]) -> dict[str, float]:
    """Effective positions of an upstream look-through, else the input weights."""
    for output in _upstream(ctx):
        if isinstance(output.get("positions"), list):
            return {p["key"]: p["weight"] for p in output["positions"]}
    if "weights" not in ctx["inputs"]:
        raise LookupError("no upstream effective positions for this stage")
    return dict(ctx["inputs"]["weights"])


def _effective_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "basket": [dict(p) for p in ctx["inputs"]["basket"]],
        "commodity_trusts": list(ctx["inputs"]["commodity_trusts"]),
    }


def _concentration_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {"weights": _weights(ctx)}


def _construction_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {"effective": _weights(ctx)}


_TARGET_COLUMNS = ("name", "current", "target", "band_lo", "band_hi", "status")


def evidence_table(output: Mapping[str, Any]) -> dict[str, Any]:
    """Render one engine output as the evidence table written for it."""
    if isinstance(output.get("positions"), list):
        rows = [[p["key"], p["weight"]] for p in output["positions"]]
        return {"columns": ["key", "weight"], "rows": rows}
    if isinstance(output.get("targets"), list):
        rows = [[t[c] for c in _TARGET_COLUMNS] for t in output["targets"]]
        return {"columns": list(_TARGET_COLUMNS), "rows": rows}
    rows = [
        [key, value]
        for key, value in sorted(output.items())
        if isinstance(value, str | int | float | bool) or value is None
    ]
    return {"columns": ["metric", "value"], "rows": rows}


def _table_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    upstream = _upstream(ctx)
    if not upstream:
        raise LookupError("no upstream output to tabulate")
    return {
        "run_id": ctx["run_id"],
        "name": ctx["stage_id"],
        "stage_id": ctx["stage_id"],
        "format": "json",
        "table": evidence_table(upstream[0]),
    }


def _checkpoint_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": ctx["run_id"],
        "expected_version": ctx["version"],
        "stage_id": ctx["stage_id"],
        "status": "succeeded",
        "state": {"output_sha256": dict(ctx["hashes"])},
        "provenance": {"tool_call_ids": list(ctx["evidence"])},
    }


_ARGUMENTS: Mapping[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "story_basket_effective_positions": _effective_args,
    "story_artifact_table": _table_args,
    "story_concentration": _concentration_args,
    "story_construction_targets": _construction_args,
    _CHECKPOINT_TOOL: _checkpoint_args,
}


def _reject_result(
    admission: Any,
    stage_ids: Sequence[str],
    rejections: Sequence[Rejection] | None = None,
) -> WorkflowRunResult:
    return WorkflowRunResult(
        admitted=False,
        workflow_id=admission.workflow_id,
        workflow_manifest_sha256=admission.workflow_manifest_sha256,
        manifest_version=None,
        run_id=None,
        stages=tuple(StageResult(stage_id, "not_run") for stage_id in stage_ids),
        rejections=tuple(rejections or admission.rejections),
    )


def _run_tool_pins(manifest: WorkflowManifest) -> tuple[dict[str, Any], list]:
    """Return the pin of each run tool, and rejections for any not pinned."""
    pins: dict[str, Any] = {}
    for pin in manifest.capabilities.values():
        if pin.tool in _RUN_TOOLS:
            pins.setdefault(pin.tool, pin)
    missing = [
        Rejection("capability_unresolved", f"run tool '{tool}' is not pinned")
        for tool in _RUN_TOOLS
        if tool not in pins
    ]
    return pins, missing


def _document_stage_ids(document: Any) -> list[str]:
    stages = document.get("stages") if isinstance(document, Mapping) else None
    if not isinstance(stages, list):
        return []
    return [s["id"] for s in stages if isinstance(s, Mapping) and "id" in s]


def _reused(record: Mapping[str, Any], stage_id: str) -> str | None:
    """Return the recorded output hash if this stage's checkpoint succeeded."""
    if record.get("stage_status", {}).get(stage_id) != "succeeded":
        return None
    value = (record.get("state") or {}).get(stage_id, {}).get("output_sha256")
    if isinstance(value, str):
        return value
    return canonical_json_sha256(value) if value else None


async def _outcome(
    invoker: ToolInvoker, server: str, run_id: str
) -> tuple[str | None, str | None]:
    """Return ``(outcome, error)`` from the server's derived run outcome.

    ``story_run_outcome`` is a pinned run tool, so admission already proved
    the profile exposes it; a failed read is reported, never guessed.
    """
    try:
        reply = await invoker.call(server, _OUTCOME_TOOL, {"run_id": run_id})
    except Exception as error:  # pylint: disable=broad-exception-caught
        return None, f"outcome_unavailable: {type(error).__name__}"[:_MAX_ERROR]
    outcome = reply.get("outcome") if isinstance(reply, Mapping) else None
    if not isinstance(outcome, str):
        return None, "outcome_unavailable: no outcome in reply"
    return outcome, None


async def run_workflow(  # noqa: PLR0912,PLR0915  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    document: Any,
    inputs: Mapping[str, Any],
    invoker: ToolInvoker,
    *,
    live_tools: Mapping[str, str],
    resume_run_id: str | None = None,
    after_stage: Callable[[str, str], None] | None = None,
) -> WorkflowRunResult:
    """Admit and execute (or resume) ``document``; never retries a stage."""
    admission = admit_workflow(document, live_tools=live_tools)
    if not admission.admitted:
        return _reject_result(admission, _document_stage_ids(document))

    manifest = WorkflowManifest.model_validate(document)
    run_pins, missing = _run_tool_pins(manifest)
    if missing:
        return _reject_result(admission, _document_stage_ids(document), missing)
    digest = admission.workflow_manifest_sha256 or ""
    stages = _ordered(manifest)
    not_run = tuple(StageResult(s.id, "not_run") for s in stages)
    create, checkpoint_pin = run_pins[_CREATE_TOOL], run_pins[_CHECKPOINT_TOOL]

    try:
        if resume_run_id is not None:
            run = await invoker.call(
                create.server, _GET_TOOL, {"run_id": resume_run_id}
            )
        else:
            run = await invoker.call(
                create.server,
                create.tool,
                {"story_id": f"workflow:{manifest.workflow_id}"},
            )
        if run.get("workflow_manifest_sha256") != digest:
            if resume_run_id is not None:
                # The workflow changed since the run started: never resume it.
                return WorkflowRunResult(
                    True,
                    manifest.workflow_id,
                    digest,
                    run.get("manifest_version"),
                    resume_run_id,
                    not_run,
                    error="resume_blocked: workflow_changed; start a new run",
                    outcome="blocked",
                )
            raise RuntimeError("registry run is not bound to this workflow digest")
    except Exception as error:  # pylint: disable=broad-exception-caught
        phase = "run_resume_failed" if resume_run_id else "run_create_failed"
        return WorkflowRunResult(
            True,
            manifest.workflow_id,
            digest,
            None,
            resume_run_id,
            not_run,
            error=f"{phase}: {type(error).__name__}"[:_MAX_ERROR],
        )

    state = {"run_id": run["run_id"], "version": run["state_version"]}
    hashes: dict[str, str] = {}
    evidence: list[str] = []
    outputs: dict[str, Any] = {}
    results: list[StageResult] = []

    async def write(arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Write one checkpoint; a lost reply is reconciled, never rewritten."""
        try:
            reply = await invoker.call(
                checkpoint_pin.server, checkpoint_pin.tool, arguments
            )
        except Exception:
            record = await invoker.call(
                create.server, _GET_TOOL, {"run_id": state["run_id"]}
            )
            stage_id = arguments["stage_id"]
            landed = (
                record.get("stage_status", {}).get(stage_id) == arguments["status"]
                and (record.get("state") or {}).get(stage_id) == arguments["state"]
            )
            if not landed:
                raise
            reply = record
        state["version"] = reply["state_version"]
        return reply

    async def checkpoint(stage_id: str, status: str, body: Mapping[str, Any]) -> None:
        await write(
            {
                "run_id": state["run_id"],
                "expected_version": state["version"],
                "stage_id": stage_id,
                "status": status,
                "state": dict(body),
            }
        )

    for position, stage in enumerate(stages):
        pin = manifest.capabilities[stage.capabilities[0]]
        builder = _ARGUMENTS.get(pin.tool)
        recorded = _reused(run, stage.id) if resume_run_id else None
        if recorded is not None:
            evidence_id = f"{digest[:12]}:{stage.id}:{recorded[:12]}"
            hashes[stage.id] = recorded
            evidence.append(evidence_id)
            results.append(
                StageResult(
                    stage.id,
                    "succeeded",
                    pin.tool,
                    recorded,
                    (evidence_id,),
                    reused=True,
                )
            )
            continue
        try:
            if builder is None:
                raise LookupError("no argument binding for tool")
            context = {
                "inputs": inputs,
                "stage": stage,
                "outputs": outputs,
                "stage_id": stage.id,
                "hashes": hashes,
                "evidence": evidence,
                **state,
            }
            if pin.tool == _CHECKPOINT_TOOL:
                output = await write(builder(context))
            else:
                output = await invoker.call(pin.server, pin.tool, builder(context))
            output_sha = canonical_json_sha256(output)
            evidence_id = f"{digest[:12]}:{stage.id}:{output_sha[:12]}"
            if pin.tool != _CHECKPOINT_TOOL:
                await checkpoint(stage.id, "succeeded", {"output_sha256": output_sha})
                outputs[stage.id] = output
            hashes[stage.id] = output_sha
            evidence.append(evidence_id)
            results.append(
                StageResult(stage.id, "succeeded", pin.tool, output_sha, (evidence_id,))
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            results.append(
                StageResult(
                    stage.id,
                    "failed",
                    pin.tool,
                    error=f"{type(error).__name__}"[:_MAX_ERROR],
                )
            )
            # The stage failure above is the reported outcome; bookkeeping
            # failures on top of it add nothing.
            with contextlib.suppress(Exception):
                await checkpoint(stage.id, "failed", {})
            results.extend(StageResult(s.id, "not_run") for s in stages[position + 1 :])
            break
        if after_stage is not None:
            after_stage(state["run_id"], stage.id)

    outcome, outcome_error = await _outcome(invoker, create.server, run["run_id"])
    return WorkflowRunResult(
        True,
        manifest.workflow_id,
        digest,
        run.get("manifest_version"),
        run["run_id"],
        tuple(results),
        outputs=outputs,
        outcome=outcome,
        error=outcome_error,
    )


def _as_json(result: WorkflowRunResult, guard: dict[str, int] | None) -> dict[str, Any]:
    return {
        "admitted": result.admitted,
        "workflow_id": result.workflow_id,
        "workflow_manifest_sha256": result.workflow_manifest_sha256,
        "manifest_version": result.manifest_version,
        "run_id": result.run_id,
        "stages": [
            {
                "stage_id": s.stage_id,
                "status": s.status,
                "tool": s.tool,
                "output_sha256": s.output_sha256,
                "evidence_ids": list(s.evidence_ids),
                "error": s.error,
                "reused": s.reused,
            }
            for s in result.stages
        ],
        "rejections": [{"code": r.code, "detail": r.detail} for r in result.rejections],
        "outputs": dict(result.outputs),
        "error": result.error,
        "outcome": result.outcome,
        "notebook_guard": guard,
    }


def _crash_after(stage: str) -> Callable[[str, str], None]:
    """Fault hook: hard-exit (no cleanup) once ``stage`` is checkpointed."""

    def hook(run_id: str, stage_id: str) -> None:
        if stage_id == stage:
            sys.stdout.write(
                json.dumps({"run_id": run_id, "crashed_after": stage_id}) + "\n"
            )
            sys.stdout.flush()
            os._exit(CRASH_EXIT)  # pylint: disable=protected-access

    return hook


async def _run_in_process(
    document: Any,
    inputs: Mapping[str, Any],
    profile: str,
    *,
    resume_run_id: str | None = None,
    after_stage: Callable[[str, str], None] | None = None,
    owner_principal: str | None = None,
) -> WorkflowRunResult:
    from fastmcp import Client  # pylint: disable=import-outside-toplevel

    server = build_server(
        profile, principal="workflow-run", owner_principal=owner_principal
    )
    live_tools = await server_tool_hashes(server, profile)
    async with Client(server) as client:
        return await run_workflow(
            document,
            inputs,
            FastMcpInvoker(client),
            live_tools=live_tools,
            resume_run_id=resume_run_id,
            after_stage=after_stage,
        )


def run_plan(
    document: Any, owner_principal: str, run_id: str, profile: str = "portfolio-ops"
) -> WorkflowRunResult:
    """Run an approved plan's run as its recorded owner (jobs worker, #1342)."""
    workflow_id = document.get("workflow_id") if isinstance(document, Mapping) else ""
    return asyncio.run(
        _run_in_process(
            document,
            synthetic_inputs(str(workflow_id)),
            profile,
            resume_run_id=run_id,
            owner_principal=owner_principal,
        )
    )


def run_result_json(result: WorkflowRunResult) -> dict[str, Any]:
    """JSON form of a run result (no notebook-guard stats)."""
    return _as_json(result, None)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Exit codes: 0 succeeded, 1 stage/run failed or blocked, 2 rejected,
    3 usage, 75 injected crash.
    """
    parser = argparse.ArgumentParser(prog="workflow_runner", description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--workflow", help="ID of a shipped workflow")
    source.add_argument("--workflow-file", help="path to a workflow JSON document")
    parser.add_argument("--inputs", choices=("synthetic",), required=True)
    parser.add_argument("--server", choices=sorted(_PROFILE_SERVER), required=True)
    parser.add_argument(
        "--forbid-notebooks",
        action="store_true",
        help="install the audit-hook guard that refuses notebook access",
    )
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--resume", metavar="RUN_ID", help="resume this run")
    parser.add_argument(
        "--crash-after",
        metavar="STAGE",
        help=f"fault injection, needs {FAULT_ENV}=1: exit 75 after STAGE",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    if args.crash_after and os.environ.get(FAULT_ENV) != "1":
        sys.stderr.write(f"usage error: --crash-after needs {FAULT_ENV}=1\n")
        return 3
    if args.forbid_notebooks:
        notebook_guard.install()
    try:
        document = _load_document(args)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"usage error: {type(error).__name__}\n")
        return 3

    workflow_id = document.get("workflow_id") if isinstance(document, dict) else ""
    inputs = synthetic_inputs(str(workflow_id))
    result = asyncio.run(
        _run_in_process(
            document,
            inputs,
            args.server,
            resume_run_id=args.resume,
            after_stage=_crash_after(args.crash_after) if args.crash_after else None,
        )
    )
    guard = notebook_guard.stats() if args.forbid_notebooks else None
    if args.format == "json":
        sys.stdout.write(json.dumps(_as_json(result, guard), indent=2) + "\n")
    else:
        sys.stdout.write(("succeeded" if result.succeeded else "not succeeded") + "\n")
        for stage in result.stages:
            reused = " (reused)" if stage.reused else ""
            sys.stdout.write(f"  {stage.stage_id}: {stage.status}{reused}\n")
    if not result.admitted:
        return 2
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
