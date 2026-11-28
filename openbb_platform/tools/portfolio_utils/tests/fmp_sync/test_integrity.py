"""Bounded integrity checks over the SQLite stand-in (#1345-T02).

Real aggregate and NULL semantics run against synthetic rows; the conftest
blocks MySQL and non-loopback sockets. Every load-bearing test here was
reverse-verified (``.dev-cycle/reverse_verify_1345_t02.py``).
"""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest
from portfolio_utils.fmp_sync import fundamentals, integrity, readiness, sessions
from portfolio_utils.fmp_sync.checks import CheckState

from .conftest import DISPOSABLE_DB
from .fixtures import sql_fixture as sf
from .test_admission import world  # noqa: F401  (fixture)
from .test_audit_cli import NOW as AUDIT_NOW
from .test_audit_cli import _read_only
from .test_readiness import CLOSURES_2026_2027, FIXTURE, NOW, TARGET

SESSIONS = 5
ALL_CHECKS = ("readiness", "integrity", "fundamentals")
PKG = Path(integrity.__file__).parent


@pytest.fixture(name="cal")
def _cal():
    return sessions.SyntheticCalendar.from_json(FIXTURE)


def _window(cal, n=SESSIONS):
    return sessions.sessions_between(cal, cal.first_day, TARGET)[-n:]


def _history(cal, *symbols, skip=()):
    return [sf.row(s, d) for s in symbols for d in _window(cal) if (s, d) not in skip]


def _raw(symbol, day, **cols):
    base = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}
    return {"symbol": symbol, "date": day, **base, **cols}


def _eval(conn, cal, symbols=("AAA", "BBB"), checks=("integrity",), **policy):
    return readiness.evaluate(
        list(symbols),
        now=NOW,
        calendar=cal,
        policy={"max_sessions": SESSIONS, **policy},
        connect_fn=lambda: conn,
        database=DISPOSABLE_DB,
        checks=checks,
    )


def _conn(prices=(), **kwargs):
    kwargs.setdefault("holidays", CLOSURES_2026_2027)
    return sf.build(DISPOSABLE_DB, prices=list(prices), **kwargs)


