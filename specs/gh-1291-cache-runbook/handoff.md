# Handoff: Provider-cache backup and restore runbook (#1291)

Branch `docs/pi-cache-runbook-gh-1291`, base `origin/portfolio` b886835ce. Changes uncommitted.

## Changed

- Added `docs/operations/portfolio-intelligence-cache-runbook.md`.
- Added a link paragraph in section 10 of `docs/operations/portfolio-intelligence-operator-setup.md` (file keeps CRLF endings).

## Stores covered and sources

- fmp_cached MySQL: `utils/database.py`, `utils/cache_schema.py`.
- EOD snapshot (MySQL or SQLite): `techtrade/config.py`, `snapshot/store.py`, `snapshot/mysql_store.py`, `jobs.py`.
- Paper ledger: `techtrade/config.py`, `execution/paper_engine.py`, `mysql_paper_engine.py`.
- Execution audit: `widgets_endpoints.py`, `execution/broker_adapter.py`, `execution/secure_file.py`.

## Verification

- markdownlint-cli 0.39.0 with `.markdownlintrc`: clean on both files.
- codespell: clean.
- New doc is LF.
- No backup commands were run.

## Findings and lead decisions

- `/health/details` and `serve status` do not report store paths or engines; the runbook says so and uses env var names and log warnings instead.
- `cleanup_expired_cache()` is a no-op, so the provider cache never expires except `aftermarket_quote` (60s), `ttl_cache` and the free-yield cache (24h).
- The MySQL snapshot, paper and trading-state tables share the provider-cache database, so a whole-database dump is operator data. The runbook gives split dumps.
- `FMP_CACHE_AUTO_CREATE_DB` defaults differ: `init_database()` uses false and `should_auto_create()` uses true. The runbook cites `init_database()`.
- `DATABASE_CONFIGURATION.md` says the default is false for auto-create, which matches `init_database()`.
- The `techtrade.prune_snapshots` schedule is 19:00 in code but 04:00 in the older design spec. The runbook follows the code.
- There is no CLI to run the prune job manually; the runbook does not invent one.
- The `sqlite3` CLI is not repo-provided; the Python `Connection.backup` alternative is mentioned.
- The hermetic probe is `test_workspace_endpoint_contracts.py`; I did not run it.
