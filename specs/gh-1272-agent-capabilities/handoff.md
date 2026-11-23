# Handoff: Align Workspace agent capabilities

| Field | Value |
|---|---|
| Parent issue | #1264 ([portfolio-ux][PROGRAM] Make Portfolio Intelligence a native OpenBB Workspace terminal) |
| Sub-issues | #1272 ([portfolio-ux] Align Workspace agent capabilities) |
| Branch | `feat/pi-agent-capabilities-gh-1272` |
| Base | `portfolio` @ `dff95c67c` |
| HEAD | `dff95c67c` (changes uncommitted; the lead commits) |
| Worktree | `.worktrees/pi-agent-capabilities-gh-1272` |
| Executor model | `claude-opus-5.5` (implementer subagent; route mode, plan Step 8) |

## What changed

The Workspace custom agent (`openbb_portfolio.copilot`, `/agents.json` + `/query`) was text-only.
It now reads the widgets the user selects, read-only, through Workspace's own `get_widget_data`
function call, and advertises only what `/query` implements.

- **New `openbb_portfolio/agent_capabilities.py`:** `WidgetCapability` (id, name, kind, endpoint,
  `denied_reason`) and `capabilities_from_manifest(widgets_json, denied)`. `input_args()` passes
  the widget's current parameters unchanged and adds `raw=True` for charts. A denial that names
  no manifest widget raises.
- **New `widget_backend/agent_policy.py`:** `AGENT_DENIED_WIDGETS` = `pi_paper_ticket` (places
  paper orders) and `pi_backtest_button` (queues a job); `build_agent_capabilities()` builds the
  inventory from this backend's `widgets.json`.
- **`widget_backend/main.py`:** registers the inventory on `app.state.agent_widget_capabilities`
  inside the existing best-effort copilot import.
- **`openbb_portfolio/copilot.py`:**
  - `/agents.json`: `streaming` true; `widget-dashboard-select` true only when the app has
    readable widgets; `widget-dashboard-search` false. `IMPLEMENTED_FEATURES` is the ceiling.
  - `/query` turn 1 (human message + selected widgets): refuses denied or unknown widgets with a
    message, then emits one `get_widget_data` for at most 8 readable widgets.
  - `/query` turn 2 (tool result): drops data for any widget outside the inventory, redacts
    credentials, extracts provenance, emits a `copilotStatusUpdate`
    (`Data provenance - <widget>: <state> (source ..., as of ...)`), and sends bounded context
    (50 rows per widget, 300 chars per cell, 24,000 chars) plus data-state rules to the model.
  - Model call: client `timeout` and `max_retries=0`, `max_tokens=1500`, and a wall-clock limit on
    the whole stream (`COPILOT_PROXY_TIMEOUT_SECONDS`, default 60) with a visible cut-off note.
  - `request.api_keys` and `request.tools` (auth tokens) are never read. The module has no HTTP
    client of its own and never sees the backend token.
- **MCP adapter (`adapters/portfolio_intel.py`):** `ChartRowsMiddleware` replaces any `raw`
  argument with `raw=true` on the 12 cloned Plotly chart routes (detected by the route's `raw`
  parameter, as the matrix builder does). The clone keeps the original handler and dependencies.
  Chart tool descriptions say they return rows with `data_state` / `data_source` / `data_as_of`.
- **Probe:** `tests/unit/_workspace_endpoint_probe.py` gained an `agent` mode.
- **README:** new self-contained "Workspace agent (#1272)" section in `widget_backend/README.md`.

## Capability map

