"""Real-path replay probe for resumable Hermes runs (#1341).

``python -m openbb_agents.hermes_integration.replay_probe --scenario
duplicate-delivery --format json`` builds the in-process ``portfolio-ops`` MCP
server over its own temporary run store and job store, derives Hermes keys with
the OpenBB ``pre_tool_call`` hook (``binding``) from synthetic session and
tool-call IDs, and delivers every story mutation twice:

- ``story_run_create``: the same Hermes call re-delivered (same tool call ID);
- ``story_job_submit``, ``story_paper_prepare`` and ``story_artifact_table``:
  re-issued by the model under a new tool call ID, so a new delivery key.

It then reads the outcomes back from SQLite (not from the replies) and expects
two deliveries and one outcome per operation. The ``cancel`` scenario runs
``story_run_cancel`` over a finished, a claimed and a queued job plus a pending
paper request, then again after the claimed job completes. Exit codes: 0 all
single outcomes, 1 a duplicate or missing outcome, 3 usage. Synthetic data only: no
services, no network, no credentials. The probe always uses a fresh temporary
directory, points every story store and home directory at it for the duration
of the run, and refuses to run if a store would resolve outside it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sqlite3
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from openbb_agents.hermes_integration.binding import make_pre_tool_call

SCENARIOS = ("duplicate-delivery", "cancel")
WORKFLOW = "workflow:synthetic.concentration_review"
SESSION = "synthetic-probe-session"
PRINCIPAL = "replay-probe"
_ENV = (
    "HOME",
    "USERPROFILE",
    "OPENBB_STORY_RUN_STORE",
    "OPENBB_STORY_ARTIFACT_ROOT",
    "OPENBB_STORY_PAPER_ROOT",
    "OPENBB_STORY_APPROVAL_KEY",
)
BACKTEST = {
    "config": {
        "strategy": "buy_and_hold",
        "universe": ["AAA", "BBB"],
        "start": "2023-01-03",
        "end": "2024-12-31",
    },
    "strategy_params": {"symbols": ["AAA", "BBB"]},
}
BATCH = {
    "plan_id": "synthetic-plan-1",
    "tickets": [{"symbol": "AAA", "action": "Buy", "quantity": "10"}],
    "verdict_gate_pass": True,
    "verdict_gates": [
        {"name": "PBO", "threshold": "< 0.5", "actual": "0.21", "passed": True}
    ],
}
TABLE = {"columns": ["symbol", "weight"], "rows": [["AAA", 0.5], ["BBB", 0.5]]}


class ProbeRefused(RuntimeError):
    """A store would resolve outside the probe's temporary directory."""


@contextmanager
def _sandbox() -> Iterator[Path]:
    """Yield a fresh temporary root that every story store and home points at."""
    saved = {name: os.environ.get(name) for name in _ENV}
    # The job store may hold its SQLite file open on Windows until exit.
    with tempfile.TemporaryDirectory(
        prefix="gh1341-probe-", ignore_cleanup_errors=True
    ) as raw:
        root = Path(raw).resolve()
        (root / "home").mkdir()
        os.environ.update(
            {
                "HOME": str(root / "home"),
                "USERPROFILE": str(root / "home"),
                "OPENBB_STORY_RUN_STORE": str(root / "runs.sqlite"),
                "OPENBB_STORY_ARTIFACT_ROOT": str(root / "artifacts"),
                "OPENBB_STORY_PAPER_ROOT": str(root / "paper"),
                "OPENBB_STORY_APPROVAL_KEY": secrets.token_hex(32),
            }
        )
        try:
            yield root
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _ensure_contained(root: Path) -> None:
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.story_adapters.artifacts import default_artifact_root
    from openbb_mcp_server.story_adapters.paper import default_paper_root
    from openbb_mcp_server.story_adapters.registry import default_store_path

    for path in (default_store_path(), default_artifact_root(), default_paper_root()):
        if not _inside(root, path):
            raise ProbeRefused("a story store resolves outside the probe directory")


def _count(database: Path, sql: str, params: Sequence[Any] = ()) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute(sql, params).fetchone()[0])


def _receipt_deliveries(database: Path, tool: str, run_id: str) -> int:
    return _count(
        database,
        "SELECT COALESCE(SUM(deliveries), 0) FROM story_receipts"
        " WHERE tool = ? AND run_id = ?",
        (tool, run_id),
    )


