# Live acceptance steps (owner-run)

Status: partial. Sections for #1338 T02 (step L2), T03 (step L3) and #1339 T02 (step L4) and T03 (step L5) are
written. L1 stays in `plan.md` section 4 until its code lands. Nothing here is executed by agents, except the
synthetic-home scan in L5 step 3, which the plan allows.

## L2: #1338 T02, Hermes/WebUI and provider handshake matrix

Code-only parts (matrix engine, route policy reader, every unavailable or blocked outcome) are tested in
`openbb_platform/extensions/agents/tests/hermes_integration/test_handshake_matrix.py`. This step produces the
qualified rows that need the pinned Hermes runtime (owner decisions O1 and O2) and, for the route rows, O3 and O4.

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

Notes for the owner, from what the code does today:

- Step 6 needs `HERMES_WEBUI_PORT` (the port from step 5), `HERMES_WEBUI_HOST=127.0.0.1`, `HERMES_WEBUI_PASSWORD`,
  `HERMES_WEBUI_PYTHON` (inside the Hermes runtime venv) and the profile's `python.venv_env` variable set in the
  same window, otherwise the `webui_hermes` edge reports `blocked` (layer `auth` or `abi`) by design.
- `hermes_litellm` reaches `callable` only when the gateway answers `GET /v1/models` with the private alias.
  Set `gateway_key_env` in the owner profile to the name of the variable that holds the scoped key.
- `openbb_mysql` is TCP reachability only (level `configured`, `callable=false`). The authenticated
  `SELECT DATABASE()` check stays in step L1. The settings-based database name is already checked by the
  `database` component.
- Pin the MCP catalog by setting `mcp_catalog_sha256` in the owner profile and passing `--mcp-tools <json list>`
  (tool descriptors with name, description, inputSchema). A drift reports `failed_layer=schema`.

## L3: #1338 T03, bind LiteLLM aliases to a verified local backend; refused-backend proof

Code-only parts (proxy YAML reader, alias classifier, route policy, preflight wiring) are tested in
`openbb_platform/extensions/agents/tests/hermes_integration/test_litellm_routes.py`. The in-process proof
(`-m requires_agents`) runs real litellm 1.106.6 `Router` code in an ephemeral interpreter outside the repo
(decision O5) against test-owned loopback servers: for refused, timed-out and rate-limited local backends it
raises, the loopback hosted stand-in receives zero requests, there are zero non-loopback lookups or connects,
and no sentinel appears in INFO-level logs or the exception. The same harness proves the opposite for the
config the classifier rejects (router `fallbacks` to a hosted alias does reach the hosted stand-in).

Today's result against the existing proxy config (code-only real path): 6 aliases, all `hosted`
(`github_copilot`), 0 `local`, `private_route=BLOCKED` (`no_private_alias_allowlisted`, `no_local_alias`,
`message_logging_not_disabled`), `failed_layer=route` among others, `master_key` and `database_url` present
as env references. That is the correct fail-closed outcome until O3 and O4.

```text
Live acceptance for #1338 (HFP-P01 LiteLLM binding) - normal (non-elevated) pwsh 7 window, planned restart window
Preconditions: PR A merged; O3 runtime chosen and listening on 127.0.0.1:<LOCAL_RUNTIME_PORT> only;
  no agent session is using the proxy during the restart (it serves the lead's session).
1. Back up the proxy YAML; apply specs/gh-1338-hfp-runtime-privacy-admission/proposed-claude-proxy.diff by hand
   (fill the placeholders; no secret values in the YAML, env references only).
2. Owner profile: private_alias_allowlist: [finance-private]; local_backends: ["http://127.0.0.1:<LOCAL_RUNTIME_PORT>"];
   gateway_key_env: <NAME of the env var holding the scoped finance key>.
3. hermes_preflight --profile <owner profile> --litellm-config <proxy yaml> --probe none --format text
                                    Expect: litellm_routes private_route=ADMITTED local=1 hosted=6; alias finance-private kind=local
4. Restart the proxy (litellm-copilot-start). Start it WITHOUT --detailed_debug and with LITELLM_LOG unset or INFO:
   at DEBUG, litellm 1.106.6 logs the prompt even with turn_off_message_logging (proved in-process).
5. Create a scoped virtual key limited to models: [finance-private] (no hosted alias in its model list) and
   metadata {"disable_fallbacks": true} (litellm 1.106.6 copies that key metadata onto every request, so a
   caller-supplied "fallbacks" body field is not honoured); store it in the secret store under the name from
   step 2. Never paste it into chat or a file in the repo.
   Also confirm in the admin UI or /model/info (owner-run) that no model is stored in the database
   (store_model_in_db is false) and that the YAML has no `include:` section: the preflight reads only this YAML.
   Then, owner-run, GET /key/info for the new key and /team/info for its team (if any) and confirm:
   the key's aliases is empty ({}), it has no router_settings override (absent or {}), its metadata has
   "disable_fallbacks": true, and the team has no model_aliases. A key or team alias can remap
   finance-private to a hosted model after the preflight has passed; the preflight reads only the YAML.
6. With a synthetic sentinel prompt only: request-level fallback check. Send one chat request with the scoped key,
   model finance-private, and body field "fallbacks": ["<a hosted alias>"] while the local runtime is stopped.
                                    Expect: an error; no hosted request. (In-process, a caller-supplied fallbacks
                                    kwarg DOES reach a hosted alias, so the key's model scope is the control here.)
7. Local runtime running: hermes_preflight ... --hermes-config <qual-home>\config.yaml --probe loopback --backend-url http://127.0.0.1:<LOCAL_RUNTIME_PORT>
                                    Expect: hermes_litellm callable (only finance-private listed); litellm_backend callable
8. Stop the local runtime; re-run step 7.
                                    Expect: litellm_backend unavailable (failed_layer=backend); exit 2
9. Owner-only, count-only query on the proxy's request history for the sentinel string used in steps 6-8.
                                    Expect: 0 rows containing it, and no rows for a hosted model in the window.
                                    Agents never read that history.
Cleanup: leave the binding in place if steps 3-9 match; otherwise restore the backup and restart.
Report back: exit codes, the step 3 and 7/8 preflight text output, the count from step 9, and any Expect line that did not match.
```

