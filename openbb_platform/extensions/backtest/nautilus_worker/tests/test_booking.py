"""Booking and marks against the hand-computed cases C3a, C3b, C4 (#1356 T03).

The expected values are literals from ``cash_cases.json`` and plan section 2.6,
never recomputed from the code under test. Each case is chosen so that the
three candidate rules (HALF_EVEN, exact half-up, the engine's ``f64`` half
away) give different literals; only the declared engine rule passes.
"""

# ruff: noqa: D103

from __future__ import annotations

from decimal import Decimal

from openbb_nautilus_worker.reviewed import booking, staging

D = Decimal


def _expected(cash_cases, name):
    return cash_cases["cases"][name]["expected"]


def test_c3a_exact_tie_books_half_away_and_marks_half_even(cash_cases):
    exp = _expected(cash_cases, "c3a")
    booked = booking.notional(1, D("20.125"))
    assert booked == D("20.13")  # HALF_EVEN would give 20.12
    cash = D("30.00") - booked
    assert str(cash) == exp["cash"]
    assert str(booking.mark(cash + D("20.115"))) == exp["equity"][1]  # not 29.99
    assert booking.residual(1, D("20.125")) == D(exp["booking_residual"])


def test_c3b_binary_tie_books_down_like_the_engine(cash_cases):
    exp = _expected(cash_cases, "c3b")
    booked = booking.notional(1, D("1.005"))
    assert booked == D("1.00")  # exact half-up would give 1.01
    cash = D("1.50") - booked
    assert str(cash) == exp["cash"]
    assert str(booking.mark(cash + D("1.005"))) == exp["equity"][1]
    assert booking.residual(1, D("1.005")) == D(exp["booking_residual"]) == D("0.005")


def test_c4_taker_fee_limits_quantity(cash_cases):
    exp = _expected(cash_cases, "c4")
    rate = booking.taker_rate(D("10"))
    assert booking.buy_cost(10, D("99.99"), rate) == D("1000.90")
    q = staging.max_affordable(D("1000.00"), D("99.99"), rate, 10)
    assert q == exp["positions"]["FFF"] == 9
    fee = booking.commission(booking.notional(9, D("99.99")), rate)
    assert str(fee) == exp["trades"][0][5] == "0.90"
    assert str(D("1000.00") - booking.buy_cost(9, D("99.99"), rate)) == exp["cash"]


def test_zero_rate_commission_is_zero():
    assert booking.commission(D("123.45"), booking.taker_rate(None)) == D("0.00")


def test_marks_are_half_even_cents():
    assert booking.mark(D("29.985")) == D("29.98")
    assert booking.mark(D("29.995")) == D("30.00")
