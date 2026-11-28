# fmp_cached MCP server (hosted FMP MCP parity)

Program #1298 (fmp_cached MCP parity). Package: `openbb_platform/extensions/fmp_cached_mcp`
(`openbb_fmp_cached_mcp`). Spec: `specs/gh-1298-fmp-cached-mcp-parity/`.

The server exposes the same 24 tools and 208 `endpoint` values as FMP's hosted MCP server
(`https://financialmodelingprep.com/mcp`). Payloads, argument validation and error texts match
the hosted server; deliberate differences are listed in the package `DIVERGENCES.md`. Data is
served from the persistent `fmp_cached` MySQL store first and fetched from FMP REST only for what
the store does not hold yet.

## 1. Install

```powershell
.venv_portfolio\Scripts\python.exe -m pip install -e openbb_platform\extensions\fmp_cached_mcp
```

The FMP key is read from `FMP_API_KEY` or from `fmp_cached_api_key` / `fmp_api_key` in
`~/.openbb_platform/user_settings.json`. It is sent to FMP in the `apikey` header only. It never
appears in results, logs, `_meta`, store keys or fixtures.

## 2. Run

| Purpose | Command |
|---|---|
| Claude Code and other clients that spawn the server | `python -m openbb_fmp_cached_mcp --transport stdio` |
| Workspace or other HTTP clients (`http://127.0.0.1:8011/mcp`) | `python -m openbb_fmp_cached_mcp --transport http` |
| Bind beyond loopback | `$env:FMP_CACHED_MCP_TOKEN = '<32+ chars>'; python -m openbb_fmp_cached_mcp --transport http --host 0.0.0.0` |

**Loopback bind.**
- On loopback, Host and Origin are restricted to `127.0.0.1`, `localhost` and `[::1]` (DNS
  rebinding protection).
- Only IP literals and `localhost` count as loopback.

**Non-loopback bind.**
- A non-loopback bind refuses to start without `FMP_CACHED_MCP_TOKEN`.
- Every request must then send `Authorization: Bearer <token>`.

**Store selection** (`--store` or `FMP_CACHED_MCP_STORE`):

| Value | Behaviour |
|---|---|
| `auto` (default) | `fmp_cached` MySQL; serves live from FMP (with one warning) if MySQL is unreachable |
| `mysql` | `fmp_cached` MySQL; refuses to start if unreachable |
| `sqlite:PATH` | a local SQLite file (hosts without MySQL, development) |
| `none` | live only, nothing stored |

## 3. Register with a client

### Claude Code `.mcp.json`

The hosted entry stays as it is. Add the parity server next to it, then switch prompts or agents
from `fmp` to `fmp_cached` without changing any tool call:

```json
{
  "mcpServers": {
    "fmp": {
      "type": "http",
      "url": "https://financialmodelingprep.com/mcp",
      "headers": { "Authorization": "Bearer ${FMP_API_KEY}" }
    },
    "fmp_cached": {
      "type": "stdio",
      "command": "<repo>/.venv_portfolio/Scripts/python.exe",
      "args": ["-m", "openbb_fmp_cached_mcp", "--transport", "stdio"]
    }
  }
}
```

### Workspace

Register `http://127.0.0.1:8011/mcp` as a **separate** MCP server. Do not add it to the
Portfolio MCP profiles: its tool names (`quote`, `search`, `news`, …) are FMP's, and the
Portfolio MCP inventory and Workspace contract checks do not cover it.

Workspace calls the server from the browser, so its origin must be allowed explicitly.
Otherwise the DNS-rebinding check refuses it and the browser gets no CORS headers:

```bash
python -m openbb_fmp_cached_mcp --transport http --allow-origin https://pro.openbb.co
```

`--allow-origin` can be repeated, and `FMP_CACHED_MCP_ALLOWED_ORIGINS` (comma-separated) is the
default. Each value must be an exact `http(s)://host[:port]`; `*` is refused. Preflights are
answered before the bearer-token check, but every real request still needs the token.

## 4. Provenance

Every result that reached FMP or the store carries `result._meta["openbb/provenance"] = {state, source, asOf, reason?}`. The
`state` values come from the #1269 `DataState` vocabulary:

| state | Meaning |
|---|---|
| `live` | fetched from FMP now |
| `cached` | served from the store, within its refresh window |
| `stale` | FMP failed and an older stored copy was served |
| `unavailable` | an FMP refusal, or an error with no stored copy |

`content` is never changed by provenance.

## 5. Storage and retention

The store is persistent: meaningful data is kept for good and only ephemeral data expires. The
retention rules (series ranges per request, immutable and revisable documents, feeds, ephemeral
TTLs) are in the package README. The tables are `fmp_mcp_document`, `fmp_mcp_feed_item` and
`fmp_mcp_ephemeral`. They are registered in
`openbb_fmp_cached.utils.cache_schema` (`FMP_MCP_TABLE_COLUMNS`).

**Pruning.**
- Only `fmp_mcp_ephemeral` is prunable.
- The server prunes expired rows hourly.
- `python -m openbb_fmp_cached.utils.cache_prune` also covers it (rule on `expires_at`).
- The persistent tables are not in the prune allowlist, and tests assert this.

**Backups.** The persistent tables are public market data. Back them up with the provider-cache
tables, as described in `portfolio-intelligence-cache-runbook.md` section 4.3.

## 6. Verify

```powershell
# hermetic parity, store and security tests (CI job "FMP cached MCP parity")
cd openbb_platform\extensions\fmp_cached_mcp; ..\..\..\.venv_portfolio\Scripts\python.exe -m pytest -q tests

# live: hosted tools/list drift and answer equality (needs the key; never updates fixtures)
..\..\..\.venv_portfolio\Scripts\python.exe -m pytest -q -m integration tests\test_hosted_live.py
```

When the hosted server changes, re-record with `scripts/fmp_mcp_record.py`, rebuild the assets
with `scripts/fmp_mcp_build_assets.py`, and review the fixture diff in a PR.

## 7. Known limits

- **402 coverage.** Only the parameter-level 402 form ("Premium Query Parameter") has been
  recorded. An endpoint-level 402 uses the same `ACCESS DENIED` template (DIVERGENCES D5).
- **Series gap-fill** (fetch only the missing dates of a stored series) is #1310. Until then,
  each distinct range is its own stored request.
- **Warm start** from the typed `fmp_cached` tables (task B6) is deferred: MySQL was unavailable
  when this shipped. The store fills on first use.
