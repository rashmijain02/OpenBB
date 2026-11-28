"""Declared timestamp semantics of the datasets readiness reads (#1345-T01).

Every timestamp a check compares must have declared semantics. Undeclared
datasets, and host-local wall-clock values that fall in a DST fold or gap, are
``UNKNOWN AMBIGUOUS_TIMESTAMP``: freshness is never guessed from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from portfolio_utils.fmp_sync.checks import CheckResult, CheckState

TimestampSemantics = Literal["DATE_ET_SESSION", "DATETIME_UTC", "DATETIME_HOST_LOCAL"]


@dataclass(frozen=True)
class DatasetSpec:
    """One dataset column readiness may compare against a session or instant."""

    table: str
    column: str
    timestamp_semantics: TimestampSemantics


DATASETS: dict[str, DatasetSpec] = {
    "equity_historical.date": DatasetSpec(
        "equity_historical", "date", "DATE_ET_SESSION"
    ),
    "equity_historical.cached_at": DatasetSpec(
        "equity_historical", "cached_at", "DATETIME_HOST_LOCAL"
    ),
    "market_holidays.holiday_date": DatasetSpec(
        "market_holidays", "holiday_date", "DATE_ET_SESSION"
    ),
}


def _ambiguous(check_id: str) -> CheckResult:
    return CheckResult(
        check_id=check_id, state=CheckState.UNKNOWN, reason_code="AMBIGUOUS_TIMESTAMP"
    )


def semantics_check(dataset: str, expected: TimestampSemantics) -> CheckResult | None:
    """``None`` when ``dataset`` is declared with ``expected`` semantics, else UNKNOWN."""
    spec = DATASETS.get(dataset)
    if spec is None or spec.timestamp_semantics != expected:
        return _ambiguous(f"timestamp.{dataset}")
    return None


def resolve_instant(
    dataset: str, value: datetime | date, host_tz: str
) -> datetime | CheckResult:
    """Return an aware UTC instant, or ``UNKNOWN AMBIGUOUS_TIMESTAMP``.

    ``DATETIME_HOST_LOCAL`` values are interpreted in ``host_tz``; a value in a
    DST fold (two instants) or gap (no instant) is ambiguous. Dates are never
    instants.
    """
    spec = DATASETS.get(dataset)
    check_id = f"timestamp.{dataset}"
    if spec is None or not isinstance(value, datetime):
        return _ambiguous(check_id)
    if spec.timestamp_semantics == "DATETIME_UTC":
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo("UTC"))
        return value.astimezone(ZoneInfo("UTC"))
    if spec.timestamp_semantics != "DATETIME_HOST_LOCAL" or value.tzinfo is not None:
        return _ambiguous(check_id)
    zone = ZoneInfo(host_tz)
    early = value.replace(tzinfo=zone, fold=0)
    late = value.replace(tzinfo=zone, fold=1)
    if early.utcoffset() != late.utcoffset():
        return _ambiguous(check_id)
    # In a fold the two readings are an hour apart; in a gap zoneinfo also
    # returns different offsets per fold. Either way the instant is unknown.
    return early.astimezone(ZoneInfo("UTC"))
