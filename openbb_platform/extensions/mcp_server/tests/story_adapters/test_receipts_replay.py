"""Logical-operation receipts: one outcome per logical operation (#1341 T01).

A Hermes model that re-issues a story mutation with a new ``operation_id``
(after an "outcome uncertain" reply) must get the first outcome back on a
Hermes-bound run. Legacy (unbound) runs keep today's semantics, except that an
identical artifact re-delivery now returns the first record (decision D1).
Synthetic data only; every store lives in ``tmp_path``.
"""

# pylint: disable=redefined-outer-name,protected-access

import importlib.util
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_core.api.dependency.jobs import get_job_service
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.sqlite_store import SqliteJobStore
from openbb_core.app.jobs.worker import JobWorker
from openbb_core.app.service.job_service import JobService
from openbb_mcp_server.story_adapters import paper, paper_approve, story_job_kinds
from openbb_mcp_server.story_adapters.artifacts import compose_story_artifacts_app
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app
from openbb_mcp_server.story_adapters.paper import compose_story_paper_app
from openbb_mcp_server.story_adapters.receipts import logical_operation_key
from openbb_mcp_server.story_adapters.registry import compose_story_registry_app
from openbb_mcp_server.story_adapters.story_job_kinds import get_job_definitions

AGENTS = Path(__file__).resolve().parents[3] / "agents" / "openbb_agents"
MANIFESTS = AGENTS / "notebook_guide" / "stories"
BACKTEST = {
    "config": {
        "strategy": "buy_and_hold",
        "universe": ["AAA", "BBB"],
        "start": "2023-01-03",
        "end": "2024-12-31",
    },
    "strategy_params": {"symbols": ["AAA", "BBB"]},
}
FAKE_BACKTEST = {
    "engine_used": "vector",
    "equity_curve": [{"value": 100.0}, {"value": 104.0}],
    "trades": [],
    "metrics": {"cagr": 0.04, "sharpe": 1.25, "max_drawdown": -0.1, "sortino": None},
}
TABLE = {
    "name": "positions",
    "format": "csv",
    "table": {"columns": ["symbol", "weight"], "rows": [["AAA", 0.5]]},
}


