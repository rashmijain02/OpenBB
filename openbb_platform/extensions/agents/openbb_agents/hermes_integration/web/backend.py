"""Server-side story facts the HFP sidecar reads (#1342 T02).

One principal, one run store, one job service: the same stores the
``story.workflow_run`` worker writes. The sidecar reads plans, approves them
as the human (``approve_plan``), and reads run outcomes through the
``story_run_outcome`` route function itself, so the card and the MCP tool
cannot disagree. Nothing here starts a run, submits a job or approves a paper
action.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.routing import APIRoute
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import (
    jobs as story_jobs,
    plans as story_plans,
)
from openbb_mcp_server.story_adapters.artifacts import ArtifactStore
from openbb_mcp_server.story_adapters.registry import (
    RunRecord,
    RunStore,
    WorkflowCatalog,
    default_workflow_dir,
)
from openbb_mcp_server.story_adapters.run_outcome import RunOutcome, read_submissions
from openbb_mcp_server.story_adapters.story_job_kinds import SubmissionLedger

# A job queued this long with no worker heartbeat as recent is ``worker_unavailable``.
QUEUE_TIMEOUT = timedelta(seconds=60)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RunFacts:
    """What the run card shows, all read from durable records."""

    record: RunRecord
    plan: story_plans.Plan | None
    outcome: RunOutcome | None
    jobs: list[tuple[str, str]]
    artifacts: list[tuple[str, str, str]]
    worker_unavailable: bool = False


class StoryBackend:
    """Plan, approval and run reads for one principal over shared stores."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        principal: str,
        store_path: Path,
        artifact_root: Path,
        service: JobService,
        workflow_dir: Path | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not principal:
            raise ValueError("StoryBackend requires a principal")
        self.principal = principal
        self.store_path = store_path
        self.service = service
        self._clock = clock
        self.workflows = WorkflowCatalog(
            workflow_dir if workflow_dir is not None else default_workflow_dir()
        )
        self.plans = story_plans.PlanStore(store_path)
        self._runs = RunStore(store_path)
        self._artifacts = ArtifactStore(artifact_root, store_path)
        router = story_jobs.build_router(
            self._runs,
            SubmissionLedger(store_path),
            principal,
            self.workflows,
            self._artifacts,
        )
        self._outcome = next(
            route.endpoint
            for route in router.routes
            if isinstance(route, APIRoute) and route.name == "story_run_outcome"
        )

    def plan(self, plan_id: str) -> story_plans.Plan | None:
        """One plan of this principal."""
        return self.plans.get(self.principal, plan_id)

    def issue_nonce(self, plan_id: str) -> str | None:
        """Issue a fresh one-use approval nonce for a pending plan, else ``None``."""
        return self.plans.issue_nonce(self.principal, plan_id)

    def approve(
        self, plan_id: str, *, plan_sha256: str, nonce: str
    ) -> tuple[story_plans.ApproveResult, story_plans.Plan | None]:
        """Approve as the human; the result maps through ``APPROVE_STATUS``."""
        return story_plans.approve_plan(
            self.plans,
            self.workflows,
            self.principal,
            plan_id,
            plan_sha256=plan_sha256,
            nonce=nonce,
        )

    def workflow_ids(self) -> list[dict[str, Any]]:
        """Admitted workflows (id, version, stage count) for the starter list."""
        return [
            {
                "workflow_id": summary.story_id.removeprefix("workflow:"),
                "version": summary.manifest_version,
                "stages": summary.stages,
            }
            for summary in self.workflows.summaries()
        ]

    def run(self, run_id: str) -> RunFacts | None:
        """Run facts of one owned run, else ``None``.

        The outcome comes from ``story_run_outcome``; ``None`` when it cannot
        be derived. Job states come from the shared job store.
        """
        record = self._runs.get(self.principal, run_id)
        if record is None:
            return None
        try:
            outcome: RunOutcome | None = self._outcome(
                run_id=run_id, service=self.service
            )
        except (HTTPException, sqlite3.Error, OSError, ValueError):
            outcome = None
        jobs: list[tuple[str, str]] = []
        queued_since: list[datetime] = []
        try:
            with sqlite3.connect(self.store_path, timeout=30) as connection:
                submissions = read_submissions(connection, self.principal, run_id)
        except sqlite3.Error:
            submissions = []
        for _stage, job_id in submissions:
            if job_id is None:
                continue
            try:
                job = self.service.get_run(job_id)
            except KeyError:
                jobs.append((job_id, "unknown"))
                continue
            jobs.append((job_id, str(job.status)))
            if str(job.status) == "queued":
                queued_since.append(job.available_at or job.created_at)
        plan = self.plans.by_run(run_id)
        if plan is not None and plan.principal != self.principal:
            plan = None
        try:
            artifacts = [
                (item.ref.artifact_id, item.ref.sha256, str(item.kind))
                for item in self._artifacts.list(self.principal, run_id=run_id)
            ]
        except (sqlite3.Error, ValueError):
            artifacts = []
        return RunFacts(
            record=record,
            plan=plan,
            outcome=outcome,
            jobs=jobs,
            artifacts=artifacts,
            worker_unavailable=self._worker_unavailable(queued_since),
        )

    def _worker_unavailable(self, queued_since: list[datetime]) -> bool:
        """Report a job waiting past ``QUEUE_TIMEOUT`` with no worker beat since.

        A busy worker still heartbeats, so a long queue alone is not an outage.
        """
        now = self._clock()
        if not any(now - since > QUEUE_TIMEOUT for since in queued_since):
            return False
        try:
            age = self.service.health(now).worker_heartbeat_age_seconds
        except (sqlite3.Error, OSError, ValueError):
            return True
        return age is None or age > QUEUE_TIMEOUT.total_seconds()
