"""24h-asset calendars for cache gap detection (#1304).

Crypto trades 24x7 and forex 24x5 (closed Fri 17:00 -> Sun 17:00 New York
time). The equity gap detectors must not apply NYSE sessions or holidays to
those symbols, and must be unchanged for equities.

Bars are generated in the shape FMP returns for ``historical-chart`` rows
(naive New York wall time, one bar per interval) because no recorded
crypto/forex intraday snapshot exists in ``tests/fixtures`` yet.
"""

# ruff: noqa: D102, D103

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from openbb_fmp_cached.models import (
    equity_historical as eh,
    equity_intraday_historical as ei,
)
from openbb_fmp_cached.utils import session_calendar as sc

EXEC = "openbb_fmp_cached.models.equity_intraday_historical.execute_query"


def _bars(symbol, interval, start, end, *, skip=None, extended=False):
    """FMP-shaped intraday rows (DB column names) from start to end inclusive."""
    step = ei._interval_delta(interval)
    rows, ts = [], start
    while ts <= end:
        if not (skip and skip(ts)):
            rows.append(
                {
                    "symbol": symbol,
                    "interval_type": interval,
                    "ts": ts,
                    "open_price": 100.0,
                    "high_price": 100.5,
                    "low_price": 99.5,
                    "close_price": 100.2,
                    "volume": 10,
                    "is_extended": extended,
                    "is_valid": True,
                }
            )
        ts += step
    return rows


def _analyze(symbol, interval, start, end, rows, *, date_only=False, now=None):
    q = ei.FMPCachedEquityIntradayHistoricalQueryParams(
        symbol=symbol,
        interval=interval,
        start_date=start,
        end_date=end,
        extended_hours=False,
    )
    for name in ("start_date", "end_date"):
        object.__setattr__(q, f"_{name}_date_only", date_only)
    with patch(EXEC, return_value=rows):
        return ei._analyze_intraday_cache(q, now=now)


# --------------------------------------------------------------------------
# classification + calendar primitives
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BTCUSD", "crypto"),
        ("ethusd", "crypto"),
        ("SOLUSDT", "crypto"),
        ("BTC-USD", "crypto"),
        ("EURUSD", "forex"),
        ("USDJPY", "forex"),
        ("GBP/USD", "forex"),
        ("AAPL", "equity"),
        ("SPY", "equity"),
        ("^GSPC", "equity"),
        ("GCUSD", "equity"),
        ("", "equity"),
        (None, "equity"),
    ],
)
def test_classify_symbol(symbol, expected):
    assert sc.classify_symbol(symbol) == expected


def test_forex_closure_window_is_friday_1700_to_sunday_1700():
    assert not sc.forex_is_closed(datetime(2026, 7, 10, 16, 55))  # Fri
    assert sc.forex_is_closed(datetime(2026, 7, 10, 17, 0))
    assert sc.forex_is_closed(datetime(2026, 7, 11, 12, 0))  # Sat
    assert sc.forex_is_closed(datetime(2026, 7, 12, 16, 55))  # Sun
    assert not sc.forex_is_closed(datetime(2026, 7, 12, 17, 0))
    assert sc.forex_next_open(datetime(2026, 7, 11, 3, 0)) == datetime(
        2026, 7, 12, 17, 0
    )
    last = sc.forex_last_open_bar_start(
        datetime(2026, 7, 11, 3, 0), timedelta(minutes=15)
    )
    assert last == datetime(2026, 7, 10, 16, 45)


# --------------------------------------------------------------------------
# daily / date-level detector (equity_historical)
# --------------------------------------------------------------------------

WEEK = [date(2026, 7, 6) + timedelta(days=i) for i in range(7)]  # Mon..Sun


def test_daily_crypto_weekend_is_missing():
    cached = {d for d in WEEK if d.weekday() < 5}
    assert eh._detect_missing_ranges(WEEK[0], WEEK[-1], cached, "1d") == []
    gaps = eh._detect_missing_ranges(
        WEEK[0], WEEK[-1], cached, "1d", asset_class="crypto"
    )
    assert gaps == [(date(2026, 7, 11), date(2026, 7, 12))]


