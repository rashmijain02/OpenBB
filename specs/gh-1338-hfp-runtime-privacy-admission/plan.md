# Plan: HFP runtime provenance and privacy admission (#1338, #1339)

Status: **design draft, not committed.** G1 approved 2026-11-28; SOURCES-PINNED = owner forks (below);
**PRIVATE-APPROVAL not granted**, so every task uses synthetic private-shaped sentinels only.
Base: `origin/portfolio` @ `75f442402`. Parent: #1323 (HFP-F01). Design sources:
`docs/Specs/gh-1312-hermes-financial-planning/` spec.md §4.8, §11; plan.md §4, §7, §12; research.md §9;
github-plan/plan.md (HFP-P01/P02, External prerequisites).

Scope: #1338 (HFP-P01, qualify native runtime provenance and connection health) and #1339 (HFP-P02,
enforce private data and immutable skill boundaries). No product code in this document.

## 0. Facts observed while planning (metadata only)

| Fact | Consequence |
|---|---|
| The **installed** native Hermes (under `%LOCALAPPDATA%\hermes`) is upstream `NousResearch/hermes-agent` @ `bf0203a7`. It is an ancestor of the pinned fork `710fa8a0` and **1194 commits behind** it. That home is the owner's live one: memories, sessions, `state.db`, `auth.json`, `.env`, `gateway.pid`. | The pinned runtime is not installed. A preflight that inspected the default `HERMES_HOME` would qualify the wrong origin. Qualification needs an isolated `HERMES_HOME` (decision O1). |
| Running any `hermes` binary touches its `HERMES_HOME` (locks, config migrations at `_config_version: 52`, `skills_sync` seeding). | CODE-ONLY checks never execute Hermes. They read git metadata, `pyvenv.cfg` and YAML only. |
| WebUI `start.ps1` auto-discovers the agent: `HERMES_WEBUI_AGENT_DIR`, then `$HERMES_HOME\hermes-agent`. Its default is in-process Hermes, and `HERMES_WEBUI_PASSWORD` is unset by default. README: `bootstrap.py` is unsupported on native Windows, so `start.ps1` is the only native path. | Without `HERMES_WEBUI_AGENT_DIR`, the WebUI would load the upstream install. This is the first **wrong-origin** regression case. Unauthenticated WebUI must block. |
| Hermes requires Python `>=3.11,<3.15` and "we only support 3.14". Its compiled wheels are cp314. OpenBB `.venv_portfolio` is CPython 3.12.15. | An in-process WebUI on a non-3.14 interpreter is an **ABI** case. The preflight runs in 3.12 and must never import Hermes. |
| Hermes defaults at the pin include `model.provider: auto`, `auxiliary.*.provider: auto`, `fallback_providers: []`, `delegation.fallback_providers`, `auth.adopt_external_logins: true` (adopts Claude Code/Codex logins), `memory.memory_enabled: true`, `curator.enabled: true`, `background_review.enabled: true`, `skills.project_discovery: true` and `telemetry.shared_metrics.enabled: false`. | Each of these is a hosted-fallback or memory vector. The route policy must require explicit safe values, not just defaults. |
| Hermes skill precedence: trusted project > local (`$HERMES_HOME/skills`) > `skills.create_dir` > `skills.external_dirs`. `create_dir` is a **search root**, so skills written there are loaded. | A "quarantine" inside any search root is not a quarantine. Proposals must land outside every root (see 1339-T02). |
| Existing LiteLLM (`..\litellm\claude-proxy.yaml`, proxy venv litellm **1.106.6**, checkout 1.109.0) has six aliases, all `github_copilot/*` (hosted). There is no `litellm_settings` and no fallbacks. It uses one `master_key`, and request history goes to local Postgres :5433. It listens on 127.0.0.1:4000 and serves the lead's session. | No alias resolves to local inference, so private routes must report BLOCKED today. That is the correct fail-closed outcome. Binding aliases needs proxy edits and a restart (O4). |
| No local inference runtime: no `ollama`, `llama-server` or `lms` on PATH, and no listener on 11434, 8080 or 1234. MySQL84 runs on 127.0.0.1:3306. | Live private-route qualification waits on a runtime choice (O3). |
| `fmp_cached` resolves the database from `user_settings.json` or `DB_NAME`. Its **default is `openbb_fmp_cache` (old copy)**; the live store is `openbb_fmp_cache_test` (only via setting or `FMP_CACHE_TEST_MODE`). | This is a concrete **wrong-database** regression case (O7 confirms the expected name). |
| `openbb_agents` is **not installed** in `.venv_portfolio`. Its tests use `sys.path.insert`, and `litellm`, `psutil` and ADK are absent; pydantic 2.14, PyYAML 6.0.3, `mcp` 1.30 and pytest 9.2 are present. | The new code uses only pydantic, PyYAML, stdlib and `mcp`. It has no `litellm` import and does not import `openbb_agents.config` (that module probes hosted candidates with auto-fallback, which research.md §7 forbids inheriting). |

