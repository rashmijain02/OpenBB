"""HFP sidecar plan/run/workflow cards over the real stores (#1342 T02).

Real plan store, run store, job service and worker over temporary paths; the
sidecar is the guarded ASGI app driven through ``TestClient`` with the token.
Rows are read back from SQLite, never from handler counters. The only seams
are the three analytics provider calls, which raise if reached.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import secrets
import sqlite3
import typing
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("openbb_portfolio_intel")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openbb_agents.hermes_integration.web import cards, security, sidecar  # noqa: E402
from openbb_agents.hermes_integration.web.backend import StoryBackend  # noqa: E402
from openbb_core.api.dependency.jobs import get_job_service  # noqa: E402
from openbb_core.app.jobs.registry import JobRegistry  # noqa: E402
from openbb_core.app.jobs.sqlite_store import SqliteJobStore  # noqa: E402
from openbb_core.app.jobs.worker import JobWorker  # noqa: E402
from openbb_core.app.service.job_service import JobService  # noqa: E402
from openbb_mcp_server.story_adapters import analytics  # noqa: E402
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app  # noqa: E402
from openbb_mcp_server.story_adapters.registry import (  # noqa: E402
    RunRecord,
    compose_story_registry_app,
)
from openbb_mcp_server.story_adapters.run_outcome import (  # noqa: E402
    OutcomeState,
    derive_outcome,
)
from openbb_mcp_server.story_adapters.story_job_kinds import (  # noqa: E402
    get_job_definitions,
)

PRINCIPAL = "hermes#0123456789abcdef"
WID = "synthetic.basket_xray"
PORT = 8799


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """Story routes, job service, worker and the sidecar over one temp store."""
    store, root = tmp_path / "runs.sqlite", tmp_path / "artifacts"
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(store))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root))
    for name in ("_nport_rows", "_search_ticker", "_profile_sector"):

        def seam(*_a, _name=name, **_k):
            raise AssertionError(f"provider seam {_name} reached")

        monkeypatch.setattr(analytics, name, seam)
    jobs_db = tmp_path / "jobs.db"
    service = JobService(
        store=SqliteJobStore(jobs_db), registry=JobRegistry(get_job_definitions())
    )
    app = compose_story_registry_app(FastAPI(), principal=PRINCIPAL, store_path=store)
    app = compose_story_jobs_app(
        app, principal=PRINCIPAL, store_path=store, artifact_root=root
    )
    app.dependency_overrides[get_job_service] = lambda: service
    token = secrets.token_urlsafe(32)
    token_file = tmp_path / "state" / "sidecar-auth" / "openbb-hfp.token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(token, encoding="utf-8")
    clock: list[datetime] = []  # empty: real time; else the injected "now"
    backend = StoryBackend(
        principal=PRINCIPAL,
        store_path=store,
        artifact_root=root,
        service=service,
        clock=lambda: clock[0] if clock else datetime.now(timezone.utc),
    )
    guarded = sidecar.create_app(
        sidecar.SidecarConfig(
            port=PORT, principal=PRINCIPAL, token_file=token_file, backend=backend
        )
    )
    side = TestClient(guarded, base_url=f"http://127.0.0.1:{PORT}")
    side.headers[security.TOKEN_HEADER] = token
    return {
        "story": TestClient(app),
        "side": side,
        "store": store,
        "jobs_db": jobs_db,
        "worker": JobWorker(service=service, worker_id="test-worker"),
        "service": service,
        "clock": clock,
    }


def _rows(path, sql, *args):
    with sqlite3.connect(path) as connection:
        try:
            return connection.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []


def _preview(stack) -> dict:
    response = stack["story"].post("/api/v1/story/plans", json={"workflow_id": WID})
    assert response.status_code == 200, response.text
    return response.json()


def _approve(stack, card, nonce=None):
    return stack["side"].post(
        f"/plans/{card['plan_id']}/approve",
        json={
            "plan_sha256": card["plan_sha256"],
            "approval_nonce": nonce or card["approval_nonce"],
        },
    )


def test_plan_card_renders_stored_plan_not_model_text(stack):
    plan = _preview(stack)
    response = stack["side"].get(f"/plans/{plan['plan_id']}")
    assert response.status_code == 200
    card = response.json()
    assert card["kind"] == "plan" and card["state"] == "pending"
    assert card["plan_sha256"] == plan["plan_sha256"]
    assert card["stages"] == [s["id"] for s in plan["plan"]["stages"]]
    assert card["inputs"] == "synthetic"
    assert card["can_approve"] is True and len(card["approval_nonce"]) == 64
    assert card["paper_approval"] == "paper_approval_terminal_only"
    stored = _rows(
        stack["store"],
        "SELECT nonce_sha256 FROM story_plans WHERE plan_id = ?",
        plan["plan_id"],
    )
    assert stored and stored[0][0] and stored[0][0] != card["approval_nonce"]


def test_approve_via_sidecar_once_then_already_approved(stack):
    card = stack["side"].get(f"/plans/{_preview(stack)['plan_id']}").json()
    first, second = _approve(stack, card), _approve(stack, card)
    assert (first.status_code, first.json()["result"]) == (200, "approved")
    assert first.json()["card"]["state"] == "approved"
    assert first.json()["card"]["approval_nonce"] is None
    assert (second.status_code, second.json()["result"]) == (200, "already_approved")
    rows = _rows(
        stack["store"],
        "SELECT state, approved_at FROM story_plans WHERE plan_id = ?",
        card["plan_id"],
    )
    assert len(rows) == 1 and rows[0][0] == "approved" and rows[0][1]
    again = stack["side"].get(f"/plans/{card['plan_id']}").json()
    assert again["state"] == "approved" and again["approval_nonce"] is None


@pytest.mark.parametrize(
    ("mutate", "status", "code"),
    [
        (lambda c: {**c, "approval_nonce": "b" * 64}, 403, "bad_nonce"),
        (lambda c: {**c, "plan_sha256": "f" * 64}, 409, "plan_superseded"),
        (lambda c: {**c, "plan_id": "plan_" + "e" * 32}, 404, "plan_not_found"),
    ],
)
def test_approve_maps_results_through_approve_status(stack, mutate, status, code):
    card = mutate(stack["side"].get(f"/plans/{_preview(stack)['plan_id']}").json())
    response = _approve(stack, card)
    assert (response.status_code, response.json()) == (status, {"error": code})
    assert not _rows(
        stack["store"], "SELECT 1 FROM story_plans WHERE state != 'pending'"
    )


def test_expired_plan_card_has_no_nonce_and_approve_410(stack):
    plan = _preview(stack)
    card = stack["side"].get(f"/plans/{plan['plan_id']}").json()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(stack["store"]) as connection:
        connection.execute("UPDATE story_plans SET expires_at = ?", (past,))
    response = _approve(stack, card)
    assert (response.status_code, response.json()) == (410, {"error": "plan_expired"})
    expired = stack["side"].get(f"/plans/{plan['plan_id']}").json()
    assert expired["state"] == "expired" and expired["approval_nonce"] is None


def test_no_sidecar_route_starts_a_workflow_or_approves_paper(stack):
    routes = {
        (method, route.path)
        for route in stack["side"].app.inner.routes
        for method in getattr(route, "methods", ())
    }
    posts = {path for method, path in routes if method == "POST"}
    assert posts == {"/plans/{plan_id}/approve"}
    plan = _preview(stack)
    for path in (f"/plans/{plan['plan_id']}/start", "/paper/approve"):
        assert stack["side"].post(path, json={}).status_code in (404, 405)
    assert not _rows(stack["store"], "SELECT 1 FROM story_runs")


def test_run_card_shows_run_job_artifact_ids_and_outcome(stack):
    card = stack["side"].get(f"/plans/{_preview(stack)['plan_id']}").json()
    assert _approve(stack, card).status_code == 200
    started = (
        stack["story"].post(f"/api/v1/story/plans/{card['plan_id']}/start", json={})
    ).json()
    before = stack["side"].get(f"/runs/{started['run_id']}").json()
    assert before["outcome"] != "succeeded" and before["ok"] is False
    assert [j["job_id"] for j in before["jobs"]] == [started["job_id"]]
    stack["worker"].run_once()
    after = stack["side"].get(f"/runs/{started['run_id']}").json()
    assert after["outcome"] == "succeeded" and after["ok"] and after["terminal"]
    assert after["plan_id"] == card["plan_id"] and after["workflow_id"] == WID
    assert after["jobs"] == [{"job_id": started["job_id"], "status": "succeeded"}]
    job_rows = _rows(
        stack["jobs_db"],
        "SELECT status FROM job_run WHERE run_id = ?",
        started["job_id"],
    )
    assert job_rows == [("succeeded",)]
    stored = _rows(
        stack["store"],
        "SELECT record FROM story_artifacts WHERE run_id = ?",
        started["run_id"],
    )
    records = [json.loads(r[0]) for r in stored]
    expected = sorted(
        (r["ref"]["artifact_id"], r["ref"]["sha256"], r["kind"]) for r in records
    )
    shown = sorted(
        (a["artifact_id"], a["sha256"], a["kind"]) for a in after["artifacts"]
    )
    assert shown == expected
    assert (
        sum(r["name"].endswith("_table") or r["kind"] == "table" for r in records) >= 3
    )
    assert after["paper_approval"] == "paper_approval_terminal_only"


def test_run_and_plan_unavailable_states(stack, tmp_path):
    assert stack["side"].get("/runs/" + "a" * 32).json() == {"error": "run_unavailable"}
    assert stack["side"].get("/runs/not-a-run").status_code == 404
    assert stack["side"].get("/plans/plan_" + "c" * 32).status_code == 404
    token = stack["side"].headers[security.TOKEN_HEADER]
    path = tmp_path / "t.token"
    path.write_text(token, encoding="utf-8")
    bare = sidecar.create_app(
        sidecar.SidecarConfig(port=PORT, principal=PRINCIPAL, token_file=path)
    )
    with TestClient(bare, base_url=f"http://127.0.0.1:{PORT}") as client:
        client.headers[security.TOKEN_HEADER] = token
        plan = client.get("/plans/plan_" + "c" * 32)
        run = client.get("/runs/" + "a" * 32)
        flows = client.get("/workflows")
    assert (plan.status_code, plan.json()["code"]) == (503, "plan_store_unavailable")
    assert (run.status_code, run.json()["code"]) == (503, "run_unavailable")
    assert (flows.status_code, flows.json()["code"]) == (503, "plan_store_unavailable")


def test_workflows_list_prefills_only(stack):
    body = stack["side"].get("/workflows").json()
    assert body["auto_send"] is False
    ids = [w["workflow_id"] for w in body["workflows"]]
    assert WID in ids
    assert all("story_plan_preview" in w["prompt"] for w in body["workflows"])


def test_backend_principal_must_match_sidecar(stack, tmp_path):
    other = StoryBackend(
        principal="hermes#ffffffffffffffff",
        store_path=stack["store"],
        artifact_root=tmp_path / "a",
        service=JobService(
            store=SqliteJobStore(tmp_path / "j.db"),
            registry=JobRegistry(get_job_definitions()),
        ),
    )
    with pytest.raises(ValueError, match="principal_mismatch"):
        sidecar.create_app(
            sidecar.SidecarConfig(
                port=PORT, principal=PRINCIPAL, token_file=None, backend=other
            )
        )


def _record(stages: dict[str, str]) -> RunRecord:
    now = datetime.now(timezone.utc)
    return RunRecord(
        run_id="a" * 32,
        story_id=f"workflow:{WID}",
        manifest_version="v",
        provider_mode="fixture",
        state_version=0,
        stage_status=stages,
        state={},
        provenance={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("state", typing.get_args(OutcomeState))
def test_cards_map_every_outcome_state(state):
    outcome = derive_outcome(
        _record({"s": "succeeded"}),
        optional={},
        workflow_current=True,
        jobs=[],
        requests=[],
        artifacts_valid=True,
        now=datetime.now(timezone.utc),
    ).model_copy(update={"outcome": state, "reason": "free text from somewhere"})
    card = cards.run_card(
        run_id="a" * 32,
        plan_id=None,
        workflow_id=None,
        outcome=outcome,
        jobs=[],
        artifacts=[],
    )
    assert card["outcome"] == state
    assert card["ok"] is (state == "succeeded")
    assert card["terminal"] is (state in cards.TERMINAL_OUTCOMES)
    assert card["reason"] == "unspecified"
    missing = cards.run_card(
        run_id="a" * 32,
        plan_id=None,
        workflow_id=None,
        outcome=None,
        jobs=[],
        artifacts=[],
    )
    assert (missing["code"], missing["ok"]) == ("outcome_unavailable", False)


def test_worker_unavailable_after_queue_timeout(stack):
    """A job queued > 60 s with no worker heartbeat reads ``worker_unavailable``."""
    card = stack["side"].get(f"/plans/{_preview(stack)['plan_id']}").json()
    assert _approve(stack, card).status_code == 200
    started = (
        stack["story"].post(f"/api/v1/story/plans/{card['plan_id']}/start", json={})
    ).json()
    (created,) = _rows(
        stack["jobs_db"],
        "SELECT COALESCE(available_at, created_at) FROM job_run WHERE run_id = ?",
        started["job_id"],
    )
    queued_at = datetime.fromisoformat(created[0])
    path = f"/runs/{started['run_id']}"
    stack["clock"].append(queued_at + timedelta(seconds=59))
    fresh = stack["side"].get(path).json()
    assert fresh["state"] == "available" and "code" not in fresh
    stack["clock"][0] = queued_at + timedelta(seconds=61)
    stalled = stack["side"].get(path).json()
    assert (stalled["state"], stalled["code"]) == ("unavailable", "worker_unavailable")
    assert stalled["ok"] is False and stalled["terminal"] is False
    assert stalled["jobs"] == [{"job_id": started["job_id"], "status": "queued"}]
    # A worker that beats (busy, not dead) clears it; the job is still queued.
    stack["service"].heartbeat("busy-worker", queued_at + timedelta(seconds=60))
    alive = stack["side"].get(path).json()
    assert alive["state"] == "available" and "code" not in alive
    # Once the heartbeat is stale too, the card reads unavailable again.
    stack["clock"][0] = queued_at + timedelta(seconds=125)
    assert stack["side"].get(path).json()["code"] == "worker_unavailable"
    # A terminal run never reads worker_unavailable.
    stack["clock"].clear()
    stack["worker"].run_once()
    done = stack["side"].get(path).json()
    assert done["outcome"] == "succeeded" and done["state"] == "available"
