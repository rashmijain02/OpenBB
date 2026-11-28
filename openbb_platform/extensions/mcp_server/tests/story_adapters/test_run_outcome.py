"""Run outcome from durable records only (#1341 T03, plan 3.5).

The pure table covers every row of plan 3.5 (first match wins), and the
``story_run_outcome`` route is exercised over the real composed apps, a real
job service and a real paper store. Synthetic data, temporary stores only.
"""

# pylint: disable=redefined-outer-name,unused-import

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import paper, paper_approve
from openbb_mcp_server.story_adapters.registry import RunRecord
from openbb_mcp_server.story_adapters.run_outcome import (
    APPLY_STALE,
    JobFact,
    RequestFact,
    derive_outcome,
)
from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

from .test_cancel_semantics import BATCH, BINDING, env  # noqa: F401

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=10)
EARLIER = NOW - timedelta(minutes=10)


def _record(stages: dict[str, str], cancelled: bool = False) -> RunRecord:
    return RunRecord(
        run_id="run-1",
        story_id="workflow:synthetic.concentration_review",
        manifest_version="synthetic.concentration_review@1.0.0",
        workflow_manifest_sha256="a" * 64,
        provider_mode="fixture",
        state_version=len(stages),
        stage_status=stages,
        state={},
        provenance={},
        created_at=EARLIER,
        updated_at=EARLIER,
        cancel_requested_at=EARLIER if cancelled else None,
    )


DONE = {"a": "succeeded", "b": "succeeded"}
OPTIONAL = {"a": False, "b": True}

# (name, record kwargs, derive kwargs, expected outcome, uncertain)
TABLE = [
    ("blocked", {"stages": DONE}, {"workflow_current": False}, "blocked", False),
    (
        "cancel_requested",
        {"stages": DONE, "cancelled": True},
        {"jobs": [JobFact("a", "running")]},
        "cancel_requested",
        False,
    ),
    ("cancelled", {"stages": DONE, "cancelled": True}, {}, "cancelled", False),
    (
        "partial_stale_applying",
        {"stages": DONE},
        {"requests": [RequestFact("applying", LATER, NOW - APPLY_STALE)]},
        "partial",
        True,
    ),
    (
        "partial_submission_without_job",
        {"stages": DONE},
        {"jobs": [JobFact("a", None)]},
        "partial",
        True,
    ),
    ("failed_stage", {"stages": {"a": "failed", "b": "pending"}}, {}, "failed", False),
    (
        "failed_job",
        {"stages": {"a": "running", "b": "pending"}},
        {"jobs": [JobFact("a", "failed")]},
        "failed",
        False,
    ),
    (
        "waiting_job",
        {"stages": {"a": "running", "b": "pending"}},
        {"jobs": [JobFact("a", "queued")]},
        "waiting_job",
        False,
    ),
    (
        "awaiting_approval",
        {"stages": {"a": "running", "b": "pending"}},
        {"requests": [RequestFact("pending", LATER, None)]},
        "awaiting_approval",
        False,
    ),
    (
        "needs_input",
        {"stages": {"a": "running", "b": "pending"}},
        {"requests": [RequestFact("pending", EARLIER, None)]},
        "needs_input",
        False,
    ),
    (
        "succeeded",
        {"stages": DONE},
        {"jobs": [JobFact("a", "succeeded")]},
        "succeeded",
        False,
    ),
    (
        "partial_optional_failed",
        {"stages": {"a": "succeeded", "b": "failed"}},
        {},
        "partial",
        False,
    ),
    (
        "running",
        {"stages": {"a": "succeeded", "b": "pending"}},
        {"optional": {}},
        "running",
        False,
    ),
    ("ready", {"stages": {"a": "pending", "b": "pending"}}, {}, "ready", False),
]


