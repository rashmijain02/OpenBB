"""Workflow-bound runs in the story registry (#1340-T02).

Runtime identity of a workflow run is the workflow digest. The notebook hash
of a tutorial story never appears in it, and a run survives with no story
manifests at all.
"""

# pylint: disable=redefined-outer-name

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters.registry import (
    RunCreate,
    RunRecord,
    WorkflowCatalog,
    compose_story_registry_app,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
AGENTS = REPO_ROOT / "openbb_platform" / "extensions" / "agents" / "openbb_agents"
MANIFESTS = AGENTS / "notebook_guide" / "stories"
SHIPPED = AGENTS / "hermes_integration" / "workflows"
WORKFLOW_ID = "workflow:synthetic.concentration_review"
FILE = "synthetic.concentration_review.workflow.json"


def _digest(document: dict) -> str:
    """Independent oracle: sorted compact JSON, SHA-256 (not the production helper)."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _client(store: Path, workflows: Path, manifests: Path | None = MANIFESTS):
    app = compose_story_registry_app(
        FastAPI(),
        principal="alice",
        manifest_dir=manifests,
        workflow_dir=workflows,
        store_path=store,
    )
    return TestClient(app)


@pytest.fixture
def workflow_dir(tmp_path) -> Path:
    """Copy the shipped workflow into a directory safe to mutate."""
    target = tmp_path / "workflows"
    target.mkdir()
    shutil.copy(SHIPPED / FILE, target / FILE)
    return target


def _create(client) -> dict:
    response = client.post("/api/v1/story/runs", json={"story_id": WORKFLOW_ID})
    assert response.status_code == 200, response.text
    return response.json()


def _checkpoint(client, run: dict):
    return client.post(
        f"/api/v1/story/runs/{run['run_id']}/checkpoint",
        json={
            "expected_version": run["state_version"],
            "stage_id": "concentration",
            "status": "succeeded",
            "state": {"hhi": 0.25},
        },
    )


def test_workflow_run_version_is_workflow_digest_not_notebook_hash(
    tmp_path, workflow_dir
):
    """Version is ``workflow:<id>@<digest12>``; no notebook field feeds it."""
    document = json.loads((workflow_dir / FILE).read_text("utf-8"))
    digest = _digest(document)
    notebook_hash = json.loads((MANIFESTS / "portfolio__03.json").read_text("utf-8"))[
        "source_sha256"
    ]
    run = _create(_client(tmp_path / "runs.sqlite", workflow_dir))
    assert run["manifest_version"] == f"{WORKFLOW_ID}@{digest[:12]}"
    assert run["workflow_manifest_sha256"] == digest
    assert notebook_hash[:12] not in run["manifest_version"]
    assert set(run["stage_status"]) == {s["id"] for s in document["stages"]}
    # Changing the document changes the version (the digest is what binds).
    document["title"] = "changed"
    (workflow_dir / FILE).write_text(json.dumps(document), "utf-8")
    other = _create(_client(tmp_path / "runs2.sqlite", workflow_dir))
    assert other["manifest_version"] != run["manifest_version"]


def test_workflow_run_survives_missing_story_manifest_dir(tmp_path, workflow_dir):
    """No story manifests: workflow runs work, legacy story runs say unavailable."""
    client = _client(
        tmp_path / "runs.sqlite", workflow_dir, manifests=tmp_path / "empty"
    )
    run = _create(client)
    assert run["workflow_manifest_sha256"]
    legacy = client.post("/api/v1/story/runs", json={"story_id": "portfolio/03"})
    assert legacy.status_code == 503
    catalog = client.get("/api/v1/story/catalog")
    assert catalog.status_code == 200
    assert [row["story_id"] for row in catalog.json()] == [WORKFLOW_ID]
    assert catalog.json()[0]["notebook_path"] is None


def test_catalog_lists_stories_and_workflows_and_input_schema_is_unchanged(
    tmp_path, workflow_dir
):
    """Both kinds of runs are exposed; ``RunCreate`` keeps its pinned input shape."""
    client = _client(tmp_path / "runs.sqlite", workflow_dir)
    ids = [row["story_id"] for row in client.get("/api/v1/story/catalog").json()]
    assert WORKFLOW_ID in ids and "portfolio/03" in ids
    assert len(ids) == 26
    assert set(RunCreate.model_json_schema()["properties"]) == {
        "story_id",
        "provider_mode",
    }
    described = client.get("/api/v1/story/describe", params={"story_id": WORKFLOW_ID})
    assert described.status_code == 200
    assert described.json()["workflow_id"] == "synthetic.concentration_review"


def test_checkpoint_rejected_when_workflow_manifest_changed(tmp_path, workflow_dir):
    """A run started on one digest cannot be checkpointed against another."""
    store = tmp_path / "runs.sqlite"
    client = _client(store, workflow_dir)
    run = _create(client)

    # Control: unchanged workflow accepts a checkpoint.
    assert _checkpoint(client, run).status_code == 200

    document = json.loads((workflow_dir / FILE).read_text("utf-8"))
    document["title"] = "Edited after the run started"
    (workflow_dir / FILE).write_text(json.dumps(document), "utf-8")
    changed = _client(store, workflow_dir)
    current = changed.get(f"/api/v1/story/runs/{run['run_id']}").json()
    response = _checkpoint(changed, current)
    assert response.status_code == 409
    assert "workflow" in response.json()["detail"].lower()
    # Nothing was written.
    after = changed.get(f"/api/v1/story/runs/{run['run_id']}").json()
    assert after["state_version"] == current["state_version"]


def test_checkpoint_rejected_when_workflow_is_removed(tmp_path, workflow_dir):
    """A run whose workflow is no longer loaded fails closed."""
    store = tmp_path / "runs.sqlite"
    run = _create(_client(store, workflow_dir))
    (workflow_dir / FILE).unlink()
    gone = _client(store, workflow_dir)
    assert _checkpoint(gone, run).status_code == 409


def test_legacy_rows_without_workflow_digest_still_load(tmp_path, workflow_dir):
    """Stored story runs predate the field: they load with ``None`` and checkpoint."""
    store = tmp_path / "runs.sqlite"
    client = _client(store, workflow_dir)
    response = client.post("/api/v1/story/runs", json={"story_id": "portfolio/03"})
    legacy = response.json()
    assert legacy["workflow_manifest_sha256"] is None
    connection = sqlite3.connect(store)
    try:
        (raw,) = connection.execute(
            "SELECT record FROM story_runs WHERE run_id = ?", (legacy["run_id"],)
        ).fetchone()
        old = json.loads(raw)
        old.pop("workflow_manifest_sha256")
        connection.execute(
            "UPDATE story_runs SET record = ? WHERE run_id = ?",
            (json.dumps(old), legacy["run_id"]),
        )
        connection.commit()
    finally:
        connection.close()
    assert RunRecord.model_validate(old).workflow_manifest_sha256 is None
    fetched = client.get(f"/api/v1/story/runs/{legacy['run_id']}")
    assert fetched.status_code == 200
    stage = next(iter(legacy["stage_status"]))
    written = client.post(
        f"/api/v1/story/runs/{legacy['run_id']}/checkpoint",
        json={
            "expected_version": 0,
            "stage_id": stage,
            "status": "succeeded",
            "state": {},
        },
    )
    assert written.status_code == 200


def _with_stage_cells(document: dict) -> dict:
    document["stages"][0]["cells"] = [1, 2]
    return document


def _with_notebook_path(document: dict) -> dict:
    document["notebook_path"] = "notebooks/portfolio/03.ipynb"
    return document


def _with_nested_ipynb_string(document: dict) -> dict:
    document["limitations"].append("see notebooks/portfolio/03-x.ipynb")
    return document


def _with_source_hash(document: dict) -> dict:
    document["source_sha256"] = "0" * 64
    return document


@pytest.mark.parametrize(
    "mutate",
    [
        _with_stage_cells,
        _with_notebook_path,
        _with_nested_ipynb_string,
        _with_source_hash,
    ],
)
def test_workflow_catalog_refuses_documents_with_cells_or_notebook_path(
    tmp_path, workflow_dir, mutate
):
    """A document carrying notebook identity is never loaded or run."""
    document = json.loads((workflow_dir / FILE).read_text("utf-8"))
    (workflow_dir / FILE).write_text(json.dumps(mutate(document)), "utf-8")
    catalog = WorkflowCatalog(workflow_dir)
    assert catalog.get("synthetic.concentration_review") is None
    assert catalog.summaries() == []
    assert FILE in catalog.refused
    client = _client(tmp_path / "runs.sqlite", workflow_dir)
    response = client.post("/api/v1/story/runs", json={"story_id": WORKFLOW_ID})
    assert response.status_code == 404


def test_shipped_workflow_loads_into_catalog():
    """Control for the refusal test: the shipped document is accepted."""
    catalog = WorkflowCatalog(SHIPPED)
    assert not catalog.refused
    assert [s.story_id for s in catalog.summaries()] == [WORKFLOW_ID]


def _malformed(document: dict, case: str) -> dict:
    """Structurally broken variants of the shipped workflow (review finding 1)."""
    broken = json.loads(json.dumps(document))
    if case == "no_stages":
        del broken["stages"]
    elif case == "stages_not_list":
        broken["stages"] = {"concentration": {}}
    elif case == "stage_not_object":
        broken["stages"] = ["concentration"]
    elif case == "empty_stages":
        broken["stages"] = []
    elif case == "bool_schema_version":
        broken["schema_version"] = True
    elif case == "float_schema_version":
        broken["schema_version"] = 1.0
    elif case == "bad_workflow_id":
        broken["workflow_id"] = "../Escape"
    elif case == "capabilities_not_object":
        broken["capabilities"] = ["platform:story_concentration"]
    broken["workflow_id"] = (
        broken["workflow_id"] if case == "bad_workflow_id" else "synthetic.malformed"
    )
    return broken


@pytest.mark.parametrize(
    "case",
    [
        "no_stages",
        "stages_not_list",
        "stage_not_object",
        "empty_stages",
        "bool_schema_version",
        "float_schema_version",
        "bad_workflow_id",
        "capabilities_not_object",
    ],
)
def test_malformed_workflow_is_refused_and_catalog_still_serves(
    tmp_path, workflow_dir, case
):
    """A bad file next to the shipped one never takes the catalog down."""
    document = json.loads((workflow_dir / FILE).read_text("utf-8"))
    (workflow_dir / "bad.workflow.json").write_text(
        json.dumps(_malformed(document, case)), "utf-8"
    )
    catalog = WorkflowCatalog(workflow_dir)
    assert "bad.workflow.json" in catalog.refused
    client = _client(tmp_path / "runs.sqlite", workflow_dir)
    response = client.get("/api/v1/story/catalog")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert sum(row["family"] == "workflow" for row in rows) == 1
    assert len(rows) == 26  # 25 stories + 1 workflow


def test_duplicate_workflow_id_is_refused(workflow_dir):
    """Two files claiming one ID are ambiguous; neither is served."""
    shutil.copy(workflow_dir / FILE, workflow_dir / "copy.workflow.json")
    catalog = WorkflowCatalog(workflow_dir)
    assert catalog.get("synthetic.concentration_review") is None
    assert {FILE, "copy.workflow.json"} <= set(catalog.refused)


@pytest.mark.parametrize("depth", [500, 5000])
def test_deeply_nested_workflow_is_refused_without_recursion_error(
    tmp_path, workflow_dir, depth
):
    """The notebook-key scan is iterative and depth-bounded; loading never raises."""
    text = (workflow_dir / FILE).read_text("utf-8")
    nested = '{"x":' * depth + "{}" + "}" * depth
    text = text.replace('"limitations": [', '"limitations": [' + nested + ",", 1)
    (workflow_dir / FILE).write_text(text, "utf-8")
    catalog = WorkflowCatalog(workflow_dir)
    assert FILE in catalog.refused
    client = _client(tmp_path / "runs.sqlite", workflow_dir)
    assert client.get("/api/v1/story/catalog").status_code == 200
