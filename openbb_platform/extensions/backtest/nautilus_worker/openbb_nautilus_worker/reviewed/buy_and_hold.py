"""Reviewed strategy ``buy_and_hold@1.0.0`` (#1356 T01).

Decides once, at the first session close: equal target weights over the listed
symbols, sized by the shared whole-share rule. Sizing, staging and booking are
shared reviewed code (added in T03) listed in ``code_files``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from . import sizing
from .hashing import digest
from .params import BuyAndHoldParams
from .spec import StrategySpec, SupportedAssumptions

STRATEGY_ID = "buy_and_hold"
VERSION = "1.0.0"
PARAMS_MODEL = BuyAndHoldParams

SUPPORTED = SupportedAssumptions(
    decision=("session_close",),
    fill_timing=("next_open", "same_close"),
    sizing=("whole_share_floor_v1",),
    staging=("sell_then_buy_v1",),
    account=("CASH",),
    settlement=("T+1", "T+2"),
    cash_model=("settled_cash_only",),
    fees=("zero", "taker_bps"),
    booking=("nautilus_f64_half_away_cents_v1",),
    marks=("exact_decimal_half_even_cents_v1",),
    corporate_actions=("reject_if_present_in_window",),
)

CODE_FILES = (
    "reviewed/buy_and_hold.py",
    "reviewed/spec.py",
    "reviewed/params.py",
    "reviewed/hashing.py",
    "reviewed/sizing.py",
    "reviewed/staging.py",
    "reviewed/booking.py",
    "reviewed/host.py",
)


def build_spec() -> StrategySpec:
    """Return the spec as the code under review defines it."""
    return StrategySpec(
        strategy_id=STRATEGY_ID,
        version=VERSION,
        code_files=CODE_FILES,
        param_schema_sha256=digest(PARAMS_MODEL.model_json_schema()),
        supported=SUPPORTED,
    )


def universe(params: BuyAndHoldParams) -> tuple[str, ...]:
    """Symbols the strategy trades."""
    return tuple(params.symbols)


def decide(
    params: BuyAndHoldParams,
    session: int,
    equity: Decimal,
    closes: Mapping[str, Decimal],
) -> dict[str, int] | None:
    """Decide once, at the first close: an equal whole-share split of equity."""
    if session != 0:
        return None
    return sizing.equal_targets(tuple(params.symbols), equity, closes)
