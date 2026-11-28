"""Readiness v2: read-only, allowlisted, lifecycle-aware checks (#1345-T01).

``evaluate`` is the body behind the legacy
``fetch_position_history.check_portfolio_app_readiness`` (whose four keys stay)
and behind ``python -m portfolio_utils.fmp_sync audit``.

Read-only by construction: after connecting, the session is switched to
``READ ONLY`` with a per-query time cap (MySQL 8 ``MAX_EXECUTION_TIME``) and a
``READ ONLY`` transaction is started; a failure there runs no query at all. The
transaction is rolled back at the end. Every statement comes from the versioned
:data:`QUERIES` allowlist (fixed identifiers, bound values); anything else is
refused by :class:`ReadOnlySession`.

Private portfolio-table counts are opt-in (``readiness.private_counts`` in the
private map, default off). They are informational (never required), never turn
an unavailable table into a zero, and their values live only in the local run
file -- checks and stdout carry states.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from portfolio_utils.fmp_sync import (
    datasets,
    fundamentals,
    integrity,
    ops_observe,
    sessions,
)
from portfolio_utils.fmp_sync.checks import (
    CheckResult,
    CheckState,
    aggregate,
    findings,
    state_counts,
    utcnow,
)

QUERY_VERSION = 1
REQUIRED_TABLES = ("equity_historical", "market_holidays")
PRIVATE_TABLES = ("Portfolio_Positions", "Account_Owner", "ESPP_Plan")
_IN = "{in}"
QUERIES: dict[str, str] = {
    "ro_session": "SET SESSION TRANSACTION READ ONLY",
    "max_execution_time": "SET SESSION MAX_EXECUTION_TIME = %s",
    "ro_start": "START TRANSACTION READ ONLY",
    "session_database": "SELECT DATABASE() AS db",
    "lower_case_table_names": "SELECT @@lower_case_table_names AS lctn",
    "visible_tables": (
        "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE()"
    ),
    "holiday_dates": (
        "SELECT holiday_date AS d FROM market_holidays "
        "WHERE market = 'US' AND holiday_date BETWEEN %s AND %s"
    ),
    "price_latest": (
        "SELECT symbol, MAX(date) AS max_date FROM equity_historical "
        "WHERE symbol IN ({in}) AND interval_type <=> %s AND adjustment_type <=> %s "
        "AND is_valid AND NOT COALESCE(is_filled, 0) GROUP BY symbol"
    ),
    "null_partition": (
        "SELECT COUNT(*) AS c FROM equity_historical WHERE symbol IN ({in}) "
        "AND date >= %s AND (interval_type IS NULL OR adjustment_type IS NULL)"
    ),
    "duplicate_groups": (
        "SELECT COUNT(*) AS c FROM (SELECT symbol FROM equity_historical "
        "WHERE symbol IN ({in}) AND date >= %s GROUP BY symbol, date, "
        "COALESCE(interval_type, '<null>'), COALESCE(adjustment_type, '<null>') "
        "HAVING COUNT(*) > 1) AS dup"
    ),
    # Fixed identifiers only (no string-built SQL); opt-in, see ReadinessPolicy.
    "private_count:Portfolio_Positions": "SELECT COUNT(*) AS c FROM Portfolio_Positions",
    "private_count:Account_Owner": "SELECT COUNT(*) AS c FROM Account_Owner",
    "private_count:ESPP_Plan": "SELECT COUNT(*) AS c FROM ESPP_Plan",
}
QUERIES.update(integrity.INTEGRITY_QUERIES)
QUERIES.update(fundamentals.FUNDAMENTALS_QUERIES)
_GRANT = {1044, 1142, 1143}
_TABLE_MISSING = 1146
_TIMEOUT = 3024
_DOWN = {2002, 2003, 2006, 2013, 2055}
CORE_DB_CHECKS = (
    "db.session",
    "table.equity_historical",
    "table.market_holidays",
    "calendar.holiday_table",
)
PRICE_CHECKS = ("prices.freshness", "prices.null_partition", "prices.duplicates")
DB_CHECKS = (*CORE_DB_CHECKS, *PRICE_CHECKS)
CHECK_GROUPS = ("readiness", "integrity", "fundamentals", "ops")
_GROUP_IDS = {
    "readiness": PRICE_CHECKS,
    "integrity": integrity.INTEGRITY_CHECKS,
    "fundamentals": ("fundamentals.profile_price",),
    "ops": (),  # file metadata only; never depends on the database
}


class QueryNotAllowed(ValueError):
    """A statement id outside the allowlist was requested."""


class _Abort(Exception):
    def __init__(self, check: CheckResult):
        super().__init__(check.reason_code)
        self.check = check


class ReadinessPolicy(BaseModel):
    """``readiness`` block of the private deployment map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    private_counts: bool = False
    interval_type: str = Field(default="1d", pattern=r"^[0-9a-z_]{1,10}$")
    adjustment_type: str = Field(default="splits_only", pattern=r"^[0-9a-z_]{1,20}$")
    max_sessions: int = Field(default=30, ge=1, le=252)
    query_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    grace_minutes: int = Field(default=120, ge=0, le=720)
    max_rows: int = Field(default=20000, ge=100, le=200000)
    max_symbols: int = Field(default=200, ge=1, le=5000)