| Inventory | Count | Agent |
|---|---|---|
| Matrix widgets (`native_workspace_matrix.json`) | 61 | All 61 in the inventory, same ids, types and endpoints |
| Readable | 59 | 14 charts read with `raw=true` (12 Plotly, 2 #1271 TechTrade charts) |
| Denied | 2 | `pi_paper_ticket`, `pi_backtest_button`: the set the MCP policy restricts (`deny-success-shaped-intelligence-stubs`) |
| Mutation POSTs (`/tt/execute/{approve-plan,write-batch,cancel}`, `/tt/scan/trigger`) | n/a | Not widgets. The agent's only function is `get_widget_data`, so they are unreachable |

## Consumers

| Consumer | Handling |
|---|---|
| Local Viewer chat pane (`POST /query` with `messages` only) | Unchanged text-only path; it reads only `name` from `/agents.json`. |
| `portfolio/launch.py` (6902) | Mounts the router without an inventory: text-only, `widget-dashboard-select` false (as before). |
| `test_copilot.py`, `test_copilot_mount.py` | Pass unchanged. |
| MCP `test_portfolio_intel_adapter.py` (endpoint and dependent identity) | Passes unchanged (middleware, not a new endpoint). |
| MCP capability inventories and CSV | Path-based. Head vs base export identical except the worktree `dirty` flag; no regeneration needed. |
| Workspace widgets (`/pi/*` on the backend) | Still Plotly by default; only the MCP clone forces rows. |

## Evidence

- **Red first** (`.dev-cycle/red-gh-1272.log`): agent tests 26 failed, 4 passed on the old
  copilot (the 3 inventory tests were red at collection before `agent_capabilities` existed; the
  AST no-HTTP-client test passes on old code and is proven by mutation). PI cross-check:
  collection error (no `agent_policy`). MCP chart rows: 5 failed, 2 passed.
- **Mutation** (`.dev-cycle/mutation-gh-1272.log`): 19 of 19 killed: chart raw dropped, deny
  check removed, read cap ignored, key redaction off, value redaction off, provenance always
  unknown, context not sent, no provenance step, no time limit, no max_tokens, widget access always
  advertised, denied data not dropped, row cap removed, copilot gains an HTTP client, denial list
  shrinks, backend registers no inventory, MCP raw not forced, MCP description dropped, MCP keeps
  the caller's `raw`. The last survived at first (Starlette takes the last value, so the response
  was still rows); `test_middleware_replaces_raw_once_and_keeps_other_params` now kills it.
- **Full unit:** `python -m pytest openbb_platform/extensions/portfolio_intel/tests/unit -q -p no:cacheprovider`
  -> `1964 passed, 2 skipped in 1685.90s`, exit 0.
- **Touched suites:** portfolio tests + MCP adapter, chart rows, data boundaries, exposure + PI
  agent and mount -> 121 passed, 1 skipped; MCP chart rows (with the middleware test) 8 passed.
  Full `mcp_server/tests -m "not integration"` -> 902 passed, 5 skipped, 3 failed; the same 3 fail
  on base (FinancialToolkit and fmp_cached registration environment tests, unrelated).
- **Manifest validator:** exit 0 (61 widgets, 3 apps, 5 recorded debt).
- **CI lint parity** (5 changed non-test `.py`): codespell, black and ruff clean; pylint
  10.00/10; mypy `--no-site-packages` 0 issues.
- **Real path** (`.dev-cycle/realpath-gh-1272.log`; in-process backend, demo data, model proxy on
  a refused loopback port):

```text
GET /agents.json 200 {"streaming": true, "widget-dashboard-select": true, "widget-dashboard-search": false}
POST /query (selection) 200 ['copilotMessageChunk', 'copilotFunctionCall']
  refusal: I can't read pi_paper_ticket (`pi_paper_ticket`): it places paper orders ...
  function: get_widget_data [('pi_xray_sector', {'account_id': 'demo', 'raw': True}), ('pi_risk_dashboard', {'account_id': 'demo'})]
  Workspace fetch /pi/xray/sector 200 rows=True X-PI-Data-State=demo
  Workspace fetch /pi/risk/dashboard 200 rows=True X-PI-Data-State=demo
POST /query (tool result) 200 ['copilotStatusUpdate', 'copilotMessageChunk']
  Data provenance - X-Ray - Sector Weights: demo (source stub, as of unknown); Risk Dashboard: demo (source unknown, as of unknown)
```

