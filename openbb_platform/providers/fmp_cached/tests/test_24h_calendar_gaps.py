"""24h-asset calendars for cache gap detection (#1304).

Crypto trades 24x7 and forex 24x5 (closed Fri 17:00 -> Sun 17:00 New York
time). The equity gap detectors must not apply NYSE sessions or holidays to
those symbols, and must be unchanged for equities.

Recorded FMP snapshots (``tests/fixtures/fmp_24h``, recorded 2026-11-28)
settled how the data behaves:

* timestamps are naive New York wall time (EDT in July, EST in January);
* crypto majors are dense, forex majors are dense except for the weekly
  closure (last Friday bar 16:55, first Sunday bar 17:05) and thin days
  (Dec 24/25/31 and Jan 1); exotic pairs (USDTRY) omit no-trade bars, with
  holes of 5+ hours inside a normal day;
* the newest bar is published roughly two intervals behind the clock;
* EURUSD daily bars have no rows for Dec 25 or Jan 1, BTCUSD has every day.
"""

# ruff: noqa: D102, D103

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from openbb_fmp_cached.models import (
    equity_historical as eh,
    equity_intraday_historical as ei,
)
from openbb_fmp_cached.utils import session_calendar as sc

EXEC = "openbb_fmp_cached.models.equity_intraday_historical.execute_query"
_SNAP = json.loads(
    (
        Path(__file__).parent / "fixtures" / "fmp_24h" / "fmp_24h_snapshots.json"
    ).read_text(encoding="utf-8")
)
FAR = datetime(2030, 1, 1)


def _fx(name, symbol, interval="5min", *, skip=None, lo=None, hi=None):
    """Convert recorded FMP rows to cache rows (DB column names)."""
    rows = []
    for raw in _SNAP[name]:
        ts = datetime.strptime(raw["date"], "%Y-%m-%d %H:%M:%S")
        if (lo and ts < lo) or (hi and ts > hi) or (skip and skip(ts)):
            continue
        rows.append(
            {
                "symbol": symbol,
                "interval_type": interval,
                "ts": ts,
                "open_price": raw["open"],
                "high_price": raw["high"],
                "low_price": raw["low"],
                "close_price": raw["close"],
                "volume": raw["volume"],
                "is_extended": False,
                "is_valid": True,
            }
        )
    rows.sort(key=lambda r: r["ts"])
    return rows


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


def _analyze(symbol, interval, start, end, rows, *, date_only=False, now=FAR):
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
        ("SOLUSD", "crypto"),
        ("BTC-USD", "crypto"),
        ("EURUSD", "forex"),
        ("USDJPY", "forex"),
        ("USDTRY", "forex"),
        ("XAUSAR", "forex"),
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
    assert ei._is_extended_row({"date": row["date"]}, symbol="AAPL") is True
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


# --------------------------------------------------------------------------
# recorded-data behaviour (#1304 review round 1)
# --------------------------------------------------------------------------

D = datetime


def test_recorded_crypto_weekend_is_complete_and_dense():
    start, end = D(2025, 1, 3, 12, 0), D(2025, 1, 6, 12, 0)
    rows = _fx("btcusd_5min_weekend", "BTCUSD")
    assert _analyze("BTCUSD", "5min", start, end, rows)[1] is False
    no_sat = [r for r in rows if r["ts"].date() != date(2025, 1, 4)]
    assert _analyze("BTCUSD", "5min", start, end, no_sat)[1] is True


def test_recorded_crypto_small_hole_tolerated_but_long_hole_flagged():
    start, end = D(2025, 1, 3, 12, 0), D(2025, 1, 6, 12, 0)
    short = _fx(
        "btcusd_5min_weekend",
        "BTCUSD",
        skip=lambda t: D(2025, 1, 4, 3, 0) <= t < D(2025, 1, 4, 3, 10),
    )
    assert _analyze("BTCUSD", "5min", start, end, short)[1] is False
    long_ = _fx(
        "btcusd_5min_weekend",
        "BTCUSD",
        skip=lambda t: D(2025, 1, 4, 3, 0) <= t < D(2025, 1, 4, 3, 30),
    )
    assert _analyze("BTCUSD", "5min", start, end, long_)[1] is True


