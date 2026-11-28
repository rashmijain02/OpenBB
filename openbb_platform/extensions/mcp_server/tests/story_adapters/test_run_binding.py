"""One Hermes start or cron fire binds to exactly one story run (#1341 T01).

Synthetic binding keys only; the run store lives in ``tmp_path``.
"""

# pylint: disable=redefined-outer-name

import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters.registry import (
    BindingConflict,
    RunBinding,
    RunRecord,
    RunStore,
    compose_story_registry_app,
)

AGENTS = Path(__file__).resolve().parents[3] / "agents" / "openbb_agents"
MANIFESTS = AGENTS / "notebook_guide" / "stories"
SHIPPED = AGENTS / "hermes_integration" / "workflows"
FILE = "synthetic.concentration_review.workflow.json"
WORKFLOW = "workflow:synthetic.concentration_review"
KEY_A = "hs-" + "a" * 32
KEY_B = "hc-" + "b" * 32


def _binding(key=KEY_A, origin="interactive"):
    return {"harness": "hermes", "binding_key": key, "origin": origin}


@pytest.fixture
def client(tmp_path):
    """Registry app over a copied workflow and a tmp run store."""
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    shutil.copy(SHIPPED / FILE, workflows / FILE)
    app = compose_story_registry_app(
        FastAPI(),
        principal="alice",
        manifest_dir=MANIFESTS,
        workflow_dir=workflows,
        store_path=tmp_path / "runs.sqlite",
    )
    test_client = TestClient(app)
    test_client.store = tmp_path / "runs.sqlite"  # type: ignore[attr-defined]
    return test_client


def _create(client, story_id=WORKFLOW, binding=None):
    body = {"story_id": story_id}
    if binding is not None:
        body["binding"] = binding
    return client.post("/api/v1/story/runs", json=body)


def _run_count(store: Path) -> int:
    with sqlite3.connect(store) as connection:
        return connection.execute("SELECT COUNT(*) FROM story_runs").fetchone()[0]


def test_same_binding_key_returns_same_run(client):
    """Same binding key returns same run."""
    first = _create(client, binding=_binding())
    second = _create(client, binding=_binding())
    assert first.status_code == second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"]
    assert second.json()["binding"] == _binding()
    assert _run_count(client.store) == 1


def test_unbound_creates_stay_distinct(client):
    """Unbound creates stay distinct."""
    first = _create(client).json()
    second = _create(client).json()
    assert first["run_id"] != second["run_id"]
    assert first["binding"] is None
    assert _run_count(client.store) == 2


def test_different_binding_keys_are_different_runs(client):
    """Different binding keys are different runs."""
    first = _create(client, binding=_binding()).json()
    second = _create(client, binding=_binding(KEY_B, "cron")).json()
    assert first["run_id"] != second["run_id"]


def test_binding_key_for_other_story_conflicts(client):
    """Binding key for other story conflicts."""
    assert _create(client, binding=_binding()).status_code == 200
    response = _create(client, story_id="portfolio/08", binding=_binding())
    assert response.status_code == 409, response.text
    assert "binding_conflict" in response.json()["detail"]
    assert _run_count(client.store) == 1


def test_binding_key_must_match_the_operation_id_pattern(client):
    """Binding key must match the operation id pattern."""
    response = _create(client, binding=_binding(key="has spaces"))
    assert response.status_code == 422


def test_concurrent_creates_one_run(tmp_path):
    """Concurrent creates one run."""
    store = RunStore(tmp_path / "runs.sqlite")
    binding = RunBinding(**_binding())
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def create(run_id: str) -> None:
        now = datetime.now(timezone.utc)
        record = RunRecord(
            run_id=run_id,
            story_id=WORKFLOW,
            manifest_version="m",
            provider_mode="fixture",
            state_version=0,
            stage_status={},
            state={},
            provenance={},
            created_at=now,
            updated_at=now,
            binding=binding,
        )
        barrier.wait()
        try:
            results.append(store.create("alice", record).run_id)
        except BaseException as error:  # noqa: BLE001  # surfaced below
            errors.append(error)

    threads = [threading.Thread(target=create, args=(f"r{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert len(set(results)) == 1
    assert _run_count(tmp_path / "runs.sqlite") == 1


def test_binding_conflict_is_typed(tmp_path):
    """Binding conflict is typed."""
    store = RunStore(tmp_path / "runs.sqlite")
    now = datetime.now(timezone.utc)

    def record(run_id, story_id):
        return RunRecord(
            run_id=run_id,
            story_id=story_id,
            manifest_version="m",
            provider_mode="fixture",
            state_version=0,
            stage_status={},
            state={},
            provenance={},
            created_at=now,
            updated_at=now,
            binding=RunBinding(**_binding()),
        )

    store.create("alice", record("r1", "a"))
    with pytest.raises(BindingConflict):
        store.create("alice", record("r2", "b"))
    # Another principal's binding namespace is separate.
    assert store.create("bob", record("r3", "b")).run_id == "r3"


def test_legacy_rows_without_binding_still_load(client):
    """Legacy rows without binding still load."""
    run_id = _create(client).json()["run_id"]
    with sqlite3.connect(client.store) as connection:
        raw = connection.execute("SELECT record FROM story_runs").fetchone()[0]
        legacy = raw.replace(',"binding":null', "")
        assert "binding" not in legacy
        connection.execute("UPDATE story_runs SET record = ?", (legacy,))
    response = client.get(f"/api/v1/story/runs/{run_id}")
    assert response.status_code == 200, response.text
    assert response.json()["binding"] is None