class _HermesCalls:
    """Calls tools the way Hermes would: hook first, shallow merge, dispatch."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._hook = make_pre_tool_call()

    async def call(self, tool: str, args: Mapping[str, Any], tool_call_id: str) -> Any:
        arguments = dict(args)
        directive = self._hook(
            tool_name=f"mcp__openbb__{tool}",
            args=dict(arguments),
            task_id="synthetic-task",
            session_id=SESSION,
            tool_call_id=tool_call_id,
            turn_id="synthetic-turn",
            api_request_id="synthetic-request",
            middleware_trace=[],
        )
        if directive and directive.get("action") == "modify":
            arguments = {**arguments, **directive["args"]}
        result = await self._client.call_tool(tool, arguments)
        content = result.structured_content
        return content if content is not None else result.data


@asynccontextmanager
async def _harness(root: Path) -> AsyncIterator[tuple[_HermesCalls, Any]]:
    """Yield a Hermes-style caller and the job service over the probe's stores."""
    # pylint: disable=import-outside-toplevel
    from fastmcp import Client
    from openbb_core.api.dependency.jobs import get_job_service
    from openbb_core.api.rest_api import app
    from openbb_core.app.jobs.registry import JobRegistry
    from openbb_core.app.jobs.sqlite_store import SqliteJobStore
    from openbb_core.app.service.job_service import JobService
    from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

    from openbb_agents.hermes_integration.workflow_admit import build_server

    service = JobService(
        store=SqliteJobStore(root / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
    )
    previous = app.dependency_overrides.get(get_job_service)
    app.dependency_overrides[get_job_service] = lambda: service
    try:
        server = build_server("portfolio-ops", principal=PRINCIPAL)
        _ensure_contained(root)
        async with Client(server) as client:
            yield _HermesCalls(client), service
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_job_service, None)
        else:
            app.dependency_overrides[get_job_service] = previous


async def _duplicate_delivery(root: Path) -> dict[str, Any]:
    jobs_db = root / "jobs.db"
    runs_db = root / "runs.sqlite"
    async with _harness(root) as (hermes, _service):
        create = {"story_id": WORKFLOW}
        first_run = await hermes.call("story_run_create", create, "call-run-1")
        again_run = await hermes.call("story_run_create", create, "call-run-1")
        run_id = first_run["run_id"]
        job = {"run_id": run_id, "kind": "story.backtest", "payload": BACKTEST}
        job_a = await hermes.call("story_job_submit", job, "call-job-1")
        job_b = await hermes.call("story_job_submit", job, "call-job-2")
        table = {"run_id": run_id, "format": "csv", "table": TABLE}
        art_a = await hermes.call(
            "story_artifact_table", {**table, "name": "weights"}, "call-art-1"
        )
        art_b = await hermes.call(
            "story_artifact_table", {**table, "name": "weights-retry"}, "call-art-2"
        )
        sandbox = await hermes.call(
            "story_paper_sandbox_create",
            {"run_id": run_id, "engine": "techtrade", "starting_cash": "100000"},
            "call-sandbox-1",
        )
        prep = {
            "sandbox_id": sandbox["sandbox_id"],
            "action": "submit_batch",
            "arguments": BATCH,
        }
        prep_a = await hermes.call("story_paper_prepare", prep, "call-prep-1")
        prep_b = await hermes.call("story_paper_prepare", prep, "call-prep-2")

    operations = [
        {
            "operation": "story_run_create",
            "deliveries": 2,
            "outcomes": _count(runs_db, "SELECT COUNT(*) FROM story_runs"),
            "bindings": _count(runs_db, "SELECT COUNT(*) FROM story_run_bindings"),
            "same_reply": again_run["run_id"] == run_id,
        },
        {
            "operation": "story_job_submit",
            "deliveries": _receipt_deliveries(runs_db, "story_job_submit", run_id),
            "outcomes": _count(jobs_db, "SELECT COUNT(*) FROM job_run"),
            "replay_of_set": job_b.get("replay_of") == job_a["operation_id"],
            "same_reply": job_b["job_id"] == job_a["job_id"],
        },
        {
            "operation": "story_artifact_table",
            "deliveries": _receipt_deliveries(runs_db, "story_artifact", run_id),
            "outcomes": _count(
                runs_db,
                "SELECT COUNT(*) FROM story_artifacts WHERE run_id = ?",
                (run_id,),
            ),
            "files": sum(1 for p in (root / "artifacts").rglob("*.csv") if p.is_file()),
            "same_reply": art_b["ref"]["artifact_id"] == art_a["ref"]["artifact_id"],
        },
        {
            "operation": "story_paper_prepare",
            "deliveries": _receipt_deliveries(runs_db, "story_paper_prepare", run_id),
            "outcomes": _count(
                runs_db,
                "SELECT COUNT(*) FROM story_paper_requests WHERE run_id = ?",
                (run_id,),
            ),
            "replay_of_set": prep_b.get("replay_of") == prep_a["operation_id"],
            "same_reply": prep_b["request_id"] == prep_a["request_id"],
        },
    ]
    ok = all(op["deliveries"] == 2 and op["outcomes"] == 1 for op in operations)
    return {
        "scenario": "duplicate-delivery",
        "workflow": WORKFLOW,
        "run_bound": first_run.get("binding", {}).get("origin") == "interactive",
        "operations": operations,
        "ok": ok,
    }


