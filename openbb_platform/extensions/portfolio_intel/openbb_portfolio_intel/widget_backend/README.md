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

## CORS

Locked to `https://pro.openbb.co` on purpose. This backend is a Workspace data source, not a public API. If you're running a self-hosted Workspace, add its origin to `_ALLOWED_ORIGINS` in `main.py` — do NOT open to `"*"`.

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
