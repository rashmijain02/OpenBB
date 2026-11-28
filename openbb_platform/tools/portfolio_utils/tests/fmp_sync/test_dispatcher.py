"""Dispatcher: budgets, deadlines, cancellation and sanitized outcomes (#1344-T02).

No MySQL and no network: the session probe uses a fake connection and the FMP
transport is an injected inner ``Session.send`` that returns built responses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from portfolio_utils.fmp_sync import locking
from portfolio_utils.fmp_sync.budget import REFUSED_PREFIX
from portfolio_utils.fmp_sync.dispatcher import run_prices
from portfolio_utils.fmp_sync.outcome import EXIT_CODES, FmpSyncOutcome, Outcome, utcnow
from pydantic import ValidationError

from .conftest import DISPOSABLE_DB
from .test_admission import FakeConn, world  # noqa: F401  (fixture)
from .test_budget import FMP_URL, Clock, response
from .test_locking import holder, state_root  # noqa: F401  (fixtures)

FIVE = {"symbols": ("AAA", "BBB", "CCC", "DDD")}  # + benchmark SPY = 5
LIMITS = {"per_run": 50, "per_minute": 50, "per_day": 500, "bytes_per_day": 10**8}


def _state() -> Path:
    return Path(os.environ["FMP_SYNC_STATE_ROOT"])


def gapped_fetch(symbol, **_kwargs):
    """A gapped symbol: one real ``requests.get`` through the guarded Session.send."""
    resp = requests.get(FMP_URL, params={"symbol": symbol}, timeout=120)
    resp.raise_for_status()
    return {
        "rows": 1,
        "first": "2020-01-01",
        "last": "2020-01-02",
        "cache_tag": "FETCH",
    }


@pytest.fixture
def harness(world, monkeypatch):  # noqa: F811
    make, admit_kwargs = world
    mono, wall = Clock(0.0), Clock()
    h = SimpleNamespace(mono=mono, wall=wall, sent=[], holidays=[], probes=[])
    h.responses = lambda: response()

    def inner_send(_session, request, **kwargs):
        h.sent.append((request.url, kwargs))
        return h.responses()

    def connect():
        h.probes.append(1)
        return FakeConn(DISPOSABLE_DB)

    def holiday(start, end, database):
        h.holidays.append((start, end, database, locking.lock_status(DISPOSABLE_DB)))

    def run(mode="execute", *, limits=LIMITS, label="acct", map_kwargs=None, **kwargs):
        mk = dict(map_kwargs or {})
        if limits is not None:
            mk["limits"] = limits
        dmap = make(account_label=label, **mk)
        defaults = {
            "admit_kwargs": {**admit_kwargs, "connect_fn": connect},
            "fetch_one_fn": gapped_fetch,
            "api_key_resolver": lambda: "k",
            "holiday_fn": holiday,
            "readiness_fn": lambda symbols, database=None: {
                "target_date": "2026-01-02"
            },
            "inner_send": inner_send,
            "clock": mono,
            "now_fn": wall,
        }
        defaults.update(kwargs)
        return run_prices(dmap, mode=mode, **defaults)

    h.run = run
    h.inner_send = inner_send
    h.admit_kwargs = {**admit_kwargs, "connect_fn": connect}
    h.dmap_make = make
    return h


def _run_file(outcome: FmpSyncOutcome) -> dict:
    return json.loads(
        (_state() / "runs" / f"{outcome.run_id}.json").read_text(encoding="utf-8")
    )


def test_execute_happy_path(harness):
    out = harness.run()
    assert out.outcome is Outcome.OK and out.exit_code == 0
    assert out.counts.success == 3 and out.counts.failed == 0
    assert out.budget.sent == 3 and len(harness.sent) == 3
    assert out.data_status == "UNVALIDATED" and out.db_category == "expected"
    assert harness.probes == [1]
    # D2: holiday upsert through next year, under the lock, before the warm
    start, end, database, lock_state = harness.holidays[0]
    assert end >= utcnow().year + 1 and database == DISPOSABLE_DB
    assert lock_state == "held"
    run = _run_file(out)
    assert sorted(run["symbols"]["success"]) == ["AAA", "BBB", "SPY"]
    assert locking.lock_status(DISPOSABLE_DB) == "free"


def test_dry_run_no_holiday_no_sockets_no_budget(harness):
    out = harness.run("dry_run", limits=None)
    assert out.outcome is Outcome.OK and out.exit_code == 0
    assert out.budget.sent == 0 and harness.sent == [] and harness.holidays == []
    assert harness.probes == []  # no session probe in dry-run
    assert not (_state() / "budget").exists()
    assert (_state() / "runs" / f"{out.run_id}.json").exists()


def test_missing_limits_blocks_execute(harness):
    out = harness.run(limits=None)
    assert out.outcome is Outcome.BLOCKED_POLICY and out.exit_code == 40
    assert "LIMITS_MISSING" in out.findings
    assert harness.probes == [] and harness.holidays == [] and harness.sent == []
    assert not list(_state().glob("*.lock"))
    bad = harness.run(limits={"per_run": 1})
    assert "LIMITS_INVALID" in bad.findings and bad.exit_code == 40


def test_admission_block_maps_outcome(harness):
    out = harness.run(map_kwargs={"target": "openbb_fmp_cache_test"})
    assert out.outcome is Outcome.BLOCKED_DATABASE and out.exit_code == 40
    assert out.failed_layer == "database"
    assert harness.probes == [] and harness.holidays == [] and harness.sent == []


def test_busy_lock_skips_before_admission(harness, holder):  # noqa: F811
    holder(DISPOSABLE_DB)
    out = harness.run()
    assert out.outcome is Outcome.SKIPPED_BUSY and out.exit_code == 10
    assert harness.probes == [] and harness.holidays == [] and harness.sent == []


def test_budget_blocks_before_socket(harness):
    out = harness.run(limits={**LIMITS, "per_run": 2}, map_kwargs=FIVE)
    assert out.outcome is Outcome.DEFERRED_QUOTA and out.exit_code == 10
    assert len(harness.sent) == 2 and out.budget.sent == 2 == out.budget.reserved
    assert out.counts.success == 2 and out.counts.failed == 0
    assert out.counts.deferred == 3
    run = _run_file(out)
    assert len(run["symbols"]["deferred"]) == 3 and run["symbols"]["failed"] == []


def test_429_defers_and_persists(harness):
    harness.responses = lambda: response(429, headers={"Retry-After": "90"})
    out = harness.run()
    assert out.outcome is Outcome.DEFERRED_RATE_LIMIT and out.exit_code == 10
    assert len(harness.sent) == 1 and out.counts.failed == 0
    assert out.counts.deferred == 3
    harness.responses = lambda: response()
    again = harness.run()  # still inside Retry-After
    assert again.outcome is Outcome.DEFERRED_RATE_LIMIT and len(harness.sent) == 1
    harness.wall.t += 91
    later = harness.run()
    assert later.outcome is Outcome.OK and len(harness.sent) == 4


def test_402_blocked_plan_exit_20(harness):
    harness.responses = lambda: response(402)
    out = harness.run()
    assert out.outcome is Outcome.BLOCKED_PLAN and out.exit_code == 20
    assert out.counts.failed == 0 and out.counts.deferred == 3
    assert len(harness.sent) == 1


def test_401_blocked_auth_layer(harness):
    harness.responses = lambda: response(401)
    out = harness.run()
    assert out.outcome is Outcome.BLOCKED_AUTH and out.failed_layer == "auth"


def test_egress_attempt_blocked_outcome(harness):
    def llm_fetch(symbol, **_kw):
        requests.get("http://127.0.0.1:4000/v1/chat/completions")

    out = harness.run(fetch_one_fn=llm_fetch)
    assert out.outcome is Outcome.BLOCKED_EGRESS and out.exit_code == 20
    assert out.failed_layer == "egress" and out.budget.denied == 1
    assert harness.sent == [] and out.budget.sent == 0


def test_deadline_cancels_between_symbols(harness):
    def slow(symbol, **kw):
        result = gapped_fetch(symbol, **kw)
        harness.mono.t += 400
        return result

    out = harness.run(fetch_one_fn=slow, deadline_s=900.0, map_kwargs=FIVE)
    assert out.outcome is Outcome.CANCELLED_DEADLINE and out.exit_code == 10
    assert out.counts.success == 3 and out.counts.deferred == 2


def test_cancel_file(harness):
    def cancelling(symbol, **kw):
        result = gapped_fetch(symbol, **kw)
        cancel = _state() / "cancel"
        cancel.mkdir(parents=True, exist_ok=True)
        (cancel / "rid-cancel").write_text("stop", encoding="utf-8")
        return result

    out = harness.run(fetch_one_fn=cancelling, run_id="rid-cancel")
    assert out.outcome is Outcome.CANCELLED and out.exit_code == 10
    assert out.counts.success == 1 and out.counts.deferred == 2


def test_partial_and_all_failed(harness):
    def flaky(symbol, **kw):
        if symbol == "BBB":
            raise ValueError("per-symbol failure text")
        return gapped_fetch(symbol, **kw)

    out = harness.run(fetch_one_fn=flaky)
    assert out.outcome is Outcome.PARTIAL and out.exit_code == 10
    assert out.counts.failed == 1 and _run_file(out)["symbols"]["failed"] == ["BBB"]

    def broken(symbol, **_kw):
        raise ValueError("nope")

    dead = harness.run(fetch_one_fn=broken)
    assert dead.outcome is Outcome.FAILED_INFRA and dead.exit_code == 30


def test_readiness_exception_becomes_finding(harness):
    def unavailable(symbols, database=None):
        raise RuntimeError("least-privilege user cannot COUNT")

    out = harness.run(readiness_fn=unavailable)
    assert out.outcome is Outcome.OK and "READINESS_UNAVAILABLE" in out.findings


def test_unexpected_error_is_generic(harness):
    def boom(start, end, database):
        raise RuntimeError("secret detail")

    out = harness.run(holiday_fn=boom)
    assert out.outcome is Outcome.FAILED_INFRA and out.exit_code == 30
    assert out.findings == ("UNEXPECTED_ERROR",)
    assert "secret" not in out.model_dump_json()
    assert locking.lock_status(DISPOSABLE_DB) == "free"


def test_refused_prefix_is_not_a_failure():
    assert REFUSED_PREFIX == "FMPSYNC_REFUSED"


EXPECTED_EXIT = {
    "OK": 0,
    "PARTIAL": 10,
    "SKIPPED_BUSY": 10,
    "DEFERRED_QUOTA": 10,
    "DEFERRED_RATE_LIMIT": 10,
    "CANCELLED_DEADLINE": 10,
    "CANCELLED": 10,
    "BLOCKED_PLAN": 20,
    "BLOCKED_AUTH": 20,
    "BLOCKED_EGRESS": 20,
    "FAILED_INFRA": 30,
    "PERSIST_FAILED": 30,
    "BLOCKED_PROCESS": 40,
    "BLOCKED_ABI": 40,
    "BLOCKED_MODULE_ORIGIN": 40,
    "BLOCKED_CONFIG": 40,
    "BLOCKED_DATABASE": 40,
    "BLOCKED_POLICY": 40,
    "BLOCKED_UNIVERSE": 40,
    "BLOCKED_EMPTY_UNIVERSE": 40,
}


def _outcome(value: Outcome, **extra) -> FmpSyncOutcome:
    now = utcnow()
    return FmpSyncOutcome(
        run_id="r",
        mode="execute",
        started_utc=now,
        ended_utc=now,
        outcome=value,
        **extra,
    )


@pytest.mark.parametrize("value", list(Outcome))
def test_outcome_schema_and_exit_codes(value):
    out = _outcome(
        value, findings=("A_CODE", "MODULE_OUTSIDE_SOURCE_ROOT:portfolio_utils")
    )
    assert EXPECTED_EXIT[value.value] == out.exit_code == EXIT_CODES[value]
    line = out.to_line()
    assert len(line) <= 512 and json.loads(line)["exit"] == out.exit_code


def test_outcome_covers_every_enum_member():
    assert {o.value for o in Outcome} == set(EXPECTED_EXIT)


def test_outcome_rejects_free_text_and_unknown_fields():
    with pytest.raises(ValidationError):
        _outcome(Outcome.OK, findings=("HTTP 429 for https://x/?apikey=abc",))
    with pytest.raises(ValidationError):
        _outcome(Outcome.OK, findings=("C:\\Users\\me\\key.txt",))
    with pytest.raises(ValidationError):
        FmpSyncOutcome(
            run_id="r",
            mode="m",
            started_utc=utcnow(),
            ended_utc=utcnow(),
            outcome=Outcome.OK,
            error="free text",
        )


def test_readiness_error_maps_to_unavailable(harness):
    """A readiness exception is UNAVAILABLE READINESS_ERROR -> data_status UNKNOWN."""

    def unavailable(symbols, database=None):
        raise RuntimeError("least-privilege user cannot COUNT")

    out = harness.run(readiness_fn=unavailable)
    assert out.outcome is Outcome.OK and out.exit_code == 0
    assert out.data_status == "UNKNOWN"
    assert "least-privilege" not in out.model_dump_json()
    assert json.loads(out.to_line())["data_status"] == "UNKNOWN"


def test_readiness_data_status_reaches_outcome(harness):
    out = harness.run(readiness_fn=lambda symbols, database=None: {"data_status": "WARN"})
    assert out.data_status == "WARN"
    bogus = harness.run(readiness_fn=lambda symbols, database=None: {"data_status": "GREEN"})
    assert bogus.data_status == "UNVALIDATED"


def test_outcome_rejects_unknown_data_status():
    with pytest.raises(ValidationError):
        FmpSyncOutcome(
            run_id="a" * 32,
            mode="execute",
            started_utc=utcnow(),
            ended_utc=utcnow(),
            outcome=Outcome.OK,
            data_status="HEALTHY",
        )
