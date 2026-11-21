"""Server-side labels and metric cards for the Terminal widgets (#1268).

Workspace's widget schema is closed, so a manifest cannot carry viewer-only
label maps (``valueLabels``, ``rowLabels``, ``rowLabelPatterns``) or metric
configuration (``data.metric``). Workspace shows the response value as-is,
so the endpoint returns the readable label itself:

- :func:`label_rows` replaces enum codes and row identifiers with labels
  (unknown values pass through unchanged, so nothing is dropped);
- :func:`relabel` applies that to whatever an endpoint (or its provider
  tier) returned;
- :func:`metric_cards` builds Workspace metric cards (``[{label, value}]``)
  with an explicit data-state card, so demo and unavailable values are
  never shown as bare numbers or a fabricated ``0.0``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

Row = Mapping[str, Any]
Pattern = tuple[re.Pattern[str], str]

#: Label of the card that states where metric values came from.
DATA_STATE_LABEL = "Data State"
UNAVAILABLE = "Unavailable"

EVENT_TYPE_LABELS = {
    "earnings": "Earnings",
    "ex_dividend": "Ex-Dividend",
    "form_8k": "Form 8-K",
    "info": "Information",
}
SMART_MONEY_KIND_LABELS = {
    "insider_buy": "Insider Buy",
    "13F_increase": "13F Increase",
    "insider_sell": "Insider Sell",
    "info": "Information",
}
ALERT_KIND_LABELS = {
    "form_8k_for_held": "Held-Security Form 8-K",
    "earnings_upcoming": "Upcoming Earnings",
    "news_material": "Material News",
}
CONSENSUS_LABELS = {
    "STRONG_BUY": "Strong Buy",
    "BUY": "Buy",
    "HOLD": "Hold",
    "SELL": "Sell",
    "STRONG_SELL": "Strong Sell",
    "PENDING": "Pending",
}
TECHNICAL_ROW_LABELS = {
    "Consensus": "Analyst Consensus",
    "R3 (Classic)": "Resistance 3",
    "R2 (Classic)": "Resistance 2",
    "R1 (Classic)": "Resistance 1",
    "P (Classic)": "Pivot",
    "S1 (Classic)": "Support 1",
    "S2 (Classic)": "Support 2",
    "S3 (Classic)": "Support 3",
    "ATM IV term structure": "ATM Implied Volatility Term Structure",
}
FORECAST_ROW_LABELS = {
    "1Y target (consensus)": "12-Month Price Target",
    "Target range": "Target Range",
    "Upside vs current": "Upside vs Current Price",
    "Historical rev estimate (last Q)": "Historical Revenue Estimate",
}
FORECAST_ROW_PATTERNS: tuple[Pattern, ...] = (
    (re.compile(r"^Rating:\s*(.+)$"), r"Rating Distribution: \1"),
    (re.compile(r"^(Q\d\s+\d{4})\s+EPS Surprise$"), r"\1 EPS Surprise"),
)
WHATIF_ROW_LABELS = {
    "symbol_weight_%": "Symbol Weight (%)",
    "sector_weight_%": "Sector Weight (%)",
    "cash_%": "Cash Weight (%)",
    "beta_spy": "Beta vs SPY",
}


def _label(value: Any, labels: Mapping[str, str], patterns: Iterable[Pattern]) -> Any:
    if not isinstance(value, str):
        return value
    if value in labels:
        return labels[value]
    for pattern, template in patterns:
        if pattern.match(value):
            return pattern.sub(template, value)
    return value


def label_rows(
    rows: Iterable[Row],
    field: str,
    labels: Mapping[str, str],
    patterns: Sequence[Pattern] = (),
) -> list[dict[str, Any]]:
    """Return copies of ``rows`` with ``field`` replaced by its display label."""
    out = []
    for row in rows:
        copy = dict(row)
        if field in copy:
            copy[field] = _label(copy[field], labels, patterns)
        out.append(copy)
    return out


def relabel(
    field: str, labels: Mapping[str, str], patterns: Sequence[Pattern] = ()
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Label ``field`` in an endpoint's rows, whichever tier served them.

    ``functools.wraps`` keeps the wrapped signature and return annotation,
    so FastAPI's parameters and response model are unchanged.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return label_rows(func(*args, **kwargs), field, labels, patterns)

        return wrapper

    return decorator


def metric_cards(
    values: Sequence[tuple[str, float | str]], *, available: bool, state: str
) -> list[dict[str, float | str]]:
    """Return Workspace metric cards followed by one data-state card.

    ``available=False`` replaces every value with ``"Unavailable"`` so no
    placeholder number is ever shown as if it were measured. ``state`` is the
    text of the trailing card, e.g. ``"Demo: synthetic sample book"``.
    """
    cards: list[dict[str, float | str]] = [
        {"label": label, "value": value if available else UNAVAILABLE}
        for label, value in values
    ]
    cards.append({"label": DATA_STATE_LABEL, "value": state})
    return cards
