"""Reviewed strategy ``target_weight_rebalance@1.0.0`` (#1356 T01).

Re-applies long-only, unlevered target weights every N sessions, sized by the
shared whole-share rule. Sizing, staging and booking are shared reviewed code
(added in T03) listed in ``code_files``.
"""

from __future__ import annotations

from .hashing import digest
from .params import TargetWeightRebalanceParams
from .spec import StrategySpec, SupportedAssumptions

STRATEGY_ID = "target_weight_rebalance"
VERSION = "1.0.0"
PARAMS_MODEL = TargetWeightRebalanceParams

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
    "reviewed/target_weight_rebalance.py",
    "reviewed/spec.py",
    "reviewed/params.py",
    "reviewed/hashing.py",
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


def universe(params: TargetWeightRebalanceParams) -> tuple[str, ...]:
    """Symbols the strategy trades, in symbol (sorted) order."""
    return tuple(sorted(params.weights))
