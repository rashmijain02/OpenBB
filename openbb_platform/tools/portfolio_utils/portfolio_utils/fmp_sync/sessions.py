"""Lifecycle-aware NYSE sessions (#1345-T01, lead decisions E1/E2).

``exchange_calendars`` XNYS is the session authority, built with an explicit
``start``/``end`` (never the library's import-day default end). The
``market_holidays`` table is only cross-checked against it. Every function takes
an injected :class:`CalendarSource`, so tests use a synthetic calendar.

``target_session(now)`` is the last session whose *actual* close (16:00 ET, or
13:00 ET on a half day) plus the publication grace (2 h) is at or before
``now``. A naive ``now`` is rejected: host-local wall clock is never trusted.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from portfolio_utils.fmp_sync.checks import CheckResult, CheckState

ET = ZoneInfo("America/New_York")
DEFAULT_GRACE = timedelta(hours=2)
REGULAR_CLOSE = time(16, 0)
NEXT_YEAR_BLOCK_MONTH = 12  # from Dec 1 a missing next year blocks execute


class CalendarCoverageError(ValueError):
    """The requested instant or range is outside the calendar's coverage."""


class CalendarSource(Protocol):
    """Minimal session calendar interface (dates are Eastern session dates)."""

    name: str
    version: str
    first_day: date
    last_day: date

    def is_session(self, day: date) -> bool:
        """Return whether ``day`` is a trading session."""

    def close_et(self, day: date) -> time:
        """Actual Eastern close of session ``day``."""


@dataclass
class SyntheticCalendar:
    """Weekdays minus ``holidays``; ``half_days`` maps a session to its early close."""

    first_day: date
    last_day: date
    holidays: frozenset[date] = frozenset()
    half_days: dict[date, time] = field(default_factory=dict)
    name: str = "synthetic"
    version: str = "synthetic"

    @classmethod
    def from_json(cls, path: Path) -> SyntheticCalendar:
        """Load the fixture shape ``{first_day, last_day, holidays, half_days}``."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            date.fromisoformat(data["first_day"]),
            date.fromisoformat(data["last_day"]),
            frozenset(date.fromisoformat(d) for d in data["holidays"]),
            {
                date.fromisoformat(d): time.fromisoformat(t)
                for d, t in data.get("half_days", {}).items()
            },
        )

    def is_session(self, day: date) -> bool:
        """Weekday, inside coverage and not a holiday."""
        return (
            self.first_day <= day <= self.last_day
            and day.weekday() < 5
            and day not in self.holidays
        )

    def close_et(self, day: date) -> time:
        """Half-day close or 16:00."""
        return self.half_days.get(day, REGULAR_CLOSE)


class XnysCalendar:
    """``exchange_calendars`` XNYS over an explicit ``[start, end]`` range."""

    name = "XNYS"

    def __init__(self, start: date, end: date):
        import exchange_calendars  # pylint: disable=import-outside-toplevel

        cal = exchange_calendars.get_calendar(
            "XNYS", start=start.isoformat(), end=end.isoformat()
        )
        self.version = str(getattr(exchange_calendars, "__version__", "unknown"))
        self.first_day = start
        self.last_day = end
        self._closes: dict[date, time] = {}
        for session in cal.sessions:
            close = cal.session_close(session).tz_convert(ET)
            self._closes[session.date()] = time(close.hour, close.minute)

    def is_session(self, day: date) -> bool:
        """Return whether ``day`` is an XNYS session inside the built range."""
        return day in self._closes

    def close_et(self, day: date) -> time:
        """Actual Eastern close (13:00 on half days)."""
        return self._closes[day]


def xnys_for(now: datetime) -> XnysCalendar:
    """XNYS from Jan 1 of last year through Dec 31 of ``current_year + 1``."""
    year = _eastern(now).year
    return XnysCalendar(date(year - 1, 1, 1), date(year + 1, 12, 31))


def _eastern(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ET)


def close_instant(calendar: CalendarSource, day: date) -> datetime:
    """Aware Eastern datetime of the session's actual close."""
    return datetime.combine(day, calendar.close_et(day), tzinfo=ET)


def sessions_between(calendar: CalendarSource, start: date, end: date) -> list[date]:
    """Sessions in ``[start, end]``; raises when the range leaves the calendar."""
    if start < calendar.first_day or end > calendar.last_day:
        raise CalendarCoverageError("range outside calendar coverage")
    out, day = [], start
    while day <= end:
        if calendar.is_session(day):
            out.append(day)
        day += timedelta(days=1)
    return out