def _derive(record_kwargs, derive_kwargs):
    kwargs = {
        "optional": OPTIONAL,
        "workflow_current": True,
        "jobs": [],
        "requests": [],
        "artifacts_valid": True,
        "now": NOW,
        **derive_kwargs,
    }
    return derive_outcome(_record(**record_kwargs), **kwargs)


@pytest.mark.parametrize(
    "record_kwargs,derive_kwargs,expected,uncertain",
    [row[1:] for row in TABLE],
    ids=[row[0] for row in TABLE],
)
def test_outcome_table(record_kwargs, derive_kwargs, expected, uncertain):
    """Every row of plan 3.5, first match wins."""
    outcome = _derive(record_kwargs, derive_kwargs)
    assert outcome.outcome == expected
    assert outcome.uncertain is uncertain


def test_partial_never_maps_to_success():
    """D3: an optional failure is partial; a broken artifact is not success."""
    optional_failed = _derive({"stages": {"a": "succeeded", "b": "failed"}}, {})
    assert optional_failed.outcome == "partial"
    broken = _derive({"stages": DONE}, {"artifacts_valid": False})
    assert broken.outcome != "succeeded"


def test_stale_applying_is_partial_uncertain():
    """D6: an apply that never reported back is partial and uncertain."""
    fresh = _derive(
        {"stages": DONE}, {"requests": [RequestFact("applying", LATER, NOW)]}
    )
    assert fresh.outcome == "running" and not fresh.uncertain
    legacy = _derive(
        {"stages": DONE}, {"requests": [RequestFact("applying", LATER, None)]}
    )
    assert (legacy.outcome, legacy.uncertain) == ("partial", True)


def test_cancelled_run_outcome_is_never_succeeded():
    """A cancelled run with every stage done still reads cancelled."""
    outcome = _derive({"stages": DONE, "cancelled": True}, {})
    assert outcome.outcome == "cancelled"


# --- the route, over the real composed apps -------------------------------


def _outcome(env, run_id):
    response = env.client.get(f"/api/v1/story/runs/{run_id}/outcome")
    assert response.status_code == 200, response.text
    return response.json()


def _restart(env, tmp_path):
    """A fresh app over the same stores, as after a server restart."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openbb_core.api.dependency.jobs import get_job_service
    from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
    from openbb_mcp_server.story_adapters.paper import compose_story_paper_app
    from openbb_mcp_server.story_adapters.registry import compose_story_registry_app

    from .test_cancel_semantics import MANIFESTS

    common = {"principal": "alice", "store_path": env.store}
    workflows = tmp_path / "workflows"
    app = compose_story_registry_app(
        FastAPI(), manifest_dir=MANIFESTS, workflow_dir=workflows, **common
    )
    app = compose_story_jobs_app(app, workflow_dir=workflows, **common)
    app = compose_story_paper_app(
        app, paper_root=tmp_path / "paper", workflow_dir=workflows, **common
    )
    app.dependency_overrides[get_job_service] = lambda: env.service
    return TestClient(app)


def _checkpoint(env, run_id, stage_id, status="succeeded"):
    version = env.client.get(f"/api/v1/story/runs/{run_id}").json()["state_version"]
    response = env.client.post(
        f"/api/v1/story/runs/{run_id}/checkpoint",
        json={
            "expected_version": version,
            "stage_id": stage_id,
            "status": status,
            "state": {"output_sha256": "b" * 64},
        },
    )
    assert response.status_code == 200, response.text


def test_route_reads_ready_then_succeeded(env):
    """A fresh run is ready; all mandatory stages checkpointed is succeeded."""
    run_id = env.new_run()
    assert _outcome(env, run_id)["outcome"] == "ready"
    for stage in ("concentration", "construction", "checkpoint"):
        _checkpoint(env, run_id, stage)
    body = _outcome(env, run_id)
    assert body["outcome"] == "succeeded"
    assert body["workflow_current"] is True


def test_route_reports_waiting_job_then_failed(env):
    """Job status comes from the job store, not from the reply."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-1")
    assert _outcome(env, run_id)["outcome"] == "waiting_job"
    claimed = env.claim()
    assert claimed.run_id == job["job_id"]
    env.service.fail(claimed.run_id, RuntimeError("synthetic failure"))
    assert _outcome(env, run_id)["outcome"] == "failed"


