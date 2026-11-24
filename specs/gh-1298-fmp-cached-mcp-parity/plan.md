# Plan: `fmp_cached` MCP server with hosted-FMP parity

Status: **G1 approved 2026-11-24** (recommended answers to Q1–Q10 accepted). Inputs: `spec.md`, `mapping-matrix.md` (208 rows),
`openbb_platform/extensions/fmp_cached_mcp/tests/fixtures/hosted/inventory-2026-11-23.json`.
Base: `origin/portfolio` @ `041f292ea` (#1292/#1293 merged). MySQL on 127.0.0.1:3306 was **down**
on 2026-11-23 (port check only). `scripts/local_ci.py` is **not on `portfolio` yet** (#1274 open).

## 1. What is already supported (answer to "how much exists")

| Status (vs. hosted contract) | n | Meaning |
|---|---|---|
| covered | 17 | `fmp_cached` fetcher hits the same FMP path and caches it |
| partial | 152 | a fetcher hits the path but stores nothing, a write-only copy, or normalised columns only |
| missing | 17 | no fetcher at all |
| not-cacheable | 22 | real-time quotes/aftermarket (9 `quote`), index/commodity/crypto/forex quotes (8), custom DCF (2), live snapshots (3) |
| **total** | **208** | 24 tools |

Stricter test — *can the hosted `content` be reproduced from MySQL today?* Only **8 endpoints**:
income / balance / cash-flow statements, key-metrics, metrics-ratios, profile-symbol, peers,
exchange-market-hours store raw FMP JSON and read it back. The other 9 "covered" (EOD + intraday
charts) store normalised columns with synthetic gap-fill rows, so raw shape is lost.
**Effective parity from cache today: 8 / 208 (≈4%).** There is no MCP server with the hosted tool
names; today's MCP exposure is 112 `fmp_cached_<command>` tools (OpenBB shapes, one tool per route).

Other facts that shape the plan:
- TTLs are hard-coded per reader (1 d statements/metrics, 7 d profile/peers, 300 s quote, 60 s
  aftermarket, 1 d market hours); everything else never expires. `CACHE_EXPIRY_RULES`
  (`cache_schema.py:6059`) mirrors them for `cache_prune`.
- `plan_limited._PLAN_LIMITED` has 57 entries keyed by **OpenBB model name**, not FMP path, and is not
  consulted at runtime. Hosted endpoints affected: `most-active`, `cryptocurrency-list`, `sp-500`
  (+`financials-latest`, unconfirmed).
- Bug found: statement caches are keyed by symbol only and `replace_rows` deletes the symbol's whole
  history (`utils/database.py:367`), so annual/quarter calls evict each other and a hit may return
  fewer rows than `limit`. → separate `area:fmp-cached-gap` / bug issue.
- Intraday gap detection uses equity calendars for 24 h assets (crypto/forex) → wrong fills.

Conclusion: reusing the typed fetchers cannot give byte/JSON parity for most endpoints. The hosted
server is a thin proxy to `/stable/*` that returns the REST JSON compactly re-serialised, so the
parity-preserving design is a **persistent raw-JSON store** (row-level for series and feeds, response-level for documents), with a TTL only for ephemeral data (§4).

## 2. Architecture options

| | (a) adapter in `mcp_server` | (b) standalone server package (**recommended**) | (c) proxy misses to hosted MCP |
|---|---|---|---|
| Parity fidelity | Low–medium. `FastMCP.from_fastapi` derives `inputSchema`/descriptions from FastAPI routes; exact draft-07 schema, `additionalProperties:false`, annotations, `execution`, and zod-style error text are hard to force | **High.** Low-level `mcp` server (`mcp==1.30.0`, already locked) serves the recorded `tools/list` verbatim and owns error text | High for payloads (hosted produces them), but we inherit its session/latency and can't cache what we don't parse |
| Reuse of OpenBB fetchers / provenance | Highest on paper, but fetchers return OBBject shapes, not raw | Reuses `fmp_cached` DB layer, `cache_schema`, `cache_prune`, `plan_limited`, `pi_fmp_record` conventions; `DataState` vocabulary. Typed tables used only where raw is stored (8) | Little reuse; second cache semantics |
| Auth | Inherits `server_auth`/`TokenAuthProvider`, portfolio transport checks | Reuses `openbb_mcp_server.app.auth` token provider + same loopback rule | Our key goes to hosted MCP; same as today |
| MCP-inventory CI impact | Touches `capability_policy.json`, profiles, Portfolio inventory diff, replay — every PR perturbs the Portfolio MCP gates | **None on Portfolio inventories.** Adds its own parity contract job. Dual MCP locks unchanged (no new deps) | Same as (b) plus network-dependent tests |
| Workspace contract | Would add 24 tools to Portfolio MCP profiles (name clash risk: `search`, `news`, `quote`) | Separate server/port (default `127.0.0.1:8011`), registered as its own MCP entry; Workspace contract tests untouched | Same as (b) |

**Recommendation: (b)**, as package `openbb_platform/extensions/fmp_cached_mcp/`
(`openbb_fmp_cached_mcp`), with a pluggable *upstream* interface whose default is FMP REST
`/stable/*` (so misses use our key directly, no hosted dependency) and an optional
`HostedMcpUpstream` used **only** in the parity/shadow test harness (and as an owner-selectable
fallback, see Q2). Read path: (1) the persistent raw store, according to retention class → (2) a one-off warm start from the 8 typed raw tables → (3) FMP for the missing part only.

Endpoint → REST path map: one checked-in table (`endpoint_map.json`) of
`{tool, endpoint, path, param_renames (from_date→from, to_date→to), ttl_class, plan_limited_key}`,
generated from the recorded inventory + the matrix and verified by recording (Phase 2).

## 3. Response contract

- **Success**: `content=[{"type":"text","text": json.dumps(body, separators=(",",":"), ensure_ascii=False)}]`
  where `body` is the FMP JSON as received (key order preserved). Parity is asserted as JSON
  equality plus the compact-serialisation rule; byte equality is checked on recorded fixtures.
  Non-JSON bodies (10-K xlsx) are passed through as hosted does (exact encoding recorded in Phase 2).
- **Validation errors**: reproduce `MCP error -32602: Input validation error: Invalid arguments for
  tool <tool>: <zod issues JSON>` with `isError:true`. We generate the zod issue array from the
  JSON-Schema validator; the contract test compares recorded hosted error fixtures for enum, type
  and unknown-key cases.
- **Upstream errors**: `Bad request for tool "<tool>" (endpoint /<path>): <FMP message>`, `isError:true`.
  **402/plan-limited**: whatever hosted emits (recorded in Phase 2 on a `plan_limited` endpoint);
  we additionally short-circuit known plan-limited endpoints (no upstream call) only if Q5 = yes.
  The key is scrubbed from every message (regex on the key value and `apikey=` patterns).
- **Pagination/limits**: pass `page`/`limit` through; cache key includes them. No server cap by
  default (parity); optional `max_response_bytes` guard off by default (Q6).
- **Provenance**: `result._meta["openbb/provenance"] = {"state": "cached|live|stale|unavailable",
  "source": "fmp_cached|fmp", "asOf": <ISO fetched_at>, "reason"?: str, "ttlSeconds": int}`.
  States are the #1269 `DataState` values; a test asserts our literal set ⊆ `DataState`.
  `content` never changes; hosted clients ignore `_meta`.

## 4. Storage semantics: persistent store first, TTL only for truly ephemeral data

### 4.1 What `fmp_cached` actually does today (verified on `portfolio` @ `041f292ea`)

`fmp_cached` is a **persistent MySQL store**, not a cache. The `cache` naming is historical.
- **Default = keep forever.** Every table without a rule in `CACHE_EXPIRY_RULES` is non-expiring;
  rows are upserted or extended on refetch and only grow (runbook §7). That includes
  `equity_historical` and the other historical tables, reference lists and `sp500_constituents`.
- **Series are gap-filled, not expired.** `equity_historical` reads the stored rows for the
  requested range, computes missing trading-day ranges (holiday-aware, with an intraday density
  guard), fetches **only the gaps** and upserts them (`ON DUPLICATE KEY UPDATE`,
  `models/equity_historical.py:278-350, 780+, 1193`). Stored history is never re-downloaded.
- **Reference lists** are mirrored: `TRUNCATE + INSERT` on refresh (`available_directories.py:105-135`).
  Note that today they are written but always fetched live, so they act as a write-only mirror.
- **Stale is a fallback, not an error.** `index_constituents` refetches after 7 days, but serves the
  stored rows when FMP fails (`index_constituents.py:743-758`).
- **TTL applies to only 13 reader paths** (`cache_schema.py:6059`, runbook §7):
  - genuinely ephemeral: `aftermarket_quote` 60 s, `equity_quote` 300 s, and `ttl_cache` for
    ExchangeMarketHours 1 d;
  - refresh intervals on durable data: statements, key-metrics, ratios and ETF holdings 1 d;
    profile, peers and institutional ownership 7 d; complementary yields 24 h.

Two existing behaviours conflict with "keep meaningful results forever". I propose to treat both
as `fmp_cached` gaps outside this program (Q9):
1. **#1292 prune deletes durable data.** `prune_expired_cache` deletes statement, key-metric,
   ratio, profile, peer, ETF-holding and institutional rows once they are older than the reader's
   refresh interval. That turns "refetch after 1 day" into "forget after 1 day".
2. **Statement refresh deletes history.** `replace_rows` deletes all of a symbol's rows before it
   inserts the new fetch (`utils/database.py:367`), so quarterly and annual fetches evict each
   other.
   - It is also unverified whether today's partial EOD bar is ever refreshed: no "today"
     handling exists in the gap detector. Phase 2 will check this.

### 4.2 Retention classes for the 208 hosted endpoints

Per-endpoint assignment: `retention-classes.json` (generated during planning, approved at G1;
Phase 2 confirms it while recording fixtures).

| Class | n | Stored | When we call FMP | Pruned? |
|---|---|---|---|---|
| `series` | 54 | Forever, one raw FMP row per (endpoint family, symbol, date or timestamp, variant) | Only for missing ranges, plus the **open tail** (today's session or the latest bar), which is re-fetched until the session closes. Closed ranges are never re-fetched. Applies to EOD and intraday charts for all asset classes, technical indicators, treasury rates, economic indicators, COT, historical market cap, employees, PE and performance | Never |
| `immutable-doc` | 30 | Forever, one raw response per canonical request | Once. Examples: as-reported statements, 10-K JSON/xlsx, filings search, past insider/congress trades, M&A, IPO prospectus, company dividends, splits and earnings history | Never |
| `revisable` | 59 | Forever. Rows are upserted by natural key, so new periods and restatements are added and older periods kept (Q10: keep superseded versions?) | When the **refresh interval** passes, with stale-while-error. Examples: statements, metrics, ratios, estimates, grades, price targets, profiles, peers, ETF weightings, calendars, DCF, classifications, symbol search | Never |
| `reference` | 16 | Forever, as a mirror of the latest list | Every refresh interval (1 to 7 d). Directories, symbol, ETF, CIK and exchange lists, transaction types, COT list | Never (replaced in place) |
| `feed` | 14 | **Items** forever (articles, filings and trades keyed by URL or accession number); the **listing** response is ephemeral | Listing TTL 5 to 15 min. Examples: news, press releases, FMP articles, the `latest-*` endpoints, 8-K latest, house/senate latest | The listing only |
| `ephemeral` | 33 | Short-lived raw response | When the TTL passes: quotes 15 to 60 s; market-hours status, gainers, losers, most-active, snapshots, float and market cap 1 to 15 min; screener 15 min | **Yes**, the only prunable class |
| `no-store` | 2 | Nothing (custom DCF with caller-supplied assumptions) | Always | n/a |

Persistent: 173 of 208. Ephemeral: 33. Never stored: 2.
- **Dated variants:** an "ephemeral" endpoint called with a **past** `date` or `from`/`to` (for
  example `sector-performance-snapshot?date=2025-01-02`) is immutable and is stored
  forever. The class is resolved per call, not only per endpoint.

### 4.3 Store layout (all raw FMP JSON, so hosted payloads are reproducible)

- **`fmp_raw_series`**: `(family, symbol, variant, ts)` primary key, `row_json` (key order
  preserved), `fetched_at`, `is_final`.
  - `is_final = false` marks the open-tail row; it is re-fetched until final.
  - The response is rebuilt in FMP order (date descending) for the requested range, then
    compact-serialised.
  - Existing typed tables (`equity_historical`) are **not** reused for payloads. They store
    normalised columns plus synthetic fill rows. Phase 2 can backfill `fmp_raw_series` from FMP
    rather than from them.
- **`fmp_raw_document`**: `cache_key` = sha256 of the path plus the canonical query, with the key
  removed. Columns: `path`, `query_json`, `body` (gzip), `content_type`, `retention_class`,
  `fetched_at` and `refresh_after`; `refresh_after` is NULL for immutable rows.
  - Holds the `immutable-doc`, `revisable` and `reference` classes.
  - For `limit`-paged statements we store the response per (symbol, period, limit). Fetching the
    widest page once and slicing it is an optimisation to adopt only if a replay proves byte
    equality.
- **`fmp_raw_feed_item`**: `(family, item_id)` primary key, plus `row_json`, `published_at` and
  `fetched_at`. A separate `fmp_raw_feed_listing` stores the listing response with a TTL.
- **`fmp_mcp_ephemeral`**: raw response with `expires_at`. This is the **only** new table added to
  `EXPIRABLE_CACHE_TABLES` and `CACHE_EXPIRY_RULES`.
- **Warm start:** the 8 typed tables that already hold raw JSON (statements ×3, key-metrics,
  ratios, profile, peers, market hours) can seed `fmp_raw_document`, but only where the stored
  rows match the requested period and limit.

### 4.4 Read path

1. **Classify the call:** endpoint class, plus the date-sensitivity rule.
2. **Answer from the store if it is complete:**
   - `series`: no gaps and the tail is final;
   - `immutable-doc`: a row exists;
   - `revisable` and `reference`: before `refresh_after`;
   - `ephemeral` and feed listings: before `expires_at`.

   Result: `_meta.state = "cached"`, and `asOf = fetched_at`.
3. **Otherwise call FMP for the missing part only** (the gaps or the tail), under per-key
   single-flight and the rate limiter. Upsert the result, then answer.
   - A fully fresh fetch has state `live`.
   - A response that combines stored and fresh rows has state `cached`, with
     `reason: "gap-filled"`.
4. **If FMP fails** and stored data exists, serve the stored data with `state: "stale"` and a
   `reason`. Durable data always has a last good copy, so this is the normal fallback.
5. If nothing is stored, return the hosted-format error.
   - 4xx and 402 responses are remembered for 10 min in `fmp_mcp_ephemeral`, to protect quota.
6. **If MySQL is down**, the server runs live-only with `state: "live"` and a startup warning.
   `require_store=true` makes it refuse to start instead.

### 4.5 Pruning

- `cache_prune` may only ever touch `fmp_mcp_ephemeral` from this program.
- Tests assert that:
  - the series, document and feed tables are **not** in `EXPIRABLE_CACHE_TABLES`;
  - the protected guard still refuses the operator tables (`pi_*`, `paper_*`, `snapshot*`,
    audit tables).
- A mutation test checks the assertions: adding `fmp_raw_series` to the allowlist must fail the
  suite.

## 5. Security and privacy

- Bind `127.0.0.1` by default; non-loopback refuses to start without `FMP_CACHED_MCP_TOKEN`
  (bearer via the existing `TokenAuthProvider`). Stdio transport supported for Claude Code.
- FMP key read from env/`user_settings.json` server-side only; never in `_meta`, errors, logs,
  cache keys or fixtures. Recorder strips `apikey` and verifies with a grep test over fixtures.
- No account data: the package imports nothing from portfolio/brokerage/paper modules (AST import
  guard test, R8). Only public market data tables are touched.
- Bounds: upstream concurrency semaphore (default 4), token bucket (default 5 req/s, burst 10,
  below FMP plan limits), `symbols` max 100, `limit` passed through but capped by FMP.

## 6. Test strategy

- **Parity contract** (`tests/contract/test_hosted_parity.py`): our `tools/list` == recorded
  inventory (exact, key-sorted); fails on drift. A `@pytest.mark.integration` twin re-fetches hosted
  `tools/list` and diffs against the fixture (detects hosted drift; never auto-updates).
- **Shape replay**: per endpoint, recorded hosted response (AAPL/MSFT/SPY/BTCUSD/EURUSD, public) →
  our server with a stub upstream returning the recorded REST body → assert content equality and
  compact serialisation. Fixtures differ between buggy/fixed code (R7): e.g. pretty vs compact,
  key reordering, `from_date` not renamed.
- **Hermetic units**: cache key canonicalisation, TTL class map completeness (every endpoint has a
  class), single-flight, stale-while-error, negative caching, key scrubbing, loopback/token guard,
  import guard. MySQL tests use the existing test DB fixtures (`create_test_database.sql`).
- **Live** `@pytest.mark.integration`; plan-limited endpoints add `@pytest.mark.plan_limited` +
  `skipif(is_plan_limited(...))` per CLAUDE.md tier rule. `plan_limited` gains a path→model alias
  map so the MCP endpoint names resolve.
- Red-first for each task (keep red output in the commit/handoff); mutation check on the parity and
  scrubbing guards (remove the guard → test fails), per Testing Rules R7/R11.
- **CI**: new workflow job "FMP cached MCP parity" (hermetic contract + replay, 3.12/3.13), plus
  entry in `scripts/local_ci.py` once #1274 merges. Portfolio MCP inventory/replay jobs and Dual
  MCP locks are unaffected (verified by running them locally in the batch PR).
- **Real-path check**: launch the server on stdio, point a scratch `.mcp.json` at it, run a scripted
  set of ~10 hosted-identical tool calls twice; second run must be all `cached` with zero upstream
  requests (counted by the upstream stub/log).

## 7. Phased delivery (3 PRs)

| PR | Scope | Acceptance | Risks | Size |
|---|---|---|---|---|
| **PR-A: contract + server core** (US1, US2, US5) | Recorder script (`scripts/fmp_mcp_record.py`, reuses `pi_fmp_record` key handling), versioned inventory fixture, `endpoint_map.json`, package skeleton, verbatim `tools/list`, argument validation + hosted error text, REST upstream with param renames, key scrubbing, loopback/token, bounds. No cache yet (`_meta.state="live"`). | Contract test 24/24 tools, 208/208 enums; error fixtures match; security tests green; real-path stdio call works | zod error text emulation; non-JSON endpoints | L |
| **PR-B: persistent store + provenance** (US3, US4) | Raw series, document and feed stores plus the ephemeral table; retention classes; gap-fill and open-tail refresh; single-flight; stale-while-error; negative cache; `_meta` provenance, prune allow-list + operator-table guard, warm-start from the 8 raw typed tables, `plan_limited` path aliases. Record shape fixtures for all non-plan-limited endpoints. | SC2 + SC4; prune guard test; replay of all recorded endpoints | MySQL availability; fixture volume (cap each fixture, trim long arrays to N rows with a recorded length) | M–L |
| **PR-C: switch-over + gaps** (US6) | `.mcp.json` example + docs/runbook, Workspace registration (separate server entry), local CI job, record plan-limited error fixtures, file and link `area:fmp-cached-gap` issues: statement period eviction bug, 24 h-asset intraday calendars, EOD light variants, search multi-param, missing endpoints list | SC3 agent smoke; local CI evidence comment; every `no-store`/plan-limited endpoint documented | Workspace treating two FMP servers; owner switch timing | S–M |

Typed-fetcher gaps (17 missing, e.g. EOD light ×4, insider latest/reporting-name/transaction-types,
press-release/stock-latest news, SEC company-search ×3, house/senate by-name, employee-count,
10-K xlsx) **do not block MCP parity** under (b) — the raw cache serves them. They are filed as
`area:fmp-cached-gap` issues only for the OpenBB command surface.

## 8. Decisions needed from the owner (G1)

1. **Q1 Parity target**: freeze on snapshot 2026-11-23 (24 tools / 208 endpoints) and treat hosted
   drift as a reviewed fixture update? *(recommended: yes)*
2. **Q2 Miss upstream**: FMP REST `/stable/*` (recommended) or the hosted MCP server, or REST with
   hosted as fallback?
3. **Q3 Extra tools**: allow cache-only tools (e.g. `cacheStatus`)? If yes, prefix `fmpCached_*`
   and expose only behind a flag so the default `tools/list` stays identical. *(recommended: none in v1)*
4. **Q4 Retention classes**: accept the §4.2 model and the draft per-endpoint assignment? It keeps
   173 endpoints forever and gives TTLs only to the 33 ephemeral ones and the feed listings.
   The refresh intervals are: revisable 1 d (profiles 7 d), reference 1 to 7 d, ephemeral
   15 s to 15 min.
5. **Q5 Plan-limited**: short-circuit known plan-limited endpoints without calling FMP, or always
   call and return FMP's 402 text (closer parity)? *(recommended: always call, negative-cache 10 min)*
6. **Q6 Response size**: keep unbounded (parity) or cap e.g. 2 MB with a hosted-style error?
7. **Q7 Location/port**: package `openbb_platform/extensions/fmp_cached_mcp`, default port 8011,
   server name `fmp_cached` in `.mcp.json`?
8. **Q8 Issues**: create 1 parent, 3 sub-issues (one per PR) and up to 6 `area:fmp-cached-gap`
   issues? D4 says to confirm anything over 3.
9. **Q9 Existing `fmp_cached` expiry**: take the 9 durable tables (statements, metrics, ratios, ETF
   holdings, profile, peers, institutional) out of the #1292 prune allowlist? Their reader TTL
   would then mean "refresh after", not "delete after". Also stop `replace_rows` from deleting a
   symbol's history? I recommend yes to both, as a separate fix issue, not in this program.
10. **Q10 Revisions**: for `revisable` data, overwrite in place (one current row per natural key),
    or keep superseded versions (as-of history, useful for "what did we know on date X")?
    I recommend overwriting in v1 and recording `fetched_at`.
