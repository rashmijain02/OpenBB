"""Stable ids of the documented legacy-vs-Nautilus modelling differences (#1357 T03).

One constant per difference, shared by the code that reports them
(``ReconciliationReport.modeled_differences``) and by the design document
``docs/designs/backtest-design/14-nautilus-modeling-differences.md``, whose
sections are tagged ``**id:** `<id>```. A unit test keeps the two in sync, so a
difference cannot be reported without being explained (and vice versa).
"""

from __future__ import annotations

WHOLE_SHARE_QUANTITIES = "whole_share_quantities"
SETTLED_CASH = "settled_cash"
FILL_TIMING = "fill_timing"
FEE_MODEL = "fee_model"
STAGING_ORDER = "staging_order"
BOOKING_ROUNDING = "booking_rounding"
FIXED_PRECISION = "fixed_precision"
CORPORATE_ACTIONS_REJECTED = "corporate_actions_rejected"
BUY_AND_HOLD_SCOPE = "buy_and_hold_scope"
PER_FOLD_FRESH_CASH = "per_fold_fresh_cash"
SELECTION_STATISTICS = "selection_statistics"
SHARED_METRICS = "shared_metrics"
RECONCILE_DIAGNOSTIC_ONLY = "reconcile_diagnostic_only"

#: Every documented difference, in document order.
MODELED_DIFFERENCES: tuple[str, ...] = (
    WHOLE_SHARE_QUANTITIES,
    SETTLED_CASH,
    FILL_TIMING,
    FEE_MODEL,
    STAGING_ORDER,
    BOOKING_ROUNDING,
    FIXED_PRECISION,
    CORPORATE_ACTIONS_REJECTED,
    BUY_AND_HOLD_SCOPE,
    PER_FOLD_FRESH_CASH,
    SELECTION_STATISTICS,
    SHARED_METRICS,
    RECONCILE_DIAGNOSTIC_ONLY,
)
