# Plan: standardize reviewed strategies and preserve OpenBB callers (#1356, HFP-P16)

Status: **design draft, not committed.** Base `origin/portfolio` @ `a5b190f79` (#1355 merged via PR #1395; #1340 closed).
Parent #1329 (HFP-F07). Requirements BT-01, BT-02. Sources: spec.md §9.1, plan.md §3.1–3.3, github-plan HFP-P16..P18,
`specs/gh-1355-hfp-nautilus-runtime/plan.md`. Nautilus facts were read from pinned source `27a8e54e` (raw GitHub, read-only).
No product code here. Synthetic data only. **#1355 LIVE steps (T01-L..T03-L) are still open**, so every P16 LIVE step waits for them.

## 0. Existing assets and what they imply

| Asset | Fact | Consequence |
|---|---|---|
| `openbb_backtest/registry.py`, `strategies/discovery.py` | Mutable name→class registry; `resolve()` lazily walks the `openbb_backtest_strategies` entry points (techtrade ships `techtrade_confluence`) and calls `cls(**params)`. | The legacy path keeps this unchanged. The reviewed path must **never** call it: it uses a separate frozen allowlist, with no entry points, no `importlib` on strings, and no class objects taken from requests. |
| `engine/event_driven.py::_run_ledger` | Target weight × equity at the open / open price = **fractional** shares. It loops over symbols in universe order (buys can come before sells), has no settlement, does not stop cash going negative, and rounds outputs with `_round_money(float)` (HALF_EVEN cents through float). | Legacy cannot honour whole-share, settled-cash or sell-first semantics. A reviewed spec that declares them must be **rejected on legacy**, not approximated. |
| `models.py` `BacktestConfig` / `BacktestResult` | `engine: auto|vectorized|event`, `engine_used: str`. Money is `Decimal`. No provenance field. | Additive optional fields only (§2.4). |
| `nautilus_worker/.../runs.py` | `run` op: buy-and-hold only. Order = `floor(cash/close0)`, fills at the first close (`on_bar`). The worker re-derives cash from fills and checks it against the engine's `balance_total` at cents. `Engine` seam = `Callable[[RunSpec], EngineResult]`. | P16 widens this to reviewed multi-asset strategies and keeps "engine reports fills, worker does the accounting, exact cross-check". |
| `nautilus_worker/.../admission.py` `RunRequest` | `strategy: Literal["buy_and_hold"]`, `SIM/NETTING/CASH/USD`, `fees: "zero"`, `extra="forbid"`. | Becomes `RunRequest` v2 (§2.1). The `strategy="buy_and_hold"` alias stays, so the #1355 probe and LIVE commands keep working. |
| `protocol.ErrorCode` | Values equal `FailedLayer` (lead decision L5: no new members). | Code drift ⇒ `module_origin`. Parameter, spec or semantics mismatch ⇒ `schema`. Unsupported account or venue ⇒ `egress`/`config` as in #1355. |
| Nautilus 1.231.0 (`accounting/accounts/cash.pyx`, `model/instruments/base.pyx`, `model/objects.pyx`, `crates/model/src/types/fixed.rs`) | A CASH account has **no settlement concept**: sale proceeds are free at once. `notional_value = Money(f64(qty)*f64(px))`. `Money(x)` does `float(x)` and then `round(x*100)`, which is **half away from zero on a binary double**. Commission = `Money(notional.as_decimal()*taker_fee)`. Venue options include `bar_execution`, `trade_execution` and `allow_cash_borrowing=False`. | Settlement (T+1/T+2) and sell-first staging are **OpenBB-owned logic inside the reviewed strategy host**, as spec §9.1 requires ("do not assume Nautilus supplies settled-cash/T+1"). The booking rounding rule is declared as the engine's own rule and reproduced exactly (§2.5). |
| `docs/designs/backtest-design/11-adapters.md` / issue #4 | Generic `EngineAdapter` framework (open). | P16 adds **no** generic adapter protocol and does not use `register_engine` for Nautilus. A plain `backend` switch dispatches to one Nautilus module. |
| `tests/golden/fixtures/buy_and_hold.json` | Output of the legacy vectorized engine, refreshed with `BACKTEST_REGEN_GOLDEN`. | Not an oracle. The P16 cash cases are hand-written literals with **no regeneration path**. |

### Callers and the contracts they rely on (all must stay green)

| # | Caller | Contract pinned |
|---|---|---|
| C-a | `obb.backtest.run` (`routers/run_router.py::run`) | Signature `(config, engine="auto", strategy_params=None, provider=None)`. Engine precedence (bd-q7u5) = parameter, then `config.engine`, then auto. `OBBject[BacktestResult]` with `positions == []` (`sanitize_result`). |
| C-b | `obb.backtest.sweep` / `reconcile` | Vectorized/event only. `SweepResult`, `ReconciliationReport` fields. |
| C-c | `obb.backtest.validate` / `tearsheet` (`routers/validate_router.py`) | `config.engine` resolution; `ValidationReport` / `TearSheet`. |
| C-d | MCP story job `story.backtest` (`mcp_server/.../story_job_kinds.py::run_backtest`) | `BacktestPayload{config: BacktestConfig, engine: auto|vector|event, strategy_params}` with `extra="forbid"`. Returns `result.results.model_dump(mode="json")`. |
| C-e | techtrade `validation/backtest_bridge.py::validate_plan` (+ `story.validate`, `story.tune`) | `validate_router.validate(config, method, thresholds, strategy_params, provider)` with the entry-point plugin `techtrade_confluence`. |
| C-f | portfolio_intel `execution/simple_fill.py`, `handoff/backtest_export.py` | Imports `engine.execution.{Commission,Slippage}` and `models.{Bar,CommissionModel,SlippageModel,Trade}`. Trade field names and types. `routers/backtest_router.py` probes a non-existent `obb.backtest.portfolio` (stub; unaffected). |
| C-g | Notebooks `portfolio{,_yfinance}/06,07,08`, `techtrade/01,04,05` | Keyword calls to `run`, `sweep`, `tearsheet`, `validate`, `bundle.ingest`, `factor_eval`. |
| C-h | `mcp_server/tests/app/test_analytics_profiles.py`, `backtest/tests/integration/test_router_surface_integration.py` | **10** `/api/v1/backtest` routes. No new command may be added. |

## 1. Design summary

```
caller -> run_router.run(config, engine, strategy_params, provider, backend=None)
            resolve_backend(param > config.backend > DEFAULT "legacy")  -- recorded, never silently changed
   legacy:   unchanged path (+ provenance{backend:"legacy", strategy_review:"unreviewed"|"reviewed-incompatible"=>reject})
   nautilus: reviewed.resolve(id[,version]) -> StrategySpec + validated params + ExecutionAssumptions
             -> export neutral dataset from the same Bundle (#1355 export.py) -> WorkerClient.run(v2 body)
             worker: re-resolve spec from ITS allowlist, recompute code/params/spec hashes, admit, run host,
                     independent settled-cash ledger, exact cross-check vs engine -> body
             -> projection.to_backtest_result(body) -> sanitize_result -> OBBject
   any nautilus failure => typed error; legacy engine is never called (spy-tested)
```

## 2. Design details

### 2.1 `StrategySpec` (pure pydantic, `extra="forbid"`, frozen; lives in the worker package so both sides import one module)
- `strategy_id` must match `^[a-z][a-z0-9_]{0,47}$` (no dots, colons or slashes, so no dotted paths). `version` is SemVer.
  P16 reviews exactly two: `buy_and_hold@1.0.0` and `target_weight_rebalance@1.0.0`. TechTrade entry/stop/target is HFP-P18-T01.
- `code_files`: tuple of package-relative paths (the strategy module + `reviewed/{spec,params,sizing,staging,booking,host}.py`).
  `code_sha256 = sha256(canonical_json([[path, sha256(LF-normalised UTF-8 bytes)] ...]))`. CRLF checkouts hash the same.
- `param_model`: a per-strategy pydantic model with bounds. buy_and_hold: `symbols` 1–50. rebalance: `weights{sym: Decimal str}` with
  each ≥ 0 and sum ≤ 1 (long-only, no leverage), `rebalance_every_sessions` 1–252. `param_schema_sha256` = hash of
  `model_json_schema()`, pinned. `params_sha256 = sha256(canonical_json({id, version, params}))` after validation and normalisation
  (Decimal strings normalised; float input `1.0` is converted through `str` and becomes `"1"`; key order does not matter).
- `supported` execution assumptions (a run picks one of each; the choice is a separate `ExecutionAssumptions` model with its own
  `execution_sha256`): `decision="session_close"`. `fill_timing ∈ {next_open, same_close}`, default `next_open`.
  `next_open` is implemented as a synthetic open print (`TradeTick` at `bar.ts_event − 1 ns`, price = bar open) consumed by the host. `same_close` fills
  in `on_bar`, as in #1355. Also: `sizing="whole_share_floor_v1"`, `staging="sell_then_buy_v1"`, `account="CASH"`, `borrowing=False`,
  `short=False`, `settlement ∈ {T+1, T+2}` (default T+1, counted in sessions of the manifest calendar), `cash_model="settled_cash_only"`,
  `fees ∈ {zero, taker_bps(0..100)}`, `booking="nautilus_f64_half_away_cents_v1"`, `marks="exact_decimal_half_even_cents_v1"`,
  `corporate_actions="reject_if_present_in_window"`.
- `spec_sha256` = hash of the spec without the params. The run binds the tuple
  `(spec_sha256, code_sha256, params_sha256, execution_sha256, dataset_id, engine version)`. That tuple is acceptance bullet 1.
- **Allowlist / loader.** `reviewed/registry.py` holds a frozen `MappingProxyType{(id, version): StrategySpec}` with **pinned**
  `code_sha256` and `param_schema_sha256` literals. Resolution = dictionary lookup, then hash recomputation from the *local* package
  files. A mismatch raises `strategy_code_drift` (`module_origin`) or `param_schema_drift` (`schema`). The worker does the same against its
  installed copy, so a stale worker venv is caught. If a name has several versions, `config.strategy_version` is required. A name with a
  single version resolves to that version and the version is recorded.

### 2.2 Sizing and staging (pure `reviewed/sizing.py`, `staging.py`; the Nautilus host only forwards events)
1. At the decision close of session t: `E = settled + unsettled cash + Σ qty·close_t`. Target `q*_i = floor(w_i·E / close_t)`.
2. At the fill event (open of t+1, or close t for `same_close`), start of session: unsettled lots whose settle session ≤ now move
   to settled. **Sells first**: `held − q*` for every over-weight symbol, in symbol order. Proceeds go to `unsettled[s+k]`.
   **Then buys**, in symbol order: `q = min(q* − held, max q such that book(q·px) + book(fee) ≤ settled)`. Settled cash is debited on the trade date.
3. Any shortfall is retried at each later fill event until a new decision replaces it. Orders still pending after the last session are
   dropped with warning `orders_pending_at_end`. buy_and_hold decides once, at the first close.
4. The worker's independent ledger repeats steps 1–3 from the **engine-reported fills**. Engine cash must equal the ledger at
   cents, with no tolerance. Every per-fill commission must match. Positions must match. Any `OrderDenied` or `OrderRejected` raises a `process` error
   (loud), never a skipped trade.

### 2.3 Backend selection (T02)
- `run(..., backend: str | None = None)` is appended **last**. Add `BacktestConfig.backend: Literal["legacy","nautilus"] | None = None` and
  `BacktestConfig.strategy_version: str | None = None`. Precedence matches bd-q7u5: parameter, then config, then `DEFAULT_SETTINGS.default_backend="legacy"`.
  The source of the choice is recorded as `provenance.backend_source ∈ {param, config, default}`.
- `nautilus` together with engine `vector` ⇒ `BackendSelectionError`. An unknown backend ⇒ `BackendSelectionError`. Worker not configured, `describe`
  failure or a qualify mismatch ⇒ `BackendUnavailableError`. An unreviewed or plugin strategy, an unsupported settlement, timing or fee, or
  corporate actions in the window ⇒ `UnsupportedSemanticsError`. All of these are `BacktestError` subclasses. None of them calls `_engine_for`.
- `legacy` with a strategy that is *only* in the reviewed registry (`target_weight_rebalance`) ⇒ `UnsupportedSemanticsError`, because
  legacy has no whole-share/settlement capability. Legacy calls with today's registered names run exactly as before.
- `sweep`, `reconcile`, `validate` and `tearsheet` with `backend="nautilus"` (taken from `config.backend`) ⇒ `UnsupportedSemanticsError("P17")`.
  Folds and sweeps through Nautilus belong to HFP-P17. No new route is added (C-h).

### 2.4 Normalised result projection (one function per backend, both produce `BacktestResult`)
| Field | Unit / precision | Legacy | Nautilus projection |
|---|---|---|---|
| `equity_curve[].date` | tz-aware UTC session timestamp (00:00 UTC of the session date, as legacy `_as_utc`) | unchanged | session date from the worker `sessions`. Raw ns timestamps are never exposed |
| `.equity`, `.cash` | `Decimal`, 2 dp, HALF_EVEN | via float (unchanged) | exact Decimal (ledger), quantised HALF_EVEN. `cash` = settled + unsettled |
| `.exposure` | float, invested/equity | unchanged | same formula from the ledger |
| `trades[]` | `timestamp` = session, `side`, `quantity` = abs `Decimal` (whole), `price` = fill px at instrument precision, `commission` 2 dp, `slippage` 0 | unchanged | from engine fills (matched by the ledger) |
| `positions` | stripped by `sanitize_result` | unchanged | stripped (privacy boundary still applies) |
| `metrics` | `PerformanceMetrics` floats | unchanged | **same** `_metrics_from_returns` + `turnover` on the projected curve. No Nautilus analyzer |
| `engine_used` | str | `"vectorized"`/`"event"` | `"nautilus"` |
| `provenance` (new, optional, default `None`) | `RunProvenance` | `{backend, backend_source, engine, strategy_review}` | the above plus engine name/version, worker dist version, python/wheel tag, `fixed_precision`, `dataset_id`, `bars_sha256`, spec/code/params/execution hashes, assumptions, warnings, booking residual (exact − booked) |

### 2.5 Rounding and fixed-point policy (declared; no blanket tolerance)
- Quantities are whole shares (`lot_size=1`) and always floored. Prices keep the instrument precision ≤ the source decimals ≤ `FIXED_PRECISION`
  (admission from #1355).
- **Booking** (cash debits/credits and commission): exactly the engine's rule, `round_half_away(f64(qty)·f64(px)·100)/100`. The OpenBB
  ledger reproduces it as `Decimal(float(q)*float(p)*100.0).to_integral_value(ROUND_HALF_UP)`. The exact-Decimal residual is recorded.
- **Marks** (equity, cash in output): exact `Decimal` sum, then HALF_EVEN to cents. Metrics are floats from the marks. The only tolerance is
  1e-12 on metric floats. Cash, quantity, equity and commission must match exactly.

### 2.6 Independent hand-computed cash cases (literals in `tests/unit/nautilus/fixtures/cash_cases.json`, `"source":"hand-computed"`)
Zero fees and T+1 unless noted. Prices are given as open/close per session S1..Sn. Cash is in USD.
- **C1 buy-and-hold, next_open, gap-up.** AAA 100/100, 101/102, 103/101, 100/104. Cash 10,000. q* = floor(10000/100) = 100, but at the S2 open
  of 101 only floor(10000/101) = 99 are affordable: buy 99 @ 101.00 = 9,999.00, leaving cash 1.00. The shortfall gets 0 at S3 and S4. Equity = [10000.00, 10099.00, 10000.00, 10297.00].
  (Legacy would buy 99.0099 shares: a modelled difference, diagnostic only.)
- **C1′ same_close.** Same bars. Buy 100 @ 100.00 at S1, cash 0.00. Equity [10000, 10200, 10100, 10400]. Timing is bound to the run.
- **C2 rebalance 50/50, every 2 sessions, next_open, T+1.** AAA 100/100, 100/120, 120/120, 120/120, 120/120. BBB 50/50, 50/40, 40/40, 40/40, 44/44.
  At S1 close, q* = 50 AAA, 100 BBB. S2 open: buy 50 @ 100 and 100 @ 50, cash 0. At S3 close E = 10,000, q* = 41 AAA (41.67) and 125 BBB.
  S4 open: **sell 9 AAA @ 120 = 1,080 unsettled**; the BBB buy gets 0 shares (settled = 0). S5: 1,080 settles, then buy floor(1080/44) = 24 BBB @ 44 = 1,056, leaving cash 24.00.
  Equity [10000, 10000, 10000, 10000, 10400.00]. Final AAA 41, BBB 124. The S5 decision is dropped with `orders_pending_at_end`.
  Discriminators: with no settlement, 25 BBB are bought @ 40 at S4, giving cash 80.00 and S5 equity 10,500.00. With buy-before-sell, the engine rejects the order and the run fails loudly.
- **C2b C2 with T+2.** No BBB buy happens. Final cash 1,080.00, BBB 100, S5 equity 10,400.00 (cash and quantity discriminate).
- **C3a booking tie (exactly representable), precision 3.** DDD 20.000/20.000, 20.125/20.115. Cash 30.00, q* = 1. Book 20.125 → **20.13**
  (half-even would give 20.12), leaving cash 9.87. Mark S2 = 9.87 + 20.115 = 29.985 → **29.98** (HALF_EVEN; half-up would give 29.99).
- **C3b booking tie (not representable).** EEE 1.000/1.000, 1.005/1.005. Cash 1.50. Book 1 @ 1.005 → **1.00** (f64 gives 100.49999999999999; exact
  half-up would give 1.01), leaving cash 0.50, residual +0.005. Mark 1.505 → **1.50**.
- **C4 fee 10 bps.** FFF 100.00/100.00, 99.99/99.99. Cash 1,000. q* = 10, but 999.90 + 1.00 fee = 1,000.90 is more than 1,000, so q = 9:
  899.91 + fee 0.90 (0.89991 rounds to 0.90) leaves cash **99.19**, commission 0.90, S2 equity 999.10.
- **C6 staging order (planner only).** Settled 100, buys of 1 AAA @ 60 and 1 BBB @ 60: AAA fills, BBB gets 0 (symbol order).

## 3. Tasks

Common setup is as in #1355 §3 (`$py`, `$env:PYTHONPATH` with both the `backtest` and `nautilus_worker` directories).
`$U='openbb_platform/extensions/backtest/tests/unit/nautilus'`, `$W='openbb_platform/extensions/backtest/nautilus_worker/tests'`.
**A1** = "reviewed spec: code and parameter hashes bind timing, sizing and normalised output to the run".
**A2** = "an unsupported strategy, arbitrary plugin or settlement ⇒ the facade rejects it, with no silent legacy run".
Every load-bearing test gets a reverse-verification at authoring time (Testing Rule 7): mutate the production code and watch the test go red.

### T01: reviewed strategy metadata and loader allowlist with drift rejection (CODE-ONLY)
Files (new): `nautilus_worker/openbb_nautilus_worker/reviewed/{__init__,spec,params,hashing,registry,buy_and_hold,
target_weight_rebalance}.py`. Edit `admission.py` (RunRequest v2: `strategy_ref{id,version,code_sha256,spec_sha256}`, `params`,
`params_sha256`, `execution`; keep the `strategy="buy_and_hold"` alias). New facade module
`openbb_backtest/adapters/nautilus/strategies.py` (lookup plus CLI `verify|list`). Tests: `$W/test_reviewed_spec.py`, `$U/test_reviewed_loader.py`.
Red-first tests:
- A1: `test_pinned_code_hashes_match_sources`, `test_code_hash_lf_normalised` (a CRLF copy hashes the same),
  `test_params_hash_canonical` (key order, `1.0` vs `"1"` vs `Decimal("1.00")`), `test_spec_hash_changes_with_each_assumption`
  (mutating timing, sizing, settlement, booking or fees gives a new hash: mutation guard), `test_param_schema_hash_pinned`.
- A2: `test_one_byte_code_change_rejected_module_origin` (tmp copy of the package as root), `test_params_sha_mismatch_rejected_schema`,
  `test_out_of_bounds_params_rejected` (weight sum > 1, negative weight, 0 symbols), `test_unknown_id_or_version_rejected`,
  `test_dotted_path_colon_and_filesystem_ids_rejected`, `test_entry_points_never_consulted` (`importlib.metadata.entry_points`
  monkeypatched to raise; an EP named `buy_and_hold` cannot shadow the reviewed one), `test_unsupported_settlement_rejected`
  (T+0, T+3, `margin`, `borrowing=True`, `short=True`), `test_corporate_actions_in_window_rejected`.
Focused: `& $py -m pytest $W/test_reviewed_spec.py $U/test_reviewed_loader.py -q -m "not requires_nautilus"`
Real path (code-only): `& $py -m openbb_backtest.adapters.nautilus.strategies verify --format json` ⇒ exit 0, listing both ids,
versions and hashes. Run it again with `--root <tmp copy with one edited byte>` ⇒ exit 2 `strategy_code_drift`.

### T02: explicit backend selection and normalised projection behind the existing facade (CODE-ONLY; LIVE leg in T03)
Files: `models.py` (`backend`, `strategy_version`, `RunProvenance`, `BacktestResult.provenance=None`), `settings.py`
(`default_backend`), `errors.py` (3 errors), `router_helpers.py` (`resolve_backend`), `routers/run_router.py` (`backend` parameter;
`execute_run(config, *, engine, backend, strategy_params, feed)` extracted so the CLI shares the facade path), `routers/validate_router.py`
(reject nautilus), new `adapters/nautilus/{backend.py,projection.py}`, and regenerated story manifests if the `BacktestConfig` schema
hash is pinned (`scripts/build_story_manifests.py`; reviewed diff).
Red-first tests (`tests/unit/test_backend_selection.py`, `$U/test_projection.py`, plus caller contract tests):
- Contract: `test_run_signature_backward_compatible` (names, defaults and order of the first 4 parameters unchanged; `backend` last),
  `test_legacy_result_keys_superset` (old key set plus `provenance` only; equity and cash are `Decimal` with 2 dp),
  `test_default_backend_legacy_recorded_as_default`, `test_engine_precedence_unchanged` (existing bd-q7u5 tests stay green),
  `test_story_backtest_old_payload_still_validates` and `test_story_run_backtest_output_keys` (in `mcp_server/tests/story_adapters/test_jobs.py`,
  `importorskip`), and the existing C-e/C-f/C-h suites unchanged.
- A2: `test_nautilus_unavailable_never_calls_legacy` (spy `_engine_for` raises if called), `test_nautilus_with_vector_engine_rejected`,
  `test_nautilus_unreviewed_strategy_rejected` (`momentum_12_1`, `techtrade_confluence`), `test_legacy_rejects_reviewed_only_strategy`,
  `test_sweep_reconcile_validate_tearsheet_reject_nautilus`, `test_unknown_backend_rejected`, `test_worker_error_maps_to_typed_error`.
- A1: `test_projection_hand_case_c2` (canned worker body for C2 ⇒ exact curve, trades and cash), `test_projection_uses_shared_metrics`
  (equal to `_metrics_from_returns` on the same curve), `test_projection_rejects_inconsistent_body` (length mismatch or a cash disagreement ⇒ error,
  never an empty result: Rule 3), `test_nautilus_result_positions_sanitised`, `test_provenance_binds_all_hashes` (changing a param changes
  `params_sha256`; changing timing changes `execution_sha256`).
Focused: `& $py -m pytest openbb_platform/extensions/backtest/tests/unit/test_backend_selection.py $U/test_projection.py openbb_platform/extensions/backtest/tests/unit/test_run_router.py -q`
Callers: `& $py -m pytest openbb_platform/extensions/backtest/tests openbb_platform/extensions/techtrade/tests/unit/test_backtest_bridge.py openbb_platform/extensions/portfolio_intel/tests/unit/test_backtest_export.py openbb_platform/extensions/portfolio_intel/tests/unit/test_simple_fill.py openbb_platform/extensions/mcp_server/tests/app/test_analytics_profiles.py openbb_platform/extensions/mcp_server/tests/story_adapters/test_jobs.py -q`
Real path: the golden CLI in T03 (it goes through `execute_run`).

### T03: settlement-aware sell-before-buy staging and declared rounding vs independent cash cases (CODE-ONLY + LIVE)
Files: `reviewed/{sizing,staging,booking,host}.py` (`host.py` imports nautilus lazily: a `ReviewedStrategyHost(Strategy)` that subscribes
to bars and trade ticks and forwards events to the pure planner). Generalise `runs.py` (multi-asset `RunSpec`, open-print generation,
taker-fee instrument, ledger cross-check, order denied/rejected ⇒ `process`). Extend `tests/unit/nautilus/fixtures/fake_run_worker.py` with an
event-replay fake that fills each submitted order at the event price and books it with the declared rule. The fake has **no** settlement or staging,
so those can only come from the code under test. New: `fixtures/cash_cases.json`, `adapters/nautilus/golden.py` (CLI).
Red-first tests:
- `$W/test_staging.py` (pure, hand cases): C2 / C2b / C6 planner steps, `test_unsettled_proceeds_never_fund_buys`,
  `test_sells_precede_buys_in_one_event`, `test_shortfall_retried_then_superseded`, `test_pending_at_end_warning`.
- `$W/test_booking.py`: C3a (20.13 / 29.98), C3b (1.00 / 1.50 / residual 0.005), C4 (q = 9, 99.19, 0.90). Discriminating rules:
  half-even, exact half-up and the f64 rule each give a different literal.
- `$U/test_cash_cases_facade.py`: every case through `execute_run` + the real worker entrypoint + the fake engine ⇒ exact literals
  (A1 binding check included). `test_no_regen_path_for_cash_cases` (the file is read-only to code: no writer exists).
- `requires_nautilus` (worker venv only; seam contracts, Rule 4): `test_open_print_fills_at_open_price`, `test_money_rounding_rule_matches_declared`
  (C3a/C3b through the real `Money`/`notional_value`), `test_taker_fee_commission_matches_c4`, `test_cash_account_rejects_overspend_loudly`,
  `test_real_engine_reproduces_c1_c1p_c2_c2b_c3_c4`.
Focused: `& $py -m pytest $W/test_staging.py $W/test_booking.py $U/test_cash_cases_facade.py -q -m "not requires_nautilus"`
Real path, code-only: `& $py -m openbb_backtest.adapters.nautilus.golden --case all --runtime fake --format json` ⇒ exit 0, with each
case showing expected = got. `--case c2 --settlement T+0` ⇒ exit 2 `unsupported_settlement`.
Real path, LIVE (after #1355 T01-L; env `OPENBB_NAUTILUS_VENV`, `OPENBB_NAUTILUS_DATA_ROOT`): reinstall the worker package into the worker venv,
run `& "$env:OPENBB_NAUTILUS_VENV\Scripts\python.exe" -I -m pytest $W -m requires_nautilus -q`, then
`& $py -m openbb_backtest.adapters.nautilus.golden --case all --runtime native --format json` ⇒ exit 0, engine `1.231.0`, every literal
exact. Post the output (hashes and numbers only) on #1356. This is the issue's Verification ("buy-and-hold and multi-asset rebalance
through the actual facade and worker").
Optional LIVE diagnostic: `obb.backtest.run(config, backend="nautilus")` on real cached data is expected to fail closed with
`corporate_actions_present` or `double_adjustment` (#1385) until those are supported. Record that; do not work around it.

Classification: T01 **CODE-ONLY**. T02 **CODE-ONLY**. T03 planner, booking, fake and facade cases **CODE-ONLY**; real-engine reproduction **LIVE**.
D1–D5 below are **NEEDS-OWNER-DECISION** (recommended answers are given and implementation can proceed on them).

## 4. Ordering and PR batching
```
T01 (spec/allowlist/hashes) -> T03-pure (sizing/staging/booking, cash cases) -> T02 (backend, projection, execute_run, golden CLI)
#1355 T01-L (worker venv) -> T03-L (requires_nautilus seam tests + golden --runtime native) -> close #1356
```
| PR | Content | Gates |
|---|---|---|
| A `feat/hfp-strategy-standardization-gh-1356`, `Refs #1356` | All CODE-ONLY parts of T01–T03, one commit per Task. Split into A1 (worker side: T01 + T03-pure) and A2 (facade: T02) only if the diff exceeds about 1.5k lines | focused + caller suites, black/ruff, `/code-review`, `/security-review`, `local-privacy-review`, local CI (`test-unit-platform`, `general-linting`), code-only real paths |
| LIVE | T03-L evidence on #1356 by the owner/lead; update the issue's Command field with the two LIVE commands | close only after the real engine reproduces every literal |

## 5. Risks
1. Nautilus behaviour behind the open print (whether `trade_execution` and bar processing reset the book; whether the risk engine pre-checks notional differently)
   is unproven until LIVE. Any rejection is loud. If the open print is unsound, fall back to `same_close` only and decide again (D2).
2. The f64 booking rule differs from exact Decimal on non-representable ties (C3b). This is declared and recorded per fill, and never hidden by a tolerance.
3. Adding fields to `BacktestConfig`/`BacktestResult` changes the OpenAPI/MCP schemas and story manifest hashes. Regenerate and review them in PR A. Route count stays 10.
4. A reviewer could "fix" drift by bumping a pinned hash. The PR checklist requires a version bump plus review for any change to a reviewed file.
5. Legacy and Nautilus differ by design (fractional vs whole shares, no settlement, daily re-weighting in legacy buy_and_hold). Comparison is diagnostic
   only (gate 3, HFP-P17/P18).
6. Real data rarely has a window without dividends, so the reject-if-present rule makes real-data Nautilus runs fail closed until a later PBI.

## 6. Decisions needed (recommended answers)
| # | Question | Recommendation |
|---|---|---|
| D1 | Default backend in P16 | `legacy`, recorded as `backend_source=default`. Nautilus only when explicitly selected. The default flips at the P18 cutover (operator change). |
| D2 | Fill timings | Support `next_open` (default; matches the legacy event default `next_bar_open`) through a synthetic open print at `ts_event−1ns`, plus `same_close`. Do not change the #1355 dataset schema. |
| D3 | Settlement and cash model | `T+1` default and `T+2` allowed (pre-2024-05-28 history). `settled_cash_only` (no good-faith-violation exposure). Reject T+0, other values, margin, borrowing and shorting. |
| D4 | Rounding | Booking = the engine's own f64 half-away rule, replicated and with the residual recorded. Marks = exact Decimal HALF_EVEN cents. Exact match on cash, quantity, equity and commission; 1e-12 on metrics only. |
| D5 | Fees and corporate actions in P16 | Fees: `zero` and `taker_bps` (C4). Corporate actions in the window: reject; follow up in a later PBI. |
| D6 | Nautilus on sweep/validate/reconcile/tearsheet | Reject in P16; HFP-P17 routes them. |
| D7 | Strategies reviewed in P16 | `buy_and_hold@1.0.0`, `target_weight_rebalance@1.0.0`. Existing legacy strategies stay unreviewed (legacy only). |

## Lead decisions (2026-11-28, under the owner's delegation)

D1–D7 are accepted as recommended:
- D1: the default backend is `legacy` in P16, recorded as the default; it flips at the HFP-P18 cutover.
- D2: `next_open` is the default timing (synthetic open print), with `same_close` also supported.
- D3: settlement is T+1 by default, T+2 allowed. Buys use settled cash only. T+0, margin, borrowing and shorting are rejected.
- D4: booking uses the engine's float rule, with the residual recorded. Cash, quantity, equity and commission must match exactly.
- D5: zero fees and a basis-point taker fee are supported. Runs with corporate actions in the window are rejected until supported; see #1385 (FmpCachedReader ignores adjustment_type).
- D6: sweep, validate, reconcile and tearsheet reject `nautilus` in P16.
- D7: only `buy_and_hold@1.0.0` and `target_weight_rebalance@1.0.0` are reviewed strategies.

A drift failure is never fixed by bumping a pinned hash alone. It needs a version bump plus review.
