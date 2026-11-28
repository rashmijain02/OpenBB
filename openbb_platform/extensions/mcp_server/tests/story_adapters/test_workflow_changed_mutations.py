"""Only mutating story routes refuse a changed workflow (#1340, N1/N2).

Every mutating route answers 200/202 before the workflow document changes and
409 ``workflow_changed`` after it. Reads and job cancel stay open so an owner
can always inspect a run and stop queued work. Legacy runs are unaffected.
"""

# pylint: disable=redefined-outer-name,too-many-locals

import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import paper, paper_approve
from openbb_mcp_server.story_adapters.artifacts import compose_story_artifacts_app
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
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


def _flat_plan():
    """Reuse the artifact suite's synthetic TechTrade plan builder."""
    path = Path(__file__).with_name("test_artifacts.py")
    spec = importlib.util.spec_from_file_location("_artifacts_plan_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._flat_plan()  # pylint: disable=protected-access


SHEET = {"name": "S", "columns": ["a"], "rows": [[1]]}
ARTIFACT_BODIES = {
    "table": TABLE,
    "chart": {
        "name": "c",
        "chart": {"kind": "bar", "x": ["a"], "series": [{"name": "s", "values": [1]}]},
    },
    "workbook": {"name": "w", "sheets": [SHEET]},
    "report": {
        "name": "r",
        "title": "T",
        "sections": [{"heading": "H", "paragraphs": ["text"]}],
    },
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """All four adapters over one workflow copy, plus a change-the-workflow hook."""
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, KEY)
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    shutil.copy(SHIPPED / FILE, workflows / FILE)
    store = tmp_path / "runs.sqlite"
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(get_job_definitions()),
    )

    def build():
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
        return TestClient(app)

    client = build()

    def new_run(story_id=WORKFLOW):
        response = client.post("/api/v1/story/runs", json={"story_id": story_id})
        assert response.status_code == 200, response.text
        return response.json()

    def change():
        document = json.loads((workflows / FILE).read_text("utf-8"))
        document["title"] = "Changed after the run started"
        (workflows / FILE).write_text(json.dumps(document), "utf-8")
        return build()

    return SimpleNamespace(client=client, new_run=new_run, change=change, store=store)


def _assert_changed(response):
    assert response.status_code == 409, response.text
    assert "workflow_changed" in response.json()["detail"]


def _submit(client, run_id, operation_id="op-1"):
    return client.post(
        f"/api/v1/story/runs/{run_id}/jobs",
        json={
            "operation_id": operation_id,
            "kind": "story.backtest",
            "payload": BACKTEST,
        },
    )


def _sandbox(client, run_id):
    return client.post(
        f"/api/v1/story/runs/{run_id}/paper/sandboxes",
        json={"engine": "techtrade", "starting_cash": "100000"},
    )


def _prepare(client, sandbox_id, operation_id="prep-1"):
    return client.post(
        f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
        json={
            "operation_id": operation_id,
            "action": "submit_batch",
            "arguments": BATCH,
        },
    )


def test_checkpoint_gated(env):
    """Run checkpoint: 200 before the change, 409 after."""
    run = env.new_run()
    stage = next(iter(run["stage_status"]))
    body = {"expected_version": 0, "stage_id": stage, "status": "succeeded"}
    path = f"/api/v1/story/runs/{run['run_id']}/checkpoint"
    assert env.client.post(path, json=body).status_code == 200
    _assert_changed(env.change().post(path, json={**body, "expected_version": 1}))


def test_job_submit_gated(env):
    """Job submit: 202 before the change, 409 after."""
    run_id = env.new_run()["run_id"]
    assert _submit(env.client, run_id).status_code == 202
    _assert_changed(_submit(env.change(), run_id, "op-2"))


@pytest.mark.parametrize("kind", sorted(ARTIFACT_BODIES))
def test_artifact_write_gated(env, kind):
    """Each artifact write route: 200 before the change, 409 after."""
    run_id = env.new_run()["run_id"]
    path = f"/api/v1/story/runs/{run_id}/artifacts/{kind}"
    assert env.client.post(path, json=ARTIFACT_BODIES[kind]).status_code == 200
    _assert_changed(env.change().post(path, json=ARTIFACT_BODIES[kind]))


def test_techtrade_workbook_gated(env):
    """TechTrade workbook write: 200 before the change, 409 after."""
    run_id = env.new_run()["run_id"]
    path = f"/api/v1/story/runs/{run_id}/artifacts/techtrade_workbook"
    body = {"name": "morning", "plans": [_flat_plan()]}
    assert env.client.post(path, json=body).status_code == 200
    _assert_changed(env.change().post(path, json=body))


def test_paper_sandbox_prepare_apply_gated(env):
    """Sandbox create, prepare and apply: allowed before, 409 after."""
    run_id = env.new_run()["run_id"]
    sandbox = _sandbox(env.client, run_id)
    assert sandbox.status_code == 200, sandbox.text
    sandbox_id = sandbox.json()["sandbox_id"]
    prepared = _prepare(env.client, sandbox_id)
    assert prepared.status_code == 200, prepared.text
    request_id = prepared.json()["request_id"]
    approval = paper_approve.approve_request(
        request_id, db_path=env.store, confirm=lambda _summary: True
    )
    changed = env.change()
    _assert_changed(_sandbox(changed, run_id))
    _assert_changed(_prepare(changed, sandbox_id, "prep-2"))
    _assert_changed(
        changed.post(
            f"/api/v1/story/paper/requests/{request_id}/apply",
            json={"approval": approval, "action": "submit_batch", "arguments": BATCH},
        )
    )


def test_reads_and_cancel_stay_open_after_change(env):
    """The owner can read everything and cancel a queued job after a change."""
    run_id = env.new_run()["run_id"]
    job = _submit(env.client, run_id)
    assert job.status_code == 202, job.text
    job_id = job.json()["job_id"]
    base = f"/api/v1/story/runs/{run_id}"
    artifact = env.client.post(f"{base}/artifacts/table", json=TABLE)
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["ref"]["artifact_id"]
    sandbox_id = _sandbox(env.client, run_id).json()["sandbox_id"]
    changed = env.change()
    reads = [
        base,
        f"{base}/jobs",
        f"{base}/jobs/{job_id}",
        f"{base}/artifacts/{artifact_id}",
        f"/api/v1/story/artifacts?run_id={run_id}",
        f"{base}/paper/sandboxes",
        f"/api/v1/story/paper/sandboxes/{sandbox_id}",
    ]
    for url in reads:
        response = changed.get(url)
        assert response.status_code == 200, (url, response.text)
    cancelled = changed.post(f"{base}/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["outcome"] == "cancelled"
    # Run-level cancel is a stop, not a mutation: it stays open too.
    run_cancel = changed.post(f"{base}/cancel")
    assert run_cancel.status_code == 200, run_cancel.text
    assert run_cancel.json()["run_state"] == "cancelled"


def test_legacy_runs_are_unaffected(env):
    """A legacy story run still accepts mutations after any workflow change."""
    run_id = env.new_run("portfolio/03")["run_id"]
    assert _submit(env.change(), run_id).status_code == 202
