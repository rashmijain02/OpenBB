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
| MCP `test_portfolio_intel_adapter.py` (endpoint and dependant identity) | Passes unchanged (middleware, not a new endpoint). |
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