def target_session(
    now: datetime, calendar: CalendarSource, grace: timedelta = DEFAULT_GRACE
) -> date:
    """Last session whose actual close + ``grace`` is at or before ``now``."""
    local = _eastern(now)
    day = local.date()
    if day > calendar.last_day or day < calendar.first_day:
        raise CalendarCoverageError("now is outside calendar coverage")
    while day >= calendar.first_day:
        if calendar.is_session(day) and close_instant(calendar, day) + grace <= local:
            return day
        day -= timedelta(days=1)
    raise CalendarCoverageError("no completed session inside calendar coverage")


def missed_sessions(calendar: CalendarSource, latest: date, target: date) -> int:
    """Sessions after ``latest`` up to and including ``target``."""
    if latest >= target:
        return 0
    return len(sessions_between(calendar, latest + timedelta(days=1), target))


@dataclass(frozen=True)
class ExpectedSessions:
    """Expected session window for one symbol plus its coverage state."""

    state: CheckState
    reason_code: str
    sessions: tuple[date, ...] = ()


def expected_sessions(  # pylint: disable=too-many-arguments
    calendar: CalendarSource,
    start: date,
    end: date,
    *,
    first_stored: date | None = None,
    lifecycle_start: date | None = None,
) -> ExpectedSessions:
    """Return sessions from max(requested start, verified lifecycle start).

    Stored history that starts after the first expected session without a
    verified lifecycle start is ``UNKNOWN LIFECYCLE_UNKNOWN``: a late first row
    is never assumed to be the IPO.
    """
    begin = max(start, lifecycle_start) if lifecycle_start else start
    window = tuple(sessions_between(calendar, begin, end))
    if not window:
        return ExpectedSessions(CheckState.NOT_APPLICABLE, "NO_EXPECTED_SESSIONS")
    if first_stored is not None and first_stored > window[0]:
        if lifecycle_start is None:
            return ExpectedSessions(CheckState.UNKNOWN, "LIFECYCLE_UNKNOWN", window)
        return ExpectedSessions(CheckState.WARN, "COVERAGE_GAP_AT_START", window)
    return ExpectedSessions(CheckState.OK, "COVERAGE_OK", window)


def coverage_check(
    calendar: CalendarSource,
    now: datetime,
    *,
    start: date | None = None,
    end: date | None = None,
    holiday_years: Iterable[int] | None = None,
) -> CheckResult:
    """Calendar and ``market_holidays`` coverage for the requested range.

    Range beyond the calendar, or a year missing from the table -> ``BLOCKED
    CALENDAR_COVERAGE_MISSING``. ``current_year + 1`` missing -> ``WARN
    NEXT_YEAR_CALENDAR_MISSING`` before Dec 1, ``BLOCKED`` from Dec 1.
    """
    local = _eastern(now)
    year = local.year
    start = start or date(year, 1, 1)
    end = end or local.date()
    years = set(holiday_years) if holiday_years is not None else None
    counts = {
        "first_year": calendar.first_day.year,
        "last_year": calendar.last_day.year,
    }

    def _result(state: CheckState, code: str) -> CheckResult:
        return CheckResult(
            check_id="calendar.coverage", state=state, reason_code=code, counts=counts
        )

    if start < calendar.first_day or end > calendar.last_day:
        return _result(CheckState.BLOCKED, "CALENDAR_COVERAGE_MISSING")
    if years is not None and any(
        y not in years for y in range(start.year, end.year + 1)
    ):
        return _result(CheckState.BLOCKED, "CALENDAR_COVERAGE_MISSING")
    next_missing = calendar.last_day < date(year + 1, 12, 31) or (
        years is not None and year + 1 not in years
    )
    if next_missing:
        state = (
            CheckState.BLOCKED
            if local.month >= NEXT_YEAR_BLOCK_MONTH
            else CheckState.WARN
        )
        return _result(state, "NEXT_YEAR_CALENDAR_MISSING")
    return _result(CheckState.OK, "CALENDAR_COVERED")


def holiday_cross_check(
    calendar: CalendarSource, table_dates: Iterable[date], start: date, end: date
) -> CheckResult:
    """Compare ``market_holidays`` weekday dates with the calendar's full closures.

    Extra table dates (e.g. a wrongly observed 2021-12-31) and missing closures
    are counted and reported as ``WARN CALENDAR_DISAGREEMENT``; nothing is ever
    deleted. Half days are sessions and are never expected in the table.
    """
    table = {d for d in table_dates if start <= d <= end and d.weekday() < 5}
    closures, day = set(), start
    while day <= end:
        if day.weekday() < 5 and not calendar.is_session(day):
            closures.add(day)
        day += timedelta(days=1)
    extra, missing = len(table - closures), len(closures - table)
    state = CheckState.WARN if extra or missing else CheckState.OK
    return CheckResult(
        check_id="calendar.holiday_table",
        state=state,
        reason_code=(
            "CALENDAR_DISAGREEMENT" if state is CheckState.WARN else "CALENDAR_AGREES"
        ),
        counts={"extra": extra, "missing": missing},
    )
