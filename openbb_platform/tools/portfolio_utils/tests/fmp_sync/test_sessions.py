"""Lifecycle-aware market sessions (#1345-T01, A1).

Synthetic calendar fixture (shape-checked against ``exchange_calendars`` XNYS);
no network, no database.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from portfolio_utils import populate_market_holidays as pmh
from portfolio_utils.fmp_sync import sessions
from portfolio_utils.fmp_sync.checks import CheckState

FIXTURE = Path(__file__).parent / "fixtures" / "calendar_synthetic.json"
LA = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")


@pytest.fixture(name="cal")
def _cal():
    return sessions.SyntheticCalendar.from_json(FIXTURE)


def _pt(y, m, d, hh=15, mm=30):
    return datetime(y, m, d, hh, mm, tzinfo=LA)


def test_synthetic_fixture_matches_xnys_contract(cal):
    """Seam contract: the synthetic calendar agrees with the real XNYS source."""
    real = sessions.XnysCalendar(date(2026, 1, 1), date(2028, 12, 31))
    day = date(2026, 1, 2)
    while day <= date(2028, 12, 29):
        assert cal.is_session(day) == real.is_session(day), day
        if cal.is_session(day):
            assert cal.close_et(day) == real.close_et(day), day
        day += timedelta(days=1)
    assert real.version


def test_thanksgiving_2026_targets_nov25(cal):
    assert sessions.target_session(_pt(2026, 11, 26), cal) == date(2026, 11, 25)


def test_half_day_nov27_after_grace_targets_nov27(cal):
    # 15:30 PT = 18:30 ET; half-day close 13:00 ET + 2 h grace = 15:00 ET.
    assert sessions.target_session(_pt(2026, 11, 27), cal) == date(2026, 11, 27)


def test_half_day_before_grace_targets_previous(cal):
    # 14:30 ET on the half day: 13:00 + 2 h not reached -> Wednesday Nov 25.
    now = datetime(2026, 11, 27, 14, 30, tzinfo=ET)
    assert sessions.target_session(now, cal) == date(2026, 11, 25)
    # A regular 16:00 close would not even be reached at 17:30 ET.
    assert sessions.target_session(
        datetime(2026, 11, 27, 17, 30, tzinfo=ET), cal
    ) == date(2026, 11, 27)


def test_regular_day_before_grace_targets_previous(cal):
    now = datetime(2026, 11, 30, 17, 59, tzinfo=ET)
    assert sessions.target_session(now, cal) == date(2026, 11, 27)
    assert sessions.target_session(now + timedelta(minutes=1), cal) == date(
        2026, 11, 30
    )


@pytest.mark.parametrize(
    "day", [date(2027, 3, 12), date(2027, 3, 15), date(2027, 11, 5), date(2027, 11, 8)]
)
def test_1530_pt_maps_to_1830_et_across_dst(cal, day):
    now = _pt(day.year, day.month, day.day)
    assert now.astimezone(ET).time() == time(18, 30)
    assert sessions.target_session(now, cal) == day


def test_target_uses_eastern_date_not_utc_date(cal):
    # 21:30 PT Friday = 00:30 UTC Saturday; still Friday's session.
    assert sessions.target_session(_pt(2026, 12, 4, 21, 30), cal) == date(2026, 12, 4)


def test_naive_now_rejected(cal):
    with pytest.raises(ValueError):
        sessions.target_session(datetime(2026, 11, 27, 15, 30), cal)


def test_new_year_2027_friday_closed_and_jan4_session(cal):
    assert not cal.is_session(date(2027, 1, 1))
    assert cal.is_session(date(2027, 1, 4))
    assert cal.is_session(date(2027, 12, 31))  # 2028-01-01 is a Saturday
    assert sessions.target_session(_pt(2027, 1, 1), cal) == date(2026, 12, 31)
    assert sessions.target_session(_pt(2027, 1, 4), cal) == date(2027, 1, 4)


def test_2028_saturday_new_year_not_observed_dec31():
    """NYSE rule 7.2: a Saturday New Year's Day is not observed on Friday."""
    rows = pmh.compute_us_holidays(2021, 2028)
    dates = {r[0] for r in rows}
    assert date(2027, 12, 31) not in dates
    assert date(2021, 12, 31) not in dates
    assert date(2026, 1, 1) in dates and date(2027, 1, 1) in dates
    # Other Saturday holidays are still observed on Friday (July 4 2026 -> Jul 3).
    assert date(2026, 7, 3) in dates
    new_years = [r for r in rows if r[2] == "New Year's Day"]
    assert {r[0].year for r in new_years} == {2021, 2023, 2024, 2025, 2026, 2027}


