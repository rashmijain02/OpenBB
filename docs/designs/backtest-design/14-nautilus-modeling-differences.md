# 14 — Nautilus vs legacy: material modelling differences

**GitHub:** #1357 (validation and trial accounting) · **Depends on:** #1355 (worker), #1356 (reviewed strategies and cash model)

The `nautilus` backend runs reviewed strategies in an isolated worker and projects the result onto the
same `BacktestResult` shape as the legacy engines. It does **not** reproduce the legacy numbers. This
document lists every difference that can move a result, so a reader of a `reconcile`, `sweep`,
`validate` or `tearsheet` report knows why two backends disagree.

Each section carries an `**id:**` tag. The same ids are the constants in
`openbb_backtest/modeled_differences.py` and are returned in
`ReconciliationReport.modeled_differences`; a unit test
(`tests/unit/validation/test_bench.py`) fails when the code and this document list different ids.
Evidence cases (`c1` ... `c4`) are the hand-written literals in
`tests/unit/nautilus/fixtures/cash_cases.json`; they have no regeneration path.

**Agreement is diagnostic, never a gate.** `reconcile` with `backend="nautilus"` reports
`diagnostic_only=true`, rejects `strict=True`, and a large divergence is expected, not a failure.
Legacy golden pins (`test_legacy_golden_1357.py`) guard the legacy numbers; nothing asserts that the
two engines agree.

## 1. Execution and cash

**id:** `whole_share_quantities`

- Legacy: fractional share quantities. Nautilus: whole shares, `floor(target value / price)`
  (`whole_share_floor_v1`), so a position can be smaller than its target and cash is left over.
- Effect: lower invested fraction, more idle cash, quantisation noise on small accounts.
- Evidence: `c1`, `c1p`.

**id:** `settled_cash`

- Legacy: proceeds are available at once. Nautilus: cash account, settled cash only, settlement
  `T+1` (default) or `T+2`; a buy cannot spend unsettled sale proceeds. `T+0` is rejected.
- Effect: after a sale the next buy can be smaller or later than legacy.
- Evidence: `c2` (T+1), `c2b` (T+2).

**id:** `fill_timing`

- Legacy: fills at the decision close. Nautilus: `next_open` (default) fills at
  the next session open, so a gap changes quantity and price; `same_close` is available explicitly.
- Effect: gap risk is paid on `next_open`; an order is dropped with warning `orders_pending_at_end`
  when no next session exists.
- Evidence: `c1` (gap-up shortfall), `c1p` (same close).

**id:** `fee_model`

- Legacy: commission and slippage models on the config. Nautilus: those config fields must be zero
  (`legacy_cost_model` is rejected); costs are declared in `strategy_params["execution"]` as `zero`
  or `taker_bps` (0 < bps <= 100), booked through `Money`, and they also limit the buy size.
- Effect: no commission minimum, no slippage model; fees reduce the whole-share quantity.
- Evidence: `c4`.

**id:** `staging_order`

- Legacy: buys may be placed before sells. Nautilus: sell-then-buy (`sell_then_buy_v1`), buys sized
  from settled cash after the sells were staged.
- Effect: a rebalance that relied on same-day sale proceeds buys less.
- Evidence: `c2`; planner-only cases in `cash_cases.json`.

## 2. Numbers and rounding

**id:** `booking_rounding`

- Legacy: float arithmetic end to end. Nautilus: cash debits, credits and commissions are booked the
  way the engine books them (`f64(qty) * f64(price)`, then `x * 100` rounded half away from zero to
  cents); marks (equity, cash in the output) are exact `Decimal` sums rounded half-even to cents.
  The exact-minus-booked amount of every notional is recorded as the **booking residual**
  (`provenance.booking_residual`), reported and never applied.
- Effect: cent-level differences between booked cash and exact marks; the residual explains them.
- Evidence: `c3a` (tie exactly representable), `c3b` (tie not representable in binary).

**id:** `fixed_precision`

- Nautilus runs at fixed precision 9 (pinned in the runtime facts and bound into every configuration
  id of an experiment).- Effect: a precision change creates new configuration ids, so old and new trials are never merged.

## 3. Scope

**id:** `corporate_actions_rejected`

