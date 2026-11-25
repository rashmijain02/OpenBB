# openbb-fmp-cached-mcp

An MCP server with tool-for-tool parity to FMP's hosted MCP server
(`https://financialmodelingprep.com/mcp`): the same 24 tools, 208 `endpoint` values, argument
schemas, error texts and payloads. Data comes from the persistent `fmp_cached` store first and
from FMP REST only for what the store does not hold yet. Spec: `specs/gh-1298-fmp-cached-mcp-parity/`.
Deliberate differences: [DIVERGENCES.md](DIVERGENCES.md).

## Packaging

This is a standalone MCP server, not an OpenBB Platform extension. It adds no `obb` router or
commands, so it is deliberately not listed in `openbb_platform/pyproject.toml` (the CLAUDE.md
"Adding New Extension" step applies to platform extensions). Install it on its own with
`pip install -e openbb_platform/extensions/fmp_cached_mcp`.

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

## Persistent store

`fmp_cached` MySQL is a persistent store, not a TTL cache. Every endpoint has a retention class
(`specs/gh-1298-fmp-cached-mcp-parity/retention-classes.json`, rules in `policy.py`):

| Mode | Kept | FMP is called |
|---|---|---|
| series (prices, indicators, rates) | rows forever (`fmp_mcp_series_row`) | for missing date ranges and the open tail (last 2 days); a re-based history (split, adjustment) is detected on the overlap and re-fetched |
| document, immutable (as-reported, filings, past trades) | forever (`fmp_mcp_document`) | once |
| document, revisable / reference (statements, profiles, lists) | forever, last good copy | after the refresh interval (1 day) |
| feed (news, latest filings) | items forever (`fmp_mcp_feed_item`); listing 10 min | when the listing expires |
| ephemeral (quotes, snapshots, screener) | `fmp_mcp_ephemeral` with `expires_at` | after 15 s to 15 min |
| no-store (custom DCF) | nothing | always |

A call about a past date is immutable whatever its class; an empty answer is never immutable.
Rows become final after 2 days, except late-published series: economic indicators after 120
days, COT reports after 14. Endpoints where FMP ignores `from`/`to` (constituent histories) are
documents, not series; any series answer with rows outside the requested range falls back to
the document path, as do answers with several rows per date. Empty series answers are kept
ephemeral (1 day), never as coverage. When FMP truncates a long range (row caps, plan history),
only the dates it returned count as fetched. Only 400/402/404 are remembered as refusals; other
errors serve the stored copy as stale.
On an FMP failure the stored copy is served with `_meta.openbb/provenance.state = "stale"`.
Only `fmp_mcp_ephemeral` is prunable (`python -m openbb_fmp_cached.utils.cache_prune`); the
persistent tables are not in its allowlist.

`--store auto` (default) uses the `fmp_cached` MySQL database and serves live-only if it is
unreachable; `--store mysql` refuses to start without it; `--store sqlite:PATH` uses a local file;
`--store none` stores nothing. `FMP_CACHED_MCP_STORE` sets the default.

### What the store keeps

Only public FMP market data plus the request that fetched it (path and query, e.g. which
symbol was asked about). Nothing identifies the caller: no token, address or session. Rows are
shared by every client of the server, and persistent rows are not deleted automatically. Check
that permanent storage fits your FMP subscription terms before running a shared instance.
Bodies over 32 MB are served but not stored; empty answers expire after a day; expired
ephemeral rows are pruned hourly.

## Re-recording the parity fixtures

```bash
python scripts/fmp_mcp_record.py inventory|errors|paths|samples --date YYYY-MM-DD ...
python scripts/fmp_mcp_build_assets.py --date YYYY-MM-DD
pytest openbb_platform/extensions/fmp_cached_mcp/tests
```

A hosted change shows up as a failing contract test; update the fixtures in a reviewed PR.
