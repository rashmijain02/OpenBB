# Spec: `fmp_cached` MCP server with parity to FMP's hosted MCP server

Status: **G1 approved 2026-11-24** (recommended answers to Q1–Q10 accepted) (no parent issue yet; parent #1298 (fmp_cached MCP parity); G1 approved by the owner 2026-11-24)
Branch (Phase 2): `feat/pi-fmp-mcp-parity-gh-1298` in `OpenBB/.worktrees/fmp-mcp-parity-gh-1298`, cut from `origin/portfolio`
Ground truth: `openbb_platform/extensions/fmp_cached_mcp/tests/fixtures/hosted/inventory-2026-11-23.json` (live `tools/list`, recorded 2026-11-23)

## Problem

Agents and Workspace can call FMP's hosted MCP server (`https://financialmodelingprep.com/mcp`,
server `fmp` in `OpenBBWorkspace/.mcp.json`). Every call goes to FMP: no reproducibility, no cost
control, and it bypasses the `fmp_cached` rule in the constitution (principle IV). We want a
drop-in server, backed by the `fmp_cached` persistent MySQL store, so a client can switch `fmp` → `fmp_cached`
with no change to prompts or tool calls.

## What the hosted server is (verified 2026-11-23)

- `serverInfo`: `FMP MCP Server` 1.0.0, protocol `2025-06-18`, capabilities `tools` only
  (`listChanged: true`). `prompts/list`, `resources/list`, `resources/templates/list` return
  JSON-RPC `-32601 Method not found`.
- Streamable HTTP, stateful: `initialize` returns `Mcp-Session-Id`; calls without it get HTTP 400
  `-32000 "Bad Request: No valid session ID provided"`. Responses are `application/json` (no SSE).
- **24 tools, 208 endpoints.** Each tool takes a required `endpoint` string enum plus optional
  parameters (`additionalProperties: false`, draft-07). Annotations on every tool:
  `readOnlyHint: true, destructiveHint: false, openWorldHint: true`; `execution.taskSupport: "forbidden"`.
  Tool `title` = name. Descriptions list each endpoint with its required params (`*`).
- Names are mixed case: `Fundraisers`, `analyst`, `calendar`, `chart`, `commitmentOfTraders`,
  `commodity`, `company`, `crypto`, `directory`, `discountedCashFlow`, `economics`,
  `etfAndMutualFunds`, `forex`, `indexes`, `insiderTrades`, `marketHours`, `marketPerformance`,
  `news`, `quote`, `search`, `secFilings`, `senate`, `statements`, `technicalIndicators`.
- **Success payload** = `result.content[0]` of type `text` whose text is the FMP `/stable/...` REST
  JSON re-serialised **compactly** (no whitespace). JSON-equal to the REST body, not byte-equal to
  it (REST is pretty-printed). No `structuredContent`, no `_meta`, no `outputSchema`.
  Non-JSON endpoints (e.g. `financial-reports-form-10-k-xlsx`) return a string payload
  (~176 KB for AAPL FY2024) — unbounded.
- **Errors** are tool results, not JSON-RPC errors (HTTP 200):
  - schema violations → `isError: true`, text `MCP error -32602: Input validation error: Invalid
    arguments for tool <tool>: [<zod issue array>]` (zod `invalid_enum_value`, `invalid_type`, …);
  - FMP-side 4xx → `isError: true`, text `Bad request for tool "<tool>" (endpoint /<path>): <FMP message>`.
  - 402 / plan-limited shape: not observed with this key (the probes `COT-report-list`,
    `historical-sp-500`, `all-shares-float`, `batch-quote` all succeeded). To be recorded in Phase 0
    against an endpoint in `plan_limited.py`.
- **Pagination/limits**: pass-through `page`/`limit` to FMP; no server-side cap observed
  (`historical-sp-500` returned ~364 KB).
- Array params: `quote.symbols`, `company.symbols`, `news.symbols` are `array<string>`
  (hosted rejects a comma string).

## User stories

- **US1 (P0) Parity inventory as a contract.** As a maintainer I have a versioned recording of the
  hosted `tools/list` and per-endpoint response shapes (public symbols only) and a test that fails
  when our server or the hosted server drifts from it.