- **Claude review gate:** not run by the implementer; the lead owns it.

## Open questions for the lead

- The agent matches Workspace's `widget_id` to the manifest key. Confirm in a real Workspace
  session that custom-backend widgets arrive with that id.
- The read-only `tt_execute_bridge` and `tt_execute_paper_status` Markdown widgets stay readable
  (they only describe gates and status). Should they be denied too?
- Metric cards carry no source, so metric provenance reads `source unknown`.

## Not done / follow-ups

- Not verified in a real self-hosted Workspace with a live model.
- `tt_scan_table` and `tt_segment_movers` bodies carry no data state (#1271 shape debt), so the
  agent reports `unknown` for them; the test records them shrink-only.
- The 6902 portfolio backend's own widgets are not in any agent inventory (text-only there).

## Round 2: review fixes (uncommitted on top of `5e0a86acb`)

| Finding | Fix |
|---|---|
| PRIVACY-1 (MEDIUM) minimize | `sanitize` drops identifier fields (keys normalized to lowercase alphanumerics, starting with account / basket / owner / user / customer / client / holder / login / email / phone) and masks written-out ids (`account_id=…`, `**Account ID:** …`) before any context is built. No real widget column is affected (checked against the matrix `tableFields`). |
| PRIVACY-1 (MEDIUM) disclose | `COPILOT_DESCRIPTION` and the README "Workspace agent" section say selected widget data is sent to the configured external model provider (GitHub Copilot by default); every data turn's status step ends with the same disclosure. |
| SECURITY-1 (LOW) | Key matching on normalized keys (exact `key`/`sig`/`jwt`/`token`/…, suffixes `token`/`secret`/`apikey`/`accesskey`/`sessionid`/…, prefixes). Values: `Bearer`/`Basic` tokens (must contain a digit or symbol, so "Basic Materials" survives), JWTs, AWS `AKIA`/`ASIA` keys, `key=`/`access_key=`/`sig=`/`token=` and `token:`/`password:` values, `user:pass@` in URLs. |
| SECURITY-2 (LOW) | Safe by default: `agent_capabilities.action_markers` flags non-GET `method`, `confirm`-like params, and execute / paper / backtest / order / trigger / … endpoint segments or category words. Flagged widgets are denied unless on `agent_policy.AGENT_READ_ALLOWLIST` (paper blotter, performance, KPIs, execute bridge, paper status). A stale or needless allowlist entry raises. Denied set on the real manifest is unchanged (`pi_paper_ticket`, `pi_backtest_button`). |
| Code (a) origin | The inventory applies only to widgets whose Workspace `origin` (casefolded) is this backend: `portfolio-intel` (the README connector name) or `PI_AGENT_WIDGET_ORIGINS`. Other origins are refused in turn 1 and their data is dropped in turn 2. No origins registered means no widget reads. |
| Code (b) context cap | Blocks are capped at 20,000 chars each; a block that would push the context past 24,000 is left out whole. The status step lists only included widgets plus "Omitted (context limit): …"; the model context names them too. |

### Evidence (round 2)

- **Red first** (`.dev-cycle/red2-gh-1272.log`): agent tests 40 failed, 16 passed (the new
  `origins` argument plus the new behaviors); PI tests with the round-2 copilot but the old
  policy and `main.py`: 8 failed, 4 passed.
- **Mutation** (`.dev-cycle/mutation2-gh-1272.log`): 25 of 25 killed. Identifier fields kept,
  identifier text not masked, disclosure dropped, camelCase not normalized, key suffixes ignored,
  URL userinfo, JWT, AWS and Basic kept, Bearer and Basic over-redacting prose, action markers /
  confirm / category / method ignored, stale allowlist accepted, origin check off (both turns),
  origin case-sensitive, cap truncating instead of omitting, omitted not reported, allowlist
  emptied, backend origin not registered, origins env ignored. Two needed fixes: the first
  identifier-text mutant was faulty (re-run correctly, killed), and the prose test gained
  "Basic Materials" / "Bearer instruments", which also found and fixed Bearer over-redaction.
- **Tests:** portfolio tests 74 passed, 1 skipped; PI agent + mount 18 passed; MCP chart rows +
  adapter 23 passed. Full PI unit: 2068 passed, 1 failed, 2 skipped; the failure is the wall-clock
  test `test_pi_terminal_f12.py::test_provider_health_never_blocks_on_cold_cache` (1.58s against a
  1s limit while parallel suites loaded the machine); that file alone: 19 passed.
- **CI lint parity:** codespell, black, ruff clean; mypy `--no-site-packages` 0 issues; pylint has
  only the local-only C0328 (CRLF checkout of the unchanged adapter file).
- **Real path** (`.dev-cycle/realpath2-gh-1272.log`): as round 1, and the status step now ends
  with the external-provider disclosure.

## Round 3: privacy bypasses, ReDoS, size caps (uncommitted on top of `e6c01eb0c`)

| Item | Fix |
|---|---|
| PRIVACY-1a identifier keys | New `openbb_portfolio/agent_privacy.py` (split out of `copilot.py`, which had passed pylint's 1000-line limit). Keys are split into camelCase/snake/kebab tokens: an identifier if any token is account/acct/basket/owner/user/username/customer/client/login/email/phone/ssn (at any position: `pm_user`, `primary_account_id`), if portfolio/book/household/member/person sits next to an id-like token (`portfolio_id`, `book_id`, `id_portfolio`), or if the joined key contains a word+id compound (`primaryaccountid`, `AcctNo`). Applies at any depth. `ownership_pct`, `portfolio_value` and `holder` (institution names) are kept; no real matrix column matches. |
| PRIVACY-1b tables and columns | Markdown tables: a header cell matching the identifier rule masks that column's cells (line-by-line parse, no regex). Column-oriented payloads (`{"columns": [...], "data"/"rows"/"values": [[...]]}`, with column names as strings or `field`/`name`/`headerName` objects) and header-first lists of lists lose identifier columns. |
| ReDoS | All value patterns are bounded: the URL userinfo pattern uses `{0,31}`/`{1,256}`; identifier and `name: value` whitespace uses `[ \t]{0,4..8}`; the bearer/basic lookahead is `{0,512}`. Measured: `"a-"*100k` 91.9s before, 0.09s after; 200k-space identifier and token runs 0.03s. |
| Size caps before sanitize | `/query` reads the body itself: a declared `Content-Length` over `MAX_REQUEST_BYTES` (8 MB) is refused without reading, and a chunked body is cut off at the cap, both with HTTP 413; an invalid body gets 422. A widget payload over `MAX_PAYLOAD_CHARS` (1,000,000) is reported unavailable without parsing. Rows (50), nested lists (200), cells (300 + 512 margin) and text (6000 + 512 margin) are cut before redaction runs. |
| Item 4 | Endpoint and category words are also split on `-`; `confirm*` params (`confirmed`, `confirm_order`) are action-like; `basic <token>` is matched case-insensitively. `tt_order_legs` (`tt/position/order-legs`, a read-only GET of planned legs) now matches `order`, so it was added to `AGENT_READ_ALLOWLIST`; the denied set is unchanged. |

### `/query` auth (finding for the lead; not changed)

- Pre-existing: on base `b886835ce`, `openbb_portfolio/copilot.py` has no auth on `/agents.json` or
  `/query` (it has been that way since #1794). The widget backend's `require_auth` (bearer token
  unless `PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev`) covers `/pi/*` only.
- Workspace (`terminalpro/.../useGetCopilotRequestHeaders.tsx`, `AddCopilotDialog.tsx`): for a
  custom agent it sends only `Content-Type`, `X-Trace-Id` and the user-configured headers or query
  parameters from the "add agent" dialog (key/value, location `headers` or `query`). It does not
  attach its own bearer token (that goes only to the built-in OpenBB copilot). So the agent can be
  protected by asking users to configure `Authorization: Bearer <PI_WIDGET_BACKEND_TOKEN>` in that
  dialog.
- Not changed: the Local Viewer chat (`index.html`) sends no `Authorization` header, so requiring
  the bearer on `/query` in `required` mode would break viewer chat. That is not backward-compatible.
  The exposure is limited: `/query` has no backend data access (widget data comes from the
  caller), but an unauthenticated caller can spend the model proxy's quota. The backend binds to
  loopback by default.
- Option for the lead: call `require_auth` from `/agents.json` and `/query` through an
  `app.state` hook (no-op in `loopback-dev`), and make the viewer send the token, for example as a
  follow-up with #1273.

### Evidence (round 3)

- **Red first** (`.dev-cycle/red3-gh-1272.log`): 22 failed, 62 passed (ReDoS cases excluded from
  that run); ReDoS before the fix: `"a-"*100k` took 91.88s in `redact_text`.
- **Mutation** (`.dev-cycle/mutation3-gh-1272.log`): 18 of 18 killed. The qualified-id, body-cap
  and declared-length mutants survived at first because overlapping guards masked them; new tests
  (`book_id`/`id_portfolio`, chunked body, declared oversize length without reading) kill them.
- **Tests:** portfolio tests + PI agent and mount 130 passed, 1 skipped; MCP chart rows +
  adapter 23 passed. Full PI unit: 2146 passed, 1 failed, 2 skipped; the failure is again the
  wall-clock `test_pi_terminal_f12.py::test_provider_health_never_blocks_on_cold_cache` (1.56s against
  1s on a shared machine), which passed 3 of 3 when rerun alone.
- **CI lint parity** (6 changed non-test files including `agent_privacy.py`): codespell, black and
  ruff clean; mypy `--no-site-packages` and `--platform linux` 0 issues; pylint clean apart from
  local-only C0328.
- **Real path** (`.dev-cycle/realpath3-gh-1272.log`): same flow as before, with body parsing
  through the size-capped reader.

## Round 4: identifier precision (uncommitted on top of `84b911ada`)

- **PRIVACY-2:** `holder`, `investor` and `beneficiary` are *strong* identifier words again
  (`holder_name`, `holderId`), together with the short forms `acc`, `accno`, `acct`, `acctno`
  (`acct_no`) and `email`, `phone`, `login`, `ssn`, `username`. Lowercase run-together keys are
  identifiers when the token ends with a word+id-form compound (`accountnbr`, `primaryaccountid`,
  `portfolioid`) or a strong word (`accountholder`, `useremail`).
- **Over-stripping:** matching is token-aware. A *subject* word (account, user, basket, client,
  customer, owner) is an identifier when it ends the key or sits next to an id form (id, ids,
  uuid, key, no, nbr, num, number, name, email, ref). A *qualified* word (portfolio, book,
  household, member, person) is an identifier only next to an id form. Compounds match only at a
  token's end. Kept: `portfolio_notional`, `portfolio_refresh_ts`, `portfolio_weight`,
  `portfolio_value`, `account_value`, `user_rating`, `basket_return`, `client_count`, `book`.
  Dropped: the id, number, name and email forms. No real matrix column matches.
- **Text form:** a bounded `key=value` / `key: value` pattern masks the value when the key is an
  identifier (`portfolio_id=`, `pm_user:`, `acctNo=`, `Account:`, `holder_name =`); metric pairs
  are kept. CSV, JSON inside a string and Markdown tables without `|` delimiters are documented
  as a known limitation in the README.
- **Evidence:** red first 17 failed, 102 passed (`.dev-cycle/red4-gh-1272.log`). Mutation 13 of 14
  killed; one is equivalent (`holder` is in both the strong set and the strong-suffix list)
  (`.dev-cycle/mutation4-gh-1272.log`). Agent tests 137 passed, 1 skipped; PI agent and mount 18
  passed; MCP chart rows and adapter 23 passed; CI lint parity clean (mypy `--platform linux` 0
  issues). Full PI unit: 2148 passed, 1 skipped, exit 0.
