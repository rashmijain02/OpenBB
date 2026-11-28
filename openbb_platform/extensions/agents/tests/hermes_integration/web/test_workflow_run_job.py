"""Approved plan -> story.workflow_run job -> runner as the plan owner (#1342 T02).

Real stack over temporary stores: the story registry and job routes, the
durable job service and worker, and the in-process ``portfolio-ops`` server
the worker builds. The only seams are the three analytics provider calls,
which raise if reached, and the egress guard.
"""

# pylint: disable=redefined-outer-name,import-outside-toplevel,protected-access

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("openbb_portfolio_intel")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openbb_agents.hermes_integration.egress_guard import egress_guard  # noqa: E402
from openbb_agents.hermes_integration.workflow_runner import (  # noqa: E402
    SYNTHETIC_BASKET,
    SYNTHETIC_COMMODITY_TRUSTS,
)
from openbb_core.api.dependency.jobs import get_job_service  # noqa: E402
from openbb_core.app.jobs.registry import JobRegistry  # noqa: E402
from openbb_core.app.jobs.sqlite_store import SqliteJobStore  # noqa: E402
from openbb_core.app.jobs.worker import JobWorker  # noqa: E402
from openbb_core.app.service.job_service import JobService  # noqa: E402
from openbb_mcp_server.story_adapters import analytics, plans  # noqa: E402
from openbb_mcp_server.story_adapters.artifact_render import (  # noqa: E402
    Table,
    render_table_json,
)
from openbb_mcp_server.story_adapters.jobs import compose_story_jobs_app  # noqa: E402
from openbb_mcp_server.story_adapters.registry import (  # noqa: E402
    RunStore,
    WorkflowCatalog,
    compose_story_registry_app,
    default_workflow_dir,
)
from openbb_mcp_server.story_adapters.story_job_kinds import (  # noqa: E402
    get_job_definitions,
)

PRINCIPAL = "hermes#0123456789abcdef"
WID = "synthetic.basket_xray"
STAGES = (
    "effective",
    "concentration",
    "construction",
    "effective_table",
    "concentration_table",
    "construction_table",
    "checkpoint",
)


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """Plan routes, job service and worker over one temporary run store."""
    store, root = tmp_path / "runs.sqlite", tmp_path / "artifacts"
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(store))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root))
    provider_calls: list[str] = []

    def refuse(name):
        def seam(*args, **kwargs):
            provider_calls.append(name)
            raise AssertionError(f"provider seam {name} reached")

        return seam

    for name in ("_nport_rows", "_search_ticker", "_profile_sector"):
        monkeypatch.setattr(analytics, name, refuse(name))
    jobs_db = tmp_path / "jobs.db"
    service = JobService(
        store=SqliteJobStore(jobs_db), registry=JobRegistry(get_job_definitions())
    )
    app = compose_story_registry_app(FastAPI(), principal=PRINCIPAL, store_path=store)
    app = compose_story_jobs_app(
        app, principal=PRINCIPAL, store_path=store, artifact_root=root
    )
    app.dependency_overrides[get_job_service] = lambda: service
    return {
        "client": TestClient(app),
        "store": store,
        "jobs_db": jobs_db,
        "plans": plans.PlanStore(store),
        "worker": JobWorker(service=service, worker_id="test-worker"),
        "provider_calls": provider_calls,
    }


def _started(stack) -> dict:
    """Preview, approve as a human, start: the plan's one run and job."""
    client = stack["client"]
    plan = client.post("/api/v1/story/plans", json={"workflow_id": WID}).json()
    nonce = stack["plans"].issue_nonce(PRINCIPAL, plan["plan_id"])
    result, _ = plans.approve_plan(
        stack["plans"],
        WorkflowCatalog(default_workflow_dir()),
        PRINCIPAL,
        plan["plan_id"],
        plan_sha256=plan["plan_sha256"],
        nonce=nonce,
    )
    assert result == "approved"
    response = client.post(f"/api/v1/story/plans/{plan['plan_id']}/start", json={})
    assert response.status_code == 202, response.text
    return response.json()


def _rows(stack, sql, *args):
    with sqlite3.connect(stack["store"]) as connection:
        try:
            return connection.execute(sql, args).fetchall()
        except sqlite3.OperationalError:  # table never created: no rows
            return []


