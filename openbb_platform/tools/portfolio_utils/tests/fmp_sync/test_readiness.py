"""Readiness v2: read-only allowlisted SQL, private counts, table case (#1345-T01).

SQLite stand-in (real aggregate/NULL semantics) and synthetic calendar; the
conftest blocks every MySQL connection and non-loopback socket.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pymysql
import pytest
from portfolio_utils import fetch_position_history as tool
from portfolio_utils.fmp_sync import datasets, readiness, sessions
from portfolio_utils.fmp_sync.checks import CheckResult, CheckState, aggregate

from .conftest import DISPOSABLE_DB
from .fixtures import sql_fixture as sf

FIXTURE = Path(__file__).parent / "fixtures" / "calendar_synthetic.json"
NOW = datetime(2026, 11, 27, 15, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
TARGET = date(2026, 11, 27)
PRIVATE = ("Portfolio_Positions", "Account_Owner", "ESPP_Plan")
CLOSURES_2026_2027 = [
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1), date(2027, 1, 18),
    date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
]  # fmt: skip


@pytest.fixture(name="cal")
def _cal():
    return sessions.SyntheticCalendar.from_json(FIXTURE)


def _fresh(*symbols, day=TARGET):
    return [sf.row(s, day) for s in symbols]


def _conn(prices=None, **kwargs):
    kwargs.setdefault("holidays", CLOSURES_2026_2027)
    return sf.build(DISPOSABLE_DB, prices=prices or _fresh("AAA", "BBB"), **kwargs)


def _eval(conn, cal, symbols=("AAA", "BBB"), **kwargs):
    return readiness.evaluate(
        list(symbols),
        now=NOW,
        calendar=cal,
        connect_fn=lambda: conn,
        database=DISPOSABLE_DB,
        **kwargs,
    )


def _check(report, check_id) -> CheckResult:
    return next(c for c in report.checks if c.check_id == check_id)


def test_all_fresh_is_validated(cal):
    report = _eval(_conn(), cal)
    assert report.data_status == "VALIDATED", [c.model_dump() for c in report.checks]


def test_legacy_keys_preserved(cal):
    conn = _conn(prices=_fresh("AAA") + [sf.row("CCC", date(2026, 11, 24))])
    out = tool.check_portfolio_app_readiness(
        ["AAA", "BBB", "CCC"],
        DISPOSABLE_DB,
        now=NOW,
        calendar=cal,
        connect_fn=lambda: conn,
    )
    assert {
        "target_date",
        "table_counts",
        "missing_price_symbols",
        "stale_price_symbols",
    } <= set(out)
    assert out["target_date"] == "2026-11-27"
    assert out["missing_price_symbols"] == ["BBB"]
    assert out["stale_price_symbols"] == [("CCC", "2026-11-24")]
    assert out["table_counts"] == {}
    assert out["data_status"] == "CRITICAL"
    assert {"checks", "calendar"} <= set(out)
    assert out["calendar"]["target_session"] == "2026-11-27"
    assert out["calendar"]["grace_minutes"] == 120


def test_legacy_empty_symbols_never_connects(cal):
    def boom():
        raise AssertionError("must not connect")

    out = tool.check_portfolio_app_readiness(
        [], None, now=NOW, calendar=cal, connect_fn=boom
    )
    assert out["missing_price_symbols"] == [] and out["data_status"] == "UNVALIDATED"


def test_audit_read_only_runs_only_allowlisted_selects(cal):
    conn = _conn(private=dict.fromkeys(PRIVATE, 1))
    _eval(conn, cal, policy={"private_counts": True})
    assert conn.sql[:3] == [
        readiness.QUERIES["ro_session"],
        readiness.QUERIES["max_execution_time"],
        readiness.QUERIES["ro_start"],
    ]
    assert conn.sql[0] == "SET SESSION TRANSACTION READ ONLY"
    assert conn.sql[2] == "START TRANSACTION READ ONLY"
    allowed = {q.replace("({in})", "(%s)") for q in readiness.QUERIES.values()}
    for stmt in conn.sql:
        assert re.sub(r"\(%s(, %s)*\)", "(%s)", stmt) in allowed, stmt
    assert conn.writes() == []
    assert conn.rolled_back and conn.closed


def test_runner_rejects_unlisted_statement():
    session = readiness.ReadOnlySession(sf.SqliteConn(DISPOSABLE_DB), timeout_ms=1000)
    with pytest.raises(readiness.QueryNotAllowed):
        session.run("DELETE FROM equity_historical")


def test_readonly_setup_failure_runs_no_select(cal):
    conn = _conn()
    conn.errors["TRANSACTION READ ONLY"] = 1227
    report = _eval(conn, cal)
    assert _check(report, "db.session").state is CheckState.UNAVAILABLE
    assert _check(report, "db.session").reason_code == "READ_ONLY_SETUP_FAILED"
    assert not [s for s in conn.sql if s.lstrip().upper().startswith("SELECT")]
    assert report.data_status == "UNKNOWN"


def test_mysql_unavailable_is_unknown(cal):
    def refused():
        raise pymysql.err.OperationalError(2003, "synthetic")

    report = readiness.evaluate(["AAA"], now=NOW, calendar=cal, connect_fn=refused)
    db = _check(report, "db.session")
    assert (db.state, db.reason_code) == (CheckState.UNAVAILABLE, "MYSQL_UNAVAILABLE")
    assert report.data_status == "UNKNOWN"


def test_session_database_mismatch_blocks(cal):
    conn = sf.build("obb_disposable_other0000", prices=_fresh("AAA"))
    report = _eval(conn, cal, symbols=("AAA",))
    assert _check(report, "db.session").reason_code == "SESSION_DATABASE_MISMATCH"
    assert report.data_status == "BLOCKED"
    assert not [s for s in conn.sql if "equity_historical" in s]


def test_freshness_thresholds(cal):
    prices = [
        sf.row("OK1", TARGET),
        sf.row("WRN", date(2026, 11, 25)),  # one missed session (Nov 27)
        sf.row("CRT", date(2026, 11, 24)),  # two missed sessions
    ]
    report = _eval(_conn(prices=prices), cal, symbols=("OK1", "WRN", "CRT", "NONE"))
    fresh = _check(report, "prices.freshness")
    assert fresh.state is CheckState.CRITICAL
    assert fresh.counts == {"ok": 1, "warn": 1, "critical": 1, "missing": 1}
    only_warn = _eval(_conn(prices=prices), cal, symbols=("OK1", "WRN"))
    assert _check(only_warn, "prices.freshness").state is CheckState.WARN


def test_filled_rows_do_not_satisfy_freshness(cal):
    prices = [
        sf.row("AAA", date(2026, 11, 24)),
        sf.row("AAA", date(2026, 11, 25), filled=1),
        sf.row("AAA", TARGET, filled=1),
        sf.row("BBB", date(2026, 11, 24)),
        sf.row("BBB", TARGET, valid=0),
    ]
    report = _eval(_conn(prices=prices), cal)
    fresh = _check(report, "prices.freshness")
    assert fresh.state is CheckState.CRITICAL and fresh.counts["critical"] == 2
    assert report.stale == [("AAA", "2026-11-24"), ("BBB", "2026-11-24")]


def test_exclusions_not_counted_success(cal):
    report = _eval(_conn(), cal, exclusions=3)
    excl = _check(report, "prices.exclusions")
    assert excl.state is CheckState.NOT_APPLICABLE and excl.counts == {"excluded": 3}
    assert _check(report, "prices.freshness").counts["ok"] == 2
    assert report.data_status == "VALIDATED"


def test_null_partition_and_null_safe_duplicates(cal):
    prices = _fresh("AAA", "BBB") + [
        sf.row("AAA", date(2026, 11, 20), adjustment=None),
        sf.row("AAA", date(2026, 11, 20), adjustment=None),  # unique key bypassed
        sf.row("BBB", date(2026, 11, 19), interval=None),
    ]
    report = _eval(_conn(prices=prices), cal)
    nulls = _check(report, "prices.null_partition")
    assert (nulls.state, nulls.reason_code, nulls.counts) == (
        CheckState.WARN,
        "NULL_PARTITION",
        {"rows": 3},
    )
    dup = _check(report, "prices.duplicates")
    assert (dup.state, dup.counts) == (CheckState.WARN, {"groups": 1})
    assert report.data_status == "WARN"


def test_private_counts_off_by_default_no_private_sql(cal):
    conn = _conn(private=dict.fromkeys(PRIVATE, 5))
    report = _eval(conn, cal)
    assert not [s for s in conn.sql if any(t.lower() in s.lower() for t in PRIVATE)]
    assert not [c for c in report.checks if c.check_id.startswith("private.")]
    assert report.private_counts == {}


def test_private_counts_on_are_local_values(cal):
    conn = _conn(private={"Portfolio_Positions": 4, "Account_Owner": 2, "ESPP_Plan": 1})
    report = _eval(conn, cal, policy={"private_counts": True})
    assert report.private_counts == {
        "Portfolio_Positions": 4,
        "Account_Owner": 2,
        "ESPP_Plan": 1,
    }
    for name in PRIVATE:
        check = _check(report, f"private.{name}")
        assert (
            check.state is CheckState.OK and check.counts == {} and not check.required
        )


def test_grant_missing_1142_is_unavailable(cal):
    conn = _conn(private=dict.fromkeys(PRIVATE, 1))
    conn.errors["FROM Portfolio_Positions"] = 1142
    report = _eval(conn, cal, policy={"private_counts": True})
    check = _check(report, "private.Portfolio_Positions")
    assert (check.state, check.reason_code) == (CheckState.UNAVAILABLE, "GRANT_MISSING")
    assert "Portfolio_Positions" not in report.private_counts
    legacy = report.legacy()
    assert "Portfolio_Positions" not in legacy["table_counts"]


def test_private_unavailable_never_zero_never_blocks_warm(cal):
    conn = _conn(private={"Account_Owner": 1})
    conn.errors["FROM Portfolio_Positions"] = 1044
    conn.hidden.add("ESPP_Plan")
    conn.errors["FROM ESPP_Plan"] = 1143
    report = _eval(conn, cal, policy={"private_counts": True})
    states = {c.check_id: (c.state, c.reason_code) for c in report.checks}
    assert states["private.Portfolio_Positions"] == (
        CheckState.UNAVAILABLE,
        "GRANT_MISSING",
    )
    assert states["private.ESPP_Plan"] == (CheckState.UNAVAILABLE, "GRANT_MISSING")
    assert set(report.private_counts) == {"Account_Owner"}
    assert 0 not in report.private_counts.values()
    assert report.data_status == "VALIDATED"  # informational only


def test_table_missing_1146(cal):
    conn = _conn(private={"Portfolio_Positions": 1, "ESPP_Plan": 1})
    report = _eval(conn, cal, policy={"private_counts": True})
    check = _check(report, "private.Account_Owner")
    assert (check.state, check.reason_code) == (CheckState.WARN, "TABLE_MISSING")
    assert "Account_Owner" not in report.private_counts
    no_holidays = _eval(_conn(with_holidays=False), cal)
    assert _check(no_holidays, "table.market_holidays").reason_code == "TABLE_MISSING"
    assert no_holidays.data_status == "CRITICAL"


def test_hidden_table_not_visible(cal):
    conn = _conn(private=dict.fromkeys(PRIVATE, 1))
    conn.hidden.add("Account_Owner")
    conn.errors["FROM Account_Owner"] = 1105
    report = _eval(conn, cal, policy={"private_counts": True})
    check = _check(report, "private.Account_Owner")
    assert (check.state, check.reason_code) == (CheckState.UNAVAILABLE, "NOT_VISIBLE")


def test_table_case_mismatch_reported(cal):
    conn = _conn(private={"Portfolio_Positions": 1, "Account_Owner": 1, "espp_plan": 7})
    report = _eval(conn, cal, policy={"private_counts": True})
    check = _check(report, "private.ESPP_Plan")
    assert (check.state, check.reason_code) == (CheckState.WARN, "TABLE_CASE_MISMATCH")
    assert "ESPP_Plan" not in report.private_counts
    folded = _eval(
        _conn(
            private={"Portfolio_Positions": 1, "Account_Owner": 1, "espp_plan": 7},
            lctn=1,
        ),
        cal,
        policy={"private_counts": True},
    )
    assert _check(folded, "private.ESPP_Plan").state is CheckState.OK
    upper = _eval(_conn(equity_name="EQUITY_HISTORICAL"), cal)
    eq = _check(upper, "table.equity_historical")
    assert (eq.state, eq.reason_code) == (CheckState.WARN, "TABLE_CASE_MISMATCH")


def test_holiday_table_disagreement_reported_not_deleted(cal):
    wrong = [*CLOSURES_2026_2027, date(2021, 12, 31), date(2027, 12, 31)]
    conn = _conn(holidays=wrong)
    report = _eval(conn, cal)
    check = _check(report, "calendar.holiday_table")
    assert (check.state, check.reason_code) == (
        CheckState.WARN,
        "CALENDAR_DISAGREEMENT",
    )
    assert check.counts == {"extra": 1, "missing": 0}
    assert conn.writes() == []
    (rows,) = conn.db.execute("SELECT COUNT(*) FROM market_holidays").fetchone()
    assert rows == len(wrong)


def test_next_year_missing_in_table_warns(cal):
    report = _eval(_conn(holidays=CLOSURES_2026_2027[:10]), cal)
    check = _check(report, "calendar.coverage")
    assert (check.state, check.reason_code) == (
        CheckState.WARN,
        "NEXT_YEAR_CALENDAR_MISSING",
    )


def test_dry_run_lists_db_checks_not_evaluated(cal):
    def boom():
        raise AssertionError("a dry run must never connect")

    report = readiness.evaluate(
        ["AAA"], now=NOW, calendar=cal, dry_run=True, connect_fn=boom
    )
    db = [c for c in report.checks if c.reason_code == "DRY_RUN_NO_DB"]
    assert db and all(c.state is CheckState.NOT_EVALUATED for c in db)
    assert report.data_status == "UNVALIDATED"
    assert report.target_session == TARGET


def test_required_unknown_never_validated():
    ok = CheckResult(check_id="a", state=CheckState.OK, reason_code="X")
    for bad, expected in (
        (CheckState.UNKNOWN, "UNKNOWN"),
        (CheckState.UNAVAILABLE, "UNKNOWN"),
        (CheckState.NOT_EVALUATED, "UNVALIDATED"),
        (CheckState.BLOCKED, "BLOCKED"),
    ):
        other = CheckResult(check_id="b", state=bad, reason_code="Y")
        assert aggregate([ok, other]) == expected
        assert (
            aggregate([ok, other.model_copy(update={"required": False})]) == "VALIDATED"
        )
    assert aggregate([]) == "UNVALIDATED"


def test_ambiguous_host_local_fold_unknown():
    fold = datasets.resolve_instant(
        "equity_historical.cached_at",
        datetime(2027, 11, 7, 1, 30),
        "America/Los_Angeles",
    )
    assert isinstance(fold, CheckResult)
    assert (fold.state, fold.reason_code) == (CheckState.UNKNOWN, "AMBIGUOUS_TIMESTAMP")
    gap = datasets.resolve_instant(
        "equity_historical.cached_at",
        datetime(2027, 3, 14, 2, 30),
        "America/Los_Angeles",
    )
    assert isinstance(gap, CheckResult)
    plain = datasets.resolve_instant(
        "equity_historical.cached_at",
        datetime(2027, 11, 7, 3, 30),
        "America/Los_Angeles",
    )
    assert plain == datetime(2027, 11, 7, 11, 30, tzinfo=ZoneInfo("UTC"))
    assert isinstance(datasets.resolve_instant("nope.col", plain, "UTC"), CheckResult)
    assert datasets.semantics_check("equity_historical.date", "DATE_ET_SESSION") is None
    assert (
        datasets.semantics_check("nope.col", "DATE_ET_SESSION").state
        is CheckState.UNKNOWN
    )


def test_undeclared_price_semantics_make_freshness_unknown(cal, monkeypatch):
    monkeypatch.delitem(datasets.DATASETS, "equity_historical.date")
    report = _eval(_conn(), cal)
    fresh = _check(report, "prices.freshness")
    assert (fresh.state, fresh.reason_code) == (
        CheckState.UNKNOWN,
        "AMBIGUOUS_TIMESTAMP",
    )
    assert report.data_status == "UNKNOWN"


def test_query_timeout_is_unknown(cal):
    conn = _conn()
    conn.errors["MAX(date)"] = 3024
    report = _eval(conn, cal)
    fresh = _check(report, "prices.freshness")
    assert (fresh.state, fresh.reason_code) == (CheckState.UNKNOWN, "QUERY_TIMEOUT")
    assert report.data_status == "UNKNOWN"


def test_target_is_never_host_local_today(cal, monkeypatch):
    """The target comes from ``now`` in New York, not the host's date."""
    late = datetime(
        2026, 11, 30, 23, 30, tzinfo=ZoneInfo("Pacific/Kiritimati")
    )  # Nov 30 04:30 ET
    report = readiness.evaluate(["AAA"], now=late, calendar=cal, dry_run=True)
    assert report.target_session == date(2026, 11, 27)
    assert report.target_session - timedelta(days=0) != late.date()