def error_code(exc: BaseException) -> int | None:
    """MySQL error number of a pymysql error (``args[0]``), else ``None``."""
    args = getattr(exc, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


class ReadOnlySession:
    """Allowlisted statements over one connection inside a read-only transaction."""

    def __init__(self, conn: Any, timeout_ms: int):
        self.conn = conn
        self.timeout_ms = timeout_ms

    def begin(self) -> None:
        """Read-only session, per-query time cap, read-only transaction."""
        self._execute("ro_session")
        self._execute("max_execution_time", (int(self.timeout_ms),))
        self._execute("ro_start")

    def _execute(self, query_id: str, params: Sequence[Any] = (), n_in: int = 0) -> Any:
        if query_id not in QUERIES:
            raise QueryNotAllowed("statement is not in the readiness allowlist")
        sql = QUERIES[query_id]
        if _IN in sql:
            if n_in < 1:
                raise QueryNotAllowed("IN list needs at least one value")
            sql = sql.replace(_IN, ", ".join(["%s"] * n_in))
        cursor = self.conn.cursor()
        cursor.execute(sql, tuple(params))
        return cursor

    def run(
        self, query_id: str, params: Sequence[Any] = (), n_in: int = 0
    ) -> list[dict[str, Any]]:
        """Run an allowlisted SELECT and return rows as dicts."""
        cursor = self._execute(query_id, params, n_in)
        try:
            rows = cursor.fetchall()
            names = [d[0] for d in (cursor.description or ())]
        finally:
            with contextlib.suppress(Exception):
                cursor.close()
        return [r if isinstance(r, dict) else dict(zip(names, r)) for r in rows]

    def close(self) -> None:
        """Roll back the read-only transaction and close the connection."""
        for action in ("rollback", "close"):
            with contextlib.suppress(Exception):
                getattr(self.conn, action)()


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _check(check_id: str, state: CheckState, code: str, **kw: Any) -> CheckResult:
    return CheckResult(check_id=check_id, state=state, reason_code=code, **kw)


def _query_failure(check_id: str, exc: BaseException, **kw: Any) -> CheckResult:
    code = error_code(exc)
    if code == _TIMEOUT:
        return _check(check_id, CheckState.UNKNOWN, "QUERY_TIMEOUT", **kw)
    if code in _GRANT:
        return _check(check_id, CheckState.UNAVAILABLE, "GRANT_MISSING", **kw)
    if code in _DOWN:
        return _check(check_id, CheckState.UNAVAILABLE, "MYSQL_UNAVAILABLE", **kw)
    return _check(check_id, CheckState.UNAVAILABLE, "QUERY_FAILED", **kw)


@dataclass
class ReadinessReport:  # pylint: disable=too-many-instance-attributes
    """Checks plus the legacy readiness projection; private counts stay local."""

    target_session: date | None
    grace_minutes: int
    calendar_name: str
    calendar_version: str
    checks: list[CheckResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    stale: list[tuple[str, str]] = field(default_factory=list)
    private_counts: dict[str, int] = field(default_factory=dict)
    groups: tuple[str, ...] = ("readiness",)

    @property
    def data_status(self) -> str:
        """Aggregate over required checks (no fabricated health)."""
        return aggregate(self.checks)

    def calendar(self) -> dict[str, Any]:
        """Calendar provenance (name, version, target session, grace)."""
        return {
            "name": self.calendar_name,
            "version": self.calendar_version,
            "target_session": str(self.target_session) if self.target_session else None,
            "grace_minutes": self.grace_minutes,
        }

    def legacy(self) -> dict[str, Any]:
        """Legacy four keys plus ``checks``, ``data_status`` and ``calendar``."""
        return {
            "target_date": str(self.target_session) if self.target_session else None,
            "table_counts": dict(self.private_counts),
            "missing_price_symbols": list(self.missing),
            "stale_price_symbols": list(self.stale),
            "checks": [c.model_dump(mode="json") for c in self.checks],
            "data_status": self.data_status,
            "calendar": self.calendar(),
        }


def evaluate(  # pylint: disable=too-many-arguments
    symbols: Sequence[str],
    *,
    now: datetime,
    calendar: sessions.CalendarSource | None = None,
    policy: ReadinessPolicy | Mapping[str, Any] | None = None,
    connect_fn: Callable[[], Any] | None = None,
    database: str | None = None,
    exclusions: int = 0,
    dry_run: bool = False,
    checks: Sequence[str] = ("readiness",),
    ops_policy: ops_observe.OpsPolicy | Mapping[str, Any] | None = None,
    disk_usage_fn: Callable[[str], Any] | None = None,
    ops_state_root: Path | None = None,
    ops_attested: bool = False,
) -> ReadinessReport:
    """Evaluate calendar, session, table and price checks for ``symbols``.

    ``checks`` selects groups beyond the always-on core: ``readiness`` (price
    freshness, NULL partitions, duplicates), ``integrity`` and ``fundamentals``.
    """
    groups = tuple(g for g in CHECK_GROUPS if g in set(checks))
    pol = (
        policy
        if isinstance(policy, ReadinessPolicy)
        else ReadinessPolicy(**(policy or {}))
    )
    cal = calendar or sessions.xnys_for(now)
    grace = timedelta(minutes=pol.grace_minutes)
    report = ReadinessReport(
        None, pol.grace_minutes, cal.name, cal.version, groups=groups
    )
    try:
        report.target_session = sessions.target_session(now, cal, grace)
        report.checks.append(_check("session.target", CheckState.OK, "TARGET_SESSION"))
    except sessions.CalendarCoverageError:
        report.checks.append(
            _check("session.target", CheckState.BLOCKED, "CALENDAR_COVERAGE_MISSING")
        )
    if exclusions:
        report.checks.append(
            _check(
                "prices.exclusions",
                CheckState.NOT_APPLICABLE,
                "EXCLUDED_SYMBOLS",
                counts={"excluded": exclusions},
                required=False,
            )
        )
    if "fundamentals" in groups:
        report.checks.extend(fundamentals.json_blob_sources())
    if "ops" in groups:
        report.checks.extend(
            ops_observe.evaluate(
                ops_policy,
                now=now,
                **({"disk_usage_fn": disk_usage_fn} if disk_usage_fn else {}),
                state_root=ops_state_root,
                attested=ops_attested,
            )
        )
    skip = "DRY_RUN_NO_DB" if dry_run or connect_fn is None else None
    if not symbols and skip is None:
        skip = "NO_SYMBOLS"
    if skip or report.target_session is None or connect_fn is None:
        report.checks.append(sessions.coverage_check(cal, now))
        _not_evaluated(report, skip or "CALENDAR_COVERAGE_MISSING", pol)
        return report
    _evaluate_db(report, list(symbols), now, cal, pol, connect_fn, database)
    return report


def _not_evaluated(report: ReadinessReport, code: str, pol: ReadinessPolicy) -> None:
    done = {c.check_id for c in report.checks}
    ids = [
        *CORE_DB_CHECKS,
        *(i for g in report.groups for i in _GROUP_IDS[g]),
        *(f"private.{t}" for t in PRIVATE_TABLES if pol.private_counts),
    ]
    for check_id in ids:
        if check_id not in done:
            report.checks.append(
                _check(
                    check_id,
                    CheckState.NOT_EVALUATED,
                    code,
                    required=not check_id.startswith("private."),
                )
            )


def _evaluate_db(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    report: ReadinessReport,
    symbols: list[str],
    now: datetime,
    cal: sessions.CalendarSource,
    pol: ReadinessPolicy,
    connect_fn: Callable[[], Any],
    database: str | None,
) -> None:
    try:
        conn = connect_fn()
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        code = error_code(exc)
        reason = (
            "MYSQL_UNAVAILABLE" if code is None or code in _DOWN else "CONNECT_FAILED"
        )
        report.checks.append(_check("db.session", CheckState.UNAVAILABLE, reason))
        report.checks.append(sessions.coverage_check(cal, now))
        _not_evaluated(report, "DB_UNAVAILABLE", pol)
        return
    session = ReadOnlySession(conn, pol.query_timeout_ms)
    try:
        _db_checks(report, session, symbols, now, cal, pol, database)
    except _Abort as abort:
        report.checks.append(abort.check)
        if not any(c.check_id == "calendar.coverage" for c in report.checks):
            report.checks.append(sessions.coverage_check(cal, now))
        _not_evaluated(report, "DB_CHECK_ABORTED", pol)
    finally:
        session.close()


def _db_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    report: ReadinessReport,
    session: ReadOnlySession,
    symbols: list[str],
    now: datetime,
    cal: sessions.CalendarSource,
    pol: ReadinessPolicy,
    database: str | None,
) -> None:
    try:
        session.begin()
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        reason = (
            "MYSQL_UNAVAILABLE"
            if error_code(exc) in _DOWN
            else "READ_ONLY_SETUP_FAILED"
        )
        raise _Abort(_check("db.session", CheckState.UNAVAILABLE, reason)) from None
    try:
        rows = session.run("session_database")
        lctn = session.run("lower_case_table_names")[0].get("lctn")
        visible = {str(r["name"]) for r in session.run("visible_tables")}
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        raise _Abort(_query_failure("db.session", exc)) from None
    current = rows[0].get("db") if rows else None
    if database and (
        not isinstance(current, str) or current.lower() != database.lower()
    ):
        raise _Abort(
            _check("db.session", CheckState.BLOCKED, "SESSION_DATABASE_MISMATCH")
        )
    report.checks.append(_check("db.session", CheckState.OK, "READ_ONLY_SESSION"))
    case_insensitive = str(lctn) in ("1", "2")
    present = {
        name: _table_state(name, visible, case_insensitive) for name in REQUIRED_TABLES
    }
    for name, check in present.items():
        report.checks.append(check)
    _holiday_checks(report, session, now, cal, present["market_holidays"])
    if present["equity_historical"].state is CheckState.CRITICAL:
        for check_id in (i for g in report.groups for i in _GROUP_IDS[g]):
            report.checks.append(
                _check(check_id, CheckState.NOT_EVALUATED, "TABLE_MISSING")
            )
    else:
        if "readiness" in report.groups:
            _price_checks(report, session, symbols, cal, pol)
        if "integrity" in report.groups:
            _integrity_checks(report, session, symbols, cal, pol)
        if "fundamentals" in report.groups:
            _fundamentals_checks(report, session, symbols, visible, pol)
    if pol.private_counts:
        _private_counts(report, session, visible, case_insensitive)


def _integrity_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    report: ReadinessReport,
    session: ReadOnlySession,
    symbols: list[str],
    cal: sessions.CalendarSource,
    pol: ReadinessPolicy,
) -> None:
    target = report.target_session
    if target is None:
        return
    window = sessions.sessions_between(cal, cal.first_day, target)[-pol.max_sessions :]
    report.checks.extend(
        integrity.evaluate(
            session.run,
            symbols,
            window,
            cal,
            interval_type=pol.interval_type,
            adjustment_type=pol.adjustment_type,
            limits=integrity.IntegrityLimits(pol.max_rows, pol.max_symbols),
            failure=_query_failure,
        )
    )