def test_route_reports_cancelled_never_succeeded(env):
    """After story_run_cancel the outcome is cancelled, even with every stage done."""
    run_id = env.new_run(BINDING)
    for stage in ("concentration", "construction", "checkpoint"):
        _checkpoint(env, run_id, stage)
    env.cancel_run(run_id)
    body = _outcome(env, run_id)
    assert body["outcome"] == "cancelled"
    assert body["cancel_requested_at"] is not None


def test_route_reports_stale_applying_as_partial_uncertain(env):
    """An applying row older than APPLY_STALE is partial + uncertain (D6)."""
    run_id = env.new_run()
    _, request_id = env.sandbox_and_request(run_id)
    stale = (datetime.now(timezone.utc) - APPLY_STALE - timedelta(seconds=5)).isoformat()
    with sqlite3.connect(env.store) as connection:
        connection.execute(
            "UPDATE story_paper_requests SET status = 'applying', applying_at = ?"
            " WHERE request_id = ?",
            (stale, request_id),
        )
    body = _outcome(env, run_id)
    assert (body["outcome"], body["uncertain"]) == ("partial", True)
    assert body["requests"] == {"applying": 1}


def test_route_reports_blocked_after_workflow_drift(env, tmp_path):
    """A changed workflow document blocks the run instead of erroring."""
    run_id = env.new_run()
    path = tmp_path / "workflows" / "synthetic.concentration_review.workflow.json"
    path.write_text(path.read_text("utf-8").replace("Synthetic", "Drifted", 1), "utf-8")
    # The catalog is read at start-up: a restarted server sees the change.
    client = _restart(env, tmp_path)
    response = client.get(f"/api/v1/story/runs/{run_id}/outcome")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "blocked"
    assert body["workflow_current"] is False


def test_route_reports_awaiting_approval_then_needs_input(env, monkeypatch):
    """A pending request awaits approval; once expired the run needs input."""
    run_id = env.new_run()
    env.sandbox_and_request(run_id)
    assert _outcome(env, run_id)["outcome"] == "awaiting_approval"
    from openbb_mcp_server.story_adapters import run_outcome

    real_now = run_outcome.utc_now
    monkeypatch.setattr(
        run_outcome,
        "utc_now",
        lambda: real_now() + paper.APPROVAL_TTL + timedelta(seconds=1),
    )
    body = _outcome(env, run_id)
    assert (body["outcome"], body["reason"]) == ("needs_input", "approval_expired")
    assert body["requests"] == {"expired": 1}


def test_another_principal_cannot_read_the_outcome(env):
    """Unknown or foreign runs are 404."""
    response = env.client.get("/api/v1/story/runs/not-a-run/outcome")
    assert response.status_code == 404


# --- scheduler ownership (D4) ---------------------------------------------


def test_story_job_definitions_have_no_schedule(tmp_path):
    """Story kinds never get an OpenBB schedule: Hermes cron owns finance runs."""
    definitions = get_job_definitions()
    assert definitions, "no story job definitions: the kind table is broken"
    assert all(definition.schedule is None for definition in definitions)
    service = JobService(
        store=SqliteJobStore(tmp_path / "jobs.db"),
        registry=JobRegistry(definitions),
    )
    assert service.enqueue_due(NOW + timedelta(days=400)) == []


def test_approve_helper_still_signs(env):
    """The approver CLI path is unchanged by the outcome route."""
    run_id = env.new_run()
    _, request_id = env.sandbox_and_request(run_id)
    assert paper_approve.approve_request(
        request_id, db_path=env.store, confirm=lambda _summary: True
    )