def _job_error(stack, job_id):
    with sqlite3.connect(stack["jobs_db"]) as connection:
        return connection.execute(
            "SELECT status, error_message FROM job_run WHERE run_id = ?", (job_id,)
        ).fetchone()


def _run_ok(stack, started):
    stack["worker"].run_once()
    status, message = _job_error(stack, started["job_id"])
    assert status == "succeeded", message


def _stage_status(stack, run_id):
    (record,) = _rows(stack, "SELECT record FROM story_runs WHERE run_id = ?", run_id)
    return json.loads(record[0])["stage_status"]


def _artifacts(stack, run_id) -> dict[str, str]:
    rows = _rows(
        stack, "SELECT name, record FROM story_artifacts WHERE run_id = ?", run_id
    )
    return {name: json.loads(record)["ref"]["sha256"] for name, record in rows}


def _expected_tables() -> dict[str, str]:
    """Recompute each table from the engines the notebooks call."""
    from openbb_portfolio_intel.analytics.basket_lookthrough import (
        concentration,
        construction_targets,
        effective_positions,
    )

    def no_lookthrough(symbol):
        raise AssertionError(f"look-through of {symbol}")

    effective = effective_positions(
        [{"symbol": s, "weight": w} for s, w in SYNTHETIC_BASKET],
        no_lookthrough,
        equity_etfs=set(),
        bond_etfs=set(),
        commodity_trusts=set(SYNTHETIC_COMMODITY_TRUSTS),
    ).effective
    ranked = sorted(effective.items(), key=lambda kv: -kv[1])
    metrics = concentration(effective, kill_shot_drop=0.20).__dict__
    targets = construction_targets(
        dict(ranked), max_single_name=0.06, top5_cap=0.35, band_abs=0.015
    ).targets
    columns = ["name", "current", "target", "band_lo", "band_hi", "status"]
    tables = {
        "effective_table": Table(
            columns=["key", "weight"], rows=[[k, w] for k, w in ranked]
        ),
        "concentration_table": Table(
            columns=["metric", "value"], rows=[[k, metrics[k]] for k in sorted(metrics)]
        ),
        "construction_table": Table(
            columns=columns,
            rows=[[k] + [v[c] for c in columns[1:]] for k, v in targets.items()],
        ),
    }
    return {
        name: hashlib.sha256(render_table_json(table)).hexdigest()
        for name, table in tables.items()
    }


def test_basket_xray_admitted_with_live_pins():
    """The shipped workflow is admitted against live schema pins."""
    from openbb_agents.hermes_integration.admission import admit_workflow
    from openbb_agents.hermes_integration.workflow_admit import live_tool_hashes

    document = json.loads(
        (Path(default_workflow_dir()) / f"{WID}.workflow.json").read_text("utf-8")
    )
    admission = admit_workflow(document, live_tools=asyncio.run(live_tool_hashes()))
    assert admission.admitted, admission.rejections
    assert WorkflowCatalog(default_workflow_dir()).digest(WID) == (
        admission.workflow_manifest_sha256
    )


def test_basket_xray_runs_effective_concentration_construction_and_writes_tables(
    stack,
):
    """The worker resumes the plan run; each table equals the engine output."""
    started = _started(stack)
    _run_ok(stack, started)
    # The worker resumed the plan's own run: one run, every stage succeeded.
    assert len(_rows(stack, "SELECT run_id FROM story_runs")) == 1
    assert _stage_status(stack, started["run_id"]) == dict.fromkeys(STAGES, "succeeded")
    assert _artifacts(stack, started["run_id"]) == {
        **_expected_tables(),
        **{
            name: sha
            for name, sha in _artifacts(stack, started["run_id"]).items()
            if name.startswith("story.workflow_run-")
        },
    }
    assert len(_artifacts(stack, started["run_id"])) == 4  # 3 tables + job result


def test_basket_xray_makes_zero_provider_calls(stack):
    """No provider seam and no non-loopback socket is touched."""
    started = _started(stack)
    with egress_guard() as refused:
        _run_ok(stack, started)
    assert refused == []
    assert stack["provider_calls"] == []
    assert set(_stage_status(stack, started["run_id"]).values()) == {"succeeded"}