def _fundamentals_checks(
    report: ReadinessReport,
    session: ReadOnlySession,
    symbols: list[str],
    visible: set[str],
    pol: ReadinessPolicy,
) -> None:
    if "equity_profile" not in visible:
        # Source absent: nothing to judge, and not a defect of the audited data.
        report.checks.append(
            _check(
                "fundamentals.profile_price",
                CheckState.NOT_EVALUATED,
                "SOURCE_TABLE_ABSENT",
                required=False,
            )
        )
        return
    report.checks.append(
        fundamentals.evaluate_profiles(
            session.run,
            symbols,
            interval_type=pol.interval_type,
            adjustment_type=pol.adjustment_type,
            max_rows=pol.max_rows,
            failure=_query_failure,
        )
    )


def _table_state(name: str, visible: set[str], case_insensitive: bool) -> CheckResult:
    check_id = f"table.{name}"
    if name in visible:
        return _check(check_id, CheckState.OK, "TABLE_PRESENT")
    if name.lower() in {v.lower() for v in visible}:
        if case_insensitive:
            return _check(check_id, CheckState.OK, "TABLE_PRESENT_CASE_FOLDED")
        return _check(check_id, CheckState.WARN, "TABLE_CASE_MISMATCH")
    return _check(check_id, CheckState.CRITICAL, "TABLE_MISSING")