def test_recorded_forex_weekend_closure_and_sunday_1705_open_is_complete():
    start, end = D(2025, 1, 3, 12, 0), D(2025, 1, 6, 12, 0)
    rows = _fx("eurusd_5min_weekend", "EURUSD")
    assert not any(r["ts"] == D(2025, 1, 5, 17, 0) for r in rows)  # opens 17:05
    assert _analyze("EURUSD", "5min", start, end, rows)[1] is False
    gap = _fx(
        "eurusd_5min_weekend",
        "EURUSD",
        skip=lambda t: D(2025, 1, 6, 3, 0) <= t < D(2025, 1, 6, 4, 0),
    )
    assert _analyze("EURUSD", "5min", start, end, gap)[1] is True


def test_recorded_forex_holiday_windows_do_not_report_a_gap():
    xmas = _fx(
        "eurusd_5min_holidays", "EURUSD", lo=D(2024, 12, 24), hi=D(2024, 12, 27, 23)
    )
    assert (
        _analyze("EURUSD", "5min", D(2024, 12, 24), D(2024, 12, 27, 16, 55), xmas)[1]
        is False
    )
    new_year = _fx(
        "eurusd_5min_holidays", "EURUSD", lo=D(2024, 12, 31), hi=D(2025, 1, 2, 23, 59)
    )
    assert (
        _analyze("EURUSD", "5min", D(2024, 12, 31), D(2025, 1, 2, 23, 55), new_year)[1]
        is False
    )


def test_recorded_exotic_forex_sparse_bars_do_not_loop_refetch():
    rows = _fx("usdtry_5min", "USDTRY")
    # FMP omits no-trade bars: a 17h hole inside a normal Wednesday.
    assert (
        _analyze("USDTRY", "5min", D(2025, 1, 6), D(2025, 1, 8, 23, 55), rows)[1]
        is False
    )


def test_live_edge_allows_publishing_lag_but_not_more():
    start, end = D(2025, 1, 6, 0, 0), D(2025, 1, 6, 23, 55)
    rows = _fx("btcusd_5min_weekend", "BTCUSD", lo=start, hi=D(2025, 1, 6, 3, 20))
    # newest bar is 03:20; clock 03:27 -> latest published is two intervals back
    assert (
        _analyze("BTCUSD", "5min", start, end, rows, now=D(2025, 1, 6, 3, 27))[1]
        is False
    )
    # clock 04:30 -> ~70 minutes of bars missing at the live edge
    assert (
        _analyze("BTCUSD", "5min", start, end, rows, now=D(2025, 1, 6, 4, 30))[1]
        is True
    )


def test_recorded_daily_forex_has_no_rows_for_dec25_or_jan1():
    cached = {date.fromisoformat(r["date"]) for r in _SNAP["eurusd_daily_holidays"]}
    start, end = date(2024, 12, 20), date(2025, 1, 3)
    assert (
        eh._detect_missing_ranges(start, end, cached, "1d", asset_class="forex") == []
    )
    for day in (date(2024, 12, 25), date(2025, 1, 1)):
        assert day not in cached
        assert not sc.is_calendar_day_open(day, "forex")
        assert not sc.is_calendar_day_open(day, "forex", intraday=True)


def test_recorded_daily_crypto_has_every_calendar_day():
    cached = {date.fromisoformat(r["date"]) for r in _SNAP["btcusd_daily_holidays"]}
    start, end = date(2024, 12, 20), date(2025, 1, 3)
    assert (
        eh._detect_missing_ranges(start, end, cached, "1d", asset_class="crypto") == []
    )
    weekdays = {d for d in cached if d.weekday() < 5}
    assert eh._detect_missing_ranges(start, end, weekdays, "1d", asset_class="crypto")


def test_forex_new_year_closure_window_matches_recording():
    assert not sc.forex_is_closed(D(2024, 12, 31, 16, 55))
    assert sc.forex_is_closed(D(2024, 12, 31, 17, 30))
    assert sc.forex_is_closed(D(2025, 1, 1, 15, 55))
    assert not sc.forex_is_closed(D(2025, 1, 1, 16, 0))
    assert sc.forex_next_open(D(2024, 12, 31, 20, 0)) == D(2025, 1, 1, 16, 0)