@pytest.mark.parametrize("table", ["story_plans", "story_runs"])
def test_worker_principal_mismatch_fails_closed_and_runs_nothing(stack, table):
    """A plan or run owned by another principal fails closed."""
    started = _started(stack)
    with sqlite3.connect(stack["store"]) as connection:
        connection.execute(
            f"UPDATE {table} SET principal = 'mallory#ffff'"  # noqa: S608
        )
    assert stack["worker"].run_once().status == "failed"
    status, message = _job_error(stack, started["job_id"])
    assert status == "failed" and message.startswith("principal_mismatch")
    rows = _rows(stack, "SELECT record FROM story_runs")
    assert {s for r in rows for s in json.loads(r[0])["stage_status"].values()} == {
        "pending"
    }
    assert _artifacts(stack, started["run_id"]) == {}


def test_worker_cancelled_run_runs_nothing(stack):
    """A run cancelled before the claim runs no stage (#1341 guard)."""
    started = _started(stack)
    RunStore(stack["store"]).request_cancel(PRINCIPAL, started["run_id"])
    assert stack["worker"].run_once().status == "failed"
    _, message = _job_error(stack, started["job_id"])
    assert message.startswith("run_cancelled")
    assert set(_stage_status(stack, started["run_id"]).values()) == {"pending"}
    assert _artifacts(stack, started["run_id"]) == {}


class _Crash(Exception):
    """Simulated worker death after a durable checkpoint."""


def _crash_mid_run(stack, started, stage) -> None:
    """Run the plan's run as its owner and die once ``stage`` is checkpointed."""
    from openbb_agents.hermes_integration import workflow_runner

    document = json.loads(
        (Path(default_workflow_dir()) / f"{WID}.workflow.json").read_text("utf-8")
    )

    def hook(_run_id, stage_id):
        if stage_id == stage:
            raise _Crash(stage_id)

    with pytest.raises(_Crash):
        asyncio.run(
            workflow_runner._run_in_process(
                document,
                workflow_runner.synthetic_inputs(WID),
                "portfolio-ops",
                resume_run_id=started["run_id"],
                after_stage=hook,
                owner_principal=PRINCIPAL,
            )
        )


def test_resume_after_crash_recomputes_math_and_never_rewrites_tables(stack):
    """T03: a crashed run resumes; pure stages recompute, side effects stay once."""
    started = _started(stack)
    _crash_mid_run(stack, started, "effective_table")
    status = _stage_status(stack, started["run_id"])
    assert status["effective_table"] == "succeeded"
    assert status["concentration_table"] == "pending"
    first = _rows(
        stack,
        "SELECT artifact_id FROM story_artifacts WHERE run_id = ? AND name = ?",
        started["run_id"],
        "effective_table",
    )
    _run_ok(stack, started)  # the queued job resumes the same run
    assert len(_rows(stack, "SELECT run_id FROM story_runs")) == 1
    assert _stage_status(stack, started["run_id"]) == dict.fromkeys(STAGES, "succeeded")
    tables = {
        k: v
        for k, v in _artifacts(stack, started["run_id"]).items()
        if not k.startswith("story.workflow_run-")
    }
    assert tables == _expected_tables()
    again = _rows(
        stack,
        "SELECT artifact_id FROM story_artifacts WHERE run_id = ? AND name = ?",
        started["run_id"],
        "effective_table",
    )
    assert again == first and len(first) == 1


def test_resume_recomputed_hash_mismatch_fails_the_stage(stack, monkeypatch):
    """A pure stage whose recomputation differs from its checkpoint fails closed."""
    from openbb_agents.hermes_integration import workflow_runner

    started = _started(stack)
    _crash_mid_run(stack, started, "concentration")
    original = workflow_runner._effective_args

    def drifted(ctx):
        args = original(ctx)
        args["basket"] = args["basket"][:-1]
        return args

    monkeypatch.setitem(
        workflow_runner._ARGUMENTS, "story_basket_effective_positions", drifted
    )
    assert stack["worker"].run_once().status == "failed"
    _, message = _job_error(stack, started["job_id"])
    assert "effective: resume_output_mismatch" in message
    assert _artifacts(stack, started["run_id"]) == {}
