"""Story jobs over the existing durable jobs service (#2218, N08).

Routes under ``/api/v1/story/runs/{run_id}/jobs``:

- ``POST``: submit one allowlisted job kind with a typed payload and a
  caller-chosen operation ID. Resubmitting the same operation returns the same
  job, so a lost response can be retried safely; reusing it for a different
  payload or run is a ``409``.
- ``GET`` (list and by job ID): status, result highlights, the result
  artifact's ref and any terminal error.
- On a Hermes-bound run (#1341), a model that re-issues the same submission
  under a new operation ID gets the first job back (``replay_of`` names the
  operation that owns it) unless that job failed or was cancelled.
- ``POST /{job_id}/cancel``: ``cancelled`` for a queued job, ``too_late``
  once a worker has claimed it (the worker never interrupts a handler), and
  ``already_finished`` for a terminal one.

Nothing here runs a handler: jobs are persisted with the core
``JobService`` and executed by the ``openbb-jobs`` worker. A kind whose engine
is not installed, or whose worker definition is not registered, is a ``503``
that says so. Every route is bound to the server's one principal.
"""

from __future__ import annotations

import contextlib
import copy
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.api.dependency.jobs import get_authenticated_job_service
from openbb_core.app.jobs.models import JobRun
from openbb_core.app.jobs.registry import UnknownJobDefinitionError
from openbb_core.app.service.job_service import JobService
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openbb_mcp_server.story_adapters import run_outcome
from openbb_mcp_server.story_adapters.artifacts import (
    ArtifactConflict,
    ArtifactExpired,
    ArtifactNotFound,
    ArtifactStore,
    default_artifact_root,
)
from openbb_mcp_server.story_adapters.paper import withdraw_pending_requests
from openbb_mcp_server.story_adapters.receipts import (
    Receipt,
    ReceiptLedger,
    args_digest,
    logical_operation_key,
    run_workflow_ref,
)
from openbb_mcp_server.story_adapters.registry import (
    RunStore,
    StoryCatalog,
    WorkflowCatalog,
    default_manifest_dir,
    default_store_path,
    default_workflow_dir,
    ensure_run_open,
    ensure_workflow_current,
)
from openbb_mcp_server.story_adapters.run_outcome import (
    JobFact,
    RunOutcome,
    derive_outcome,
    read_request_facts,
    read_submissions,
    stage_optional,
)
from openbb_mcp_server.story_adapters.story_job_kinds import (
    OPERATION_ID,
    KindUnavailable,
    StoryJobKind,
    StoryJobParams,
    Submission,
    SubmissionLedger,
    payload_digest,
    payload_model,
)

MAX_ACTIVE_JOBS = 4
_ACTIVE = {"queued", "running"}
_TERMINAL = {"succeeded", "succeeded_with_warnings", "failed", "cancelled"}
# A logical submission whose job ended like this may be submitted again.
_RETRYABLE = {"failed", "cancelled"}


class JobSubmit(BaseModel):
    """One story job: an allowlisted kind and its typed payload."""

    model_config = ConfigDict(extra="forbid")

    operation_id: Annotated[str, Field(pattern=OPERATION_ID)]
    kind: StoryJobKind
    payload: dict[str, Any] = Field(default_factory=dict)
    stage_id: str | None = Field(default=None, max_length=200)


class JobError(BaseModel):
    """A terminal error, as the worker recorded it."""

    model_config = ConfigDict(extra="forbid")

    type: str | None
    message: str | None


class StoryJob(BaseModel):
    """A story job as its principal sees it."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    operation_id: str
    run_id: str
    kind: str
    stage_id: str | None
    status: str
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    warnings: list[str]
    error: JobError | None
    replay_of: str | None = None


CancelState = Literal[
    "cancel_confirmed", "cancel_requested", "too_late", "already_finished"
]


class CancelOutcome(BaseModel):
    """What cancelling did, and the job after it."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["cancelled", "too_late", "already_finished"]
    cancel_state: CancelState
    job: StoryJob


class JobCancel(BaseModel):
    """One job's cancel state inside a run-level cancel."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    cancel_state: CancelState


class RequestCancel(BaseModel):
    """Paper requests touched by a run-level cancel."""

    model_config = ConfigDict(extra="forbid")

    withdrawn: int
    applying: int


class RunCancelOutcome(BaseModel):
    """What cancelling a run did.

    ``cancel_state`` is ``cancel_requested`` while any claimed job or
    ``applying`` request is still in flight (never interrupted),
    ``cancel_confirmed`` when this call stopped everything that was left, and
    ``already_finished`` when a repeat found nothing to do.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_state: Literal["cancel_requested", "cancelled"]
    cancel_state: CancelState
    cancel_requested_at: datetime
    jobs: list[JobCancel]
    requests: RequestCancel


