"""Story catalog, run registry and typed run state (#2216, N06).

Routes under ``/api/v1/story``:

- ``GET /catalog`` and ``GET /describe``: metadata reads over the reviewed
  story manifests. They never run a notebook.
- ``POST /runs``, ``GET /runs/{run_id}`` and
  ``POST /runs/{run_id}/checkpoint``: principal-scoped run state with
  optimistic concurrency. A checkpoint names the state version it read; a
  stale version is a ``409`` and changes nothing.

``POST /runs`` takes an optional Hermes ``binding`` (#1341): one Hermes start
or cron fire is bound to exactly one run, so a repeated create with the same
binding key returns that run instead of starting another.

Run state is JSON only and size-bounded. Nothing here reads arbitrary files or
deserializes notebook pickle state. The principal is bound when the routes are
composed: an MCP server has one effective credential, so every call it serves
belongs to that principal, and another credential cannot see its runs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import BaseModel, ConfigDict, Field

from openbb_mcp_server.utils.schema_digest import canonical_json_sha256

MAX_STATE_BYTES = 64 * 1024
# Same shape as a story job ``operation_id`` (``story_job_kinds.OPERATION_ID``).
BINDING_KEY = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_ID = Annotated[str, Field(min_length=1, max_length=200)]
ProviderMode = Literal["fixture", "recorded", "live"]
StageStatus = Literal[
    "pending", "running", "succeeded", "failed", "unavailable", "approval_required"
]


class StorySummary(BaseModel):
    """Catalog entry for one reviewed story manifest."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    family: str
    variant: str
    notebook_path: str | None = None
    manifest_version: str
    stages: int
    optional_stages: int


