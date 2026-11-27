"""Retention policy per tool call (#1300, plan §4.2).

``fmp_cached`` is a persistent store: meaningful results are kept for good and
only genuinely ephemeral data has a TTL.

========== ======================================================== ============
mode       behaviour                                                classes
========== ======================================================== ============
document   kept forever; ``refresh_s=None`` -> fetched once,        ``immutable-doc``,
           otherwise refreshed after ``refresh_s`` (last good copy  ``revisable``,
           kept and served on upstream errors)                      ``reference``,
                                                                    ``series``
ephemeral  short TTL, prunable; feed items are also kept forever    ``ephemeral``, ``feed``
no-store   always live                                              ``no-store``
========== ======================================================== ============

Series (prices, indicators, rates) are stored per exact request: a range whose
end is past the series' finality lag is refreshed daily (split-adjusted history
can be re-based upstream), an open range by interval (60 s intraday, 1 h daily,
1 day for late-published data). Fetching only the missing ranges of a stored
series (gap-fill) is #1310.

A call about a past date (``date`` or ``to_date`` older than ``RECENT_DAYS``)
on an ephemeral or revisable endpoint is immutable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from openbb_fmp_cached_mcp.endpoint_map import endpoint_spec, load_tools

DAY = 86400
RECENT_DAYS = 2  # days still open to revision (today and yesterday)
NEGATIVE_TTL_S = 600  # remembered 4xx answers
REVISABLE_REFRESH_S = DAY
REFERENCE_REFRESH_S = DAY
FEED_LISTING_TTL_S = 600
SERIES_TAIL_TTL_DAILY_S = 3600
SERIES_TAIL_TTL_INTRADAY_S = 60

#: Ephemeral TTLs by REST path prefix (first match wins); default 900 s.
_EPHEMERAL_TTL: tuple[tuple[str, int], ...] = (
    ("/quote", 15),
    ("/batch-", 15),
    ("/aftermarket-", 15),
    ("/stock-price-change", 15),
    ("/company-screener", 900),
    ("/exchange-market-hours", 300),
    ("/all-exchange-market-hours", 300),
    ("/biggest-", 300),
    ("/most-actives", 300),
    ("/sector-", 300),
    ("/industry-", 300),
)
_EPHEMERAL_DEFAULT_TTL_S = 900
_INTRADAY_TIMEFRAMES = {"1min", "5min", "15min", "30min", "1hour", "4hour"}


@dataclass(frozen=True)
class Policy:
    """How one call is stored and refreshed."""

    mode: str  # "document" | "ephemeral" | "no-store"
    refresh_s: int | None  # document refresh (None = immutable) / ephemeral TTL
    retention: str
    feed: bool = False


def _has_range_params(tool: str) -> bool:
    props = next(t for t in load_tools() if t["name"] == tool)["inputSchema"][
        "properties"
    ]
    return "from_date" in props and "to_date" in props


def _is_past(value: Any, today: dt.date) -> bool:
    try:
        day = dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return day <= today - dt.timedelta(days=RECENT_DAYS)


#: Finality lag by REST path prefix for series published or revised late.
_FINAL_LAG_DAYS: tuple[tuple[str, int], ...] = (
    ("/economic-indicators", 120),  # GDP etc.: dated at period start, revised
    ("/commitment-of-traders-", 14),  # Tuesday positions published Friday
)


def final_lag_days(path: str) -> int:
    """Days after which a series row of ``path`` no longer changes."""
    for prefix, lag in _FINAL_LAG_DAYS:
        if path.startswith(prefix):
            return lag
    return RECENT_DAYS


def series_tail_ttl(path: str, args: dict[str, Any]) -> int:
    """Seconds an open series range stays fresh."""
    if (
        path.startswith("/historical-chart/")
        or args.get("timeframe") in _INTRADAY_TIMEFRAMES
    ):
        return SERIES_TAIL_TTL_INTRADAY_S
    if final_lag_days(path) > RECENT_DAYS:
        return DAY  # late-published data changes daily at most
    return SERIES_TAIL_TTL_DAILY_S


def _series_policy(path: str, args: dict[str, Any], today: dt.date) -> Policy:
    """Policy for a series call with an explicit ``from_date`` / ``to_date``."""
    try:
        end = dt.date.fromisoformat(str(args["to_date"])[:10])
        final = end <= today - dt.timedelta(days=final_lag_days(path))
    except (ValueError, OverflowError):
        final = False
    refresh = REVISABLE_REFRESH_S if final else series_tail_ttl(path, args)
    return Policy("document", refresh, "series")


def _ephemeral_ttl(path: str) -> int:
    for prefix, ttl in _EPHEMERAL_TTL:
        if path.startswith(prefix):
            return ttl
    return _EPHEMERAL_DEFAULT_TTL_S


# One return per retention rule keeps the table above readable.
# pylint: disable-next=too-many-return-statements
def resolve_policy(  # noqa: PLR0911
    tool: str, args: dict[str, Any], *, today: dt.date
) -> Policy:
    """Return the storage policy for ``tool`` called with ``args``."""
    spec = endpoint_spec(tool, args["endpoint"])
    retention: str = spec["retention"]
    path: str = spec["path"]
    if retention == "no-store":
        return Policy("no-store", None, retention)
    if retention == "series" and _has_range_params(tool):
        if "limit" in args or "page" in args:
            # FMP pages the range: a page is not the whole range, so it cannot
            # mark coverage. Keep it as a revisable document instead.
            return Policy("document", REVISABLE_REFRESH_S, retention)
        if "from_date" in args and "to_date" in args:
            return _series_policy(path, args, today)
        # Open-ended request (FMP picks the window): treat as a short-lived answer.
        return Policy("ephemeral", series_tail_ttl(path, args), retention)
    if retention in ("ephemeral", "revisable", "feed") and (
        ("date" in args and _is_past(args["date"], today))
        or ("to_date" in args and _is_past(args["to_date"], today))
    ):
        return Policy("document", None, retention)
    if retention == "immutable-doc":
        return Policy("document", None, retention)
    if retention == "revisable":
        return Policy("document", REVISABLE_REFRESH_S, retention)
    if retention == "reference":
        return Policy("document", REFERENCE_REFRESH_S, retention)
    if retention == "feed":
        return Policy("ephemeral", FEED_LISTING_TTL_S, retention, feed=True)
    if retention == "series":  # series endpoint without a date range in its schema
        return Policy("document", REVISABLE_REFRESH_S, retention)
    return Policy("ephemeral", _ephemeral_ttl(path), retention)