def _holiday_checks(  # pylint: disable=too-many-arguments
    report: ReadinessReport,
    session: ReadOnlySession,
    now: datetime,
    cal: sessions.CalendarSource,
    table: CheckResult,
) -> None:
    year = now.astimezone(sessions.ET).year
    start, end = date(year, 1, 1), min(date(year + 1, 12, 31), cal.last_day)
    if table.state is CheckState.CRITICAL:
        report.checks.append(sessions.coverage_check(cal, now))
        report.checks.append(
            _check("calendar.holiday_table", CheckState.NOT_EVALUATED, "TABLE_MISSING")
        )
        return
    try:
        rows = session.run("holiday_dates", (start, end))
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        report.checks.append(sessions.coverage_check(cal, now))
        report.checks.append(_query_failure("calendar.holiday_table", exc))
        return
    dates = {d for d in (_as_date(r["d"]) for r in rows) if d is not None}
    report.checks.append(
        sessions.coverage_check(cal, now, holiday_years={d.year for d in dates})
    )
    report.checks.append(sessions.holiday_cross_check(cal, dates, start, end))


def _price_checks(
    report: ReadinessReport,
    session: ReadOnlySession,
    symbols: list[str],
    cal: sessions.CalendarSource,
    pol: ReadinessPolicy,
) -> None:
    target = report.target_session
    if target is None:  # evaluate() never reaches the DB without a target
        return
    ambiguous = datasets.semantics_check("equity_historical.date", "DATE_ET_SESSION")
    if ambiguous is not None:
        report.checks.append(
            ambiguous.model_copy(update={"check_id": "prices.freshness"})
        )
    else:
        try:
            rows = session.run(
                "price_latest",
                (*symbols, pol.interval_type, pol.adjustment_type),
                n_in=len(symbols),
            )
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            report.checks.append(_query_failure("prices.freshness", exc))
        else:
            latest = {str(r["symbol"]): _as_date(r["max_date"]) for r in rows}
            report.checks.append(_freshness(report, symbols, latest, cal, target))
    window = sessions.sessions_between(cal, cal.first_day, target)[-pol.max_sessions :]
    since = window[0] if window else target
    for check_id, query_id, code, key in (
        ("prices.null_partition", "null_partition", "NULL_PARTITION", "rows"),
        ("prices.duplicates", "duplicate_groups", "DUPLICATE_KEYS", "groups"),
    ):
        try:
            count = session.run(query_id, (*symbols, since), n_in=len(symbols))[0]["c"]
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            report.checks.append(_query_failure(check_id, exc))
            continue
        if count is None:
            report.checks.append(_check(check_id, CheckState.UNKNOWN, "NULL_AGGREGATE"))
            continue
        state = CheckState.WARN if int(count) else CheckState.OK
        report.checks.append(
            _check(check_id, state, code if count else "NONE", counts={key: int(count)})
        )


