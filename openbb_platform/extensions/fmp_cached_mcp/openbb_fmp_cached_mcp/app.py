"""HTTP/stdio transports with the security defaults from the spec (FR7, #1299).

- Binds ``127.0.0.1`` by default.
- A non-loopback bind refuses to start without a bearer token of at least 32
  characters (``FMP_CACHED_MCP_TOKEN``).
- When a token is set it is required on every HTTP request, compared in
  constant time.
- The FMP key stays inside the upstream; it is never logged or returned.
"""

from __future__ import annotations

import contextlib
import hmac
import ipaddress
import socket
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from openbb_fmp_cached_mcp.server import build_server
from openbb_fmp_cached_mcp.upstream import Upstream

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8011
MIN_TOKEN_LEN = 32


class BindError(RuntimeError):
    """Refused to start with an unsafe bind/auth combination."""


def is_loopback(host: str) -> bool:
    """Return True for loopback literals and names resolving only to loopback."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if host == "localhost":
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addrs = {str(info[4][0]) for info in infos}
    return bool(addrs) and all(
        ipaddress.ip_address(a.split("%")[0]).is_loopback for a in addrs
    )


def check_bind(host: str, token: str) -> None:
    """Raise ``BindError`` unless the bind/auth combination is safe."""
    if token and len(token) < MIN_TOKEN_LEN:
        raise BindError(
            f"FMP_CACHED_MCP_TOKEN must be at least {MIN_TOKEN_LEN} characters"
        )
    if not is_loopback(host) and not token:
        raise BindError(
            f"refusing to bind {host!r} without FMP_CACHED_MCP_TOKEN; "
            f"bind {DEFAULT_HOST} or set a token"
        )


class BearerAuth:
    """ASGI middleware requiring ``Authorization: Bearer <token>``."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app, self._token = app, token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject requests without the configured bearer token."""
        if scope["type"] == "http":
            header = dict(scope.get("headers") or []).get(b"authorization", b"")
            scheme, _, value = header.partition(b" ")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(
                value, self._token
            ):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


def build_http_app(upstream: Upstream | None, *, token: str = "") -> ASGIApp:
    """Streamable-HTTP app serving the parity server at ``/mcp``."""
    manager = StreamableHTTPSessionManager(
        app=build_server(upstream), json_response=True
    )

    async def handle(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    app: ASGIApp = Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan)
    return BearerAuth(app, token) if token else app
