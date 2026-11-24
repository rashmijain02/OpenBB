# Handoff: fmp_cached MCP server with hosted FMP MCP parity

| Field | Value |
|---|---|
| Parent issue | #1298 (Drop-in MCP server with FMP hosted-MCP parity, backed by the persistent fmp_cached store) |
| Sub-issues | #1299 (parity contract and server core), #1300 (persistent raw store), #1301 (switch-over, CI, gap issues) |
| Gap issues filed | #1302 #1303 #1304 #1305 #1306 #1307 (`area:fmp-cached-gap`) |
| Branch | `feat/pi-fmp-mcp-parity-gh-1298` (not pushed) |
| Base | `portfolio` @ `041f292ea` |
| HEAD | see `git log -1`; the last code commit is `edb28824c` |
| Worktree | `.worktrees/fmp-mcp-parity-gh-1298` |
| Executor model | `claude-opus-5.5` (lead); review subagents `sonnet` |

The owner approved G1 on 2026-11-24 ("go ahead do it now"), taking the recommended answers to
Q1–Q10 in `plan.md`. The branch has 7 commits: 253 files, +18.1k lines. Most of that is recorded
fixtures (about 2 MB of JSON).

## Tasks

| Task | Status | Commit |
|---|---|---|
| A1 recorder and fixtures | done | `e6236a42b` |
| A2–A7 endpoint map, verbatim `tools/list`, zod-style validation, REST upstream, security, real path | done | `2f0908208`, review fixes `8bf60a181` |
| B1–B5, B7–B9 persistent store, retention policy, provenance, prune allowlist, plan_limited aliases, real path | done | `bc0eb8966`, review fixes `3629a856b` |
| B6 warm start from typed tables | **deferred** (no MySQL on host; see #1300 comment) | — |
| C1–C6 402 fixture, runbook and `.mcp.json`, CI job, live drift tests, gap issues, scripted client smoke | done | `edb28824c` |

## Evidence

- **Package tests:** `cd openbb_platform/extensions/fmp_cached_mcp && pytest -q tests` gives
  **319 passed, 12 deselected** (the deselected tests are `integration`).
  - 179 recorded hosted payloads are replayed byte for byte through the real MCP protocol path.
  - A differential test compares our output with Node's `JSON.stringify`.
- **Live tests:** `pytest -m integration tests/test_hosted_live.py` gives **7 passed, 5 skipped**.
  The skips are the plan-limited markers.
- **fmp_cached provider suite** (not integration, base vs head): identical result sets on both,
  1085 passed with the same 38 pre-existing failures. Those fail because MySQL is down on this
  host.
- **fmp_cached prune contract:** `tests/test_cache_expiry.py` gives 44 passed.
- **Mutation checks:** every load-bearing guard was reverse-verified; 32 of 32 mutations killed.
  - Scrubbing, the bind guard, bearer auth and DNS rebinding.
  - Key in the header, hosted defaults, unknown-key stripping, JS number thresholds,
    big integers and key order.
  - Gap-fill, the open tail, re-basing and the overlap, open-bar revision.
  - Stale-while-error, the negative cache and its key length, immutability.
  - Single-flight and cancellation.
  - Prune scope, opportunistic prune and store back-off.
  - Data errors versus outages, the body cap, timestamp length, paged series, the MySQL upsert
    syntax.
- **Lint (General Code Linting job reproduced on the changed files):**
  - `black --check`, `ruff`, `pylint`: clean.
  - `codespell`: clean.
  - `mypy`: one error in `openbb_fmp_cached/__init__.py:498`, a file this branch does not touch.
    It is identical on base `041f292ea` and comes from the locally installed `openbb_fmp`, which
    CI does not install.
- **Real-path checks:** logs are in `.dev-cycle/verify-gh-1299.log`, `verify-gh-1300.log` and
  `verify-gh-1300-review.log` (git-ignored).

```text
A7  stdio server vs live hosted server: RESULT 9/9 identical to hosted; key in any output: False
B9  run 1 (cold store): 10/10 identical to hosted; states=['cached', 'live']
    run 2 (new process, same store): 10/10 identical to hosted; states=['cached']
    RESULT run2 all cached: True
```

## Review findings

| Severity | Finding | Action |
|---|---|---|
| Medium | JS JSON edge cases: integers beyond 2^53, array-index key order, NaN literals | applied `8bf60a181` (a node differential test added) |
| Medium | Missing DNS-rebinding protection on the loopback HTTP transport | applied `8bf60a181` |
| Low | Auth on non-HTTP scopes; resolve-once bind; httpx INFO URL logging; recorder key in the URL | applied `8bf60a181` |
| Medium | The `neg:` key overflowed `CHAR(64)` (on MySQL every 4xx would mark the store down) | applied `3629a856b` |
| Medium | A false re-basing from open bars, and a skipped overlap in the merge branch | applied `3629a856b` |
| Medium | Paged series marked coverage; removed rows were never deleted; double fetch on a write error | applied `3629a856b` |
| Medium | Empty answers persisted forever; no body cap; ephemeral rows were never pruned | applied `3629a856b` |
| Low | Cancellation propagated to waiters; `VALUES()` upsert syntax; per-row writes | applied `3629a856b` |
| Low | Blocking DB calls inside the event loop (no `to_thread`) | **deferred**: bounded by local single-user use; revisit with MySQL latency data |
| Info | FMP terms for permanent storage | README note; owner decision |

## Local CI-equivalent (Actions is not creating runs)

| Workflow / job | Local result |
|---|---|
| FMP cached MCP parity (new) | reproduced on 3.12: assets rebuild byte-identically, 319 passed, prune contract 44 passed. 3.13 was not run: no 3.13 interpreter on the host. |
| General Code Linting | reproduced (see Evidence) |
| Portfolio MCP Coverage | triggered by `openbb_platform/**` but **not reproduced**. Its wheel list does not include the new package; the only overlap is `cache_schema.py` (new tables, one new prune rule). The `mcp_server` suites error identically on base and head in `.venv_portfolio`, so run them in the MCP lock venv (`scripts/test_portfolio_mcp.ps1`) before merge. |
| Labeler / closes-syntax / PR description | need a PR; not reproducible |

## Open questions for the owner

- **Push and PR.** Push the branch and open one PR into `portfolio` closing #1299, #1300 and
  #1301 (batching per the local CI rule), or three stacked PRs as the plan first said?
- **Claude Code `.mcp.json`.** Add the `fmp_cached` entry to the workspace `.mcp.json` next to
  `fmp` (example in `docs/operations/fmp-cached-mcp.md` §3)? It was not edited.
- **FMP terms.** Is permanent storage of FMP payloads acceptable under the subscription terms?
  See the package README.

## Not done / follow-ups

- **B6 warm start, MySQL live verification, long intraday range truncation:** tracked as a comment
  on #1300.
- **`fmp_cached` provider gaps** found along the way: #1302–#1307.
- **Blocking DB calls (`asyncio.to_thread`):** deferred review finding. File it if MySQL latency
  shows up.
