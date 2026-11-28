# Plan: independent validation and complete trial accounting (#1357, HFP-P17)

Status: **design draft, not committed.** Base `origin/portfolio` @ `f7ce26ccc` (#1355 via PR #1395, #1356 via PR #1397 merged).
Parent #1330 (HFP-F08). Requirement BT-03 (+ spec §9.1 reviewer item 3, plan.md §3.3 gate 4 and its "preserve all evaluated
configurations, fold returns and exclusions, with retries deduplicated by trial ID"). Dependency HFP-P16 (code merged; its LIVE
step T03-L and #1355 T01-L are still open, so every P17 LIVE step waits for them). No product code here. Synthetic data only.

## 0. Existing assets, callers and findings

| Asset (all under `openbb_platform/extensions/backtest/openbb_backtest/`) | Fact | Consequence |
|---|---|---|
| `validation/stats.py` `deflated_sharpe(sr, n_trials, skew, kurt, n_obs)`, `_expected_max_sharpe(N)`, `min_backtest_length` | DSR benchmark = E[max of N **unit-variance** normals]; no cross-trial Sharpe variance input. MinBTL is the `2·ln N / SR²` upper-bound approximation. | **F1.** The paper's DSR needs `V[SR_n]`; with per-observation SR (~0.06/day) and unit variance, any N>1 drives DSR to ~0. Add keyword `sr_variance: float = 1.0` (default keeps legacy bit-identical). |
| `validation/pbo.py` `pbo(matrix, n_groups=16)` | CSCV over `(T, N_configs)`; IS/OOS performance = **column sum**; IS-best = first `argmax`; rank = `#(oos < best) + 1`. | Correct primitive. Ties and the statistic are undeclared: pin them (T02). Paper's statistic is a performance ratio (e.g. Sharpe) per sub-matrix; add `statistic: Literal["sum","sharpe"]="sum"`. |
| `validation/cpcv.py` `cpcv(...)`, `n_backtest_paths` | One `Fold` per `C(N,k)` split; `path_id` is **never set**. Purge + embargo correct on indices. | Add pure `cpcv_paths(n_groups, k) -> list[list[(split, group)]]` (AFML ch.7 path reconstruction); `cpcv()` output unchanged. |
| `validation/splitters.py` `walk_forward`, `Fold` | Positional indices only; engine-agnostic. | Reused unchanged by the experiment planner. |
| `routers/validate_router.py::_run_folds` | Runs each fold's `test_idx` as `start=window[0], end=window[-1]`; `n_trials = len(folds)`; `skew=0, kurt=3` hard-coded; `_pbo_from_folds` stacks **folds as PBO columns**; PBO undefined ⇒ returns `0.0`. | **F2** CPCV test sets of non-adjacent groups are run as one contiguous span that includes train groups. **F3** N counts folds, not configurations. **F4** PBO columns must be configurations; folds-as-columns measures fold dispersion. **F5** undefined PBO = 0.0 is fail-open (helps "robust"). Legacy stays as is in P17 (callers C-e); the Nautilus path never inherits F2–F5; follow-up `type-bug` for legacy (decision D6). |
| `routers/run_router.py::sweep` → `engine/vectorized.py::sweep` | Cartesian grid, returns `[(params, metrics)]` + `select_best`; **no return series, no failed/excluded combos, no trial ids**; nothing feeds DSR. | The trial ledger (T01) is the missing link from sweep to DSR/PBO. |
| `router_helpers.py::reject_nautilus_until_p17` (used by `sweep`, `reconcile`, `validate`, `tearsheet`); test `tests/unit/test_backend_selection.py::test_sweep_reconcile_validate_tearsheet_reject_nautilus` | P16 D6. | P17 deletes the helper and replaces that test with routing tests. |
| `routers/run_router.py::execute_run` + `adapters/nautilus/{backend,export,client,projection}.py` | One run = export neutral dataset from the `Bundle` → `WorkerClient.run` → `BacktestResult` with `RunProvenance` (spec/code/params/execution/dataset/binding hashes). Worker holds `guards.HeavyJobLock` (one heavy job) and a deadline. | A trial cell = one `execute_run`-equivalent call. No new worker op; no worker protocol change (D2). |
| `models.py` `SweepResult`, `ValidationReport(pbo: float in [0,1])`, `FoldResult(path_id)`, `ReconciliationReport`, `RunProvenance` | No trial fields. | Additive optional fields only (§2.5). |
| techtrade `validation/backtest_bridge.py::validate_plan` → `validate_router.validate`; `tuning/tune_router.py` runs tuneta with `trials=100` then `validate_plan` | **F6** the tuneta search count never reaches DSR (N understated by ~100×). `tune_router.py:137-140,239-264` format `pbo`/`deflated_sharpe` with `:.2f`. | Contract tests stay green; `external_trials` (§2.3) is the hook; wiring tune into it is legacy behaviour change ⇒ D6. |
| Tests: `tests/unit/test_validation_{stats,pbo,cpcv,splitters,report}.py`, `test_validate_router.py`, `nautilus/test_cash_cases_facade.py`, fixtures `nautilus/fixtures/{fake_run_worker.py,synthetic_bundle/,cash_cases.json}`, `nautilus_worker/tests/fake_engine.py` | Existing stats tests are properties (monotonic, PSR=0.5 anchor, E[max] within 5 %), **no published reference values**; PBO tests use dominant/inverted/noise matrices. | T02 adds literal reference fixtures; T03 reuses the fake worker + synthetic bundle. |
| Callers C-a..C-h from `specs/gh-1356-hfp-strategy-standardization/plan.md` §0 | 10 routes; signatures pinned. | No new route. New parameters are appended last, optional. |

## 1. Design summary

```
sweep/validate(config.backend=="nautilus") -> ExperimentSpec (strategy ref, param grid, folds policy, base dataset, bounds)
  plan_cells(): every (config_id, window) cell, sorted; planned set persisted BEFORE dispatch
  dispatch(): sequential cells over WorkerClient spawns (one heavy job); retry policy per error class; attempts appended to ledger
  assemble(): ledger -> TrialLedger (dedup by trial_id) -> FoldReturnMatrix (long, canonical, sha256) -> wide views
  statistics: DSR(N = distinct attempted config_ids + external_trials, V = cross-config SR variance, sample moments),
              PBO(configs as columns), CPCV paths, MinBTL -> report + ExperimentSummary(provenance, exclusions)
legacy backend: unchanged code path and numbers (summary field None)
```

## 2. Design details

### 2.1 Identity and lineage (pure `validation/trials.py`; canonical JSON = sorted keys, no whitespace, Decimal-as-string)
- `config_id = sha256(canon{"v":"trial-config/1", backend, strategy_id, strategy_version, spec_sha256, code_sha256,
  param_schema_sha256, params_sha256, execution_sha256, base_dataset_id, engine_version, worker_version, fixed_precision})`.
  `params_sha256` comes from P16 normalisation, so `1.0`, `"1"`, `Decimal("1.00")` are **one** config (not an inflated N).
  `base_dataset_id` = neutral export of the full experiment range from the same `Bundle`: changed data ⇒ new config_id.
- `window = {policy, method, fold_params_sha256, ordinal, start_session, end_session, session_count, sessions_sha256}`.
- `trial_id = sha256(canon{"v":"trial/1", config_id, window})`; `attempt_id = sha256(trial_id, attempt_no, spawn_nonce_sha256)`.
- `experiment_id = sha256(canon(ExperimentSpec))`; the planned cell list (trial ids) is written first, so completeness is checkable.
- `AttemptRecord{attempt_id, trial_id, attempt_no, status: ok|failed|excluded, error_code (protocol.ErrorCode / FailedLayer),
  reason, result_sha256, window_dataset_id, binding_sha256, started_at, ended_at}`. Nothing is ever deleted or overwritten.

### 2.2 Normalized fold-return matrix (`validation/matrix.py`)
- **Long canonical form** (the stored artifact): rows `(config_id, window_ordinal, session_date, ret)` sorted by
  `(config_id, session_date)`. `ret = E_t/E_{t-1} − 1` computed in the facade from the projected Decimal cent equity curve
  (worker never computes returns), as float64; hashed via `float.hex()` ⇒ `matrix_sha256` is exact and platform-stable.
  First session of each window has no prior mark ⇒ no row (declared).
- **Wide view** for PBO/DSR: rows = OOS sessions ascending, columns = config_ids **sorted lexicographically** (so the
  `argmax` first-index tie rule is independent of completion order and worker split).
- Stored as `<runs_root>/experiments/<experiment_id>/{spec.json, planned.json, ledger.jsonl, matrix.jsonl, summary.json}`
  (`runs_root = settings` sibling of `bundle_root`, already ignored by `/.openbb_backtest/`). Atomic append with fsync per
  record; `safe_join` for paths. Content = hashes, returns, error codes; no positions, no account values (privacy boundary).

### 2.3 Deduplication and N (the "never understate" rules, each a red test)
1. Dedup key is `trial_id`. Many attempts ⇒ one cell. Terminal state: `ok` if any attempt is `ok`; two `ok` attempts with
   different `result_sha256` ⇒ cell `conflict` ⇒ experiment `failed_closed` (nondeterminism is never averaged away).
2. `N_dsr = |{config_id : any attempt recorded, any status}| + external_trials`. Failed and excluded configs **count** (they
   were searched); retries never add (same config_id); changed data adds (new config_id). `N_effective` (correlation-clustered)
   may be reported as a diagnostic only, never used to lower the penalty.
3. Matrix columns: configs whose every planned window is `ok`. Others are listed in `exclusions[{config_id, reason}]` with
   reason ∈ {`worker_failed`, `admission_rejected`, `unsupported_semantics`, `incomplete_windows`, `zero_variance`,
   `insufficient_sessions`, `conflict`}. Any exclusion ⇒ `matrix_complete=false` ⇒ verdict capped at `fragile` (D3).
4. Mixed `base_dataset_id` inside one experiment ⇒ no matrix (`mixed_dataset`), ledger still kept and counted.
5. Retry policy: retry only `process`/`timeout`/spawn failures, `max_attempts=2` (settings). Deterministic codes (`schema`,
   `admission`, `module_origin`, `egress`, unsupported semantics) are terminal on first attempt.
6. Resume: re-running the same `experiment_id` reads the ledger, skips cells with terminal `ok`, continues attempt numbers.
7. Monotonicity property: for every permutation/partition of a fixed record set, N and `matrix_sha256` are identical, and
   N never decreases as records are appended.

### 2.4 Worker split and reassembly
- Cells are dispatched sequentially through `WorkerClient` (#1355: one heavy job, `HeavyJobLock`, per-run deadline, idle
  unload). "Split across workers" = several spawns (crash, deadline kill, idle exit, resume in a new process). A spawn
  carries no experiment state; the ledger is the only state. Order of completion never affects assembly (sorted keys).
- Bounds (settings, checked at plan time before any spawn): `max_configs=64`, `max_cells=512`, `max_attempts=2`,
  experiment wall budget; exceeding ⇒ `UnsupportedSemanticsError("experiment_too_large")`, never truncation.
- Window policy (D1): `continuous` (default) = one cell per config over the full range, folds are index views; `per_fold` =
  one cell per atomic window (WFO test window, or each CPCV group — never a non-contiguous span; fixes F2), fresh starting
  cash per cell, one per-window export from the same `Bundle`. CPCV dedupes to `configs × n_groups` cells, not `× C(N,k)`.

### 2.5 Routing (lift P16 D6; legacy stays default)
- Delete `reject_nautilus_until_p17`. `resolve_backend(param > config.backend > default "legacy")` as P16.
- `sweep(config, param_grid, rank_by, provider)`: nautilus ⇒ each combo validated by the reviewed `param_model`
  (invalid combo ⇒ `excluded/admission_rejected`, still counted), experiment with `continuous`, `SweepResult.results` =
  ok configs; `best` by the same `select_best`; new optional `SweepResult.experiment: ExperimentSummary | None`.
- `validate(..., param_grid=None, external_trials=0)` (appended last): nautilus + `param_grid` ⇒ selection-aware:
  PBO over configs, DSR of the selected best with `N_dsr`, `V = var(per-config per-obs SR, ddof=1)`, sample skew and
  non-excess kurtosis of the selected OOS series. Without grid ⇒ N = 1 + external_trials; PBO undefined (D3).
  `FoldResult.path_id` filled from `cpcv_paths`. `ValidationReport.experiment` optional.
- `tearsheet`: nautilus ⇒ `execute_run` (P16) then the same `build_tearsheet`; `engine` conflict rules from P16.
- `reconcile`: nautilus ⇒ reference = nautilus, candidate = legacy `event` on matching assumptions, `diagnostic_only=true`,
  `modeled_differences: list[str]` (from §T03 doc ids); `strict=True` with nautilus ⇒ rejected (agreement is not a gate).
- Legacy calls: identical numbers (golden + existing suites), `experiment=None`.

## 3. Tasks

Setup as `specs/gh-1355-hfp-nautilus-runtime/plan.md` §3 (`$py` = `.venv_portfolio`, `$env:PYTHONPATH` with `backtest` and
`nautilus_worker`). `$B='openbb_platform/extensions/backtest/tests/unit'`, `$U="$B/nautilus"`, `$V="$B/validation"` (new).
**A1** = "sweeps and folds split across workers: retained trial IDs, return matrices and exclusions reproduce qualified
DSR/PBO/CPCV results". **A2** = "retries of failed trials or changed data: dedup and provenance prevent understated penalties".
Every load-bearing test gets reverse verification (Testing Rule 7: mutate production code, see it go red).

### T01 — normalize fold returns and trial lineage, retain all configurations and exclusions (CODE-ONLY)
Files (new): `validation/{trials,matrix,experiment}.py`, `adapters/nautilus/experiment.py` (cell executor over
`execute_run` internals; reuses one export per window), `validation/__init__.py` exports. Edit: `models.py`
(`ExperimentSummary{experiment_id, n_planned, n_ok, n_failed, n_excluded, n_trials_dsr, external_trials, matrix_sha256,
matrix_complete, exclusions, window_policy}`; `SweepResult.experiment`, `ValidationReport.experiment`,
`ReconciliationReport.{diagnostic_only, modeled_differences}` — all optional), `settings.py` (bounds), `router_helpers.py`,
`routers/run_router.py` (sweep, reconcile), `routers/validate_router.py` (validate, tearsheet), story manifests if the schema
hash is pinned (`scripts/build_story_manifests.py`, reviewed diff).
Red-first tests:
- A1 `$V/test_trials.py`: `test_config_id_ignores_window_trial_id_binds_it`, `test_equivalent_params_one_config`
  (`1.0`/`"1"`/`Decimal("1.00")`), `test_each_binding_field_changes_config_id` (mutation guard over every field).
- A1 `$V/test_matrix.py`: `test_long_form_canonical_and_hash_float_hex`, `test_wide_columns_sorted_by_config_id`,
  `test_returns_from_decimal_curve` (hand curve ⇒ literal returns), `test_empty_matrix_from_nonempty_ledger_raises` (Rule 3).
- A1 `$V/test_experiment_split.py`: golden ledger of 3 configs × 4 WFO windows dispatched (a) in one spawn, (b) across 3
  fake-worker spawns in shuffled order, (c) crash after cell 5 + resume ⇒ identical `matrix_sha256`, N, exclusions.
- A2 `$V/test_trial_accounting.py`: `test_retry_after_process_failure_counts_once` (attempts=2, N unchanged),
  `test_deterministic_rejection_not_retried`, `test_failed_and_excluded_configs_count_in_n`, `test_changed_dataset_is_new_trial`
  (N+1, `mixed_dataset`, no matrix), `test_conflicting_ok_attempts_fail_closed`, `test_n_monotone_under_permutations`
  (all permutations of a 6-record set), `test_external_trials_added`, `test_exclusion_caps_verdict_at_fragile`,
  `test_bounds_reject_before_spawn` (spawn spy not called).
- Routing `$B/test_backend_selection.py` (replace the P16 rejection test): `test_sweep_routes_nautilus_never_calls_legacy`,
  `test_validate_nautilus_uses_configs_as_pbo_columns` (reverse-verify against folds-as-columns),
  `test_validate_nautilus_cpcv_runs_atomic_groups` (no span contains a train group; F2),
  `test_validate_nautilus_n_is_configs_not_folds` (F3), `test_tearsheet_nautilus_uses_execute_run`,
  `test_reconcile_nautilus_is_diagnostic_and_strict_rejected`, `test_legacy_numbers_unchanged` (existing goldens).
- `$U/test_experiment_facade.py`: the real worker entrypoint via `fixtures/fake_run_worker.py` + `synthetic_bundle`, 2 reviewed
  strategies × 3 configs ⇒ ledger, matrix and summary equal committed literals; a `--fail-once <trial_id>` flag added to the
  fake drives the retry path through the real client.
Focused: `& $py -m pytest $V $U/test_experiment_facade.py $B/test_backend_selection.py $B/test_validate_router.py $B/test_run_router.py -q -m "not requires_nautilus"`
Callers: the P16 caller command (backtest tests + techtrade `test_backtest_bridge.py`, `test_tune_router.py` + portfolio_intel
`test_backtest_export.py`, `test_simple_fill.py` + mcp_server `test_analytics_profiles.py`, `story_adapters/test_jobs.py`).
Real path, code-only (replaces "Not yet qualified"):
`& $py -m openbb_backtest.validation.experiment run --spec $V/fixtures/experiment_small.json --runtime fake --format json` ⇒ exit 0,
prints `experiment_id`, N, `matrix_sha256` equal to the fixture; rerun ⇒ resume, zero new attempts.

### T02 — qualify statistical bridges against independent matrices (CODE-ONLY)
Files: `validation/stats.py` (`sr_variance` keyword; public `expected_max_sharpe`; optional exact MinBTL
`min_backtest_length_exact` beside the approximation), `validation/pbo.py` (`statistic`, declared tie rules, optional
`pbo_detail()` returning per-partition `(is_best, rank, logit)`), `validation/cpcv.py` (`cpcv_paths`), new
`$V/fixtures/independent_references.json` (`"source"` per case: `hand-computed` or a paper citation with section/page;
**no regeneration path**, no call to any engine). Tolerances are declared per case: `exact` (rational/enumerated) or
`half-ulp-of-published-digits` for paper values; nothing blanket.
Red-first tests (`$V/test_independent_references.py`):
- DSR: Bailey & López de Prado (2014) numerical example (N=100, `V[SR]`=1/2 annualised, T=1250 daily, skew −3, kurt 10,
  annual SR 2.5; published SR0 ≈ 0.1132 per-obs, DSR ≈ 0.9004 — implementer transcribes exact inputs/outputs and the
  annualisation factor from the paper text before pinning). `test_dsr_unit_variance_default_unchanged` (legacy bit-identical).
- PSR: inputs solved so z equals a tabulated normal quantile (e.g. 1.959964 ⇒ 0.975) to 1e-12.
- E[max]: literal values of the formula at N=2, 10, 100 hand-derived from `Φ⁻¹` table values; true E[max of 2] = 1/√π kept as a
  documented approximation-error bound, not an equality.
- MinBTL: approximation ≥ exact form for all N≥2; paper example (N≈45 trials, SR=1 ⇒ ≈5 years for the exact form), transcribed.
- PBO: 3 hand matrices (T=4, S=4 ⇒ 6 partitions enumerated in the fixture with IS-best, OOS rank and logit per partition):
  literal PBO 0, 1/2, 1; a tie matrix pinning the first-index IS rule and the `#(oos<best)+1` OOS rank; `statistic="sharpe"` case
  where sum and Sharpe disagree (discriminating, Rule 7).
- CPCV: `(N=4,k=2)` split order, `cpcv_paths` table (3 paths × 4 groups), purge/embargo literal index sets for T=12,
  `label_span=1`, `embargo=1/12`; `n_backtest_paths(6,2)=5` stays.
- Composition: `test_validate_statistics_from_matrix_literal` — a hand 3-config × 12-session matrix through the T01 assembler
  and the validate statistics bridge ⇒ literal N, V, DSR, PBO (no engine, no worker).
Focused: `& $py -m pytest $V/test_independent_references.py $B/test_validation_stats.py $B/test_validation_pbo.py $B/test_validation_cpcv.py -q`
Real path, code-only: `& $py -m openbb_backtest.validation.experiment qualify-stats --format json` ⇒ exit 0, each case
`expected/got/tolerance/source`; a mutated fixture copy (`--references <tmp>`) ⇒ exit 2 naming the case.

### T03 — bounded realistic benchmark jobs + modeling-differences document (CODE-ONLY + LIVE)
Files: `validation/experiment.py` subcommand `bench`; `$V/fixtures/bench_spec.json` (2 reviewed strategies, 3×3 grid, 2 symbols,
756 synthetic sessions from a seeded generator in the existing `synthetic_bundle` shape, WFO 4 folds and CPCV(6,2) in both window
policies); new doc `docs/designs/backtest-design/14-nautilus-modeling-differences.md`.
Red-first tests (`$V/test_bench.py`, fake worker; no network, no DB, no wall-clock asserts — `benchmark_sweep` precedent):
`test_bench_counts_cells_attempts_and_n` (literal planned/ok/failed/N), `test_bench_peak_concurrency_one` (HeavyJobLock observed),
`test_bench_injected_kill_known_n` (kill at cell k ⇒ resume ⇒ N and matrix unchanged), `test_bench_rejects_over_bounds`,
`test_modeling_differences_doc_lists_every_reconcile_difference_id` (doc ↔ `modeled_differences` ids stay in sync).
Doc content (each item: legacy behaviour, Nautilus behaviour, effect, evidence case): fractional vs whole shares (C1),
no settlement vs T+1/T+2 (C2/C2b), buy-before-sell vs sell-first, fill timing, f64 booking vs Decimal marks (C3a/C3b), fees (C4),
per-fold fresh cash and window policy, F1–F5 statistic differences, MinBTL approximation, corporate-action rejection (#1385),
metrics from shared `_metrics_from_returns` (no Nautilus analyzers). States that agreement is diagnostic, never a gate.
Focused: `& $py -m pytest $V/test_bench.py -q -m "not requires_nautilus"`
Real path, code-only: `& $py -m openbb_backtest.validation.experiment bench --spec $V/fixtures/bench_spec.json --runtime fake --format json`
⇒ exit 0 with cells, attempts, N, `matrix_sha256`, elapsed (reported, not asserted).
Real path, **LIVE** (after #1355 T01-L and #1356 T03-L; `OPENBB_NAUTILUS_VENV`, `OPENBB_NAUTILUS_DATA_ROOT`): same command with
`--runtime native` ⇒ exit 0, engine `1.231.0`, the same N/exclusions as fake, matrix hash recorded (may differ from fake only
where the doc declares it); then `--runtime native --inject-kill 5` ⇒ identical N. Post hashes and counts only on #1357.
Optional LIVE diagnostic on real cached data is expected to fail closed (`corporate_actions_present`, #1385); record, don't bypass.

Classification: T01 **CODE-ONLY**; T02 **CODE-ONLY**; T03 fake bench + doc **CODE-ONLY**, native bench **LIVE**.
D1–D6 **NEEDS-OWNER-DECISION** (recommendations below; implementation can proceed on them).

## 4. Ordering and PR batching
```
T02 (pure stats + independent fixtures; no routing)  ->  T01 (ledger, matrix, experiment, routing)  ->  T03 (bench, doc)
#1355 T01-L + #1356 T03-L  ->  T03-L native bench  ->  close #1357
```
| PR | Content | Gates |
|---|---|---|
| A `feat/hfp-validation-trials-gh-1357`, `Refs #1357` | T02 + T01 + T03 code-only, one commit per Task (split T02 into its own PR only if the diff exceeds ~1.5k lines) | focused + caller suites, black/ruff, `/code-review`, `/security-review`, `local-privacy-review` (ledger contents), local CI (`test-unit-platform`, `general-linting`), the three code-only real paths |
| LIVE | T03-L evidence on #1357; update the issue's Command field with the T01/T02/T03 commands above | close only after native bench matches declared counts |

## 5. Risks
1. Paper reference values must be transcribed from the papers, not recalled; a wrong literal would "qualify" a wrong formula.
   Mitigation: fixture stores section/page and every intermediate (SR0, z); reviewer re-derives one case by hand.
2. Changing `ValidationReport.pbo` type (D3) touches techtrade formatters (`tune_router.py:137-140`, `examples/validate_a_plan.py`).
3. Legacy statistics (F1–F6) stay wrong until P18 unless D6 is taken; reports keep their old meaning, now documented.
4. Sequential single-heavy-job dispatch makes CPCV sweeps slow (`configs × groups` runs); bounds fail closed rather than truncate.
5. Continuous policy means WFO/CPCV on non-fitted reviewed strategies only re-slices one path; CPCV adds information only when a
   selection/fit happens on train groups (selection-aware validate with `param_grid`). Documented, not hidden.
6. Schema additions change OpenAPI/MCP schemas and story-manifest hashes; regenerate and review in PR A; route count stays 10.

## 6. Decisions needed (recommended answers)
| # | Question | Recommendation |
|---|---|---|
| D1 | Window policy default | `continuous` for sweeps and validate; `per_fold` available (atomic windows, fresh cash), recorded in the trial key. |
| D2 | Fold windows: worker protocol change vs per-window export | Per-window export from the same `Bundle`; config binds `base_dataset_id`. No worker change, no worker reinstall for P17. |
| D3 | Undefined PBO and incomplete matrices | `ValidationReport.pbo: float | None` (None = undefined, never 0.0) on the Nautilus path; verdict capped at `fragile` when PBO is None or `matrix_complete=false`; update the techtrade formatters. Legacy keeps its float. |
| D4 | What N counts | Distinct attempted config_ids incl. failed/excluded, + declared `external_trials`; retries never add; data change adds. Effective-N diagnostic only. |
| D5 | Cross-trial variance and moments | `V` = sample variance (ddof=1) of per-config per-observation SR over ok configs; sample skew and non-excess kurtosis; N=1 ⇒ benchmark 0. Legacy default `sr_variance=1.0`. |
| D6 | Legacy F1–F6 (folds-as-columns PBO, N=folds, CPCV span, tuneta N) | Leave legacy numbers unchanged in P17; file one `type-bug` for the legacy validate statistics and fix at the P18 cutover (tune passes `external_trials=trials` then). |

## Lead decisions (2026-11-28, under the owner's delegation)

- D1–D5 are accepted as recommended. In particular, D3: on the Nautilus path an undefined PBO is `None`, never 0.0, and the verdict is capped at "fragile".
- **D6:** legacy numbers stay unchanged in P17. The legacy findings F1–F6 are recorded in this plan as the follow-up list for the P18 cutover. The lead has already created 3 issues this session (the D6 limit), so the `type-bug` issue for F1–F6 is filed only after owner confirmation.
- **Reference values:** do NOT pin paper numbers recalled from memory. Use a value only if it is verified against the paper's public text (a read-only fetch is fine) and cited with page or section. Otherwise compute the expected value independently from the closed-form definition with its stated inputs, and show the derivation in the fixture. Never derive it from the code under test.
- **Ordering:** T02, then T01, then T03, in one PR.
