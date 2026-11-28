"""Matched-basis fundamentals: pure functions, no database (#1345-T02)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from portfolio_utils.fmp_sync import fundamentals as f
from portfolio_utils.fmp_sync.checks import CheckState, aggregate

D = Decimal
AS_OF = date(2026, 11, 27)
SPLIT = date(2024, 8, 28)


def basis(**over):
    base = dict(
        share_class="COMMON",
        unit="shares",
        currency="USD",
        as_of=AS_OF,
        split_basis=SPLIT,
    )
    return f.Basis(**{**base, **over})


def q(value, **over):
    return f.Quantity(
        None if value is None else D(str(value)), basis(**over), "synthetic"
    )


def test_float_gt_outstanding_matched_basis_warn():
    out = f.float_vs_outstanding(q(120), q(100))
    assert (out.state, out.reason_code) == (
        CheckState.WARN,
        "FLOAT_EXCEEDS_OUTSTANDING",
    )
    assert f.float_vs_outstanding(q(100), q(100)).state is CheckState.OK
    assert f.float_vs_outstanding(q(80), q(100)).state is CheckState.OK


@pytest.mark.parametrize(
    "over",
    [
        {"share_class": "CLASS_B"},
        {"unit": "thousands"},
        {"as_of": date(2026, 9, 30)},
        {"split_basis": date(2025, 1, 1)},
        {"currency": "EUR"},
    ],
)
def test_basis_mismatch_unknown(over):
    # 120 > 100 would WARN on a matched basis; a mismatched basis must not judge.
    out = f.float_vs_outstanding(q(120, **over), q(100))
    assert (out.state, out.reason_code) == (CheckState.UNKNOWN, "BASIS_MISMATCH")


def test_unknown_basis_field_is_not_a_match():
    out = f.float_vs_outstanding(q(120, split_basis=None), q(100, split_basis=None))
    assert (out.state, out.reason_code) == (CheckState.UNKNOWN, "BASIS_MISMATCH")


def test_missing_inputs_unknown_never_ok():
    assert f.float_vs_outstanding(None, q(1)).reason_code == "MISSING_INPUT"
    assert f.float_vs_outstanding(q(None), q(1)).state is CheckState.UNKNOWN
    assert f.market_cap_divergence(q(1), None, q(1)).state is CheckState.UNKNOWN
    assert f.current_fy_estimates(None, 2026).state is CheckState.UNKNOWN
    assert f.repeated_diluted_shares([]).state is CheckState.UNKNOWN
    unknown = f.float_vs_outstanding(None, None).model_copy(update={"required": True})
    assert aggregate([unknown]) == "UNKNOWN"


def test_mcap_divergence_threshold_boundary():
    price, shares = q(10), q(10)  # implied market cap 100
    assert f.market_cap_divergence(q(115), price, shares).state is CheckState.OK
    assert f.market_cap_divergence(q(85), price, shares).state is CheckState.OK
    over = f.market_cap_divergence(q("115.01"), price, shares)
    assert (over.state, over.reason_code) == (CheckState.WARN, "MARKET_CAP_DIVERGES")
    assert f.market_cap_divergence(q("84.99"), price, shares).state is CheckState.WARN
    assert f.market_cap_divergence(q(115), price, q(10, unit="thousands")).state is (
        CheckState.UNKNOWN
    )


def _quarters(*values):
    return [
        (date(2025, 3 * (i + 1), 28), None if v is None else D(str(v)))
        for i, v in enumerate(values)
    ]


def test_repeated_diluted_shares_three_quarters_warn_two_ok():
    warn = f.repeated_diluted_shares(_quarters(90, 100, 100, 100))
    assert (warn.state, warn.counts["longest_run"]) == (CheckState.WARN, 3)
    assert f.repeated_diluted_shares(_quarters(90, 100, 100, 95)).state is CheckState.OK
    assert (
        f.repeated_diluted_shares(_quarters(100, 100, None, 100)).state is CheckState.OK
    )


def test_repeated_diluted_shares_same_quarter_counted_once():
    same = [
        (date(2025, 3, 28), D(100)),
        (date(2025, 3, 28), D(100)),
        (date(2025, 6, 28), D(100)),
    ]
    assert f.repeated_diluted_shares(same).state is CheckState.UNKNOWN


def test_current_fy_estimates_missing_warn():
    assert f.current_fy_estimates([2027, 2028], 2026).state is CheckState.WARN
    assert f.current_fy_estimates([2026, 2027], 2026).state is CheckState.OK
    assert (
        f.current_fy_estimates([], 2026).reason_code == "CURRENT_FY_ESTIMATES_MISSING"
    )


def test_json_blob_sources_not_evaluated():
    out = f.json_blob_sources()
    assert {c.check_id for c in out} == {
        "fundamentals.shares_float",
        "fundamentals.analyst_estimates",
    }
    assert {(c.state, c.reason_code, c.required) for c in out} == {
        (CheckState.NOT_EVALUATED, "SOURCE_NOT_ADMITTED", False)
    }


def test_profile_price_rows_without_currency_or_close_are_unknown():
    rows = [{"symbol": "AAA", "price": 1.0, "currency": None, "close": 1.0}]
    assert f.profile_price_check(rows).reason_code == "BASIS_MISMATCH"
    rows = [{"symbol": "AAA", "price": 1.0, "currency": "USD", "close": None}]
    assert f.profile_price_check(rows).state is CheckState.UNKNOWN
    assert f.profile_price_check([]).reason_code == "NO_PROFILE_ROWS"