def _get(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


def _states(report, prefix="integrity."):
    return {
        c.check_id: (c.state, c.reason_code)
        for c in report.checks
        if c.check_id.startswith(prefix)
    }


def test_complete_history_is_validated(cal):
    report = _eval(_conn(_history(cal, "AAA", "BBB")), cal)
    assert report.data_status == "VALIDATED", _states(report)
    assert _get(report, "integrity.window").counts["rows"] == 2 * SESSIONS


def test_empty_expected_window_is_critical_not_green(cal):
    # Other symbols exist, so the table is fine; AAA/BBB have zero rows in the window.
    report = _eval(_conn(_history(cal, "ZZZ")), cal)
    states = _states(report)
    assert states["integrity.window"] == (CheckState.CRITICAL, "EMPTY_PARTITION")
    assert states["integrity.gaps"] == (CheckState.CRITICAL, "EMPTY_PARTITION")
    # SUM over zero rows is NULL: it must surface as UNKNOWN, never as 0 (clean).
    assert states["integrity.ohlc"] == (CheckState.UNKNOWN, "NULL_AGGREGATE")
    assert report.data_status == "CRITICAL"


def test_all_holiday_window_not_applicable(cal):
    holiday = date(2026, 11, 26)
    assert sessions.sessions_between(cal, holiday, holiday) == []
    out = integrity.evaluate(
        lambda *a, **k: pytest.fail("no query for an empty expected window"),
        ["AAA"],
        [],
        cal,
        interval_type="1d",
        adjustment_type="splits_only",
        failure=lambda c, e: pytest.fail(str(e)),
    )
    assert {c.state for c in out} == {CheckState.NOT_APPLICABLE}
    assert {c.reason_code for c in out} == {"NO_EXPECTED_SESSIONS"}


def test_null_partition_rows_counted(cal):
    rows = [_raw("AAA", TARGET, adjustment_type=None)]
    conn = _conn(_history(cal, "AAA") + [], raw_rows=rows)
    report = _eval(conn, cal, symbols=("AAA",), checks=("readiness", "integrity"))
    null = _get(report, "prices.null_partition")
    assert (null.state, null.counts["rows"]) == (CheckState.WARN, 1)
    # The NULL-partition row is not silently folded into the validated basis.
    assert _get(report, "integrity.window").counts["rows"] == SESSIONS


def test_duplicates_with_null_interval_detected(cal):
    day = TARGET
    rows = [_raw("AAA", day, interval_type=None), _raw("AAA", day, interval_type=None)]
    conn = _conn(_history(cal, "AAA"), raw_rows=rows)
    # The unique key does not stop duplicates when interval_type is NULL.
    assert conn.db.execute(
        "SELECT COUNT(*) FROM equity_historical WHERE interval_type IS NULL"
    ).fetchone() == (2,)
    report = _eval(conn, cal, symbols=("AAA",), checks=("readiness",))
    dup = _get(report, "prices.duplicates")
    assert (dup.state, dup.counts["groups"]) == (CheckState.WARN, 1)


def _top_level_split(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*parts, cur.strip()]


def test_duplicate_groups_sql_uses_null_safe_grouping():
    """SQLite groups NULLs together, so only the emitted SQL can prove NULL safety."""
    sql = readiness.QUERIES["duplicate_groups"]
    group_by = re.search(r"GROUP BY (.*?) HAVING", sql, re.S)
    assert group_by, "duplicate query must group explicitly"
    exprs = _top_level_split(group_by.group(1))
    nullable = [
        e
        for e in exprs
        if e.split("(")[-1].strip(" ,)").startswith(("interval", "adjust"))
        or "interval_type" in e
        or "adjustment_type" in e
    ]
    assert len(nullable) == 2
    for expr in nullable:
        assert expr.upper().startswith("COALESCE("), expr


def test_invalid_close_negative_volume_critical(cal):
    rows = [
        _raw("AAA", date(2026, 11, 20), open=-1.0, high=-1.0, low=-1.0, close=-1.0),
        _raw("AAA", date(2026, 11, 23), volume=-5),
        _raw("AAA", date(2026, 11, 24), high=1.0, low=2.0),
    ]
    skip = {("AAA", date(2026, 11, d)) for d in (20, 23, 24)}
    conn = _conn(_history(cal, "AAA", skip=skip), raw_rows=rows)
    ohlc = _get(_eval(conn, cal, symbols=("AAA",)), "integrity.ohlc")
    assert (ohlc.state, ohlc.reason_code) == (CheckState.CRITICAL, "OHLC_INVALID")
    assert ohlc.counts == {"bad_close": 1, "bad_ohlc": 1, "neg_volume": 1}


def test_null_open_high_low_is_ohlc_invalid(cal):
    """NULL comparisons are never true in SQL; a NULL leg must still count as bad."""
    for column in ("open", "high", "low"):
        skip = {("AAA", TARGET)}
        rows = [_raw("AAA", TARGET, **{column: None})]
        conn = _conn(_history(cal, "AAA", skip=skip), raw_rows=rows)
        ohlc = _get(_eval(conn, cal, symbols=("AAA",)), "integrity.ohlc")
        assert (ohlc.state, ohlc.reason_code) == (
            CheckState.CRITICAL,
            "OHLC_INVALID",
        ), column
        assert ohlc.counts["bad_ohlc"] == 1, column


def test_zero_volume_alone_ok(cal):
    skip = {("AAA", TARGET)}
    rows = [_raw("AAA", TARGET, volume=0, open=1.0, high=1.0, low=1.0)]
    conn = _conn(_history(cal, "AAA", skip=skip), raw_rows=rows)
    ohlc = _get(_eval(conn, cal, symbols=("AAA",)), "integrity.ohlc")
    assert (ohlc.state, ohlc.counts["zero_volume"]) == (CheckState.OK, 1)


def test_gap_in_expected_sessions_warns_and_holiday_is_not_a_gap(cal):
    window = _window(cal)
    assert date(2026, 11, 26) not in window  # Thanksgiving is never expected
    skip = {("AAA", window[2])}
    conn = _conn(_history(cal, "AAA", "BBB", skip=skip))
    gaps = _get(_eval(conn, cal), "integrity.gaps")
    assert (gaps.state, gaps.reason_code) == (CheckState.WARN, "SESSION_GAPS")
    assert gaps.counts["missing_sessions"] == 1 and gaps.counts["gapped"] == 1


def test_late_first_row_without_lifecycle_is_unknown_not_ipo(cal):
    window = _window(cal)
    skip = {("AAA", d) for d in window[:2]}
    conn = _conn(_history(cal, "AAA", "BBB", skip=skip))
    gaps = _get(_eval(conn, cal), "integrity.gaps")
    assert (gaps.state, gaps.reason_code) == (CheckState.UNKNOWN, "LIFECYCLE_UNKNOWN")
    assert _eval(conn, cal).data_status == "UNKNOWN"


def _jump_conn(cal):
    window = _window(cal)
    skip = {("AAA", window[-1])}
    return (
        _conn(
            _history(cal, "AAA", skip=skip),
            raw_rows=[_raw("AAA", window[-1], open=2.0, high=2.0, low=2.0, close=2.0)],
        ),
        window[-1],
    )


def test_jump_without_corporate_action_evidence_unknown(cal):
    conn, _ = _jump_conn(cal)
    jumps = _get(_eval(conn, cal, symbols=("AAA",)), "integrity.jumps")
    assert (jumps.state, jumps.reason_code) == (
        CheckState.UNKNOWN,
        "CORPORATE_ACTION_EVIDENCE_MISSING",
    )
    assert jumps.counts == {"jumps": 1}


def test_jump_with_complete_evidence_warns_only_if_unexplained():
    series = {"AAA": {date(2026, 11, 24): 1.0, date(2026, 11, 25): 2.0}}
    explained = integrity._jump_check(series, {"AAA": {date(2026, 11, 25)}})
    unexplained = integrity._jump_check(series, {"AAA": set()})
    assert explained.state is CheckState.OK
    assert (unexplained.state, unexplained.reason_code) == (
        CheckState.WARN,
        "PRICE_JUMP",
    )


def test_window_and_symbol_bounds_enforced(cal):
    # Symbol cap: more symbols than allowed runs no integrity SQL at all.
    many = [f"S{i:03d}" for i in range(4)]
    conn = _conn(_history(cal, *many))
    report = _eval(conn, cal, symbols=many, max_symbols=3)
    assert set(_states(report).values()) == {
        (CheckState.UNKNOWN, "SYMBOL_CAP_EXCEEDED")
    }
    assert not [s for s in conn.sql if "bad_close" in s or "ORDER BY" in s]
    # Window cap: every bound parameter stays inside the last ``max_sessions`` sessions.
    seen: list[tuple] = []

    def spy(query_id, params=(), n_in=0):
        seen.append((query_id, tuple(params)))
        return {
            "window_aggregate": [
                {
                    "n": 1,
                    "bad_close": 0,
                    "bad_ohlc": 0,
                    "neg_volume": 0,
                    "zero_volume": 0,
                }
            ]
        }.get(query_id, [])

    window = _window(cal, 3)
    integrity.evaluate(
        spy, ["AAA"], window, cal, interval_type="1d", adjustment_type="splits_only",
        failure=lambda c, e: pytest.fail(str(e)),
    )  # fmt: skip
    dates = {
        p
        for qid, params in seen
        if qid != "first_dates"
        for p in params
        if isinstance(p, date)
    }
    assert dates == {window[0], window[-1]} and len(window) == 3


def test_row_cap_is_limit_bound_and_reported(cal):
    conn = _conn(_history(cal, "AAA"))
    capped = integrity.IntegrityLimits(max_rows=2, max_symbols=10)
    calls: list[tuple] = []

    def run(query_id, params=(), n_in=0):
        calls.append((query_id, tuple(params)))
        return readiness.ReadOnlySession(conn, 100).run(query_id, params, n_in)

    out = integrity.evaluate(
        run, ["AAA"], _window(cal), cal, interval_type="1d",
        adjustment_type="splits_only", limits=capped,
        failure=lambda c, e: pytest.fail(str(e)),
    )  # fmt: skip
    closes = next(p for q, p in calls if q == "window_closes")
    assert closes[-1] == 3  # LIMIT max_rows + 1
    by_id = {c.check_id: c for c in out}
    assert by_id["integrity.gaps"].reason_code == "ROW_CAP_REACHED"
    assert by_id["integrity.jumps"].state is CheckState.UNKNOWN


_WRITE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|DROP|CREATE|ALTER|TRUNCATE|GRANT|PURGE|INTO)\b",
    re.I,
)