def _view(
    submission: Submission, run: JobRun, replay_of: str | None = None
) -> StoryJob:
    failed = run.status == "failed"
    return StoryJob(
        replay_of=replay_of,
        job_id=run.run_id,
        operation_id=submission.operation_id,
        run_id=submission.run_id,
        kind=submission.kind,
        stage_id=submission.stage_id,
        status=run.status,
        attempt=run.attempt,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result=run.result.summary if run.result else None,
        warnings=list(run.result.warnings) if run.result else [],
        error=(
            JobError(type=run.error_type, message=run.error_message) if failed else None
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_router(  # pylint: disable=too-many-statements
    runs: RunStore,
    ledger: SubmissionLedger,
    principal: str,
    workflows: WorkflowCatalog | None = None,
    artifacts: ArtifactStore | None = None,
) -> APIRouter:
    """Return the story job routes bound to one principal."""
    workflow_catalog = workflows or WorkflowCatalog(default_workflow_dir())
    artifact_store = artifacts or ArtifactStore(default_artifact_root(), ledger.db_path)
    stories = StoryCatalog(default_manifest_dir())
    router = APIRouter(prefix="/api/v1/story/runs", tags=["story"])
    dedupe_prefix = f"story:{ArtifactStore.principal_key(principal)}:"
    receipts = ReceiptLedger(ledger.db_path)

    def _owned_run(run_id: str, *, mutating: bool = False):
        record = runs.get(principal, run_id)
        if record is None:
            # Another principal's run is indistinguishable from no run.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        if mutating:
            ensure_workflow_current(record, workflow_catalog)
            ensure_run_open(record)
        return record

    def _job(
        service: JobService, run_id: str, job_id: str
    ) -> tuple[Submission, JobRun]:
        _owned_run(run_id)
        submission = ledger.by_job(principal, run_id, job_id)
        if submission is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
        return submission, service.get_run(job_id)

    def _active_jobs(service: JobService) -> int:
        active = 0
        for job_id in ledger.open_job_ids(principal):
            try:
                active += service.get_run(job_id).status in _ACTIVE
            except KeyError:
                continue
        return active

    def _conflict(detail: str) -> HTTPException:
        return HTTPException(status.HTTP_409_CONFLICT, detail)

    def _job_key(run, stage_id: str | None, digest: str) -> str:
        return logical_operation_key(
            tool="story_job_submit",
            run_id=run.run_id,
            workflow_ref=run_workflow_ref(run),
            stage_id=stage_id,
            args_sha256=digest,
        )

    def _logical_owner(
        service: JobService, run, request: JobSubmit, digest: str
    ) -> tuple[str, str | None]:
        """Return the operation that owns this logical submission on a bound run.

        The first delivery owns it. A later delivery under another operation ID
        is pointed at the owner (``replay_of``) unless the owner's job failed or
        was cancelled; then this delivery takes the operation over.
        """
        logical_key = _job_key(run, request.stage_id, digest)
        receipt: Receipt | None = receipts.claim(
            principal,
            logical_key,
            tool="story_job_submit",
            run_id=run.run_id,
            workflow_ref=run_workflow_ref(run),
            stage_id=request.stage_id,
            args_sha256=digest,
            operation_id=request.operation_id,
        )
        while receipt is not None and receipt.operation_id != request.operation_id:
            owner = ledger.get(principal, receipt.operation_id)
            if owner is None or owner.job_id is None:
                # The owner crashed before its job was recorded: the core
                # dedupe key under the owner's operation ID finds or makes it.
                return receipt.operation_id, receipt.operation_id
            try:
                ended = service.get_run(owner.job_id).status in _RETRYABLE
            except KeyError:
                ended = True
            if not ended:
                return receipt.operation_id, receipt.operation_id
            if receipts.supersede(
                principal,
                logical_key,
                previous_operation_id=receipt.operation_id,
                operation_id=request.operation_id,
            ):
                break
            receipt = receipts.get(principal, logical_key)
        return request.operation_id, None

    @router.post(
        "/{run_id}/jobs",
        operation_id="story_job_submit",
        status_code=status.HTTP_202_ACCEPTED,
        openapi_extra={"mcp_config": {"name": "story_job_submit"}},
    )
    def story_job_submit(
        run_id: str,
        request: JobSubmit,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> StoryJob:
        """Queue one allowlisted story job; the same operation ID returns the same job."""
        run = _owned_run(run_id, mutating=True)
        if request.stage_id is not None and request.stage_id not in run.stage_status:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stage '{request.stage_id}' is not in {run.manifest_version}.",
            )
        try:
            model = payload_model(request.kind)
        except KindUnavailable as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(error)
            ) from error
        try:
            payload = model.model_validate(request.payload).model_dump(mode="json")
        except ValidationError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                error.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            ) from error
        digest = payload_digest(run_id, request.kind, request.stage_id, payload)
        operation_id, replay_of = request.operation_id, None
        existing = ledger.get(principal, operation_id)
        if run.binding is not None and (existing is None or existing.digest == digest):
            operation_id, replay_of = _logical_owner(service, run, request, digest)
            existing = ledger.get(principal, operation_id)
        if existing is None and _active_jobs(service) >= MAX_ACTIVE_JOBS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"At most {MAX_ACTIVE_JOBS} story jobs may be queued or running.",
            )
        submission = existing or ledger.record(
            Submission(
                principal=principal,
                operation_id=operation_id,
                run_id=run_id,
                kind=request.kind,
                stage_id=request.stage_id,
                digest=digest,
                job_id=None,
                created_at=_now(),
            )
        )
        if submission.digest != digest:
            raise _conflict(
                f"Operation '{operation_id}' was already used for a" " different job."
            )
        params = StoryJobParams(
            principal=principal,
            run_id=run_id,
            operation_id=operation_id,
            stage_id=request.stage_id,
            payload=payload,
        ).model_dump(mode="json")
        try:
            # The core dedupe key makes this safe to repeat: a retry after a
            # lost response, or after a crash before the job ID was recorded,
            # returns the run that already exists.
            job = service.enqueue(
                request.kind,
                params,
                idempotency_key=dedupe_prefix + operation_id,
            )
        except UnknownJobDefinitionError as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"The {request.kind} worker definition is not registered; install"
                " openbb-mcp-server where the jobs worker runs.",
            ) from error
        except ValidationError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                error.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            ) from error
        if job.job_name != request.kind or job.params != params:
            raise _conflict(f"Operation '{operation_id}' belongs to a different job.")
        ledger.attach_job(principal, operation_id, job.run_id)
        latest = runs.get(principal, run_id)
        if latest is not None and latest.cancel_requested_at is not None:
            # story_run_cancel ran between the open check and the enqueue and
            # could not see this job yet: cancel it here (#1341).
            # A worker that claimed it first refuses a cancelled run.
            with contextlib.suppress(ValueError):
                service.cancel(job.run_id)
            ensure_run_open(latest)
        if run.binding is not None:
            receipts.record_outcome(
                principal,
                _job_key(run, request.stage_id, digest),
                operation_id=operation_id,
                outcome_ref=job.run_id,
                state="submitted",
            )
        return _view(submission, job, replay_of)

    @router.get(
        "/{run_id}/jobs",
        operation_id="story_job_list",
        openapi_extra={"mcp_config": {"name": "story_job_list"}},
    )
    def story_job_list(
        run_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> list[StoryJob]:
        """List this run's story jobs, oldest first."""
        _owned_run(run_id)
        return [
            _view(submission, service.get_run(submission.job_id))
            for submission in ledger.for_run(principal, run_id)
            if submission.job_id is not None
        ]

    @router.get(
        "/{run_id}/jobs/{job_id}",
        operation_id="story_job_get",
        openapi_extra={"mcp_config": {"name": "story_job_get"}},
    )
    def story_job_get(
        run_id: str,
        job_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> StoryJob:
        """Return one story job: status, highlights, result artifact or error."""
        return _view(*_job(service, run_id, job_id))

    @router.post(
        "/{run_id}/jobs/{job_id}/cancel",
        operation_id="story_job_cancel",
        openapi_extra={"mcp_config": {"name": "story_job_cancel"}},
    )
    def story_job_cancel(
        run_id: str,
        job_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> CancelOutcome:
        """Cancel a queued job; report too_late once a worker has claimed it."""
        submission, job = _job(service, run_id, job_id)
        if job.status in _TERMINAL:
            return CancelOutcome(
                outcome="already_finished",
                cancel_state="already_finished",
                job=_view(submission, job),
            )
        if job.status == "queued":
            try:
                cancelled = service.cancel(job_id)
            except ValueError:
                # A worker claimed it between the read and the cancel.
                job = service.get_run(job_id)
            else:
                return CancelOutcome(
                    outcome="cancelled",
                    cancel_state="cancel_confirmed",
                    job=_view(submission, cancelled),
                )
        return CancelOutcome(
            outcome="too_late", cancel_state="too_late", job=_view(submission, job)
        )

    def _record_cancel(record, state: str) -> None:
        """Receipt the cancel transition: hashes and states only."""
        digest = args_digest(record.run_id)
        key = logical_operation_key(
            tool="story_run_cancel",
            run_id=record.run_id,
            workflow_ref=run_workflow_ref(record),
            stage_id=None,
            args_sha256=digest,
        )
        receipt = receipts.claim(
            principal,
            key,
            tool="story_run_cancel",
            run_id=record.run_id,
            workflow_ref=run_workflow_ref(record),
            stage_id=None,
            args_sha256=digest,
            operation_id=record.run_id,
        )
        receipts.record_outcome(
            principal,
            key,
            operation_id=receipt.operation_id,
            outcome_ref=record.run_id,
            state="cancel_requested" if state == "cancel_requested" else "cancelled",
        )

    @router.post(
        "/{run_id}/cancel",
        operation_id="story_run_cancel",
        openapi_extra={"mcp_config": {"name": "story_run_cancel"}},
    )
    def story_run_cancel(
        run_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> RunCancelOutcome:
        """Cancel a run: stop queued work, never interrupt claimed work.

        Queued jobs are cancelled and pending paper requests withdrawn. A
        claimed job or an ``applying`` request is left to finish, so the run
        reports ``cancel_requested`` until none remain, then ``cancelled``.
        The run refuses new mutations from the first call on.
        """
        before = _owned_run(run_id)
        record = runs.request_cancel(principal, run_id)
        if record is None or record.cancel_requested_at is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        repeat = before.cancel_requested_at is not None
        results: list[JobCancel] = []
        for submission in ledger.for_run(principal, run_id):
            if submission.job_id is None:
                continue
            outcome = story_job_cancel(run_id, submission.job_id, service)
            results.append(
                JobCancel(job_id=submission.job_id, cancel_state=outcome.cancel_state)
            )
        counts = withdraw_pending_requests(ledger.db_path, principal, run_id)
        in_flight = counts["applying"] > 0 or any(
            item.cancel_state == "too_late" for item in results
        )
        changed = counts["withdrawn"] > 0 or any(
            item.cancel_state == "cancel_confirmed" for item in results
        )
        if in_flight:
            state: CancelState = "cancel_requested"
        elif repeat and not changed:
            state = "already_finished"
        else:
            state = "cancel_confirmed"
        if record.binding is not None:
            _record_cancel(record, state)
        return RunCancelOutcome(
            run_id=run_id,
            run_state="cancel_requested" if in_flight else "cancelled",
            cancel_state=state,
            cancel_requested_at=record.cancel_requested_at,
            jobs=results,
            requests=RequestCancel(**counts),
        )

    def _artifacts_valid(record) -> bool:
        cited = {
            artifact_id
            for provenance in record.provenance.values()
            for artifact_id in provenance.artifact_ids
        }
        for artifact_id in sorted(cited):
            try:
                artifact_store.read(principal, record.run_id, artifact_id)
            except (ArtifactNotFound, ArtifactExpired, ArtifactConflict, ValueError):
                return False
        return True

    @router.get(
        "/{run_id}/outcome",
        operation_id="story_run_outcome",
        openapi_extra={"mcp_config": {"name": "story_run_outcome"}},
    )
    def story_run_outcome(
        run_id: str,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> RunOutcome:
        """Report what a run amounts to, from durable records only.

        Read-only. ``partial`` is never success; an apply that never reported
        back reads ``partial`` with ``uncertain`` set; a changed workflow reads
        ``blocked`` (start a new run).
        """
        record = _owned_run(run_id)
        workflow_id = workflow_catalog.parse_id(record.story_id)
        document = (
            workflow_catalog.get(workflow_id)
            if workflow_id is not None
            else stories.get(record.story_id)
        )
        try:
            ensure_workflow_current(record, workflow_catalog)
            current = True
        except HTTPException:
            current = False
        jobs: list[JobFact] = []
        with sqlite3.connect(ledger.db_path, timeout=30) as connection:
            submissions = read_submissions(connection, principal, run_id)
            requests = read_request_facts(connection, principal, run_id)
        for stage_id, job_id in submissions:
            job_status = None
            if job_id is not None:
                try:
                    job_status = service.get_run(job_id).status
                except KeyError:
                    job_status = None
            jobs.append(JobFact(stage_id, job_status))
        return derive_outcome(
            record,
            optional=stage_optional(document),
            workflow_current=current,
            jobs=jobs,
            requests=requests,
            artifacts_valid=_artifacts_valid(record),
            now=run_outcome.utc_now(),
        )

    return router


def compose_story_jobs_app(
    source_app: FastAPI,
    *,
    principal: str,
    store_path: Path | None = None,
    workflow_dir: Path | None = None,
    artifact_root: Path | None = None,
) -> FastAPI:
    """Add the story job routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("Story jobs require an authenticated principal")
    db_path = store_path if store_path is not None else default_store_path()
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(
        build_router(
            RunStore(db_path),
            SubmissionLedger(db_path),
            principal,
            WorkflowCatalog(
                workflow_dir if workflow_dir is not None else default_workflow_dir()
            ),
            ArtifactStore(
                artifact_root if artifact_root is not None else default_artifact_root(),
                db_path,
            ),
        )
    )
    composed.openapi_schema = None
    return composed