class Provenance(BaseModel):
    """Where a checkpoint's state came from."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=100)
    tool_call_ids: list[_ID] = Field(default_factory=list, max_length=100)
    artifact_ids: list[_ID] = Field(default_factory=list, max_length=100)
    source_story: str | None = Field(default=None, max_length=100)


class RunBinding(BaseModel):
    """Which Hermes start or cron fire a run belongs to (#1341).

    ``binding_key`` is a hash derived by the OpenBB Hermes plugin from the
    Hermes session and tool-call IDs (``hs-``) or the cron job, execution and
    workflow (``hc-``); raw Hermes identifiers never reach the server.
    """

    model_config = ConfigDict(extra="forbid")

    harness: Literal["hermes"]
    binding_key: Annotated[str, Field(pattern=BINDING_KEY)]
    origin: Literal["interactive", "cron"]


class RunCreate(BaseModel):
    """Request to start a run of one story."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    provider_mode: ProviderMode = "fixture"
    binding: RunBinding | None = None


class Checkpoint(BaseModel):
    """One stage's result, written only against the version it read."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    stage_id: str
    status: StageStatus
    state: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)


class RunRecord(BaseModel):
    """A run as its principal sees it."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    story_id: str
    manifest_version: str
    workflow_manifest_sha256: str | None = None
    provider_mode: ProviderMode
    state_version: int
    stage_status: dict[str, StageStatus]
    state: dict[str, dict[str, Any]]
    provenance: dict[str, Provenance]
    created_at: datetime
    updated_at: datetime
    binding: RunBinding | None = None


class StaleCheckpoint(Exception):
    """The checkpoint was computed from an older state version."""


class BindingConflict(Exception):
    """A binding key already names a run of another story or provider mode."""


class StoryCatalog:
    """Read-only view over the reviewed story manifests."""

    def __init__(self, manifest_dir: Path | None):
        """Load every ``*__*.json`` manifest under ``manifest_dir``, if present."""
        self._manifests: dict[str, dict[str, Any]] = {}
        self.available = False
        if manifest_dir is None or not manifest_dir.is_dir():
            return
        self.available = True
        for path in sorted(manifest_dir.glob("*__*.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self._manifests[manifest["story_id"]] = manifest

    @staticmethod
    def version(manifest: dict[str, Any]) -> str:
        """Immutable manifest version: story ID plus source fingerprint."""
        return f"{manifest['story_id']}@{manifest['source_sha256'][:12]}"

    def summaries(self) -> list[StorySummary]:
        """Every story, in story order."""
        return [
            StorySummary(
                story_id=m["story_id"],
                family=m["family"],
                variant=m["variant"],
                notebook_path=m["notebook_path"],
                manifest_version=self.version(m),
                stages=len(m["stages"]),
                optional_stages=sum(bool(s["optional"]) for s in m["stages"]),
            )
            for _, m in sorted(self._manifests.items())
        ]

    def get(self, story_id: str) -> dict[str, Any] | None:
        """Return a copy of one manifest, or ``None``."""
        manifest = self._manifests.get(story_id)
        return copy.deepcopy(manifest) if manifest is not None else None


WORKFLOW_PREFIX = "workflow:"
_WORKFLOW_FILE = "*.workflow.json"
# Keys that carry notebook identity. A workflow naming any of them (at any
# depth), or any string that points at a notebook file, is refused.
_NOTEBOOK_KEYS = frozenset(
    {
        "cells",
        "cell",
        "notebook",
        "notebook_path",
        "notebooks",
        "source_sha256",
        "kernel",
        "kernel_name",
        "kernelspec",
    }
)
_NOTEBOOK_FILE = re.compile(r"\.ipynb\s*$", re.IGNORECASE)


_MAX_DEPTH = 64
_MAX_NODES = 200_000
_WORKFLOW_ID = re.compile(r"^[a-z0-9][a-z0-9_.:/-]*$")


def _notebook_identity(document: Any) -> str | None:
    """Return the first notebook key or notebook-file string in ``document``.

    Iterative and bounded in depth and node count, so a hostile document
    cannot exhaust the stack; exceeding a bound is itself a refusal.
    """
    stack: list[tuple[Any, int]] = [(document, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if depth > _MAX_DEPTH or visited > _MAX_NODES:
            return "document too deep or too large to scan"
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in _NOTEBOOK_KEYS:
                    return f"key '{key}'"
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
        elif isinstance(node, str) and _NOTEBOOK_FILE.search(node):
            return "notebook file reference"
    return None


def _structural_problem(document: Any) -> str | None:
    """Minimal shape check for what the registry itself reads from a workflow.

    The full contract lives in ``openbb_agents.hermes_integration.workflow``;
    ``openbb_mcp_server`` must not import it, so this checks only the fields
    the catalog and run routes use, strictly (no bool-for-int coercion).
    """
    if not isinstance(document, dict):
        return "document is not an object"
    schema_version = document.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        # ``True == 1`` and ``1.0 == 1``: only the int 1 is accepted.
        return "unsupported schema_version"
    workflow_id = document.get("workflow_id")
    if not isinstance(workflow_id, str) or not _WORKFLOW_ID.match(workflow_id):
        return "missing or invalid workflow_id"
    if not isinstance(document.get("version"), str):
        return "missing version"
    if not isinstance(document.get("capabilities"), dict):
        return "capabilities is not an object"
    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        return "stages is not a non-empty list"
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
            return "stage is not an object with an id"
        if not isinstance(stage.get("optional", False), bool):
            return "stage optional is not a boolean"
    return None


class WorkflowCatalog:
    """Read-only view over reviewed, notebook-free workflow documents.

    Identity is the SHA-256 of the document itself. IDs are namespaced
    ``workflow:<id>`` so ``RunCreate.story_id`` keeps its input schema.
    """

    def __init__(self, workflow_dir: Path | None):
        """Load every ``*.workflow.json`` under ``workflow_dir``, if present."""
        self._documents: dict[str, dict[str, Any]] = {}
        self._digests: dict[str, str] = {}
        self.refused: dict[str, str] = {}
        self.available = False
        if workflow_dir is None or not workflow_dir.is_dir():
            return
        self.available = True
        owners: dict[str, list[str]] = {}
        for path in sorted(workflow_dir.glob(_WORKFLOW_FILE)):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError):
                self.refused[path.name] = "unreadable or invalid JSON"
                continue
            problem = _notebook_identity(document)
            if problem:
                self.refused[path.name] = f"notebook identity: {problem}"
                continue
            problem = _structural_problem(document)
            if problem:
                self.refused[path.name] = problem
                continue
            workflow_id = document["workflow_id"]
            owners.setdefault(workflow_id, []).append(path.name)
            self._documents[workflow_id] = document
            self._digests[workflow_id] = canonical_json_sha256(document)
        for workflow_id, names in owners.items():
            if len(names) > 1:
                # Ambiguous identity: serve neither copy.
                del self._documents[workflow_id]
                del self._digests[workflow_id]
                for name in names:
                    self.refused[name] = f"duplicate workflow_id '{workflow_id}'"

    @staticmethod
    def parse_id(story_id: str) -> str | None:
        """Return the workflow ID of a namespaced ID, else ``None``."""
        if story_id.startswith(WORKFLOW_PREFIX):
            return story_id[len(WORKFLOW_PREFIX) :]
        return None

    def digest(self, workflow_id: str) -> str | None:
        """Full SHA-256 of one workflow document, or ``None``."""
        return self._digests.get(workflow_id)

    def version(self, workflow_id: str) -> str:
        """Immutable run version: namespaced ID plus 12 hex of the digest."""
        return f"{WORKFLOW_PREFIX}{workflow_id}@{self._digests[workflow_id][:12]}"

    def summaries(self) -> list[StorySummary]:
        """Every workflow, in ID order."""
        return [
            StorySummary(
                story_id=f"{WORKFLOW_PREFIX}{workflow_id}",
                family="workflow",
                variant=str(document.get("version", "")),
                notebook_path=None,
                manifest_version=self.version(workflow_id),
                stages=len(document["stages"]),
                optional_stages=sum(
                    bool(stage.get("optional")) for stage in document["stages"]
                ),
            )
            for workflow_id, document in sorted(self._documents.items())
        ]

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        """Return a copy of one workflow document, or ``None``."""
        document = self._documents.get(workflow_id)
        return copy.deepcopy(document) if document is not None else None


def ensure_workflow_current(record: RunRecord, workflows: WorkflowCatalog) -> None:
    """Raise ``409 workflow_changed`` if a workflow run's document changed.

    Legacy story runs (no ``workflow_manifest_sha256``) are never affected.
    Shared by the registry, paper, jobs and artifacts routes.
    """
    if record.workflow_manifest_sha256 is None:
        return
    current = workflows.digest(workflows.parse_id(record.story_id) or "")
    if current != record.workflow_manifest_sha256:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "workflow_changed: the workflow changed since this run started "
            f"({record.manifest_version}); start a new run.",
        )


class RunStore:
    """SQLite run store with optimistic concurrency per run."""

    def __init__(self, path: Path):
        """Bind the store to ``path``; the database is created on first use."""
        # Nothing touches disk until the first run is created or read, so
        # composing the routes into a server has no filesystem side effect.
        self.path = path
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None)
        if not self._ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS story_runs ("
                " run_id TEXT PRIMARY KEY, principal TEXT NOT NULL,"
                " version INTEGER NOT NULL, record TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS story_run_bindings ("
                " principal TEXT NOT NULL, binding_key TEXT NOT NULL,"
                " run_id TEXT NOT NULL, created_at TEXT NOT NULL,"
                " PRIMARY KEY (principal, binding_key))"
            )
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    def create(self, principal: str, record: RunRecord) -> RunRecord:
        """Persist a new run for ``principal``.

        A bound run (``record.binding``) is created at most once per binding
        key: the binding and the run are written in one transaction, and a
        repeat returns the run already bound. A binding key that names a run
        of another story or provider mode raises ``BindingConflict``.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = (
                    self._bound_run(connection, principal, record)
                    if record.binding is not None
                    else None
                )
                if existing is None:
                    connection.execute(
                        "INSERT INTO story_runs (run_id, principal, version, record)"
                        " VALUES (?, ?, ?, ?)",
                        (record.run_id, principal, 0, record.model_dump_json()),
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        if existing is None:
            return record
        if (
            existing.story_id != record.story_id
            or existing.provider_mode != record.provider_mode
        ):
            raise BindingConflict(
                "binding_conflict: this binding key already names a run of"
                f" {existing.story_id} ({existing.provider_mode})."
            )
        return existing

    @staticmethod
    def _bound_run(
        connection: sqlite3.Connection, principal: str, record: RunRecord
    ) -> RunRecord | None:
        """Return the run this binding already names, else bind ``record``."""
        assert record.binding is not None  # noqa: S101  # caller checked
        row = connection.execute(
            "SELECT r.record FROM story_run_bindings b"
            " JOIN story_runs r ON r.run_id = b.run_id AND r.principal = b.principal"
            " WHERE b.principal = ? AND b.binding_key = ?",
            (principal, record.binding.binding_key),
        ).fetchone()
        if row is not None:
            return RunRecord.model_validate_json(row[0])
        connection.execute(
            "INSERT INTO story_run_bindings (principal, binding_key, run_id,"
            " created_at) VALUES (?, ?, ?, ?)",
            (
                principal,
                record.binding.binding_key,
                record.run_id,
                record.created_at.isoformat(),
            ),
        )
        return None

    def get(self, principal: str, run_id: str) -> RunRecord | None:
        """Return the run only if ``principal`` owns it."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record FROM story_runs WHERE run_id = ? AND principal = ?",
                (run_id, principal),
            ).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    def checkpoint(
        self, principal: str, run_id: str, expected_version: int, updated: RunRecord
    ) -> RunRecord:
        """Write ``updated`` only if the stored version is ``expected_version``."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE story_runs SET version = ?, record = ?"
                    " WHERE run_id = ? AND principal = ? AND version = ?",
                    (
                        expected_version + 1,
                        updated.model_dump_json(),
                        run_id,
                        principal,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StaleCheckpoint(run_id)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return updated


def default_workflow_dir() -> Path | None:
    """Locate the reviewed workflows shipped with the agents package.

    Uses the top-level package spec only; nothing from the package is imported.
    """
    spec = importlib.util.find_spec("openbb_agents")
    if spec is None or not spec.submodule_search_locations:
        return None
    return (
        Path(next(iter(spec.submodule_search_locations)))
        / "hermes_integration"
        / "workflows"
    )


def default_manifest_dir() -> Path | None:
    """Locate the reviewed manifests shipped with the agents package."""
    spec = importlib.util.find_spec("openbb_agents")
    if spec is None or not spec.submodule_search_locations:
        return None
    return (
        Path(next(iter(spec.submodule_search_locations))) / "notebook_guide" / "stories"
    )


STORE_ENV = "OPENBB_STORY_RUN_STORE"


def default_store_path() -> Path:
    """Run store location: ``$OPENBB_STORY_RUN_STORE`` or the user directory."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    return Path.home() / ".openbb_platform" / "story_runs.sqlite"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_router(
    catalog: StoryCatalog,
    workflows: WorkflowCatalog,
    store: RunStore,
    principal: str,
) -> APIRouter:
    """Return the story routes bound to one principal."""
    router = APIRouter(prefix="/api/v1/story", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    def _available() -> None:
        if not catalog.available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Story manifests are not installed (openbb-agents).",
            )

    def _workflow(workflow_id: str) -> dict[str, Any]:
        document = workflows.get(workflow_id)
        if document is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Unknown workflow '{workflow_id}'."
            )
        return document

    def _manifest(story_id: str) -> dict[str, Any]:
        workflow_id = workflows.parse_id(story_id)
        if workflow_id is not None:
            return _workflow(workflow_id)
        _available()
        manifest = catalog.get(story_id)
        if manifest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Unknown story '{story_id}'."
            )
        return manifest

    @router.get(
        "/catalog",
        operation_id="story_catalog",
        openapi_extra={"mcp_config": {"name": "story_catalog"}},
    )
    def story_catalog() -> list[StorySummary]:
        """List every reviewed story and workflow without running it."""
        if not workflows.available:
            _available()
        return [*catalog.summaries(), *workflows.summaries()]

    @router.get(
        "/describe",
        operation_id="story_describe",
        openapi_extra={"mcp_config": {"name": "story_describe"}},
    )
    def story_describe(
        story_id: Annotated[str, Query(description="Story ID, e.g. portfolio/03")],
    ) -> dict[str, Any]:
        """Return one story's reviewed manifest: stages, cells and capabilities."""
        return _manifest(story_id)

    @router.post(
        "/runs",
        operation_id="story_run_create",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_create"}},
    )
    def story_run_create(request: RunCreate) -> RunRecord:
        """Start a run of one story; state begins empty at version 0.

        With a Hermes ``binding``, a repeat returns the run already bound.
        """
        manifest = _manifest(request.story_id)
        workflow_id = workflows.parse_id(request.story_id)
        now = _now()
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            story_id=request.story_id,
            manifest_version=(
                workflows.version(workflow_id)
                if workflow_id is not None
                else catalog.version(manifest)
            ),
            workflow_manifest_sha256=(
                workflows.digest(workflow_id) if workflow_id is not None else None
            ),
            provider_mode=request.provider_mode,
            state_version=0,
            stage_status={stage["id"]: "pending" for stage in manifest["stages"]},
            state={},
            provenance={},
            created_at=now,
            updated_at=now,
            binding=request.binding,
        )
        try:
            return store.create(principal, record)
        except BindingConflict as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    def _owned_run(run_id: str) -> RunRecord:
        record = store.get(principal, run_id)
        if record is None:
            # Another principal's run is indistinguishable from no run.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        return record

    @router.get(
        "/runs/{run_id}",
        operation_id="story_run_get",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_get"}},
    )
    def story_run_get(run_id: str) -> RunRecord:
        """Return a run owned by this principal."""
        return _owned_run(run_id)

    @router.post(
        "/runs/{run_id}/checkpoint",
        operation_id="story_run_checkpoint",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_run_checkpoint"}},
    )
    def story_run_checkpoint(run_id: str, checkpoint: Checkpoint) -> RunRecord:
        """Record one stage's status and JSON state against the version read."""
        record = _owned_run(run_id)
        ensure_workflow_current(record, workflows)
        if checkpoint.stage_id not in record.stage_status:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stage '{checkpoint.stage_id}' is not in {record.manifest_version}.",
            )
        written = {
            "state": checkpoint.state,
            "provenance": checkpoint.provenance.model_dump(mode="json"),
        }
        if len(json.dumps(written).encode("utf-8")) > MAX_STATE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Stage state and provenance exceed {MAX_STATE_BYTES} bytes.",
            )
        if checkpoint.expected_version != record.state_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Run is at version {record.state_version}; reload before writing.",
            )
        updated = record.model_copy(
            update={
                "state_version": record.state_version + 1,
                "stage_status": {
                    **record.stage_status,
                    checkpoint.stage_id: checkpoint.status,
                },
                "state": {**record.state, checkpoint.stage_id: checkpoint.state},
                "provenance": {
                    **record.provenance,
                    checkpoint.stage_id: checkpoint.provenance,
                },
                "updated_at": _now(),
            }
        )
        try:
            return store.checkpoint(
                principal, run_id, checkpoint.expected_version, updated
            )
        except StaleCheckpoint as error:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Run changed concurrently; reload before writing.",
            ) from error

    return router


def compose_story_registry_app(
    source_app: FastAPI,
    *,
    principal: str,
    manifest_dir: Path | None = None,
    workflow_dir: Path | None = None,
    store_path: Path | None = None,
) -> FastAPI:
    """Add the story routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("The story registry requires an authenticated principal")
    catalog = StoryCatalog(
        manifest_dir if manifest_dir is not None else default_manifest_dir()
    )
    workflows = WorkflowCatalog(
        workflow_dir if workflow_dir is not None else default_workflow_dir()
    )
    store = RunStore(store_path if store_path is not None else default_store_path())
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router(catalog, workflows, store, principal))
    composed.openapi_schema = None
    return composed