def _freshness(
    report: ReadinessReport,
    symbols: list[str],
    latest: Mapping[str, date | None],
    cal: sessions.CalendarSource,
    target: date,
) -> CheckResult:
    """0 missed sessions OK, 1 WARN, 2+ CRITICAL; no history CRITICAL."""
    counts = {"ok": 0, "warn": 0, "critical": 0, "missing": 0}
    for symbol in symbols:
        last = latest.get(symbol)
        if last is None:
            counts["missing"] += 1
            report.missing.append(symbol)
            continue
        if last < target:
            report.stale.append((symbol, str(last)))
        try:
            missed = sessions.missed_sessions(cal, last, target)
        except sessions.CalendarCoverageError:
            missed = 2
        counts["ok" if missed == 0 else "warn" if missed == 1 else "critical"] += 1
    if counts["critical"] or counts["missing"]:
        state, code = CheckState.CRITICAL, "PRICES_STALE"
    elif counts["warn"]:
        state, code = CheckState.WARN, "PRICES_ONE_SESSION_BEHIND"
    else:
        state, code = CheckState.OK, "PRICES_FRESH"
    return _check("prices.freshness", state, code, counts=counts)


def _private_counts(
    report: ReadinessReport,
    session: ReadOnlySession,
    visible: set[str],
    case_insensitive: bool,
) -> None:
    folded = {v.lower() for v in visible}
    for name in PRIVATE_TABLES:
        check_id = f"private.{name}"

        def _state(state: CheckState, code: str, cid: str = check_id) -> None:
            report.checks.append(_check(cid, state, code, required=False))

        if name not in visible and name.lower() in folded and not case_insensitive:
            _state(CheckState.WARN, "TABLE_CASE_MISMATCH")
            continue
        try:
            value = session.run(f"private_count:{name}")[0]["c"]
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            code = error_code(exc)
            if code in _GRANT:
                _state(CheckState.UNAVAILABLE, "GRANT_MISSING")
            elif code == _TABLE_MISSING:
                _state(CheckState.WARN, "TABLE_MISSING")
            elif name.lower() not in folded:
                _state(CheckState.UNAVAILABLE, "NOT_VISIBLE")
            else:
                report.checks.append(
                    _query_failure(check_id, exc).model_copy(update={"required": False})
                )
            continue
        if value is None:
            _state(CheckState.UNKNOWN, "NULL_AGGREGATE")
            continue
        report.private_counts[name] = int(value)
        _state(CheckState.OK, "COUNTED")


