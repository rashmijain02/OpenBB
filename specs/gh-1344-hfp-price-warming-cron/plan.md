# Plan: guarded price warming through Hermes no-agent cron (#1344, HFP-P07)

Status: **design draft, not committed.** Branch `feat/hfp-price-warming-cron-gh-1344` off
`origin/portfolio` @ `16565fcc3` (includes #1338). Parent #1326 (HFP-F04), program:openbb-jobs.
Sources: workspace G1 draft `prompts\out\fmp-cache-hermes-sync-design.md` §1-5, 8, 9, 13 (SHA in
issue body); `docs/Specs/gh-1312-hermes-financial-planning/plan.md` §9, §12 "Specialized FMP-cache
operations boundary"; `.../github-plan/plan.md` HFP-P07..P09 and "External prerequisites".
External prerequisites **OPS-ATTEST and FMP-QUOTA are not granted**: every task is code-only
against fakes; nothing connects to `openbb_fmp_cache_test` (live store) or `openbb_fmp_cache` (old copy).

## 0. Existing assets (observed, metadata only)

| Asset (repo-relative) | Fact | Consequence |
|---|---|---|
| `openbb_platform/tools/portfolio_utils/portfolio_utils/fetch_position_history.py` `run_position_history_warm` | Importable warmer with seams `symbols`, `database`, `dry_run`, `skip_holiday_prestep`, `get_symbols_fn`, `holiday_prestep_fn`, `fetch_one_fn`, `api_key_resolver`, `readiness_fn`, `should_cancel`; returns frozen `PositionHistoryWarmResult` (`to_summary()`). | Wrap it; do not rewrite fetch/store. |
| same, `main()` | CLI runs `ensure_market_holidays` **before** the `--dry-run` return; non-dry path then calls the warmer with `skip_holiday_prestep=True`. No lock. | CLI dry-run writes `market_holidays`; fix in T01 and put the CLI under the lock. |
| same, `ensure_market_holidays` | Upsert (`ON DUPLICATE KEY UPDATE`), non-deleting; **swallows all errors** (prints WARNING). | Caller cannot tell success; coverage is validated by HFP-P08, not assumed. |
| same, `fetch_history` | `should_cancel` polled between symbols only; per-item `str(e)[:80]` into `failed`; `init_database()` (skipped when `FMP_CACHE_AUTO_CREATE_DB=false`, which the module `setdefault`s). | Error strings are never forwarded; cancellation granularity = one symbol. |
| same, `_fetch_one_symbol_history_in_scope` | One `_fetch_from_fmp_sync` per gapped symbol (full overall range); if `_analyze_cache_gaps` raises it falls back to the full range. | Request estimate is "≤1 per symbol", not a cap; T02 enforces the cap at transport. |
| same, `check_portfolio_app_readiness` | Unconditional `COUNT(*)` on `Portfolio_Positions`, `Account_Owner`, `ESPP_Plan`; previous-weekday target. | Least-privilege user fails it; P07 wraps it as `READINESS_UNAVAILABLE`; the fix is HFP-P08-T01. |
| same, module import | `load_dotenv(<PROJECT_ROOT>/.env, override=True)` where `PROJECT_ROOT` resolves to `openbb_platform/tools/portfolio_utils`; `sys.path` bootstrap with the same root. | Import can silently override `DB_*`/`FMP_CACHE_TEST_MODE`; admission snapshots DB, TLS/proxy (`HTTP(S)_PROXY`, `ALL_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `SSL_CERT_FILE`), `FMP_API_KEY` and state-root env before/after import (presence + SHA-256 only, never a value) and blocks on drift (`DOTENV_DRIFT`). **Stripped-env interaction:** the cron child starts with an allowlisted environment (no Hermes env is passed), so the warmer's `.env` legitimately *supplies* `DB_*`, `MYSQL_*`, `FMP_API_KEY`, `FMP_CACHE_*`. Drift is therefore only an *override*: a drift key that was present in the process environment before the import and whose hash changed or vanished after `.env` loading. Keys the `.env` newly supplies are allowed (never named or valued in outcomes). `FMP_CACHE_TEST_MODE` / `FMP_CACHE_AUTO_CREATE_DB` are still checked on the env, on the `.env` file and after import, and the resolved target is enforced independently by the database layer (`db_category` on the post-load values, then `SELECT DATABASE()` in execute mode). Credential sources on the cron path: `.env` and/or `~/.openbb_platform/user_settings.json` (`DatabaseConfig`; FMP key via `_resolve_api_key`); the owner confirms the resolved target is `openbb_fmp_cache_test` (OPS-ATTEST h). |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/equity_historical.py` `_fetch_from_fmp_sync` | Bare `requests.get(..., params={"apikey": ...}, timeout=120)`, no retries; `raise_for_status_redacted`. | Account at `requests.Session.send` in the dispatcher process; no provider edit. |
| `.../openbb_fmp_cached/utils/database.py` `database_override`, `DatabaseConfig._load_config` | ContextVar DB scope with `safe_identifier`; `FMP_CACHE_TEST_MODE=true` forces `openbb_fmp_cache_test`, default `openbb_fmp_cache`. | Never set test mode; explicit `database=` always. |
| `openbb_platform/tools/portfolio_utils/portfolio_utils/jobs.py` | `portfolio.position_history` (weekdays 01:00, `overlap_policy="forbid"`, **no `database` param** by design, `_should_cancel` always False). | Same guard must cover this handler (lock inside the warmer). Schedule cutover stays HFP-P09-T03. |
| `openbb_platform/core/openbb_core/app/jobs/worker.py` | Worker schedules and executes; `trigger --wait` only polls. | Not used (design §1). |
| `openbb_platform/tools/portfolio_utils/scheduler/run_*.ps1` | Task-Scheduler shims calling `run_openbb_jobs.ps1` (worker-dependent). | Untouched; inventoried at cutover. |
| `openbb_platform/core/openbb_core/app/static/package_builder.py` (≈L98-115) | In-repo `msvcrt.locking`/`fcntl.flock` 1-byte lock pattern. | Reuse the pattern (no `filelock` dep; it is present in the venv but undeclared). |
| `openbb_platform/extensions/agents/openbb_agents/hermes_integration/` (#1338) | `models.FailedLayer`, `HealthLevel`, `Presence`, `ComponentReport`; `provenance.resolve_fmp_cached_database`, `db_category`, `git_facts`, `origin_of`, `read_pyvenv_version`, `python_matches`; `profile.FinanceRuntimeProfile`/`DatabasePin`/`load_profile`; `hermes_preflight._check_database`. | Admission reuses these; no new identity/report vocabulary. `openbb_agents` is not installed in `.venv_portfolio` (import via path; lazy). |
| Tests: `openbb_platform/tools/portfolio_utils/tests/test_fetch_position_history.py`, `test_jobs.py`; no conftest | Fakes via injected seams. | New tests under `tests/fmp_sync/` with a safety conftest. |

`scripts/fetch_position_history.py` does **not** exist; the manual entry point is
`python -m portfolio_utils.fetch_position_history`. Docs saying otherwise are stale (not fixed here).

## 1. Design

New package `openbb_platform/tools/portfolio_utils/portfolio_utils/fmp_sync/`:
`locking.py`, `admission.py`, `budget.py`, `outcome.py`, `state.py`, `dispatcher.py` (`__main__`),
`render.py`. Only `admission.py` imports `openbb_agents.hermes_integration`, lazily; import failure is
`BLOCKED` with `FailedLayer.MODULE_ORIGIN`. No `subprocess` in the warming path (AST test); only
the rendered cron wrapper (§1.6) uses `subprocess`, to start the isolated venv child.

### 1.1 Lock protocol (shared by manual CLI, jobs handler and cron)
- **Key:** one lock per resolved target DB: `<lock_root>/fmp-sync.<db-lowercase>.lock`. Resolved DB =
  explicit `database` else `provenance.resolve_fmp_cached_database(settings, env).database`.
- **Root:** `FMP_SYNC_STATE_ROOT` else `%LOCALAPPDATA%\OpenBB\fmp-sync` (`~/.local/state/openbb/fmp-sync`
  off Windows). Refuse a root inside any git worktree, on a UNC path or a `DRIVE_REMOTE` drive
  (`GetDriveTypeW`): network locks are not mutual exclusion. Cron wrapper passes the root explicitly
  (Hermes child env is sanitized); render verifies it equals the manual default.
- **Acquire:** `os.open(O_RDWR|O_CREAT|O_NOINHERIT)`, seek 0, `msvcrt.locking(fd, LK_NBLCK, 1)`
  (Windows) / `fcntl.flock(LOCK_EX|LOCK_NB)`; non-blocking only. Contention -> `LockBusy` ->
  outcome `SKIPPED_BUSY` (never failure, never a second worker, never a wait loop).
- **Windows semantics:** the byte-range lock belongs to the handle/process and is released by the OS
  on handle close or process death (incl. `TerminateProcess` from a Hermes timeout); `O_NOINHERIT`
  keeps children from holding the handle. The lock file is **never deleted** (unlink races break
  exclusion; delete-pending on Windows).
- **Reentrancy:** process-local `threading.RLock` + depth counter per key; the dispatcher holds the
  lock across holiday step, warm and readiness, and the inner guard in `run_position_history_warm`
  re-enters. Different key in one process while holding one -> `LockConflict` (programming error).
- **Owner metadata / stale recovery:** after acquiring, atomically write `<lock>.owner.json`
  (run_id, pid, process start time, entrypoint, UTC start). It is diagnostic only. On acquire, an
  owner file whose run has no end receipt -> finding `PRIOR_RUN_INTERRUPTED` (recovery, not
  inherited health). A live holder older than 2x deadline -> `LOCK_HELD_OVERDUE` (WARN). No PID
  kill, no lock-file removal, no "stale" override flag.
- **Coverage limit:** uninstrumented writers (Workspace, MCP, other hosts) are not excluded; recorded
  as a standing limitation finding, not claimed.

### 1.2 Target and universe admission (before any DB/FMP access; ordered, first failure wins)
1. `PROCESS`/`ABI`: `sys.executable`'s venv equals the deployment map's pinned venv;
   `read_pyvenv_version` + `python_matches` against the profile `python` pin.
2. `MODULE_ORIGIN`: `portfolio_utils`, `openbb_fmp_cached`, `openbb_agents` resolve under the approved
   source root (`origin_of`); `git_facts` SHA equals the map's `source_sha`, `dirty is False`.
3. `CONFIG`: `FMP_CACHE_TEST_MODE` unset/false; `FMP_CACHE_AUTO_CREATE_DB` is `false`; DB-related env
   identical before/after importing the warmer (dotenv drift); `safe_identifier(target)`.
4. `DATABASE`: target == `profile.database.expected`; `resolve_fmp_cached_database` category is
   `expected` (default-resolving helpers would otherwise hit another DB); target class:
   `disposable` requires `^obb_disposable_[a-z0-9]{8,32}$` and not in {`openbb_fmp_cache`,
   `openbb_fmp_cache_test`}; `production` requires `--target-class production` **and** an
   `ops_attest_ref` digest in the map (else `BLOCKED_POLICY`). Execute mode then runs
   `SELECT DATABASE()` on the warmer's own connection path and blocks on mismatch before any write.
5. Universe: private ticker-only manifest JSON (`schema_version`, `manifest_id`, `source`,
   `accepted_at`, `expires_at`, `symbol_limit`, `symbols`, `benchmarks`, `sha256` over canonical
   sorted symbols). Block on expiry, digest mismatch, count > `symbol_limit` or > global cap,
   symbol not matching `^[A-Z][A-Z0-9.\-]{0,9}$`, `_is_cusip`, or empty result
   (`BLOCKED_EMPTY_UNIVERSE`, loud). `SKIP_SYMBOLS` applied and counted. Passed as `symbols=`, so
   `get_portfolio_symbols` is never called; the legacy selector is a labelled opt-in
   (`universe.legacy_selector: true`), default off. Receipts carry `manifest_id` + digest + counts.

### 1.3 Transport-accounted budget, deadline, cancellation
- `budget.TransportGuard` (context manager, dispatcher process only) wraps `requests.Session.send`
  and installs a `sys.addaudithook` on `socket.connect`/`socket.getaddrinfo`:
  allowlist = FMP host(s) + loopback MySQL port from the map; anything else (incl. LiteLLM
  `127.0.0.1:4000`) raises `EgressDenied` -> `FailedLayer.EGRESS` (proves zero LLM calls).
- Before each send: reserve 1 against per-run, per-minute (rolling 60 s) and per-day limits from
  a durable ledger `<state>/budget/<account_label>/<YYYY-MM-DD>.json` (day boundary per FMP-QUOTA;
  UTC until told), under the state lock. No reservation -> `BudgetExhausted` raised **before** the
  socket opens. After: record status class and `len(resp.content)` (bandwidth cap). An FMP connect
  without a matching reservation -> fail closed (`ACCOUNTING_GAP`).
- 429: parse `Retry-After`, persist `defer_until`, set cancel -> `DEFERRED_RATE_LIMIT`. 401/403 ->
  `AUTH`; 402 -> `BLOCKED_PLAN`; no retries are added in P07 (retry policy is HFP-P08).
- Deadline (one story, innermost first): (1) the dispatcher's monotonic deadline,
  `locking.DEFAULT_DEADLINE_S` = 900 s, ends the run itself (`CANCELLED_DEADLINE`); `send` caps
  `timeout` to `min(orig, remaining - reserve, 60)`. (2) The wrapper's hard deadline,
  `WRAPPER_DEADLINE_S` = 900 + 120 s margin = 1020 s: it touches `<state>/cancel/<run_id>`.
  (3) Grace, `WRAPPER_GRACE_S` = 30 s (rendered; render refuses grace outside (0, margin)): the
  child's CANCELLED line is relayed if it ends in time, otherwise the wrapper terminates the Job
  Object ("killed after grace", exit 5). (4) Hermes' script timeout (3600 s default) is only the
  outer backstop; render refuses deadline + grace >= 3600 s. `should_cancel` = deadline | budget
  exhausted | rate-limit defer | `<state>/cancel/<run_id>` file | SIGINT/SIGBREAK flag. Ctrl+C /
  Ctrl+Break reach the child only in a console run; under cron the wrapper receives them (the
  child is `CREATE_NO_WINDOW`) and relays them as the cancel file; a second stop request kills at
  once. DB statement time is not capped (provider scope); a kill leaves upserts idempotent and the
  lock released.
- Execute mode refuses to run without explicit limits in the map (no built-in quota default).

### 1.4 Sanitized structured outcome
`outcome.FmpSyncOutcome` (pydantic, `extra="forbid"`, frozen): schema_version, run_id (uuid4),
logical_job, mode, started/ended UTC, target_class + `db_category`, manifest_id/digest, source SHA,
counts (requested, skipped, success, failed, cancelled), budget (reserved, sent, bytes, limits),
transport status-class counts, `outcome` enum (`OK`, `PARTIAL`, `SKIPPED_BUSY`, `DEFERRED_QUOTA`,
`DEFERRED_RATE_LIMIT`, `CANCELLED_DEADLINE`, `BLOCKED_*`, `FAILED_INFRA`, `PERSIST_FAILED`),
`data_status` (`UNVALIDATED` until HFP-P08 readiness exists), `failed_layer: FailedLayer | None`,
finding codes, business exit code (0 ok, 10 partial/deferred/busy, 20 critical, 30 infra,
40 policy/config). Never: exception text, URLs, keys, account data, amounts. Symbols appear only in
`runs/<run_id>.json` (local). Errors map by type + transport ledger to codes. The wrapper never
imports the dispatcher: it reads the child's stdout through a pipe (first 4 KiB kept, rest drained)
and sends the child's stderr to `os.devnull`. Exactly one non-empty line is accepted and validated
field by field (`op`=prices, `mode`=execute, `run_id` 32 lowercase hex and equal to the run id the
wrapper chose, `outcome` from the enum with its matching `exit`, `data_status`/`failed_layer`
enums, `counts` with exactly requested/skipped/success/failed/deferred as non-negative ints, `sent`
non-negative int, <= 8 finding codes; or the short `BLOCKED_CONFIG` shape). Anything else, or a
non-business exit, prints only "internal error" (exit 4). Nothing else reaches cron.

### 1.5 State, receipts and Windows replacement
`<state>/status.json` (atomic, per-job entries), `history.jsonl` (append-only; run-start receipt
before work, end receipt after; `transition` event when fingerprint (outcome, data_status,
failed_layer, sorted findings) changes), `runs/<run_id>.json`, `alerts.json` (last fingerprint),
`deploy-receipts.jsonl` (render/registration receipts). Separate short-held `state.lock` (same
lock primitive, blocking with 2 s timeout) for every writer, including busy runs.
`state.atomic_write_json`: tmp in same dir, flush + `os.fsync`, `os.replace` with up to 8 jittered
attempts within ~1 s on `PermissionError` winerror 5/32/33; never unlink the old file; on exhaustion
remove only our tmp, keep the old snapshot (stale), return `PERSIST_FAILED` and exit nonzero
generically (never acknowledge durability). Preflight write/ACL check first; permanent denial is a
distinct code `STATE_ACCESS_DENIED`. Torn history tail -> `HISTORY_TORN_TAIL` finding, newline
guard, never truncate. No SQLite fallback.

### 1.6 Versioned paused cron wrappers
`render.py` (Python, pytest-testable; no PS1 so no Pester gate): `plan` (default) renders
`fmp_cache_prices.py` (`WRAPPER_VERSION=3`, fixed operation `prices`, no params from cron) from an
in-repo template plus a private deployment map (outside git: source root, source SHA, interpreter,
target, manifest path, state root, profile path, limits, `account_label`, `HERMES_TIMEZONE`).
Output: semantic diff + hashes; actions `create|update|unchanged|drift` (foreign edit blocks).
`apply-files` writes into the resolved `HERMES_HOME\scripts` (env `HERMES_HOME` else
`%LOCALAPPDATA%\hermes`; must contain `cron\`) via `atomic_write_json`'s replace helper (text
variant). It **prints** the paused registration command (`hermes cron create ... --no-agent
--paused`, local delivery and failure delivery, schedule `30 15 * * 1-5`); it never runs Hermes,
never edits `cron\jobs.json`. Wrapper runtime (v2 introduced the isolated child, v3 cooperative
cancel and the hardening below): stdlib-only, runs under whatever python Hermes uses; drops the
script directory with `sys` alone and imports `os` with `sys.path` narrowed to the stdlib (safe
under `-S`), then strips cwd and inherited `PYTHONPATH`. It verifies three SHA-256 values baked at
render time: its own text, the deployment map and the venv python (`CHILD_SHA256`); any mismatch
-> one generic integrity line, exit 3. It then starts the pinned venv python with `-I` and an
allowlisted environment (system/profile variables plus `FMP_SYNC_STATE_ROOT`; no Hermes env, no
`PYTHONPATH`), inserting the baked source paths after the stdlib (before site-packages). On
Windows the child is created suspended and `CREATE_NO_WINDOW`, assigned to a Job Object with
`KILL_ON_JOB_CLOSE` and only then resumed (every kernel32 call has explicit ctypes prototypes; an
assign/resume failure terminates the job: exit 4); elsewhere it gets its own session. The wrapper
chooses the run id and passes `--run-id`; cancellation follows §1.3. The venv python hash covers
the venv launcher only, not the base interpreter it starts (LIVE caveat, §6).

## 2. Tasks

Shared setup (PowerShell, from the worktree):
`$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'`;
`$env:PYTHONPATH = "openbb_platform/tools/portfolio_utils;openbb_platform/extensions/agents"`;
`$T = "openbb_platform/tools/portfolio_utils/tests/fmp_sync"`.
`$T/conftest.py` (autouse): `FMP_SYNC_STATE_ROOT=tmp_path`; `HOME`/`USERPROFILE`/`LOCALAPPDATA`
-> tmp (never reads real `user_settings.json`); deletes `FMP_API_KEY`, `DB_*`; patches
`pymysql.connect` and `socket.socket.connect` (non-loopback) to raise; asserts neither production
DB name reaches any call; synthetic profile/settings fixtures copied from #1338 `fixtures/`.

### T01 (HFP-P07-T01): shared lock + target/universe admission - **CODE-ONLY**
Files: `fmp_sync/{__init__,locking,admission}.py`; edits in `fetch_position_history.py`
(`run_position_history_warm` enters the guard; `main()` takes the guard for non-dry runs, prints
`SKIPPED_BUSY` and exits 75 on contention; `--dry-run` no longer calls `ensure_market_holidays`);
tests `test_locking.py`, `test_admission.py`, `test_cli_guard.py`.
Red-first tests -> acceptance:
- Lock contention (A2 "lock contention ... blocks/defers safely"): `test_two_processes_one_skipped_busy`
  (two real `$py` children via `subprocess`, the first holds via a test helper script under
  `tests/fmp_sync/helpers/`); `test_manual_cli_busy_exit_75_no_fetch`; `test_jobs_handler_busy_skips`;
  `test_reentrant_same_process`; `test_lock_released_on_kill` (kill holder, second acquires,
  finding `PRIOR_RUN_INTERRUPTED`); `test_lock_file_never_deleted`; `test_rejects_unc_and_repo_root`.
- Wrong target (A2): `test_blocks_live_and_old_names_in_disposable_mode`, `test_blocks_test_mode_env`,
  `test_blocks_dotenv_drift`, `test_blocks_profile_mismatch` (FailedLayer.DATABASE),
  `test_production_requires_attest_ref`, `test_select_database_mismatch_blocks_before_write` (fake conn).
- Universe (A1 "approved ticker manifest"): expiry, digest, limit, CUSIP, empty -> loud BLOCKED;
  `test_manifest_symbols_bypass_get_portfolio_symbols`.
- Safe dry-run: `test_cli_dry_run_makes_no_holiday_write`.
Mutations that must fail tests: remove guard call in warmer; drop `LK_NBLCK`; drop name denylist.
Focused: `& $py -m pytest "$T/test_locking.py" "$T/test_admission.py" "$T/test_cli_guard.py" openbb_platform/tools/portfolio_utils/tests -q`
Real path (replaces "Not yet qualified"): `& $py -m portfolio_utils.fmp_sync prices --dry-run --map <tmp>\map-wrong.json`
(synthetic map naming `openbb_fmp_cache_test` in disposable class) -> exit 40, `failed_layer=database`;
same with `map-disposable.json` -> exit 0 preview, zero sockets; `& $py -m portfolio_utils.fmp_sync lock --status --map ...`
while the pytest helper holds the lock -> `busy`. Log to `.dev-cycle/verify-gh-1344.log`.

### T02 (HFP-P07-T02): budgets, deadlines, cancellation, sanitized outcomes - **CODE-ONLY**
Files: `fmp_sync/{budget,outcome,dispatcher,__main__}.py`; tests `test_budget.py`,
`test_dispatcher.py`, `test_output_sentinels.py`. Dispatcher calls `run_position_history_warm(symbols=..., database=target, dry_run=..., skip_holiday_prestep=dry_run, holiday_prestep_fn=<years start..current+1, D2>, readiness_fn=<wrapped existing, exceptions -> READINESS_UNAVAILABLE>, should_cancel=...)`.
Red-first tests -> acceptance:
- Quota exhaustion (A2): `test_budget_blocks_before_socket` (limit 2, five gapped fakes calling real
  `requests.get` through the guard with an injected inner send returning built `requests.Response`):
  exactly 2 sends, outcome `DEFERRED_QUOTA`, remaining symbols persisted; `test_minute_window`;
  `test_daily_ledger_survives_restart`; `test_bytes_cap`; `test_429_retry_after_defers`;
  `test_402_blocked_plan_no_retry`; `test_unreserved_connect_fails_closed`.
- No LLM (A1): `test_egress_to_litellm_port_denied`; `test_no_openbb_agents_config_or_litellm_import` (AST).
- Deadline/cancel: `test_deadline_cancels_between_symbols`, `test_send_timeout_capped`,
  `test_cancel_file`, `test_sigbreak_flag` (skip off Windows).
- Secret-bearing failure (A2): sentinel key from `api_key_resolver` and sentinel text in a raised
  exception and in prints/logging; assert absent from wrapper stdout/stderr (fd-level capture),
  outcome, status, history and runs files.
- Structured status/history (A1): `test_outcome_schema_and_exit_codes` for every enum value;
  `test_no_delete_paths` (AST: no `cache_prune`, `replace_rows`, `pi_fmp_record`, DELETE/TRUNCATE literals).
Mutations: remove reservation; remove audit hook; forward `failed[].error`.
Focused: `& $py -m pytest "$T/test_budget.py" "$T/test_dispatcher.py" "$T/test_output_sentinels.py" -q`
Real path: `& $py -m portfolio_utils.fmp_sync prices --dry-run --map <tmp>\map-disposable.json --manifest <tmp>\synthetic.json`
-> exit 0, `sent=0`, outcome JSON in `<tmp>\state\runs`; and `--execute` with no limits in the map -> exit 40 `BLOCKED_POLICY`.

### T03 (HFP-P07-T03): versioned paused wrappers + durable receipts - **CODE-ONLY** (render/state) + **LIVE** (registration) + **NEEDS-OWNER-DECISION** (D1, D3)
Files: `fmp_sync/{state,render}.py`, template `fmp_sync/templates/fmp_cache_prices.py.tmpl`;
tests `test_state.py`, `test_render.py`, `test_wrapper.py`.
Red-first tests -> acceptance:
- Windows replacement: `test_replace_retries_on_sharing_violation` (real handle without
  `FILE_SHARE_DELETE` via `win32file.CreateFile`, released by a timer thread; skip off Windows);
  `test_replace_exhaustion_keeps_old_snapshot_and_persist_failed`; `test_acl_denied_distinct_code`;
  `test_history_torn_tail_finding`; `test_busy_run_still_appends_receipt`.
- State-change receipts: `test_transition_only_on_fingerprint_change` (unchanged -> empty stdout).
- Wrappers: `test_render_plan_is_default_and_writes_nothing`; `test_render_idempotent_unchanged`;
  `test_drift_blocks`; `test_wrapper_has_no_params_or_paths_from_cron`; `test_registration_text_is_paused_local`;
  `test_requires_hermes_timezone_los_angeles`; `test_schedule_1530_pt_is_1830_et_through_dst`
  (zoneinfo, 2027-03-15/11-08); `test_wrapper_hash_mismatch_generic_nonzero`;
  `test_wrapper_exit0_for_recorded_unhealthy_outcome`.
Focused: `& $py -m pytest "$T/test_state.py" "$T/test_render.py" "$T/test_wrapper.py" -q`
Real path (code-only): `& $py -m portfolio_utils.fmp_sync.render plan --map <tmp>\map-disposable.json --hermes-home <tmp>\hermes`
-> diff + printed paused command, no files written; `apply-files` into the tmp home, then
`& $py <tmp>\hermes\scripts\fmp_cache_prices.py` -> exit 0, one line, receipt appended.
**LIVE (owner, after OPS-ATTEST + test quota):** see §3 acceptance run.

## 3. Owner prerequisites and LIVE acceptance

**OPS-ATTEST** (owner provides a private attestation file; the map stores only its SHA-256):
(a) credential-bearing DB report sanitized and the affected MySQL/API credential rotated (yes/date);
(b) MySQL84 listens on 127.0.0.1 only or an inbound TCP 3306 block rule exists (rule name or
`Get-NetTCPConnection -LocalPort 3306 -State Listen` addresses); (c) 03:30 backup task name,
principal, DB coverage and newest file time; (d) runtime identity: approved OpenBB source path +
SHA (clean), `.venv_portfolio` version, installed Hermes version + `HERMES_HOME`, gateway state, and
that gateway and manual runs use the same Windows account; (e) optional least-privilege sync user
(SELECT/INSERT/UPDATE on `equity_historical`, `market_holidays`; no DELETE/TRUNCATE/DDL);
(f) a disposable schema `obb_disposable_<hex>` the owner creates with synthetic seed and a grant
without DELETE/TRUNCATE/DDL; (g) installed `hermes cron create --help` output to bind exact flags;
(h) where the DB credentials and the FMP key live for the account that runs the gateway
(`~/.openbb_platform/user_settings.json` and/or the warmer `.env` at
`openbb_platform/tools/portfolio_utils/.env`, loaded on import with override): the cron child does
**not** inherit the Hermes environment, so credentials may come from either source (a `.env` that
merely supplies keys is not drift; only overriding a key already in the process environment
blocks as `DOTENV_DRIFT`). Owner confirms the resolved target is `openbb_fmp_cache_test` (yes/no).
**FMP-QUOTA:** plan tier; per-minute, per-day and bandwidth limits; reset boundary/timezone; other
consumers' reservation (Workspace, MCP, agents, manual runs); this job's allocation (proposed 200/day,
20/min, per-run 120, bytes/day) and probe allowance; a LIVE test allocation (proposed ≤10 requests).

LIVE acceptance (template, isolated `HERMES_HOME` per #1338 O1; never the owner's live home first):
1. `& $py -m portfolio_utils.fmp_sync prices --dry-run --map <private>\map-disposable.json` Expect exit 0, sent=0.
2. `... prices --execute --map <private>\map-disposable.json` (3-symbol manifest) Expect `PARTIAL|OK`, sent ≤ 3, receipts redacted.
3. While 2 runs: `& $py -m portfolio_utils.fetch_position_history --symbols SPY --database obb_disposable_<hex> --skip-holiday-prestep` Expect exit 75 `SKIPPED_BUSY`.
4. Render `apply-files` into the isolated home; run the printed paused `hermes cron create`; `hermes cron run <id>` Expect one counts-only line, no LLM call, `cron list` shows paused.
5. Report exit codes, ledger counts, `history.jsonl` tail (codes only). Cleanup: `hermes cron remove <id>` (generated ID only); keep the disposable schema rows.
Production registration (paused) and any resume are separate owner decisions after HFP-P08.

## 4. PR batching
One PR for #1344 (T01-T03 share `fmp_sync/` and the outcome contract), body `Refs #1344` (not
`Closes`): code-only gates (focused pytest, existing portfolio_utils tests, black/ruff, local
code/security/privacy reviews, `scripts/local_ci.py --merged-with origin/portfolio` or the OM8
fallback). The issue closes after the LIVE run is recorded. Do not batch with #1300/#1301 work;
batch with HFP-P08 only if its plan is approved before this PR's local CI run.

## 5. Decisions needed (recommended answers)
- **D1** `HERMES_TIMEZONE=America/Los_Angeles`, prices `30 15 * * 1-5` (18:30 ET); ET sessions, UTC receipts. *Accept (design §4).*
- **D2** Execute mode runs the existing non-deleting holiday upsert through `current_year+1` under the lock; dry-run never. *Accept; 2027 must exist before 2026-12-31 (separate authorized run).*
- **D3** Lock/state root `%LOCALAPPDATA%\OpenBB\fmp-sync`, same Windows account for gateway and manual runs. *Accept; otherwise a shared ACL'd machine path set in both.*
- **D4** Manifest-only universe; legacy selector opt-in and labelled. *Accept.*
- **D5** No built-in quota: execute is BLOCKED until FMP-QUOTA limits are in the map. *Accept.*
- **D6** The child's stderr goes to `os.devnull`; its stdout is piped to the wrapper, which relays only the one validated outcome line and discards the rest. No private diagnostic file. *Accept; add one later only with ACL and owner consent.*
- **D7** Manual CLI: busy -> exit 75; `--dry-run` stops writing holidays (behaviour change). *Accept.*
- **D8** Leave `portfolio.position_history` job definition (now lock-guarded); do not run the worker; cutover in HFP-P09-T03. *Accept.*
- **D9** `fmp_sync` lives in `portfolio_utils`, lazily importing `openbb_agents.hermes_integration`. *Accept; alternative is moving admission glue into `openbb_agents`.*

## 6. Risks and open questions
- Session.send/audit-hook accounting is process-wide monkeypatching; a provider-native request hook
  would be cleaner but is **#1298-#1301 owner scope** (listed as an optional dependency, not work here).
- `_analyze_cache_gaps` failure falls back to a full-range fetch and full-history responses are large;
  budget counts requests and bytes but cannot shrink responses (provider scope; no change).
- `ensure_market_holidays` swallows errors; P07 cannot prove calendar coverage (HFP-P08-T01).
- DB statements have no timeout under our control; the wrapper's hard deadline + grace and the
  Job Object kill are the backstop (Hermes' timeout is outermost).
- LIVE verification still needed: the installed Hermes `cron create` flags (OPS-ATTEST g); what the
  gateway does to the wrapper on its own timeout (console event -> cooperative cancel; hard
  terminate -> the Job Object still kills the child and frees the lock, but no run file is
  written); which python the gateway runs the wrapper with (any 3.x works, the child is always the
  venv python); whether the child sees the expected credentials without the Hermes env
  (OPS-ATTEST h); and that the venv launcher's base interpreter is the attested one (only the
  launcher is hashed).
- Uninstrumented writers (Workspace/MCP/LAN) are outside the lock; standing limitation finding.
- `data_status` stays `UNVALIDATED` until HFP-P08; production jobs must stay paused until then.
- Conflict check with #1298-#1301: none required; no edits to `openbb_fmp_cached` storage, schema,
  retention, prune, `equity_historical` store/upsert, `DatabaseConfig` or `database_override`.

## Lead decisions (2026-11-28, under the owner's delegation)

D1–D9 are accepted as recommended:
- D1: the gateway runs on `HERMES_TIMEZONE=America/Los_Angeles` with schedule `30 15 * * 1-5`.
- D2: execute mode runs the non-deleting holiday upsert through `current_year+1`, under the lock.
- D3: the lock and state root is `%LOCALAPPDATA%\OpenBB\fmp-sync`; the gateway and manual runs use the same Windows account.
- D4: the universe comes from the manifest only.
- D5: there is no built-in quota default.
- D6: the child's stderr goes to devnull; of its stdout only the one validated outcome line is relayed.
- D7: a busy lock makes the manual command exit 75, and `--dry-run` no longer writes holidays.
- D8: the openbb-jobs schedule stays and is now lock-guarded; the worker is not run, and cutover happens in HFP-P09.
- D9: `fmp_sync` lives in `portfolio_utils` and imports `hermes_integration` lazily.

OPS-ATTEST and FMP-QUOTA remain owner prerequisites for every LIVE step. No CODE-ONLY step connects to `openbb_fmp_cache_test` or `openbb_fmp_cache`. Nothing here changes fmp_cached storage, retention or prune; that scope stays with #1298–#1301.