def test_multi_symbol_rows_are_classified_per_row_symbol():
    crypto = {"symbol": "BTCUSD", "date": "2025-01-04 21:00:00"}
    stock = {"symbol": "AAPL", "date": "2025-01-06 21:00:00"}
    assert ei._is_extended_row(crypto, symbol="AAPL,BTCUSD") is False
    assert ei._is_extended_row(stock, symbol="BTCUSD,AAPL") is True
    q = ei.FMPCachedEquityIntradayHistoricalQueryParams(
        symbol="AAPL,BTCUSD",
        interval="5min",
        start_date=datetime(2025, 1, 4),
        end_date=datetime(2025, 1, 7),
        extended_hours=False,
    )
    kept = ei._filter_fresh_rows([crypto, stock], q)
    assert [r["symbol"] for r in kept] == ["BTCUSD"]


def test_is_24h_symbol_matches_classification():
    assert sc.is_24h_symbol("BTCUSD") and sc.is_24h_symbol("EURUSD")
    assert not sc.is_24h_symbol("AAPL")


def test_edge_shortfall_within_tolerance_is_accepted_beyond_it_flagged():
    start, end = D(2025, 1, 3, 12, 0), D(2025, 1, 6, 12, 0)
    # last two bars (10 min) absent at the end, first two at the start
    ok = _fx(
        "btcusd_5min_weekend",
        "BTCUSD",
        lo=D(2025, 1, 3, 12, 10),
        hi=D(2025, 1, 6, 11, 50),
    )
    assert _analyze("BTCUSD", "5min", start, end, ok)[1] is False
    late_end = _fx("btcusd_5min_weekend", "BTCUSD", hi=D(2025, 1, 6, 11, 30))
    assert _analyze("BTCUSD", "5min", start, end, late_end)[1] is True
    late_start = _fx("btcusd_5min_weekend", "BTCUSD", lo=D(2025, 1, 3, 12, 30))
    assert _analyze("BTCUSD", "5min", start, end, late_start)[1] is True


# --------------------------------------------------------------------------
# review round 2
# --------------------------------------------------------------------------


def _synthetic(symbol, start, end, *, skip=None):
    """Dense bars (recordings show majors have none missing)."""
    return _bars(symbol, "5min", start, end, skip=skip)


def test_forex_now_inside_weekly_closure_does_not_demand_closed_bars():
    start, end = D(2025, 1, 6, 0, 0), D(2025, 1, 12, 23, 55)
    rows = _synthetic("EURUSD", start, D(2025, 1, 10, 16, 55), skip=sc.forex_is_closed)
    now = D(2025, 1, 12, 10, 0)  # Sunday morning, market still closed
    assert sc.forex_is_closed(now)
    assert _analyze("EURUSD", "5min", start, end, rows, now=now)[1] is False
    # after the Sunday reopen the missing evening bars are demanded again
    assert _analyze("EURUSD", "5min", start, end, rows, now=D(2025, 1, 12, 22, 0))[1]


def test_forex_now_inside_new_year_closure_does_not_demand_closed_bars():
    start, end = D(2024, 12, 30, 0, 0), D(2025, 1, 1, 23, 55)
    rows = _synthetic("EURUSD", start, D(2024, 12, 31, 17, 0), skip=sc.forex_is_closed)
    assert (
        _analyze("EURUSD", "5min", start, end, rows, now=D(2025, 1, 1, 10, 0))[1]
        is False
    )


def test_crypto_spring_forward_hour_is_not_a_gap():
    start, end = D(2026, 3, 8, 0, 0), D(2026, 3, 8, 5, 55)
    # naive New York labels skip 02:00-02:55 on the transition Sunday
    rows = _synthetic("BTCUSD", start, end, skip=lambda t: t.hour == 2)
    assert _analyze("BTCUSD", "5min", start, end, rows)[1] is False
    missing_more = _synthetic("BTCUSD", start, end, skip=lambda t: t.hour in (2, 4))
    assert _analyze("BTCUSD", "5min", start, end, missing_more)[1] is True


def test_crypto_fall_back_window_is_not_a_gap_or_negative_delta():
    start, end = D(2026, 11, 1, 0, 0), D(2026, 11, 1, 5, 55)
    rows = _synthetic("BTCUSD", start, end)  # 01:xx labels exist once after upsert
    assert _analyze("BTCUSD", "5min", start, end, rows)[1] is False
    # a short hole spanning the repeated hour: elapsed time stays 10 minutes
    holed = _synthetic(
        "BTCUSD",
        start,
        end,
        skip=lambda t: t.hour == 1 and t.minute >= 55 or t.hour == 2 and t.minute == 0,
    )
    assert _analyze("BTCUSD", "5min", start, end, holed)[1] is False


