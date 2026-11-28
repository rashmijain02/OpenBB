"""Matched-basis fundamental diagnostics (#1345-T02).

Pure functions over normalized inputs. A comparison between two quantities is
only made when their basis (share class, unit, currency, as-of date and split
basis) matches on every field and every field is known; otherwise the result is
``UNKNOWN BASIS_MISMATCH`` -- a diagnostic never guesses across bases. Missing
inputs are ``UNKNOWN MISSING_INPUT`` and are never ``OK``.

JSON-blob sources (``shares_float_all``, ``analyst_estimates``) have no
qualified typed read interface yet and are ``NOT_EVALUATED
SOURCE_NOT_ADMITTED``. The only database adapter reads typed
``equity_profile.price/currency`` against the same-date ``equity_historical``
close. Results carry integer counts only, never prices, shares or symbols.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_utils.fmp_sync.checks import CheckResult, CheckState

MCAP_DIVERGENCE = Decimal("0.15")
PRICE_DIVERGENCE = Decimal("0.15")
REPEAT_QUARTERS = 3
BLOB_SOURCES = {
    "fundamentals.shares_float": "shares_float_all",
    "fundamentals.analyst_estimates": "analyst_estimates",
}
FUNDAMENTALS_QUERIES: dict[str, str] = {
    "profile_price": (
        "SELECT p.symbol AS symbol, p.price AS price, p.currency AS currency, "
        "h.close AS close FROM equity_profile p "
        "LEFT JOIN equity_historical h ON h.symbol = p.symbol AND h.date = p.date "
        "AND h.interval_type <=> %s AND h.adjustment_type <=> %s AND h.is_valid "
        "AND NOT COALESCE(h.is_filled, 0) "
        "WHERE p.symbol IN ({in}) AND p.price IS NOT NULL LIMIT %s"
    ),
}


@dataclass(frozen=True)
class Basis:
    """What a number is measured in; every field must be known to compare."""

    share_class: str | None = None
    unit: str | None = None
    currency: str | None = None
    as_of: date | None = None
    split_basis: date | None = None

    def complete(self) -> bool:
        """Return whether no field is unknown."""
        return None not in (
            self.share_class,
            self.unit,
            self.currency,
            self.as_of,
            self.split_basis,
        )


@dataclass(frozen=True)
class Quantity:
    """A value with its basis and source tag."""

    value: Decimal | None
    basis: Basis
    source: str = ""


def _result(check_id: str, state: CheckState, code: str, **counts: int) -> CheckResult:
    return CheckResult(
        check_id=check_id, state=state, reason_code=code, counts=dict(counts)
    )


def _unknown_inputs(check_id: str, *quantities: Quantity | None) -> CheckResult | None:
    """``UNKNOWN`` when an input is missing or the bases do not match exactly."""
    if any(q is None or q.value is None for q in quantities):
        return _result(check_id, CheckState.UNKNOWN, "MISSING_INPUT")
    bases = [q.basis for q in quantities if q is not None]
    if not all(b.complete() for b in bases) or any(b != bases[0] for b in bases):
        return _result(check_id, CheckState.UNKNOWN, "BASIS_MISMATCH")
    return None


def float_vs_outstanding(
    shares_float: Quantity | None, outstanding: Quantity | None
) -> CheckResult:
    """Float above shares outstanding (same class/unit/date/split basis) is ``WARN``."""
    check_id = "fundamentals.float_vs_outstanding"
    unknown = _unknown_inputs(check_id, shares_float, outstanding)
    if unknown is not None:
        return unknown
    if (
        shares_float is None
        or outstanding is None
        or shares_float.value is None
        or outstanding.value is None
    ):
        return _result(check_id, CheckState.UNKNOWN, "MISSING_INPUT")
    if shares_float.value > outstanding.value:
        return _result(check_id, CheckState.WARN, "FLOAT_EXCEEDS_OUTSTANDING")
    return _result(check_id, CheckState.OK, "FLOAT_WITHIN_OUTSTANDING")


def market_cap_divergence(
    market_cap: Quantity | None, price: Quantity | None, shares: Quantity | None
) -> CheckResult:
    """``abs(mcap / (price * shares) - 1)`` above 0.15 is ``WARN`` (0.15 exactly is OK)."""
    check_id = "fundamentals.market_cap"
    unknown = _unknown_inputs(check_id, market_cap, price, shares)
    if unknown is not None:
        return unknown
    cap = market_cap.value if market_cap else None
    px = price.value if price else None
    count = shares.value if shares else None
    if cap is None or px is None or count is None or px * count <= 0:
        return _result(check_id, CheckState.UNKNOWN, "MISSING_INPUT")
    implied = px * count
    if abs(cap - implied) > MCAP_DIVERGENCE * implied:
        return _result(check_id, CheckState.WARN, "MARKET_CAP_DIVERGES")
    return _result(check_id, CheckState.OK, "MARKET_CAP_CONSISTENT")


def repeated_diluted_shares(
    quarters: Iterable[tuple[date, Decimal | None]],
) -> CheckResult:
    """Identical diluted weighted shares for 3+ consecutive distinct quarters is ``WARN``.

    A repeat is an inspection prompt, not proof of error. Fewer than three
    distinct quarters cannot be judged (``UNKNOWN``); a missing value breaks a run.
    """
    check_id = "fundamentals.diluted_shares"
    by_period = dict(quarters)
    ordered = [by_period[p] for p in sorted(by_period)]
    if len(ordered) < REPEAT_QUARTERS:
        return _result(check_id, CheckState.UNKNOWN, "INSUFFICIENT_HISTORY")
    longest = run = 0
    prev: Decimal | None = None
    for value in ordered:
        if value is None:
            run = 0
        elif prev is not None and value == prev:
            run += 1
        else:
            run = 1
        prev = value
        longest = max(longest, run)
    if longest >= REPEAT_QUARTERS:
        return _result(
            check_id, CheckState.WARN, "REPEATED_DILUTED_SHARES", longest_run=longest
        )
    return _result(check_id, CheckState.OK, "SHARES_VARY", longest_run=longest)


def current_fy_estimates(
    estimate_years: Iterable[int] | None, current_fy: int
) -> CheckResult:
    """No estimate for the current fiscal year is ``WARN``; unknown inputs ``UNKNOWN``."""
    check_id = "fundamentals.current_fy_estimates"
    if estimate_years is None:
        return _result(check_id, CheckState.UNKNOWN, "MISSING_INPUT")
    if current_fy in set(estimate_years):
        return _result(check_id, CheckState.OK, "CURRENT_FY_ESTIMATES_PRESENT")
    return _result(check_id, CheckState.WARN, "CURRENT_FY_ESTIMATES_MISSING")


def json_blob_sources(required: bool = False) -> list[CheckResult]:
    """``NOT_EVALUATED SOURCE_NOT_ADMITTED`` for JSON-blob sources (not a defect)."""
    return [
        CheckResult(
            check_id=check_id,
            state=CheckState.NOT_EVALUATED,
            reason_code="SOURCE_NOT_ADMITTED",
            required=required,
        )
        for check_id in BLOB_SOURCES
    ]


def profile_price_check(rows: Sequence[dict[str, Any]]) -> CheckResult:
    """Profile price vs the same-date stored close; counts only.

    A row without a currency or without a close on the profile's own date has no
    matched basis and is ``unknown``; a divergence above 15% is ``diverged``.
    """
    check_id = "fundamentals.profile_price"
    if not rows:
        return _result(check_id, CheckState.UNKNOWN, "NO_PROFILE_ROWS", rows=0)
    diverged = unknown = 0
    for row in rows:
        price, close = row.get("price"), row.get("close")
        if (
            row.get("currency") in (None, "")
            or close is None
            or Decimal(str(close)) <= 0
        ):
            unknown += 1
        elif abs(Decimal(str(price)) / Decimal(str(close)) - 1) > PRICE_DIVERGENCE:
            diverged += 1
    counts = {"rows": len(rows), "diverged": diverged, "unknown": unknown}
    if unknown:
        return _result(check_id, CheckState.UNKNOWN, "BASIS_MISMATCH", **counts)
    if diverged:
        return _result(check_id, CheckState.WARN, "PROFILE_PRICE_DIVERGES", **counts)
    return _result(check_id, CheckState.OK, "PROFILE_PRICE_CONSISTENT", **counts)


def evaluate_profiles(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    run: Callable[..., list[dict[str, Any]]],
    symbols: Sequence[str],
    *,
    interval_type: str,
    adjustment_type: str,
    max_rows: int,
    failure: Callable[[str, BaseException], CheckResult],
) -> CheckResult:
    """Run the allowlisted profile query (capped) and judge it."""
    if not symbols:
        return _result(
            "fundamentals.profile_price", CheckState.NOT_EVALUATED, "NO_SYMBOLS"
        )
    try:
        rows = run(
            "profile_price",
            (interval_type, adjustment_type, *symbols, max_rows + 1),
            n_in=len(symbols),
        )
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        return failure("fundamentals.profile_price", exc)
    if len(rows) > max_rows:
        return _result(
            "fundamentals.profile_price", CheckState.UNKNOWN, "ROW_CAP_REACHED"
        )
    return profile_price_check(rows)