## 1. Pinned sources

| Component | Repo / ref | SHA | Licence | Native Windows launch (qualification only, isolated dirs) |
|---|---|---|---|---|
| Hermes Agent (pinned) | `rashmijain02/hermes-agent` `main` (local clone `..\..\hermes-agent` relative to the workspace root) | `710fa8a073f9a8136e10749b083a16779341faef` | MIT (`LICENSE`, (c) 2025 Nous Research) | `$env:HERMES_HOME=<qual-home>; $env:HERMES_RUNTIME_DIR=<qual-runtime>; pwsh .\setup-hermes.ps1 -RuntimeOnly; .\activate.ps1; hermes ...` (entry point `hermes = hermes_cli.main:main`; downloads the pinned uv and Python 3.14 into `HERMES_RUNTIME_DIR`) |
| Hermes Agent (installed, **not** pinned) | upstream `NousResearch/hermes-agent` | `bf0203a794a07aac3ff764972ab9087baa4e4f4e` | MIT | `%LOCALAPPDATA%\hermes\bin\hermes.exe`. Never used for qualification. Reported as `wrong_origin`. |
| Hermes WebUI | `rashmijain02/hermes-webui` `multilora-ux` (copy at `multi-lora/external/hermes-webui`) | `22d984026c305dfbadd09f29482be6cefe0f028b` | MIT ((c) 2025 Hermes Web UI Contributors) | `$env:HERMES_HOME=<qual-home>; $env:HERMES_WEBUI_AGENT_DIR=<pinned clone>; $env:HERMES_WEBUI_PYTHON=<Hermes 3.14 python>; $env:HERMES_WEBUI_STATE_DIR=<qual-home>\webui; $env:HERMES_WEBUI_PASSWORD=<from secret store>; pwsh .\start.ps1 -BindHost 127.0.0.1 -Port <free>` then `GET /health` |
| LiteLLM gateway | existing local install, `..\litellm` (not a pin, reused) | runtime litellm 1.106.6 (proxy venv); checkout 1.109.0 | MIT (LiteLLM OSS) | Existing `litellm-copilot-start` on 127.0.0.1:4000. **Never started, stopped or contacted by agents.** |
| OpenBB | this repo, `portfolio` | `75f442402` | per repo | `.venv_portfolio` (CPython 3.12.15) |

Pins live in a committed synthetic profile (§2). The owner's real profile lives outside the repo
and is selected by `OPENBB_HERMES_PROFILE`; no drive letters or user paths appear in code.

## 2. Package and file layout

**Confirmed:** `openbb_platform/extensions/agents/openbb_agents/hermes_integration/`, as proposed in plan.md §14.
`openbb_agents` already holds sibling, self-contained policy code (`notebook_guide/` with pydantic
`extra="forbid", frozen=True` contracts, pure-function readiness and network-denied tests) and the
PII guardrail. HFP-P05 and later build on this package. No new distribution is needed.
Constraints:

- `hermes_integration` never imports `openbb_agents.config`, `litellm`, ADK or Hermes. An AST test enforces this.
- It reuses `openbb_mcp_server.service.capability_provenance.normalize_import_origin`, which yields
  `repo://`, `site-packages://` and `external://<sha12>/...` without absolute paths. That code is installed
  editable from the main checkout and is unchanged here, so the import is safe from a worktree.
- It reuses the `AccessClass` vocabulary from `openbb_mcp_server.models.capability` for the existing classes.
  New household classes are local to `access.py`.

