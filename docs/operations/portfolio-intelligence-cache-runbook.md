# Portfolio Intelligence cache and data-store runbook

Back up, restore, size and prune the data stores behind the Portfolio
Intelligence Workspace backend. Issue #1291; companion to the
[operator setup guide](portfolio-intelligence-operator-setup.md).

All paths are relative to the repository root unless they start with `~` or
an angle-bracket placeholder (`<backup-dir>`, `<database>`, `<mysql-option-file>`).
Replace placeholders with your own values and keep those values out of commits,
issues and logs. This runbook never needs you to open, print or paste real
cache rows or account data; every example below is synthetic or metadata-only.

## 1. What each store holds

| Store | Holds | Classification | Safe to delete? |
|---|---|---|---|
| `fmp_cached` provider cache (MySQL) | Public market data fetched from the data provider: prices, statements, estimates, market hours | Public market data | Yes. Rebuilds on demand, at the cost of API quota and time |
| EOD snapshot store, MySQL backend (default) | `pi_eod_snapshot`, `pi_eod_live_pointer`, `snapshot_job`, `snapshot_job_error` in the same database as the provider cache | Derived from public data, but stored beside operator output | No. Rebuildable only for sessions the provider can still serve |
| EOD snapshot store, SQLite backend | One file, default `~/.portfolio_intel/snapshot.db`. Account-scoped (PII) datasets are only ever written here, never to shared MySQL | Operator data | No |
| Paper ledger | MySQL `pi_paper_*` tables and `_pi_paper_lot`, or a SQLite file, default `~/.portfolio_intel/paper.db` | Operator data | No |
| Paper order batches | Files under a directory, default `~/.portfolio_intel/order_batches` | Operator data | No |
| Execution audit journal | One SQLite file, default `~/.portfolio_intel/execution-audit/audit.db`, append-only idempotency and audit records | Operator data | No. Deleting it discards the idempotency record that stops a duplicate submission |
| Trading state | MySQL `fmp_trading_state` in the provider database | Operator data | No |
| MCP story run store | One SQLite file, default `~/.openbb_platform/story_runs.sqlite`, or the path in `OPENBB_STORY_RUN_STORE`; run records keyed by principal | Operator data | No |

Two consequences:

- A whole-database dump of the provider-cache MySQL database is **not** a
  public-data backup when the paper and snapshot engines use MySQL, because
  they share that database. Section 4.3 shows how to dump the public cache only.
- If MySQL is unreachable at startup, the snapshot store and paper engine fall
  back to SQLite files (see section 2), so a host can hold the same kind of data
  in both places. Check both.

