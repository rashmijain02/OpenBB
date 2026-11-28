"""Plan preview, human approval and start (#1342 T02)."""

from __future__ import annotations

import csv
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import plans
from openbb_mcp_server.story_adapters.jobs import JobSubmit, compose_story_jobs_app
from openbb_mcp_server.story_adapters.registry import (
    WorkflowCatalog,
    compose_story_registry_app,
)
from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

REPO_ROOT = Path(__file__).resolve().parents[5]
AGENTS = REPO_ROOT / "openbb_platform" / "extensions" / "agents" / "openbb_agents"
SHIPPED = AGENTS / "hermes_integration" / "workflows"
FILE = "synthetic.concentration_review.workflow.json"
WID = "synthetic.concentration_review"
POLICY = (
    REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "mcp_server"
    / "openbb_mcp_server"
    / "assets"
    / "capability_policy_operations.csv"
)


@pytest.fixture
def env(tmp_path):
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    shutil.copy(SHIPPED / FILE, workflows / FILE)
    store = tmp_path / "runs.sqlite"
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
    )
    common = {"principal": "alice", "store_path": store, "workflow_dir": workflows}
    app = compose_story_registry_app(FastAPI(), **common)
    app = compose_story_jobs_app(app, artifact_root=tmp_path / "art", **common)
    app.dependency_overrides[get_job_service] = lambda: service
    client = TestClient(app)
    return {
        "client": client,
        "store": store,
        "plans": plans.PlanStore(store),
        "catalog": WorkflowCatalog(workflows),
        "workflows": workflows,
        "service": service,
    }


def _preview(env):
    response = env["client"].post("/api/v1/story/plans", json={"workflow_id": WID})
    assert response.status_code == 200, response.text
    return response.json()


def _approve(env, plan, nonce=None, sha=None):
    nonce = nonce or env["plans"].issue_nonce("alice", plan["plan_id"])
    result, _ = plans.approve_plan(
        env["plans"],
        env["catalog"],
        "alice",
        plan["plan_id"],
        plan_sha256=sha or plan["plan_sha256"],
        nonce=nonce,
    )
    return result, nonce


def _start(env, plan_id):
    return env["client"].post(f"/api/v1/story/plans/{plan_id}/start", json={})


def _count(env, sql):
    with sqlite3.connect(env["store"]) as connection:
        try:
            return connection.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:  # table not created yet: no rows
            return 0


def test_preview_stores_pending_plan_with_sha(env):
    plan = _preview(env)
    assert plan["state"] == "pending"
    assert plan["marker"] == f"[[hfp:plan:{plan['plan_id']}]]"
    stored = env["plans"].get("alice", plan["plan_id"])
    assert stored.plan_sha256 == plans._sha(stored.plan) == plan["plan_sha256"]
    digest = env["catalog"].digest(WID)
    assert stored.plan["workflow_manifest_sha256"] == digest


def test_reissued_preview_same_lok_returns_same_plan(env):
    assert _preview(env)["plan_id"] == _preview(env)["plan_id"]
    assert _count(env, "SELECT COUNT(*) FROM story_plans") == 1


def test_approve_same_nonce_twice_already_approved(env):
    plan = _preview(env)
    first, nonce = _approve(env, plan)
    second, _ = _approve(env, plan, nonce=nonce)
    assert (first, second) == ("approved", "already_approved")
    assert env["plans"].get("alice", plan["plan_id"]).state == "approved"


def test_bad_nonce_403(env):
    plan = _preview(env)
    env["plans"].issue_nonce("alice", plan["plan_id"])
    result, _ = _approve(env, plan, nonce="0" * 64)
    assert (result, plans.APPROVE_STATUS[result]) == ("bad_nonce", 403)
    assert env["plans"].get("alice", plan["plan_id"]).state == "pending"


def test_approve_stale_sha_409_superseded(env):
    plan = _preview(env)
    result, _ = _approve(env, plan, sha="f" * 64)
    assert (result, plans.APPROVE_STATUS[result]) == ("plan_superseded", 409)


def test_expired_plan_410(env):
    plan = _preview(env)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(env["store"]) as connection:
        connection.execute("UPDATE story_plans SET expires_at = ?", (past,))
    result, _ = _approve(env, plan)
    assert (result, plans.APPROVE_STATUS[result]) == ("plan_expired", 410)


def test_start_requires_approved(env):
    plan = _preview(env)
    response = _start(env, plan["plan_id"])
    assert response.status_code == 409 and "plan_not_approved" in response.text
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 0


