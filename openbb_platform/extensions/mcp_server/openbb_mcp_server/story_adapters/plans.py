"""Workflow plans: preview, human approval and start (#1342).

``story_plan_preview`` stores a ``pending`` plan of one admitted workflow and
returns its ``plan_id`` and ``plan_sha256``. Only a human can approve it,
through ``approve_plan`` (called by the HFP sidecar behind the WebUI, never an
MCP tool) with a one-use nonce bound to the plan hash. ``story_workflow_start``
then creates one run and one ``story.workflow_run`` job per approved plan; a
repeat returns the same run and job.

Rows live in ``story_plans`` of the run store. The plan hash covers the
workflow ID, version, manifest digest, every capability pin (schema + access),
the inputs digest and the expiry, so a drifted workflow supersedes the plan.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from openbb_core.api.dependency.jobs import get_authenticated_job_service
from openbb_core.app.service.job_service import JobService
from pydantic import BaseModel, ConfigDict, Field

from openbb_mcp_server.story_adapters.registry import (
    RunBinding,
    RunRecord,
    RunStore,
    WorkflowCatalog,
)
from openbb_mcp_server.story_adapters.story_job_kinds import OPERATION_ID

WORKFLOW_RUN_KIND = "story.workflow_run"
PLAN_TTL = timedelta(hours=24)
PLAN_ID = r"^plan_[a-f0-9]{32}$"
PlanState = Literal["pending", "approved", "started"]
ApproveResult = Literal[
    "approved",
    "already_approved",
    "plan_not_found",
    "plan_expired",
    "plan_superseded",
    "bad_nonce",
]
# HTTP status the sidecar maps each approval result to (plan 3.5).
APPROVE_STATUS: dict[str, int] = {
    "approved": 200,
    "already_approved": 200,
    "plan_not_found": 404,
    "plan_expired": 410,
    "plan_superseded": 409,
    "bad_nonce": 403,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS story_plans (
    principal TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    state TEXT NOT NULL,
    nonce_sha256 TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_at TEXT,
    run_id TEXT UNIQUE,
    PRIMARY KEY (principal, plan_id)
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Plan:  # pylint: disable=too-many-instance-attributes
    """One stored plan as the server holds it."""

    principal: str
    plan_id: str
    workflow_id: str
    plan_sha256: str
    plan: dict[str, Any]
    state: PlanState
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None
    run_id: str | None

    def expired(self, now: datetime) -> bool:
        """Return True once the plan is past its expiry and not yet started."""
        return self.state != "started" and now >= self.expires_at


def plan_document(
    workflow_id: str, document: dict[str, Any], digest: str, expires_at: datetime
) -> dict[str, Any]:
    """Canonical facts a plan approval binds to (no model text)."""
    pins = {
        key: {
            "tool": pin.get("tool"),
            "schema_sha256": pin.get("schema_sha256"),
            "access": pin.get("access"),
        }
        for key, pin in sorted((document.get("capabilities") or {}).items())
    }
    inputs = {"kind": "synthetic"}
    return {
        "workflow_id": workflow_id,
        "version": str(document.get("version", "")),
        "title": str(document.get("title", "")),
        "workflow_manifest_sha256": digest,
        "capabilities": pins,
        "stages": [
            {"id": s.get("id"), "title": s.get("title"), "kind": s.get("kind")}
            for s in document.get("stages", [])
        ],
        "inputs": inputs,
        "inputs_sha256": _sha(inputs),
        "expires_at": expires_at.isoformat(),
    }


class PlanStore:
    """``story_plans`` rows in the run-store SQLite file."""

    def __init__(self, path: Path):
        # Created on first use, like RunStore: composing the app writes nothing.
        self.path = path

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(_SCHEMA)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _plan(row: sqlite3.Row) -> Plan:
        return Plan(
            principal=row["principal"],
            plan_id=row["plan_id"],
            workflow_id=row["workflow_id"],
            plan_sha256=row["plan_sha256"],
            plan=json.loads(row["plan_json"]),
            state=row["state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            approved_at=(
                datetime.fromisoformat(row["approved_at"])
                if row["approved_at"]
                else None
            ),
            run_id=row["run_id"],
        )

    def get(self, principal: str, plan_id: str) -> Plan | None:
        """Return one plan of ``principal``, else ``None``."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM story_plans WHERE principal = ? AND plan_id = ?",
                (principal, plan_id),
            ).fetchone()
        return self._plan(row) if row is not None else None

    def preview(
        self, principal: str, workflow_id: str, document: dict[str, Any], digest: str
    ) -> Plan:
        """Store a pending plan; a re-issued preview returns the open one (LOK)."""
        logical_key = _sha([principal, workflow_id, digest, {"kind": "synthetic"}])
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM story_plans WHERE principal = ? AND logical_key = ?"
                " AND state = 'pending' AND expires_at > ?"
                " ORDER BY created_at DESC LIMIT 1",
                (principal, logical_key, now.isoformat()),
            ).fetchone()
            if row is None:
                expires_at = now + PLAN_TTL
                facts = plan_document(workflow_id, document, digest, expires_at)
                connection.execute(
                    "INSERT INTO story_plans (principal, plan_id, logical_key,"
                    " workflow_id, plan_sha256, plan_json, state, created_at,"
                    " expires_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (
                        principal,
                        "plan_" + uuid.uuid4().hex,
                        logical_key,
                        workflow_id,
                        _sha(facts),
                        json.dumps(facts, sort_keys=True),
                        now.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM story_plans WHERE principal = ? AND"
                    " logical_key = ? ORDER BY created_at DESC LIMIT 1",
                    (principal, logical_key),
                ).fetchone()
            connection.execute("COMMIT")
        return self._plan(row)

    def issue_nonce(self, principal: str, plan_id: str) -> str | None:
        """Mint the one-use approval nonce of a pending plan (stored hashed)."""
        nonce = secrets.token_hex(32)
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE story_plans SET nonce_sha256 = ? WHERE principal = ? AND"
                " plan_id = ? AND state = 'pending'",
                (hashlib.sha256(nonce.encode()).hexdigest(), principal, plan_id),
            ).rowcount
        return nonce if updated else None

    def approve(  # pylint: disable=too-many-arguments
        self,
        principal: str,
        plan_id: str,
        *,
        plan_sha256: str,
        nonce: str,
        current_digest: str | None,
    ) -> tuple[ApproveResult, Plan | None]:
        """Compare-and-set ``pending -> approved`` for a human approval."""
        presented = hashlib.sha256(nonce.encode()).hexdigest()
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM story_plans WHERE principal = ? AND plan_id = ?",
                (principal, plan_id),
            ).fetchone()
            result = self._decide(row, presented, plan_sha256, current_digest, now)
            if result == "approved":
                connection.execute(
                    "UPDATE story_plans SET state = 'approved', approved_at = ?"
                    " WHERE principal = ? AND plan_id = ? AND state = 'pending'",
                    (now.isoformat(), principal, plan_id),
                )
            connection.execute("COMMIT")
        return result, self.get(principal, plan_id)

    @staticmethod
    def _decide(
        row: sqlite3.Row | None,
        presented: str,
        plan_sha256: str,
        current_digest: str | None,
        now: datetime,
    ) -> ApproveResult:
        if row is None:
            return "plan_not_found"
        stored = row["nonce_sha256"]
        if stored is None or not secrets.compare_digest(stored, presented):
            return "bad_nonce"
        if row["state"] != "pending":
            return "already_approved"
        plan = json.loads(row["plan_json"])
        if (
            plan_sha256 != row["plan_sha256"]
            or current_digest != plan["workflow_manifest_sha256"]
        ):
            return "plan_superseded"
        if now >= datetime.fromisoformat(row["expires_at"]):
            return "plan_expired"
        return "approved"

    def mark_started(self, principal: str, plan_id: str, run_id: str) -> Plan:
        """Record the plan's one run; a repeat keeps the first run."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE story_plans SET state = 'started', run_id = ? WHERE"
                " principal = ? AND plan_id = ? AND state = 'approved'",
                (run_id, principal, plan_id),
            )
        plan = self.get(principal, plan_id)
        if plan is None:
            raise LookupError("plan_not_found")
        return plan


def plan_run_binding(plan: Plan, origin: str = "interactive") -> RunBinding:
    """Return the run binding of a plan: one plan is one run, whatever the delivery."""
    return RunBinding(
        harness="hermes",
        binding_key="hp-" + plan.plan_id.removeprefix("plan_"),
        origin="cron" if origin == "cron" else "interactive",
    )


class PlanPreview(BaseModel):
    """Request to preview one admitted workflow."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: Annotated[str, Field(min_length=1, max_length=200)]
    inputs: Literal["synthetic"] = "synthetic"
    operation_id: Annotated[str, Field(pattern=OPERATION_ID)] | None = None