Notes for the owner:

- `turn_off_message_logging` and `set_verbose` are global in litellm 1.106.6, so step 1 also stops message
  logging for the Copilot aliases.
- `store_prompts_in_spend_logs: false` keeps prompts out of the Postgres request history; the preflight blocks
  an explicit `true`.
- Key scope (read from litellm 1.106.6 code, `proxy/auth/model_checks.py` `get_key_models` /
  `get_complete_model_list` and `proxy/utils.py` `get_available_models_for_user`): `/v1/models` with a virtual
  key whose `models` list is non-empty returns only those models (plus models of its access groups); an empty
  list falls back to the team's models and then to every proxy model, and `all-proxy-models` /
  `all-team-models` expand the same way. So the served list is the key's call scope. The `hermes_litellm` edge
  in step 7 reports `blocked` (`failed_layer=auth`, `gateway_key_not_scoped`) when that list holds anything
  outside `private_alias_allowlist`, which is what the master key or an unscoped key produce.
- The preflight cannot see CLI flags or env vars of the running proxy (`--detailed_debug`, `LITELLM_LOG`), so
  step 4 is a manual check.

## L4: #1339 T02, read-only admitted skills and quarantined proposals

Code-only parts (skill reader, hash pin, drift, write probes, search-root recomputation, proposal writer,
shadowing, ACL detection on a temp dir) are tested in
`openbb_platform/extensions/agents/tests/hermes_integration/test_skill_admission.py`. This step applies the chosen
protection to the qualification home and proves the preflight sees it. Decision O6: a same-user deny ACE plus the
hash pin is **tamper-evident, not immutable**. The owner can rewrite the DACL, and the ACE does not stop file
deletion (denying DELETE on files also breaks plain reads, see below); the hash pin reports both as `drift` or
`missing`. A separate runtime identity for real read-only access stays with OPS-ATTEST.

```text
Live acceptance for #1339 (HFP-P02 skills admission) - normal (non-elevated) pwsh 7 window
Preconditions: L2 done (<qual-home> exists, pinned runtime); the owner's own Hermes home is never used.
  Hermes has run once in <qual-home>, so its bundled-skill seeding has finished BEFORE the ACE is applied.
1. Write <qual-home>\config.yaml from fixtures/hermes/config-finance-safe.yaml (skills/curator/background_review
   and agent.disabled_toolsets: [skills] exactly as in the fixture). Create <qual-quarantine> OUTSIDE <qual-home>.
2. Decide the admitted set. Remove every other skill dir from <qual-home>\skills (bundled seeds included) or
   admit it too. For each admitted dir (POSIX path relative to <qual-home>\skills):
     python -c "from openbb_agents.hermes_integration.skills_admission import tree_sha256 as t; print(t(r'<qual-home>\skills\<rel>'))"
   and record `admitted_skills: {<rel>: <sha256>}` in the owner profile.
3. Before the ACE: hermes_preflight --profile <owner profile> --hermes-config <qual-home>\config.yaml `
     --skills-root <qual-home>\skills --skills-quarantine <qual-quarantine> --probe none --format text
                                    Expect: skills failed_layer=skills, detail contains admitted_dir_writable
4. $sid = (whoami /user /fo csv /nh).Split(',')[-1].Trim('"')
   icacls <qual-home>\skills /deny "*${sid}:(OI)(CI)(WD,AD,WEA,WA,DC)"
                                    (Do NOT add D: denying DELETE on files also denies reads for this user.)
5. Re-run step 3.                   Expect: skills level=admitted detail=skills_admitted: n=<count>
6. Tamper check: Set-Content -Path <qual-home>\skills\<rel>\SKILL.md -Value x
                                    Expect: Access denied