def test_start_twice_same_run_and_job_replay_of(env):
    plan = _preview(env)
    _approve(env, plan)
    first = _start(env, plan["plan_id"])
    second = _start(env, plan["plan_id"])
    assert first.status_code == second.status_code == 202, first.text
    a, b = first.json(), second.json()
    assert (a["run_id"], a["job_id"]) == (b["run_id"], b["job_id"])
    assert a["replay_of"] is None and b["replay_of"] == a["run_id"]
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 1
    assert _count(env, "SELECT COUNT(*) FROM story_jobs") == 1


def test_concurrent_starts_one_run(env):
    plan = _preview(env)
    _approve(env, plan)
    replies = []
    threads = [
        threading.Thread(target=lambda: replies.append(_start(env, plan["plan_id"])))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert {r.json()["run_id"] for r in replies} and len(
        {r.json()["run_id"] for r in replies}
    ) == 1
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 1


def test_start_after_manifest_drift_blocked(env):
    plan = _preview(env)
    _approve(env, plan)
    # The plan was hashed under an older manifest: its stored facts differ
    # from what the current workflow recomputes.
    old = env["plans"].get("alice", plan["plan_id"]).plan
    old["workflow_manifest_sha256"] = "0" * 64
    with sqlite3.connect(env["store"]) as connection:
        connection.execute("UPDATE story_plans SET plan_sha256 = ?", (plans._sha(old),))
    response = _start(env, plan["plan_id"])
    assert response.status_code == 409 and "plan_superseded" in response.text
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 0


def test_story_job_submit_schema_unchanged():
    kinds = JobSubmit.model_json_schema()["properties"]["kind"]["enum"]
    assert "story.workflow_run" not in kinds


def test_no_mcp_tool_can_approve():
    with POLICY.open(encoding="utf-8", newline="") as handle:
        tools = {row["mcp_tool"] for row in csv.DictReader(handle)}
    assert {"story_plan_preview", "story_workflow_start"} <= tools
    assert not [t for t in tools if t and "approv" in t and t.startswith("story_")]


def test_start_returns_the_run_marker(env):
    """The start reply carries ``[[hfp:run:<id>]]`` like the plan view's marker."""
    plan = _preview(env)
    assert plan["marker"] == f"[[hfp:plan:{plan['plan_id']}]]"
    _approve(env, plan)
    started = _start(env, plan["plan_id"]).json()
    assert started["marker"] == f"[[hfp:run:{started['run_id']}]]"


def test_started_plan_replays_before_manifest_recheck(env):
    """A repeat start of a started plan returns its ids even after drift (F6)."""
    plan = _preview(env)
    _approve(env, plan)
    first = _start(env, plan["plan_id"]).json()
    # The workflow changed after the start: a fresh start would be superseded.
    old = env["plans"].get("alice", plan["plan_id"]).plan
    old["workflow_manifest_sha256"] = "0" * 64
    with sqlite3.connect(env["store"]) as connection:
        connection.execute("UPDATE story_plans SET plan_sha256 = ?", (plans._sha(old),))
    again = _start(env, plan["plan_id"])
    assert again.status_code == 202, again.text
    body = again.json()
    assert (body["run_id"], body["job_id"]) == (first["run_id"], first["job_id"])
    assert body["replay_of"] == first["run_id"]
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 1
    assert _count(env, "SELECT COUNT(*) FROM story_jobs") == 1


def test_interleaved_starts_create_exactly_one_run_record(env, monkeypatch):
    """H1: both starts read the approved plan before either creates its run."""
    plan = _preview(env)
    _approve(env, plan)
    barrier = threading.Barrier(2, timeout=20)
    gate = {"left": 2}
    lock = threading.Lock()
    real_get = plans.PlanStore.get

    def get(self, principal, plan_id):
        found = real_get(self, principal, plan_id)
        with lock:
            wait = gate["left"] > 0
            gate["left"] -= 1
        if wait:
            barrier.wait()  # both deliveries saw run_id None
        return found

    monkeypatch.setattr(plans.PlanStore, "get", get)
    replies = []
    threads = [
        threading.Thread(target=lambda: replies.append(_start(env, plan["plan_id"])))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [r.status_code for r in replies] == [202, 202], [r.text for r in replies]
    bodies = [r.json() for r in replies]
    run_id = bodies[0]["run_id"]
    assert {b["run_id"] for b in bodies} == {run_id}
    assert sorted(str(b["replay_of"]) for b in bodies) == sorted(["None", run_id])
    assert _count(env, "SELECT COUNT(*) FROM story_runs") == 1
    assert _count(env, "SELECT COUNT(*) FROM story_run_bindings") == 1
    assert _count(env, "SELECT COUNT(*) FROM story_jobs") == 1