# --------------------------------------------------------------------- audit


@dataclass
class AuditResult:  # pylint: disable=too-many-instance-attributes
    """Outcome of ``audit``: states and codes on stdout, counts in the run file."""

    run_id: str
    mode: str
    outcome: str
    exit_code: int
    data_status: str
    target_session: str | None = None
    findings: tuple[str, ...] = ()
    states: dict[str, int] = field(default_factory=dict)
    report: ReadinessReport | None = None

    def to_line(self) -> str:
        """One counts-free JSON line (max 512 characters)."""
        import json  # pylint: disable=import-outside-toplevel

        payload = {
            "op": "audit",
            "mode": self.mode,
            "run_id": self.run_id,
            "outcome": self.outcome,
            "exit": self.exit_code,
            "data_status": self.data_status,
            "target_session": self.target_session,
            "findings": list(self.findings)[:8],
            "states": self.states,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))[:512]

    def run_payload(self) -> dict[str, Any]:
        """Local ``runs/<run_id>.json`` body (includes opt-in private counts)."""
        report = self.report
        return {
            "op": "audit",
            "mode": self.mode,
            "outcome": self.outcome,
            "exit": self.exit_code,
            "data_status": self.data_status,
            "query_version": QUERY_VERSION,
            "calendar": report.calendar() if report else None,
            "checks": (
                [c.model_dump(mode="json") for c in report.checks] if report else []
            ),
            "private_counts": dict(report.private_counts) if report else {},
        }


