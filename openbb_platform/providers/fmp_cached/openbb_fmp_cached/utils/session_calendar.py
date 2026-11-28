"""Per-asset-class trading calendars for cache gap detection (#1304).

FMP serves crypto, forex, index and commodity bars through the same chart
endpoints as equities, so the cached equity fetchers can be asked for
symbols that do not follow the NYSE session calendar:

* ``crypto`` trades 24x7, including weekends and US holidays.
* ``forex`` trades 24x5: it closes Friday 17:00 New York time and reopens
  Sunday 17:00 New York time. US equity holidays are not closures.
* ``equity`` (the default, and anything not recognised) keeps the NYSE
  behaviour that the gap detectors have always used.

Classification is deliberately conservative: only symbols that clearly look
like a crypto or forex pair are treated as 24h assets. Anything ambiguous
stays on the equity calendar so existing behaviour cannot change.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal

AssetClass = Literal["equity", "crypto", "forex"]

_FOREX_CLOSE_WEEKDAY = 4  # Friday
_FOREX_OPEN_WEEKDAY = 6  # Sunday
_FOREX_SESSION_TIME = time(17)  # 17:00 America/New_York

_FIAT_CODES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK",
        "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
        "CNY", "ILS", "THB", "KRW", "INR", "BRL", "RUB",
    }
)  # fmt: skip

_CRYPTO_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH")

_CRYPTO_BASES = frozenset(
    {
        "BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "DOT", "DOGE", "SOL", "AVAX",
        "LINK", "MATIC", "XLM", "TRX", "ETC", "ATOM", "UNI", "XMR", "ALGO",
        "FIL", "NEAR", "SHIB", "BNB", "APT", "ARB", "OP", "AAVE", "EOS",
        "XTZ", "DASH", "ZEC", "USDT", "USDC", "DAI",
    }
)  # fmt: skip


def _normalise(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


def classify_symbol(symbol: str | None) -> AssetClass:
    """Return the calendar family for a symbol (``equity`` when unsure)."""
    if not symbol:
        return "equity"
    text = _normalise(symbol)
    if len(text) == 6 and text[:3] in _FIAT_CODES and text[3:] in _FIAT_CODES:
        return "forex"
    for quote in _CRYPTO_QUOTES:
        if text.endswith(quote) and text[: -len(quote)] in _CRYPTO_BASES:
            return "crypto"
    return "equity"


def is_24h_symbol(symbol: str | None) -> bool:
    """Return True when the symbol does not follow the NYSE session calendar."""
    return classify_symbol(symbol) != "equity"


def is_calendar_day_open(
    check_date: date, asset_class: str, *, intraday: bool = False
) -> bool:
    """Day-level openness for non-equity assets (no holiday closures).

    Forex never trades on Saturday. Sunday only has evening bars, so it is an
    expected day for intraday series but not for daily bars, which are
    stamped on the weekday session they belong to.
    """
    if asset_class == "crypto":
        return True
    if intraday:
        return check_date.weekday() != 5
    return check_date.weekday() < 5


def forex_is_closed(value: datetime) -> bool:
    """Return True inside the weekly forex closure (New York wall time, naive)."""
    weekday = value.weekday()
    if weekday == 5:
        return True
    if weekday == _FOREX_CLOSE_WEEKDAY:
        return value.time() >= _FOREX_SESSION_TIME
    if weekday == _FOREX_OPEN_WEEKDAY:
        return value.time() < _FOREX_SESSION_TIME
    return False


def forex_next_open(value: datetime) -> datetime:
    """First instant at or after ``value`` that is not in the forex closure."""
    if not forex_is_closed(value):
        return value
    days_ahead = (_FOREX_OPEN_WEEKDAY - value.weekday()) % 7
    return datetime.combine(
        value.date() + timedelta(days=days_ahead), _FOREX_SESSION_TIME
    )


def forex_last_open_bar_start(value: datetime, interval: timedelta) -> datetime:
    """Latest bar start at or before ``value`` that lies in an open window."""
    if not forex_is_closed(value):
        return value
    # Walk back to the Friday close; the final bar starts one interval earlier.
    days_back = (value.weekday() - _FOREX_CLOSE_WEEKDAY) % 7
    close = datetime.combine(
        value.date() - timedelta(days=days_back), _FOREX_SESSION_TIME
    )
    return close - interval
