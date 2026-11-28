"""Synthetic web journey of the HFP vertical slice (#1342 T02).

``synthetic_stack`` builds the real stores over a temp dir: the story plan and job
routes, one durable job service, an in-process ``JobWorker`` and the sidecar
:class:`~.backend.StoryBackend`, all over the same run store and job store. The
three analytics provider seams raise and are counted, and the egress guard refuses
non-loopback and live ports, so a run makes zero provider calls.

``run_journey`` drives preview -> approve (through the real loopback sidecar, twice)
-> start (twice) -> worker -> outcome card and reports SQLite row counts.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import secrets
import sqlite3
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.worker import JobWorker
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import analytics
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app
from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

from ..egress_guard import egress_guard
from .backend import StoryBackend
from .security import TOKEN_HEADER
from .sidecar import LoopbackSidecar

PRINCIPAL = "hermes#00000000000000a5"
WORKFLOW_ID = "synthetic.basket_xray"
_SEAMS = ("_nport_rows", "_search_ticker", "_profile_sector")


@dataclass
class SyntheticStack:  # pylint: disable=too-many-instance-attributes
    """One temp journey stack; every part shares ``store`` and ``jobs_db``."""

    root: Path
    store: Path
    jobs_db: Path
    story: TestClient
    backend: StoryBackend
    worker: JobWorker
    provider_calls: list[str] = field(default_factory=list)
    egress: list[str] = field(default_factory=list)

    def rows(self, db: Path, sql: str, *args: Any) -> list[tuple]:
        """Rows of ``sql``; a table that was never created has none."""
        with contextlib.closing(sqlite3.connect(db)) as connection:
            try:
                return connection.execute(sql, args).fetchall()
            except sqlite3.OperationalError:
                return []


@contextlib.contextmanager
def _env(values: dict[str, str]) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _refuse_seams(calls: list[str]) -> Iterator[None]:
    saved = {name: getattr(analytics, name) for name in _SEAMS}

    def refuse(name: str):
        def seam(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise RuntimeError(f"provider seam {name} refused in the synthetic journey")

        return seam

    for name in _SEAMS:
        setattr(analytics, name, refuse(name))
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(analytics, name, value)


@contextlib.contextmanager
def synthetic_stack(root: Path, principal: str = PRINCIPAL) -> Iterator[SyntheticStack]:
    """Real stores under ``root``; the process env points the worker at them."""
    store, artifacts, jobs_db = (
        root / "runs.sqlite",
        root / "artifacts",
        root / "jobs.db",
    )
    calls: list[str] = []
    env = {
        "OPENBB_STORY_RUN_STORE": str(store),
        "OPENBB_STORY_ARTIFACT_ROOT": str(artifacts),
    }
    with _env(env), _refuse_seams(calls), egress_guard(
        refuse_live_ports=True
    ) as egress:
        job_store = SqliteJobStore(jobs_db)
        service = JobService(
            store=job_store, registry=JobRegistry(get_job_definitions())
        )
        app = compose_story_registry_app(
            FastAPI(), principal=principal, store_path=store
        )
        app = compose_story_jobs_app(
            app, principal=principal, store_path=store, artifact_root=artifacts
        )
        app.dependency_overrides[get_job_service] = lambda: service
        stack = SyntheticStack(
            root=root,
            store=store,
            jobs_db=jobs_db,
            story=TestClient(app),
            backend=StoryBackend(
                principal=principal,
                store_path=store,
                artifact_root=artifacts,
                service=service,
            ),
            worker=JobWorker(service=service, worker_id="hfp-journey-worker"),
            provider_calls=calls,
            egress=egress,
        )
        try:
            yield stack
        finally:
            job_store.close()


def _call(port: int, token: str, method: str, path: str, body: Any = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Host": f"127.0.0.1:{port}", TOKEN_HEADER: token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        conn.close()


def run_journey() -> dict[str, Any]:  # pylint: disable=too-many-locals
    """Preview, approve twice, start twice, run the worker, read the outcome card."""
    with tempfile.TemporaryDirectory(
        prefix="hfp-journey-", ignore_cleanup_errors=True
    ) as tmp:
        root = Path(tmp)
        token = secrets.token_urlsafe(32)
        token_file = root / "state" / "sidecar-auth" / "openbb-hfp.token"
        token_file.parent.mkdir(parents=True)
        token_file.write_text(token, encoding="utf-8")
        with synthetic_stack(root) as stack, LoopbackSidecar(
            principal=PRINCIPAL, token_file=token_file, backend=stack.backend
        ) as side:
            preview = stack.story.post(
                "/api/v1/story/plans", json={"workflow_id": WORKFLOW_ID}
            ).json()
            plan_id = preview["plan_id"]
            _, card = _call(side.port, token, "GET", f"/plans/{plan_id}")
            body = {
                "plan_sha256": card["plan_sha256"],
                "approval_nonce": card["approval_nonce"],
            }
            approvals = [
                _call(side.port, token, "POST", f"/plans/{plan_id}/approve", body)
                for _ in range(2)
            ]
            starts = [
                stack.story.post(f"/api/v1/story/plans/{plan_id}/start", json={})
                for _ in range(2)
            ]
            run_id = starts[0].json()["run_id"]
            ran = stack.worker.run_once()
            status, run_card = _call(side.port, token, "GET", f"/runs/{run_id}")
            plan_rows = stack.rows(
                stack.store,
                "SELECT state, run_id FROM story_plans WHERE plan_id = ?",
                plan_id,
            )
            runs = stack.rows(
                stack.store, "SELECT run_id FROM story_runs WHERE run_id = ?", run_id
            )
            jobs = stack.rows(stack.jobs_db, "SELECT run_id, status FROM job_run")
            arts = stack.rows(
                stack.store,
                "SELECT record FROM story_artifacts WHERE run_id = ?",
                run_id,
            )
            calls, egress = list(stack.provider_calls), list(stack.egress)
    stored = sorted(
        (json.loads(r[0])["ref"]["artifact_id"], json.loads(r[0])["ref"]["sha256"])
        for r in arts
    )
    shown = sorted(
        (a["artifact_id"], a["sha256"]) for a in run_card.get("artifacts", [])
    )
    report = {
        "scenario": "journey",
        "plan": f"{card['state']}->{plan_rows[0][0] if plan_rows else 'missing'}",
        "approve_results": [
            f"{code}:{data.get('result') or data.get('error')}"
            for code, data in approvals
        ],
        "start_statuses": [r.status_code for r in starts],
        "start_replay_of": starts[1].json().get("replay_of"),
        "worker_ran": bool(ran),
        "plan_rows_approved": sum(
            1 for s, _ in plan_rows if s in ("approved", "started")
        ),
        "runs": len(runs),
        "jobs": len(jobs),
        "job_status": [s for _, s in jobs],
        "run_card_status": status,
        "outcome": run_card.get("outcome"),
        "artifacts": len(shown),
        "artifacts_sha_ok": bool(shown) and shown == stored,
        "duplicates": {
            "approve": f"{len(approvals)}->{len(plan_rows)}",
            "start": f"{len(starts)}->{len(runs)}",
        },
        "provider_calls": len(calls),
        "egress_refused": len(egress),
    }
    report["ok"] = (
        report["plan"] == "pending->started"
        and report["approve_results"] == ["200:approved", "200:already_approved"]
        and report["start_statuses"] == [202, 202]
        and report["start_replay_of"] == run_id
        and report["runs"] == 1
        and report["jobs"] == 1
        and report["outcome"] == "succeeded"
        and report["artifacts_sha_ok"]
        and report["provider_calls"] == 0
        and report["egress_refused"] == 0
    )
    return report