def test_daily_forex_weekdays_complete_and_us_holiday_is_not_a_closure():
    cached = {d for d in WEEK if d.weekday() < 5}
    assert (
        eh._detect_missing_ranges(WEEK[0], WEEK[-1], cached, "1d", asset_class="forex")
        == []
    )
    # 2026-07-03 is the observed US Independence Day: NYSE closed, FX open.
    start, end = date(2026, 6, 29), date(2026, 7, 3)
    cached = {date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2)}
    assert eh._detect_missing_ranges(start, end, cached, "1d") == []
    assert eh._detect_missing_ranges(start, end, cached, "1d", asset_class="forex") == [
        (date(2026, 7, 3), date(2026, 7, 3))
    ]


def test_daily_default_asset_class_is_unchanged_equity_behaviour():
    cached = {date(2026, 7, 6)}
    assert eh._detect_missing_ranges(
        date(2026, 7, 6), date(2026, 7, 10), cached, "1d"
    ) == [(date(2026, 7, 7), date(2026, 7, 10))]


def test_intraday_density_crypto_weekdays_only_cache_is_not_complete():
    cached = {d for d in WEEK if d.weekday() < 5}
    # equity: weekdays only IS complete (unchanged)
    assert eh._detect_missing_ranges(WEEK[0], WEEK[4], cached, "5min") == []
    # crypto over a window that includes the weekend: 5/7 < 0.9 -> refetch
    out = eh._detect_missing_ranges(
        date(2026, 7, 6), date(2026, 7, 12), cached | {date(2026, 7, 12)},
        "5min", asset_class="crypto",
    )  # fmt: skip
    assert out == [(date(2026, 7, 6), date(2026, 7, 12))]


def test_intraday_density_forex_counts_sunday_evening_but_not_saturday():
    cached = {date(2026, 7, 5)} | {d for d in WEEK if d.weekday() < 5}
    assert (
        eh._detect_missing_ranges(
            date(2026, 7, 5), date(2026, 7, 10), cached, "5min", asset_class="forex"
        )
        == []
    )
    assert eh._count_trading_days_in_range(
        date(2026, 7, 5), date(2026, 7, 11), asset_class="forex", intraday=True
    ) == 6  # fmt: skip


# --------------------------------------------------------------------------
# intraday cache analysis (equity_intraday_historical)
# --------------------------------------------------------------------------


def test_crypto_full_weekend_cached_is_complete():
    start, end = datetime(2026, 7, 10, 12, 0), datetime(2026, 7, 13, 12, 0)
    rows = _bars("BTCUSD", "15min", start, end)
    _, gap = _analyze("BTCUSD", "15min", start, end, rows)
    assert gap is False


def test_crypto_missing_whole_saturday_is_a_gap():
    start, end = datetime(2026, 7, 10, 12, 0), datetime(2026, 7, 13, 12, 0)
    rows = _bars(
        "BTCUSD", "15min", start, end, skip=lambda t: t.date() == date(2026, 7, 11)
    )
    _, gap = _analyze("BTCUSD", "15min", start, end, rows)
    assert gap is True


def test_crypto_missing_overnight_tail_before_next_day_is_a_gap():
    start, end = datetime(2026, 7, 7, 0, 0), datetime(2026, 7, 8, 23, 45)
    rows = _bars(
        "ETHUSD",
        "15min",
        start,
        end,
        skip=lambda t: t.date() == date(2026, 7, 7) and t.hour >= 20,
    )
    _, gap = _analyze("ETHUSD", "15min", start, end, rows)
    assert gap is True


def test_crypto_overnight_bars_are_not_extended_hours():
    row = {"symbol": "BTCUSD", "date": "2026-07-08 21:00:00"}
    assert ei._is_extended_row(row, symbol="BTCUSD") is False
    assert ei._is_extended_row(row, symbol="AAPL") is True
    q = ei.FMPCachedEquityIntradayHistoricalQueryParams(
        symbol="BTCUSD",
        interval="5min",
        start_date=datetime(2026, 7, 8),
        end_date=datetime(2026, 7, 9),
        extended_hours=False,
    )
    assert len(ei._filter_fresh_rows([row], q)) == 1