def test_next_year_missing_warns_then_blocks_dec1():
    short = sessions.SyntheticCalendar(date(2026, 1, 1), date(2026, 12, 31))
    nov = sessions.coverage_check(short, _pt(2026, 11, 30))
    assert (nov.state, nov.reason_code) == (
        CheckState.WARN,
        "NEXT_YEAR_CALENDAR_MISSING",
    )
    dec = sessions.coverage_check(short, _pt(2026, 12, 1, 0, 1))
    assert (dec.state, dec.reason_code) == (
        CheckState.BLOCKED,
        "NEXT_YEAR_CALENDAR_MISSING",
    )


def test_next_year_missing_from_holiday_table_warns(cal):
    now = _pt(2026, 11, 27)
    ok = sessions.coverage_check(cal, now, holiday_years={2026, 2027})
    assert ok.state is CheckState.OK
    warn = sessions.coverage_check(cal, now, holiday_years={2026})
    assert warn.state is CheckState.WARN
    gap = sessions.coverage_check(cal, now, holiday_years={2027})
    assert (gap.state, gap.reason_code) == (
        CheckState.BLOCKED,
        "CALENDAR_COVERAGE_MISSING",
    )


def test_range_beyond_calendar_end_blocks(cal):
    out = sessions.coverage_check(
        cal, _pt(2026, 11, 27), start=date(2026, 1, 1), end=date(2029, 1, 5)
    )
    assert (out.state, out.reason_code) == (
        CheckState.BLOCKED,
        "CALENDAR_COVERAGE_MISSING",
    )
    with pytest.raises(sessions.CalendarCoverageError):
        sessions.target_session(_pt(2029, 2, 1), cal)


def test_lifecycle_unknown_is_unknown_not_ipo(cal):
    unknown = sessions.expected_sessions(
        cal, date(2026, 11, 2), date(2026, 11, 27), first_stored=date(2026, 11, 16)
    )
    assert (unknown.state, unknown.reason_code) == (
        CheckState.UNKNOWN,
        "LIFECYCLE_UNKNOWN",
    )
    known = sessions.expected_sessions(
        cal,
        date(2026, 11, 2),
        date(2026, 11, 27),
        first_stored=date(2026, 11, 16),
        lifecycle_start=date(2026, 11, 14),  # Saturday -> first session Nov 16
    )
    assert known.state is CheckState.OK
    assert known.sessions[0] == date(2026, 11, 16)
    assert date(2026, 11, 26) not in known.sessions
    assert len(known.sessions) == 9


def test_holiday_table_disagreement_reported(cal):
    table = {date(2026, 11, 26), date(2027, 12, 31), date(2027, 7, 4)}
    out = sessions.holiday_cross_check(
        cal, table, date(2026, 11, 1), date(2027, 12, 31)
    )
    assert (out.state, out.reason_code) == (CheckState.WARN, "CALENDAR_DISAGREEMENT")
    # 2027-12-31 extra (a session); 2026-12-25, 2027 closures missing; Sunday ignored.
    assert out.counts["extra"] == 1
    assert out.counts["missing"] == 11
    full = {d for d in _weekday_closures(cal, date(2026, 11, 1), date(2027, 12, 31))}
    agree = sessions.holiday_cross_check(
        cal, full, date(2026, 11, 1), date(2027, 12, 31)
    )
    assert agree.state is CheckState.OK


def _weekday_closures(cal, start, end):
    day = start
    while day <= end:
        if day.weekday() < 5 and not cal.is_session(day):
            yield day
        day += timedelta(days=1)