- Legacy: no such rejection. Nautilus: a window containing a split or dividend is rejected before the
  run (`corporate_actions_present`, #1385); there is no adjustment path.
- Effect: real cached data with corporate actions fails closed instead of producing a number.

**id:** `buy_and_hold_scope`

- The reviewed `buy_and_hold@1.0.0` decides once at the first session close and the worker host
  accepts exactly one symbol (`buy_and_hold needs exactly one symbol`). Legacy buy-and-hold accepts
  a basket. `target_weight_rebalance@1.0.0` handles several symbols (long-only, unlevered).
- Effect: multi-symbol buy-and-hold comparisons need the rebalance strategy or are unsupported.

## 4. Validation and metrics

**id:** `per_fold_fresh_cash`

- Window policy is explicit: `continuous` runs one window over the full range and treats folds as
  index views of one path; `per_fold` runs one window per atomic test window, each starting from
  fresh initial cash. A CPCV test set is never run as one span across a training group.
- Effect: per-fold results are not comparable with a continuous run's slice, and cash and positions
  do not carry across `per_fold` windows.

**id:** `selection_statistics`

- On the nautilus path `N` for the deflated Sharpe ratio is the number of **configurations** in the
  trial ledger plus declared `external_trials` (never the number of folds); PBO columns are
  configurations; undefined PBO is `None` and caps the verdict at `fragile`; excluded cells count in
  `N` and make the matrix incomplete. The minimum backtest length keeps the `2 ln N / SR^2`
  approximation. See the legacy findings below for what the legacy path does differently.

**id:** `shared_metrics`

- Metrics (Sharpe, drawdown, ...) come from the shared `_metrics_from_returns` over the projected
  equity curve; Nautilus analyzers are not used. Differences from legacy metrics therefore come from
  the equity curve, not from a different formula.

**id:** `reconcile_diagnostic_only`

- `reconcile` on `nautilus` never fails on divergence, rejects `strict=True`, and always sets
  `diagnostic_only=true`. The documented differences above are the expected explanation of any
  divergence (`max_divergence > 0` is normal when quantities are whole shares).

## 5. Known legacy issues, fixed at P18 cutover

The legacy statistics stay unchanged in P17 (decision D6) so existing reports keep their meaning;
the nautilus path never inherits F2 to F5. They are recorded here as the follow-up list for the P18
cutover (one `type-bug` issue, filed after owner confirmation).

| # | Where | Finding | Fix at P18 |
|---|---|---|---|
| F1 | `validation/stats.py` `deflated_sharpe` | The benchmark is E[max of N unit-variance normals] with no cross-trial Sharpe variance, so with per-observation Sharpe (~0.06/day) any N > 1 drives DSR to ~0. | `sr_variance` keyword exists (default keeps legacy bit-identical); pass the real `V[SR_n]`. |
| F2 | `routers/validate_router.py` `_run_folds` | CPCV test sets of non-adjacent groups run as one contiguous span that includes train groups. | Run atomic windows (already done on the nautilus path). |
| F3 | same | `n_trials = len(folds)`: N counts folds, not configurations. | N from configurations plus external trials. |
| F4 | same, `_pbo_from_folds` | Folds are stacked as PBO columns; this measures fold dispersion, not selection overfit. | Configurations as columns. |
| F5 | same | An undefined PBO is returned as `0.0`, which is fail-open (helps "robust"). | Undefined stays `None` and caps the verdict. |
| F6 | techtrade `tuning/tune_router.py` | The tuneta search count (`trials=100`) never reaches DSR, so N is understated by about 100x. | Pass `external_trials=trials` from tune. |

## 6. Benchmark

`python -m openbb_backtest.validation.experiment bench --spec tests/unit/validation/fixtures/bench_spec.json --runtime fake`
runs two reviewed strategies over a seeded synthetic bundle (756 sessions, two symbols), WFO and
CPCV(6,2), both window policies, and prints counts, codes and timings only. `--inject-kill K`,
`--inject-fail-once`, `--inject-reject` and `--inject-changed-data` add deterministic failure
injection. Timings are reported, never asserted. The native run (`--runtime native`) is a LIVE step.

The WFO layout copies the legacy `_run_folds` split: train = T//2 and test = step = T//4
sessions, which always gives 2 folds (378 train / 189 test sessions for T = 756), not 4. The fold
logic itself is unchanged in P17.
