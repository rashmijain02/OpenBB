# Plan: market readiness and independent operational audits (#1345, HFP-P08)

Status: **design draft, not committed.** Branch `feat/hfp-market-readiness-gh-1345` off
`origin/portfolio` @ `5d931ae64` (includes #1338 `openbb_agents.hermes_integration` and #1344 / PR
#1391 `portfolio_utils/fmp_sync/`). Parent #1326 (HFP-F04), program:openbb-jobs. Requirements
OPS-02, OPS-04, OPS-07. Sources: workspace G1 draft `prompts\out\fmp-cache-hermes-sync-design.md`
§6, §8, §9, §10 (SHA in issue body); `docs/Specs/gh-1312-hermes-financial-planning/plan.md` §9, §12;
`.../github-plan/plan.md` HFP-P08; `specs/gh-1344-hfp-price-warming-cron/plan.md` (§0, §1.4, §6).
Dependency HFP-P07 (#1344): code merged, LIVE acceptance pending; OPS-ATTEST and FMP-QUOTA not granted.
Every CODE-ONLY step runs against synthetic calendars, SQLite files and fake cursors; nothing
connects to `openbb_fmp_cache_test` (live store) or `openbb_fmp_cache` (old copy). Nothing deletes data.

## 0. Existing assets (observed, metadata only)

| Asset (repo-relative) | Fact | Consequence |
|---|---|---|
| `openbb_platform/tools/portfolio_utils/portfolio_utils/fetch_position_history.py` `check_portfolio_app_readiness(symbols, database)` | Unconditional `COUNT(*)` on `Portfolio_Positions`, `Account_Owner`, `ESPP_Plan` (mixed case); `MAX(date)` per symbol with no `interval_type`/`adjustment_type`/`is_valid`/`is_filled` filter; target from `_previous_trading_day` (weekday only, no holidays, host-local `datetime.now()`); returns `{target_date, table_counts, missing_price_symbols, stale_price_symbols}`. | Extend, keep old keys (design §6 "extend existing function"); the private counts and naive target are the T01 fixes. |
| same, `run_position_history_warm` / `_run_position_history_warm_locked` | Readiness skipped in dry run (`{} if dry_run`); `readiness_fn` seam. `PositionHistoryWarmResult.to_summary()` projects readiness keys. | Dry-run evaluation is new and must not open the warm path. |
| same, `ensure_market_holidays` + `populate_market_holidays.compute_us_holidays` | Non-deleting upsert, swallows errors. `_observed` maps a **Saturday Jan 1 to Friday Dec 31** (2022 -> 2021-12-31, 2028 -> 2027-12-31). NYSE does not close then. No half-days. | Real calendar bug: the D2 upsert through `current_year+1` would write 2027-12-31 as a holiday during 2027. Fix the generator (T01); existing wrong rows are reported, never deleted. |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_historical.py` `_get_basic_market_holidays` | DB rows for a year range else computed fallback with the **same `_observed` bug**; any non-empty result is accepted even if a year is missing. | Provider scope (#1298-#1301 owner): dependency, not edited here. |
| `.../openbb_fmp_cached/utils/cache_schema.py` `equity_historical` | `interval_type`/`adjustment_type` nullable with defaults; UNIQUE (symbol, date, interval_type, adjustment_type) does not stop duplicates when either is NULL; `is_filled`, `is_valid`, `cached_at TIMESTAMP`. | NULL partitions are their own finding; duplicate check must use `<=>`-safe grouping. Schema fixes are storage-owner scope. |
| same, `equity_profile` (`market_cap`, `price`, `currency`); `shares_float_all` / directories (JSON-blob `data_json`); `models/analyst_estimates.py` | Heterogeneous shapes; no stable typed share-count columns. | Fundamentals diagnostics are pure functions over normalized inputs; table adapters only where columns are typed, others `NOT_EVALUATED`. |
| `market_holidays` DDL | Not in the repo (created out of band); provider reads a `year` column. | Disposable fixture DDL is ours; LIVE step records `SHOW CREATE TABLE` shape only. |
| `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/semantics.py` `last_completed_session`, `snapshot_staleness`; `extensions/backtest/openbb_backtest/data/calendars.py`; `extensions/fmp_trading/.../core/flat_by_close.py` `_cutoffs_for_session` | `exchange_calendars` XNYS (4.13.2 in `.venv_portfolio`, declared by techtrade) with actual `session_close` incl. half-days. | Reuse the library and pattern; do not import techtrade (extension coupling). |
| `portfolio_utils/fmp_sync/` (#1344): `outcome.FmpSyncOutcome` (`data_status="UNVALIDATED"`, findings, exit codes), `dispatcher._warm` (`READINESS_UNAVAILABLE` wrapper), `budget.BudgetLedger` (`reserve`, `set_defer`, `defer.json`), `TransportGuard`, `CancelController`, `state.record_start/record_end/fingerprint/atomic_write_json/read_history`, `locking.target_lock`, `admission.admit`, `render`, `templates/fmp_cache_prices.py.tmpl` (`WRAPPER_VERSION`, `_DATA_STATUS = {"UNVALIDATED"}`, `op == "prices"`) | Budget, deferral, receipts, lock and wrapper contract exist. | Reuse; the wrapper must learn new `data_status` values (template version bump, render drift path). |
| Tests: `tests/fmp_sync/conftest.py` (autouse safety: blocks `pymysql.connect`, non-loopback sockets, protected DB names), `test_dispatcher.py::test_readiness_exception_becomes_finding`, `test_dry_run_no_holiday_no_sockets_no_budget`, `test_budget.py`, `test_state.py`, `test_wrapper.py` | Hermetic harness. | All new tests live under `tests/fmp_sync/` and inherit it. |
| Backup/binlog/disk | No code. Runbook `docs/operations/portfolio-intelligence-cache-runbook.md`; `rules/DEVELOPMENT_RULES.md` "Backups" (dir outside the repo). | New metadata-only observer; paths come from the private map, never the repo. |
| `scripts/local_ci.py` | Absent on this base. | OM8 fallback applies for the PR. |

## 1. Design

All new code lives in `portfolio_utils/fmp_sync/` (D9 of #1344). Shared vocabulary
`fmp_sync/checks.py`: `CheckState` = `OK | WARN | CRITICAL | BLOCKED | UNKNOWN | UNAVAILABLE |
NOT_APPLICABLE | NOT_EVALUATED`; `CheckResult(check_id, state, reason_code, scope, observed_utc,
counts)` (pydantic, `extra="forbid"`, frozen; codes only, no row content). Aggregate
`data_status` = worst of required checks, where `UNKNOWN`/`UNAVAILABLE` on a required check can
never yield `OK` ("no fabricated health"): `VALIDATED | WARN | CRITICAL | UNKNOWN | BLOCKED |
UNVALIDATED` (last = not evaluated, e.g. dry run without DB).

### 1.1 Lifecycle-aware market sessions (`fmp_sync/sessions.py`)
- Primary authority: `exchange_calendars` XNYS built with explicit `start`/`end` covering
  `current_year+1` (the library's default end is ~1 year from import day; never rely on it). Pin by
  declaring `exchange-calendars = "^4.13.2"` in `portfolio_utils/pyproject.toml`; record the
  installed version in receipts. Injected `CalendarSource` protocol so tests use synthetic calendars.
- `target_session(now: aware datetime, grace=2h)` -> last session whose **actual** close (16:00 or
  13:00 ET half-day) + grace <= now in America/New_York. Naive `now` raises. Cron fires 15:30 PT =
  18:30 ET on both sides of DST (same switch dates); full day 18:00 <= 18:30 -> today; half day
  15:00 -> today; Thanksgiving -> previous session.
- `expected_sessions(start, end, lifecycle_start=None)`: expected start = first session on/after
  max(requested, verified lifecycle start); unknown lifecycle -> `UNKNOWN` coverage, never an assumed IPO.
- Coverage guard: requested range beyond the calendar's end, or a year missing from
  `market_holidays` -> `BLOCKED` (`CALENDAR_COVERAGE_MISSING`); `current_year+1` missing before
  Dec 1 -> `WARN` (`NEXT_YEAR_CALENDAR_MISSING`), from Dec 1 -> `BLOCKED` for execute.
- Cross-check `market_holidays` vs XNYS full-day closures for the window: extra table dates
  (e.g. 2021-12-31) or missing ones -> `WARN CALENDAR_DISAGREEMENT` with counts; half-days are
  never expected in the table. The generator fix: `compute_us_holidays` skips New Year when Jan 1 is
  a Saturday (NYSE rule 7.2); no existing row is removed.

### 1.2 Readiness v2 (extends `check_portfolio_app_readiness`; `fmp_sync/readiness.py`)
- Keep the public function and its four keys; add `checks` (list of `CheckResult` dumps),
  `data_status`, `calendar` (version, target session, grace). Old callers/printing unchanged. The
  body delegates to `readiness.evaluate(cursor_factory, symbols, now, policy)`; the naive
  `_previous_trading_day` is replaced by `sessions.target_session`.
- Read-only by construction: connection opened with `autocommit=False`, then
  `SET SESSION TRANSACTION READ ONLY`, `SET SESSION MAX_EXECUTION_TIME=<ms>` (MySQL 8 SELECT cap),
  `START TRANSACTION READ ONLY`, rollback at end. Every statement comes from a versioned allowlist
  `QUERIES: dict[id, sql]` (identifiers fixed, values bound); runner rejects any id not in it.
  Price query filters `interval_type <=> %s AND adjustment_type <=> %s AND is_valid AND
  NOT COALESCE(is_filled,0)` (synthetic fills never satisfy freshness).
- Freshness/coverage per symbol: 0 missed sessions OK, 1 WARN, 2+ CRITICAL; no history CRITICAL
  unless lifecycle evidence says later start; exclusions (CUSIP, `SKIP_SYMBOLS`, manifest
  skips) counted separately as `NOT_APPLICABLE`, never as fetched success.
- **Table-case check:** resolve required tables through `information_schema.TABLES WHERE
  TABLE_SCHEMA = DATABASE()` with exact and case-folded names; `TABLE_CASE_MISMATCH` (WARN) when only
  a case-folded match exists and `@@lower_case_table_names` is 0; missing -> `TABLE_MISSING`.
- **Optional private counts:** off unless the private map sets `readiness.private_counts: true`.
  When on, `COUNT(*)` only, per allowlisted table; MySQL 1142/1143/1044 (grant missing) ->
  `UNAVAILABLE GRANT_MISSING`; 1146 -> `TABLE_MISSING`; table hidden from information_schema ->
  `UNAVAILABLE NOT_VISIBLE`. A private check is informational: it never blocks warming and never
  turns `UNAVAILABLE` into a zero. Counts stay in the local `runs/<run_id>.json`; the stdout line and
  `status.json` carry states only.
- **Dry-run evaluation:** `audit --dry-run` evaluates calendar/session checks with zero sockets
  and lists DB checks as `NOT_EVALUATED DRY_RUN_NO_DB` (`data_status=UNVALIDATED`);
  `audit --read-only` runs the allowlisted SELECTs under admission (#1344 `admit`, target class,
  `SELECT DATABASE()` match) and the target lock is **not** taken (pure reads), but a `read_only`
  receipt is written. `prices --dry-run` keeps zero sockets (existing test stays green).
- Ambiguous timestamps: each dataset declares `timestamp_semantics` (`DATE_ET_SESSION`,
  `DATETIME_UTC`, `DATETIME_HOST_LOCAL`) in an in-repo `fmp_sync/datasets.py`; undeclared, or a
  host-local value in a DST fold/gap (`zoneinfo` fold 0 vs 1 differ) -> `UNKNOWN AMBIGUOUS_TIMESTAMP`.
- Dispatcher: replace the bare `READINESS_UNAVAILABLE` swallow with mapping to `CheckResult`
  (`UNAVAILABLE READINESS_ERROR`, error type only) and set `outcome.data_status`.
  `templates/fmp_cache_prices.py.tmpl` -> `WRAPPER_VERSION=4`, `_DATA_STATUS` = new enum; render
  reports `update` for v3 installs (existing drift/plan path). Exit stays 0 for a recorded business
  outcome (G1 §8).

### 1.3 Bounded integrity and matched-basis fundamentals
- `fmp_sync/integrity.py` (allowlisted SELECTs, window <= policy `max_sessions` (default 30) and
  symbols <= manifest cap, every query `LIMIT`-ed or aggregate):
  C3 duplicates grouped with `COALESCE(interval_type,'<null>')`, C4 aggregates, plus
  `NULL_PARTITION` count (rows with NULL interval/adjustment). `checked_rows == 0` for a non-empty
  expected window -> `CRITICAL EMPTY_PARTITION` (loud); intentionally empty window (all holidays)
  -> `NOT_APPLICABLE`; NULL SUMs are never coerced to 0. Price jump > 30% -> `WARN` only with
  corporate-action evidence complete, else `UNKNOWN`. Never deduplicates or rewrites.
- `fmp_sync/fundamentals.py`: pure functions over a normalized `FundamentalInput` (value, unit,
  currency, share class, as-of date, split basis, source). Float > outstanding (matched class/units/
  date/split basis) WARN; `abs(mcap/(close*shares)-1) > 0.15` WARN; diluted weighted shares
  identical for >=3 consecutive distinct fiscal quarters WARN (inspection, not wrong); current-FY
  estimates absent WARN/UNKNOWN. Any basis mismatch or missing input -> `UNKNOWN BASIS_MISMATCH`.
  Adapters: only `equity_profile.market_cap/price/currency` + `equity_historical.close`; JSON-blob
  sources (`shares_float_all`, `analyst_estimates`) -> `NOT_EVALUATED SOURCE_NOT_ADMITTED` until the
  storage owner exposes a qualified read interface.

### 1.4 Backup, binlog and disk observability (`fmp_sync/ops_observe.py`)
Metadata only, inputs from the private map (`ops.backup_dir`, `ops.backup_glob` default `*.sql.gz`,
`ops.binlog_dir` optional, `ops.volumes`): `shutil.disk_usage` per volume (free <15% WARN; <5% or
<5 GiB CRITICAL); newest **stable** backup (exclude `*.tmp`/`*.partial`, mtime older than 10 min,
size > 0) age >=26 h or size 0 -> CRITICAL; dir missing/denied -> `UNKNOWN`; backup task
registration and restore proof -> `NOT_EVALUATED` unless OPS-ATTEST (c) digest in map. Binlog
growth from file sizes vs prior sample in `<state>/ops/binlog.json`; first sample, negative delta
(rotation/purge) or interval < 1 h -> `UNKNOWN`, never 0 growth; `SHOW BINARY LOGS` only if the map
opts in, 1227 (privilege) -> `UNKNOWN`. AST test: no `PURGE`, `unlink`, `remove`, `rmtree`,
`subprocess`, `schtasks` in the new modules. Disk CRITICAL on the data volume sets
`BLOCKED DISK_CRITICAL` for **execute** admission (reads still allowed).

### 1.5 Catch-up recovery without fetch storms
- `state.py` gains per-job watermarks in `status.json` (`last_attempt_utc`,
  `last_successful_sync_session`, `last_validation_utc`, `delivery_state`), updated only by a
  run that holds the lock; heartbeats never advance `last_successful_sync_session`.
- `fmp_sync/recovery.py` `plan_catch_up(status, history, now, sessions)`: missed due runs since the
  watermark (cron `30 15 * * 1-5` PT intersected with sessions, 30 min grace) -> finding
  `CRON_RUN_MISSED` with count; coalesced into **one** run whose target is the current target session
  (gap-based warm already covers every missed session; <= 1 request per gapped symbol, capped by
  `per_run`). An open `defer.json` window -> the run makes zero sends and records
  `DEFERRED_RATE_LIMIT` again (transition-suppressed, so no repeated alert). No in-run retries
  (D10); FMP retries happen only at the next scheduled run. `delivery_state` is `unknown` for every
  wrapper line (the wrapper cannot see Hermes delivery) and never triggers a re-run.

## 2. Tasks

Shared setup (PowerShell, worktree root), as #1344:
`$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'`;
`$env:PYTHONPATH = "openbb_platform/tools/portfolio_utils;openbb_platform/extensions/agents"`;
`$T = "openbb_platform/tools/portfolio_utils/tests/fmp_sync"`. New fixtures under `$T/fixtures/`:
`calendar_synthetic.json` (2026-2028 sessions incl. half-days 2026-11-27, 2026-12-24), SQLite builder
`sql_fixture.py` (portable DDL for `equity_historical`, `market_holidays`, seeded synthetic rows only,
`tmp_path`), `FakeCursor` scripting rows and pymysql errors (1142, 1146, 1227, 2003) keyed by query id.
Acceptance labels: **A1** = holidays/half-days/DST/next-year, Pacific schedule -> correct Eastern
session, real dry-run readiness. **A2** = NULL partitions, missing grants, ambiguous timestamps,
unknown delivery -> explicit states, no fabricated health, no fetch storms.

### T01 (HFP-P08-T01): sessions, readiness v2, dry-run evaluation, private counts, table case - **CODE-ONLY**
Files: `fmp_sync/{checks,sessions,readiness,datasets}.py`; edits `fetch_position_history.py`
(`check_portfolio_app_readiness` delegates, keeps keys; `_previous_trading_day` kept as deprecated
shim), `populate_market_holidays.py` (Saturday New Year), `fmp_sync/{dispatcher,outcome,__main__}.py`
(`audit` subcommand, `data_status` enum), `templates/fmp_cache_prices.py.tmpl` (v4),
`portfolio_utils/pyproject.toml`. Tests `test_sessions.py`, `test_readiness.py`, `test_audit_cli.py`,
updates in `test_wrapper.py`, `test_render.py`, `../test_fetch_position_history.py`.
Red-first tests:
- A1: `test_thanksgiving_2026_targets_nov25`; `test_half_day_nov27_after_grace_targets_nov27`
  (`now` 2026-11-27 15:30 PT); `test_half_day_before_grace_targets_previous`;
  `test_1530_pt_maps_to_1830_et_across_dst` (2027-03-12/15, 2027-11-05/08); `test_naive_now_rejected`;
  `test_new_year_2027_friday_closed_and_jan4_session`; `test_2028_saturday_new_year_not_observed_dec31`
  (generator); `test_next_year_missing_warns_then_blocks_dec1`; `test_range_beyond_calendar_end_blocks`;
  `test_holiday_table_disagreement_reported_not_deleted` (SQLite seeded with 2021-12-31);
  `test_legacy_keys_preserved`; `test_audit_dry_run_zero_sockets_unvalidated`;
  `test_audit_read_only_runs_only_allowlisted_selects` (FakeCursor records statements; asserts read-only
  txn first, no DML); `test_lifecycle_unknown_is_unknown_not_ipo`; `test_exclusions_not_counted_success`.
- A2: `test_private_counts_off_by_default_no_private_sql`; `test_grant_missing_1142_is_unavailable`;
  `test_private_unavailable_never_zero_never_blocks_warm`; `test_private_counts_absent_from_stdout_status`
  (sentinel count value); `test_table_case_mismatch_reported`; `test_table_missing_1146`;
  `test_filled_rows_do_not_satisfy_freshness`; `test_ambiguous_host_local_fold_unknown` (2027-11-07
  01:30 LA); `test_required_unknown_never_validated`; `test_readiness_error_maps_to_unavailable`;
  `test_wrapper_v4_accepts_new_data_status_rejects_others`; `test_render_v3_install_is_update`.
Mutations that must fail tests: drop half-day close lookup; use host-local `date.today()`; coerce
`UNAVAILABLE` to 0; remove `is_filled` filter; remove the read-only transaction statement.
Focused: `& $py -m pytest "$T/test_sessions.py" "$T/test_readiness.py" "$T/test_audit_cli.py" "$T/test_wrapper.py" "$T/test_render.py" openbb_platform/tools/portfolio_utils/tests/test_fetch_position_history.py -q`
Real path (replaces "Not yet qualified"): `& $py -m portfolio_utils.fmp_sync audit --dry-run --map <tmp>\map-disposable.json --now 2026-11-27T15:30:00-08:00`
-> exit 0, `target_session=2026-11-27`, DB checks `NOT_EVALUATED`, zero sockets (audit hook count);
then `audit --read-only` with the same map and no MySQL listening -> `UNAVAILABLE MYSQL_UNAVAILABLE`,
`data_status=UNKNOWN`, exit 30, no fetch. Log to `.dev-cycle/verify-gh-1345.log`.

### T02 (HFP-P08-T02): bounded integrity + matched-basis fundamentals - **CODE-ONLY**
Files: `fmp_sync/{integrity,fundamentals}.py`, wiring in `readiness.evaluate` and `audit`; tests
`test_integrity.py` (SQLite fixture, real aggregate NULL semantics), `test_fundamentals.py`.
Red-first tests:
- A2: `test_empty_expected_window_is_critical_not_green` (C4 over zero rows -> SUM NULL);
  `test_all_holiday_window_not_applicable`; `test_null_partition_rows_counted`;
  `test_duplicates_with_null_interval_detected` (two rows, NULL adjustment, unique key bypassed);
  `test_invalid_close_negative_volume_critical`; `test_zero_volume_alone_ok`;
  `test_jump_without_corporate_action_evidence_unknown`; `test_window_and_symbol_bounds_enforced`;
  `test_no_dml_or_ddl_in_queries` (AST + allowlist scan).
- Fundamentals: `test_float_gt_outstanding_matched_basis_warn`; `test_basis_mismatch_unknown`
  (class/units/split date differ); `test_mcap_divergence_threshold_boundary` (0.15 exact = OK);
  `test_repeated_diluted_shares_three_quarters_warn_two_ok`; `test_current_fy_estimates_missing_warn`;
  `test_json_blob_sources_not_evaluated`; `test_missing_inputs_unknown_never_ok`.
Mutations: coerce `None` SUM to 0; drop the NULL-safe grouping; drop basis match.
Focused: `& $py -m pytest "$T/test_integrity.py" "$T/test_fundamentals.py" "$T/test_readiness.py" -q`
Real path: `& $py -m portfolio_utils.fmp_sync audit --dry-run --checks integrity,fundamentals --map <tmp>\map-disposable.json`
-> exit 0, DB checks `NOT_EVALUATED`, JSON-blob sources `SOURCE_NOT_ADMITTED` (aggregates run live in §3.1).

### T03 (HFP-P08-T03): ops observability + catch-up recovery - **CODE-ONLY** (+ **LIVE** game day)
Files: `fmp_sync/{ops_observe,recovery}.py`; edits `state.py` (watermarks, `delivery_state`),
`dispatcher.py` (`plan_catch_up` before warm; `DISK_CRITICAL` admission), `admission.py` (disk gate
code only); tests `test_ops_observe.py`, `test_recovery.py`, additions in `test_state.py`.
Red-first tests:
- Ops: `test_disk_thresholds_15_5_5gib` (injected `disk_usage`); `test_backup_age_26h_critical`;
  `test_backup_zero_size_critical`; `test_inprogress_backup_ignored`; `test_backup_dir_denied_unknown`;
  `test_binlog_first_sample_unknown`; `test_binlog_rotation_negative_unknown`;
  `test_binlog_growth_over_1gib_day_warn`; `test_show_binary_logs_1227_unknown`;
  `test_no_delete_or_purge_paths` (AST); `test_disk_critical_blocks_execute_not_read_only`.
- Recovery (A2 "no repeated fetch storms"): `test_gateway_down_three_fires_one_catch_up_run`
  (history with 3 missed due times; one run; FakeSend count <= gapped symbols <= `per_run`);
  `test_simulated_429_defers_and_next_run_sends_zero` (injected inner send returns 429
  `Retry-After: 120`; second run within window: `sent == 0`, `DEFERRED_RATE_LIMIT`, no transition
  line); `test_after_defer_window_single_resume`; `test_unknown_delivery_never_reruns`;
  `test_heartbeat_does_not_advance_sync_watermark`; `test_busy_run_does_not_touch_watermark`;
  `test_mysql_unavailable_no_fmp_send` (FakeCursor 2003 -> `FAILED_INFRA`, zero sends);
  `test_persist_failed_keeps_old_watermark`.
Mutations: catch-up per missed fire; ignore `defer.json`; advance watermark on PARTIAL.
Focused: `& $py -m pytest "$T/test_ops_observe.py" "$T/test_recovery.py" "$T/test_state.py" "$T/test_budget.py" "$T/test_dispatcher.py" -q`
Real path: `& $py -m portfolio_utils.fmp_sync audit --dry-run --checks ops --map <tmp>\map-ops.json`
(map points at tmp volumes and a tmp backup dir with a synthetic 0-byte `x.sql.gz`) -> `CRITICAL
BACKUP_EMPTY`, disk states, binlog `UNKNOWN FIRST_SAMPLE`; then `prices --execute` with a map whose
tmp state has an open `defer.json` -> `DEFERRED_RATE_LIMIT`, `sent=0`, exit 10.
**LIVE game day** (owner, after OPS-ATTEST + FMP-QUOTA test allocation): §3 steps 3-5.

Full sweep before PR: `& $py -m pytest openbb_platform/tools/portfolio_utils/tests -q`; black/ruff on changed files.

## 3. LIVE acceptance (owner-run; isolated `HERMES_HOME`; never the live store first)
1. Disposable schema `obb_disposable_<hex>` with synthetic seed incl. a NULL-partition row, a
   duplicate, a holiday-only window and a read-only grant without the three private tables:
   `& $py -m portfolio_utils.fmp_sync audit --read-only --map <private>\map-disposable.json`
   Expect `GRANT_MISSING` x3 (when private counts enabled), `NULL_PARTITION`, `EMPTY_PARTITION`, no writes.
2. `audit --dry-run --map <private>\map-production.json --target-class production` Expect exit 0, zero sockets.
3. Game day: stop the **test** gateway for two scheduled fires, restart; `hermes cron run <id>` Expect
   `CRON_RUN_MISSED`, one catch-up run, `sent <=` gapped symbols.
4. Point the disposable map at a loopback stub that returns 429 (test-only) for one run, then rerun
   within `Retry-After` Expect second run `sent=0`, one transition line total.
5. Ops: `audit --read-only --checks ops` against the real backup dir/volumes (metadata only).
   Report exit codes, finding codes and counts only. Read-only audit of `openbb_fmp_cache_test` is a
   separate owner decision (E7). Do not stop MySQL, touch the backup task or send orders.

## 4. PR batching
One PR for #1345 (T01-T03 share `checks`/`readiness`/`state` and the wrapper v4 contract), base
`portfolio`, body `Refs #1345` (closes after LIVE). Gates: focused + full `portfolio_utils` pytest,
black/ruff, local code/security/privacy reviews on the PR diff, OM8 local-CI fallback (no
`scripts/local_ci.py` on this base). Do not batch with #1298-#1301 work. If #1344 LIVE finds
wrapper defects, rebase T01's v4 template on that fix rather than merging both template bumps.

## 5. Decisions needed (recommended answers)
- **E1** Session authority = `exchange_calendars` XNYS (declared dep, explicit end = `current_year+1`),
  `market_holidays` only cross-checked. *Accept.*
- **E2** Publication grace 2 h after the actual close (half-days included). *Accept.*
- **E3** Fix `compute_us_holidays` Saturday New Year (writes change from 2028 rows on); existing
  wrong rows reported as `CALENDAR_DISAGREEMENT`, never deleted. *Accept; must merge before the
  2027 year-end upsert.*
- **E4** Private counts opt-in, default off; counts local only; states outbound. *Accept.*
- **E5** `data_status` enum + wrapper v4; Hermes exit 0 still means "observer completed". *Accept.*
- **E6** Thresholds as G1 §6 (1/2+ sessions, 26 h backup, 15%/5%/5 GiB disk, 1 GiB/day binlog,
  30 min cron grace), overridable in the map. *Accept as defaults.*
- **E7** Read-only `audit` against `openbb_fmp_cache_test` (no private counts) after the disposable
  LIVE run passes. *Owner decision; recommend yes, once, manual.*
- **E8** No audit cron registration in P08; render `fmp_cache_audit` wrapper in HFP-P09. *Accept.*
- **E9** Binlog via map-declared directory metadata; `SHOW BINARY LOGS` opt-in only. *Accept.*
- **E10** No in-run 429 retries; the next scheduled run is the only retry; `Retry-After` honoured
  via `defer.json`. *Accept.*

## 6. Risks, open questions, dependencies
- **#1298-#1301 owner (dependencies, not work here):** (a) provider `_get_basic_market_holidays`
  has the same Saturday-New-Year bug and accepts partial-year DB results (file `type-bug` for the
  owner); (b) nullable `interval_type`/`adjustment_type` let duplicates bypass the unique key; any
  NOT NULL/backfill is storage scope, we only report; (c) a qualified typed read interface for
  `shares_float_all` / `analyst_estimates` before fundamentals beyond `equity_profile` are evaluated;
  (d) canonical `market_holidays` DDL (fixture shape until then); (e) optional provider-native request
  hook (carried from #1344).
- Ad hoc closures (state funerals) reach `exchange_calendars` only via a library update; table
  disagreement is surfaced, not auto-resolved. `MAX_EXECUTION_TIME` caps SELECTs on MySQL 8+ only.
- `NOT_VISIBLE` vs `TABLE_MISSING` is told apart only by the COUNT error code; neither is zero.
- Backup freshness is not restore proof. `data_status` stays `UNVALIDATED` on production until E7
  and the #1344 LIVE run are recorded; OPS-ATTEST/FMP-QUOTA gate every LIVE step.

## Lead decisions (2026-11-28, under the owner's delegation)

- E1–E6 and E8–E10 are accepted as recommended.
- E3: the holiday-generator fix ships in this PR, before the 2027 year-end upsert.
- E7 (one manual read-only audit against `openbb_fmp_cache_test`) stays an OWNER decision. No agent step touches the live store.
- Owner-dependency (a), the provider `_get_basic_market_holidays` bug, is filed as #1392 for the fmp_cached owner. Dependencies (b)–(e) remain listed only.
- Model policy: the `portfolio` `CLAUDE.md` (D1) governs.
