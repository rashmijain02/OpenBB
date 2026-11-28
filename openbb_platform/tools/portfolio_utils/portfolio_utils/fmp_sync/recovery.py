"""Catch-up planning after missed scheduled runs (#1345-T03).

A gateway outage can skip several cron fires. They are coalesced into **one**
budget-limited run: the gap-based warm already covers every missed session, so
the run asks for at most one request per gapped symbol, capped by the #1344
budget (``per_run``), and an open ``defer.json`` window makes it send nothing.
Nothing here sends, retries or re-runs: the plan is a count and a finding code.
The Hermes ``delivery_state`` is unknown to the wrapper and is never an input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from portfolio_utils.fmp_sync import sessions

PT = ZoneInfo("America/Los_Angeles")
CRON_HOUR, CRON_MINUTE = 15, 30  # cron "30 15 * * 1-5" in Pacific time
GRACE = timedelta(minutes=30)
MAX_SCAN_DAYS = 31
FINDING = "CRON_RUN_MISSED"


@dataclass(frozen=True)
class CatchUpPlan:
    """Missed due times since the last attempt, and the single run they need."""

    missed: int = 0

    @property
    def runs(self) -> int:
        """Always at most one run, however many fires were missed."""
        return 1 if self.missed else 0

    @property
    def findings(self) -> tuple[str, ...]:
        """``CRON_RUN_MISSED`` when anything was missed."""
        return (FINDING,) if self.missed else ()


def _last_attempt(status: Mapping[str, Any] | None) -> datetime | None:
    raw = (status or {}).get("last_attempt_utc")
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def plan_catch_up(
    status: Mapping[str, Any] | None,
    *,
    now: datetime,
    calendar: sessions.CalendarSource,
) -> CatchUpPlan:
    """Count scheduled fires (Mon-Fri sessions at 15:30 PT + grace) after the last attempt.

    No recorded attempt, an unreadable stamp or a calendar gap never fabricates a
    miss. Only ``last_attempt_utc`` is read; ``delivery_state`` is ignored.
    """
    last = _last_attempt(status)
    if last is None or now.tzinfo is None:
        return CatchUpPlan()
    day = max(
        last.astimezone(PT).date(),
        (now - timedelta(days=MAX_SCAN_DAYS)).astimezone(PT).date(),
    )
    today = now.astimezone(PT).date()
    missed = 0
    while day <= today:
        due = datetime.combine(day, time(CRON_HOUR, CRON_MINUTE), tzinfo=PT)
        day += timedelta(days=1)
        if due <= last or due + GRACE > now:
            continue
        try:
            if due.weekday() < 5 and calendar.is_session(due.date()):
                missed += 1
        except sessions.CalendarCoverageError:
            break
    return CatchUpPlan(missed)
