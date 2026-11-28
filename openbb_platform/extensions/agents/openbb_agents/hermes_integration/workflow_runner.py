"""Deterministic, notebook-free workflow executor (#1340-T03).

``run_workflow`` admits a workflow document against live tool hashes, creates a
digest-bound registry run, executes its stages in dependency order through a
``ToolInvoker`` and checkpoints each result. There is no retry, no fallback and
no LLM: the first failing stage ends the run and later stages are ``not_run``.
A rejected workflow never reaches the invoker.

Notebooks, kernels and ``notebook_guide`` are not part of this path; the
``--forbid-notebooks`` CLI flag proves it with an audit hook (``notebook_guard``).
Only the synthetic pure-math workflow is wired (CLAUDE.md Lead decision Q5).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
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
_CHECKPOINT_TOOL = "story_run_checkpoint"
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

    @property
    def succeeded(self) -> bool:
        """Every stage ran to success."""
        return (
            self.admitted
            and self.error is None
            and all(s.status == "succeeded" for s in self.stages)
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


def _concentration_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {"weights": dict(ctx["inputs"]["weights"])}


def _construction_args(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {"effective": dict(ctx["inputs"]["weights"])}


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
    "story_concentration": _concentration_args,
    "story_construction_targets": _construction_args,
    _CHECKPOINT_TOOL: _checkpoint_args,
}


def _reject_result(
    document: Any, admission: Any, stage_ids: Sequence[str]
) -> WorkflowRunResult:
    return WorkflowRunResult(
        admitted=False,
        workflow_id=admission.workflow_id,
        workflow_manifest_sha256=admission.workflow_manifest_sha256,
        manifest_version=None,
        run_id=None,
        stages=tuple(StageResult(stage_id, "not_run") for stage_id in stage_ids),
        rejections=admission.rejections,
    )


def _document_stage_ids(document: Any) -> list[str]:
    stages = document.get("stages") if isinstance(document, Mapping) else None
    if not isinstance(stages, list):
        return []
    return [s["id"] for s in stages if isinstance(s, Mapping) and "id" in s]


async def run_workflow(
    document: Any,
    inputs: Mapping[str, Any],
    invoker: ToolInvoker,
    *,
    live_tools: Mapping[str, str],
) -> WorkflowRunResult:
    """Admit and execute ``document``; never retries, never falls back."""
    admission = admit_workflow(document, live_tools=live_tools)
    if not admission.admitted:
        return _reject_result(document, admission, _document_stage_ids(document))

    manifest = WorkflowManifest.model_validate(document)
    digest = admission.workflow_manifest_sha256 or ""
    stages = _ordered(manifest)
    not_run = tuple(StageResult(s.id, "not_run") for s in stages)
    server = next(iter(manifest.capabilities.values())).server

    try:
        run = await invoker.call(
            server, "story_run_create", {"story_id": f"workflow:{manifest.workflow_id}"}
        )
        if run.get("workflow_manifest_sha256") != digest:
            raise RuntimeError("registry run is not bound to this workflow digest")
    except Exception as error:  # pylint: disable=broad-exception-caught
        return WorkflowRunResult(
            True,
            manifest.workflow_id,
            digest,
            None,
            None,
            not_run,
            error=f"run_create_failed: {type(error).__name__}"[:_MAX_ERROR],
        )

    state = {"run_id": run["run_id"], "version": run["state_version"]}
    hashes: dict[str, str] = {}
    evidence: list[str] = []
    outputs: dict[str, Any] = {}
    results: list[StageResult] = []

    async def checkpoint(stage_id: str, status: str, body: Mapping[str, Any]) -> None:
        reply = await invoker.call(
            server,
            _CHECKPOINT_TOOL,
            {
                "run_id": state["run_id"],
                "expected_version": state["version"],
                "stage_id": stage_id,
                "status": status,
                "state": dict(body),
            },
        )
        state["version"] = reply["state_version"]

    for position, stage in enumerate(stages):
        pin = manifest.capabilities[stage.capabilities[0]]
        builder = _ARGUMENTS.get(pin.tool)
        try:
            if builder is None:
                raise LookupError("no argument binding for tool")
            context = {
                "inputs": inputs,
                "stage_id": stage.id,
                "hashes": hashes,
                "evidence": evidence,
                **state,
            }
            output = await invoker.call(pin.server, pin.tool, builder(context))
            output_sha = canonical_json_sha256(output)
            evidence_id = f"{digest[:12]}:{stage.id}:{output_sha[:12]}"
            if pin.tool == _CHECKPOINT_TOOL:
                state["version"] = output["state_version"]
            else:
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

    return WorkflowRunResult(
        True,
        manifest.workflow_id,
        digest,
        run.get("manifest_version"),
        run["run_id"],
        tuple(results),
        outputs=outputs,
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
            }
            for s in result.stages
        ],
        "rejections": [{"code": r.code, "detail": r.detail} for r in result.rejections],
        "outputs": dict(result.outputs),
        "error": result.error,
        "notebook_guard": guard,
    }


async def _run_in_process(
    document: Any, inputs: Mapping[str, Any], profile: str
) -> WorkflowRunResult:
    from fastmcp import Client  # pylint: disable=import-outside-toplevel

    server = build_server(profile, principal="workflow-run")
    live_tools = await server_tool_hashes(server, profile)
    async with Client(server) as client:
        return await run_workflow(
            document, inputs, FastMcpInvoker(client), live_tools=live_tools
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Exit codes: 0 succeeded, 1 stage/run failed, 2 rejected, 3 usage."""
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
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    if args.forbid_notebooks:
        notebook_guard.install()
    try:
        document = _load_document(args)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"usage error: {type(error).__name__}\n")
        return 3

    inputs = {"weights": dict(SYNTHETIC_WEIGHTS)}
    result = asyncio.run(_run_in_process(document, inputs, args.server))
    guard = notebook_guard.stats() if args.forbid_notebooks else None
    if args.format == "json":
        sys.stdout.write(json.dumps(_as_json(result, guard), indent=2) + "\n")
    else:
        sys.stdout.write(("succeeded" if result.succeeded else "not succeeded") + "\n")
        for stage in result.stages:
            sys.stdout.write(f"  {stage.stage_id}: {stage.status}\n")
    if not result.admitted:
        return 2
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