def test_illiquid_crypto_is_sparse_but_recorded_majors_are_dense():
    for dense in ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "AVAXUSD"):
        assert not sc.is_sparse_symbol(dense)
        assert sc.gap_tolerances(dense, timedelta(minutes=5))[0] is not None
    for sparse in ("ADAUSD", "DOGEUSD", "ATMUSD", "USDTRY"):
        assert sc.is_sparse_symbol(sparse)
        assert sc.gap_tolerances(sparse, timedelta(minutes=5))[0] is None
    assert not sc.is_sparse_symbol("EURUSD")


def test_recorded_sparse_crypto_does_not_loop_refetch():
    rows = _fx("adausd_5min", "ADAUSD")
    assert (
        _analyze("ADAUSD", "5min", D(2025, 1, 6), D(2025, 1, 8, 23, 55), rows)[1]
        is False
    )


def test_recorded_dense_crypto_solusd_still_detects_holes():
    start, end = D(2025, 1, 6, 0, 0), D(2025, 1, 7, 23, 55)
    rows = _fx("solusd_5min", "SOLUSD", hi=end)
    assert _analyze("SOLUSD", "5min", start, end, rows)[1] is False
    holed = _fx(
        "solusd_5min",
        "SOLUSD",
        hi=end,
        skip=lambda t: D(2025, 1, 6, 9, 0) <= t < D(2025, 1, 6, 10, 0),
    )
    assert _analyze("SOLUSD", "5min", start, end, holed)[1] is True


def test_date_only_range_before_first_bar_is_exempt_at_the_edges():
    rows = _fx(
        "btcusd_5min_weekend", "BTCUSD", lo=D(2025, 1, 4, 3, 0), hi=D(2025, 1, 4, 20, 0)
    )
    day = D(2025, 1, 4)
    assert _analyze("BTCUSD", "5min", day, day, rows, date_only=True)[1] is False
    assert _analyze("BTCUSD", "5min", day, D(2025, 1, 4, 20, 0), rows)[1] is True


def test_intraday_range_ending_on_saturday_is_not_missing():
    mon_fri = {date(2025, 1, 6) + timedelta(days=i) for i in range(5)}
    args = (date(2025, 1, 6), date(2025, 1, 11), mon_fri, "1hour")
    assert eh._detect_missing_ranges(*args, asset_class="forex") == []
    assert eh._detect_missing_ranges(*args) == []  # equity: same closed Saturday
    # a range starting Saturday begins at the Sunday evening open
    sun_to_fri = mon_fri | {date(2025, 1, 5)}
    sat_start = (date(2025, 1, 4), date(2025, 1, 10), sun_to_fri, "1hour")
    assert eh._detect_missing_ranges(*sat_start, asset_class="forex") == []
    assert (
        eh._detect_missing_ranges(
            date(2025, 1, 4), date(2025, 1, 10), mon_fri, "1hour", asset_class="forex"
        )
        != []
    )
    # a genuinely uncovered open day is still reported
    thin = {date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)}
    assert (
        eh._detect_missing_ranges(*args[:2], thin, "1hour", asset_class="forex") != []
    )


def test_missing_symbol_list_is_a_loud_warning(caplog, tmp_path, monkeypatch):
    import logging

    monkeypatch.setattr(sc, "_ASSET_FILE", tmp_path / "absent.json")
    sc._symbol_sets.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger=sc.__name__):
            assert sc._symbol_sets() == (frozenset(), frozenset())
            sc._symbol_sets()
        hits = [r for r in caplog.records if "fmp_24h_symbols" in r.getMessage()]
        assert len(hits) == 1  # warned once, not per call
    finally:
        sc._symbol_sets.cache_clear()


def test_intraday_range_entirely_inside_closures_has_nothing_missing():
    mon_fri = {date(2025, 1, 6) + timedelta(days=i) for i in range(5)}
    saturday = date(2025, 1, 11)
    assert eh._detect_missing_ranges(saturday, saturday, mon_fri, "1hour") == []
    assert (
        eh._detect_missing_ranges(
            saturday, saturday, mon_fri, "1hour", asset_class="forex"
        )
        == []
    )
