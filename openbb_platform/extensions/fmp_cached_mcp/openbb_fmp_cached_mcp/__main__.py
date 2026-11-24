"""Command line: ``python -m openbb_fmp_cached_mcp [--transport stdio|http]`` (#1299)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from openbb_fmp_cached_mcp.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    BindError,
    build_http_app,
    check_bind,
)
from openbb_fmp_cached_mcp.server import build_server
from openbb_fmp_cached_mcp.upstream import FmpRestUpstream, load_fmp_key


async def _run_stdio(upstream: FmpRestUpstream) -> None:
    from mcp.server.stdio import stdio_server  # pylint: disable=import-outside-toplevel

    server = build_server(upstream)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await upstream.aclose()


def main(argv: list[str] | None = None) -> int:
    """Run the server; returns a process exit code."""
    parser = argparse.ArgumentParser(prog="openbb-fmp-cached-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    # httpx logs request URLs at INFO; keep tool arguments out of the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    key = load_fmp_key()
    if not key:
        sys.stderr.write(
            "error: FMP key not configured (FMP_API_KEY or user_settings.json)\n"
        )
        return 2
    upstream = FmpRestUpstream(key)

    if args.transport == "stdio":
        asyncio.run(_run_stdio(upstream))
        return 0

    token = os.environ.get("FMP_CACHED_MCP_TOKEN", "")
    try:
        check_bind(args.host, token)
    except BindError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    import uvicorn  # pylint: disable=import-outside-toplevel

    if not token:
        logging.getLogger(__name__).info(
            "serving on loopback without a bearer token; set FMP_CACHED_MCP_TOKEN "
            "to require one"
        )
    app = build_http_app(upstream, token=token, host=args.host, port=args.port)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