```
openbb_agents/hermes_integration/
  __init__.py            # no side effects
  models.py              # 1338-T01: HealthLevel ladder configured<authenticated<admitted<callable<qualified;
                         #   FailedLayer {process, module_origin, abi, config, auth, route, backend, database,
                         #   schema, skills, egress}; Presence {present, absent} for any secret-shaped field;
                         #   ComponentReport, PreflightReport (extra=forbid, frozen)
  profile.py             # 1338-T01: FinanceRuntimeProfile (expected SHAs, remotes, python tag, db name,
                         #   gateway base_url, private alias allowlist, skills roots) YAML loader
  provenance.py          # 1338-T01: git origin/SHA/dirty, licence hash, pyvenv.cfg version, module origin,
                         #   fmp_cached db-name resolver (reads only db/host/port keys; creds -> Presence)
  hermes_config.py       # 1338-T02/T03, 1339-T02/T03: metadata-only Hermes config.yaml reader -> RouteFacts,
                         #   SkillFacts, MemoryFacts (secret-shaped keys -> Presence; never echoes values)
  litellm_config.py      # 1338-T03: proxy YAML reader -> AliasFacts (backend kind, api_base locality,
                         #   fallbacks, retries, callbacks, logging flags); os.environ/X -> env name + Presence
  handshake.py           # 1338-T02: probe matrix with injected transports; loopback-only; never starts,
                         #   installs or falls back
  hermes_preflight.py    # CLI: python -m openbb_agents.hermes_integration.hermes_preflight
                         #   --profile P [--hermes-config F] [--litellm-config F] [--openbb-settings F]
                         #   [--probe none|loopback] [--format json|text]; exit 0 qualified, 2 blocked, 3 usage
  access.py              # 1339-T01: Principal x Operation x Scope capabilities, PolicyGate default-deny
  skills_admission.py    # 1339-T02: admitted-skill manifest (sha256 tree), drift/shadow/writability checks,
                         #   quarantine outside every Hermes search root
  projection.py          # 1339-T03: field allowlist EvidenceProjection, PrivateMetricRef, sentinel scanner
  egress_guard.py        # 1339-T03: loopback-only socket guard (records and refuses non-loopback connects)
  policy_probe.py        # 1339-T01/T03 real path: stdio MCP client against the gated server (synthetic env)
openbb_agents/mcp_server.py   # 1339-T01: opt-in `--policy-profile hermes-finance` gate at the call_tool seam;
                              #   default behaviour unchanged
tests/hermes_integration/
  conftest.py            # sys.path insert (importlib mode), tmp HERMES_HOME/HOME, deny non-loopback network,
                         #   SENTINELS (e.g. acct "ZZ-000000001", amount "$4,242,424.42", name "Sentinel Q. Owner")
  fixtures/profiles/{synthetic-ok,synthetic-wrong-origin,synthetic-wrong-db,synthetic-abi}.yaml
  fixtures/hermes/config-{pinned-defaults,finance-safe,auto-provider,fallback-hosted,adopt-logins,...}.yaml
                         #   trimmed from cli-config.yaml.example @710fa8a (MIT, header records SHA + source path)
  fixtures/litellm/{existing-shape-hosted-only,finance-local,local-with-hosted-fallback,logging-on}.yaml
                         #   key names verified against litellm 1.106.6; no real values
  test_import_hygiene.py, test_provenance.py, test_handshake_matrix.py, test_litellm_routes.py,
  test_access_capabilities.py, test_mcp_policy_gate.py, test_skill_admission.py, test_projection_routing.py
```

Fixture rule (CLAUDE.md Testing Rules 1, 4): each reader gets a **seam-contract test**. The trimmed
upstream fixture must contain every key the reader consumes, and a renamed key fails the test.
Load-bearing tests get the mutation check (rule 7) at authoring time.

## 3. Common commands

