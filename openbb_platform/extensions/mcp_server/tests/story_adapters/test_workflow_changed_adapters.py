"""Paper, jobs and artifacts refuse workflow runs whose workflow changed (#1340).

Review finding 6: the ``workflow_changed`` 409 guarded only checkpoints.
Legacy story runs are unaffected.
"""

# pylint: disable=redefined-outer-name

import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters.artifacts import compose_story_artifacts_app
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
from openbb_mcp_server.story_adapters.paper import compose_story_paper_app
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app

REPO_ROOT = Path(__file__).resolve().parents[5]
AGENTS = REPO_ROOT / "openbb_platform" / "extensions" / "agents" / "openbb_agents"
MANIFESTS = AGENTS / "notebook_guide" / "stories"
SHIPPED = AGENTS / "hermes_integration" / "workflows"
FILE = "synthetic.concentration_review.workflow.json"


@pytest.fixture
def setup(tmp_path):
    """A workflow dir copy, a shared store, and one workflow + one legacy run."""
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    shutil.copy(SHIPPED / FILE, workflows / FILE)
    store = tmp_path / "runs.sqlite"
    registry = TestClient(
        compose_story_registry_app(
            FastAPI(),
            principal="alice",
            manifest_dir=MANIFESTS,
            workflow_dir=workflows,
            store_path=store,
        )
    )
    runs = {}
    for name, story_id in (
        ("workflow", "workflow:synthetic.concentration_review"),
        ("legacy", "portfolio/03"),
    ):
        response = registry.post("/api/v1/story/runs", json={"story_id": story_id})
        assert response.status_code == 200, response.text
        runs[name] = response.json()["run_id"]
    return tmp_path, workflows, store, runs


def _clients(tmp_path, workflows, store):
    common = {"principal": "alice", "store_path": store, "workflow_dir": workflows}
    return {
        "jobs": (
            TestClient(compose_story_jobs_app(FastAPI(), **common)),
            "/api/v1/story/runs/{run}/jobs",
        ),
        "artifacts": (
            TestClient(
                compose_story_artifacts_app(
                    FastAPI(), artifact_root=tmp_path / "artifacts", **common
                )
            ),
            "/api/v1/story/artifacts?run_id={run}",
        ),
        "paper": (
            TestClient(
                compose_story_paper_app(
                    FastAPI(), paper_root=tmp_path / "paper", **common
                )
            ),
            "/api/v1/story/runs/{run}/paper/sandboxes",
        ),
    }


@pytest.mark.parametrize("adapter", ["jobs", "artifacts", "paper"])
def test_adapter_rejects_run_of_changed_workflow(setup, adapter):
    """Control 200 before the change, 409 workflow_changed after it."""
    tmp_path, workflows, store, runs = setup
    client, url = _clients(tmp_path, workflows, store)[adapter]
    assert client.get(url.format(run=runs["workflow"])).status_code == 200
    document = json.loads((workflows / FILE).read_text("utf-8"))
    document["title"] = "Changed after the run started"
    (workflows / FILE).write_text(json.dumps(document), "utf-8")
    client, url = _clients(tmp_path, workflows, store)[adapter]
    response = client.get(url.format(run=runs["workflow"]))
    assert response.status_code == 409
    assert "workflow_changed" in response.json()["detail"]
    # Legacy story runs carry no workflow digest and are unaffected.
    assert client.get(url.format(run=runs["legacy"])).status_code == 200
