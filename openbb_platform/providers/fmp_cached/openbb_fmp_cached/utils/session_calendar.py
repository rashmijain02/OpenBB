"""Per-asset-class trading calendars for cache gap detection (#1304).

FMP serves crypto, forex, index and commodity bars through the same chart
endpoints, so the cached equity fetchers can be asked for symbols that do
not follow the NYSE session calendar:

* ``crypto`` trades 24x7, including weekends and US holidays.
* ``forex`` trades 24x5: it closes Friday 17:00 New York time and reopens
  Sunday 17:00 (the first bar is labelled 17:05). Daily bars do not exist
  for Dec 25 and Jan 1, and intraday bars are absent from Dec 31 17:00 to
  Jan 1 16:00.
* ``equity`` (the default, and anything not recognised) keeps the NYSE
  behaviour that the gap detectors have always used.

Behaviour settled from recorded FMP snapshots
(``tests/fixtures/fmp_24h``, 2026-11-28): bar timestamps are naive New York
wall time; crypto majors and forex majors are dense; exotic forex pairs omit
no-trade bars; holiday periods are thin.

Classification uses symbol lists bundled from FMP's ``cryptocurrency-list``
and ``forex-list`` (``assets/fmp_24h_symbols.json``, no runtime call).
Anything unknown stays on the equity calendar so existing behaviour cannot
change.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

AssetClass = Literal["equity", "crypto", "forex"]

_FOREX_CLOSE_WEEKDAY = 4  # Friday
_FOREX_OPEN_WEEKDAY = 6  # Sunday
_FOREX_SESSION_TIME = time(17)  # 17:00 America/New_York
_FOREX_NEW_YEAR_REOPEN = time(16)  # Jan 1 16:00 America/New_York
# (month, day) with no forex daily bar.
_FOREX_HOLIDAYS = frozenset({(12, 25), (1, 1)})
# (month, day) whose intraday bars are thin: holes there are not gaps.
_FOREX_THIN_DAYS = frozenset({(12, 24), (12, 25), (12, 31), (1, 1)})

_ASSET_FILE = Path(__file__).resolve().parent.parent / "assets" / "fmp_24h_symbols.json"

# Pairs whose bars are dense in the recordings; every other pair is treated
# as sparse because FMP omits no-trade bars for it (USDTRY: 17h hole midweek).
_DENSE_FIAT = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK"}
)
_FIAT_CODES = _DENSE_FIAT | frozenset(
    {
        "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH", "CNY",
        "ILS", "THB", "KRW", "INR", "BRL", "RUB",
    }
)  # fmt: skip

_CRYPTO_TOLERANCE = timedelta(minutes=15)
_FOREX_TOLERANCE = timedelta(minutes=30)
_SPARSE_EDGE_TOLERANCE = timedelta(hours=24)
_MIN_TOLERANCE_INTERVALS = 3


@lru_cache(maxsize=1)
def _symbol_sets() -> tuple[frozenset[str], frozenset[str]]:
    try:
        data = json.loads(_ASSET_FILE.read_text(encoding="utf-8"))
        return frozenset(data["crypto"]), frozenset(data["forex"])
    except (OSError, ValueError, KeyError):
        return frozenset(), frozenset()


def _normalise(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


def classify_symbol(symbol: str | None) -> AssetClass:
    """Return the calendar family for a symbol (``equity`` when unsure)."""
    if not symbol:
        return "equity"
    text = _normalise(symbol)
    crypto, forex = _symbol_sets()
    if text in forex or (
        len(text) == 6 and text[:3] in _FIAT_CODES and text[3:] in _FIAT_CODES
    ):
        return "forex"
    if text in crypto:
        return "crypto"
    return "equity"


def is_24h_symbol(symbol: str | None) -> bool:
    """Return True when the symbol does not follow the NYSE session calendar."""
    return classify_symbol(symbol) != "equity"


def is_sparse_symbol(symbol: str | None) -> bool:
    """Return True for forex pairs where FMP omits no-trade bars."""
    if classify_symbol(symbol) != "forex":
        return False
    text = _normalise(str(symbol))
    return not (text[:3] in _DENSE_FIAT and text[3:] in _DENSE_FIAT)


def gap_tolerances(
    symbol: str | None, interval: timedelta
) -> tuple[timedelta | None, timedelta]:
    """Return ``(interior_hole, edge)`` tolerances for a 24h symbol.

    A hole shorter than the tolerance is vendor sparseness, not a gap, so a
    refetch that returns the same holes stops reporting one. ``None`` means
    interior holes are never reported (sparse pairs).
    """
    if is_sparse_symbol(symbol):
        return None, _SPARSE_EDGE_TOLERANCE
    base = _FOREX_TOLERANCE if classify_symbol(symbol) == "forex" else _CRYPTO_TOLERANCE
    tolerance = max(_MIN_TOLERANCE_INTERVALS * interval, base)
    return tolerance, tolerance


def is_calendar_day_open(
    check_date: date, asset_class: str, *, intraday: bool = False
) -> bool:
    """Day-level openness for non-equity assets (no US equity holidays).

    Forex never trades on Saturday and has no bars on Dec 25 or Jan 1. Sunday
    only has evening bars, so it is an expected day for intraday series but
    not for daily bars, which are stamped on the weekday session they belong
    to.
    """
    if asset_class == "crypto":
        return True
    if (check_date.month, check_date.day) in _FOREX_HOLIDAYS:
        return False
    if intraday:
        return check_date.weekday() != 5
    return check_date.weekday() < 5


def forex_is_thin_day(value: datetime) -> bool:
    """Return True on forex days whose intraday bars are legitimately sparse."""
    return (value.month, value.day) in _FOREX_THIN_DAYS


def _new_year_window(value: datetime) -> tuple[datetime, datetime] | None:
    if value.month == 12 and value.day == 31:
        year = value.year
    elif value.month == 1 and value.day == 1:
        year = value.year - 1
    else:
        return None
    start = datetime.combine(date(year, 12, 31), _FOREX_SESSION_TIME)
    end = datetime.combine(date(year + 1, 1, 1), _FOREX_NEW_YEAR_REOPEN)
    return (start, end) if start <= value < end else None


def forex_is_closed(value: datetime) -> bool:
    """Return True inside a forex closure (New York wall time, naive)."""
    if _new_year_window(value):
        return True
    weekday = value.weekday()
    if weekday == 5:
        return True
    if weekday == _FOREX_CLOSE_WEEKDAY:
        return value.time() >= _FOREX_SESSION_TIME
    if weekday == _FOREX_OPEN_WEEKDAY:
        return value.time() < _FOREX_SESSION_TIME
    return False


def forex_next_open(value: datetime) -> datetime:
    """First instant at or after ``value`` that is not in a forex closure."""
    while forex_is_closed(value):
        window = _new_year_window(value)
        if window:
            value = window[1]
            continue
        days_ahead = (_FOREX_OPEN_WEEKDAY - value.weekday()) % 7
        value = datetime.combine(
            value.date() + timedelta(days=days_ahead), _FOREX_SESSION_TIME
        )
    return value


def forex_last_open_bar_start(value: datetime, interval: timedelta) -> datetime:
    """Latest bar start at or before ``value`` that lies in an open window."""
    if not forex_is_closed(value):
        return value
    window = _new_year_window(value)
    if window:
        return window[0] - interval
    days_back = (value.weekday() - _FOREX_CLOSE_WEEKDAY) % 7
    close = datetime.combine(
        value.date() - timedelta(days=days_back), _FOREX_SESSION_TIME
    )
    return close - interval
