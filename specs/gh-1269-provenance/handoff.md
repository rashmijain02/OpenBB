# Handoff: Normalize provenance and provider-state behavior

| Field | Value |
|---|---|
| Parent issue | #1264 ([portfolio-ux][PROGRAM] Make Portfolio Intelligence a native OpenBB Workspace terminal) |
| Sub-issues | #1269 ([portfolio-ux] Normalize provenance and provider-state behavior) |
| Branch | `feat/pi-provenance-gh-1269` |
| Base | `portfolio` @ `e77c6abd1` |
| HEAD | `e77c6abd1` (changes uncommitted; the lead commits) |
| Worktree | `.worktrees/pi-provenance-gh-1269` |
| Executor model | `claude-opus-5.5` (implementer subagent; route mode, plan Step 6) |

## What changed

- **One model:** new `widget_backend/provenance.py`. `DataState` = live, cached, demo, stale,
  partial, unavailable, forbidden. `Provenance(state, source, reason, as_of)`. A per-request
  record (context variable, bound by the middleware, shared with the worker thread) collects the
  serving tier (`record_tier_used`), explicit `mark(...)` calls and the final record. `resolve()`
  never defaults: no tier, mark, demo reason or local source raises.
- **Per widget type** (all inside the Workspace schema):

| Type | Representation |
|---|---|
| chart | `layout.meta = {state, source, asOf, reason}`; every non-live state also gets an annotation |
| table, and `raw=true` chart rows | `data_state`, `data_source`, `data_as_of` string columns on every row |
| metric | trailing `{"label": "Data State", "value": "<State>: <reason>"}` card (text unchanged from #1268) |
| markdown | closing `**Data state:** <State> - <reason>. Source: ...; as of ....` line |

  Table choice: Workspace's table contract is "array of row objects" (`backend-contract.md`), and
  `terminalpro/.../AgGridUtils.tsx#getColumnDefs` builds a column for every row key (`columnsDefs`
  only labels and orders), so per-row columns are the only schema-valid carrier that both the grid
  and the agent ("reads the rows directly", `ai-agent-contract.md`) see. They are always strings, so
  raw rows stay type-stable; existing keys and JSON number types are unchanged. The 18 tables with
  `columnsDefs` declare the three columns last.
- **Headers:** `X-PI-Data-State`, `X-PI-Data-Source`, `X-PI-Data-As-Of` come from the per-request
  record, not the shared `_TIER_IN_USE` ledger. A 401/403 sends `X-PI-Data-State: forbidden` and no
  source or data.
- **States per endpoint:** with_chain tier -> live (as-of `unknown`; tiers report none), stub ->
  demo; non-demo accounts -> unavailable (15 widgets); empty rows -> unavailable (no more `empty`);
  EOD snapshot widgets -> unavailable / partial / stale / cached from `_snapshot_meta`
  (`as_of_session`); provider health -> live / cached (TTL entry time) / unavailable (all probes
  unknown); backend-local markdown (context bar, engine status, bridge, paper status) -> live, as of
  `request time`; resolved non-demo basket -> unavailable (zero placeholders); invalid What-If
  input -> unavailable. The provenance strip's "Data mode" uses the same `state_for_tier`.
- **Pie hover:** weight pies show the stored weight and the plotted share; weights not summing to
  the whole (X-Ray sector/country, ownership vs 100%) are `partial` in figure, raw rows and header.
- **Contract checks:** `collect_response_issues` adds `response.state.{table,chart,annotation,
  metric,markdown}`; the hermetic probe also captures the headers and a new test checks that they
  match the body for all 61 widgets. No debt entries added.
- `metric_cards(values, available=...)` no longer takes `state`; the decorator appends the card.
- `/pi/xray/sector` and `/pi/attribution` now use `plotly_chart` like the Terminal charts.

## Consumers found and how each keeps working

| Consumer | Handling |
|---|---|
| Local Viewer `index.html` (`X-PI-Data-Source` badge, Data State card, figure meta) | Header and card unchanged; extra row columns render as columns. No code change. 113/113 node tests. |
| MCP adapter (`adapters/portfolio_intel.py` clones routes; the backend middleware does not run there) | State is in every body (rows, card, meta, markdown), so MCP tools see it. 66 passed (MCP + harness). |
| Browser harness fixtures | 35 deterministic fixtures re-recorded in-process (tiers cleared, temp HOME); re-check reports 0 drift. |
| `native_workspace_matrix.json` | Regenerated with `scripts/build_portfolio_workspace_matrix.py` (column additions only). |
| Row/column tests in 9 files (#1267, #1268, tier1, tier_calls, batch, price_history, terminology, f2, endpoint contracts) | Strip and separately assert the provenance columns; `empty` -> `unavailable`; `Data mode: Live`. |

## Evidence

- **Red first:** new `test_provenance_contracts_1269.py` with `provenance.py` absent -> `48 failed`;
  the concurrency test fails on the old middleware with `assert 'fmp_cached' == 'stub'` (3/3 runs).
  Probe enforcement against the pre-fix endpoints -> `44 failed, 17 passed`.
- **Mutation:** 17/17 killed (`.dev-cycle/mutation-gh-1269.log`): ledger header, forbidden,
  four checker rules, raw stamping, partial weights, pie hover, unwired mark, stale->cached,
  silent resolve default, snapshot tier, table/markdown decorators, provenance strip, health.
- **Full unit:** `python -m pytest openbb_platform/extensions/portfolio_intel/tests/unit -q -p no:cacheprovider`
  -> `1930 passed, 2 skipped in 987.07s`, exit 0.
- **Viewer** 113 passed; **harness non-live + MCP** 66 passed, 3 skipped;
  `scripts/validate_portfolio_workspace_manifests.py` exit 0 (5 recorded debt).
- **CI lint parity** (changed non-test `.py`, CI commands): codespell 0, black 0, pylint 10.00/10,
  ruff 0; mypy 5 errors, all pre-existing lines in `widgets_endpoints.py` (1258, 3782, 3881, 4558)
  and `_app.py:87`, caused by locally installed `openbb` / paper-engine packages. CI installs only
  devtools, so they resolve to `Any` there (#1268 merged with the same lines). Not suppressed.
- **Real path** (`.dev-cycle/realpath-gh-1269.log`): 61 widgets, all 200; states live 5, demo 45,
  unavailable 11; only the three recorded #1271 shape-debt widgets have issues.
- **Claude review gate:** not run by the implementer; the lead owns it.

## Round 2: lead decisions, plan Step 6.3 (demo mode) and 6.6 (redaction)

### What changed

- **`fmp_cached` is `cached`.** `state_for_tier`: `stub` -> demo, `none` -> unavailable,
  `*cached*` / `*snapshot*` -> cached, any other tier (`fmp`, `sec`, `cboe`) -> live. As-of stays
  `unknown`. The provenance strip's "Data mode" now says `Cached` for `fmp_cached`.
- **Real as-of for backend-local state:** UTC ISO-8601 (`now_iso()`), no literal. Harness fixtures
  stay deterministic through `openbb_browser_test_harness/normalize.py`, which tokenizes only
  `data_as_of`, `layout.meta.asOf` and the Markdown `as of <ts>.` clause, and only when the value
  is a timestamp. The recorder (`snapshot.py`) and the drift check (`test_fixtures_are_current.py`)
  both use it.
- **Tables:** `data_state` visible; `data_source` and `data_as_of` are `hide: true` column defs with
  a `headerTooltip` on the 18 tables that already had `columnsDefs` (none added elsewhere). The
  Local Viewer honours `hide` and has two new glossary records for the tooltips.
- **Demo mode (6.3), `PI_DEMO_MODE`:** `fallback` is the default (lead decision, round 3): the
  labelled stub fallback, state `demo`. `off` (opt-in) means no synthetic fallback. With no
  provider answer, a widget is `unavailable` (source `none`): a table returns one
  `{"message": "Unavailable: ..."}` row, Markdown says `**Unavailable:**`, a metric shows
  `Status: Unavailable`, a chart has no traces, and `raw=true` returns the marker row.
  `account_id=demo` / `basket_id=demo` or an explicit `mark(DEMO)` is an explicit selection and
  still shows the labelled demo book. `fallback` is the old labelled stub fallback. `only` skips
  provider tiers in `retrofit.route_through_chain`. Unknown values raise. The unit `conftest.py`,
  the hermetic probe and the harness `StandaloneDriver` select `fallback` explicitly.
  `collect_response_issues` does not require data columns when every row is `unavailable`.
- **Redaction (6.6):** responses no longer echo a non-demo account id (`_shared.account_display`:
  book context, paper ticket, backtest); the basket 403/404 details drop `basket_id`; the
  unwired-account warnings no longer log the id.

### Evidence (round 2)

- **Red first** (`.dev-cycle/red2-gh-1269.log`): 15 failed (demo mode x8, redaction x2, cached x3,
  real as-of x1, hidden columns x1); the harness normalizer test failed collection (module
  missing); the viewer had 2 failures (hide filter, tooltip count).
- **Mutation** (`.dev-cycle/mutation2-gh-1269.log`): 14 of 15 killed (fmp_cached live, literal as-of,
  default fallback, gate off, explicit account ignored, unknown mode accepted, only mode calls
  providers, chart gate off, account echoed in body, account echoed in log, marker table needs data
  columns, normalizer skips `data_as_of`, normalizer rewrites non-timestamps, viewer ignores
  `hide`). One equivalent mutant: adding `data_state` to the normalizer keys changes nothing,
  because the timestamp guard already blocks non-timestamp values.
- **Full unit:** `1946 passed, 1 failed, 2 skipped`. The failure was the new glossary `source` host
  (not in the curated allow-list); after moving it to `en.wikipedia.org`,
  `test_pi_terminal_terminology_1987.py` -> 40 passed and the viewer -> 114 passed. That URL was
  the only change after the full run.
- **Harness non-live + MCP:** 70 passed, 3 skipped (with and without `PI_DEMO_MODE`). **Manifest
  validator:** exit 0 (5 recorded debt). **Fixtures:** re-recorded (normalized), 0 drift.
- **Real path, 61 widgets:** off -> live 5, demo 18, unavailable 38; fallback and only -> live 5,
  demo 45, unavailable 11. In each mode only the three #1271 shape-debt widgets have issues.
- **CI lint parity:** codespell, black and ruff clean; pylint 10.00/10. mypy with the local
  site-packages reports the 5 untouched-line errors plus `account_display` (it resolves the main
  checkout's installed package); with `--no-site-packages` (as CI, devtools only) there are 0 issues.

### Open questions for the lead (round 2)

- TechTrade's snapshot store logs its absolute SQLite fallback path (home directory), and
  `techtrade/tests/unit/test_snapshot_store.py` requires that absolute path. The redaction test
  checks that logger separately (no account or credential), and every other log line is fully
  checked. Should TechTrade redact the home prefix (and change its tests), or should a backend log
  filter do it?
- Production `uvicorn` access logs include query strings (`account_id=...`). Not covered by the
  in-process test; disable or redact the access log in deployment?
- (Round 3: the lead set the default to `fallback`; the TechTrade store path log and the uvicorn
  access-log query strings moved to follow-ups.)

## Round 4: review fixes

- Basket 404 returns a fixed message (no basket/user id, no snapshot id); the 400 for a malformed
  `basket_id` no longer reflects the value (fixture `IV.basket-consensus-xss` re-recorded).
- `/tt/execute/paper-status/markdown` shows the paper account through `account_display()`.
- `PI_DEMO_MODE` is validated when `_app` is imported (app creation) and again at lifespan
  startup; the per-call guard stays.
- Red first: 6 failed (`.dev-cycle/red4-gh-1269.log`). Mutation: 5/5 killed
  (`.dev-cycle/mutation4-gh-1269.log`). Full unit: 1953 passed, 2 skipped. Viewer 114 passed;
  harness non-live + MCP 70 passed, 3 skipped; fixture drift 0; 61-widget probe (default mode):
  all 200, issues only on the three #1271 widgets; CI lint parity clean (mypy without
  site-packages: 0 issues).

## Open questions for the lead

- (Round 1 questions on `fmp_cached`, as-of and column width were decided by the lead; see Round 2.)

## Not done / follow-ups

- TechTrade snapshot store logs its absolute SQLite fallback path (operator home directory), and
  its own tests require that path; the #1269 redaction test checks that logger only for account
  ids and credentials. Routed by the lead to #1271.
- Production `uvicorn` access logs include query strings (`account_id=...`), which the in-process
  redaction test does not cover. Routed by the lead to #1273.

- Not verified in a real self-hosted Workspace browser render; live harness drift not run.
- #1271 shape-debt widgets get headers but no body state until #1271 makes them valid shapes.