def test_crypto_future_end_does_not_force_refetch():
    start, end = datetime(2026, 7, 8, 0, 0), datetime(2026, 7, 8, 23, 45)
    now = datetime(2026, 7, 8, 10, 7)
    rows = _bars("BTCUSD", "15min", start, datetime(2026, 7, 8, 10, 0))
    _, gap = _analyze("BTCUSD", "15min", start, end, rows, now=now)
    assert gap is False


def test_forex_week_with_weekend_closure_is_complete():
    start, end = datetime(2026, 7, 10, 12, 0), datetime(2026, 7, 13, 12, 0)
    rows = _bars("EURUSD", "15min", start, end, skip=sc.forex_is_closed)
    assert not any(sc.forex_is_closed(r["ts"]) for r in rows)
    _, gap = _analyze("EURUSD", "15min", start, end, rows)
    assert gap is False


def test_forex_request_ending_in_closure_needs_bars_only_until_friday_close():
    start, end = datetime(2026, 7, 10, 12, 0), datetime(2026, 7, 11, 18, 0)
    rows = _bars("EURUSD", "15min", start, end, skip=sc.forex_is_closed)
    _, gap = _analyze("EURUSD", "15min", start, end, rows)
    assert gap is False
    short = [r for r in rows if r["ts"] < datetime(2026, 7, 10, 16, 0)]
    _, gap = _analyze("EURUSD", "15min", start, end, short)
    assert gap is True


def test_forex_missing_sunday_evening_is_a_gap():
    start, end = datetime(2026, 7, 12, 17, 0), datetime(2026, 7, 13, 12, 0)
    rows = _bars(
        "EURUSD", "15min", start, end, skip=lambda t: t < datetime(2026, 7, 13, 0, 0)
    )
    _, gap = _analyze("EURUSD", "15min", start, end, rows)
    assert gap is True


def test_forex_missing_midweek_hours_across_midnight_is_a_gap():
    start, end = datetime(2026, 7, 7, 0, 0), datetime(2026, 7, 8, 23, 45)
    rows = _bars(
        "EURUSD",
        "15min",
        start,
        end,
        skip=lambda t: t.date() == date(2026, 7, 7) and t.hour >= 20,
    )
    _, gap = _analyze("EURUSD", "15min", start, end, rows)
    assert gap is True


def test_equity_session_gap_behaviour_unchanged():
    start, end = datetime(2026, 7, 8, 9, 30), datetime(2026, 7, 8, 15, 55)
    rows = _bars("AAPL", "5min", start, end)
    _, gap = _analyze("AAPL", "5min", start, end, rows)
    assert gap is False
    _, gap = _analyze("AAPL", "5min", start, end, rows[:-3])
    assert gap is True
    # weekend / overnight absence is NOT a gap for equities across sessions
    start, end = datetime(2026, 7, 10, 9, 30), datetime(2026, 7, 13, 15, 55)
    rows = _bars(
        "AAPL",
        "30min",
        start,
        end,
        skip=lambda t: not (
            t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) < (16, 0)
        ),
    )
    _, gap = _analyze("AAPL", "30min", start, end, rows)
    assert gap is False


def test_crypto_tail_bar_is_invalidated_after_us_close():
    rows = [{"date": datetime(2026, 7, 8, 21, 0), "is_extended": False}]
    with patch(EXEC) as ex:
        ei._invalidate_same_session_tail(
            "BTCUSD", "5min", rows, now=datetime(2026, 7, 8, 21, 2)
        )
    assert ex.call_count == 1


def test_equity_tail_after_close_still_not_invalidated():
    rows = [{"date": datetime(2026, 7, 8, 16, 0), "is_extended": False}]
    with patch(EXEC) as ex:
        ei._invalidate_same_session_tail(
            "AAPL", "5min", rows, now=datetime(2026, 7, 8, 16, 2)
        )
    assert ex.call_count == 0
