"""Cancel semantics without promised interruption (#1341, T02).

``cancel_state`` is additive on the job cancel reply; ``outcome`` keeps its
literals. ``story_run_cancel`` cancels queued work, never interrupts claimed
work, withdraws pending paper requests and closes the run to new mutations.
Synthetic data, a temporary run store and a temporary job store only.
"""

# pylint: disable=redefined-outer-name,too-many-locals

import shutil
import sqlite3
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.models import JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import paper, paper_approve
from openbb_mcp_server.story_adapters.artifacts import compose_story_artifacts_app
from openbb_mcp_server.story_adapters.jobs import CancelOutcome, compose_story_jobs_app
from openbb_mcp_server.story_adapters.paper import compose_story_paper_app
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app
from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

REPO_ROOT = Path(__file__).resolve().parents[5]
AGENTS = REPO_ROOT / "openbb_platform" / "extensions" / "agents" / "openbb_agents"
MANIFESTS = AGENTS / "notebook_guide" / "stories"
SHIPPED = AGENTS / "hermes_integration" / "workflows"
FILE = "synthetic.concentration_review.workflow.json"
WORKFLOW = "workflow:synthetic.concentration_review"
KEY = "k" * 48
BINDING = {
    "harness": "hermes",
    "binding_key": "hs-" + "a" * 32,
    "origin": "interactive",
}
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
    "plan_id": "plan-1",
    "tickets": [{"symbol": "MSFT", "action": "Buy", "quantity": "10"}],
    "verdict_gate_pass": True,
    "verdict_gates": [
        {"name": "PBO", "threshold": "< 0.5", "actual": "0.21", "passed": True}
    ],
}
TABLE = {
    "name": "positions",
    "format": "csv",
    "table": {"columns": ["symbol", "weight"], "rows": [["AAA", 0.5]]},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Registry, artifacts, jobs and paper over one store and one job service."""
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, KEY)
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    shutil.copy(SHIPPED / FILE, workflows / FILE)
    store = tmp_path / "runs.sqlite"
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
    )
    common = {"principal": "alice", "store_path": store}
    app = compose_story_registry_app(
        FastAPI(), manifest_dir=MANIFESTS, workflow_dir=workflows, **common
    )
    app = compose_story_artifacts_app(
        app, artifact_root=tmp_path / "artifacts", workflow_dir=workflows, **common
    )
    app = compose_story_jobs_app(app, workflow_dir=workflows, **common)
    app = compose_story_paper_app(
        app, paper_root=tmp_path / "paper", workflow_dir=workflows, **common
    )
    app.dependency_overrides[get_job_service] = lambda: service
    client = TestClient(app)

    def new_run(binding=None):
        body = {"story_id": WORKFLOW}
        if binding is not None:
            body["binding"] = binding
        response = client.post("/api/v1/story/runs", json=body)
        assert response.status_code == 200, response.text
        return response.json()["run_id"]

    def submit(run_id, operation_id, payload=None):
        response = client.post(
            f"/api/v1/story/runs/{run_id}/jobs",
            json={
                "operation_id": operation_id,
                "kind": "story.backtest",
                "payload": payload or BACKTEST,
            },
        )
        assert response.status_code == 202, response.text
        return response.json()

    def finish_next():
        """Claim the next queued job and complete it, as a worker would."""
        claimed = service.claim_next("test-worker")
        assert claimed is not None
        return claimed

    def complete(job):
        service.complete(job.run_id, JobResult(summary={"ok": True}))

    def cancel_run(run_id):
        return client.post(f"/api/v1/story/runs/{run_id}/cancel")

    def sandbox_and_request(run_id, operation_id="prep-1"):
        sandbox = client.post(
            f"/api/v1/story/runs/{run_id}/paper/sandboxes",
            json={"engine": "techtrade", "starting_cash": "100000"},
        )
        assert sandbox.status_code == 200, sandbox.text
        sandbox_id = sandbox.json()["sandbox_id"]
        prepared = client.post(
            f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
            json={
                "operation_id": operation_id,
                "action": "submit_batch",
                "arguments": BATCH,
            },
        )
        assert prepared.status_code == 200, prepared.text
        return sandbox_id, prepared.json()["request_id"]

    return SimpleNamespace(
        client=client,
        service=service,
        store=store,
        new_run=new_run,
        submit=submit,
        claim=finish_next,
        complete=complete,
        cancel_run=cancel_run,
        sandbox_and_request=sandbox_and_request,
    )


def _job_cancel(env, run_id, job_id):
    return env.client.post(f"/api/v1/story/runs/{run_id}/jobs/{job_id}/cancel")


def test_cancel_outcome_literals_unchanged():
    """``outcome`` keeps its three literals; ``cancel_state`` is additive."""
    fields = CancelOutcome.model_fields
    assert set(typing.get_args(fields["outcome"].annotation)) == {
        "cancelled",
        "too_late",
        "already_finished",
    }
    assert set(typing.get_args(fields["cancel_state"].annotation)) == {
        "cancel_confirmed",
        "cancel_requested",
        "too_late",
        "already_finished",
    }


def test_queued_job_cancel_is_confirmed(env):
    """A queued job cancels at once: outcome ``cancelled``, state confirmed."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    body = _job_cancel(env, run_id, job["job_id"]).json()
    assert body["outcome"] == "cancelled"
    assert body["cancel_state"] == "cancel_confirmed"
    assert body["job"]["status"] == "cancelled"


def test_claimed_job_is_too_late_and_still_completes(env):
    """A claimed job is never interrupted: cancel is too late; its result stays."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    claimed = env.claim()
    body = _job_cancel(env, run_id, job["job_id"]).json()
    assert body["outcome"] == "too_late"
    assert body["cancel_state"] == "too_late"
    env.complete(claimed)
    finished = env.client.get(f"/api/v1/story/runs/{run_id}/jobs/{job['job_id']}")
    assert finished.json()["status"] == "succeeded"
    assert finished.json()["result"] == {"ok": True}


def test_finished_job_is_already_finished(env):
    """A terminal job reports ``already_finished`` in both fields."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    env.complete(env.claim())
    body = _job_cancel(env, run_id, job["job_id"]).json()
    assert body["outcome"] == "already_finished"
    assert body["cancel_state"] == "already_finished"


def test_run_cancel_confirms_queued_jobs(env):
    """Run cancel with only queued work: every job cancelled, run cancelled."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    body = env.cancel_run(run_id).json()
    assert body["cancel_state"] == "cancel_confirmed"
    assert body["run_state"] == "cancelled"
    assert body["jobs"] == [
        {"job_id": job["job_id"], "cancel_state": "cancel_confirmed"}
    ]
    seen = env.client.get(f"/api/v1/story/runs/{run_id}/jobs/{job['job_id']}")
    assert seen.json()["status"] == "cancelled"
    record = env.client.get(f"/api/v1/story/runs/{run_id}").json()
    assert record["cancel_requested_at"] is not None


def test_run_cancel_is_requested_while_a_job_runs_then_cancelled_after(env):
    """A running job is never interrupted: the run is ``cancel_requested`` until it ends."""
    run_id = env.new_run()
    queued = env.submit(run_id, "op-queued")
    other = {**BACKTEST, "strategy_params": {"symbols": ["AAA"]}}
    running = env.submit(run_id, "op-running", other)
    claimed = env.claim()  # the first-created job is claimed first
    first = env.cancel_run(run_id).json()
    assert first["cancel_state"] == "cancel_requested"
    assert first["run_state"] == "cancel_requested"
    states = {job["job_id"]: job["cancel_state"] for job in first["jobs"]}
    assert sorted(states.values()) == ["cancel_confirmed", "too_late"]
    assert states[claimed.run_id] == "too_late"
    del queued, running
    env.complete(claimed)
    second = env.cancel_run(run_id).json()
    assert second["run_state"] == "cancelled"
    assert second["cancel_state"] == "already_finished"
    assert {job["cancel_state"] for job in second["jobs"]} == {"already_finished"}
    done = env.client.get(f"/api/v1/story/runs/{run_id}/jobs/{claimed.run_id}")
    assert done.json()["status"] == "succeeded"


def test_cancel_is_idempotent_and_keeps_its_first_timestamp(env):
    """A second cancel changes nothing about the recorded request time."""
    run_id = env.new_run()
    env.cancel_run(run_id)
    first = env.client.get(f"/api/v1/story/runs/{run_id}").json()
    env.cancel_run(run_id)
    second = env.client.get(f"/api/v1/story/runs/{run_id}").json()
    assert first["cancel_requested_at"] == second["cancel_requested_at"]


def test_unknown_or_foreign_run_cancel_is_404(env):
    """No existence oracle: an unknown run is a 404."""
    assert env.cancel_run("0" * 32).status_code == 404


def test_mutations_after_run_cancel_are_409(env):
    """Every mutating route refuses a cancelled run with ``run_cancelled``."""
    run_id = env.new_run()
    sandbox_id, _ = env.sandbox_and_request(run_id)
    stage = next(
        iter(env.client.get(f"/api/v1/story/runs/{run_id}").json()["stage_status"])
    )
    assert env.cancel_run(run_id).status_code == 200
    base = f"/api/v1/story/runs/{run_id}"
    attempts = [
        env.client.post(
            f"{base}/checkpoint",
            json={"expected_version": 0, "stage_id": stage, "status": "succeeded"},
        ),
        env.client.post(
            f"{base}/jobs",
            json={
                "operation_id": "op-late",
                "kind": "story.backtest",
                "payload": BACKTEST,
            },
        ),
        env.client.post(f"{base}/artifacts/table", json=TABLE),
        env.client.post(
            f"{base}/paper/sandboxes",
            json={"engine": "techtrade", "starting_cash": "100000"},
        ),
        env.client.post(
            f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
            json={
                "operation_id": "prep-late",
                "action": "submit_batch",
                "arguments": BATCH,
            },
        ),
    ]
    for response in attempts:
        assert response.status_code == 409, response.text
        assert "run_cancelled" in response.json()["detail"]


def test_reads_and_job_cancel_stay_open_on_a_cancelled_run(env):
    """A cancelled run can still be read and its jobs inspected or cancelled."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    env.claim()
    env.cancel_run(run_id)
    base = f"/api/v1/story/runs/{run_id}"
    for url in (base, f"{base}/jobs", f"{base}/jobs/{job['job_id']}"):
        assert env.client.get(url).status_code == 200, url
    assert _job_cancel(env, run_id, job["job_id"]).status_code == 200


def test_pending_request_withdrawn_cannot_apply(env):
    """Run cancel withdraws a pending request; its approval no longer applies."""
    run_id = env.new_run()
    _, request_id = env.sandbox_and_request(run_id)
    approval = paper_approve.approve_request(
        request_id, db_path=env.store, confirm=lambda _summary: True
    )
    body = env.cancel_run(run_id).json()
    assert body["requests"] == {"withdrawn": 1, "applying": 0}
    seen = env.client.get(f"/api/v1/story/paper/requests/{request_id}")
    assert seen.json()["status"] == "withdrawn"
    applied = env.client.post(
        f"/api/v1/story/paper/requests/{request_id}/apply",
        json={"approval": approval, "action": "submit_batch", "arguments": BATCH},
    )
    assert applied.status_code == 409, applied.text


def test_applying_request_keeps_the_run_cancel_requested(env):
    """A request mid-apply is never withdrawn; the run stays cancel_requested."""
    run_id = env.new_run()
    _, request_id = env.sandbox_and_request(run_id)
    with sqlite3.connect(env.store) as connection:
        connection.execute(
            "UPDATE story_paper_requests SET status = 'applying' WHERE request_id = ?",
            (request_id,),
        )
    body = env.cancel_run(run_id).json()
    assert body["requests"] == {"withdrawn": 0, "applying": 1}
    assert body["cancel_state"] == "cancel_requested"
    assert body["run_state"] == "cancel_requested"


def test_cancel_run_receipt_records_state_only(env):
    """A Hermes-bound run records the cancel transition as hashes and states."""
    run_id = env.new_run(BINDING)
    env.submit(run_id, "op-1")
    env.claim()
    env.cancel_run(run_id)
    env.cancel_run(run_id)
    with sqlite3.connect(env.store) as connection:
        rows = connection.execute(
            "SELECT tool, state, deliveries, outcome_ref FROM story_receipts"
            " WHERE run_id = ? AND tool = 'story_run_cancel'",
            (run_id,),
        ).fetchall()
    assert rows == [("story_run_cancel", "cancel_requested", 2, run_id)]


def test_legacy_run_cancel_writes_no_receipt(env):
    """An unbound run keeps legacy semantics: no receipt row."""
    run_id = env.new_run()
    env.cancel_run(run_id)
    with sqlite3.connect(env.store) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        count = (
            connection.execute(
                "SELECT COUNT(*) FROM story_receipts WHERE tool = 'story_run_cancel'"
            ).fetchone()[0]
            if "story_receipts" in tables
            else 0
        )
    assert count == 0


def test_old_run_json_without_cancel_loads(env):
    """Rows written before T02 have no ``cancel_requested_at`` and still load."""
    run_id = env.new_run()
    with sqlite3.connect(env.store) as connection:
        raw = connection.execute(
            "SELECT record FROM story_runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert "cancel_requested_at" in raw  # written as null by the model
    stripped = raw.replace('"cancel_requested_at":null,', "").replace(
        ',"cancel_requested_at":null', ""
    )
    assert "cancel_requested_at" not in stripped
    with sqlite3.connect(env.store) as connection:
        connection.execute(
            "UPDATE story_runs SET record = ? WHERE run_id = ?", (stripped, run_id)
        )
    record = env.client.get(f"/api/v1/story/runs/{run_id}").json()
    assert record["cancel_requested_at"] is None
