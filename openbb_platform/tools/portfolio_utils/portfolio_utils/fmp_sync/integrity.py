"""Bounded price-integrity checks (#1345-T02).

Every statement is an allowlisted ``SELECT`` (merged into
``readiness.QUERIES``): the window is at most ``max_sessions`` sessions, the
symbol list is capped, and the one row-returning query is ``LIMIT``-ed. Nothing
is deduplicated or rewritten.

Loud empties: zero rows over a window that should have data is
``CRITICAL EMPTY_PARTITION``; a window with no expected session (all holidays)
is ``NOT_APPLICABLE``. A ``NULL`` aggregate (``SUM`` over zero rows) is never
coerced to zero: it is ``UNKNOWN NULL_AGGREGATE``. Outputs carry integer counts
only, never symbols, dates or prices.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_utils.fmp_sync import sessions
from portfolio_utils.fmp_sync.checks import CheckResult, CheckState

INTEGRITY_CHECKS = (
    "integrity.window",
    "integrity.ohlc",
    "integrity.gaps",
    "integrity.jumps",
)
JUMP_THRESHOLD = Decimal("0.30")
_BASIS = (
    "interval_type <=> %s AND adjustment_type <=> %s AND is_valid "
    "AND NOT COALESCE(is_filled, 0)"
)
INTEGRITY_QUERIES: dict[str, str] = {
    "window_aggregate": (
        "SELECT COUNT(*) AS n, "  # noqa: S608
        "SUM(CASE WHEN close IS NULL OR close <= 0 THEN 1 ELSE 0 END) AS bad_close, "
        "SUM(CASE WHEN high < low OR close > high OR close < low "
        "OR open > high OR open < low THEN 1 ELSE 0 END) AS bad_ohlc, "
        "SUM(CASE WHEN volume < 0 THEN 1 ELSE 0 END) AS neg_volume, "
        "SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END) AS zero_volume "
        "FROM equity_historical WHERE symbol IN ({in}) "
        f"AND date BETWEEN %s AND %s AND {_BASIS}"
    ),
    "window_closes": (
        "SELECT symbol, date AS d, close FROM equity_historical "  # noqa: S608
        "WHERE symbol IN ({in}) "
        f"AND date BETWEEN %s AND %s AND {_BASIS} "
        "ORDER BY symbol, date LIMIT %s"
    ),
    "first_dates": (
        "SELECT symbol, MIN(date) AS d FROM equity_historical "  # noqa: S608
        f"WHERE symbol IN ({{in}}) AND {_BASIS} GROUP BY symbol"
    ),
}

Runner = Callable[..., list[dict[str, Any]]]
Failure = Callable[[str, BaseException], CheckResult]


@dataclass(frozen=True)
class IntegrityLimits:
    """Caps applied to every integrity run."""

    max_rows: int = 20000
    max_symbols: int = 200


def _check(check_id: str, state: CheckState, code: str, **counts: int) -> CheckResult:
    return CheckResult(
        check_id=check_id, state=state, reason_code=code, counts=dict(counts)
    )


def _all(state: CheckState, code: str) -> list[CheckResult]:
    return [_check(check_id, state, code) for check_id in INTEGRITY_CHECKS]


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value if not hasattr(value, "date") else value.date()
    return date.fromisoformat(str(value)[:10])


def _num(value: Any) -> int | None:
    """Aggregate to int; ``None`` stays ``None`` (never coerced to zero)."""
    return None if value is None else int(value)


def evaluate(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    run: Runner,
    symbols: Sequence[str],
    window: Sequence[date],
    calendar: sessions.CalendarSource,
    *,
    interval_type: str,
    adjustment_type: str,
    limits: IntegrityLimits | None = None,
    corporate_actions: Mapping[str, set[date]] | None = None,
    failure: Failure,
) -> list[CheckResult]:
    """Window, OHLC, gap and jump checks over ``window`` (already bounded)."""
    lim = limits or IntegrityLimits()
    if not window:
        return _all(CheckState.NOT_APPLICABLE, "NO_EXPECTED_SESSIONS")
    if not symbols:
        return _all(CheckState.NOT_EVALUATED, "NO_SYMBOLS")
    if len(symbols) > lim.max_symbols:
        return _all(CheckState.UNKNOWN, "SYMBOL_CAP_EXCEEDED")
    basis = (interval_type, adjustment_type)
    out = _aggregate_checks(run, symbols, window, basis, failure)
    out += _series_checks(
        run, list(symbols), window, calendar, basis, lim, corporate_actions, failure
    )
    return out


def _aggregate_checks(
    run: Runner,
    symbols: Sequence[str],
    window: Sequence[date],
    basis: tuple[str, str],
    failure: Failure,
) -> list[CheckResult]:
    try:
        row = run(
            "window_aggregate",
            (*symbols, window[0], window[-1], *basis),
            n_in=len(symbols),
        )[0]
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        return [failure(c, exc) for c in ("integrity.window", "integrity.ohlc")]
    rows = int(row["n"])
    if rows == 0:
        window_check = _check(
            "integrity.window", CheckState.CRITICAL, "EMPTY_PARTITION", rows=0
        )
    else:
        window_check = _check(
            "integrity.window", CheckState.OK, "WINDOW_POPULATED", rows=rows
        )
    bad = {key: _num(row[key]) for key in ("bad_close", "bad_ohlc", "neg_volume")}
    zero_volume = _num(row["zero_volume"])
    if zero_volume is None or any(v is None for v in bad.values()):
        ohlc = _check("integrity.ohlc", CheckState.UNKNOWN, "NULL_AGGREGATE")
    elif any(bad.values()):
        ohlc = _check(
            "integrity.ohlc",
            CheckState.CRITICAL,
            "OHLC_INVALID",
            **{k: int(v or 0) for k, v in bad.items()},
        )
    else:
        # Zero volume alone is a real market state (halts), never a defect.
        ohlc = _check(
            "integrity.ohlc", CheckState.OK, "OHLC_SANE", zero_volume=zero_volume
        )
    return [window_check, ohlc]


def _series_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    run: Runner,
    symbols: list[str],
    window: Sequence[date],
    calendar: sessions.CalendarSource,
    basis: tuple[str, str],
    lim: IntegrityLimits,
    corporate_actions: Mapping[str, set[date]] | None,
    failure: Failure,
) -> list[CheckResult]:
    try:
        rows = run(
            "window_closes",
            (*symbols, window[0], window[-1], *basis, lim.max_rows + 1),
            n_in=len(symbols),
        )
        firsts = run("first_dates", (*symbols, *basis), n_in=len(symbols))
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        return [failure(c, exc) for c in ("integrity.gaps", "integrity.jumps")]
    if len(rows) > lim.max_rows:
        return [
            _check(c, CheckState.UNKNOWN, "ROW_CAP_REACHED")
            for c in ("integrity.gaps", "integrity.jumps")
        ]
    series: dict[str, dict[date, Any]] = {s: {} for s in symbols}
    for row in rows:
        day = _date(row["d"])
        if day is not None and str(row["symbol"]) in series:
            series[str(row["symbol"])][day] = row["close"]
    first = {str(r["symbol"]): _date(r["d"]) for r in firsts}
    return [
        _gap_check(series, first, window, calendar),
        _jump_check(series, corporate_actions),
    ]


def _gap_check(
    series: Mapping[str, Mapping[date, Any]],
    first: Mapping[str, date | None],
    window: Sequence[date],
    calendar: sessions.CalendarSource,
) -> CheckResult:
    empty = unknown = gapped = missing = 0
    for symbol, days in series.items():
        if not days:
            empty += 1
            continue
        expected = sessions.expected_sessions(
            calendar, window[0], window[-1], first_stored=first.get(symbol)
        )
        if expected.state is CheckState.UNKNOWN:
            unknown += 1
            continue
        lost = len(set(expected.sessions) - set(days))
        if lost:
            gapped += 1
            missing += lost
    counts = {
        "symbols": len(series),
        "empty": empty,
        "unknown": unknown,
        "gapped": gapped,
        "missing_sessions": missing,
    }
    if empty:
        state, code = CheckState.CRITICAL, "EMPTY_PARTITION"
    elif unknown:
        state, code = CheckState.UNKNOWN, "LIFECYCLE_UNKNOWN"
    elif gapped:
        state, code = CheckState.WARN, "SESSION_GAPS"
    else:
        state, code = CheckState.OK, "SESSIONS_COMPLETE"
    return _check("integrity.gaps", state, code, **counts)


def price_jumps(
    series: Mapping[str, Mapping[date, Any]],
    threshold: Decimal = JUMP_THRESHOLD,
) -> dict[str, list[date]]:
    """Dates whose close moved more than ``threshold`` from the prior stored close."""
    out: dict[str, list[date]] = {}
    for symbol, days in series.items():
        previous: Decimal | None = None
        for day in sorted(days):
            raw = days[day]
            current = Decimal(str(raw)) if raw is not None else None
            if current is None or current <= 0:
                previous = None
                continue
            if previous is not None and abs(current / previous - 1) > threshold:
                out.setdefault(symbol, []).append(day)
            previous = current
    return out


def _jump_check(
    series: Mapping[str, Mapping[date, Any]],
    corporate_actions: Mapping[str, set[date]] | None,
) -> CheckResult:
    jumps = price_jumps(series)
    total = sum(len(v) for v in jumps.values())
    if not total:
        return _check("integrity.jumps", CheckState.OK, "NO_JUMPS", jumps=0)
    if corporate_actions is None:
        # A jump is only a defect if no split/dividend explains it; without
        # complete corporate-action evidence it is not judged.
        return _check(
            "integrity.jumps",
            CheckState.UNKNOWN,
            "CORPORATE_ACTION_EVIDENCE_MISSING",
            jumps=total,
        )
    unexplained = sum(
        1
        for symbol, days in jumps.items()
        for day in days
        if day not in corporate_actions.get(symbol, set())
    )
    if unexplained:
        return _check(
            "integrity.jumps",
            CheckState.WARN,
            "PRICE_JUMP",
            jumps=total,
            unexplained=unexplained,
        )
    return _check("integrity.jumps", CheckState.OK, "JUMPS_EXPLAINED", jumps=total)
