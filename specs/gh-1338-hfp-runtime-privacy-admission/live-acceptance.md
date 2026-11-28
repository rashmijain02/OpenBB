# Live acceptance steps (owner-run)

Status: partial. Only the section for #1338 T02 (step L2) is written so far. L1, L3, L4 and L5 stay in
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
