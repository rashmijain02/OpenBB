"""HTTP/stdio transports with the security defaults from the spec (FR7, #1299).

- Binds ``127.0.0.1`` by default. Only IP literals and ``localhost`` count as
  loopback, so the address checked is the address bound (no second DNS lookup).
- A non-loopback bind refuses to start without a bearer token of at least 32
  characters (``FMP_CACHED_MCP_TOKEN``).
- When a token is set it is required on every request (any ASGI scope except
  lifespan), compared in constant time.
- On loopback, Host and Origin headers are restricted to loopback names, which
  blocks DNS-rebinding pages from reaching the server through a browser.
- The FMP key stays inside the upstream; it is never logged or returned.
"""

from __future__ import annotations

import contextlib
import hmac
import ipaddress
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from openbb_fmp_cached_mcp.server import build_server
from openbb_fmp_cached_mcp.upstream import Upstream

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8011
MIN_TOKEN_LEN = 32
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")


class BindError(RuntimeError):
    """Refused to start with an unsafe bind/auth combination."""


def is_loopback(host: str) -> bool:
    """Return True for a loopback IP literal or ``localhost`` (no DNS lookups)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


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
        """Reject every non-lifespan request without the configured token."""
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        header = dict(scope.get("headers") or []).get(b"authorization", b"")
        scheme, _, value = header.partition(b" ")
        if scheme.lower() == b"bearer" and hmac.compare_digest(value, self._token):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
        else:
            await send({"type": "websocket.close", "code": 1008})


def loopback_security(port: int, host: str = DEFAULT_HOST) -> TransportSecuritySettings:
    """Host/Origin allow-lists for a loopback bind (DNS-rebinding protection)."""
    names = list(LOOPBACK_NAMES)
    bound = f"[{host.strip('[]')}]" if ":" in host else host
    if bound not in names:
        names.append(bound)  # e.g. 127.0.0.2: accept the address actually bound
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{name}:{port}" for name in names],
        allowed_origins=[f"http://{name}:{port}" for name in names],
    )


class _SessionEndpoint:  # pylint: disable=too-few-public-methods
    """ASGI endpoint for the exact ``/mcp`` path (a class, so Starlette's
    ``Route`` treats it as a raw ASGI app rather than a request handler).
    """

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Hand the request to the MCP session manager."""
        await self.manager.handle_request(scope, receive, send)


def build_http_app(
    upstream: Upstream | None,
    *,
    token: str = "",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ASGIApp:
    """Streamable-HTTP app serving the parity server at ``/mcp``."""
    security = loopback_security(port, host) if is_loopback(host) else None
    manager = StreamableHTTPSessionManager(
        app=build_server(upstream), json_response=True, security_settings=security
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            async with manager.run():
                yield
        finally:
            close = getattr(upstream, "aclose", None)
            if close is not None:
                await close()

    # The exact path: Mount("/mcp") would answer POST /mcp with a 307 to /mcp/.
    app: ASGIApp = Starlette(
        routes=[Route("/mcp", endpoint=_SessionEndpoint(manager), methods=None)],
        lifespan=lifespan,
    )
    return BearerAuth(app, token) if token else app
