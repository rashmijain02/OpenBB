"""Command line: ``python -m openbb_fmp_cached_mcp [--transport stdio|http] [--store ...]``.

``--store`` selects the persistent store (#1300):

``auto`` (default)  the ``fmp_cached`` MySQL database; live-only if unreachable
``mysql``           the ``fmp_cached`` MySQL database; refuse to start if unreachable
``sqlite:PATH``     a local SQLite file (development, or hosts without MySQL)
``none``            live-only, nothing stored
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sqlite3
import sys

from openbb_fmp_cached_mcp.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    BindError,
    build_http_app,
    check_bind,
    check_origins,
)
from openbb_fmp_cached_mcp.server import build_server
from openbb_fmp_cached_mcp.service import StoreBackedUpstream
from openbb_fmp_cached_mcp.store import (
    MySqlDatabase,
    SqliteDatabase,
    Store,
    StoreDataError,
    StoreUnavailable,
)
from openbb_fmp_cached_mcp.upstream import FmpRestUpstream, Upstream, load_fmp_key

logger = logging.getLogger("openbb_fmp_cached_mcp")


class StoreSetupError(RuntimeError):
    """The requested store (``mysql`` or ``sqlite:PATH``) cannot be opened."""


def open_store(spec: str) -> Store | None:
    """Return a ready store for ``spec`` or ``None`` for live-only mode."""
    if spec == "none":
        return None
    if spec.startswith("sqlite:"):
        try:
            store = Store(SqliteDatabase(spec[len("sqlite:") :]))
            store.create_tables()
        except (sqlite3.Error, StoreUnavailable, StoreDataError, OSError) as exc:
            raise StoreSetupError(
                f"cannot open the SQLite store ({type(exc).__name__})"
            ) from None
        return store
    try:
        store = Store(MySqlDatabase())
        store.create_tables()
        return store
    except (StoreUnavailable, StoreDataError, ImportError) as exc:
        # StoreDataError: reachable but refused (e.g. 1142 CREATE denied).
        if spec == "mysql":
            raise StoreSetupError(
                f"fmp_cached MySQL store unavailable ({type(exc).__name__})"
            ) from None
        logger.warning(
            "fmp_cached MySQL store unavailable (%s); serving live from FMP",
            type(exc).__name__,
        )
        return None


def valid_store_spec(spec: str) -> bool:
    """Return True for ``auto``, ``mysql``, ``none`` or ``sqlite:<non-empty path>``."""
    if spec in ("auto", "mysql", "none"):
        return True
    return spec.startswith("sqlite:") and bool(spec[len("sqlite:") :].strip())


def build_upstream(key: str, store_spec: str) -> tuple[Upstream, FmpRestUpstream]:
    """FMP REST client, with the persistent store in front unless disabled."""
    store = open_store(store_spec)  # first: a failure must not leak a client
    rest = FmpRestUpstream(key)
    return (StoreBackedUpstream(rest, store) if store is not None else rest), rest


async def _run_stdio(upstream: Upstream, rest: FmpRestUpstream) -> None:
    from mcp.server.stdio import stdio_server  # pylint: disable=import-outside-toplevel

    server = build_server(upstream)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await rest.aclose()


def main(argv: list[str] | None = None) -> int:
    """Run the server; returns a process exit code."""
    parser = argparse.ArgumentParser(prog="openbb-fmp-cached-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--store", default=os.environ.get("FMP_CACHED_MCP_STORE", "auto")
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="browser origin allowed to call the HTTP server, e.g. Workspace "
        "(repeatable; default: FMP_CACHED_MCP_ALLOWED_ORIGINS, comma-separated)",
    )
    args = parser.parse_args(argv)
    if not valid_store_spec(args.store):
        parser.error("--store must be auto, mysql, none or sqlite:PATH (non-empty)")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    # httpx logs request URLs at INFO; keep tool arguments out of the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    key = load_fmp_key()
    if not key:
        sys.stderr.write(
            "error: FMP key not configured (FMP_API_KEY or user_settings.json)\n"
        )
        return 2
    token = os.environ.get("FMP_CACHED_MCP_TOKEN", "")
    origins = args.allow_origin or [
        o.strip()
        for o in os.environ.get("FMP_CACHED_MCP_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]
    if args.transport == "http":
        try:  # refuse an unsafe bind before touching the store or the network
            check_bind(args.host, token)
            check_origins(origins)
        except (BindError, ValueError) as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2
    try:
        upstream, rest = build_upstream(key, args.store)
    except StoreSetupError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if args.transport == "stdio":
        asyncio.run(_run_stdio(upstream, rest))
        return 0

    import uvicorn  # pylint: disable=import-outside-toplevel

    if not token:
        logger.info(
            "serving on loopback without a bearer token; set FMP_CACHED_MCP_TOKEN "
            "to require one"
        )
    app = build_http_app(
        upstream,
        token=token,
        host=args.host,
        port=args.port,
        allowed_origins=origins,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
