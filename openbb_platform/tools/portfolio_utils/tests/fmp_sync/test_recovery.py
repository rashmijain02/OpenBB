"""Catch-up recovery without fetch storms (#1345-T03).

Fake transport only: gateway failure and 429 are injected as ``Session.send``
results; every assertion counts requests. No MySQL, no FMP, no real sockets.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymysql
import pytest
import requests
from portfolio_utils.fmp_sync import recovery, sessions, state
from portfolio_utils.fmp_sync.__main__ import main
from portfolio_utils.fmp_sync.dispatcher import run_prices
from portfolio_utils.fmp_sync.outcome import FmpSyncOutcome, Outcome

from .test_admission import world  # noqa: F401  (fixture)
from .test_budget import response
from .test_dispatcher import LIMITS, gapped_fetch, harness  # noqa: F401  (fixture)

PT_NOW = datetime(2026, 11, 25, 23, 0, tzinfo=timezone.utc)  # Wed 15:00 PT
CAL = sessions.xnys_for(PT_NOW)


def _utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


def _status(last_attempt: datetime) -> dict:
    return {"last_attempt_utc": last_attempt.isoformat(), "delivery_state": "unknown"}


def _state() -> Path:
    return Path(os.environ["FMP_SYNC_STATE_ROOT"])


def _outcome(kind=Outcome.OK, mode="execute", session="2026-11-24", **kw):
    now = datetime(2026, 11, 25, 23, 31, tzinfo=timezone.utc)
    return FmpSyncOutcome(
        run_id="r1",
        mode=mode,
        started_utc=now,
        ended_utc=now,
        outcome=kind,
        target_session=session,
        **kw,
    )


def _snapshot(root: Path) -> dict:
    return json.loads((root / "status.json").read_text("utf-8"))


# ---------------------------------------------------------------- planning


def test_plan_counts_three_missed_fires_as_one_run():
    # last attempt Fri 2026-11-20 15:31 PT; due Mon 23, Tue 24, Wed 25 (+30 min grace)
    status = _status(datetime(2026, 11, 20, 23, 31, tzinfo=timezone.utc))
    now = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)  # Wed 17:00 PT
    plan = recovery.plan_catch_up(status, now=now, calendar=CAL)
    assert plan.missed == 3 and plan.runs == 1
    assert plan.findings == ("CRON_RUN_MISSED",)


def test_plan_respects_grace_and_weekends_and_holidays():
    now = datetime(2026, 11, 25, 23, 45, tzinfo=timezone.utc)  # 15:45 PT Wed
    status = _status(datetime(2026, 11, 24, 23, 31, tzinfo=timezone.utc))
    assert recovery.plan_catch_up(status, now=now, calendar=CAL).missed == 0  # in grace
    later = datetime(2026, 11, 26, 0, 1, tzinfo=timezone.utc)  # 16:01 PT
    assert recovery.plan_catch_up(status, now=later, calendar=CAL).missed == 1
    # Thanksgiving Thu 26 is not a session; Sat/Sun never count
    fri = _status(datetime(2026, 11, 25, 23, 31, tzinfo=timezone.utc))
    mon = datetime(2026, 11, 30, 5, 0, tzinfo=timezone.utc)
    assert recovery.plan_catch_up(fri, now=mon, calendar=CAL).missed == 1  # Fri 27 only


def test_plan_without_history_never_fabricates_a_miss():
    assert recovery.plan_catch_up(None, now=PT_NOW, calendar=CAL).missed == 0
    assert recovery.plan_catch_up({}, now=PT_NOW, calendar=CAL).missed == 0
    bad = {"last_attempt_utc": "not-a-date"}
    assert recovery.plan_catch_up(bad, now=PT_NOW, calendar=CAL).runs == 0


def test_unknown_delivery_never_reruns():
    fresh = {
        "last_attempt_utc": (PT_NOW - timedelta(minutes=20)).isoformat(),
        "delivery_state": "unknown",
    }
    plan = recovery.plan_catch_up(fresh, now=PT_NOW, calendar=CAL)
    assert plan.runs == 0 and plan.findings == ()
    assert state.DELIVERY_UNKNOWN == "unknown"
    # delivery_state is never an input: any value gives the same plan
    other = {**fresh, "delivery_state": "failed"}
    assert recovery.plan_catch_up(other, now=PT_NOW, calendar=CAL) == plan


# ---------------------------------------------------------------- watermarks


def test_ok_execute_run_advances_watermarks(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(data_status="VALIDATED"))
    snap = _snapshot(root)
    assert snap["last_successful_sync_session"] == "2026-11-24"
    assert snap["delivery_state"] == "unknown" and snap["last_attempt_utc"]
    assert snap["last_validation_utc"]


def test_partial_does_not_advance_sync_watermark(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-23"))
    state.record_end(root, _outcome(Outcome.PARTIAL, session="2026-11-24"))
    assert _snapshot(root)["last_successful_sync_session"] == "2026-11-23"
    state.record_end(root, _outcome(Outcome.DEFERRED_RATE_LIMIT, session="2026-11-25"))
    assert _snapshot(root)["last_successful_sync_session"] == "2026-11-23"


def test_watermark_never_moves_backwards(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-24"))
    state.record_end(root, _outcome(session="2026-11-20"))
    assert _snapshot(root)["last_successful_sync_session"] == "2026-11-24"


def test_heartbeat_does_not_advance_sync_watermark(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-23"))
    before = _snapshot(root)
    assert state.record_heartbeat(root, now=PT_NOW)
    after = _snapshot(root)
    assert after["last_successful_sync_session"] == "2026-11-23"
    assert after["last_attempt_utc"] == before["last_attempt_utc"]
    assert after["fingerprint"] == before["fingerprint"]
    assert after["last_heartbeat_utc"].startswith("2026-11-25T23:00")
    assert not state.record_heartbeat(tmp_path / "empty", now=PT_NOW)
    assert not (tmp_path / "empty" / "status.json").exists()


def test_dry_run_is_not_an_attempt_or_a_sync(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-23"))
    before = _snapshot(root)
    state.record_end(root, _outcome(mode="dry_run", session="2026-11-25"))
    after = _snapshot(root)
    assert after["last_successful_sync_session"] == "2026-11-23"
    assert after["last_attempt_utc"] == before["last_attempt_utc"]


def test_busy_run_does_not_touch_watermark(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-23"))
    before = (root / "status.json").read_bytes()
    state.record_end(root, _outcome(Outcome.SKIPPED_BUSY, session="2026-11-25"))
    assert (root / "status.json").read_bytes() == before


def test_persist_failed_keeps_old_watermark(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(session="2026-11-23"))
    before = (root / "status.json").read_bytes()

    def denied(_src, _dst):
        raise PermissionError

    receipt = state.record_end(
        root,
        _outcome(session="2026-11-25"),
        replace_fn=denied,
        sleep_fn=lambda _s: None,
    )
    assert receipt.outcome.outcome is Outcome.PERSIST_FAILED
    assert (root / "status.json").read_bytes() == before
    assert _snapshot(root)["last_successful_sync_session"] == "2026-11-23"


def test_outcome_line_is_unchanged_by_target_session():
    assert "target_session" not in _outcome().to_line()


# ---------------------------------------------------------------- no fetch storms


def test_gateway_down_three_fires_one_catch_up_run(harness):  # noqa: F811
    harness.wall.t = _utc(26, 1, 0).timestamp()  # Wed 17:00 PT
    status = _status(datetime(2026, 11, 20, 23, 31, tzinfo=timezone.utc))
    (_state()).mkdir(parents=True, exist_ok=True)
    (_state() / "status.json").write_text(json.dumps(status), encoding="utf-8")
    out = harness.run()  # ONE run no matter how many fires were missed
    assert out.outcome is Outcome.OK
    assert "CRON_RUN_MISSED" in out.findings
    assert out.target_session == "2026-01-02"  # from the readiness result
    gapped = out.counts.requested  # AAA, BBB, SPY
    assert len(harness.sent) == out.budget.sent <= gapped <= 50  # per_run
    assert len(harness.sent) == 3  # exactly one request per gapped symbol


def test_no_catch_up_finding_when_nothing_missed(harness):  # noqa: F811
    harness.wall.t = _utc(25, 23, 45).timestamp()
    status = _status(datetime(2026, 11, 24, 23, 31, tzinfo=timezone.utc))
    (_state()).mkdir(parents=True, exist_ok=True)
    (_state() / "status.json").write_text(json.dumps(status), encoding="utf-8")
    assert "CRON_RUN_MISSED" not in harness.run().findings


def test_gateway_failure_no_retry_storm(harness):  # noqa: F811
    def down(_session, request, **_kw):
        harness.sent.append(request.url)
        raise requests.ConnectionError("test gateway down")

    out = harness.run(inner_send=down)
    assert out.outcome is Outcome.FAILED_INFRA
    assert len(harness.sent) == 3  # one attempt per gapped symbol, no retries
    root = _state()
    state.record_end(root, out)
    assert (
        "last_successful_sync_session" not in _snapshot(root)
        or not _snapshot(root)["last_successful_sync_session"]
    )


def test_simulated_429_defers_and_next_run_sends_zero(harness):  # noqa: F811
    harness.responses = lambda: response(429, headers={"Retry-After": "120"})
    first = harness.run()
    assert first.outcome is Outcome.DEFERRED_RATE_LIMIT and len(harness.sent) == 1
    receipt = state.record_end(_state(), first)
    assert receipt.transition
    harness.responses = lambda: response()
    harness.wall.t += 60  # inside the window
    second = harness.run()
    assert second.outcome is Outcome.DEFERRED_RATE_LIMIT
    assert second.budget.sent == 0 and len(harness.sent) == 1  # zero new sends
    again = state.record_end(_state(), second)
    assert not again.transition and not again.emit  # no repeated alert
    lines = [
        json.loads(x)
        for x in (_state() / "history.jsonl").read_text("utf-8").splitlines()
    ]
    assert sum(1 for r in lines if r["kind"] == "transition") == 1


def test_after_defer_window_single_resume(harness):  # noqa: F811
    harness.responses = lambda: response(429, headers={"Retry-After": "120"})
    harness.run()
    harness.responses = lambda: response()
    harness.wall.t += 121
    resumed = harness.run()
    assert resumed.outcome is Outcome.OK
    assert len(harness.sent) == 1 + 3  # the one 429, then one send per symbol


def test_mysql_unavailable_no_fmp_send(harness):  # noqa: F811
    def down():
        raise pymysql.err.OperationalError(2003, "cannot connect")

    harness.admit_kwargs["connect_fn"] = down
    out = harness.run(admit_kwargs=harness.admit_kwargs)
    assert out.outcome is Outcome.FAILED_INFRA and out.exit_code == 30
    assert "MYSQL_UNAVAILABLE" in out.findings
    assert harness.sent == [] and out.budget.sent == 0


@pytest.mark.parametrize("module", ["recovery.py"])
def test_recovery_has_no_network_imports(module):
    text = (Path(recovery.__file__)).read_text(encoding="utf-8")
    assert "requests" not in text and "socket" not in text


# ---------------------------------------------------------------- CLI real path


def test_cli_audit_ops_dry_run_reports_states(world, tmp_path, capsys):  # noqa: F811
    make, _kwargs = world
    bk, bl = tmp_path / "bk", tmp_path / "bl"
    for folder, name in ((bk, "x.sql.gz"), (bl, "binlog.000001")):
        folder.mkdir()
        (folder / name).write_bytes(b"")
        old = datetime.now().timestamp() - 3600
        os.utime(folder / name, (old, old))
    make(ops={"backup_dir": str(bk), "binlog_dir": str(bl), "volumes": [str(tmp_path)]})
    usage = type("U", (), {"total": 100 * 1024**3, "used": 0, "free": 50 * 1024**3})
    code = main(
        ["audit", "--dry-run", "--checks", "ops", "--map", str(tmp_path / "map.json")],
        audit_kwargs={"disk_usage_fn": lambda _p: usage},
    )
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert {"BACKUP_EMPTY", "FIRST_SAMPLE"} <= set(line["findings"])
    assert line["data_status"] == "CRITICAL"
    assert str(tmp_path) not in json.dumps(line)


def test_cli_prices_execute_with_open_defer_window_sends_zero(
    harness, capsys
):  # noqa: F811
    path = harness.dmap_make(account_label="acct", limits=LIMITS)
    del path  # the map file is written next to the fixture's tmp dir
    map_path = Path(os.environ["FMP_SYNC_STATE_ROOT"]).parent / "map.json"
    defer = _state() / "budget" / "acct" / "defer.json"
    defer.parent.mkdir(parents=True)
    defer.write_text(json.dumps({"until": harness.wall.t + 120}), encoding="utf-8")

    def runner(dmap, **kw):
        return run_prices(
            dmap,
            admit_kwargs=harness.admit_kwargs,
            fetch_one_fn=gapped_fetch,
            api_key_resolver=lambda: "k",
            holiday_fn=lambda *_a: None,
            readiness_fn=lambda symbols, database=None: {"target_date": "2026-01-02"},
            inner_send=harness.inner_send,
            clock=harness.mono,
            now_fn=harness.wall,
            **kw,
        )

    code = main(["prices", "--execute", "--map", str(map_path)], runner=runner)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 10 and line["outcome"] == "DEFERRED_RATE_LIMIT"
    assert line["sent"] == 0 and harness.sent == []
