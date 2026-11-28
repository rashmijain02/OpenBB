# Live acceptance steps (owner-run)

Status: partial. Sections for #1338 T02 (step L2) and T03 (step L3) are written. L1, L4 and L5 stay in
`plan.md` section 4 until their code lands. Nothing here is executed by agents.

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
6. With a synthetic sentinel prompt only: request-level fallback check. Send one chat request with the scoped key,
   model finance-private, and body field "fallbacks": ["<a hosted alias>"] while the local runtime is stopped.
                                    Expect: an error; no hosted request. (In-process, a caller-supplied fallbacks
                                    kwarg DOES reach a hosted alias, so the key's model scope is the control here.)
7. Local runtime running: hermes_preflight ... --hermes-config <qual-home>\config.yaml --probe loopback --backend-url http://127.0.0.1:<LOCAL_RUNTIME_PORT>
                                    Expect: hermes_litellm callable (finance-private listed); litellm_backend callable
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
- The preflight cannot see CLI flags or env vars of the running proxy (`--detailed_debug`, `LITELLM_LOG`), so
  step 4 is a manual check.
