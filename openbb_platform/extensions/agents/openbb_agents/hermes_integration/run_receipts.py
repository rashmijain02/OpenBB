"""Read-only receipt dump of one story run (#1341).

``python -m openbb_agents.hermes_integration.run_receipts --run RUN_ID
--format json`` opens the run store named by ``OPENBB_STORY_RUN_STORE`` (or
``--store``) read-only and prints, for that run: the run record's stage
states and checkpoint count, every logical-operation receipt, job submissions,
paper requests and artifacts, and the outcome derived from those durable
records (``story_run_outcome`` rules). Only IDs, hashes, states and counts are
printed: no payloads, arguments, results or file paths. Job states are read
from ``--jobs-db`` when given; without it a submitted job reads ``unknown``
and the outcome stays uncertain. Exit codes: 0 dumped, 1 unknown run, 3 usage.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openbb_mcp_server.story_adapters.registry import (
    RunRecord,
    StoryCatalog,
    WorkflowCatalog,
    default_manifest_dir,
    default_store_path,
    default_workflow_dir,
)
from openbb_mcp_server.story_adapters.run_outcome import (
    JobFact,
    derive_outcome,
    read_request_facts,
    read_submissions,
    stage_optional,
    utc_now,
)

from openbb_agents.hermes_integration.workflow_admit import in_process_principal

DEFAULT_PRINCIPAL = "workflow-run"


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _rows(connection: sqlite3.Connection, table: str, sql: str, params) -> list:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return connection.execute(sql, params).fetchall() if exists else []


def _job_states(jobs_db: Path | None, job_ids: list[str]) -> dict[str, str]:
    if jobs_db is None or not jobs_db.exists() or not job_ids:
        return {}
    marks = ",".join("?" * len(job_ids))  # placeholders only, values are bound
    sql = f"SELECT run_id, status FROM job_run WHERE run_id IN ({marks})"  # noqa: S608
    with _read_only(jobs_db) as connection:
        return dict(_rows(connection, "job_run", sql, job_ids))


def _artifacts_valid(record: RunRecord, artifacts: dict[str, str]) -> bool:
    """Cited artifacts must still be recorded (hash checks are the server's)."""
    cited = {a for p in record.provenance.values() for a in p.artifact_ids}
    return cited <= set(artifacts)


def dump(  # pylint: disable=too-many-locals
    store: Path, principal: str, run_id: str, jobs_db: Path | None = None
) -> dict[str, Any] | None:
    """Return the run's receipts and derived outcome, or ``None`` if unknown."""
    if not store.exists():
        return None
    with _read_only(store) as connection:
        row = _rows(
            connection,
            "story_runs",
            "SELECT record FROM story_runs WHERE run_id = ? AND principal = ?",
            (run_id, principal),
        )
        if not row:
            return None
        runs_in_store = connection.execute(
            "SELECT COUNT(*) FROM story_runs WHERE principal = ?", (principal,)
        ).fetchone()[0]
        record = RunRecord.model_validate_json(row[0][0])
        receipts = _rows(
            connection,
            "story_receipts",
            "SELECT tool, stage_id, state, deliveries, operation_id, args_sha256"
            " FROM story_receipts WHERE principal = ? AND run_id = ?"
            " ORDER BY created_at, tool",
            (principal, run_id),
        )
        submissions = read_submissions(connection, principal, run_id)
        requests = read_request_facts(connection, principal, run_id)
        artifacts = dict(
            _rows(
                connection,
                "story_artifacts",
                "SELECT artifact_id, json_extract(record, '$.ref.sha256')"
                " FROM story_artifacts WHERE principal = ? AND run_id = ?",
                (principal, run_id),
            )
        )
    states = _job_states(jobs_db, [j for _, j in submissions if j])
    jobs = [
        JobFact(stage_id, states.get(job_id) if job_id else None)
        for stage_id, job_id in submissions
    ]
    workflows = WorkflowCatalog(default_workflow_dir())
    workflow_id = workflows.parse_id(record.story_id)
    if workflow_id is not None:
        document = workflows.get(workflow_id)
        current = (
            record.workflow_manifest_sha256 is None
            or workflows.digest(workflow_id) == record.workflow_manifest_sha256
        )
    else:
        document = StoryCatalog(default_manifest_dir()).get(record.story_id)
        current = True
    outcome = derive_outcome(
        record,
        optional=stage_optional(document),
        workflow_current=current,
        jobs=jobs,
        requests=requests,
        artifacts_valid=_artifacts_valid(record, artifacts),
        now=utc_now(),
    )
    written = [s for s, status in record.stage_status.items() if status != "pending"]
    return {
        "run": {
            "run_id": record.run_id,
            "story_id": record.story_id,
            "workflow_manifest_sha256": record.workflow_manifest_sha256,
            "bound": record.binding is not None,
            "stage_status": dict(record.stage_status),
            "checkpoint_writes": record.state_version,
            "stages_written": len(written),
            "cancel_requested": record.cancel_requested_at is not None,
        },
        "runs_in_store": runs_in_store,
        "receipts": [
            {
                "tool": tool,
                "stage_id": stage_id,
                "state": state,
                "deliveries": deliveries,
                "operation_id": operation_id,
                "args_sha256": args_sha256,
            }
            for tool, stage_id, state, deliveries, operation_id, args_sha256 in receipts
        ],
        "jobs": [
            {"stage_id": job.stage_id, "status": job.status or "unknown"}
            for job in jobs
        ],
        "requests": dict(outcome.requests),
        "artifacts": [
            {"artifact_id": key, "sha256": value} for key, value in artifacts.items()
        ],
        "outcome": outcome.model_dump(mode="json", exclude={"stages"}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Exit codes: 0 dumped, 1 unknown run, 3 usage."""
    parser = argparse.ArgumentParser(prog="run_receipts", description=__doc__)
    parser.add_argument("--run", required=True, help="run ID to dump")
    parser.add_argument("--store", type=Path, help="run store (default: env)")
    parser.add_argument("--principal", default=DEFAULT_PRINCIPAL)
    parser.add_argument("--jobs-db", type=Path, help="openbb-jobs SQLite store")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    # A bare name is the in-process runner's server user; ``name#digest`` is
    # a story principal as stored.
    principal = (
        args.principal
        if "#" in args.principal
        else in_process_principal(args.principal)
    )
    report = dump(args.store or default_store_path(), principal, args.run, args.jobs_db)
    if report is None:
        sys.stderr.write("unknown run\n")
        return 1
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        outcome = report["outcome"]
        sys.stdout.write(
            f"{report['run']['run_id']}: {outcome['outcome']}"
            f"{' (uncertain)' if outcome['uncertain'] else ''},"
            f" {report['run']['checkpoint_writes']} checkpoint writes,"
            f" {len(report['receipts'])} receipts\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