7. Hermes session with the finance profile; ask it to create or edit a skill (synthetic text only).
                                    Expect: no skill_manage tool offered; no file under <qual-home>\skills changes
                                    (re-run step 5: still admitted, same hashes).
8. Drift check (owner, deliberate): remove the ACE (icacls <qual-home>\skills /remove:d "*$sid" /T), append one byte
   to an admitted SKILL.md, re-apply step 4, re-run step 3.
                                    Expect: exit 2, skills failed_layer=skills, detail contains drift:<rel>.
                                    Then restore the byte (or re-pin) and re-run step 5.
Cleanup: keep the ACE in place for qualification. To undo: icacls <qual-home>\skills /remove:d "*$sid" /T
Report back: exit codes and the `skills ...` lines from steps 3, 5 and 8, and any Expect line that did not match.
```

Notes for the owner:

- Proposals go only through `skills_admission.write_proposal`, into `<qual-quarantine>`. The preflight blocks a
  quarantine inside any Hermes search root and any proposal whose directory or frontmatter name shadows an
  admitted skill.
- Hermes' `skills_sync` seeds bundled skills into the local tier on first run. Any file under `<qual-home>\skills`
  that is not part of an admitted skill blocks with `unadmitted_content`, so step 2 must cover the seeds.
- `skill_manage` is removed only by `agent.disabled_toolsets: [skills]`, which also removes `skills_list` and
  `skill_view` (upstream subtracts disabled toolsets at tool granularity). How admitted skills then load (for
  example `skills.auto_load` or slash commands) is not verified at the pin; step 7 and T03 / HFP-P05 confirm it.
- `skills.external_dirs` must be empty for P0. Hash-pinned external dirs are not implemented.

## L5: #1339 T03, one end-to-end Hermes turn with synthetic sentinels

Code-only parts (field allowlist, re-identification denial, sentinel scanner, egress guard, the loopback model
capture, and the in-process LiteLLM 1.106.6 Router under refused / timeout / 429 / 500 backends with key
`disable_fallbacks`) are tested in `test_projection_routing.py` and `test_litellm_routes.py` (`requires_agents`).
The code-only real path is `policy_probe --synthetic --projection | projection --scan-stdin` (exit 0, `hits=0`).
This step proves the same boundary in one real Hermes turn. All data is synthetic: the sentinels are the values in
`projection.SENTINELS` (an account, an amount and a name), never real holdings.

```text
Live acceptance for #1339 (HFP-P02 evidence projections) - normal (non-elevated) pwsh 7 window
Preconditions: L2, L3 and L4 done in <qual-home>; the LiteLLM proxy runs the admitted finance-local config; the
finance virtual key carries metadata {"disable_fallbacks": true}; the owner's own Hermes home is never used.
$py = <worktree python>; $env:PYTHONPATH = <absolute path to openbb_platform\extensions\agents>
1. Preflight: & $py -m openbb_agents.hermes_integration.hermes_preflight <the L3 arguments>
                                    Expect: exit 0, route level=local for the finance alias
2. In <qual-home>, one Hermes turn through the finance alias. The prompt carries only an EvidenceProjection built
   by projection.project() from a sentinel artifact (all projection fields, principal hermes_runtime); paste its
   JSON, never the artifact.       Expect: an answer that cites [[metric:run_...:art_...:<field>]] refs only
3. Agent-run scan of the synthetic home (bytes, so state.db is covered):
   Get-ChildItem <qual-home>\memories,<qual-home>\sessions,<qual-home>\logs,<qual-home>\state.db -Recurse -File |
     ForEach-Object { [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::Latin1) } |
     & $py -m openbb_agents.hermes_integration.projection --scan-stdin
                                    Expect: exit 0, scan_result hits=0
4. Owner only: a count-only query on the LiteLLM request history for each sentinel value (spend logs / request
   log table). Never print rows.  Expect: 0 for each sentinel
5. Owner: stop the local model runtime (not the proxy), re-run the turn from step 2.
                                    Expect: an explicit unavailable / error state; zero requests on any hosted alias
                                    (count-only check as in step 4, by model group)
6. Restart the local runtime; re-run step 1.
                                    Expect: exit 0 again
Report back: exit codes, the scan_result line from step 3, the counts from steps 4 and 5, and any Expect line
that did not match. Never paste prompts, responses or rows.
```

Notes for the owner:

- Step 5 depends on the key metadata. Without `disable_fallbacks`, a caller-supplied `fallbacks=[hosted]` request
  field still reaches a hosted alias on an admitted config (`test_inprocess_request_level_fallback_bypasses_config_policy`).
- Keep LiteLLM at INFO. DEBUG (`--detailed_debug`, `LITELLM_LOG=DEBUG`, `set_verbose`) writes prompts to logs even
  with `turn_off_message_logging: true`, so the projection is the only thing that keeps sentinels out.
