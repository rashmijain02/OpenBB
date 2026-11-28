# Plan: HFP-P05 native Hermes web vertical slice (#1342)

Status: **design draft, not committed.** Base `origin/portfolio` @ `5321c620c` (contains #1338/PR #1388, #1339/PR #1389,
#1340/PR #1390, #1341/PR #1393). Branch `feat/hfp-web-vertical-slice-gh-1342`. Parent #1325 (HFP-F03). PF-25 (primary),
PF-26. Sources: `docs/Specs/gh-1312-hermes-financial-planning/spec.md` §6 (plan preview, result sections, metric refs,
"Hermes WebUI integration") and §12 "First end-to-end slice"; `plan.md` §12 "Runtime and browser qualification";
`github-plan/plan.md` HFP-P05 + WEBUI-OWNER; `specs/gh-1338-.../live-acceptance.md` L2; `specs/gh-1341-.../plan.md`.
Synthetic data only. No services, secrets or other-repo edits are part of this plan.

## 1. Existing assets (verified, read-only)

| Asset | File / symbol | Use in P05 |
|---|---|---|
| WebUI extension loader | fork `api/extensions.py` (`HERMES_WEBUI_EXTENSION_DIR`, `_MANIFEST`, `resolve_extension_sidecar_proxy_target`), `docs/EXTENSIONS.md` | Inject OpenBB's JS/CSS. Same-origin only. No backend routes. |
| WebUI sidecar proxy | fork `api/routes.py` `_handle_extension_sidecar_proxy` → `/api/extensions/<id>/sidecar/<path>`. `handle_post` runs `_check_csrf` (Origin/Referer vs Host, `X-Hermes-CSRF-Token` HMAC of the session) first, then `_check_same_origin_browser_request(require_provenance=True)` on every method, persisted consent, and `token-v1` (`X-Hermes-Sidecar-Token`, refused while auth is off). It strips Cookie, Authorization, Origin, Referer, `x-csrf*` and `x-hermes-*`. 10 s timeout, bounded body, no streaming | The single browser path to OpenBB. Auth, origin and CSRF are already enforced by WebUI core |
| WebUI auth / CSRF | fork `api/auth.py` `csrf_token_for_session`, `verify_csrf_token`. `static/index.html` wraps `fetch` so same-origin unsafe calls carry the token. `HERMES_WEBUI_ALLOWED_ORIGINS` is an exact allowlist | Extension fetches get CSRF for free. The origin list stays empty |
| WebUI runtime | fork `api/runtime_adapter.py` (default `legacy-direct` = in-process agent). `HERMES_WEBUI_GATEWAY_*`, `RUNNER_BASE_URL`, `CHAT_BACKEND` select delegated backends. `api/terminal.py` `_TERMINAL_SUPPORTED = sys.platform != "win32"` | Native Windows = in-process Hermes in the WebUI process. The embedded terminal is off on Windows |
| WebUI reconnect | fork `docs/sse-streams.md`: the `/api/chat/stream` run-journal replays from `after_seq`. The turn keeps running in a server thread after the browser goes away. `hermesExt.events` emits `turn:*` and suppresses reconnect duplicates | T03 observes a turn and never re-sends it |
| WebUI extension APIs | `hermesExt.register(id)`, `messages.registerAction` (gives `{sessionId, messageIndex, text}` on click), `storage.forExtension` | "Open OpenBB card" action on assistant messages |
| Prior art | `multi-lora/external/hermes-webui/extensions/{multilora-manifest.json,workshop-hub/hub.js}` (token-v1 sidecar, prompt into composer, user presses Send). `multi-lora/ux-workspace/hub/hub_sidecar.py` + `tests/test_hub.py`. Fork `tests/browser_approval_first_click.py` (Playwright against a real WebUI with isolated state) | Patterns to copy. Nothing is imported |
| Handshake | `hermes_integration/handshake.py` `check_webui` (bind, password, `HERMES_WEBUI_PYTHON` under the runtime venv, `/health`). `hermes_preflight.py` `_check_webui` (agent dir = pinned clone) | Extended with the finance-web env profile |
| Hermes config reader | `hermes_config.py`, fixture `tests/hermes_integration/fixtures/hermes/config-finance-safe.yaml` (`agent.disabled_toolsets: [skills]`) | Extended to the web profile's tool allowlist |
| Run binding | `binding.py` (`binding_key_for_session`, `delivery_key`, `make_pre_tool_call`, `RUN_CREATE`, `DELIVERY_KEYED`), `hermes_plugin/` | Add `story_workflow_start` (binding) and `story_plan_preview` (delivery key) |
| Runs/receipts/outcome | `story_adapters/registry.py` (`RunStore`, `RunBinding`, `ensure_workflow_current`, `ensure_run_open`, `story_run_cancel`), `receipts.py` (`ReceiptLedger`, LOK), `run_outcome.py` `derive_outcome`, `jobs.py` `story_run_outcome`, `story_job_kinds.py` (`KINDS`, `StoryJobKind` Literal, `_require`, `SubmissionLedger`) | Cards read these. Nothing here is re-implemented |
| Runner | `workflow_runner.py` `run_workflow(resume_run_id=)`, `_ARGUMENTS`, `SYNTHETIC_WEIGHTS`; `workflow_admit.py` `build_server`, `server_tool_hashes`; `notebook_guard.py` | A deterministic runner executes the approved plan inside a job |
| Engines | `story_adapters/analytics.py` `story_basket_effective_positions` / `story_concentration` / `story_construction_targets` over `openbb_portfolio_intel.analytics.basket_lookthrough` | The basket x-ray engine. Commodity trusts and single names make no provider call |
| Artifacts | `story_adapters/artifacts.py` `story_artifact_table` / `_list` / `_read` (`ArtifactStore`, sha-checked) | Evidence tables shown in the run card |
| Human approval precedent | `story_adapters/paper_approve.py` (`render_summary` shows the server-stored arguments, never model text) | Same rule for the plan card |
| Browser harness | `openbb_platform/tools/browser_test_harness` (optional extra `[workspace]` = `playwright>=1.45`). System Edge and Chrome are installed. Node v24 is installed. Playwright is **not** installed in `.venv_portfolio` | Headless strategy in §5 |

## 2. Boundary: what lives where (answer to the key question)

**The WebUI fork needs no code change.** Everything is OpenBB code plus WebUI **configuration** through mechanisms
it already has: the extension dir and manifest, a loopback sidecar with `proxy_auth: token-v1`, persisted consent
(Settings → Extensions), the password, and the loopback bind.

| Lives in OpenBB (this PR) | Configuration only (owner, LIVE) | WEBUI-OWNER (not needed; not in this PR) |
|---|---|---|
| Extension bundle (`hfp.js`, `hfp.css`, manifest template), HFP sidecar (card/plan/run/approval/cancel endpoints), `story_plan_preview` + `story_workflow_start` MCP tools, plan store, internal `workflow_run` job kind, `synthetic.basket_xray` workflow, plugin binding for the new tools, preflight `webui_profile` + tool-allowlist checks, probes, tests | WebUI env block (§3.3), Hermes finance-web `config.yaml` (§3.6), consent click, extension-dir ACL + tree pin, ports | Optional later items only: (a) a route-level deny list for owner-session admin routes (workspace file write, settings, gallery install) in a "finance profile"; (b) a durable server-side agent event stream. Neither is needed for P05 acceptance. Each would need its own owner-approved issue in the fork. |

## 3. Architecture

### 3.1 Process ownership (which process runs what)

| Process (interpreter) | Owns | Never does |
|---|---|---|
| WebUI `server.py` (Hermes runtime venv, `HERMES_WEBUI_PYTHON`), `legacy-direct` | Browser session, CSRF, consent, sidecar proxy, **the only Hermes agent loop** (in-process, native Windows) | Run finance tools itself. Its tools are only `mcp__openbb__*` plus `clarify` (§3.6) |
| `openbb-mcp` portfolio-ops (`.venv_portfolio`) | Every story tool route (PolicyGate, admission, receipts). Creates plans/runs. Submits the job | Run an LLM |
| `openbb-jobs` worker (`.venv_portfolio`) | Runs the `workflow_run` job: `run_workflow(resume_run_id=…)` through an in-process `build_server` invoker (same ToolGate, notebook guard) | Call a model or Hermes |
| HFP sidecar `hermes_integration.web.sidecar` (`.venv_portfolio`, `127.0.0.1:<port>`) | Read cards from the same story store. The **human** plan-approval write. Cancel (calls `story_run_cancel` logic) | Start runs, call an LLM, import Hermes or LiteLLM (import-hygiene test) |
| Scheduler | Unchanged (#1341 D4: Hermes cron). P05 adds no schedule | — |

Flow: (1) catalog in the drawer (`GET /workflows`, admitted workflows only) → (2) "Preview" pre-fills a reviewed
starter prompt; the user presses Send (W4) → (3) Hermes calls `story_plan_preview`; the server stores a `pending` plan
and returns `plan_id` + `[[hfp:plan:<id>]]` → (4) the plan card (message action or "Recent") renders the
**server-stored** plan → (5) **Approve** = `POST /plans/<id>/approve` via the WebUI proxy → (6) "Start" pre-fills
`Start approved plan <id>`; user presses Send → (7) Hermes calls `story_workflow_start`; the server checks the
approval, creates the bound run + `workflow_run` job, returns `run_id` → (8) the run card polls `GET /runs/<run_id>`
to a terminal outcome → (9) Hermes's answer cites `[[metric:run:art:field]]` refs; the card hydrates them.

### 3.2 Authentication and explicit origins

- **Browser → WebUI**: password session (`HERMES_WEBUI_PASSWORD`, secret store), bind `127.0.0.1`; `ALLOWED_ORIGINS`,
  `TRUST_FORWARDED_*`, `CSP_*_EXTRA` unset, so the single accepted origin is `http://127.0.0.1:<webui-port>`. Another
  loopback port is *same-site* (cookies are sent), so the origin check, not the cookie, is the tested control.
- **WebUI → sidecar**: `token-v1`; the sidecar reads `HERMES_EXT_SIDECAR_TOKEN_FILE`
  (`<webui-state>/sidecar-auth/openbb-hfp.token`) per request: 503 missing, 401 mismatch (`hmac.compare_digest`);
  `/health` is open and data-free.
- **Sidecar's own checks** (never assumes WebUI ran): `Host` = `127.0.0.1:<port>` (rebinding); reject any `Origin` or
  `Referer` (the proxy strips both, so presence = direct browser call); reject `Sec-Fetch-Site` other than
  `same-origin`/`none`; no CORS headers; POST must be `application/json` (415 for form/`text/plain`); body ≤ 16 KiB,
  closed schemas; principal from server config (`in_process_principal`), never from the request.
- **Model cannot approve**: no MCP tool approves (asserted over `capability_policy_operations.csv`); Hermes has no
  `terminal`/`file`/`web`/`browser`/`code_execution` (§3.6), so it can neither read the token nor reach the sidecar.
  Residual: same-UID code outside Hermes can read the token (fork doc; accepted; separate identity = OPS-ATTEST).

### 3.3 WebUI configuration block (config only; preflight `webui_profile` checks it, never prints values)

Set: `HERMES_WEBUI_HOST=127.0.0.1`, `_PORT=<free>`, `_PASSWORD` (secret store), `_STATE_DIR=<finance webui state>`
(not the everyday WebUI state), `_AGENT_DIR=<pinned hermes clone>`, `_PYTHON=<runtime venv>`,
`_EXTENSION_DIR=<bundle dir outside every git tree>`, `_EXTENSION_MANIFEST=manifest.json`. Unset/default:
`_RUNTIME_ADAPTER` (`legacy-direct`), `_GATEWAY_BASE_URL`/`_API_KEY`, `_CHAT_BACKEND`, `_RUNNER_BASE_URL`/`_API_KEY`,
`_ALLOWED_ORIGINS`, `_TRUST_FORWARDED_HOST|PROTO|FOR`, `_TRUSTED_AUTH_HEADER`, `_CSP_*_EXTRA`, `_ONBOARDING_OPEN`,
`_AUTO_INSTALL`, `_PLUGINS_DIR`. The bundle dir gets the L4-style deny-write ACE + `tree_sha256` pin; gallery installs
write into `EXTENSION_DIR`, so they fail and the pin reports drift.

### 3.4 Shared IDs (all from #1341 except `plan_id`)

| ID | Minted by | Card use |
|---|---|---|
| `plan_id` (`plan_` + 32 hex), `plan_sha256` = canonical JSON {workflow_id, version, `workflow_manifest_sha256`, tool schema pins, access classes, `inputs_sha256`, `expires_at`} | `story_plan_preview` (`story_plans`, PK `(principal, plan_id)`; LOK collapses a re-issued preview onto the pending plan, delivery key `hd-` from the plugin) | Plan card. Approval binds to `plan_sha256` |
| `run_id` (32 hex), `binding` `hs-…` | `story_workflow_start` → `RunStore.create(binding)` in the same `BEGIN IMMEDIATE` as plan `approved→started` (`story_plans.run_id UNIQUE`) | Run card key |
| `job_id`, `operation_id`, `logical_key`, `replay_of` | Internal `workflow_run` submission through `SubmissionLedger` with LOK(run, plan_sha256) | Job line, duplicate evidence |
| `artifact_id` + sha256 | `story_artifact_table` stage | Evidence tables, metric refs |
| `request_id` (paper) | Not created in P05 | Read-only: "approve in terminal" (W3) |

### 3.5 Plan approval (CSRF-safe, one logical operation)

- `GET /plans/<id>` returns the stored plan + an `approval_nonce` (32 random bytes, stored as sha256, one-use, expires
  with the plan). `POST /plans/<id>/approve {plan_sha256, approval_nonce}` = CAS `pending→approved`. Same nonce again →
  200 `already_approved` (first `approved_at`, no change); stale sha or drifted manifest → 409 `plan_superseded`;
  expired → 410; bad nonce → 403. A cross-site page cannot read the GET, so it cannot forge the nonce (on top of the
  WebUI CSRF token and origin check).
- `story_workflow_start(plan_id)` (POST, access `job`) needs `approved` (or `started`), unexpired, recomputed
  `plan_sha256` equal, `ensure_workflow_current`, `ensure_run_open`. On `started` it returns the same `run_id`/`job_id`
  with `replay_of`; a crash between run create and job submit heals on replay (LOK).
- Cancel: `POST /runs/<id>/cancel` reuses `story_run_cancel` semantics; idempotent.

### 3.6 Finance-web Hermes profile (config, validated by code)

`platform_toolsets.cli: [<openbb MCP toolset>, clarify]` (WebUI resolves `cli` in `api/config.py`
`_resolve_cli_toolsets`) **and** `agent.disabled_toolsets` = every other toolset at pin 710fa8a (`terminal`,
`code_execution`, `file`, `web`, `search`, `x_search`, `browser`, `computer_use`, `delegation`, `cronjob`, `skills`,
`memory`, `kanban`, `session_search`, `connections`, `project`, `image_gen`, `video_gen`, `video`, `vision`, `tts`,
`debugging`, `bot_room`, `desktop_ui`, `onboarding`, `catalog`, `discord*`, `feishu_*`, `yuanbao`). The deny list is
the control because a WebUI session can override `enabled_toolsets` (`routes.py` ~18851) and `disabled_toolsets`
subtracts at tool granularity (L4 note): UI hiding is not authorization. Model = private alias via the scoped
LiteLLM key (#1338 L3); a WebUI dropdown choice still hits that key scope.

### 3.7 Explicit unavailable states (rendered verbatim; `partial` is never green)

| Layer | States (each is a sanitized code with a fixed message) |
|---|---|
| Proxy / sidecar | `consent_required` (403 from WebUI), `auth_off` (token-v1 refused), `token_unprovisioned` (503), `sidecar_unreachable` (502), `sidecar_timeout` |
| Catalog / plan | `workflow_not_admitted:<rejection code>`, `plan_expired`, `plan_superseded`, `plan_not_found`, `already_approved`, `runtime_unqualified` (no preflight report newer than 24 h at `HFP_PREFLIGHT_REPORT`) |
| Run | every `derive_outcome` state (`blocked`, `cancel_requested`, `cancelled`, `partial`+`uncertain`, `failed`, `waiting_job`, `awaiting_approval`, `needs_input`, `succeeded`, `running`, `ready`), `worker_unavailable` (job `queued` > 60 s with no worker heartbeat), `run_not_found` |
| Evidence | `artifact_missing`, `artifact_hash_mismatch`, `metric_ref_denied` (field not allowlisted, or a different run), `workspace_link_unconfigured`, `paper_approval_terminal_only` |

### 3.8 Reconnect, observe, duplicate clicks

- Browser session ≠ run lifetime: the run lives in the story store + jobs worker; logout, TTL, tab close or WebUI
  restart never cancel it (only Cancel or `story_run_cancel`). On reconnect the card re-GETs by `run_id` (2 s → 10 s
  backoff, stop at terminal); the WebUI chat turn replays from its run journal.
- The extension **never** calls `/api/chat/start` (pre-fill only), so it cannot start a second agent loop. In-page:
  one in-flight request per (action, id), buttons disabled while pending.
- Server-side, every duplicate (double-click, second tab, model re-issue) is one logical op: approve → 
  `already_approved`; start → same `run_id` + `replay_of`; job → LOK; cancel → idempotent; preview → LOK.

## 4. File layout

```
openbb_platform/extensions/mcp_server/openbb_mcp_server/story_adapters/
  plans.py              # T02 PlanStore (story_plans), story_plan_preview, story_workflow_start, approve_plan() (non-MCP)
  story_job_kinds.py    # T02 INTERNAL_KINDS["workflow_run"] (lazy _require("openbb_agents")); StoryJobKind Literal unchanged
  jobs.py / registry.py # T02 wire plans router; no schema change to existing tools
openbb_mcp_server/assets/capability_policy_operations.csv, capability_policy.json (sha), runtime_profiles.json  # T02
openbb_platform/extensions/agents/openbb_agents/hermes_integration/
  binding.py            # T02 story_workflow_start gets `binding`; story_plan_preview gets delivery key
  handshake.py / hermes_preflight.py / hermes_config.py  # T01 webui_profile env check, bundle pin, tool allowlist
  workflow_runner.py    # T02 _ARGUMENTS for effective_positions / concentration(from output) / artifact_table
  workflows/synthetic.basket_xray.workflow.json          # T02 (single names + commodity trust: zero provider calls)
  web/__init__.py, web/sidecar.py (FastAPI app + uvicorn main, loopback only), web/security.py (host/origin/token/
    content-type middleware), web/cards.py (pure card models from store rows), web/bundle.py (CLI: render manifest
    with sidecar port, copy assets, print tree_sha256), web/web_probe.py (real-path CLI, temp store), web/web_journey.py
    (Playwright journey driver; --stack local|live)
  web/extension/hfp.js (UMD: pure HfpCards logic + DOM glue), hfp.css, manifest.template.json (id openbb-hfp,
    permissions.network_external=false, sidecar loopback token-v1)
tests: mcp_server/tests/story_adapters/test_plans.py;
  agents/tests/hermes_integration/web/{conftest,test_sidecar_security,test_cards,test_bundle,test_webui_profile,
    test_web_probe,test_import_hygiene_web}.py, web/js/hfp_cards.test.cjs (node --test),
    web/browser/{conftest,test_browser_origin,test_browser_cards,test_browser_reconnect}.py (-m requires_browser)
```

## 5. Test strategy and commands (PowerShell 7, worktree root)

Tiers: **A (CI-safe)** pytest with FastAPI `TestClient` + `node --test` (loads `hfp.js` via `require`; no deps).
**B (`-m requires_browser`, no network)**: Playwright Python driving system Edge (`channel="msedge"`, headless, no
browser download); `context.route("**/*")` aborts every non-`127.0.0.1` URL plus `--host-resolver-rules="MAP *
~NOTFOUND, EXCLUDE 127.0.0.1"`, and tests assert zero aborted requests. Stack = the **real pinned WebUI**
(`HFP_WEBUI_DIR`, `HFP_WEBUI_PYTHON` from L2) on an ephemeral port with temp `STATE_DIR`, test password,
`PYTHONDONTWRITEBYTECODE=1`, the generated bundle and consent via `/api/extensions/sidecar-proxy-consent`; beside it the
real sidecar and in-process portfolio-ops + `JobService` worker over a temp store (`web_probe` fixtures). No model:
tests seed plans through `story_plan_preview` as Hermes would. A missing prerequisite skips with an explicit reason,
never a fake pass. **C (LIVE)**: `web_journey --stack live` with native Hermes and the local model (L6).

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = @((Resolve-Path openbb_platform\extensions\agents).Path,(Resolve-Path openbb_platform\extensions\mcp_server).Path) -join ';'
$W = 'openbb_platform/extensions/agents/tests/hermes_integration/web'
& $py -m pytest $W openbb_platform/extensions/mcp_server/tests/story_adapters/test_plans.py -q -m "not requires_browser"
node --test "$W/js"
& $py -m pytest "$W/browser" -q -m requires_browser          # tier B; needs W1 + L2 runtime venv
& $py -m pytest openbb_platform/extensions/mcp_server/tests/story_adapters openbb_platform/extensions/agents/tests/hermes_integration -q   # regression
& $py -m black --check <changed>; & $py -m ruff check <changed>
```
Issue "Command" (replaces "Not yet qualified"): code-only real path `& $py -m openbb_agents.hermes_integration.web.web_probe
--scenario journey --format json`; browser `& $py -m openbb_agents.hermes_integration.web.web_journey --stack local
--browser msedge --format json`; live `... web_journey --stack live --webui http://127.0.0.1:<port> --workflow
synthetic.basket_xray` (owner). Evidence: `.dev-cycle/verify-gh-1342.log` (git-ignored) and `handoff.md`.

## 6. Tasks

### T01: qualify native WebUI delegation and authenticated sessions; cross-origin rejection (CODE-ONLY + LIVE L6a)

Goal: §3.2, §3.3, §3.6 as checks plus the sidecar security layer. Files: `handshake.py`, `hermes_preflight.py`,
`hermes_config.py`, `web/security.py`, `web/sidecar.py` (health + skeleton), `web/bundle.py`, the extension manifest
template.

| Bullet | Red-first tests |
|---|---|
| native delegation (in-process, pinned) | `test_webui_profile_blocks_gateway_or_runner_backend` (each of `GATEWAY_BASE_URL`, `CHAT_BACKEND`, `RUNNER_BASE_URL`, `RUNTIME_ADAPTER=runner-local` → `blocked`, layer `process`); `test_webui_profile_blocks_allowed_origins_and_forwarded_trust`; `test_webui_profile_requires_extension_dir_outside_git_and_pinned` (drift → `failed_layer=schema`); `test_profile_never_prints_env_values` |
| finance profile, UI hiding ≠ authz | `test_finance_web_config_allowlist_only_openbb_and_clarify`; `test_any_enabled_risky_toolset_blocks` (parametrised over §3.6 names); `test_disabled_toolsets_cover_every_pinned_toolset_but_allowlist` (reads the pinned toolset list as a fixture) |
| authenticated sidecar | `test_health_open_and_data_free`; `test_503_without_token_file_401_on_mismatch`; `test_principal_from_config_not_request` |
| cross-origin rejection (sidecar) | `test_rejects_origin_or_referer`; `test_rejects_cross_site_fetch_metadata`; `test_rejects_foreign_host_header` (rebinding); `test_post_requires_json_content_type` (form, text/plain → 415); `test_no_cors_headers_ever`; `test_binds_loopback_only` |
| cross-origin rejection (browser, tier B) | `test_browser_origin.py`: a page served from a second loopback port does `fetch(POST, credentials:"include")` and a `<form>` POST to `/api/extensions/openbb-hfp/sidecar/plans/<id>/approve` → WebUI 403 `origin_mismatch`; a direct call to the sidecar port → 403/401; the plan stays `pending` (read from SQLite); a same-origin call without consent → `consent_required` card state |

Mutations: drop the Origin check → `test_rejects_origin_or_referer` fails; accept `text/plain` → the 415 test fails.
Real path: `hermes_preflight --profile <synthetic-web> --probe none` → `webui_profile` row (code-only), plus `web_probe
--scenario security` → exit 0, every rejection reported with its code and `approvals_written: 0`.
**L6a (LIVE, owner)** extends L2 in `<qual-home>`: start WebUI (§3.3) and sidecar; grant consent in Settings →
Extensions; `hermes_preflight ... --probe loopback` → `webui_hermes` callable, `webui_profile` admitted; one chat turn
lists only `mcp__openbb__*` + `clarify`; record PIDs (WebUI PID = in-process agent loop; `openbb-mcp` and worker PIDs
run the tools).

### T02: plan/run/approval cards with shared IDs and explicit unavailable states (CODE-ONLY)

Goal: §3.4, §3.5, §3.7 and the basket x-ray workflow. Files:
- `plans.py`, `story_job_kinds.py` (internal kind), policy assets;
- `binding.py`, `workflow_runner.py`, `synthetic.basket_xray.workflow.json`;
- `web/cards.py`, `web/sidecar.py` routes, `hfp.js`, `hfp.css`.

| Bullet | Red-first tests |
|---|---|
| synthetic basket x-ray reaches engines, evidence engine-backed | `test_basket_xray_runs_effective_concentration_construction_and_writes_tables` (artifact sha equals the recomputed engine output); `test_basket_xray_makes_zero_provider_calls` (egress guard + seams raise); `test_basket_xray_admitted_with_live_pins` |
| plan preview = stored server facts | `test_preview_stores_pending_plan_with_sha`; `test_plan_card_renders_stored_plan_not_model_text`; `test_reissued_preview_same_lok_returns_same_plan` |
| approval (human only, one op) | `test_no_mcp_tool_can_approve` (policy CSV + live tool list); `test_approve_same_nonce_twice_already_approved`; `test_approve_stale_sha_409_superseded`; `test_expired_plan_410`; `test_bad_nonce_403` |
| start = one run, one job | `test_start_requires_approved`; `test_start_twice_same_run_and_job_replay_of` (row counts in `story_runs` and `job_run`); `test_concurrent_starts_one_run` (two threads); `test_crash_between_run_and_job_heals_on_replay`; `test_start_after_manifest_drift_blocked`; `test_story_job_submit_schema_unchanged` (existing contract pins stay green) |
| shared IDs | `test_hook_binds_workflow_start_and_keys_preview` (`resume/test_binding.py` extension); `test_run_card_shows_run_job_artifact_ids_and_outcome` |
| unavailable states | `test_cards_map_every_outcome_state` (parametrised over `derive_outcome` literals; `partial` is never `ok`); `test_worker_unavailable_after_queue_timeout`; `test_metric_ref_other_run_denied`; JS `hfp_cards.test.cjs`: proxy 403/502/503 → `consent_required`, `sidecar_unreachable`, `token_unprovisioned`; double click → one request; messages show the code, never raw server text |
| browser cards (tier B) | `test_browser_cards.py`: catalog → seeded plan card → Approve (double-click) → start via in-process `story_workflow_start` → run card reaches `succeeded` with the tables; a single row each in `story_plans`, `story_runs`, `job_run` |

Mutations: remove the `story_plans.run_id UNIQUE` lookup → the start-twice test sees 2 runs; skip the nonce hash check
→ the bad-nonce test fails. Real path: `web_probe --scenario journey --format json` → exit 0, `plan: approved→started`,
`runs: 1`, `jobs: 1`, `outcome: succeeded`, `artifacts: 3 (sha ok)`, `duplicates: {approve: 2→1, start: 2→1}`.

### T03: disconnect/reconnect without restart or a second agent loop (CODE-ONLY + LIVE L6b)

Goal: §3.8. Files: `hfp.js` (poll/backoff/resume from `ext.storage` last card id), `web_probe.py`, `web_journey.py`.

| Bullet | Red-first tests |
|---|---|
| reconnect observes | `test_web_probe_reconnect` (the sidecar restarts mid-run; the card GET returns the same `run_id`; the job completes once); JS `test_resume_polls_existing_run_never_posts`; tier B `test_browser_reconnect.py`: reload and network-offline mid-run (the job is held by a test latch) → after reconnect the card shows the same run, `/api/chat/start` was called 0 times by the page, and there is 1 job |
| no restart / no second loop | `test_extension_never_calls_chat_start` (static scan of `hfp.js` plus a runtime fetch spy); `test_sidecar_imports_no_llm_or_hermes` (`sys.modules` after import: no `litellm`, `openai`, `run_agent`, `hermes_cli`); `test_workflow_run_kind_has_no_model_client`; `test_webui_restart_does_not_cancel_run` (probe: kill and restart the sidecar and a fake WebUI session; `story_run_outcome` unchanged) |
| session ≠ run lifetime | `test_logout_or_expired_session_leaves_run_running` (tier B: clear cookies → login again → same run) |

Real path: `web_probe --scenario reconnect` → exit 0, `restarts: 1`, `runs: 1`, `jobs: 1`, `chat_starts: 0`.
**L6b (LIVE, owner, real browser journey)** in `<qual-home>` after L2-L5 and #1341 T04: `web_journey --stack live`
(Edge): select `synthetic.basket_xray` → Preview (Send) → plan card → Approve (double-click) → Start (Send) → close the
tab mid-run, reopen, log in (expect same `run_id`, no new chat turn in the WebUI run journal) → cross-origin attempt
from a second loopback page (expect 403). Expect `run_receipts --run <id>`: 1 run, 1 job, `succeeded`, tables present;
L5 scan of `<qual-home>` `hits=0`. Report exit codes and mismatched lines.

## 7. PR batching

One branch and one PR for T01-T03 (shared sidecar and fixtures; one long-gate run, OM5), commits per task. L6a/L6b
are owner live acceptance recorded on #1342 after merge. Gates: focused + regression pytest, `node --test`, tier B
when W1 is granted (else the skip reason is recorded, never counted as passed), `black`/`ruff`, `codespell`, local
code/security/privacy reviews on the PR diff vs `portfolio` (security mandatory: auth, CSRF, new listener),
`scripts/local_ci.py --merged-with origin/portfolio` or its fallback. No WebUI-fork PR.

## 8. Risks and open questions (recommended answers)

| # | Question / risk | Recommendation |
|---|---|---|
| W1 | Tier B needs `playwright` in `.venv_portfolio` (one-time network install of the harness's existing `[workspace]` extra; no browser download thanks to `channel="msedge"`) | **NEEDS-OWNER-DECISION**: approve the install. Until then tier B skips and acceptance rests on tiers A + L6. |
| W2 | Basket x-ray scope: fund look-through needs N-PORT (network) | P05 uses single names + a commodity trust (zero provider calls). Synthetic N-PORT fixtures and sector view stay in HFP-P10-T01/T03. **NEEDS-OWNER-DECISION** (lead may decide). |
| W3 | Paper approvals in the browser | Out of P05. Cards show `paper_approval_terminal_only` (keep `paper_approve` TTY). Browser paper approval needs its own security design. |
| W4 | Starter: pre-fill the composer vs auto-send | Pre-fill and the user presses Send (Workshop Hub precedent; no hidden agent turns). |
| W5 | New resident listener (sidecar) and port | Allowed: loopback only, behind WebUI. Port chosen after `Get-NetTCPConnection`; start/stop documented in L6, no service install. |
| W6 | WEBUI-OWNER | Close it as "not required for P05". Owner-session admin routes (file write, settings, gallery) stay owner powers; deny ACE + pin cover gallery writes. File the optional fork items only if the owner wants a hard finance profile. |
| R1 | `disabled_toolsets` not applied on the WebUI in-process path, or WebUI `sessionId` ≠ Hermes `session_id` | L6a step 4 proves the tool list. Cards never depend on session identity (IDs come from message text, the Recent list or server rows). |
| R2 | Admitted skills may not load with `disabled_toolsets: [skills]` (L4 note) | Rely on tool descriptions plus the starter prompt text. No skill is required. |
| R3 | Proxy 10 s timeout / no streaming | Short GETs and polling only. Responses are bounded (< 256 KiB) and paged. |
| R4 | Same-site cookie leakage from other loopback apps | Covered by WebUI's origin check, the sidecar's Origin/Host checks and the nonce (tier B test). Never set `ALLOWED_ORIGINS`. |
| R5 | Workspace `/query` copilot loop in this profile (spec §6) | Not enabled by P05. The card links to native Workspace only when configured (`workspace_link_unconfigured` otherwise). |

## Lead decisions (2026-11-28, under the owner's delegation)

- **W1:** approved. Install `playwright` into `.venv_portfolio` from the browser harness's existing `[workspace]` extra. Drive the installed system Edge only (no browser download), with every non-loopback request aborted. If installation fails, the browser tier skips with a recorded reason and never counts as passed.
- **W2:** P05 scope is the synthetic basket x-ray with no fund look-through. N-PORT fixtures and the sector view move to HFP-P10.
- **W3:** paper-action approvals stay terminal-only; the cards show `paper_approval_terminal_only`.
- **W4:** starter prompts pre-fill the chat box and never auto-send.
- **W5:** a loopback-only sidecar listener behind WebUI is accepted, with its port chosen after a conflict check. No service is installed.
- **W6:** no WebUI-fork code change is required for P05. WEBUI-OWNER is not needed beyond configuration, the consent click and the extension-directory ACE/hash pin, which are owner LIVE steps. The two optional fork items stay out of scope.