def _rows(database: Path, sql: str, params: Sequence[Any] = ()) -> list[Any]:
    with sqlite3.connect(database) as connection:
        return [list(row) for row in connection.execute(sql, params).fetchall()]


async def _cancel(root: Path) -> dict[str, Any]:
    # pylint: disable=import-outside-toplevel
    from openbb_core.app.jobs.models import JobResult

    runs_db = root / "runs.sqlite"
    jobs_db = root / "jobs.db"
    async with _harness(root) as (hermes, service):
        created = await hermes.call(
            "story_run_create", {"story_id": WORKFLOW}, "call-run-1"
        )
        run_id = created["run_id"]
        labels: dict[str, str] = {}
        for index, label in enumerate(("finished", "running", "queued")):
            payload = {
                **BACKTEST,
                "strategy_params": {"symbols": ["AAA"] * (index + 1)},
            }
            job = await hermes.call(
                "story_job_submit",
                {"run_id": run_id, "kind": "story.backtest", "payload": payload},
                f"call-job-{label}",
            )
            labels[job["job_id"]] = label
        done = service.claim_next("probe-worker")
        service.complete(done.run_id, JobResult(summary={"ok": True}))
        running = service.claim_next("probe-worker")
        sandbox = await hermes.call(
            "story_paper_sandbox_create",
            {"run_id": run_id, "engine": "techtrade", "starting_cash": "100000"},
            "call-sandbox-1",
        )
        await hermes.call(
            "story_paper_prepare",
            {
                "sandbox_id": sandbox["sandbox_id"],
                "action": "submit_batch",
                "arguments": BATCH,
            },
            "call-prep-1",
        )
        first = await hermes.call(
            "story_run_cancel", {"run_id": run_id}, "call-cancel-1"
        )
        service.complete(running.run_id, JobResult(summary={"ok": True}))
        second = await hermes.call(
            "story_run_cancel", {"run_id": run_id}, "call-cancel-2"
        )

    def _view(reply: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_state": reply["run_state"],
            "cancel_state": reply["cancel_state"],
            "jobs": [
                {"label": labels[job["job_id"]], "cancel_state": job["cancel_state"]}
                for job in reply["jobs"]
            ],
            "requests": reply["requests"],
        }

    job_status = {
        labels[job_id]: status
        for job_id, status in _rows(jobs_db, "SELECT run_id, status FROM job_run")
    }
    readback = {
        "job_status": job_status,
        "request_status": [
            row[0] for row in _rows(runs_db, "SELECT status FROM story_paper_requests")
        ],
        "cancel_requested_at_set": json.loads(
            _rows(runs_db, "SELECT record FROM story_runs")[0][0]
        ).get("cancel_requested_at")
        is not None,
        "cancel_receipts": _rows(
            runs_db,
            "SELECT state, deliveries FROM story_receipts"
            " WHERE tool = 'story_run_cancel'",
        ),
    }
    ok = (
        first["cancel_state"] == "cancel_requested"
        and second["run_state"] == "cancelled"
        and job_status
        == {"finished": "succeeded", "running": "succeeded", "queued": "cancelled"}
        and readback["request_status"] == ["withdrawn"]
        and readback["cancel_requested_at_set"]
        and readback["cancel_receipts"] == [["cancelled", 2]]
    )
    return {
        "scenario": "cancel",
        "workflow": WORKFLOW,
        "first": _view(first),
        "second": _view(second),
        "readback": readback,
        "ok": ok,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one probe scenario. Exit codes: 0 ok, 1 mismatch, 3 usage."""
    parser = argparse.ArgumentParser(prog="replay_probe", description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    try:
        with _sandbox() as root:
            run = _cancel if args.scenario == "cancel" else _duplicate_delivery
            report = asyncio.run(run(root))
    except ProbeRefused as error:
        sys.stderr.write(f"refused: {error}\n")
        return 3
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    elif args.scenario == "cancel":
        sys.stdout.write(
            f"first: {report['first']['cancel_state']},"
            f" second: {report['second']['run_state']}\n"
        )
    else:
        for op in report["operations"]:
            sys.stdout.write(
                f"{op['operation']}: deliveries {op['deliveries']},"
                f" outcomes {op['outcomes']}\n"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
