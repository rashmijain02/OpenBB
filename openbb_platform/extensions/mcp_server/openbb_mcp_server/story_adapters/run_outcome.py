"""Run outcome derived from durable records only (#1341, plan 3.5).

``derive_outcome`` is pure: it reads a run record plus facts loaded from the
run store (job states, paper request states, artifact validity) and returns
the first matching state of plan 3.5. Nothing here maps ``partial`` to
``succeeded`` (decision D3); an apply that never reported back is ``partial``
and ``uncertain`` (decision D6). The loaders read SQLite and tolerate a store
whose tables do not exist yet.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openbb_mcp_server.story_adapters.registry import RunRecord

OutcomeState = Literal[
    "blocked",
    "cancelled",
    "cancel_requested",
    "partial",
    "failed",
    "waiting_job",
    "running",
    "awaiting_approval",
    "needs_input",
    "succeeded",
    "ready",
]
# An ``applying`` request older than this never reported back (D6).
APPLY_STALE = timedelta(seconds=120)
_JOB_ACTIVE = {"queued", "running"}
_JOB_OK = {"succeeded", "succeeded_with_warnings"}


@dataclass(frozen=True)
class JobFact:
    """One recorded submission; ``status`` is ``None`` without a durable job."""

    stage_id: str | None
    status: str | None


@dataclass(frozen=True)
class RequestFact:
    """One paper request as stored."""

    status: str
    expires_at: datetime
    applying_at: datetime | None


class RunOutcome(BaseModel):
    """What a run amounts to, from durable records."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    outcome: OutcomeState
    uncertain: bool = False
    reason: str | None = None
    workflow_current: bool
    cancel_requested_at: datetime | None
    stages: dict[str, str]
    jobs: dict[str, int]
    requests: dict[str, int]


def utc_now() -> datetime:
    """Return the current UTC time (a seam for expiry tests)."""
    return datetime.now(timezone.utc)


def request_status(fact: RequestFact, now: datetime) -> str:
    """Return the stored status, ``expired`` for a pending request past expiry."""
    if fact.status == "pending" and fact.expires_at <= now:
        return "expired"
    return fact.status


def _state(  # noqa: PLR0911,PLR0912  # pylint: disable=too-many-return-statements,too-many-branches
    record: RunRecord,
    *,
    optional: Mapping[str, bool],
    workflow_current: bool,
    jobs: Sequence[JobFact],
    requests: Sequence[RequestFact],
    artifacts_valid: bool,
    now: datetime,
) -> tuple[OutcomeState, str | None, bool]:
    if not workflow_current:
        return "blocked", "workflow_changed", False
    active = [job for job in jobs if job.status in _JOB_ACTIVE]
    applying = [fact for fact in requests if fact.status == "applying"]
    stale = [
        fact
        for fact in applying
        if fact.applying_at is None or now - fact.applying_at >= APPLY_STALE
    ]
    if record.cancel_requested_at is not None:
        if active or applying:
            return "cancel_requested", "cancel_in_flight", bool(stale)
        return "cancelled", "run_cancelled", False
    if stale:
        return "partial", "apply_uncertain", True
    if any(job.status is None for job in jobs):
        return "partial", "submission_without_job", True

    def mandatory(stage_id: str | None) -> bool:
        return stage_id is None or not optional.get(stage_id, False)

    latest: dict[str | None, str | None] = {}
    for job in jobs:  # oldest first: the last one per stage wins
        latest[job.stage_id] = job.status
    stages = record.stage_status
    if any(status == "failed" and mandatory(s) for s, status in stages.items()):
        return "failed", "stage_failed", False
    if any(status == "failed" and mandatory(s) for s, status in latest.items()):
        return "failed", "job_failed", False
    if active:
        return "waiting_job", None, False
    if applying:
        return "running", "apply_in_flight", False
    statuses = {request_status(fact, now) for fact in requests}
    if "pending" in statuses:
        return "awaiting_approval", None, False
    if "expired" in statuses:
        return "needs_input", "approval_expired", False
    required = [s for s in stages if mandatory(s)]
    if stages and all(stages[s] == "succeeded" for s in required):
        if any(st not in _JOB_OK for s, st in latest.items() if mandatory(s)):
            return "partial", "job_not_succeeded", False
        if not artifacts_valid:
            return "failed", "artifact_invalid", False
        optional_failed = any(
            status == "failed" for s, status in stages.items() if not mandatory(s)
        ) or any(st not in _JOB_OK for s, st in latest.items() if not mandatory(s))
        if optional_failed:
            return "partial", "optional_stage_failed", False
        return "succeeded", None, False
    if any(status != "pending" for status in stages.values()):
        return "running", None, False
    return "ready", None, False


def derive_outcome(  # pylint: disable=too-many-arguments
    record: RunRecord,
    *,
    optional: Mapping[str, bool],
    workflow_current: bool,
    jobs: Sequence[JobFact],
    requests: Sequence[RequestFact],
    artifacts_valid: bool,
    now: datetime,
) -> RunOutcome:
    """Return the first matching state of plan 3.5; pure."""
    outcome, reason, uncertain = _state(
        record,
        optional=optional,
        workflow_current=workflow_current,
        jobs=jobs,
        requests=requests,
        artifacts_valid=artifacts_valid,
        now=now,
    )
    return RunOutcome(
        run_id=record.run_id,
        outcome=outcome,
        uncertain=uncertain,
        reason=reason,
        workflow_current=workflow_current,
        cancel_requested_at=record.cancel_requested_at,
        stages=dict(record.stage_status),
        jobs=dict(Counter(job.status or "no_job" for job in jobs)),
        requests=dict(Counter(request_status(fact, now) for fact in requests)),
    )


def stage_optional(document: Mapping[str, Any] | None) -> dict[str, bool]:
    """``stage_id -> optional`` from a workflow or story document."""
    stages = (document or {}).get("stages") or []
    return {
        stage["id"]: bool(stage.get("optional", False))
        for stage in stages
        if isinstance(stage, Mapping) and "id" in stage
    }


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def read_request_facts(
    connection: sqlite3.Connection, principal: str, run_id: str
) -> list[RequestFact]:
    """Paper requests of one run (status and timestamps only)."""
    if not _has_table(connection, "story_paper_requests"):
        return []
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(story_paper_requests)")
    }
    applying = "applying_at" if "applying_at" in columns else "NULL"
    rows = connection.execute(
        f"SELECT status, expires_at, {applying} FROM story_paper_requests"  # noqa: S608
        " WHERE principal = ? AND run_id = ? ORDER BY created_at",
        (principal, run_id),
    ).fetchall()
    return [
        RequestFact(status, datetime.fromisoformat(expires), _parse(started))
        for status, expires, started in rows
    ]


def read_submissions(
    connection: sqlite3.Connection, principal: str, run_id: str
) -> list[tuple[str | None, str | None]]:
    """``(stage_id, job_id)`` of every story job submission of one run."""
    if not _has_table(connection, "story_jobs"):
        return []
    return list(
        connection.execute(
            "SELECT stage_id, job_id FROM story_jobs"
            " WHERE principal = ? AND run_id = ? ORDER BY created_at, operation_id",
            (principal, run_id),
        ).fetchall()
    )
