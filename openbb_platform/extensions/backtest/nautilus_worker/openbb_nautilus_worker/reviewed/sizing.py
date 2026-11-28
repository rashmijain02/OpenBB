"""Whole-share floor sizing ``whole_share_floor_v1`` (#1356 T03, plan section 2.2).

At a decision close the equity is ``E = settled + unsettled + sum(qty * close)``
and each target is ``floor(w * E / close)`` whole shares, computed with exact
``Decimal`` integer division (never a rounded quotient).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def equity(cash: Decimal, held: Mapping[str, int], closes: Mapping[str, Decimal]):
    """Exact equity at the closes: cash plus every holding at its close."""
    return cash + sum((q * closes[s] for s, q in held.items()), Decimal(0))


def floor_shares(value: Decimal, price: Decimal) -> int:
    """``floor(value / price)`` exactly; zero for a non-positive value."""
    if value <= 0:
        return 0
    return int(value // price)


def weight_targets(
    weights: Mapping[str, Decimal], total: Decimal, closes: Mapping[str, Decimal]
) -> dict[str, int]:
    """Target shares per symbol for weights of ``total`` at the closes."""
    return {s: floor_shares(w * total, closes[s]) for s, w in sorted(weights.items())}


def equal_targets(
    symbols: tuple[str, ...], total: Decimal, closes: Mapping[str, Decimal]
) -> dict[str, int]:
    """Equal split of ``total`` across ``symbols``: ``floor(E / (n * close))``."""
    n = len(symbols)
    return {s: floor_shares(total, n * closes[s]) for s in sorted(symbols)}