class PlanView(BaseModel):
    """A stored plan; the card renders these server facts, never model text."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_sha256: str
    state: PlanState
    workflow_id: str
    plan: dict[str, Any]
    expires_at: datetime
    approved_at: datetime | None
    run_id: str | None
    marker: str


class WorkflowStart(BaseModel):
    """Start the run of one approved plan."""

    model_config = ConfigDict(extra="forbid")

    binding: RunBinding | None = None


class WorkflowStarted(BaseModel):
    """The plan's one run and one job."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_sha256: str
    run_id: str
    job_id: str
    operation_id: str
    job_status: str
    replay_of: str | None = None


def plan_view(plan: Plan) -> PlanView:
    """Public view of a stored plan."""
    return PlanView(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        state=plan.state,
        workflow_id=plan.workflow_id,
        plan=plan.plan,
        expires_at=plan.expires_at,
        approved_at=plan.approved_at,
        run_id=plan.run_id,
        marker=f"[[hfp:plan:{plan.plan_id}]]",
    )


Submit = Callable[..., Any]


def build_router(  # pylint: disable=too-many-arguments
    runs: RunStore,
    plans: PlanStore,
    principal: str,
    workflows: WorkflowCatalog,
    submit: Submit,
) -> APIRouter:
    """Plan routes; ``submit(service, run_id, kind, payload, operation_id)``."""
    router = APIRouter(prefix="/api/v1/story/plans", tags=["story"])

    def _current(workflow_id: str) -> tuple[dict[str, Any], str]:
        document = workflows.get(workflow_id)
        digest = workflows.digest(workflow_id)
        if document is None or digest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "workflow_not_admitted: unknown workflow."
            )
        return document, digest

    @router.post(
        "",
        operation_id="story_plan_preview",
        openapi_extra={"mcp_config": {"name": "story_plan_preview"}},
    )
    def story_plan_preview(request: PlanPreview) -> PlanView:
        """Store a pending plan of one workflow; a human approves it in the card.

        No tool approves a plan. Repeating the preview returns the open plan.
        """
        document, digest = _current(request.workflow_id)
        return plan_view(
            plans.preview(principal, request.workflow_id, document, digest)
        )

    @router.post(
        "/{plan_id}/start",
        operation_id="story_workflow_start",
        status_code=status.HTTP_202_ACCEPTED,
        openapi_extra={"mcp_config": {"name": "story_workflow_start"}},
    )
    def story_workflow_start(
        plan_id: Annotated[str, Field(pattern=PLAN_ID)],
        request: WorkflowStart,
        service: Annotated[JobService, Depends(get_authenticated_job_service)],
    ) -> WorkflowStarted:
        """Start the one run of a human-approved plan; a repeat returns it."""
        plan = plans.get(principal, plan_id)
        if plan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "plan_not_found")
        if plan.state == "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, "plan_not_approved")
        if plan.expired(_now()):
            raise HTTPException(status.HTTP_410_GONE, "plan_expired")
        document, digest = _current(plan.workflow_id)
        current = plan_document(plan.workflow_id, document, digest, plan.expires_at)
        if _sha(current) != plan.plan_sha256:
            raise HTTPException(status.HTTP_409_CONFLICT, "plan_superseded")
        replay_of = plan.run_id
        if plan.run_id is None:
            origin = request.binding.origin if request.binding else "interactive"
            now = _now()
            record = runs.create(
                principal,
                RunRecord(
                    run_id=uuid.uuid4().hex,
                    story_id=f"workflow:{plan.workflow_id}",
                    manifest_version=workflows.version(plan.workflow_id),
                    workflow_manifest_sha256=digest,
                    provider_mode="fixture",
                    state_version=0,
                    stage_status={s["id"]: "pending" for s in document["stages"]},
                    state={},
                    provenance={},
                    created_at=now,
                    updated_at=now,
                    binding=plan_run_binding(plan, origin),
                ),
            )
            plan = plans.mark_started(principal, plan_id, record.run_id)
        if plan.run_id is None:  # another delivery is mid-start
            raise HTTPException(status.HTTP_409_CONFLICT, "plan_not_approved")
        job = submit(
            service,
            plan.run_id,
            WORKFLOW_RUN_KIND,
            {"plan_id": plan.plan_id, "workflow_id": plan.workflow_id},
            "wr-" + plan.plan_id.removeprefix("plan_"),
        )
        return WorkflowStarted(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            run_id=plan.run_id,
            job_id=job.job_id,
            operation_id=job.operation_id,
            job_status=job.status,
            replay_of=replay_of,
        )

    return router


def approve_plan(  # pylint: disable=too-many-arguments
    plans: PlanStore,
    workflows: WorkflowCatalog,
    principal: str,
    plan_id: str,
    *,
    plan_sha256: str,
    nonce: str,
) -> tuple[ApproveResult, Plan | None]:
    """Human approval (sidecar only; deliberately not an MCP route)."""
    plan = plans.get(principal, plan_id)
    digest = workflows.digest(plan.workflow_id) if plan is not None else None
    return plans.approve(
        principal, plan_id, plan_sha256=plan_sha256, nonce=nonce, current_digest=digest
    )