def _paper_constants():
    path = Path(__file__).with_name("test_paper.py")
    spec = importlib.util.spec_from_file_location("_paper_constants", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KEY, module.BATCH


KEY, BATCH = _paper_constants()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Registry, artifacts, jobs and paper over one run store and one job store."""
    store = tmp_path / "runs.sqlite"
    root = tmp_path / "artifacts"
    jobs_db = tmp_path / "jobs.db"
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(store))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv(paper.APPROVAL_KEY_ENV, KEY)
    monkeypatch.setattr(story_job_kinds, "run_backtest", lambda payload: FAKE_BACKTEST)
    service = JobService(
        store=SqliteJobStore(jobs_db), registry=JobRegistry(get_job_definitions())
    )
    common = {"principal": "alice", "store_path": store}
    app = compose_story_registry_app(FastAPI(), manifest_dir=MANIFESTS, **common)
    app = compose_story_artifacts_app(app, artifact_root=root, **common)
    app = compose_story_jobs_app(app, **common)
    app = compose_story_paper_app(app, paper_root=tmp_path / "paper", **common)
    app.dependency_overrides[get_job_service] = lambda: service
    client = TestClient(app)

    def new_run(bound=True, key="hs-" + "1" * 32, story_id="techtrade/08"):
        body = {"story_id": story_id}
        if bound:
            body["binding"] = {
                "harness": "hermes",
                "binding_key": key,
                "origin": "interactive",
            }
        response = client.post("/api/v1/story/runs", json=body)
        assert response.status_code == 200, response.text
        return response.json()["run_id"]

    def submit(run_id, operation_id, payload=None, raw=False):
        response = client.post(
            f"/api/v1/story/runs/{run_id}/jobs",
            json={
                "operation_id": operation_id,
                "kind": "story.backtest",
                "payload": BACKTEST if payload is None else payload,
            },
        )
        if raw:
            return response
        assert response.status_code == 202, response.text
        return SimpleNamespace(**response.json())

    def table(run_id, body=None):
        return client.post(
            f"/api/v1/story/runs/{run_id}/artifacts/table", json=body or TABLE
        )

    def sandbox(run_id):
        response = client.post(
            f"/api/v1/story/runs/{run_id}/paper/sandboxes",
            json={"engine": "techtrade", "starting_cash": "100000"},
        )
        assert response.status_code == 200, response.text
        return response.json()["sandbox_id"]

    def prepare(sandbox_id, operation_id, arguments=None, action="submit_batch"):
        response = client.post(
            f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
            json={
                "operation_id": operation_id,
                "action": action,
                "arguments": BATCH if arguments is None else arguments,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def apply(request_id, arguments=None, action="submit_batch", token=None):
        token = token or paper_approve.approve_request(
            request_id, db_path=store, confirm=lambda summary: True
        )
        env.last_token = token
        return client.post(
            f"/api/v1/story/paper/requests/{request_id}/apply",
            json={
                "approval": token,
                "action": action,
                "arguments": BATCH if arguments is None else arguments,
            },
        )

    def count(sql, database=store):
        with sqlite3.connect(database) as connection:
            return connection.execute(sql).fetchone()[0]

    env = SimpleNamespace(
        client=client,
        service=service,
        worker=JobWorker(service=service, worker_id="test-worker"),
        store=store,
        root=root,
        jobs_db=jobs_db,
        new_run=new_run,
        submit=submit,
        table=table,
        sandbox=sandbox,
        prepare=prepare,
        apply=apply,
        count=count,
    )
    return env


# --- Jobs -------------------------------------------------------------------


def test_bound_resubmit_with_new_operation_id_returns_first_job(env):
    """Bound resubmit with new operation id returns first job."""
    run_id = env.new_run()
    first = env.submit(run_id, "op-first")
    second = env.submit(run_id, "op-reissued")
    assert second.job_id == first.job_id
    assert first.replay_of is None
    assert second.replay_of == "op-first"
    assert env.count("SELECT COUNT(*) FROM job_run", env.jobs_db) == 1


def test_same_delivery_key_on_bound_run_is_still_one_job(env):
    """Same delivery key on bound run is still one job."""
    run_id = env.new_run()
    first = env.submit(run_id, "op-first")
    again = env.submit(run_id, "op-first")
    assert again.job_id == first.job_id
    assert env.count("SELECT COUNT(*) FROM job_run", env.jobs_db) == 1


@pytest.mark.parametrize("ending", ["failed", "cancelled"])
def test_failed_job_allows_a_new_job_for_same_lok(env, monkeypatch, ending):
    """Failed job allows a new job for same lok."""
    run_id = env.new_run()
    first = env.submit(run_id, "op-first")
    if ending == "failed":

        def boom(payload):
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr(story_job_kinds, "run_backtest", boom)
        assert env.worker.run_once().status == "failed"
    else:
        env.service.cancel(first.job_id)
    second = env.submit(run_id, "op-retry")
    assert second.job_id != first.job_id
    assert second.replay_of is None
    assert env.count("SELECT COUNT(*) FROM job_run", env.jobs_db) == 2
    # The new job is now the logical outcome: a further re-issue replays it.
    third = env.submit(run_id, "op-third")
    assert third.job_id == second.job_id
    assert third.replay_of == "op-retry"


def test_bound_resubmit_with_different_payload_is_a_new_job(env):
    """Bound resubmit with different payload is a new job."""
    run_id = env.new_run()
    first = env.submit(run_id, "op-first")
    other = {**BACKTEST, "strategy_params": {"symbols": ["AAA"]}}
    second = env.submit(run_id, "op-other", payload=other)
    assert second.job_id != first.job_id


def test_legacy_run_keeps_one_job_per_operation_id(env):
    """Legacy run keeps one job per operation id."""
    run_id = env.new_run(bound=False)
    first = env.submit(run_id, "op-first")
    second = env.submit(run_id, "op-second")
    assert second.job_id != first.job_id
    assert second.replay_of is None
    assert env.count("SELECT COUNT(*) FROM job_run", env.jobs_db) == 2
    tables = env.count(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'story_receipts'"
    )
    assert tables == 0 or env.count("SELECT COUNT(*) FROM story_receipts") == 0


def test_bound_runs_do_not_share_receipts(env):
    """Bound runs do not share receipts."""
    first = env.submit(env.new_run(), "op-first")
    other_run = env.new_run(key="hs-" + "2" * 32)
    second = env.submit(other_run, "op-second")
    assert second.job_id != first.job_id


def test_receipt_records_digest_and_args_hash_not_values(env):
    """Receipt records digest and args hash not values."""
    run_id = env.new_run()
    env.submit(run_id, "op-first")
    env.submit(run_id, "op-reissued")
    with sqlite3.connect(env.store) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(r) for r in connection.execute("SELECT * FROM story_receipts")]
    assert len(rows) == 1
    row = rows[0]
    manifest_version = env.client.get(f"/api/v1/story/runs/{run_id}").json()[
        "manifest_version"
    ]
    assert row["workflow_ref"] == manifest_version
    assert len(row["args_sha256"]) == 64
    assert len(row["logical_key"]) == 64
    assert row["operation_id"] == "op-first"
    assert row["deliveries"] == 2
    text = json.dumps(row)
    for value in ("AAA", "BBB", "buy_and_hold", "2023-01-03", "symbols"):
        assert value not in text


# --- Logical key ------------------------------------------------------------


def _lok(**overrides):
    fields = {
        "tool": "story_job_submit",
        "run_id": "r1",
        "workflow_ref": "a" * 64,
        "stage_id": "concentration",
        "args_sha256": "b" * 64,
    }
    fields.update(overrides)
    return logical_operation_key(**fields)


def test_lok_differs_when_workflow_digest_differs():
    """Lok differs when workflow digest differs."""
    assert _lok() == _lok()
    assert _lok(workflow_ref="c" * 64) != _lok()


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool", "story_paper_prepare"),
        ("run_id", "r2"),
        ("stage_id", None),
        ("args_sha256", "d" * 64),
    ],
)
def test_lok_binds_every_field(field, value):
    """Lok binds every field."""
    assert _lok(**{field: value}) != _lok()


# --- Artifacts --------------------------------------------------------------


@pytest.mark.parametrize("bound", [True, False])
def test_identical_artifact_redelivery_returns_first_record(env, bound):
    """Identical artifact redelivery returns first record."""
    run_id = env.new_run(bound=bound)
    first = env.table(run_id)
    second = env.table(run_id)
    assert first.status_code == second.status_code == 200, second.text
    assert second.json() == first.json()
    assert len(list(env.root.rglob("*.csv"))) == 1


def test_changed_bytes_same_name_still_409(env):
    """Changed bytes same name still 409."""
    run_id = env.new_run(bound=False)
    assert env.table(run_id).status_code == 200
    changed = {**TABLE, "table": {"columns": ["symbol"], "rows": [["CCC"]]}}
    assert env.table(run_id, changed).status_code == 409
    assert len(list(env.root.rglob("*.csv"))) == 1


@pytest.mark.parametrize(
    "change", [{"stage_id": "s01"}, {"retention_days": 7}, {"format": "json"}]
)
def test_same_bytes_other_metadata_same_name_still_409(env, change):
    """Same bytes other metadata same name still 409."""
    run_id = env.new_run(bound=False)
    stages = env.client.get(f"/api/v1/story/runs/{run_id}").json()["stage_status"]
    if "stage_id" in change:
        change = {"stage_id": sorted(stages)[0]}
    assert env.table(run_id).status_code == 200
    response = env.table(run_id, {**TABLE, **change})
    assert response.status_code == 409, response.text


def test_bound_artifact_reissue_under_new_name_returns_first_record(env):
    """Bound artifact reissue under new name returns first record."""
    run_id = env.new_run()
    first = env.table(run_id).json()
    second = env.table(run_id, {**TABLE, "name": "positions-retry"})
    assert second.status_code == 200, second.text
    assert second.json()["ref"]["artifact_id"] == first["ref"]["artifact_id"]
    assert len(list(env.root.rglob("*.csv"))) == 1


def test_legacy_artifact_new_name_is_a_new_record(env):
    """Legacy artifact new name is a new record."""
    run_id = env.new_run(bound=False)
    first = env.table(run_id).json()
    second = env.table(run_id, {**TABLE, "name": "positions-2"}).json()
    assert second["ref"]["artifact_id"] != first["ref"]["artifact_id"]


# --- Paper prepare ----------------------------------------------------------


def test_bound_reprepare_returns_pending_request(env):
    """Bound reprepare returns pending request."""
    sandbox_id = env.sandbox(env.new_run())
    first = env.prepare(sandbox_id, "prep-first")
    second = env.prepare(sandbox_id, "prep-reissued")
    assert second["request_id"] == first["request_id"]
    assert second["nonce"] == first["nonce"]
    assert second["replay_of"] == "prep-first"
    assert "replay_of" not in first
    assert env.count("SELECT COUNT(*) FROM story_paper_requests") == 1


def test_reprepare_after_apply_returns_applied_request_no_second_fill(env):
    """Reprepare after apply returns applied request no second fill."""
    sandbox_id = env.sandbox(env.new_run())
    first = env.prepare(sandbox_id, "prep-first")
    applied = env.apply(first["request_id"])
    assert applied.status_code == 200, applied.text
    again = env.prepare(sandbox_id, "prep-after-apply")
    assert again["request_id"] == first["request_id"]
    assert again["status"] == "applied"
    replayed = env.apply(again["request_id"], token=env.last_token)
    assert replayed.json() == applied.json()
    state = env.client.get(f"/api/v1/story/paper/sandboxes/{sandbox_id}").json()
    assert len(state["orders"]) == len(BATCH["tickets"])
    assert env.count("SELECT COUNT(*) FROM story_paper_requests") == 1


def test_bound_reprepare_after_expiry_is_a_new_request(env):
    """Bound reprepare after expiry is a new request."""
    sandbox_id = env.sandbox(env.new_run())
    first = env.prepare(sandbox_id, "prep-first")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(env.store) as connection:
        connection.execute("UPDATE story_paper_requests SET expires_at = ?", (past,))
    second = env.prepare(sandbox_id, "prep-new")
    assert second["request_id"] != first["request_id"]
    assert second["nonce"] != first["nonce"]
    assert "replay_of" not in second


def test_legacy_reprepare_with_new_operation_is_a_new_request(env):
    """Legacy reprepare with new operation is a new request."""
    sandbox_id = env.sandbox(env.new_run(bound=False))
    first = env.prepare(sandbox_id, "prep-first")
    second = env.prepare(sandbox_id, "prep-second")
    assert second["request_id"] != first["request_id"]


# --- Concurrency and re-prepare outcome (#1341 review fixes) ----------------


def _outcome(env, run_id):
    response = env.client.get(f"/api/v1/story/runs/{run_id}/outcome")
    assert response.status_code == 200, response.text
    return response.json()


def _checkpoint_all(env, run_id):
    stages = env.client.get(f"/api/v1/story/runs/{run_id}").json()["stage_status"]
    for stage_id in stages:
        version = env.client.get(f"/api/v1/story/runs/{run_id}").json()["state_version"]
        response = env.client.post(
            f"/api/v1/story/runs/{run_id}/checkpoint",
            json={
                "expected_version": version,
                "stage_id": stage_id,
                "status": "succeeded",
                "state": {"output_sha256": "b" * 64},
            },
        )
        assert response.status_code == 200, response.text


def _expire_all(env):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(env.store) as connection:
        connection.execute(
            "UPDATE story_paper_requests SET expires_at = ? WHERE status = 'pending'",
            (past,),
        )


def _interleave(monkeypatch, module, second):
    """Run ``second`` in a thread at the first ``uuid4`` call of ``module``.

    The first delivery has claimed its logical key and is about to create its
    row; the second delivery races it. The second gets up to two seconds to
    finish inside that window, which an unserialized prepare uses to insert
    its own row; a serialized one stays blocked until the first commits.
    """
    real = module.uuid.uuid4
    results: list = []
    threads: list = []

    def seam():
        if not threads:
            thread = threading.Thread(target=lambda: results.append(second()))
            threads.append(thread)
            thread.start()
            thread.join(2)
        return real()

    monkeypatch.setattr(module.uuid, "uuid4", seam)
    return results, threads


def _prepare_raw(env, sandbox_id, operation_id):
    return env.client.post(
        f"/api/v1/story/paper/sandboxes/{sandbox_id}/prepare",
        json={
            "operation_id": operation_id,
            "action": "submit_batch",
            "arguments": BATCH,
        },
    )


def test_concurrent_reprepare_creates_one_live_request(env, monkeypatch):
    """Two re-issued prepares racing on one logical key leave one pending row."""
    sandbox_id = env.sandbox(env.new_run())
    results, threads = _interleave(
        monkeypatch, paper, lambda: _prepare_raw(env, sandbox_id, "prep-b")
    )
    first = env.prepare(sandbox_id, "prep-a")
    threads[0].join(30)
    second = results[0]
    pending = env.count(
        "SELECT COUNT(*) FROM story_paper_requests WHERE status = 'pending'"
    )
    assert pending == 1
    assert second.status_code == 200, second.text
    assert second.json()["request_id"] == first["request_id"]
    assert second.json()["replay_of"] == "prep-a"


def test_claimed_receipt_without_owner_row_is_in_flight(env):
    """A claim whose owner row is missing is in flight: 409, never superseded."""
    sandbox_id = env.sandbox(env.new_run())
    env.prepare(sandbox_id, "prep-a")
    with sqlite3.connect(env.store) as connection:
        connection.execute("DELETE FROM story_paper_requests")
        connection.execute(
            "UPDATE story_receipts SET state = 'claimed', outcome_ref = NULL"
        )
    response = _prepare_raw(env, sandbox_id, "prep-b")
    assert response.status_code == 409, response.text
    assert "outcome_uncertain" in response.json()["detail"]
    assert env.count("SELECT COUNT(*) FROM story_paper_requests") == 0
    assert env.count("SELECT operation_id FROM story_receipts") == "prep-a"


def test_concurrent_job_resubmit_is_one_job(env, monkeypatch):
    """Two re-issued submits racing on one logical key enqueue one job."""
    from openbb_mcp_server.story_adapters import jobs as jobs_module

    run_id = env.new_run()
    real_claim = jobs_module.ReceiptLedger.claim
    results: list = []
    threads: list = []

    def claim(self, *args, **kwargs):
        receipt = real_claim(self, *args, **kwargs)
        if not threads:
            thread = threading.Thread(
                target=lambda: results.append(env.submit(run_id, "op-b", raw=True))
            )
            threads.append(thread)
            thread.start()
            thread.join(30)
        return receipt

    monkeypatch.setattr(jobs_module.ReceiptLedger, "claim", claim)
    first = env.submit(run_id, "op-a")
    second = results[0]
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] == first.job_id
    assert env.count("SELECT COUNT(*) FROM job_run", env.jobs_db) == 1


def test_concurrent_artifact_reissue_is_one_artifact(env, monkeypatch):
    """A re-issue racing an unfinished first write never writes a second copy."""
    from openbb_mcp_server.story_adapters import artifacts as artifacts_module

    run_id = env.new_run()
    retry_body = {**TABLE, "name": "positions-retry"}
    results, threads = _interleave(
        monkeypatch, artifacts_module, lambda: env.table(run_id, retry_body)
    )
    first = env.table(run_id)
    threads[0].join(30)
    assert first.status_code == 200, first.text
    racing = results[0]
    assert racing.status_code == 409, racing.text
    assert "outcome_uncertain" in racing.json()["detail"]
    assert len(list(env.root.rglob("*.csv"))) == 1
    retry = env.table(run_id, retry_body)
    assert retry.json()["ref"]["artifact_id"] == first.json()["ref"]["artifact_id"]


def test_reprepare_after_expiry_supersedes_old_and_run_completes(env):
    """The expired owner is superseded; applying R2 lets the run succeed."""
    run_id = env.new_run()
    sandbox_id = env.sandbox(run_id)
    first = env.prepare(sandbox_id, "prep-first")
    _expire_all(env)
    assert _outcome(env, run_id)["outcome"] == "needs_input"
    second = env.prepare(sandbox_id, "prep-new")
    with sqlite3.connect(env.store) as connection:
        row = connection.execute(
            "SELECT status, superseded_reason FROM story_paper_requests"
            " WHERE request_id = ?",
            (first["request_id"],),
        ).fetchone()
    assert row == ("superseded", "reprepared")
    assert env.apply(second["request_id"]).status_code == 200
    assert _outcome(env, run_id)["outcome"] != "needs_input"
    _checkpoint_all(env, run_id)
    assert _outcome(env, run_id)["outcome"] == "succeeded"


def test_changed_args_reprepare_after_expiry_does_not_strand_the_run(env):
    """A re-prepare with other arguments also retires the expired request."""
    run_id = env.new_run()
    sandbox_id = env.sandbox(run_id)
    env.prepare(sandbox_id, "prep-first")
    _expire_all(env)
    changed = json.loads(json.dumps(BATCH))
    changed["tickets"] = changed["tickets"][:1]
    second = env.prepare(sandbox_id, "prep-changed", arguments=changed)
    assert env.apply(second["request_id"], arguments=changed).status_code == 200
    _checkpoint_all(env, run_id)
    assert _outcome(env, run_id)["outcome"] == "succeeded"


@pytest.mark.parametrize("bound", [True, False])
def test_failed_paper_request_is_never_succeeded(env, bound):
    """A request that ended failed makes the run failed, not succeeded."""
    run_id = env.new_run(bound=bound)
    sandbox_id = env.sandbox(run_id)
    env.prepare(sandbox_id, "prep-first")
    with sqlite3.connect(env.store) as connection:
        connection.execute("UPDATE story_paper_requests SET status = 'failed'")
    _checkpoint_all(env, run_id)
    body = _outcome(env, run_id)
    assert (body["outcome"], body["reason"]) == ("failed", "request_failed")


def test_reprepare_after_failure_lets_the_run_succeed(env):
    """A failed request re-prepared and applied no longer fails the run."""
    run_id = env.new_run()
    sandbox_id = env.sandbox(run_id)
    env.prepare(sandbox_id, "prep-first")
    with sqlite3.connect(env.store) as connection:
        connection.execute("UPDATE story_paper_requests SET status = 'failed'")
    second = env.prepare(sandbox_id, "prep-retry")
    assert "replay_of" not in second
    assert env.apply(second["request_id"]).status_code == 200
    _checkpoint_all(env, run_id)
    assert _outcome(env, run_id)["outcome"] == "succeeded"


# --- Submit vs cancel (#1341 CODE-3) ----------------------------------------


def _request_cancel(env, run_id):
    from openbb_mcp_server.story_adapters.registry import RunStore

    assert RunStore(env.store).request_cancel("alice", run_id) is not None


def test_worker_refuses_a_job_of_a_cancelled_run(env):
    """A job claimed after its run was cancelled runs nothing and writes nothing."""
    run_id = env.new_run()
    job = env.submit(run_id, "op-first")
    _request_cancel(env, run_id)
    outcome = env.worker.run_once()
    assert outcome.run_id == job.job_id
    assert outcome.status != "succeeded"
    error = env.service.get_run(job.job_id).error_message or ""
    assert "run_cancelled" in error
    assert not list(env.root.rglob("*.json"))
    body = _outcome(env, run_id)
    assert body["outcome"] == "cancelled"


def test_submit_racing_a_cancel_leaves_no_queued_job(env, monkeypatch):
    """A cancel landing between the open check and enqueue cancels the job."""
    run_id = env.new_run()
    real = env.service.enqueue

    def enqueue(*args, **kwargs):
        job = real(*args, **kwargs)
        _request_cancel(env, run_id)
        return job

    monkeypatch.setattr(env.service, "enqueue", enqueue)
    response = env.submit(run_id, "op-first", raw=True)
    assert response.status_code == 409, response.text
    assert "run_cancelled" in response.json()["detail"]
    statuses = [
        row[0]
        for row in sqlite3.connect(env.jobs_db).execute("SELECT status FROM job_run")
    ]
    assert statuses == ["cancelled"]
