# Tasks: fmp_cached MCP parity (#1298)

Every task starts red (failing test first, red output kept). Sub-issues: A #1299, B #1300, C #1301 (parent #1298). One branch per PR, worktree under `OpenBB/.worktrees/`.

## PR-A — contract + server core (US1, US2, US5) (#1299)

- [x] A1 Recorder `scripts/fmp_mcp_record.py`: `initialize` → `tools/list` (+ prompts/resources
      probes) → versioned fixture `openbb_platform/extensions/fmp_cached_mcp/tests/fixtures/hosted/inventory-2026-11-23.json`.
      Test: fixture contains no key (grep test) and 24 tools / 208 enums.
- [x] A2 `endpoint_map.json` (tool, endpoint, REST path, param renames, ttl_class, plan_limited key).
      Test: every inventory enum has exactly one row; unknown rows fail.
- [x] A3 Package skeleton `openbb_fmp_cached_mcp` (low-level `mcp` server, stdio + streamable HTTP,
      session ids). Test: `tools/list` equals fixture (exact); prompts/resources return -32601.
- [x] A4 Argument validation with hosted zod-style error text. Tests: recorded error fixtures
      (invalid enum, wrong type, unknown key, missing required param → FMP-side message).
- [x] A5 REST upstream (`/stable/<path>`, `from_date→from`, `to_date→to`, arrays → comma list),
      compact serialisation. Test: stub upstream with recorded REST body → content equals recorded
      hosted text; mutation: pretty-print → fails.
- [x] A6 Key scrubbing in errors/logs; loopback default; token required off-loopback; concurrency
      and rate bounds; AST import guard (no portfolio/brokerage imports).
- [x] A7 Real-path check: stdio launch + 5 scripted calls via an MCP client; record output.

## PR-B — cache + provenance (US3, US4) (#1300)

- [ ] B1 Add the schemas in `cache_schema.py`: `fmp_raw_series`, `fmp_raw_document`,
      `fmp_raw_feed_item`, `fmp_raw_feed_listing`, `fmp_mcp_ephemeral`. Add a canonical request
      key. Add `retention_classes.json` (owner-approved), with a completeness test: every
      endpoint has a class.
- [ ] B2 Series path: gap detection per asset calendar (24 h for crypto and forex; equity
      holidays), fetching only the missing parts, open-tail refresh until final, rebuilding rows
      in FMP order. Tests:
      - a second call for a closed range makes zero upstream calls;
      - a gap-only fetch requests exactly the gap;
      - the tail row is re-fetched while open and not after it is final.
- [ ] B2b Document, reference and feed paths:
      - immutable rows are fetched once;
      - revisable and reference rows refresh after their interval;
      - feed items are upserted by id, and only the listing has a TTL;
      - the past-date rule promotes ephemeral calls to immutable.
- [ ] B3 Stale-while-error on every persistent class, a 10-minute negative cache for 4xx, single
      flight, live-only mode when MySQL is down, and a `require_store` option.
- [ ] B4 `_meta["openbb/provenance"]` with `DataState` subset test; content unchanged test.
- [ ] B5 Add `fmp_mcp_ephemeral` to the `cache_prune` allowlist. Add a test that the persistent
      tables are not in it, with a mutation check (adding `fmp_raw_series` must fail), and keep
      the operator-table guard test.
- [ ] B6 Warm-start from the 8 raw typed tables (statements ×3, key-metrics, ratios, profile, peers,
      market hours) — only when the typed row set satisfies the requested `period`/`limit`.
- [ ] B7 `plan_limited` path→model alias map; `plan_limited` markers on live tests.
- [ ] B8 Record shape fixtures for all non-plan-limited endpoints (public symbols; long arrays
      trimmed with recorded length); replay test over all.
- [ ] B9 Real-path: run the scripted calls twice; second run 100% `cached`, zero upstream calls.

## PR-C — switch-over + gaps (US6) (#1301)

- [ ] C1 Record plan-limited/402 error fixtures; assert our text equals hosted.
- [ ] C2 `.mcp.json` example + runbook `docs/operations/fmp-cached-mcp.md`; Workspace registration
      as a separate MCP server.
- [ ] C3 CI job "FMP cached MCP parity" (3.12/3.13) and `local_ci.py` entry; run Portfolio MCP
      inventory/replay + dual-lock checks locally to prove no impact.
- [ ] C4 Hosted-drift integration test (live `tools/list` diff, `@pytest.mark.integration`).
- [ ] C5 File `area:fmp-cached-gap` issues (statement period eviction, 24 h intraday calendars,
      EOD light, search multi-param, missing endpoints) and link them.
- [ ] C6 Agent smoke: switch scratch `.mcp.json` `fmp` → `fmp_cached`, same prompts/tool calls.