- **US2 (P0) Drop-in server.** As an agent I can point at `fmp_cached` MCP and call the same 24 tools
  with the same arguments and get the same `content[0].text` (JSON-equal for JSON endpoints).
- **US3 (P0) Persistent store first.** As the owner, I want every meaningful result (price
  history, statements, filings, trades, news items, reference lists) kept in MySQL **for good**.
  FMP is called only for data we don't have yet: missing ranges, the open tail of a series, or a
  revisable record past its refresh interval. Only genuinely ephemeral data (quotes, snapshots,
  feed listings) has a TTL and is prunable. FMP errors fall back to the stored copy and say so.
- **US4 (P1) Provenance without breaking parity.** As Workspace / an agent I can read whether a
  result was `cached`/`live`/`stale` and its `asOf` from `result._meta`, consistent with the #1269
  `DataState` model, while `content` stays identical to hosted.
- **US5 (P1) Safe by default.** Loopback bind, bearer token required off-loopback, FMP key never
  leaves the server, no account/brokerage data reachable, bounded rate and fan-out.
- **US6 (P2) Coverage closure.** Every hosted endpoint is either served from the persistent store, served
  live-only (`no-store`, documented), or returns the hosted plan-limited error with an
  `area:fmp-cached-gap` issue.

## Functional requirements

- FR1 `tools/list` of our server equals the recorded hosted list for `name`, `title`,
  `description`, `inputSchema` and `annotations` (exact JSON equality after key sort). Any
  intentional divergence lives in a checked-in allow-list with a reason.
- FR2 `tools/call` success: `content == [{"type":"text","text": compact_json(fmp_stable_body)}]`.
  Field names, order and types come from the raw FMP body; no OpenBB normalisation in `content`.
- FR3 Errors reproduce the hosted text templates (validation and FMP-side) and `isError: true`.
- FR4 Provenance in `result._meta["openbb/provenance"] = {state, source, asOf, reason, cacheKey?}`
  only; never in `content`. Hosted-compatible clients ignore `_meta`.
- FR5 Each endpoint has a retention class (`series`, `immutable-doc`, `revisable`, `reference`,
  `feed`, `ephemeral`, `no-store`; see plan §4.2).
  - The class decides whether data is stored forever (`series` gap-fill plus open tail,
    immutable once, revisable or reference refresh intervals, feed items) or with a TTL
    (`ephemeral` and feed listings only).
  - A call with a past date is immutable whatever its endpoint's class.
  - On an FMP error, stored data is served with `state: "stale"`.
- FR6 Only the ephemeral table is prunable. Tests assert that the persistent tables are not in
  `EXPIRABLE_CACHE_TABLES`, and that operator tables (snapshot, paper, audit) are never
  candidates.
- FR7 Security: default `127.0.0.1`; non-loopback bind refuses to start without a token; the FMP key
  is read server-side and scrubbed from every error, log line and `_meta`.
- FR8 Bounds: max concurrent upstream calls (semaphore), per-client token bucket, max response size
  (configurable; default unbounded for parity, see open question Q6), max `symbols` length.

## Non-goals

- Rewriting the existing `fmp_cached_{command}` OpenBB tools (they stay; different contract).
- Prompts/resources (hosted offers none).
- Write tools or account data of any kind.

## Success criteria

- SC1 Parity contract test green: 24/24 tools, 208/208 endpoint enums equal.
- SC2 Shape replay green for every endpoint with a recorded fixture (target: all non-plan-limited
  endpoints; plan-limited ones have recorded error fixtures).
- SC3 Switching `.mcp.json` from `fmp` to `fmp_cached` passes a scripted agent smoke run (real-path
  check) with the same tool calls.
- SC4 Second identical call is served from MySQL (`_meta` state `cached`) with zero FMP requests.

## Assumptions recorded for G1 (recommended answers; owner may override)

See `plan.md` → "Decisions needed". Until answered, the plan assumes: parity snapshot 2026-11-23;
misses go to FMP REST (not the hosted MCP); no extra cache-only tools in the hosted-named tool set.