def test_no_dml_or_ddl_in_queries():
    for query_id, sql in readiness.QUERIES.items():
        assert (
            sql.lstrip()
            .upper()
            .startswith(("SELECT", "SET SESSION", "START TRANSACTION READ ONLY"))
        ), query_id
        if sql.lstrip().upper().startswith("SELECT"):
            assert not _WRITE.search(sql), query_id
    for module in ("integrity.py", "fundamentals.py"):
        tree = ast.parse((PKG / module).read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not attrs & {"execute", "executemany", "commit", "cursor"}, module
    assert set(integrity.INTEGRITY_QUERIES) <= set(readiness.QUERIES)
    assert set(fundamentals.FUNDAMENTALS_QUERIES) <= set(readiness.QUERIES)


def test_integrity_dry_run_lists_checks_not_evaluated(cal):
    report = readiness.evaluate(
        ["AAA"], now=NOW, calendar=cal, dry_run=True, checks=ALL_CHECKS
    )
    states = _states(report, "integrity.")
    assert set(states) == set(integrity.INTEGRITY_CHECKS)
    assert {s for s, _ in states.values()} == {CheckState.NOT_EVALUATED}
    assert report.data_status == "UNVALIDATED"
    blobs = _states(report, "fundamentals.")
    assert blobs["fundamentals.shares_float"] == (
        CheckState.NOT_EVALUATED,
        "SOURCE_NOT_ADMITTED",
    )


def test_default_checks_unchanged_by_integrity(cal):
    conn = _conn(_history(cal, "AAA", "BBB"))
    report = _eval(conn, cal, checks=("readiness",))
    assert not [
        c for c in report.checks if c.check_id.startswith(("integrity", "fundamentals"))
    ]
    assert not [s for s in conn.sql if "bad_close" in s]


def test_profile_price_matched_date_only(cal):
    profiles = [
        ("AAA", TARGET, "USD", 1.0, 100),
        ("BBB", TARGET, "USD", 2.0, 100),
    ]
    conn = _conn(_history(cal, "AAA", "BBB"), profiles=profiles)
    check = _get(
        _eval(conn, cal, checks=("fundamentals",)), "fundamentals.profile_price"
    )
    assert (check.state, check.reason_code) == (
        CheckState.WARN,
        "PROFILE_PRICE_DIVERGES",
    )
    assert check.counts == {"rows": 2, "diverged": 1, "unknown": 0}
    # A profile dated on a day with no stored close has no matched basis.
    other = _conn(
        _history(cal, "AAA"), profiles=[("AAA", date(2026, 11, 26), "USD", 1.0, 1)]
    )
    check = _get(
        _eval(other, cal, ("AAA",), ("fundamentals",)), "fundamentals.profile_price"
    )
    assert (check.state, check.reason_code) == (CheckState.UNKNOWN, "BASIS_MISMATCH")


def test_profile_table_absent_is_not_evaluated_not_required(cal):
    conn = _conn(_history(cal, "AAA"))
    report = _eval(conn, cal, ("AAA",), ("fundamentals",))
    check = _get(report, "fundamentals.profile_price")
    assert (check.state, check.required) == (CheckState.NOT_EVALUATED, False)
    assert report.data_status == "VALIDATED"


def test_profile_rows_never_leak_into_check_output(cal):
    sentinel = 987654.0
    conn = _conn(_history(cal, "AAA"), profiles=[("AAA", TARGET, "USD", sentinel, 5)])
    report = _eval(conn, cal, ("AAA",), ALL_CHECKS)
    text = json.dumps([c.model_dump(mode="json") for c in report.checks])
    assert "987654" not in text and "AAA" not in text


def test_audit_read_only_integrity_end_to_end(world):  # noqa: F811
    conn = sf.build(
        DISPOSABLE_DB,
        prices=[
            sf.row(s, d)
            for s in ("AAA", "BBB", "SPY")
            for d in sessions.sessions_between(
                sessions.SyntheticCalendar.from_json(FIXTURE),
                date(2026, 10, 1),
                AUDIT_NOW.date(),
            )
        ],
        holidays=CLOSURES_2026_2027,
    )
    make, admit_kwargs = world
    out = readiness.run_audit(
        make(),
        mode="read_only",
        now=AUDIT_NOW,
        calendar=sessions.SyntheticCalendar.from_json(FIXTURE),
        admit_kwargs=admit_kwargs,
        connect_fn=lambda: conn,
        checks=ALL_CHECKS,
    )
    assert (out.outcome, out.exit_code) == ("OK", 0), out.to_line()
    assert out.data_status == "VALIDATED"
    assert conn.writes() == []
    run = Path(os.environ["FMP_SYNC_STATE_ROOT"]) / "runs" / f"{out.run_id}.json"
    ids = {c["check_id"] for c in json.loads(run.read_text("utf-8"))["checks"]}
    assert set(integrity.INTEGRITY_CHECKS) <= ids
    assert _read_only  # fixture helper imported for parity with the T01 suite


def test_audit_invalid_checks_blocks(world):  # noqa: F811
    make, admit_kwargs = world
    out = readiness.run_audit(
        make(),
        mode="dry_run",
        now=AUDIT_NOW,
        calendar=sessions.SyntheticCalendar.from_json(FIXTURE),
        admit_kwargs=admit_kwargs,
        checks=("bogus",),
    )
    assert (out.outcome, out.exit_code) == ("BLOCKED_CONFIG", 40)