From the worktree root (PowerShell 7):

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path openbb_platform\extensions\agents).Path   # worktree code, not main checkout
$T = 'openbb_platform/extensions/agents/tests/hermes_integration'
$F = "$T/fixtures"
# lint gate on changed files
& $py -m black --check openbb_platform/extensions/agents ; & $py -m ruff check openbb_platform/extensions/agents
```

Real-path evidence goes to `.dev-cycle/verify-gh-1338.log` / `verify-gh-1339.log` (git-ignored) and the
handoff. Every real-path run also pipes its output through the sentinel scanner and asserts zero hits:
`... | & $py -m openbb_agents.hermes_integration.projection --scan-stdin`. Exit 1 on any sentinel or on any
`key|token|secret|password` value.

## 4. Tasks

### 1338-T01: metadata-only provenance checks (wrong origin, wrong database)

Goal: the preflight reports exact component and module provenance with no secret values. It blocks with
`failed_layer` on wrong origin, wrong database or an ABI mismatch, and never executes Hermes.

Files: `models.py`, `profile.py`, `provenance.py`, `hermes_preflight.py` (skeleton, `--probe none`),
`test_import_hygiene.py`, `test_provenance.py`, fixtures/profiles.

Red-first tests mapped to acceptance:

| Acceptance bullet | Test (red first) |
|---|---|
| health reports exact process and module provenance | `test_report_lists_sha_remote_dirty_licence_for_each_component` (tmp git repos built in the test) |
| ...without secret values | `test_secret_shaped_settings_reported_as_presence_only`: the synthetic `user_settings.json` carries sentinel password and API key, the JSON report holds `"present"` and contains no sentinel string; mutation: emit raw value, so the test fails |
| ...without secret values | `test_module_origin_has_no_absolute_paths` (reuses `normalize_import_origin`) |
| wrong origin, admission blocks and reports the failed layer | `test_wrong_remote_or_sha_blocks_module_origin`: profile pins `710fa8a`, repo at another SHA, so exit 2 and `failed_layer=module_origin`; `test_webui_agent_dir_unset_resolves_to_unpinned_home_blocks` |
| wrong database | `test_default_fmp_cached_db_name_blocks_wrong_database`: no `mysql_database` and no test mode resolves to `openbb_fmp_cache`, so blocked; `test_expected_db_name_passes`; the contract test pins the resolver keys to `fmp_cached/utils/database.py` names (AST) |
| incompatible ABI | `test_pyvenv_version_outside_hermes_requires_python_blocks_abi` (3.12 vs `<3.15, 3.14 only`) |
| instead of installing or falling back | `test_preflight_never_spawns_hermes_or_pip`: patch `subprocess` to allow only `git`; any other executable fails the test |
| no inheritance of auto-probing | `test_hermes_integration_never_imports_config_or_litellm` (AST walk) |

Focused: `& $py -m pytest "$T/test_import_hygiene.py" "$T/test_provenance.py" -q`

Real-path (replaces "Command: Not yet qualified"), metadata only, against the real pinned clones:

```powershell
$env:HFP_HERMES_AGENT_DIR = '<workspace>\hermes-agent'; $env:HFP_HERMES_WEBUI_DIR = '<workspace>\multi-lora\external\hermes-webui'
& $py -m openbb_agents.hermes_integration.hermes_preflight --profile "$F/profiles/synthetic-ok.yaml" --openbb-settings "$F/settings/synthetic-user_settings.json" --probe none --format json
#   Expect: hermes_agent sha=710fa8a.. level=configured; hermes_webui sha=22d9840..; exit 2 (no local route yet, failed_layer=route)
& $py -m openbb_agents.hermes_integration.hermes_preflight --profile "$F/profiles/synthetic-wrong-origin.yaml" --probe none --format json
#   (profile points agent dir at the installed upstream home's agent checkout) Expect: exit 2, failed_layer=module_origin, observed bf0203a..
```

Classification: **CODE-ONLY.** The real-settings DB name and the live `SELECT DATABASE()` check move to the
batch live acceptance (step L1).

### 1338-T02: Hermes/WebUI and provider handshake matrix with unavailable outcomes

Goal: a matrix of edges with the highest reached `HealthLevel` per edge, plus the failed layer when an edge is
unavailable: WebUI→Hermes (in-process, same interpreter), Hermes→LiteLLM, LiteLLM→local backend,
Hermes→OpenBB MCP (`openbb-agents-mcp` stdio, `openbb_mcp_server` HTTP) and OpenBB→MySQL. A stopped
service is reported as such and is never started, installed or rerouted.

Files: `handshake.py`, `hermes_config.py` (RouteFacts/WebUI facts), `hermes_preflight.py --probe loopback`,
`test_handshake_matrix.py`, fixtures/hermes.

| Acceptance bullet | Test (red first) |
|---|---|
| stopped model blocks and reports the layer | `test_refused_loopback_port_is_backend_unavailable`: real closed ephemeral port; expect `callable=False`, `failed_layer=backend` |
| ...instead of falling back | `test_unavailable_primary_does_not_probe_any_other_route`: transport call log holds exactly one target |
| authenticated distinct from callable | `test_401_from_test_owned_loopback_server_is_auth_layer` (in-process `http.server` on 127.0.0.1:0) |
| admitted vs callable | `test_mcp_tool_schema_hash_drift_blocks_admission`: reuse the notebook_guide catalog/hash pattern; drift gives `failed_layer=schema` |
| non-loopback binding | `test_webui_bound_to_0_0_0_0_or_no_password_blocks_auth` |
| ABI (WebUI in-process) | `test_webui_python_differs_from_hermes_python_blocks_abi` |
| timeout | `test_probe_timeout_is_unavailable_not_success` (caplog loud-empty, rule 9) |

Focused: `& $py -m pytest "$T/test_handshake_matrix.py" -q`

Real-path (code-only part): `hermes_preflight --profile "$F/profiles/synthetic-ok.yaml" --probe loopback --format json`
with the profile's gateway pointed at a free closed loopback port. Expect every downstream edge `unavailable`,
`failed_layer=backend`, exit 2, and no process created (verified by a before/after process-count diff in the
verify log).

Classification: **CODE-ONLY** for the matrix engine and every unavailable outcome. **LIVE** for the
qualified rows (needs O1 and O2), step L2:

```text
Live acceptance for #1338 (HFP-P01 handshake matrix) - normal (non-elevated) pwsh 7 window
Preconditions: PR A merged; O1/O2 approved; <qual-home> and <qual-runtime> are new empty dirs outside the repo;
  HERMES_WEBUI_PASSWORD from the secret store; ports from `Get-NetTCPConnection -State Listen` are free.
1. $env:HERMES_HOME='<qual-home>'; $env:HERMES_RUNTIME_DIR='<qual-runtime>'; cd <hermes-agent clone>; git rev-parse HEAD
                                    Expect: 710fa8a073f9a8136e10749b083a16779341faef
