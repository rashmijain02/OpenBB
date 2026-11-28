# Plan: qualify the isolated Nautilus runtime and data catalog (#1355, HFP-P15)

Status: **design draft, not committed.** Base `origin/portfolio` @ `75f442402`. Parent #1329 (HFP-F07).
Dependencies: HFP-P01 (#1338, in flight) and SOURCES-PINNED (Nautilus pin = **decision L1 below**).
Design sources: `docs/Specs/gh-1312-hermes-financial-planning/` spec.md §9.1 (BT-01, BT-02), plan.md §3.1–3.3,
§12, §14; research.md "NautilusTrader decision and migration evidence", S31–S34; github-plan/plan.md HFP-P15..P18.
No product code here. Synthetic data only, except the read-only market-data export in T02-L (no household data).

## 0. Existing assets (cited) and what P15 must not duplicate

| Asset | Fact | Consequence for P15 |
|---|---|---|
| `openbb_platform/extensions/backtest/openbb_backtest/adapters/__init__.py` | Only a docstring: "Optional, non-vendored external-engine adapters." | Home of the Nautilus-specific client (`adapters/nautilus/`, as plan.md §14 proposes). |
| Issue **#4** "Implement: optional non-vendored engine adapters" (open; design `docs/designs/backtest-design/11-adapters.md`) | Generic `EngineAdapter` protocol, `_optional.require()` lazy import guard, vectorbt/pybroker/backtrader/spectre adapters. github-preview.md:90 says HFP-P15/P16 cover "selected Nautilus qualification/integration only, not a competing generic framework". | P15 adds **no** generic adapter protocol, registry, plugin entry point or `require()` helper, and does **not** register an engine in `openbb_backtest/registry.py` (backend selection is P16-T02). Nautilus is never imported in the OpenBB process, so #4's lazy-import guard is irrelevant. |
| `openbb_backtest/data/bundle.py` | `Bundle` (look-ahead-safe `history`, atomic `save/load` with `safe_join`), `BundleIngestor`, `FmpCachedReader` (reads `equity_historical`, `calendar_splits`, `calendar_dividend` from fmp_cached MySQL), `compute_adj_factor` back-adjustment. `BundleMetadata` has **no content hash**. | P15 exports a content-addressed catalog **from a `Bundle`**; it does not add a second cache reader or download path. |
| `openbb_backtest/data/calendars.py` | `exchange_calendars` wrapper, default `XNYS` (venv has exchange_calendars 4.13.2). | Calendar check reuses it; records calendar code, library version and a sessions digest. |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py:1784` | `equity_historical` has `adjustment_type` (default `'splits_only'`), `is_filled`, `fill_type`. | **Finding:** `FmpCachedReader.equity_historical` filters only `interval_type='1d'`, not `adjustment_type`, and `build_ohlcv` then applies split factors again. Split-adjusted source + split factor = **double adjustment risk**, and mixed adjustment rows can co-exist. T02 fails closed on this; the reader fix is out of scope (file a `type-bug`, decision L6). |
| `openbb_backtest/engine/execution.py`, `models.py` (`BacktestResult.engine_used`, `BacktestConfig.engine`), `settings.py` (`bundle_root=.openbb_backtest/bundles`) | Decimal money path; engine names `auto|vector|event`. | Untouched in P15. Result projection is P16. |
| `tests/golden/fixtures/buy_and_hold.json` | Legacy-engine golden. | **Not** the oracle (spec §9.1: agreement is diagnostic). P15 adds an independent hand-computed case. |
| #1338 `hermes_integration/models.py` (`HealthLevel`, `FailedLayer`, `Presence`, `ComponentReport`, `PreflightReport`), `profile.py` (`FinanceRuntimeProfile`), `provenance.py` (`license_sha256`, `python_matches`, `read_pyvenv_version`) | Sibling worktree, unmerged; `openbb_agents` is not installed in `.venv_portfolio`. | Reuse, do not re-invent (§3.4). Dependency direction: `hermes_integration` → `openbb_backtest`, never the reverse. |
| Repo-wide search for `nautilus` | Only prose in `docs/Specs/Backtesting-Engine-PRD.md`, `docs/Tools/Quant-Strategies-Guide.md`. | Greenfield; no code to reconcile. |

## 1. Recommended pin (DECISION L1 for the lead; metadata only, nothing installed)

Evidence: PyPI JSON `pypi.org/pypi/nautilus_trader/json` read 2026-11-28; tag ref and `LICENSE` read via GitHub API/raw.

| Field | Recommendation | Evidence |
|---|---|---|
| Release | **`nautilus_trader==1.231.0`** (latest stable; uploaded 2026-08-02) | Newer files are only `2.0.0rc3..rc9` (rc9 2026-11-10, `Requires-Python >=3.13,<3.16`). plan.md §3.3 gate 1 forbids prereleases; research.md S32 says 2.x APIs differ. |
| Source tag | `v1.231.0` → tag object `d3e1685e979925d7b0ffacd1b3f442547686e18f` → commit `27a8e54e7ac3c57d6cbf8891f0283dfbaee97317` (`pin.yaml`: `source_commit` = commit, `source_tag_object` = tag object) | Matches research.md §9 table. Use docs from the tag (`docs/` at `v1.231.0`), never `latest` (2.x). |
| Licence | `LGPL-3.0-or-later` (PyPI `License`); `LICENSE` at tag sha256 `ee907919ec88c9c017b1f8b608db20960b6598aefcc4fe58820bde955d65ed3c` | Personal local use, unmodified wheel, separate process, not vendored or redistributed: no LGPL obligation is triggered, and LGPL-3 is compatible with the extension's `AGPL-3.0-only`. Obligations (source offer, notices, relinking) arise only on **conveying** (e.g. pushing a Docker image to a registry or committing the wheel); do neither. Bundled Rust/third-party notices in the wheel's `dist-info` are reviewed at T01-L. Extra `ib` (`nautilus-ibapi==10.45.1`, non-OSI IB API licence) and `betfair`/`polymarket`/`docker` extras are **excluded**. |
| Python ABI | **CPython 3.12, tag `cp312`**, in a **dedicated venv outside the repo** | Wheels exist for cp312/313/314 (`Requires-Python >=3.12,<3.15`). cp312 matches the extension's `>=3.10,<3.14` and `.venv_portfolio` (3.12) so a plain interpreter is easy to provision; Hermes' 3.14 is never reused (plan.md §3.3). Isolation still required: wheel pins `fsspec==2026.2.0`, `pyarrow>=25`, `pandas>=2.3.3,<4` (venv has pyarrow 26.0.1, pandas 3.1.0, but upgrades must not couple). |
| Native wheel (primary) | `nautilus_trader-1.231.0-cp312-cp312-win_amd64.whl` sha256 **`0697f51e9143f9d8d040f75d2e6a45218003cc34f7ea5b0eb2f9cda6935427de`** (112,750,098 B) | PyPI digest. |
| Container wheel (comparison) | `nautilus_trader-1.231.0-cp312-cp312-manylinux_2_35_x86_64.whl` sha256 **`8c438e95c275a13df0c0ddb7012c462708b5e99ff3612e36a1b7bd49ab39c216`** | Needs glibc ≥2.35 base (e.g. Ubuntu 22.04 / python:3.12-slim-bookworm has 2.36). Docker Desktop is installed on the host (not verified running). |
| Precision | **Native Windows = standard 64-bit (`HIGH_PRECISION=False`, `FIXED_PRECISION=9`)**; Linux wheel = high 128-bit (16 decimals) | Tag `docs/getting_started/installation.md`: "On Windows, only standard-precision (64-bit) Python wheels are available" (MSVC lacks `__int128`); Linux/macOS wheels ship high-precision. Runtime truth: `nautilus_trader.model.objects.HIGH_PRECISION` / `FIXED_PRECISION` (`objects.pyx:83-84` at the tag). |

**Recommendation:** select the **native Windows cp312 standard-precision** worker. Daily US-equity data has ≤6
source decimals (`DECIMAL(15,6)`), USD money 2 decimals and whole-share quantities, so 9 decimals is ample; standard
range (~9.2e9 for `Price`/`Money`) covers personal portfolios. The Linux container is qualified in T01 only as the
comparison and as the documented fallback if a later need (e.g. crypto 10+ decimals) requires 128-bit. Precision is
pinned per runtime, so a request declaring `precision_mode=high` is rejected by the native worker (acceptance 2).

## 2. Worker architecture (plan.md §3.1 diagram, §12 lifecycle "on-demand / idle-unloading")

- **Process boundary.** The OpenBB facade (`.venv_portfolio`) never imports `nautilus_trader`. It spawns the worker
  as a child process: native `"<worker-venv>\python.exe" -I -m openbb_nautilus_worker` or
  `docker run --rm -i --network none --read-only --cap-drop ALL --memory <M> --cpus <C> -v <catalog_root>:/catalog:ro
  -v <run_out>:/out <image@digest> `. Worker venv dir and image digest come from env vars named in the pin
  (`OPENBB_NAUTILUS_VENV`, `OPENBB_NAUTILUS_IMAGE`), never hard-coded paths.
- **Transport: stdio JSON lines, no listener.** No port to allocate or expose (satisfies §12 loopback rule trivially).
  Ops: `describe`, `build_catalog`, `run`, `shutdown`. Requests/responses are versioned pydantic models
  (`extra="forbid"`, `frozen`), max frame 1 MiB; bars never travel over IPC, only opaque `dataset_id` + sha256
  (plan.md §3.3 reviewer item 2).
- **Authentication.** Per-spawn 32-byte key generated by the parent, delivered as the first stdin frame (never argv or
  env, so not visible in process listings or `docker inspect`). Every later frame carries
  `hmac_sha256(key, canonical_json(body))` and a monotonically increasing `seq`; bad MAC / replay / missing key ⇒
  `failed_layer=auth`, worker exits. Containers inherit the same scheme.
- **Bounds.** Parent enforces wall-time (kill on deadline), one heavy job at a time (lock file under the run root),
  max symbols / sessions / request bytes from the pin; memory via `--memory` (container) or a Windows Job Object
  (`ctypes`, kill-on-close, memory limit) for native. Cancellation = kill; the durable job record (existing
  `story_adapters` jobs) observes the same job ID, retries never duplicate effects (no effects exist in P15).
- **Idle unload.** Worker exits after `idle_seconds` (default 120) without a request, or after `shutdown`; client
  restarts it lazily and re-runs `describe` on every spawn (provenance cannot go stale).
- **No broker access (T03).** Request schema has no venue/endpoint/credential fields; only venue `SIM`, `oms=NETTING`,
  `account=CASH`, `BacktestEngine` (never `TradingNode`/live clients). Worker installs a meta-path blocker for
  `nautilus_trader.adapters.*` live packages and `ibapi`, a socket guard that refuses non-loopback connects (same
  idea as #1339 `egress_guard.py`; local copy, the worker cannot import `openbb_agents`), and scans its own env for
  broker-credential-shaped names (`IB_*`, `TWS_*`, `*_API_KEY`, `*_SECRET`) → `Presence` only, any present ⇒ refuse.
  Container: `--network none`. Native: optional outbound Windows Firewall rule for the worker exe (LIVE, elevated, L4).
- **Paths.** Worker accepts only `dataset_id` (64 hex) resolved under its configured catalog root; it rejects absolute
  paths, `..`, drive letters, UNC, symlinks/junctions/reparse points, and any file whose sha256 differs from the
  manifest. Admission runs in the worker (authoritative) and in the client (fail-fast); both use one module.

Package layout (new):

```
openbb_platform/extensions/backtest/nautilus_worker/          # separate dist, installed only in the worker venv
  pyproject.toml                                               # deps: nautilus_trader==1.231.0, pydantic; no openbb imports
  pin.yaml                                                     # release, wheel sha per tag, python tag, precision, licence sha
  requirements-win_amd64-cp312.lock, requirements-linux_x86_64-cp312.lock   # pip --require-hashes
  Dockerfile                                                   # python:3.12-slim-bookworm@digest, non-root, no network at run
  openbb_nautilus_worker/
    protocol.py   admission.py   guards.py                     # pure: importable WITHOUT nautilus (facade imports these)
    describe.py   catalog_build.py   runs.py   __main__.py      # import nautilus lazily, inside functions
  tests/ (pure tests run in .venv_portfolio; @pytest.mark.requires_nautilus skipped unless importable)
openbb_platform/extensions/backtest/openbb_backtest/adapters/nautilus/
  __init__.py  pin.py  export.py  client.py  qualify.py  probe.py   # facade side; never imports nautilus_trader
openbb_platform/extensions/backtest/tests/unit/nautilus/            # facade tests (synthetic, network-denied)
```

## 3. Tasks

Common setup (PowerShell 7, worktree root):

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = "$((Resolve-Path openbb_platform\extensions\backtest).Path);$((Resolve-Path openbb_platform\extensions\backtest\nautilus_worker).Path)"
$U = 'openbb_platform/extensions/backtest/tests/unit/nautilus'; $W = 'openbb_platform/extensions/backtest/nautilus_worker/tests'
& $py -m black --check openbb_platform/extensions/backtest ; & $py -m ruff check openbb_platform/extensions/backtest
```

Acceptance map: **A1** = "worker ABI, precision, calendar and catalog hashes are recorded and accepted transformations
reproduce"; **A2** = "arbitrary paths, wrong hashes, incompatible precision or a broker endpoint ⇒ admission rejects".

### T01 — compare native and container runtimes with pinned wheel/licence/precision evidence

Goal: a committed pin + hash-locked requirements, a `describe` op, and a `qualify` CLI that turns worker facts into a
pass/fail report for each runtime. Files: `nautilus_worker/{pin.yaml,requirements-*.lock,Dockerfile,pyproject.toml}`,
`openbb_nautilus_worker/{protocol.py,describe.py,__main__.py}`, `adapters/nautilus/{pin.py,client.py,qualify.py}`.

Red-first tests (CODE-ONLY, fake worker = a tiny stdio script under `tests/fixtures/` emitting canned `describe` frames):
- `test_pin_loads_and_rejects_unknown_keys` / `test_pin_requires_hash_per_platform_tag` (pin schema; A1).
- `test_lock_files_pin_nautilus_hash_matches_pin_yaml` (lock line `--hash=sha256:0697f5...` equals pin; A1).
- `test_lock_files_exclude_broker_extras` (no `nautilus-ibapi`, `ibapi`, `py-clob-client`, `betfair-parser`; A2).
- `test_qualify_records_abi_precision_license` (report fields: python `3.12.x`, tag `cp312-win_amd64`, version,
  `HIGH_PRECISION`, `FIXED_PRECISION`, licence sha; A1).
- `test_qualify_rejects_wrong_python_minor` (cp313 facts ⇒ `failed_layer=abi`), `test_qualify_rejects_precision_mismatch`
  (pin `standard`, worker reports high ⇒ `abi`), `test_qualify_rejects_wrong_version_or_dist_hash` (⇒ `module_origin`) (A2).
- `test_describe_contract_matches_nautilus_names` (`requires_nautilus`; seam-contract test, CLAUDE.md Testing rule 4:
  the attribute names `describe.py` reads exist in the installed release).

Focused: `& $py -m pytest $U/test_pin.py $U/test_qualify.py $W/test_protocol.py -q -m "not requires_nautilus"`
Real-path (replaces "Not yet qualified"; LIVE after L1/L2):
`& $py -m openbb_backtest.adapters.nautilus.qualify --runtime native --format json` then `--runtime docker`.
Expect exit 0 and, for native, `nautilus_trader 1.231.0 / cp312-win_amd64 / HIGH_PRECISION=false / FIXED_PRECISION=9`;
for docker, `manylinux_2_35_x86_64 / HIGH_PRECISION=true`. Evidence also includes
`& "$env:OPENBB_NAUTILUS_VENV\Scripts\python.exe" -I -m pip install --require-hashes --no-deps -r <lock>` output and the
licence files listed in the installed `dist-info` (names + sha256 only).
Classification: code **CODE-ONLY**; venv/image creation and install **LIVE**; pin choice **NEEDS-OWNER-DECISION** (L1, L2).

### T02 — cache-derived data to content-addressed catalogs with action basis and calendar checks

Goal: deterministic two-stage export. Stage 1 (facade, no nautilus): `Bundle` → canonical "neutral" dataset
(sorted Parquet, fixed Arrow schema, `price` as scaled int64 + declared decimals, UTC `ts_event` = session close from
`exchange_calendars` incl. half-days, `ts_init = ts_event`) + `manifest.json` {schema/transform version, symbols,
calendar code + `exchange_calendars` version + sessions sha256, `action_basis`, per-instrument price precision,
currency USD, source provenance (db name, query fingerprint, row counts; never rows), per-file sha256}.
`dataset_id = sha256(canonical manifest)`; directory name = id; written atomically via `safe_join` like `Bundle.save`.
Stage 2 (worker): verify every hash, then write a Nautilus `ParquetDataCatalog` (`Equity` instruments, venue `SIM`,
`BarType <SYM>.SIM-1-DAY-LAST-EXTERNAL`) and record `catalog_sha256` over its files plus the nautilus version.
`action_basis` ∈ {`raw_plus_actions` (recommended: `unadjusted` prices + explicit split/dividend events, no factor
applied), `split_adjusted_source`}; `back_adjusted` is rejected (dividend back-adjustment is not tradeable price).
Files: `adapters/nautilus/export.py`, `openbb_nautilus_worker/catalog_build.py`, tests + fixture
`tests/unit/nautilus/fixtures/synthetic_bundle/` (3 symbols, 1 split, 1 dividend, 1 half-day, 1 holiday).

Red-first tests:
- `test_export_is_byte_reproducible` (two exports ⇒ identical `dataset_id` and file hashes; A1 "transformations reproduce").
- `test_manifest_records_calendar_version_and_sessions_digest`; `test_rejects_missing_or_extra_sessions` (A1).
- `test_half_day_close_timestamp_is_1300_new_york_in_utc`; `test_dst_transition_close_utc` (A1 calendar).
- `test_rejects_double_adjustment` (source rows `adjustment_type='splits_only'` + `action_basis=raw_plus_actions` ⇒
  error; mixed `adjustment_type` values ⇒ error) (A1/A2).
- `test_rejects_precision_beyond_source_or_worker` (values with 7+ decimals, or decimals > `FIXED_PRECISION`; A2).
- `test_dataset_id_changes_when_any_input_changes` (mutation guard against a vacuous hash).
- `test_worker_catalog_build_round_trip` (`requires_nautilus`: bars read back from `ParquetDataCatalog` equal the
  neutral values exactly; catalog hash stable over two builds).

Focused: `& $py -m pytest $U/test_export.py $W/test_catalog_admission.py -q -m "not requires_nautilus"`
Real-path (LIVE, read-only on `openbb_fmp_cache_test`, market data only):
`& $py -m openbb_backtest.adapters.nautilus.export --symbols AAPL,MSFT --start 2024-01-02 --end 2024-12-31 --basis raw_plus_actions --adjustment unadjusted --format json`
run twice ⇒ same `dataset_id`; output prints counts and hashes only. If `unadjusted` rows are absent from the cache
the command must exit non-zero with a named gap (provider rule: file `area:fmp-cached-gap`, no raw `fmp`).
Classification: stage 1 + admission **CODE-ONLY**; stage 2 and the live export **LIVE**.
Code-only real path (no database): the same command with `--snapshot-dir
openbb_platform/extensions/backtest/tests/unit/nautilus/fixtures/synthetic_bundle --out-root <tmp>` run twice gives the
same `dataset_id`; a snapshot whose AAA rows switch to `splits_only` exits 2 with `mixed_adjustment_basis`, and
`--adjustment splits_only` with `raw_plus_actions` exits 2 with `double_adjustment`.
T02-L stage 2 (LIVE, worker venv): set `OPENBB_NAUTILUS_DATA_ROOT` (outside the repo; datasets under `datasets/<id>`),
then send `build_catalog {"dataset_id": "<id>"}` through the signed client (T03 `probe`) twice. Expect identical
`catalog_sha256`, `nautilus_version` 1.231.0, and `pytest $W/test_catalog_admission.py -m requires_nautilus` green
in the worker venv (`test_worker_catalog_build_round_trip`: bars read back equal the neutral values). Record the
dataset id, catalog hash and nautilus version on #1355. Split/dividend events stay in the neutral `actions.parquet`;
the catalog holds instruments and bars only.

### T03 — authenticated worker bounds; no broker credentials or order-network permissions

Goal: admission + guards + bounds per §2, and the provenance/preflight wiring into #1338's model.
Files: `openbb_nautilus_worker/{admission.py,guards.py,runs.py}`, `adapters/nautilus/{client.py,probe.py}`; after #1338
merges: `openbb_agents/hermes_integration/nautilus_component.py` (builds a `ComponentReport` from `describe` facts) and an
optional `nautilus: NautilusPin | None` field on `FinanceRuntimeProfile`.

Red-first tests (A2 unless noted):
- `test_rejects_absolute_dotdot_unc_drive_and_symlink_paths`; `test_rejects_unknown_dataset_id`;
  `test_rejects_file_hash_mismatch` (tamper one byte of a fixture copy in `tmp_path`).
- `test_rejects_precision_mode_mismatch` (request `high` to standard worker ⇒ `abi`).
- `test_request_schema_forbids_venue_endpoint_and_credentials` (`extra="forbid"`; any URL/host/port value, any venue
  other than `SIM`, `TradingNode`/live config ⇒ reject); `test_env_with_broker_credentials_is_refused` (names only,
  `Presence`; sentinel values never appear in output); `test_live_adapter_imports_blocked`;
  `test_socket_guard_refuses_non_loopback`.
- `test_bad_hmac_replay_and_missing_key_rejected` (⇒ `auth`); `test_wall_time_kill_and_idle_exit`;
  `test_concurrency_lock_serializes_jobs`; `test_oversize_frame_rejected`.
- `test_failure_codes_are_failed_layer_values` (`importorskip("openbb_agents")`: every worker error code is a
  `FailedLayer` value; runs once #1338 is on `portfolio`).
- `test_buy_and_hold_independent_case` (`requires_nautilus`; A1 + issue Verification): synthetic 1 symbol, 5 sessions,
  cash 10,000.00 USD, buy at first close 100.00, zero fees ⇒ 100 shares, cash 0.00, final equity = 100 × last close;
  expected values hand-computed in the test, not taken from `golden/fixtures/buy_and_hold.json`.

Focused: `& $py -m pytest $U/test_client_bounds.py $W/test_admission.py $W/test_guards.py -q -m "not requires_nautilus"`
Real-path (LIVE): `& $py -m openbb_backtest.adapters.nautilus.probe --runtime native --admission-matrix --format json`
⇒ every negative case blocked with its layer, then
`& $py -m openbb_backtest.adapters.nautilus.probe --runtime native --run buy_and_hold --dataset <id from T02-L>`
⇒ exit 0, report with engine version, precision, dataset/catalog hashes; output piped through the #1339 sentinel
scanner when available. Preflight (after #1338): `python -m openbb_agents.hermes_integration.hermes_preflight
--profile <profile with nautilus pin> --format json` shows component `nautilus_worker` level `qualified`.
Classification: admission/guards/bounds **CODE-ONLY**; firewall rule and real-worker matrix **LIVE**; preflight
wiring **CODE-ONLY but blocked on #1338 merge**.

## 4. Ordering vs #1338, and PR batching

```
T01-code (pin, locks, protocol, describe, qualify w/ fake worker) ─┐
T02-code (stage-1 export, manifest, admission of datasets)          ├─ start NOW, no openbb_agents import
T03-code (admission, guards, HMAC framing, bounds, client)         ─┘
#1338 merges ─> T03-wiring (nautilus_component.py, profile field, FailedLayer parity test)
L1/L2 decisions ─> T01-L (venv + image) ─> T02-L (catalog build, live export) ─> T03-L (matrix + buy-and-hold)
```

All CODE-ONLY parts of T01–T03 can start before #1338 merges: they live under `extensions/backtest/` and use local
string error codes equal to `FailedLayer` values (`abi`, `module_origin`, `auth`, `schema`, `egress`, `config`), with
the parity test skipped until `openbb_agents` is importable.

| PR | Content | Gates |
|---|---|---|
| A `feat/hfp-nautilus-runtime-gh-1355` | T01–T03 code + fake-worker fixtures; `Refs #1355` (not `Closes`: LIVE acceptance pending) | focused pytest, black/ruff, codespell on docs, `/code-review` + `/security-review` + `local-privacy-review`, code-only real-path (`qualify`/`probe` against the fake worker, exit 2 expected for a mismatched fixture) |
| B (small, after #1338 PR A merges; may batch with #1339's PR B or P16's first PR) | T03 wiring in `hermes_integration` | same + local CI on the merged tip (`test-unit-platform`, `general-linting` until `scripts/local_ci.py` lands) |
| LIVE | T01-L..T03-L evidence posted on #1355 by the lead/owner | issue closes after both acceptance bullets are proven on the real worker; then update the issue's Command field |

## 5. Risks

1. **Double adjustment** in the existing reader (§0 finding); mitigated by fail-closed `action_basis` checks; real fix
   is a separate bug.
2. 1.x may stop receiving fixes once 2.0 is final; catalog format/APIs differ in 2.x. The pin is per-release with
   manifest `transform_version`; a re-pin rebuilds catalogs and reruns T01–T03.
3. Standard precision on Windows: overflow above ~9.2e9 in `Money`/`Price`; admission rejects out-of-range values.
4. Parquet bytes depend on the pyarrow writer version; `dataset_id` is computed over canonical content and the
   writer version is recorded, so a pyarrow upgrade changes file hashes but not the content digest (tested).
5. Native worker has no OS network sandbox without an elevated firewall rule; the in-process socket guard is
   defence-in-depth, not proof (container `--network none` is the stronger proof).
6. Daily bars cannot establish intrabar order or liquidity (spec §9.1); P15 only runs buy-and-hold at close.

## 6. Decisions needed (recommended answers)

| # | Question | Recommendation |
|---|---|---|
| L1 | SOURCES-PINNED for Nautilus | `nautilus_trader==1.231.0`, tag `d3e1685e`, cp312; win_amd64 sha `0697f51e...27de`, manylinux_2_35_x86_64 sha `8c438e95...c216`. No 2.0 rc. |
| L2 | Selected runtime | Native Windows cp312 standard precision; Linux container qualified as comparison/fallback only. Approve creating a worker venv outside the repo and building a local, never-pushed image. |
| L3 | Transport | stdio JSON lines + per-spawn HMAC key; no TCP listener. |
| L4 | Elevated outbound firewall block for the native worker exe | Yes, owner-run via the live-acceptance template; otherwise record the gap. |
| L5 | `FailedLayer` vocabulary | Reuse as is: precision ⇒ `abi`, wrong hash/path ⇒ `schema`, broker credentials/endpoint ⇒ `egress`; no new enum members in #1338. |
| L6 | Reader `adjustment_type` gap | File a `type-bug` issue for `FmpCachedReader`; P15 only fails closed. |
| L7 | Action basis | `raw_plus_actions` from `adjustment_type='unadjusted'` rows; if the cache lacks them, record an `area:fmp-cached-gap` and use `split_adjusted_source` with splits disabled for the P15 verification only. |
| L8 | Worker locations | Venv `%LOCALAPPDATA%\openbb\nautilus\1.231.0-cp312`, catalog root and run outputs under a sibling `data` dir, all via env vars; nothing under the repo. |

## Lead decisions (2026-11-28, under the owner's delegation)

| # | Decision |
|---|---|
| L1 | Pin `nautilus_trader==1.231.0` (tag `v1.231.0`, `d3e1685e`) on CPython 3.12, with the wheel hashes in §3. No broker extras. |
| L2 | The selected runtime is the native Windows cp312 standard-precision worker, in a venv outside the repo. The Linux container is qualified only for comparison and as a fallback; its image is local and never pushed. |
| L3 | Transport is stdin/stdout with per-launch signing and no network listener. |
| L4 | The elevated outbound firewall block is a LIVE owner step. |
| L5 | Keep `FailedLayer` unchanged, with the mapping in §6. |
| L6 | Filed as #1385 (FmpCachedReader ignores adjustment_type). T02 rejects the double-adjusted case until #1385 is fixed. |
| L7 | Accepted as recommended. |
| L8 | Accepted: all locations come from environment variables and are outside the repo. |

The wheel and image are never committed or distributed (LGPL-3.0-or-later).
