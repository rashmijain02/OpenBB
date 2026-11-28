"""Approval replay across expiry, changed arguments, drift and restart (#1341 T03).

``SIGNED_FIELDS`` are unchanged, so outstanding approvals stay valid; any of
expired / superseded / withdrawn, or changed arguments, needs a new prepare and
a new human decision. Real composed apps, real paper engine, synthetic data.
"""

# pylint: disable=redefined-outer-name,unused-import

import sqlite3
from datetime import timedelta

from openbb_mcp_server.story_adapters import paper, paper_approve

from .test_cancel_semantics import BACKTEST, BATCH, BINDING, env  # noqa: F401
from .test_run_outcome import _restart


def _prepare(env, sandbox_id, operation_id, arguments=None):
    response = env.client.post(
        f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
        json={
            "operation_id": operation_id,
            "action": "submit_batch",
            "arguments": arguments or BATCH,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(env, request_id):
    return paper_approve.approve_request(
        request_id, db_path=env.store, confirm=lambda _summary: True
    )


def _apply(client, request_id, approval, arguments=None):
    return client.post(
        f"/api/v1/story/paper/requests/{request_id}/apply",
        json={
            "approval": approval,
            "action": "submit_batch",
            "arguments": arguments or BATCH,
        },
    )


def _expire(monkeypatch):
    real_now = paper._now  # pylint: disable=protected-access
    monkeypatch.setattr(
        paper, "_now", lambda: real_now() + paper.APPROVAL_TTL + timedelta(seconds=1)
    )


def test_expired_request_reads_expired_and_reprepare_creates_new_request_and_nonce(
    env, monkeypatch
):
    """An expired request reads expired; a re-prepare is a new request and nonce."""
    run_id = env.new_run(BINDING)
    sandbox_id, first_id = env.sandbox_and_request(run_id, "prep-1")
    first = env.client.get(f"/api/v1/story/paper/requests/{first_id}").json()
    assert first["status"] == "pending"
    _expire(monkeypatch)
    seen = env.client.get(f"/api/v1/story/paper/requests/{first_id}").json()
    assert seen["status"] == "expired"
    second = _prepare(env, sandbox_id, "prep-2")
    assert second["request_id"] != first_id
    assert second["nonce"] != first["nonce"]
    assert second["status"] == "pending"


def test_old_approval_cannot_apply_new_request(env, monkeypatch):
    """The approval of the expired request does not carry to the new one."""
    run_id = env.new_run(BINDING)
    sandbox_id, first_id = env.sandbox_and_request(run_id, "prep-1")
    old_approval = _approve(env, first_id)
    _expire(monkeypatch)
    assert _apply(env.client, first_id, old_approval).status_code == 410
    second = _prepare(env, sandbox_id, "prep-2")
    refused = _apply(env.client, second["request_id"], old_approval)
    assert refused.status_code == 403, refused.text


def test_changed_args_reprepare_is_new_request(env):
    """Changed arguments are a new request; the old approval cannot apply them."""
    run_id = env.new_run(BINDING)
    sandbox_id, first_id = env.sandbox_and_request(run_id, "prep-1")
    approval = _approve(env, first_id)
    changed = {**BATCH, "plan_id": "plan-2"}
    second = _prepare(env, sandbox_id, "prep-2", changed)
    assert second["request_id"] != first_id
    assert _apply(env.client, second["request_id"], approval, changed).status_code == 403
    assert _apply(env.client, first_id, approval, changed).status_code == 409


def test_drift_marks_request_superseded(env, tmp_path):
    """Apply after workflow drift refuses and marks the request superseded."""
    run_id = env.new_run(BINDING)
    _, request_id = env.sandbox_and_request(run_id, "prep-1")
    approval = _approve(env, request_id)
    path = tmp_path / "workflows" / "synthetic.concentration_review.workflow.json"
    path.write_text(path.read_text("utf-8").replace("Synthetic", "Drifted", 1), "utf-8")
    client = _restart(env, tmp_path)
    refused = _apply(client, request_id, approval)
    assert refused.status_code == 409
    assert "workflow_changed" in refused.text
    seen = client.get(f"/api/v1/story/paper/requests/{request_id}").json()
    assert seen["status"] == "superseded"
    with sqlite3.connect(env.store) as connection:
        reason = connection.execute(
            "SELECT superseded_reason FROM story_paper_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()[0]
    assert reason == "workflow_changed"
    # The approval stays signed over unchanged fields but can never apply now.
    assert _apply(client, request_id, approval).status_code == 409
    outcome = client.get(f"/api/v1/story/runs/{run_id}/outcome").json()
    assert outcome["outcome"] == "blocked"


def test_fresh_app_over_same_store_returns_same_job_and_applied_result(env, tmp_path):
    """After a restart the same delivery keys return the first outcomes."""
    run_id = env.new_run(BINDING)
    job = env.submit(run_id, "op-1")
    _, request_id = env.sandbox_and_request(run_id, "prep-1")
    approval = _approve(env, request_id)
    applied = _apply(env.client, request_id, approval)
    assert applied.status_code == 200, applied.text
    client = _restart(env, tmp_path)
    again = client.post(
        f"/api/v1/story/runs/{run_id}/jobs",
        json={"operation_id": "op-1", "kind": "story.backtest", "payload": BACKTEST},
    )
    assert again.status_code == 202, again.text
    assert again.json()["job_id"] == job["job_id"]
    replayed = _apply(client, request_id, approval)
    assert replayed.status_code == 200
    assert replayed.json()["result"] == applied.json()["result"]
    with sqlite3.connect(env.store) as connection:
        jobs = connection.execute(
            "SELECT COUNT(*) FROM story_jobs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        requests = connection.execute(
            "SELECT COUNT(*) FROM story_paper_requests"
            " WHERE run_id = ? AND status = 'applied'",
            (run_id,),
        ).fetchone()[0]
    assert (jobs, requests) == (1, 1)
