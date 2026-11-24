# openbb-fmp-cached-mcp

An MCP server with tool-for-tool parity to FMP's hosted MCP server
(`https://financialmodelingprep.com/mcp`): the same 24 tools, 208 `endpoint` values, argument
schemas, error texts and payloads. Data comes from FMP REST today; the persistent `fmp_cached`
store goes in front of it in #1300. Spec: `specs/gh-1298-fmp-cached-mcp-parity/`.
Deliberate differences: [DIVERGENCES.md](DIVERGENCES.md).

## Run

```bash
# stdio (Claude Code / MCP clients that spawn the server)
python -m openbb_fmp_cached_mcp --transport stdio

# streamable HTTP on 127.0.0.1:8011/mcp
python -m openbb_fmp_cached_mcp --transport http
```

The FMP key is read from `FMP_API_KEY` or `~/.openbb_platform/user_settings.json`
(`fmp_cached_api_key` / `fmp_api_key`). It is sent to FMP in the `apikey` header only and
scrubbed from every result and log line.

Binding anything other than loopback requires `FMP_CACHED_MCP_TOKEN` (at least 32 characters);
when it is set, every HTTP request must send `Authorization: Bearer <token>`.

## Re-recording the parity fixtures

```bash
python scripts/fmp_mcp_record.py inventory|errors|paths|samples --date YYYY-MM-DD ...
python scripts/fmp_mcp_build_assets.py --date YYYY-MM-DD
pytest openbb_platform/extensions/fmp_cached_mcp/tests
```

A hosted change shows up as a failing contract test; update the fixtures in a reviewed PR.
