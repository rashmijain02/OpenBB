# Portfolio Intelligence Native Workspace Terminal: Implementation Plan

**Status:** Planned; design direction approved on 2026-11-19
**Integration target:** `portfolio`
**Scope:** Convert the capabilities demonstrated by the Local Portfolio Viewer
into complete, standards-compliant OpenBB Workspace widgets, app templates, and
agent integration
**Non-scope:** The standalone viewer is reference material only. It will not be
embedded, served as a placeholder, or copied as a custom shell into Workspace.
**Product owner:** Rashmi Jain

## 1. Objective

Make Portfolio Intelligence and TechTrade a first-class OpenBB Workspace
experience that any properly configured operator can install and use through
the supported custom-backend contract.

The result is not a frame around the Local Viewer. Workspace remains responsible
for its native UI primitives:

- application and tab navigation;
- dashboard layout, resizing, and persistence;
- widget discovery and rendering;
- linked parameters;
- tables, charts, metrics, Markdown, files, and notes;
- AI-agent presentation and context;
- standard connector authentication;
- export, duplication, and dashboard customization.

The Portfolio backend remains responsible for:

- stable `/widgets.json`, `/apps.json`, and `/agents.json` contracts;
- real provider/data-engine calls;
- typed widget responses;
- explicit provenance and freshness;
- secure account and symbol validation;
- operational and error states;
- read-only analytics and separately gated paper/live actions.

## 2. Approved design summary

1. Use native Workspace widget types: `table`, `chart`, `metric`, and
   `markdown`, plus other documented types only where a verified requirement
   exists.
2. Reuse and harden the existing 61 Portfolio Intelligence/TechTrade widget
   definitions instead of creating a duplicate catalog.
3. Make the 12-tab Portfolio Terminal and six-tab TechTrade Desk complete native
   apps with correct group/parameter synchronization.
4. Replace viewer-only behavior with backend contracts. Examples:
   - chart inference becomes explicit Plotly or documented `raw` chart
     configuration;
   - viewer hover/glossary logic becomes Workspace column/metric glossary
     metadata;
   - viewer state and re-render behavior becomes app defaults, groups, and
     standard widget state;
   - the viewer's chat pane becomes the supported `/agents.json` + SSE/query
     surface;
   - viewer provenance banners become native status/provenance widgets and
     response metadata.
5. Keep demo fixtures useful but labeled. A missing live provider must not
   silently produce a synthetic success response.
6. Support more than this machine:
   - no hard-coded operator paths;
   - configurable backend origin and connector auth;
   - no dependency on the pinned Workspace checkout being modified;
   - no requirement for a separate browser shell;
   - documented connector setup for self-hosted and hosted Workspace where
     supported.
7. Exclude live order routing, broker mutation, or authorization from this
   initiative. Any paper action remains explicitly sandboxed and gated.

## 3. Current baseline

The Portfolio Intelligence backend currently exposes:

| Surface | Current baseline |
|---|---:|
| Widget definitions | 61 |
| Widget types | `chart`, `markdown`, `metric`, `table` |
| App templates | 3 |
| Portfolio Intelligence Terminal tabs | 12 |
| Terminal widget placements | 81 |
| TechTrade Desk tabs | 6 |
| TechTrade widget placements | 12 |

Relevant implementation areas:

- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json`
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/apps.json`
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py`
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/tier_calls.py`
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/main.py`
- `openbb_platform/extensions/portfolio/openbb_portfolio/copilot.py`
- `openbb_platform/extensions/portfolio/openbb_portfolio/assets/local_viewer/index.html` (reference only)
- `openbb_platform/extensions/portfolio_intel/tests/unit/`

Known work categories already visible in the baseline:

- some `chart` definitions depend on `raw: true` row rendering;
- the Terminal app has many placements but no verified group definitions in the
  manifest inventory;
- several endpoints have demo/fallback-shaped behavior;
- endpoint and manifest tests are split across multiple historical batches;
- the Local Viewer has capabilities that do not automatically map to native
  Workspace contracts;
- provenance and provider-health information exists, but must be normalized
  into a portable first-class experience.

## 4. Success criteria

### Product outcomes

1. A new operator can connect the Portfolio Intelligence backend and discover
   complete, documented apps without knowing the Local Viewer exists.
2. Every app widget is a native Workspace-supported widget and renders through
   the current custom-backend contract.
3. Symbol and account context propagate through each applicable tab without
   manually changing every widget.
4. A chart, table, metric, or Markdown widget never renders blank because its
   endpoint shape and manifest metadata disagree.
5. Missing credentials, unsupported providers, stale caches, partial coverage,
   and upstream errors are distinguishable and visible.
6. Demo responses are explicitly marked as demo and never presented as live.
7. The agent surface uses the supported Workspace agent contract and reads the
   same backend capabilities shown by the apps.
8. Browser acceptance passes in the supported self-hosted Workspace with no
   changes under `third_party/workspace`.

### Engineering outcomes

1. A manifest/endpoint compatibility validator covers all 61 widgets.
2. Every app placement references a known widget.
3. Every parameter group has a valid producer/consumer graph.
4. Contract tests cover every endpoint or explicitly document a non-fetching
   prerequisite.
5. Live provider behavior is opt-in and isolated from deterministic tests.
6. Security, privacy, code, and quality gates pass on the exact change set.

## 5. Scope by workstream

### Workstream A — Capability and contract audit

Create one machine-readable inventory of the native product:

- app ID/name;
- tab and placement;
- widget ID/type/category;
- endpoint and HTTP method;
- input parameter;
- response contract;
- chart/table configuration dependency;
- provider/data source;
- demo/live/cached mode;
- provenance requirement;
- current coverage and failing state;
- browser/fixture acceptance owner.

Use this inventory to classify each widget:

| State | Meaning |
|---|---|
| Native-ready | Manifest and endpoint satisfy current Workspace contract |
| Contract repair | Useful endpoint, but metadata or response shape must change |
| Provider repair | Contract is valid, but live/cached provider behavior is incomplete |
| Explicit demo | Deliberately synthetic and clearly labeled until data is available |
| Gate required | Capability depends on a later approval or separate product phase |
| Remove from app | Unsupported or unsafe for the target application |

The audit is not allowed to remove a capability merely because it is difficult
to render. Any removal or deferral must cite the missing dependency and a
tracking issue.

### Workstream B — Manifest and endpoint contract layer

Add reusable contract validation for:

- allowed native widget types;
- required manifest keys;
- endpoint/ID formatting;
- placement references;
- parameter definitions;
- `raw` chart mapping;
- Plotly `data` requirements;
- table `columnsDefs` matching endpoint row keys;
- metric labels matching endpoint values;
- Markdown scalar response;
- duplicate IDs and invalid app layout;
- parameter/group identity;
- unsupported/deprecated metadata.

Do not add speculative metadata fields. The validator must follow the pinned
Workspace specification and its tests.

### Workstream C — Charts

Define a deliberate rendering decision per chart:

1. **Plotly figure** for candlesticks, financial comparisons, multi-axis
   series, Brinson/waterfall, attribution, and widgets requiring native chart
   semantics beyond simple raw-row mapping.
2. **Documented raw chart** only where the current backend rows plus
   `data.chart` mapping can fully express the visualization.
3. **AG Grid table chart/sparkline** where the user task is primarily tabular
   and the chart is a secondary view.

Requirements:

- no endpoint may return records for a chart that lacks an exact raw mapping;
- no manifest may declare a Plotly chart unless the endpoint returns a figure
  with nonempty `data`;
- empty/stale/error chart states must be explicit rather than blank;
- dates must be normalized and finite numbers enforced;
- chart metadata must include source/provenance where supported;
- the Portfolio Overview and Terminal charts must pass a real Workspace
  browser render, not only JSON shape tests.

### Workstream D — Tables, metrics, and Markdown

For every table:

- map `columnsDefs` to actual response keys;
- keep numeric values numeric;
- use the current supported formatter set;
- define date, percentage, currency, and text semantics;
- add sparklines/chart views only when they help the user task;
- define click-through only to verified, same-contract native widgets.

For every metric:

- align labels with endpoint values;
- define units and glossary keys;
- distinguish unavailable from zero;
- return stable multi-metric ordering.

For every Markdown widget:

- enforce scalar Markdown output;
- sanitize provider-derived values and links;
- use it for context, explanatory insight, provenance, and status—not for
  pseudo-tables that should be native table widgets.

### Workstream E — Native parameter linking

Implement and test Workspace parameter groups:

- research tabs share a single `symbol` group;
- portfolio tabs share a single `account_id` group;
- date/window parameters share only where semantically equivalent;
- chart-mode and widget-specific display controls remain widget-local;
- TechTrade symbol/segment groups link only compatible widgets;
- defaults are synthetic/non-personal;
- no group may merge a different concept merely because parameter names
  happen to match.

Add manifest tests for:

- every group member references the same parameter contract;
- every app placement has compatible group identity;
- changing a group input does not invoke incompatible endpoints;
- grouped widgets can each be opened independently from the Widget Gallery.

### Workstream F — Live, cached, demo, stale, and error semantics

Define a common response or metadata envelope strategy that works across
Workspace:

| State | User-facing rule |
|---|---|
| Live | Current provider response; show provider and observation time |
| Cached | Serve persisted result with cache age and source |
| Demo | Explicit synthetic fixture; never implied to be the operator's data |
| Stale | Last known result plus age and retry/reconnect action |
| Partial | Render valid data plus warning and coverage boundary |
| Unavailable | Do not return a success-shaped empty result |
| Forbidden | Explain permission/entitlement without leaking details |

Implementation rules:

- no `except` branch converts provider failure into fake live data;
- demo mode must be configured or explicitly selected;
- fallback-provider transitions must be observable;
- source/provenance output must not expose credentials or private paths;
- portfolio/account values must not appear in public issue or test evidence.

### Workstream G — Native app UX

Rebuild the product journey using Workspace standards:

1. **Portfolio Intelligence Overview**
   - concise first-look app;
   - X-Ray, What-If, Attribution, provenance and health;
   - suitable for a first-time user with a synthetic demo account.
2. **Portfolio Intelligence Terminal**
   - preserve F1–F11 and Morning Review capabilities;
   - repair layout, group behavior, charts and status surfaces;
   - include only functionality that passes native contract acceptance.
3. **TechTrade Trading Desk**
   - morning scan, workbench, validation, tuning, paper status, and audit;
   - no live execution path;
   - clear distinction between calculation, validation, approval, and paper
     artifacts.

The apps should feel cohesive through naming, descriptions, prompts, groups,
default parameters, layout, and glossary—not by embedding bespoke frontend
code.

### Workstream H — Workspace agent integration

Use the existing supported custom-agent contract:

- maintain `/agents.json` and query/streaming behavior;
- make agent capabilities correspond to real tools/providers;
- expose the same Portfolio Intelligence data boundaries as widgets;
- keep paper actions separately authorized and non-autonomous;
- ensure the agent never receives private credentials through widget data;
- test discovery, initialization, bounded invocation, error handling, and
  unauthorized-action refusal.

The agent is a separate contract from widgets; widget completeness cannot be
claimed from `/agents.json` discovery alone.

### Workstream I — Portability and operator experience

Provide:

- supported backend launcher and stop/status behavior;
- connection instructions for self-hosted Workspace;
- authentication modes and header/token configuration;
- no operator-specific file paths in committed docs;
- CORS/origin configuration appropriate to the selected deployment;
- health endpoint and manifest validation;
- clean demo mode and opt-in live mode;
- backup/data-runbook references for provider caches;
- clear limits and missing entitlements.

The implementation must not edit the pinned `third_party/workspace` source.

## 6. Detailed implementation steps

### Step 1 — Freeze deterministic baseline

1. Record current 61-widget, three-app, endpoint, and test inventory.
2. Add a test that snapshots the capability matrix without duplicating live
   values.
3. Add a current Workspace contract fixture based on the pinned source.
4. Run the existing Portfolio Intelligence focused suite and record unrelated
   failures separately.
5. Record the exact baseline branch/merge-base before future edits.

**TDD evidence**

- inventory test initially fails for unclassified or duplicate placements;
- capability snapshot must be regenerated only through reviewed tooling.

### Step 2 — Build manifest validator

1. Add validator data types/helpers under the widget backend.
2. Validate every widget definition, app placement, group, parameter, and
   response-class hint.
3. Integrate the validator into tests and an operator validation command.
4. Make `/widgets.json` and `/apps.json` fail loudly at development/test time
   if manifests are invalid.

**TDD evidence**

- mutate one widget type, one missing endpoint, one broken group, and one
  invalid chart mapping; each must fail independently.

### Step 3 — Build endpoint contract tests

1. Generate or maintain an endpoint contract table for all 61 definitions.
2. Exercise each endpoint against deterministic fixtures.
3. Assert response type, required keys, JSON safety, and finite values.
4. Assert app placements reference only tested widget IDs.
5. Mark integration-only requirements explicitly rather than skipping silently.

**Review checkpoint A**

- compare the capability inventory, validator, and response tests;
- no approved widget is unclassified;
- resolve manifest test gaps before changing live endpoint behavior.

### Step 4 — Repair chart contracts

1. Inventory every `chart` widget and choose Plotly, raw chart, or table chart.
2. Write failing real-contract tests for Overview X-Ray and Attribution first.
3. Implement the minimal response adapters for those two blockers.
4. Repeat for Terminal and TechTrade chart widgets.
5. Verify figure shapes and raw mappings in self-hosted Workspace.

**Required cases**

- X-Ray sector and country;
- Brinson attribution;
- price history/candle;
- financial statement comparison;
- revenue geography/business line;
- risk volatility;
- paper performance;
- TechTrade scan/segment views.

### Step 5 — Repair table, metric, and Markdown contracts

1. Align every table's columns with actual response keys.
2. Correct formatter values and numeric/date typing.
3. Align metric labels and glossary metadata.
4. Replace pseudo-data Markdown where a table/metric is more appropriate.
5. Add explicit not-available, partial, and stale rendering metadata.

**Review checkpoint B**

- all 61 definitions have a validated response contract;
- no known `200` response produces an unrenderable Workspace widget;
- metric/table/chart fixtures cover boundary values.

### Step 6 — Normalize provenance and provider chain behavior

1. Define the source mode contract.
2. Remove silent synthetic fallback from live provider paths.
3. Make explicit demo mode available for onboarding and tests.
4. Surface provider, tier, cache age, observation time, and partial coverage.
5. Ensure health/provenance widgets use the same state as endpoint responses.
6. Add redaction tests for account/provider configuration.

### Step 7 — Repair app groups and layouts

1. Define research symbol group and portfolio account group.
2. Associate each app placement with the correct shared context.
3. Correct duplicate or non-semantic parameter defaults.
4. Validate the 12 Terminal tabs and six TechTrade tabs.
5. Add user-facing app descriptions and prompts.
6. Keep unrelated widgets independently usable from the Widget Gallery.

### Step 8 — Complete agent integration

1. Compare `/agents.json` capabilities to the final native app inventory.
2. Remove or mark unsupported tools explicitly.
3. Test Workspace agent discovery and initialization.
4. Test read-only Portfolio Intelligence workflows.
5. Keep approval/paper actions outside autonomous agent control.
6. Add denial, invalid input, and unavailable-provider tests.

**Review checkpoint C**

- widget, app, and agent capability inventories agree;
- no model-driven mutation path is exposed by default;
- read-only and paper boundaries pass security/privacy review.

### Step 9 — Portability and connector setup

1. Remove any manifest/endpoint assumptions about a specific local hostname
   except where deployment-specific configuration requires it.
2. Validate self-hosted loopback connector behavior.
3. Document hosted/private-compatible connector boundaries without claiming
   every deployment is allowed to access it.
4. Verify CORS and connector auth against the actual deployment contract.
5. Add clean setup/status/test commands using existing supported launchers.

### Step 10 — Browser acceptance

Using the supported self-hosted Workspace scripts:

1. Start/restart the owned backend stack without editing pinned Workspace.
2. Connect the Portfolio Intelligence backend through the real connector UI.
3. Confirm all 61 widget definitions are discoverable.
4. Open Portfolio Overview and verify each widget.
5. Open each Terminal tab and verify representative render plus group sync.
6. Open TechTrade Desk and verify all six tabs.
7. Exercise live/synthetic provider mode, stale state, and error state.
8. Reload and verify apps/connections persist.
9. Initialize the supported agent surface and perform a bounded read-only task.
10. Capture only redacted, synthetic browser evidence.

### Step 11 — Performance and reliability

1. Benchmark widget endpoint cold and cached p95.
2. Ensure app discovery is fast and cacheable/no-store as designed.
3. Bound provider fan-out from multi-widget pages.
4. Validate refresh behavior does not create uncontrolled duplicate requests.
5. Add retry/backoff only at provider boundaries, not around every widget.
6. Verify a provider outage degrades explicitly without breaking the app.

**Review checkpoint D**

- backend, browser, and performance evidence agree;
- no live/private data appears in evidence;
- no unsupported widget is hidden by the browser test setup.

### Step 12 — Quality and local review

1. Run focused Portfolio Intelligence tests.
2. Run manifest/contract validator tests.
3. Run formatter, Ruff/Pylint/mypy/pre-commit on changed files.
4. Run Workspace authoritative verification and browser acceptance.
5. Invoke local code, security, and privacy review on the same snapshot.
6. Fix confirmed findings with TDD and repeat affected validation.
7. Produce the implementation report with known limitations.

## 7. File-level plan

### Modify

| File(s) | Planned change |
|---|---|
| `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json` | Correct native widget metadata, chart contracts, columns, params, provenance/source labels |
| `.../widget_backend/apps.json` | Complete layouts, groups, prompts, and portable app defaults |
| `.../widget_backend/main.py` | Discovery validation, contract-safe context/provenance behavior |
| `.../widget_backend/widgets_endpoints.py` | Correct native response shapes, states, and provider behavior |
| `.../widget_backend/tier_calls.py` | Typed provider adapters and explicit fallback/provenance semantics |
| `openbb_platform/extensions/portfolio/openbb_portfolio/copilot.py` | Align supported agent contract and data boundaries if needed |
| `.../tests/unit/test_widget_backend*.py` | Expand all-widget shape and manifest coverage |
| `.../tests/unit/test_pi_terminal_*.py` | App, group, chart, layout, and error contract acceptance |
| `docs/operations/portfolio-mcp.md` | Agent and connector operator updates |

### Add

| File(s) | Planned purpose |
|---|---|
| `.../widget_backend/contracts.py` | Typed manifest/response validation helpers |
| `.../widget_backend/provenance.py` | Shared live/cached/demo/stale/partial/error semantics |
| `.../tests/unit/test_widget_backend_contracts.py` | Mutation-resistant manifest validator tests |
| `.../tests/unit/test_widget_backend_matrix.py` | All-widget and all-app capability contract matrix |
| `.../tests/unit/fixtures/native_workspace/` | Synthetic, safe manifests/responses and browser fixtures |
| `docs/operations/portfolio-workspace-terminal.md` | User/operator runbook |
| `docs/reports/portfolio-workspace-terminal-acceptance.md` | Verified evidence and limitations |

Exact names may be adjusted during design implementation, but each concern must
have a dedicated owner rather than being hidden in the Local Viewer.

### Explicitly do not modify

- `third_party/workspace/**`;
- generated Workspace credentials, runtime state, or secrets;
- the Local Viewer as a shipping shell;
- upstream repositories;
- unrelated migration and SitePing files.

## 8. Test strategy

### Unit

- manifest schema and endpoint formatting;
- widget/app reference integrity;
- parameter groups;
- chart adapter outputs;
- table column/row matching;
- metric label/value matching;
- Markdown safety;
- finite numeric/date normalization;
- live/demo/stale/partial source states;
- redaction and input validation.

### Integration

- disposable provider chain;
- FMP Cached and other approved source adapters;
- app discovery;
- backend connector contracts;
- agent discovery and bounded query;
- provider failure, stale cache, partial response, and reauthentication paths;
- database/cache failure without success-shaped output.

### Browser

- all app templates discovered;
- all 61 definitions appear;
- Overview widgets render;
- every Terminal/TechTrade tab opens;
- each chart type renders actual Plotly/AG Grid content;
- table/metric/Markdown render;
- linked symbol/account controls update compatible widgets;
- source state is visible;
- errors are actionable;
- reload persistence passes.

### Performance

Targets are planning defaults and must be measured:

- manifest discovery p95 under 300 ms;
- cached widget responses p95 under 500 ms;
- widget app initial cached render under 1 second per representative widget;
- no duplicate provider request for repeated app-wide group state changes;
- provider work bounded under concurrency.

## 9. Dependency graph

```text
baseline inventory
  -> contract validator
  -> endpoint contract matrix
       -> chart/table/metric/Markdown repairs
       -> provenance/provider-state normalization
       -> app groups/layouts
            -> agent alignment
            -> portability/runbook
                 -> browser acceptance
                 -> performance
                 -> code/security/privacy reviews
```

Dependencies that may run in parallel after the contract matrix:

- glossary/formatter cleanup;
- app prompt/documentation work;
- provenance widget content;
- browser harness preparation using existing synthetic fixtures.

Dependencies that cannot run early:

- final layout repair before response contracts are known;
- live provider acceptance before explicit demo/live state exists;
- agent parity before the final widget capability inventory;
- browser acceptance before chart shape repairs.

## 10. Tracking issues to create after plan approval

The implementation should be split into independently reviewable issues:

1. Audit and freeze the native Workspace capability matrix.
2. Add Workspace manifest and endpoint contract validation.
3. Repair Portfolio Overview chart contracts.
4. Repair Terminal charts and table/metric contracts.
5. Normalize source, cache, demo, stale, and error states.
6. Add native symbol/account parameter groups and finalize apps.
7. Complete and verify TechTrade native Workspace behavior.
8. Align Portfolio Workspace agent capabilities.
9. Add portable operator/connectivity/authentication runbooks.
10. Add real Workspace browser and performance acceptance.
11. Complete code/security/privacy review and release report.

Issue numbers and project placement will be added only after explicit
authorization to create/claim tracker items.

## 11. Release stages

### Stage 0 — Synthetic native contract

All manifests, apps, and endpoints render with deterministic synthetic fixtures.
No operator data or live provider is required.

### Stage 1 — Overview

Portfolio Overview app becomes fully native and passes browser acceptance.

### Stage 2 — Terminal

All Terminal tabs become natively usable, including context groups, chart
repairs, and provenance.

### Stage 3 — TechTrade

TechTrade Desk is validated as read-only/paper-workflow native UX, with explicit
execution boundaries.

### Stage 4 — Agent

Supported agent discovery and read-only workflows are validated against the
same backend capability inventory.

### Stage 5 — Release candidate

Portability, performance, operator runbook, review gates, and rollback evidence
are complete.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Viewer-only behavior has no direct Workspace equivalent | Express the user task through native widget/app primitives; do not invent a custom shell |
| Existing apps contain malformed or incomplete manifests | Freeze and validate the full matrix before feature work |
| Two chart widgets currently return records where Workspace expects a figure | Contract repair with real browser tests first |
| Demo data can be mistaken for live | Explicit source mode, labels, and tests |
| Too many widget requests overload providers | Shared cache, bounded concurrency, and browser request-count checks |
| Parameter groups link semantically different values | Group tests use explicit semantic identity, not just names |
| Agent exposes more than widgets safely allow | Shared capability and authorization review |
| Private portfolio fields leak into responses/evidence | Synthetic defaults, allowlisted output, privacy review |
| Work depends on pinned Workspace internals | Use only documented backend/agent contracts; no submodule edits |
| Local passes but another operator cannot configure it | Portability tests and host-neutral runbook |
| Browser test only checks JSON discovery | Require actual rendered chart/table/metric/Markdown elements and interactions |

## 13. Definition of done

The initiative is complete only when:

- all 61 widget definitions have a tested native Workspace response contract;
- all three app templates are discoverable and valid;
- the Terminal and TechTrade app tabs pass browser acceptance;
- symbol/account groups behave correctly;
- source/live/cached/demo/stale/partial/error states are explicit;
- no known chart renders blank due to contract mismatch;
- agent discovery and bounded read-only workflows pass;
- an operator can connect using documented supported steps;
- no pinned Workspace source was changed;
- focused tests and Workspace verification pass;
- local code, security, and privacy reviews report PASS on the same snapshot;
- an implementation report records measured evidence and remaining limitations.

## 14. Plan approval gate

Approval of this plan authorizes no GitHub write, branch mutation, implementation,
commit, push, or PR by itself.

After approval, the next authorized step is:

1. confirm or create the tracking issue set in `rashmijain02/OpenBB`;
2. create an issue-linked side branch from `origin/portfolio`;
3. begin Step 1 with failing baseline contract tests.
