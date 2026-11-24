"""Retention policy per tool call (#1300, plan §4.2).

``fmp_cached`` is a persistent store: meaningful results are kept for good and
only genuinely ephemeral data has a TTL.

========== ======================================================== ============
mode       behaviour                                                classes
========== ======================================================== ============
series     rows kept forever; FMP called only for missing ranges     ``series``
           and the open tail (the last ``RECENT_DAYS``)
document   kept forever; ``refresh_s=None`` -> fetched once,        ``immutable-doc``,
           otherwise refreshed after ``refresh_s`` (last good copy  ``revisable``,
           kept and served on upstream errors)                      ``reference``
ephemeral  short TTL, prunable; feed items are also kept forever    ``ephemeral``, ``feed``
no-store   always live                                              ``no-store``
========== ======================================================== ============

A call about a past date (``date`` or ``to_date`` older than ``RECENT_DAYS``)
is immutable whatever its endpoint's class.
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

    mode: str  # "series" | "document" | "ephemeral" | "no-store"
    refresh_s: int | None  # document refresh / ephemeral TTL / series tail TTL
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


def series_tail_ttl(path: str, args: dict[str, Any]) -> int:
    """Seconds a fetched open tail stays fresh."""
    if (
        path.startswith("/historical-chart/")
        or args.get("timeframe") in _INTRADAY_TIMEFRAMES
    ):
        return SERIES_TAIL_TTL_INTRADAY_S
    return SERIES_TAIL_TTL_DAILY_S


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
            return Policy("series", series_tail_ttl(path, args), retention)
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
