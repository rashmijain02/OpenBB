"""Declared fixed-point rounding for reviewed runs (#1356 T03, plan section 2.5).

Two rules, never mixed:

* **Booking** (cash debits/credits and commissions) reproduces the engine's own
  rule exactly: Nautilus builds ``Money`` from a binary double and rounds
  ``x * 100`` half away from zero. A notional is ``f64(qty) * f64(price)``; a
  commission is ``notional_booked * taker_rate`` passed through ``Money``.
  ``Decimal(float)`` is the exact value of the double, so ``ROUND_HALF_UP`` on it
  is half away from zero for the non-negative amounts booked here.
* **Marks** (equity and cash in the output) are exact ``Decimal`` sums rounded
  HALF_EVEN to cents.

The exact-minus-booked difference of every notional is recorded as the residual.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
_BPS = Decimal(10_000)


def money(amount: float | Decimal) -> Decimal:
    """Book an amount as the engine does: ``f64`` then half away, in cents."""
    scaled = Decimal(float(amount) * 100.0).to_integral_value(rounding=ROUND_HALF_UP)
    return (scaled / 100).quantize(CENT)


def notional(quantity: int, price: Decimal) -> Decimal:
    """Booked notional: ``f64(qty) * f64(price)`` through :func:`money`."""
    return money(float(quantity) * float(price))


def residual(quantity: int, price: Decimal) -> Decimal:
    """Exact notional minus booked notional (recorded, never applied)."""
    return quantity * price - notional(quantity, price)


def taker_rate(taker_bps: Decimal | None) -> Decimal:
    """Commission rate from basis points (zero fees when ``None``)."""
    return Decimal(0) if taker_bps is None else Decimal(taker_bps) / _BPS


def commission(booked_notional: Decimal, rate: Decimal) -> Decimal:
    """Booked commission on a booked notional (zero when the rate is zero)."""
    if rate == 0:
        return Decimal("0.00")
    return money(booked_notional * rate)


def buy_cost(quantity: int, price: Decimal, rate: Decimal) -> Decimal:
    """Booked cash a buy debits: notional plus commission."""
    booked = notional(quantity, price)
    return booked + commission(booked, rate)


def mark(amount: Decimal) -> Decimal:
    """Exact amount rounded HALF_EVEN to cents (equity and cash output)."""
    return amount.quantize(CENT, rounding=ROUND_HALF_EVEN)