2. pwsh .\setup-hermes.ps1 -RuntimeOnly      Expect: exit 0; python 3.14.x under <qual-runtime>
3. Write <qual-home>\config.yaml from fixtures/hermes/config-finance-safe.yaml (base_url = gateway, model = private alias)
4. hermes_preflight --profile <owner profile> --hermes-config <qual-home>\config.yaml --probe none
                                    Expect: hermes_agent qualified-origin; route BLOCKED until O3/O4 (failed_layer=route|backend)
5. Start WebUI with the env block in section 1 (-BindHost 127.0.0.1 -Port <free>); curl.exe -s http://127.0.0.1:<port>/health
                                    Expect: 200; WebUI reports agent dir = pinned clone
6. hermes_preflight ... --probe loopback      Expect: webui->hermes callable; hermes->gateway per O4 state; mysql callable, db=openbb_fmp_cache_test
Cleanup: stop the WebUI (Ctrl+C in its window); leave <qual-home> for 1339 L-steps; nothing else is stopped.
Report back: exit codes, the preflight JSON (it is secret-free by construction) and the Expect lines that did not match.
```

### 1338-T03: bind existing LiteLLM aliases to verified local backends; refused-backend proof

Goal: classify every gateway alias as `local` (api_base resolves to a loopback port owned by an
allowlisted local runtime) or `hosted` (any provider prefix such as `github_copilot/`, or a non-loopback host).
Classify every fallback, retry and callback as safe or unsafe, and prove that a refused local backend never
produces a hosted request.

Files: `litellm_config.py`, `test_litellm_routes.py`, fixtures/litellm, plus preflight wiring.

| Acceptance bullet | Test (red first) |
|---|---|
| aliases bound to verified local backends | `test_existing_shape_hosted_only_reports_no_private_alias` (fixture with the shape of `claude-proxy.yaml`, 6 `github_copilot/*`), BLOCKED `failed_layer=route` |
| ... | `test_local_alias_on_loopback_classified_local`; `test_localhost_proxy_backed_by_hosted_model_is_not_local` (alias -> `openai/...` with api_base = another proxy whose own model is hosted) |
| refused-backend, no fallback | `test_router_fallbacks_default_fallbacks_context_window_fallbacks_to_hosted_block` (all fallback keys at 1.106.6) |
| no secret values | `test_os_environ_and_master_key_reported_as_presence`: sentinel master_key and `database_url`; report holds the env name and Presence only |
| refused backend with synthetic sentinels (real LiteLLM code) | `test_inprocess_router_refused_local_backend_makes_no_hosted_connect` runs an **in-process** `litellm.Router` (no proxy) on 1.106.6. The local deployment is on a closed loopback port, a hosted fallback is configured, and `egress_guard` is active with a sentinel in the prompt. Expect: an exception, zero non-loopback connect attempts, no sentinel in captured logs. Marked `requires_agents`; runs only in the interpreter chosen by O5. |

Focused: `& $py -m pytest "$T/test_litellm_routes.py" -q -m "not requires_agents"` and, per O5,
`& <O5 python> -I -m pytest "$T/test_litellm_routes.py" -q -m requires_agents` with
`LITELLM_LOCAL_MODEL_COST_MAP=True` (blocks the cost-map download).

Real-path (code-only): `hermes_preflight --profile "$F/profiles/synthetic-ok.yaml" --litellm-config <litellm checkout>\claude-proxy.yaml --probe none --format json | <scan-stdin>`.
The file is parsed by the tool only and never printed. Expect: 6 aliases `hosted`, 0 `local`,
`private_route=BLOCKED`, `failed_layer=route`, `master_key: present`, scan exit 0.

Classification: reader, classifier and in-process proof are **CODE-ONLY** (the proof needs O5). Binding real
aliases is **NEEDS-OWNER-DECISION** (O3 runtime, O4 proxy edit + restart + scoped key + logging settings),
then **LIVE** step L3: preflight `--probe loopback` against the restarted proxy using the scoped finance key.
Expect private alias `local` + `callable`. Then stop the local runtime and re-run. Expect `backend`
unavailable, no hosted request in LiteLLM request history (owner runs a count-only query for the sentinel
string; agents never read that history).

### 1339-T01: principal and operation-scoped access capabilities, default deny

Goal: a server-side `PolicyGate`. A request is allowed only if an explicit grant matches
(principal, operation, scope, field set). Principals: `hermes_runtime`, `hermes_scheduler`, `webui_display`,
`operator`. Operations: the existing `AccessClass` values plus `household_read`, `household_display` and
`evidence_projection_read`. Unknown principals, operations, scopes or fields are denied. A model-supplied
"approved" claim is ignored (spec principle 5). It is wired opt-in at the `openbb_agents.mcp_server` call_tool
seam (`--policy-profile hermes-finance`); the default profile is byte-for-byte unchanged.

Files: `access.py`, `mcp_server.py` (seam only), `policy_probe.py`, `test_access_capabilities.py`,
`test_mcp_policy_gate.py`.

| Acceptance bullet | Test (red first) |
|---|---|
| unauthorized artifact fields fail closed | `test_field_outside_grant_denied`; `test_empty_grant_set_denies_everything` (parametrised over every operation) |
| ... | `test_hermes_runtime_cannot_household_read`; `test_webui_display_can_read_allowlisted_field_only` |
| ... | `test_model_claimed_approval_in_arguments_is_ignored` |
| request fails closed through the actual boundary | `test_stdio_gate_denies_get_positions_before_tool_body` (real stdio subprocess of `openbb_agents.mcp_server --policy-profile hermes-finance`; the tool body is replaced by a sentinel-raising probe module, so the test fails if the body runs) |
| default profile unchanged | `test_default_profile_tool_list_unchanged` (snapshot of `collect_tools()` descriptors) |

Focused: `& $py -m pytest "$T/test_access_capabilities.py" "$T/test_mcp_policy_gate.py" -q`

Real-path: `& $py -m openbb_agents.hermes_integration.policy_probe --synthetic` spawns the real stdio server with the
gate, `HOME`/`USERPROFILE` pointing at a tmp dir and `DB_HOST=127.0.0.1 DB_PORT=<closed>`, so even a fail-open
bug cannot reach private data. It calls `get_positions` and `get_sector_exposure` as `hermes_runtime`.
Expect: both `isError` with `capability_denied`, exit 0 of the probe, the audit line structural only, scan exit 0.

Classification: **CODE-ONLY.**

### 1339-T02: read-only admitted skills, quarantined proposals

Goal: an admission check over the Hermes finance profile. It blocks unless all of the following hold:

1. Admitted skills live in `$HERMES_HOME/skills` (local tier), and their tree hash matches the committed
   manifest.
2. Their directory is not writable by the runtime token.
3. `skills.create_dir` and the proposal quarantine lie **outside every search root**.
4. `skills.project_discovery: false`, `skills.external_dirs: []` (or only hash-pinned dirs),
   `curator.enabled: false`, `auxiliary.background_review.enabled: false`, `skills.inline_shell: false`, and
   `skill_manage` is not in any enabled toolset for the finance platform.
5. No proposal name shadows an admitted name.

Proposals come from an OpenBB-owned writer into the quarantine dir only.

Files: `skills_admission.py`, `hermes_config.py` (SkillFacts), `test_skill_admission.py`, fixtures/hermes.

| Acceptance bullet | Test (red first) |
|---|---|
| writable runtime skills fail closed | `test_admitted_dir_writable_blocks_skills_layer` (tmp dir, `os.access` plus a real write probe in a scratch child that is removed afterwards) |
| ... | `test_admitted_skill_byte_change_blocks_drift` (mutation of one SKILL.md byte) |
| ... | `test_create_dir_inside_search_root_blocks`; `test_project_discovery_true_blocks`; `test_curator_or_background_review_enabled_blocks` |
| ... | `test_skill_manage_toolset_enabled_blocks` |
| quarantined proposals | `test_proposal_written_only_to_quarantine_and_not_loadable` (quarantine path is not in `get_skill_search_roots` order recomputed from the pinned precedence table) |
| ... | `test_proposal_shadowing_admitted_name_rejected` |
| Windows same-user ACL | `test_icacls_deny_write_on_tmp_dir_detected` (`@pytest.mark.skipif(os.name != 'nt')`; no elevation) |

Focused: `& $py -m pytest "$T/test_skill_admission.py" -q`

Real-path (code-only): build a synthetic admitted skill tree in a tmp dir, then run
`hermes_preflight --profile "$F/profiles/synthetic-ok.yaml" --hermes-config "$F/hermes/config-finance-safe.yaml" --skills-root <tmp> --probe none`.
Expect `skills=admitted`. Append one byte to a SKILL.md and re-run. Expect exit 2 with `failed_layer=skills`
and reason `drift`.

Classification: **CODE-ONLY** for the checks. A same-user deny ACL is tamper-evident, not immutable, because the
owner can rewrite the DACL. True read-only access needs a separate runtime identity, which is
**NEEDS-OWNER-DECISION** (O6, elevation, OPS-ATTEST). LIVE step L4 runs the same preflight against `<qual-home>`
after the owner applies the chosen ACL/identity.

### 1339-T03: field-level evidence projections and local-only routing under logging and fallback failures

Goal: Hermes sees only `EvidenceProjection` objects. These carry opaque IDs, capability status, finding codes and
allowlisted bounded aggregates, plus `[[metric:run:artifact:field]]` refs. Exact amounts, quantities, account
identities and names never cross. The private route stays local or blocks under every failure: backend refused,
timeout, 429/5xx with fallbacks configured, `auto` provider, external login adoption, auxiliary task routing, and
logging, callbacks or telemetry enabled.

Files: `projection.py`, `egress_guard.py`, the route policy in `hermes_config.py` + `litellm_config.py`, and
`test_projection_routing.py`.

| Acceptance bullet | Test (red first) |
|---|---|
| model requests contain no raw values | `test_projection_of_sentinel_artifact_has_no_sentinel` (every sentinel class; mutation: allowlist `amount` fails) |
| ... | `test_combination_reidentification_fields_denied` (exact weight + ticker + date tuple) |
| provider requests | `test_fake_local_backend_receives_no_sentinel`: a test-owned loopback OpenAI-compatible server records bodies; the request is built via projection |
| logs/callbacks | `test_route_policy_blocks_litellm_callbacks_or_message_logging_on` (`success_callback`, `callbacks`, `turn_off_message_logging` false, spend-log prompt storage; names per 1.106.6) |
| memory | `test_route_policy_blocks_hermes_memory_or_user_profile_enabled`; `test_route_policy_blocks_shared_metrics_enabled` |
| hosted fallback route fails closed | parametrised `test_route_policy_blocks_*`: `model.provider=auto`, non-loopback `base_url`, non-empty `fallback_providers` / `delegation.fallback_providers`, any `auxiliary.*.provider` not equal to the gateway alias, `auth.adopt_external_logins=true` |
| ...under fallback failure (real LiteLLM) | reuses the 1338-T03 in-process Router proof with 429/500/timeout variants (`requires_agents`, O5) |
| egress | `test_egress_guard_refuses_and_records_non_loopback` |

Focused: `& $py -m pytest "$T/test_projection_routing.py" -q -m "not requires_agents"` (+ the O5 run).

Real-path (code-only): `& $py -m openbb_agents.hermes_integration.policy_probe --synthetic --projection` builds a
sentinel artifact, projects it, and sends it through the gated stdio boundary to a test-owned loopback "model"
under `egress_guard`. Then `hermes_preflight --hermes-config "$F/hermes/config-fallback-hosted.yaml" ...`.
Expect: the model capture holds no sentinel, there are zero non-loopback attempts, the preflight exits 2 with
`failed_layer=route`, and the scan exits 0.

Classification: **CODE-ONLY** for projection, route policy and in-process proofs. **LIVE** step L5 (after O3/O4):
one Hermes turn in `<qual-home>` through the scoped finance alias, with a sentinel artifact referenced by
projection. Then (a) the agent scans `<qual-home>` (`memories/`, `sessions/`, `state.db` as bytes, `logs/`) for
sentinels; this is a synthetic home, so it is allowed. (b) The owner runs a count-only sentinel query on the LiteLLM
request history. (c) The owner stops the local runtime, re-runs the turn, and expects an explicit unavailable state
with zero hosted requests.

## 5. Dependency and ordering

```
1338-T01 (models, profile, provenance, preflight skeleton)
   ├─> 1338-T02 (handshake, hermes_config RouteFacts)
   │      └─> 1339-T02 (skills admission; needs SkillFacts reader + preflight wiring)
   └─> 1338-T03 (litellm_config, route classification)
          └─> 1339-T03 (projection + route policy; also needs 1339-T01 gate)
1339-T01 (access.py, mcp_server seam, policy_probe)  -- independent of 1338-T01 code
```

**1339-T01 can safely run in parallel with 1338-T01.** It touches only `access.py`, `policy_probe.py`, the opt-in
seam in `mcp_server.py` and its own tests, and imports nothing from `models.py` or `provenance.py`. The only shared
files are the empty `hermes_integration/__init__.py` and `tests/hermes_integration/conftest.py`. Mitigation:
1338-T01's first commit creates both, and the 1339 worktree cherry-picks that commit (or creates identical files)
and rebases before PR. The issue-level dependency "HFP-P01 before HFP-P02" applies to 1339-T02/T03 (they consume
the readers), not to T01. Live steps L1–L5 are strictly after the code merges and the owner decisions.

## 6. PR batching (OM5)

| Branch / PR | Content | Per-issue gates | Batch gates (run once) |
|---|---|---|---|
| A `feat/hfp-runtime-provenance-gh-1338` | 1338-T01..T03 | focused pytest, black/ruff, code-only real-path log, `/code-review` + `/security-review` + `local-privacy-review` on the diff vs `portfolio` | - |
| B `feat/hfp-privacy-boundaries-gh-1339` (worktree `.worktrees/hfp-privacy-boundaries-gh-1339`; T01 starts in parallel, T02/T03 after A's readers land, rebased on A) | 1339-T01..T03 | same | local CI on B's tip merged with `origin/portfolio` (covers A+B). Until `scripts/local_ci.py` is on `portfolio`, reproduce `test-unit-platform` + `general-linting` (both triggered by `openbb_platform/**`) and post the evidence |

Merge order (lead, serialized): A then B. Both PR bodies use **`Refs #1338` / `Refs #1339`, not `Closes`**,
because the acceptance requires LIVE steps. The issues close only after the owner reports L1–L5 (posted on
the issues), and Verification/Command fields in the issue bodies are then updated to the commands above.
The `requires_agents` tests are skipped by stock CI, so their O5-interpreter output is attached as evidence.
No Pester or .NET gate applies (no `deploy/windows` or `services/windows` changes).

## 7. Owner decisions and risks

| # | Decision needed | Recommendation |
|---|---|---|
| O1 | Which runtime is "selected": the installed upstream `bf0203a` (live home with private memories/sessions) or the pinned fork `710fa8a`? | Pinned fork, in a new isolated `HERMES_HOME` + `HERMES_RUNTIME_DIR` outside the repo; the live home is never read or modified. Approve running `setup-hermes.ps1 -RuntimeOnly` (downloads pinned uv + Python 3.14). |
| O2 | Native WebUI via `start.ps1` (bootstrap unsupported on Windows) with an explicit agent dir, password and loopback bind | Approve for L2 only; password from the secret store. |
| O3 | Local inference runtime + model (none installed) | Pick one (e.g. a llama.cpp server build or Ollama) after RAM/VRAM measurement (spec §11). Until then private routes report BLOCKED (correct). |
| O4 | Edit `claude-proxy.yaml` (add finance-private local aliases, scoped virtual key limited to them, `turn_off_message_logging`, no callbacks/fallbacks for those aliases, no prompt storage in request history) and restart the proxy that serves the lead's session | Owner-run change in a planned restart window; agents produce the YAML diff only. |
| O5 | Interpreter for real-LiteLLM in-process tests | Ephemeral `uv` env pinned to `litellm==1.106.6` outside the repo, `-I`; alternative: the proxy venv's python in isolated mode (read-only, no proxy contact). |
| O6 | Separate runtime identity for immutable skills (needs elevation) vs same-user deny ACL + hash-pinned admission for P0 | Accept hash pinning + same-user ACL as tamper-evident for P0, with a recorded gap; the identity goes to OPS-ATTEST. |
| O7 | Expected database for the finance profile | `openbb_fmp_cache_test` (live store); `openbb_fmp_cache` is reported as `wrong_database`. |
| O8 | Opt-in `--policy-profile hermes-finance` gate in `openbb_agents.mcp_server` | Approve; the default profile is unchanged and snapshot-tested. |

Risks:

1. Running any Hermes binary migrates or locks its home, so CODE-ONLY work never executes Hermes.
2. Upstream drift: fixtures are trimmed from `710fa8a`. A re-pin must re-run the seam-contract tests.
3. LiteLLM setting names differ by version (1.106.6 runtime vs 1.109.0 checkout). Names are verified against
   the runtime version, and setting a flag is not proof (L3/L5 carry the proof).
4. A same-user ACL is not immutability (O6).
5. Combination re-identification is policy-tested only for the listed tuples. The inference-risk review of any
   derived-ratio allowlist stays with HFP-P06.
6. MySQL wrong-database detection at the live level needs credentials, so it runs owner-side only (L1).

## 8. Lead decisions (2026-11-28, under the owner's delegation)

The owner approved G1 with the pinned forks in section 1 and delegated the program to the lead.

| # | Decision |
|---|---|
| O1 | Qualify the pinned fork `710fa8a` in an isolated `HERMES_HOME` / `HERMES_RUNTIME_DIR` outside the repo. The owner's existing Hermes home is never read or modified. Runtime setup is a LIVE step (L1/L2), not part of CODE-ONLY work. |
| O2 | Approved for L2 only: loopback bind, explicit agent dir, password from the secret store. |
| O3 | Open (owner). Until a local inference runtime is chosen, private routes report BLOCKED; that is the correct outcome. |
| O4 | Agents produce the YAML diff only. The owner applies it and restarts the proxy in a planned window. |
| O5 | Ephemeral `uv` env pinned to `litellm==1.106.6`, outside the repo, run with `-I`. |
| O6 | Hash pinning plus same-user deny ACL for P0, recorded as tamper-evident (not immutable). The separate runtime identity moves to OPS-ATTEST. |
| O7 | The finance profile's database is `openbb_fmp_cache_test`; `openbb_fmp_cache` is reported as `wrong_database`. |
| O8 | Approved: opt-in `--policy-profile hermes-finance`; the default profile stays unchanged and snapshot-tested. |

Model policy: the worktree `CLAUDE.md` on `portfolio` (D1, model-agnostic) governs. The GPT-only clause in the
main checkout's `CLAUDE.md` belongs to an older branch and does not apply.

Issue closing: PRs use `Refs`. Each Task checkbox is ticked when its code merges. A PBI closes when all of its
acceptance bullets are met, including the LIVE steps.