Sources: table definitions in
`openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/mysql_store.py`
and `openbb_platform/extensions/techtrade/openbb_techtrade/execution/mysql_paper_engine.py`;
the PII rule in `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/registry.py`
and [EOD snapshot refresh](eod-snapshot-refresh.md); `fmp_trading_state` in
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py`.

## 2. Where each store lives

### 2.1 Provider cache and shared MySQL

Defined in `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/database.py`.
Connection settings resolve in this order:

1. The `credentials` block of `~/.openbb_platform/user_settings.json`, if it
   contains any of the `mysql_*`, `db_*` or `database_*` keys.
2. Otherwise the environment variables below.
3. Otherwise the built-in defaults.

| Setting | Environment variable | Default |
|---|---|---|
| Host | `DB_HOST` | `localhost` |
| Port | `DB_PORT` | `3306` |
| User | `DB_USER` | none (required) |
| Password | `DB_PASSWORD` | none (required) |
| Database | `DB_NAME` | `openbb_fmp_cache` |
| Test database | `FMP_CACHE_TEST_MODE=true` | `openbb_fmp_cache_test`, with a `test_` table prefix |
| Create tables on start | `FMP_CACHE_AUTO_CREATE_DB` | `false`. Only the value `true` (any case) enables it |

The auto-create default is defined once, in `auto_create_enabled()` in
`database.py`; `init_database()` and `cache_schema.should_auto_create()` both
use it.

Startup fails if the user or password is missing. Never put the password on a
command line; use an option file (section 4.3).

### 2.2 EOD snapshot store

Defined in `openbb_platform/extensions/techtrade/openbb_techtrade/config.py` and
`openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py`
(`get_default_snapshot_store`).

| Variable | Values | Default |
|---|---|---|
| `PI_SNAPSHOT_ENGINE` | `mysql`, `sqlite` | `mysql` |
| `PI_SNAPSHOT_DB` | SQLite file path | `~/.portfolio_intel/snapshot.db` |
| `OPENBB_TECHTRADE_SCAN_DB` | compatibility path for the scan store (`openbb_techtrade/snapshots/sqlite.py`) | the snapshot database path |

With `PI_SNAPSHOT_ENGINE=mysql`, a construction failure (missing driver,
unreachable server, refused schema) logs a WARNING and falls back to SQLite at
the resolved path. The SQLite file must resolve outside the repository and must
not be a hard link; the store refuses it otherwise. The SQLite store runs in WAL
mode, so a live copy of the `.db` file alone can be inconsistent (section 4.4).

### 2.3 Paper ledger, order batches and audit journal

| Variable | Default | Source |
|---|---|---|
| `PI_PAPER_ENGINE` (`mysql` or `sqlite`) | `mysql` | `openbb_techtrade/config.py` |
| `PI_PAPER_DB` | `~/.portfolio_intel/paper.db` | `openbb_techtrade/config.py` |
| `PI_ORDER_SINK_PAPER_DIR` | `~/.portfolio_intel/order_batches` | `openbb_techtrade/config.py` |
| `PI_T5_EXECUTION_AUDIT_DB` | `~/.portfolio_intel/execution-audit/audit.db` | `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py` |

The MCP story run store
(`openbb_platform/extensions/mcp_server/openbb_mcp_server/story_adapters/registry.py`,
`default_store_path`) holds per-principal run records in a `story_runs` table.
Treat it as operator data and back it up and restore it with the SQLite
procedure in sections 4.4 and 5.2, using a distinct backup name such as
`story-runs-<date>.db`.

The audit path must be absolute and free of `..` and links. Its directory is a
dedicated private directory (`openbb_techtrade/execution/broker_adapter.py`,
`openbb_techtrade/execution/secure_file.py`): it may contain only the database,
its `-journal`, `-wal` and `-shm` files and a `.openbb-execution-audit` marker,
and is locked to the owner (mode `0700`, files `0600`). Do not put backups or
other files in it; the store refuses to open.

### 2.4 Finding the active location

The backend's `/health/details` and the launcher `status` report auth mode,
demo mode, origins and manifest verdict only. They do **not** report store
paths or engines, so they cannot tell you where data lives. Instead:

1. Work out which source supplies the MySQL settings. Precedence is fixed
   (section 2.1): if the `credentials` block of
   `~/.openbb_platform/user_settings.json` contains any `mysql_*`, `db_*` or
   `database_*` key, it supplies host, port, user, password and database name,
   and the `DB_*` variables are ignored. Check only whether such keys exist,
   never their values; do not open or print that file in a shared terminal or
   log. Otherwise the `DB_*` variables apply. List which environment settings
   are set, without printing their values, in a shell that has the backend's
   environment:

   ```bash
   env | grep -E '^(PI_SNAPSHOT_ENGINE|PI_SNAPSHOT_DB|PI_PAPER_ENGINE|PI_PAPER_DB|PI_ORDER_SINK_PAPER_DIR|PI_T5_EXECUTION_AUDIT_DB|DB_HOST|DB_PORT|DB_NAME)=' | sed 's/=.*/=<set>/'
   ```

   Unset variables use the defaults in the tables above.

2. To see whether a MySQL fallback happened, search the backend log in the
   launcher state directory (operator setup guide, section 3) for the WARNING
   text `MySQL backend unavailable` (snapshot store) or `MySQL backend
   unreachable` (paper engine). Do not paste the surrounding lines anywhere.

3. Confirm SQLite files exist with metadata only:

   ```bash
   ls -l ~/.portfolio_intel/
   ```

## 3. Before you start

- Work only with metadata: file names, sizes, modes, table names and row counts.
  Do not `cat`, `SELECT *` or otherwise display rows from any store.
- Keep every backup outside the repository checkout. Never commit a dump,
  database file or order batch.
- Pick `<backup-dir>` on an encrypted or access-controlled volume.

## 4. Back up

### 4.1 Prepare a private backup folder

Do this before any dump or copy, so no backup file is ever created with wider
access than intended. Backups of everything except the public provider cache
hold operator data. The repository's own audit store sets the standard to
copy: directory `0700`, files `0600`, owner only
(`openbb_techtrade/execution/secure_file.py`).

Linux and macOS:

```bash
umask 077
mkdir -p <backup-dir>
chmod 700 <backup-dir>
```

Keep the `umask 077` in the same shell for every later backup command, so new
files are created `0600`.

Windows (PowerShell): create the folder, then restrict it to your own account
and make children inherit that ACL, before writing anything into it:

```powershell
New-Item -ItemType Directory -Path "<backup-dir>" -Force | Out-Null
icacls "<backup-dir>" /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F"
```

Keep operator-data backups encrypted at rest if the volume is shared or
synchronised to a cloud service. The public-cache dump needs no special
handling beyond staying out of the repository.

### 4.2 Stop the backend first

A stopped backend writes nothing, so file copies are consistent. Use the
launcher in the operator setup guide, with the same `PI_WIDGET_BACKEND_TOKEN`
the backend started with:

```bash
python -m openbb_portfolio_intel.widget_backend.serve stop
```

Also stop any scheduled `python -m openbb_techtrade.snapshot.refresh` run and the
OpenBB jobs worker, because they open the snapshot store independently of the
backend. If you cannot stop them, use the online methods in 4.3 and 4.4, which
take a consistent snapshot while writers run.

Restart afterwards with `serve start`.

### 4.3 MySQL (provider cache, snapshots, paper ledger)

Take `<database>` and the host from whichever source applies under the
precedence in section 2.1 (the `user_settings.json` credentials block first,
then `DB_*`, then defaults). Put the credentials in a private option file so
they never appear in a process list. Create `<mysql-option-file>` with mode
`0600` and type the values yourself; do not print them from the settings file:

```ini
[client]
host=<db-host>
user=<db-user>
password=<db-password>
```

Public provider cache only (excludes every operator table named in section 1):

```bash
mysqldump --defaults-extra-file=<mysql-option-file> --single-transaction \
  --ignore-table=<database>.pi_eod_snapshot \
  --ignore-table=<database>.pi_eod_live_pointer \
  --ignore-table=<database>.snapshot_job \
  --ignore-table=<database>.snapshot_job_error \
  --ignore-table=<database>.pi_paper_account \
  --ignore-table=<database>.pi_paper_order \
  --ignore-table=<database>.pi_paper_fill \
  --ignore-table=<database>.pi_paper_position \
  --ignore-table=<database>._pi_paper_lot \
  --ignore-table=<database>.fmp_trading_state \
  <database> > <backup-dir>/provider-cache.sql
