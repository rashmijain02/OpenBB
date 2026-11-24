# Portfolio-Intel Workspace backend (#1007)

Custom-backend widgets for [OpenBB Workspace](https://pro.openbb.co) that expose the `portfolio_intel` analytics modules as Workspace-consumable widgets.

Follows the canonical Workspace custom-backend contract documented in [OpenBB-finance/backends-for-openbb](https://github.com/OpenBB-finance/backends-for-openbb).

## Run locally

From the repository root, use the supported PowerShell launcher:

```powershell
# Loopback-only development:
.\scripts\run_widget_backend.ps1

# Auto-reload:
.\scripts\run_widget_backend.ps1 -Reload

# Explicit bearer authentication:
$token = Read-Host -MaskInput "Portfolio Intelligence bearer token"
.\scripts\run_widget_backend.ps1 -AuthMode required -Token $token
```

The launcher always binds to `127.0.0.1` (port `6120` by default), rejects
port conflicts, and explicitly configures either `loopback-dev` or `required`
authentication. Confirm it is up:

```powershell
Invoke-RestMethod http://127.0.0.1:6120/widgets.json
```

The local viewer at <http://127.0.0.1:6120/viewer> is only a preview harness.
It is never a replacement for the real Workspace UI at <https://pro.openbb.co>.

## Connect to Workspace

1. Open <https://pro.openbb.co>.
2. **Data connectors → Custom backend → Add**.
3. Name: `portfolio-intel`, URL: `http://127.0.0.1:6120`.
4. Save. Workspace fetches `/widgets.json` and adds the widgets under the **Portfolio Intelligence** category.
5. The pre-built **Portfolio Intelligence — Overview** app appears in your apps list (from `/apps.json`).

## Widgets shipped in this backend

| Widget id | Type | Endpoint | Wraps |
|---|---|---|---|
| `pi_xray_sector` | `chart` (Plotly pie; `raw=true` rows) | `/pi/xray/sector` | `analytics.xray` sector breakdown |
| `pi_whatif_diff` | `markdown` | `/pi/whatif` | `analytics.whatif` diff engine (#558) |
| `pi_brinson_attribution` | `chart` (Plotly bars; `raw=true` rows) | `/pi/attribution` | `analytics.attribution_engine` (#559) |

Each endpoint is a **thin adapter** over an existing analytics module. No new financial math lives in this backend — the shape is:

```
Widget → HTTP endpoint → analytics.<module> → JSON response
```

## Add a new widget

1. Add an entry to `widgets.json` (name, description, type, endpoint, gridData, params).
2. Add the FastAPI route to `main.py` returning data matching the declared `type`. Every
   response states its data state (live, cached, demo, stale, partial or unavailable) through
   one model, `provenance.py` (#1269); see "Data state and provenance" below.
   - `markdown` → return a non-empty str; decorate with `@widget("markdown", demo=...)`, which
     appends a `**Data state:** <State>` line.
   - `chart` → return the rows and wrap the route with `terminal_charts.plotly_chart(builder,
     demo=...)` (#1268): the default response is a Plotly figure with no `layout.title`
     (Workspace shows the widget name), the record in `layout.meta` and, unless live, an
     annotation; `raw=true` returns the rows.
   - `table` → return a list of dicts and decorate with `@widget("table", demo=...)`, which adds
     the `data_state` / `data_source` / `data_as_of` columns. Label enum codes and row
     identifiers in the response (`table_contracts.relabel`); a column's glossary is its
     `headerTooltip` (the Local Viewer glossary summary). Workspace's schema rejects
     `glossaryKey`, `valueLabels`, `rowLabels` and `data.metricGlossary` (#1268).
   - `metric` → return Workspace metric cards via `table_contracts.metric_cards` (shows
     `Unavailable` instead of placeholder numbers) and decorate with `@widget("metric", ...)`,
     which appends the `Data State` card.
3. Reference the analytics module rather than reimplementing math.
4. Add a smoke test in `tests/unit/test_widget_backend.py` that hits the endpoint via `TestClient` and asserts the shape matches the widget type contract.
5. Declare a `symbol` param as `"type": "ticker"` and an `account_id` param as `text` with
   the demo option (`{"label": "Demo account (synthetic)", "value": "demo"}`), so the widget
   works alone from the Widget Gallery and can join the app groups below.

## Apps, parameter groups and prompts (#1270)

`apps.json` uses only `apps-schema.json` keys. Shared context lives in `groups`, never in an
app-level `params`:

| App | Group 1 | Group 2 |
|---|---|---|
| Overview | `ticker` (AAPL): What-If | `param` `account_id` (demo): X-Ray sector |
| Terminal | `ticker` (AAPL): every symbol widget, F1-F11 | `param` `account_id` (demo): every account widget |
| TechTrade | `ticker` (AAPL): scan table (discovery) and every symbol widget | none (no account widget) |

Every placement of a member lists the group in its `groups`, and grouped presets in
`state.params` equal the group `defaultValue`. Workspace syncs a ticker group only into a
`ticker`-typed param, and a `param` group only into a param with inline `options`;
`contracts.py` checks both, plus no overlapping placements per tab and preset values that are
real options (empty `options` accept anything; a multi-select value must contain an option, as in
`isValidParamOption`). Suggested agent questions live in `prompts` and read as plain questions,
without notebook ids, issue numbers or wiring notes (a test enforces this). The Terminal's
ten-step weekly review is one prompt per step
(`Weekly review, step <n> of 10 (<tab> > <widget>): <question>`).

## Data state and provenance

`provenance.py` defines `DataState` (live, cached, demo, stale, partial, unavailable,
forbidden) and a `Provenance` record (state, source, as-of, reason). The record is built once
per request from the serving tier (`record_tier_used`), an explicit `mark(...)` by the
endpoint (unavailable accounts, snapshot freshness, probe results) or the decorator's `demo`
reason, and rendered per widget type:

| Type | Where the state lives |
|---|---|
| chart | `layout.meta` = `{state, source, asOf, reason}` plus an annotation unless live |
| table and `raw=true` rows | `data_state`, `data_source`, `data_as_of` string columns on every row (`data_source` / `data_as_of` are `hide: true` column defs where a widget declares `columnsDefs`) |
| metric | trailing card `{"label": "Data State", "value": "<State>: <reason>"}` |
| markdown | closing `**Data state:** <State> - <reason>. Source: ...; as of ...` line |

The `X-PI-Data-State`, `X-PI-Data-Source` and `X-PI-Data-As-Of` headers come from the same
per-request record, so they always match the body. A 401/403 stays an error with
`X-PI-Data-State: forbidden` and no data. `as_of` is only what was observed (snapshot session,
probe time, or the UTC time the backend read its own state); provider tiers report `unknown`.
`fmp_cached` serves persisted provider responses, so it is `cached` (as-of `unknown`); only real
provider calls are `live`. `contracts.collect_response_issues` fails any widget response without
a valid state. Harness fixtures normalize only those observation times
(`openbb_browser_test_harness.normalize`).

### Demo mode (`PI_DEMO_MODE`)

| Value | Behaviour |
|---|---|
| `fallback` (default) | The stub answers when no provider does, always labelled `demo` in body and headers. |
| `off` | No synthetic fallback: when no provider answers, the widget is `unavailable` with a reason and no sample values. Selecting `account_id=demo` / `basket_id=demo` is explicit and still shows the labelled synthetic book. |
| `only` | Onboarding and tests: provider tiers are never called; every widget serves labelled demo data. |

Responses never echo a non-demo account identifier, credential or home path (redaction test:
`tests/unit/test_demo_mode_redaction_1269.py`).

## TechTrade Desk (#1271)

Six tabs, twelve placements, all read-only views of persisted EOD snapshots (state `cached`,
`stale`, `partial` or `unavailable`, source `eod-snapshot`, as-of the snapshot session).

| Widget | Native contract |
|---|---|
| `tt_segment_movers` | Plotly bar of each segment's strongest mover (`change_pct`, label = symbol); `raw=true` returns `{segment, symbol, change_pct, bucket}` rows (`techtrade_charts.py` via `plotly_chart`) |
| `tt_simulate_result` | Plotly line of marked P&L by simulation day; `raw=true` returns the `techtrade.simulate` rows |
| `tt_scan_table` | Row array (no `{"rows": ...}` envelope, no `dataKey`) with `columnsDefs`; the Symbol column is `cellOnClick` / `groupBy` `symbol`, and a hidden (`show: false`) `ticker` param `symbol` lets the click drive Group 1 (pinned `useCellOnClickHandler` only updates a ticker group from the clicking widget's own ticker param). The endpoint ignores `symbol` |
| order legs, validation, tuning, audit | Row arrays with provenance columns (no `columnsDefs`: their rows are engine-defined) |
| signal, plan, export, engine status, Execute Bridge, paper status | Markdown with a closing data-state line |

No snapshot, or a completed run with no rows, is `unavailable` with a reason that says which:
a trace-free figure with an annotation, or one note row. A footnote on each figure repeats the
snapshot disclaimer (planning snapshot, not a live quote) and any survivorship or earnings
warning.

**Execution boundary.** Every TechTrade widget endpoint (and `pi_paper_ticket`) is a GET route
that never reaches an order seam (paper/live broker adapters, paper engines, batch sink) or
writes a file, whatever `verdict`/`confirm` it is sent. The Execute Bridge only reports
readiness. Orders exist only behind `POST /tt/execute/write-batch` with
`PI_ALLOW_T5_EXECUTE=true` + `verdict=PASS` + explicit `confirm`, and `POST
/tt/execute/cancel` with its order-bound confirmation phrase
(`tests/unit/test_techtrade_native_1271.py` proves each denied path and a positive control).
`/tt/execute/paper-status` (JSON and Markdown) shows the paper account through
`account_display()`, and the snapshot store logs its SQLite fallback `~`-relative or by file name.

## CORS

Exact origins only: `https://pro.openbb.co` and the self-hosted Workspace `http://127.0.0.1:1420` by default. This backend is a Workspace data source, not a public API. For another Workspace origin set `PI_WIDGET_BACKEND_ALLOWED_ORIGINS` (comma-separated); a wildcard, `null` or an origin with a path stops startup. See [Operator setup](#operator-setup).

## Operator setup

Portable setup for any OS and deployment (#1273): the cross-platform launcher
`python -m openbb_portfolio_intel.widget_backend.serve start|status|stop|run`,
auth and header configuration, CORS origins, `/health` liveness and the
authenticated `/health/details`, startup manifest
validation, demo versus live mode, access-log redaction, limits, and
provider-cache backup references are in the
[Portfolio Intelligence operator setup guide](../../../../../docs/operations/portfolio-intelligence-operator-setup.md).

## Authentication

`/pi/*` routes are gated by a bearer token. Policy is set at import time by two env vars:

| `PI_WIDGET_BACKEND_AUTH_MODE` | `PI_WIDGET_BACKEND_TOKEN` | Behavior |
|---|---|---|
| **`required`** (default) | set | Every `/pi/*` request needs `Authorization: Bearer <token>`. Compared constant-time via `hmac.compare_digest`. |
| `required` | unset | **Startup fails fast** with a clear error. This is by design — running the default mode without a token is a config bug. |
| `loopback-dev` | any | No auth. Operator explicitly opted out. Logs a WARN on startup. **Never bind off-host in this mode.** |
| anything else | any | Startup fails with `invalid auth mode`. Typos are loud, not silent auth-disables. |

The auth decision is made **only** from these env vars — never from `request.client.host`, `X-Forwarded-For`, or bind address. A proxy claiming loopback origin cannot bypass auth.

Discovery endpoints (`/widgets.json`, `/apps.json`, `/`) are unauthenticated by design — Workspace fetches them anonymously on connect. That's the contract, not an oversight.

### Running locally

Use `.\scripts\run_widget_backend.ps1` for explicit loopback development, or
pass `-AuthMode required -Token $token` as shown above. Configure Workspace's
custom backend to send the same bearer token when required mode is enabled.


Reverse-proxy the backend behind Cloudflare Access / Tailscale / IAP if it's reachable off-host. The bearer token is a floor, not a moat.

## Input validation

All user-supplied params are validated against strict allowlists before echoing into response bodies or engine kwargs:

- `symbol` / `benchmark_symbol` → `^[A-Z0-9.\-]{1,10}$` (ticker allowlist, covers `BRK.B`, `BF-A`, `AAPL`, etc.).
- `account_id` → `^[A-Za-z0-9_.\-]{1,64}$`.
- `window` → fixed enum `{1M, 3M, 6M, 1Y, YTD, MTD}`.
- `delta_shares` → parsed as int; bad input returns a generic markdown error that does NOT reflect the user value.

Reject-and-400 rather than silently coerce; the widget shows a Workspace-side error indicator rather than a corrupted render.

## Follow-ups tracked separately

- Account resolver — `xray_sector` currently returns demo data for any non-`demo` `account_id`; wire to `PositionStore` in a follow-up PR against the paper program.
- What-If full plumbing — `whatif` returns a stub; the structured diff (#558) needs a positions store + price fetcher wired in.
- Brinson live book — `attribution` uses a #935 golden fixture as the demo book; live wiring waits on the #543 index-constituent history feed.

## What this replaces

The `desktop/src/pi/` canvas from #981 / #982 / #1004 was a scope error — that shipped a bespoke React canvas which is NOT how Workspace consumes widgets. It stays in the tree as a **local preview harness** (headless smoke testing of the SDK contract), but the shipping surface for portfolio-intel widgets is THIS backend + Workspace as the frontend.

## Workspace agent (#1272)

This backend also serves the custom Workspace agent (`/agents.json` and `/query`, from
`openbb_portfolio.copilot`). It answers through the local model proxy and is read-only.

**Where your data goes.** To answer, the agent sends the data of the widgets you select to the
model behind `COPILOT_PROXY_BASE_URL`. With the default `copilot-api` proxy that is GitHub
Copilot, an external model provider. Account, basket, owner and user identifier fields are
removed and credentials are redacted first, but holdings, weights and other values in the
selected widgets do leave this machine. Do not select widgets whose data you do not want sent.

- **Discovery.** `/agents.json` advertises `streaming` and `widget-dashboard-select`, and
  nothing else. Widget access is advertised only because this backend registers an agent
  inventory on `app.state` (`agent_policy.build_agent_capabilities()`, built from
  `widgets.json`); a backend without one stays text-only.
- **Reads.** The agent reads the widgets the user selected through Workspace's own
  `get_widget_data` call, and only widgets whose Workspace origin is this backend: the
  connector name `portfolio-intel` (see "Connect to Workspace"), or the comma-separated names
  in `PI_AGENT_WIDGET_ORIGINS` if you named the connector differently. It has no HTTP client or backend token of its own. It passes each
  widget's current parameters unchanged and adds `raw=true` for chart widgets, so it gets rows,
  not Plotly figures. At most 8 widgets, 50 rows per widget and 24,000 characters of context
  per question; a widget that does not fit is left out and named as omitted. The model answer has a time limit (`COPILOT_PROXY_TIMEOUT_SECONDS`, default 60)
  and a token cap.
- **Denied.** Safe by default: any widget that looks like an action (a `confirm` parameter, an
  execute / paper / backtest / order endpoint or category, a non-GET method) is denied unless it
  is on `agent_policy.AGENT_READ_ALLOWLIST` (the read-only paper blotter, performance and KPIs,
  execute bridge, paper status and TechTrade order legs). `pi_paper_ticket` (order-ticket action; places no order since #1271) and
  `pi_backtest_button` (queues a job) are refused and never requested; widgets outside the
  inventory are refused too. Paper and
  execution actions stay separately authorized in the widget itself. The MCP exposure policy
  denies the same two endpoints; `test_agent_capabilities_1272.py` keeps the lists equal and
  the inventory equal to `tests/unit/fixtures/native_workspace_matrix.json`.
- **Provenance.** Each widget's `data_state` / `data_source` / `data_as_of` (row columns, the
  `Data State` metric card, the Markdown `Data state` line, or a figure's `layout.meta`) is
  shown as a reasoning step and given to the model, which must say when data is demo, cached
  or unavailable.
- **Credentials and identifiers.** The request's `api_keys` and tool tokens are never sent to
  the model. Credential-like fields (`apiKey`, `authToken`, `sessionId`, ...) and values
  (bearer/basic tokens, JWTs, AWS keys, `key=`/`sig=`/`token:` values, `user:pass@` in URLs)
  are redacted. Identifier fields (account / acct, basket, owner, user, customer, client,
  `portfolio_id` and similar, matched by name token at any depth) are dropped, and so are
  identifier columns in column-oriented payloads and in Markdown tables. Metrics about such an
  entity (`account_value`, `portfolio_notional`, `user_rating`, `client_count`) are kept; holder,
  investor and beneficiary names and the id / number / name / email forms are dropped. In
  free text, `key=value` and `key: value` pairs with an identifier key (`portfolio_id=…`,
  `pm_user: …`, `Account: …`) are masked. Redaction uses only linear-time patterns.
- **Known limitation.** CSV text, JSON embedded inside a string, and Markdown tables without
  `|` delimiters are not parsed. Identifier columns in those forms are caught only where a
  `key=value` / `key: value` pair names them, so do not select widgets that return identifiers
  in those shapes.
- **Size caps.** `/query` bodies over 8 MB get HTTP 413, and any widget payload over 1,000,000
  characters is reported unavailable without being parsed. Rows, nested lists and strings are cut
  to their limits before redaction runs.
- **MCP.** The MCP adapter forces `raw=true` on the cloned chart tools, so MCP clients also get
  rows with the provenance columns.
