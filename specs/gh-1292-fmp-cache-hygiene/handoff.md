# Handoff: fmp_cached cache hygiene (expiry pruning and auto-create default)

| Field | Value |
|---|---|
| Parent issue | #1292 (cleanup_expired_cache is a no-op; most cache rows never expire) |
| Sub-issues | #1293 (FMP_CACHE_AUTO_CREATE_DB default is inconsistent between init paths) |
| Branch | `fix/fmp-cached-cache-hygiene-gh-1292` |
| Base | `portfolio` @ `73ddcb8a7` |
| HEAD | uncommitted at handoff; the lead commits |
| Worktree | `.worktrees/fmp-cached-fixes-gh-1292-1293` |
| Executor model | `claude-opus-5.5` (route mode: tricky bug, no spec) |

## Changes

| Path | Change |
|---|---|
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py` | `CacheExpiryRule`, `CACHE_EXPIRY_RULES`, `EXPIRABLE_CACHE_TABLES`, a protected-table guard, `prune_expired_cache()`. `cleanup_expired_cache()` now runs that function instead of doing nothing. `should_auto_create()` delegates to `database.auto_create_enabled()` |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/database.py` | `AUTO_CREATE_DB_ENV`, `AUTO_CREATE_DB_DEFAULT = False`, `auto_create_enabled()`; `init_database()` uses it. Module-level disable for the existing deliberate `cyclic-import` |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_prune.py` | New prune command, `python -m openbb_fmp_cached.utils.cache_prune [--apply] [--table NAME] [--batch-size N]`, dry run by default |
| `openbb_platform/providers/fmp_cached/tests/test_cache_expiry.py` | New, 37 tests on a SQLite double of the `execute_query` seam |
| `openbb_platform/providers/fmp_cached/tests/test_auto_create_default.py` | New, 7 tests |
| `openbb_platform/providers/fmp_cached/tests/test_fmp_cached_fetchers.py` | `test_cleanup_operations` made hermetic. It previously called `cleanup_expired_cache()` against whatever database was configured |
| `openbb_platform/providers/fmp_cached/docs/DATABASE_CONFIGURATION.md` | Fixed the "(default behavior)" comment that said `true` |
| `docs/operations/portfolio-intelligence-cache-runbook.md` | Section 2.1 default; section 7 expiry table rewritten; new 7.1 prune procedure |
| `docs/operations/portfolio-intelligence-operator-setup.md` | Section 10: auto-create default and the prune command |

## Design

**Expiring tables.** A table counts as expiring only if its reader filters on
`cached_at` against a TTL, so an expired row is never served. Each rule's TTL
equals its reader's TTL, and a contract test checks this against the model
constants.

| Table | TTL |
|---|---|
| `aftermarket_quote` | 60 s |
| `equity_quote` | 300 s |
| `ttl_cache` where `cache_name = 'ExchangeMarketHours'` | 86400 s |
| `complementary_market_yields` (with the `test_` prefix in test mode) | 24 h |
| `balance_sheet`, `cash_flow`, `income_statement`, `key_metrics`, `financial_ratios`, `etf_holdings` | 1 day |
| `equity_profile`, `equity_peers`, `institutional_ownership` | 7 days |

Every other table is documented as non-expiring. This includes
`equity_historical` and `sp500_constituents`, which serves stale rows as a
fallback. `ttl_cache` rows with an unregistered `cache_name` are never touched.

**Safety.**

- An explicit allowlist, `EXPIRABLE_CACHE_TABLES`, is checked before any SQL
  runs, for both the `tables=` argument and the rules.
- A second guard refuses `pi_*`, `_pi_*`, `paper_*`, `snapshot*`,
  `fmp_trading_state`, `schema_version` and any table containing `audit`, even
  if one is added to the allowlist.
- Identifiers pass through `safe_identifier`, and every value is a parameter.
- The cutoff uses the database clock (`SELECT CURRENT_TIMESTAMP`).
- Deletes run in bounded batches (1 to 10000; select keys, then delete by key)
  and re-check the expiry predicate, so a row refreshed during the run is kept.
- An error in one table is reported, and the remaining tables are still pruned.
- The function returns a report and logs counts at INFO.

**#1293.** The single default is `False`, defined in `database.py`. Before this
change, `should_auto_create()` had no callers in the repository, so its `true`
default changed nothing. The effective runtime behaviour, `init_database()`
with `false`, is unchanged.

## Evidence

The full log is in `.dev-cycle/verify-gh-1292.log`.

- **Red:** with the no-op still in place, round 1 had 28 failed and 1 passed.
  The test that passed is the "operator tables untouched" guard; mutations M1
  and M2 cover it. Round 2, the CLI and auto-create tests, had 6 failed,
  including `test_both_init_paths_agree[None-False]`.
- **Green:** `pytest tests/test_cache_expiry.py tests/test_auto_create_default.py`
  gives 44 passed.
- **Mutations:** all 13 were killed. They covered: allowlist off, protected
  guard off, no re-check in DELETE, Python clock, wrong TTL, batch size
  ignored, dry run deleting, partition filter dropped, old `true` default in
  both paths, CLI defaulting to apply, no `batch_size` bound, and per-table
  errors aborting the run.
- **fmp_cached unit suite** (excluding integration and
  `test_real_integration.py`): the branch has the same 212 failures as an
  `origin/portfolio` export run in the same hermetic environment. They come
  from missing keys, credentials or modules. The branch adds 44 passing tests.
- **Real-path check:** `python -m openbb_fmp_cached.utils.cache_prune --help`
  exits 0. With `--apply --table fmp_trading_state` it exits 2 and refuses
  before any SQL. With no database configured it exits 2 on missing
  credentials and opens no connection.
- **Lint:** codespell, black, mypy (`--platform linux --no-site-packages` with
  the workflow flags), pylint, ruff and markdownlint are all clean. See the log
  for pylint details.

## Open questions for the owner

- Pruning is manual. Should it be scheduled, for example as a job like
  `techtrade.prune_snapshots`?

## Not done / follow-ups (candidates for issues; none filed)

- `examples.py` calls `await cleanup_expired_cache()` on a synchronous function,
  which was already broken. The file is not touched here, because touching it
  brings it into CI lint and it fails black, ruff and pylint.
- `aftermarket_quote` and the TTL wrapper compute cutoffs with UTC on the Python
  side, while `cached_at` uses the database session clock. Other readers use
  `datetime.now()`. Prune uses the database clock, but reader freshness can be
  skewed when the two clocks differ.
- About 60 tests in the existing suite make live FMP calls without an
  `integration` marker (they fail with "Invalid API KEY" when no key is set).
- `test_real_integration.py` loads the repo-root `.env` at import time.
- `test_two_provider_coverage.py` rewrites `docs/reports/fmp-two-provider-coverage.md`
  when the suite runs. Restored here.