```

Operator tables only (snapshots, paper ledger, trading state):

```bash
mysqldump --defaults-extra-file=<mysql-option-file> --single-transaction \
  <database> pi_eod_snapshot pi_eod_live_pointer snapshot_job snapshot_job_error \
  pi_paper_account pi_paper_order pi_paper_fill pi_paper_position _pi_paper_lot \
  fmp_trading_state > <backup-dir>/operator-tables.sql
```

`--single-transaction` gives a consistent InnoDB snapshot without stopping the
backend; the tables named here are InnoDB (the `ENGINE=InnoDB` clauses in the
schema files cited in section 1). `<database>` is `openbb_fmp_cache` unless you
set `DB_NAME`. A table that does not exist in your deployment (for example the
paper tables when you use the SQLite paper engine) makes `mysqldump` report an
error for the second command; remove that name and rerun.

If you dump the whole database in one file, treat the file as operator data.

### 4.4 SQLite (snapshot, paper ledger, audit journal)

Use SQLite's own consistent copy; it is safe while the backend runs and handles
the WAL file. With the `sqlite3` command-line tool:

```bash
sqlite3 <source-db> ".backup '<backup-dir>/<name>-<date>.db'"
```

or, equivalently, a compacted copy:

```bash
sqlite3 <source-db> "VACUUM INTO '<backup-dir>/<name>-<date>.db'"
```

`<source-db>` is the file from section 2 (`PI_SNAPSHOT_DB`, `PI_PAPER_DB` or
`PI_T5_EXECUTION_AUDIT_DB` or `OPENBB_STORY_RUN_STORE`; the defaults are the
`~/.portfolio_intel/...` paths and `~/.openbb_platform/story_runs.sqlite`).
Give every database its own distinct, dated target name (for example
`snapshot-<date>.db`, `paper-<date>.db`, `audit-<date>.db`). `.backup`
overwrites an existing target file, so a reused name silently replaces an
earlier backup (`VACUUM INTO` instead fails if the target exists). Do not copy the `.db` file with `cp` while the
backend runs: committed data can sit in the `-wal` file. With the backend
stopped, copying the `.db` together with any `-wal` and `-shm` files is also
valid.

The `sqlite3` command-line tool is not installed by this repository. If it is
absent, the same operation is available from the Python standard library
(`sqlite3.Connection.backup`) with the project's Python.

### 4.5 Paper order batches

With the backend stopped, copy the `PI_ORDER_SINK_PAPER_DIR` directory tree as a
whole into `<backup-dir>`, for example `cp -a` on Linux or macOS or
`Copy-Item -Recurse` on Windows.

## 5. Restore

Restore into an empty or disposable target first when you can. Stop the backend
and every other writer (4.2) before restoring.

### 5.1 MySQL

> **Warning: a restore replaces existing tables.** A `mysqldump` file contains
> `DROP TABLE IF EXISTS` followed by `CREATE TABLE` for each table, so loading
> it discards the current contents of every table it names, including operator
> tables if the dump includes them. Before any restore, take a fresh dump of the
> CURRENT state (section 4.3, with a new file name such as
> `pre-restore-<date>.sql`) and keep it until verification passes. This is your
> MySQL rollback.

1. Create the empty database named `<database>` if it does not exist, as in the
   [database configuration guide](../../openbb_platform/providers/fmp_cached/docs/DATABASE_CONFIGURATION.md).
2. Confirm the pre-restore dump from the warning above exists and is non-empty,
   then load the dump:

   ```bash
   mysql --defaults-extra-file=<mysql-option-file> <database> < <backup-dir>/provider-cache.sql
   ```

3. Repeat for `operator-tables.sql` only if you are also restoring operator data.

A snapshot schema that does not match the code can be refused at startup
(`SnapshotSchemaMismatch`, `openbb_techtrade/snapshot/store.py`); restore from a
dump taken with the same code version.

### 5.2 SQLite

1. Move the existing database aside together with its `-wal` and `-shm` files
   (for example to `<name>.pre-restore`), keeping all three. Never delete the
   `-wal` or `-shm` file: after a crash the WAL can hold committed data that is
   not yet in the `.db`.
2. Copy the backup file to the original path as a regular file (not a hard link;
   the snapshot store refuses hard-linked files). Leave no `-wal` or `-shm` file
   next to the restored database; they were moved aside in step 1.
3. Restore permissions: `chmod 600` the file and `chmod 700` its directory on
   Linux and macOS.
4. For the audit journal, restore only the database file into its existing
   dedicated directory. The store recreates the `.openbb-execution-audit` marker
   and re-applies owner-only permissions on open.

### 5.3 Order batches

Copy the directory tree back to `PI_ORDER_SINK_PAPER_DIR` with the backend
stopped.

## 6. Verify the restore

1. Start the backend and check status; exit code 0 means healthy with valid
   manifests:

   ```bash
   python -m openbb_portfolio_intel.widget_backend.serve start
   python -m openbb_portfolio_intel.widget_backend.serve status
   ```

2. Validate the Workspace manifests (the same check CI uses):

   ```bash
   python scripts/validate_portfolio_workspace_manifests.py
   ```

3. Run the hermetic endpoint probe. It runs in a scrubbed environment with a
   temporary home directory and a blocked network, so it proves the code and
   manifests but does not read your restored data:

   ```bash
   python -m pytest openbb_platform/extensions/portfolio_intel/tests/unit/test_workspace_endpoint_contracts.py -q
   ```

4. Check the stores with metadata only:
   - SQLite: `sqlite3 <restored-db> "PRAGMA integrity_check"` prints `ok`.
   - MySQL: compare an exact row count per table with the count taken at
     backup time, for example `SELECT COUNT(*) FROM <table>` for each table you
     restored. Do not rely on `information_schema.tables.table_rows`; for InnoDB
     it is only an estimate.
5. Open one widget in Workspace and confirm its data-state badge shows `cached`
   or `live`, not `demo`, for a public symbol.

If any step fails, stop the backend and roll back:

- SQLite: move the restored `.db` aside and put back the `.db`, `-wal` and
  `-shm` files you moved aside in 5.2 step 1, all three together.
- MySQL: load the pre-restore dump taken in 5.1 the same way as in 5.1 step 2.
  This replaces the tables again with their pre-restore state.

Investigate before trying again.

## 7. Retention, size and pruning

What the code actually does:

| Store | Expiry or pruning | Source |
|---|---|---|
| Provider cache, expiring tables | Each table below is read only while `cached_at` is inside its reader's TTL. `prune_expired_cache()` (alias `cleanup_expired_cache()`) and the prune command (7.1) delete rows older than that TTL. Nothing runs it on a schedule | `openbb_fmp_cached/utils/cache_schema.py` (`CACHE_EXPIRY_RULES`) |
| `aftermarket_quote` | 60 seconds | `openbb_fmp_cached/models/aftermarket_quote.py` |
| `equity_quote` | 300 seconds | `openbb_fmp_cached/models/equity_quote.py` |
| `ttl_cache`, `cache_name = ExchangeMarketHours` | 86400 seconds. Rows with any other `cache_name` have no registered TTL and are never pruned | `openbb_fmp_cached/models/exchange_market_hours.py` |
| `complementary_market_yields` (free-yield cache; `test_` prefix in test mode) | 24 hours (`DEFAULT_TTL_HOURS`) | `openbb_fmp_cached/complementary/free_yield_service.py` |
| `balance_sheet`, `cash_flow`, `income_statement`, `key_metrics`, `financial_ratios`, `etf_holdings` | 1 day | the matching `openbb_fmp_cached/models/<table>.py` |
| `equity_profile`, `equity_peers`, `institutional_ownership` | 7 days | the matching `openbb_fmp_cached/models/<table>.py` |
| Provider cache, every other table | None. Non-expiring: rows are overwritten or extended on refetch and only grow. This includes `equity_historical` and the other historical tables, the reference lists, and `sp500_constituents` (it serves stale rows when the provider fails) | `openbb_fmp_cached/utils/cache_schema.py` |
| EOD snapshots (both backends) | `prune()` with a `RetentionPolicy(keep_sessions=N)` deletes non-LIVE rows outside the newest `N` distinct sessions per dataset and entity. LIVE rows are never pruned. The default policy keeps everything | `openbb_techtrade/snapshot/store.py`, `openbb_techtrade/snapshot/mysql_store.py` |
| Scheduled snapshot pruning | Job `techtrade.prune_snapshots`, daily at 19:00 in the configured schedule timezone, default `keep_sessions=10` (allowed 0 to 1000), applied to every TechTrade dataset | `openbb_techtrade/jobs.py` |
| Paper ledger, audit journal, story run store, order batches | No pruning in code. Retention is your decision | none |

The provider-cache paths above are under
`openbb_platform/providers/fmp_cached/`, and the TechTrade paths under
`openbb_platform/extensions/techtrade/`.

### 7.1 Prune expired provider-cache rows

Run with the project's Python, in a shell that has the backend's database
settings (section 2.1):

```bash
python -m openbb_fmp_cached.utils.cache_prune                      # dry run: counts only
python -m openbb_fmp_cached.utils.cache_prune --apply              # delete expired rows
python -m openbb_fmp_cached.utils.cache_prune --apply --table balance_sheet --table cash_flow
```

- Dry run is the default. It prints a JSON report of row counts per table and
  never prints row contents.
- `--apply` deletes in batches (`--batch-size`, default 1000, at most 10000).
  Each batch is a separate statement with parameterized values, so the command
  is safe to run while the backend runs; a row refreshed during the run is kept.
- Expiry is measured on the database clock (`CURRENT_TIMESTAMP`), the clock that
  stamps `cached_at` on write.
- It touches only the tables in the table above. An explicit allowlist
  (`EXPIRABLE_CACHE_TABLES`) is checked before any SQL runs, and operator tables
  (`pi_*`, `_pi_*`, `snapshot_*`, `fmp_trading_state`, `schema_version` and any
  audit table) are refused even if added to it. Naming any other table with
  `--table` exits with code 2 and changes nothing.
- Exit codes: 0 success; 1 one or more tables failed (the others were still
  pruned; the report lists each error); 2 refused table, bad argument or missing
  database configuration.
- Expired rows are never served, so pruning frees space but does not change
  what the backend returns. To schedule it, run the command from your own
  scheduler; the repository does not schedule it.

Guidance:

- Most provider-cache tables never expire, so the cache grows. Prune the
  expiring tables with the command in 7.1; size the rest with metadata. MySQL:
  `SELECT table_name, ROUND((data_length + index_length) / 1048576, 1) AS size_mb FROM information_schema.tables WHERE table_schema = '<database>' ORDER BY size_mb DESC`.
  SQLite: `ls -l` on the file (include any `-wal` file).
- To reclaim more provider-cache space, drop or truncate individual public
  non-expiring tables after a backup, or recreate the database and let it
  refill. Do not truncate operator tables to save space.
- Change snapshot history by changing the `techtrade.prune_snapshots`
  `keep_sessions` parameter in the OpenBB jobs configuration. Pruning removes
  history you may not be able to regenerate, so back up first.
- Keep at least the most recent operator-data backup from before any upgrade
  that changes a schema.
- Keep the public-cache dump only as long as it saves more API quota than it
  costs in storage; it is optional.

## 8. Checklist

- [ ] Backend and other writers stopped, or an online-consistent method used
- [ ] Public and operator data backed up separately, outside the repository
- [ ] Operator backups are owner-only and, where shared, encrypted
- [ ] No real rows were printed during the procedure
- [ ] Restore verified with `serve status`, the manifest validator, the
      hermetic probe and metadata-only store checks