AuditMode = Literal["dry_run", "read_only"]


def _result(
    run_id: str, mode: str, outcome: str, code: int, *found: str
) -> AuditResult:
    return AuditResult(
        run_id, mode, outcome, code, "UNVALIDATED", findings=tuple(found)
    )


def run_audit(  # pylint: disable=too-many-arguments,too-many-locals
    dmap: Any,
    *,
    mode: AuditMode,
    now: datetime,
    requested_class: Literal["disposable", "production"] = "disposable",
    run_id: str | None = None,
    calendar: sessions.CalendarSource | None = None,
    admit_fn: Callable[..., Any] | None = None,
    admit_kwargs: Mapping[str, Any] | None = None,
    connect_fn: Callable[[], Any] | None = None,
    state_root: Path | None = None,
    checks: Sequence[str] = ("readiness",),
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> AuditResult:
    """Dry-run (no socket) or read-only audit; never takes the target lock, never writes data."""
    # pylint: disable=import-outside-toplevel
    from portfolio_utils.fmp_sync import admission, locking, state

    run_id = run_id or uuid.uuid4().hex
    if now.tzinfo is None:
        return _result(run_id, mode, "BLOCKED_CONFIG", 40, "NAIVE_NOW")
    if not checks or any(c not in CHECK_GROUPS for c in checks):
        return _result(run_id, mode, "BLOCKED_CONFIG", 40, "INVALID_CHECKS")
    try:
        locking.resolve_lock_database(dmap.target)
        pol = ReadinessPolicy(**(getattr(dmap, "readiness", None) or {}))
        ops_pol = ops_observe.OpsPolicy(**(getattr(dmap, "ops", None) or {}))
    except ValueError:
        return _result(run_id, mode, "BLOCKED_CONFIG", 40, "INVALID_CONFIG")
    root = None
    if mode == "read_only":
        root = locking.validate_state_root(
            state_root
            or (
                Path(dmap.state_root)
                if dmap.state_root
                else locking.default_state_root()
            )
        )
    symbols: list[str] = []
    exclusions = 0

    def default_connect() -> Any:
        # pylint: disable-next=protected-access
        return admission._default_connect(dmap.target)

    if mode == "read_only":
        adm = (admit_fn or admission.admit)(
            dmap,
            mode="dry_run",
            requested_class=requested_class,
            **(admit_kwargs or {}),
        )
        if not adm.admitted:
            return _result(run_id, mode, adm.code, adm.exit_code, *adm.findings)
        symbols = list(adm.symbols or ())
        exclusions = int(adm.counts.get("skipped", 0))
    report = evaluate(
        symbols,
        now=now,
        calendar=calendar,
        policy=pol,
        connect_fn=None if mode == "dry_run" else connect_fn or default_connect,
        database=dmap.target,
        exclusions=exclusions,
        dry_run=mode == "dry_run",
        checks=checks,
        ops_policy=ops_pol,
        disk_usage_fn=disk_usage_fn,
        ops_state_root=root,
        ops_attested=bool(getattr(dmap, "ops_attest_ref", None)),
    )
    db = next((c for c in report.checks if c.check_id == "db.session"), None)
    outcome, code = "OK", 0
    if db is not None and db.state is CheckState.UNAVAILABLE:
        outcome, code = "FAILED_INFRA", 30
    elif db is not None and db.reason_code == "SESSION_DATABASE_MISMATCH":
        outcome, code = "BLOCKED_DATABASE", 40
    result = AuditResult(
        run_id,
        mode,
        outcome,
        code,
        report.data_status,
        str(report.target_session) if report.target_session else None,
        findings(report.checks),
        state_counts(report.checks),
        report,
    )
    if root is not None:
        written = state.atomic_write_json(
            root / "runs" / f"{run_id}.json", result.run_payload()
        )
        if not getattr(written, "ok", True):
            result.findings = (*result.findings, "RUN_FILE_WRITE_FAILED")
    return result


def utc_now() -> datetime:
    """Aware UTC now (re-exported for the CLI)."""
    return utcnow()
