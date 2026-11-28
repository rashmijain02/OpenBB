# Deliberate divergences from FMP's hosted MCP server

Parity target: `https://financialmodelingprep.com/mcp`, `tools/list` snapshot 2026-11-23
(re-recorded 2026-11-24, identical). Everything not listed here is asserted equal by
`tests/test_contract.py`, `tests/test_render.py`, `tests/test_validation.py` and
`tests/test_server.py`.

| ID | What | Hosted | Ours | Why |
|---|---|---|---|---|
| D1 | FMP report links (`financial-reports-dates` `linkJson`/`linkXlsx`) | Rewrites `apikey=YOUR_API_KEY` with the caller's real key | Keeps FMP's placeholder; our key is scrubbed from every output | The server's key never leaves the server (FR7). Tests compare these payloads with `apikey=` values masked. |
| D2 | `initialize.serverInfo` | `FMP MCP Server` 1.0.0 | `fmp_cached MCP Server` with the package version | Honest identification; clients key on tool names, not server name. |
| D3 | `result._meta` | absent | `{"openbb/provenance": {state, source, asOf, reason?}}` | Provenance (US4) without touching `content`. Hosted-compatible clients ignore `_meta`. |
| D4 | Upstream transport failure (timeout, DNS) | not observed | `Bad request for tool "<tool>" (endpoint <path>): upstream unavailable (<ExceptionType>)`, `isError: true` | No hosted sample exists; exception text is never echoed. |
| D5 | 402 not caused by a parameter | not observed | Same `ACCESS DENIED` template as the parameter case | Only the "Premium Query Parameter" form was recorded; re-check in #1301 (C1). |
| D6 | Defaults for omitted required parameters that were guessed, not recorded (`endpoint_map.json` `defaults_verified: false`: `news` search-* `symbols`, `search-ISIN`, `search-exchange-variants`, `secFilings` `8k-latest`/`financials-latest` dates) | Unknown; inferred by REST shape match | Not applied: the call goes to FMP without them and FMP's missing-parameter error renders | A guessed past-date window would be cached as an immutable document; only defaults verified against the hosted server are emulated. |

## Hosted behaviours we reproduce (recorded 2026-11-24)

- Payload = `JSON.stringify(JSON.parse(restBody))`: compact, key order kept, JS number formatting
  (`0.00008`, not `8e-05`).
- Empty `[]` for a `symbol`/`cik`/`name` lookup becomes a `not_found` envelope; other empty
  lookups stay `[]`.
- Bodies are decoded as lossy UTF-8 (bad bytes → U+FFFD) with one leading BOM stripped, then
  parsed; non-JSON bodies (10-K xlsx) become a JSON string of that text.
- Unknown argument keys are silently dropped (zod strip), despite `additionalProperties: false`.
- Validation errors: `MCP error -32602: Input validation error: Invalid arguments for tool <t>: <zod issues, 2-space JSON>`.
- Unknown tool: `MCP error -32602: Tool <name> not found`.
- FMP 4xx: `Bad request for tool "<tool>" (endpoint <path>): <FMP message>`; FMP 402: `ACCESS DENIED: ...`.
- Required parameters the hosted server defaults when omitted, where verified (e.g. `company-executives` → `symbol=AAPL`; unverified ones: D6).
- Success results carry no `isError` key.
