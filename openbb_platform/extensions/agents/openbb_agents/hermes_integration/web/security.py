"""Security layer of the HFP sidecar (#1342 T01).

The sidecar sits behind the WebUI extension proxy (``/api/extensions/openbb-hfp/sidecar/``),
which checks the browser session, CSRF, same-origin provenance and owner consent, strips
``Cookie``/``Authorization``/``Origin``/``Referer``/``x-csrf*``/``x-hermes-*`` and injects
``X-Hermes-Sidecar-Token`` (``proxy_auth: token-v1``). This guard never assumes any of that
ran. It re-checks, on every request and before any route:

1. ``Host`` is exactly ``127.0.0.1:<port>`` (DNS rebinding);
2. no ``Origin`` or ``Referer`` (the proxy strips both, so either one means a direct call);
3. ``Sec-Fetch-Site`` is absent, ``same-origin`` or ``none``;
4. the method is GET or POST (no CORS preflight is ever answered);
5. the token-v1 secret, except ``GET /health``: 503 while the token file is missing or
   malformed, 401 on a missing or wrong header (``hmac.compare_digest``);
6. a POST is ``application/json`` (415 otherwise) with a declared body of at most
   :data:`MAX_BODY_BYTES` (411/413).

Responses never carry ``Access-Control-*`` headers. Rejections are a fixed JSON code.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXTENSION_ID = "openbb-hfp"
TOKEN_HEADER = "X-Hermes-Sidecar-Token"  # noqa: S105  (a header name)
MAX_BODY_BYTES = 16 * 1024
# Same grammar as the WebUI fork's ``api/extension_sidecar_auth.py`` ``_TOKEN_RE``.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,256}")
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
_ALLOWED_METHODS = frozenset({"GET", "POST"})
_DEFAULT_OPEN_PATHS = frozenset({"/health"})
_SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
# Loose on purpose: Starlette types scope/messages as ``MutableMapping``.
ASGIApp = Callable[..., Awaitable[None]]


def resolve_token_file(env: Mapping[str, str]) -> Path | None:
    """Token file path: ``HERMES_EXT_SIDECAR_TOKEN_FILE``, else the WebUI state dir.

    Unlike the WebUI fork's lookup order, there is deliberately no fallback to a
    Hermes home: an unset state dir leaves the sidecar unprovisioned (503).
    """
    explicit = env.get("HERMES_EXT_SIDECAR_TOKEN_FILE", "").strip()
    if explicit:
        return Path(explicit)
    state = env.get("HERMES_WEBUI_STATE_DIR", "").strip()
    if state:
        return Path(state) / "sidecar-auth" / f"{EXTENSION_ID}.token"
    return None


def read_token(path: Path | None) -> str | None:
    """Return the token iff the file exists and holds a well-formed token-v1 value."""
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if _TOKEN_RE.fullmatch(text) else None


@dataclass(frozen=True)
class GuardSettings:
    """What the guard enforces; ``port`` is the bound loopback port."""

    port: int
    token_file: Path | None
    open_paths: frozenset[str] = field(default=_DEFAULT_OPEN_PATHS)
    max_body: int = MAX_BODY_BYTES


def _headers(scope: Scope) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1").lower()
        out.setdefault(name, []).append(raw_value.decode("latin-1"))
    return out


def _one(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name)
    if not values:
        return None
    return values[0] if len(values) == 1 else "\x00multiple"


def check_request(  # noqa: PLR0911
    settings: GuardSettings, method: str, path: str, headers: dict[str, list[str]]
) -> tuple[int, str] | None:
    """Return ``(status, code)`` for a rejected request, ``None`` when it may proceed."""
    # pylint: disable=too-many-return-statements
    if _one(headers, "host") != f"127.0.0.1:{settings.port}":
        return 403, "host_rejected"
    if "origin" in headers or "referer" in headers:
        return 403, "origin_rejected"
    site = _one(headers, "sec-fetch-site")
    if site is not None and site.strip().lower() not in _ALLOWED_FETCH_SITES:
        return 403, "fetch_metadata_rejected"
    if method not in _ALLOWED_METHODS:
        return 405, "method_not_allowed"
    if not (method == "GET" and path in settings.open_paths):
        expected = read_token(settings.token_file)
        if expected is None:
            return 503, "token_unprovisioned"
        given = _one(headers, TOKEN_HEADER.lower()) or ""
        if not hmac.compare_digest(given.encode("latin-1"), expected.encode("ascii")):
            return 401, "token_mismatch"
    if method == "POST":
        ctype = (_one(headers, "content-type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return 415, "unsupported_media_type"
        if "transfer-encoding" in headers:
            return 411, "length_required"
        length = _one(headers, "content-length")
        if length is None or not length.isdigit():
            return 411, "length_required"
        if int(length) > settings.max_body:
            return 413, "body_too_large"
    return None


async def _reject(send: Send, status: int, code: str) -> None:
    body = json.dumps({"error": code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *_SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SidecarGuard:  # pylint: disable=too-few-public-methods
    """ASGI middleware applying :func:`check_request` and stripping CORS headers."""

    def __init__(self, app: ASGIApp, settings: GuardSettings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject or forward one ASGI event; responses lose any CORS header."""
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            return  # websockets are never accepted
        method = scope.get("method", "")
        rejection = check_request(
            self.settings, method, scope.get("path", ""), _headers(scope)
        )
        if rejection is not None:
            await _reject(send, *rejection)
            return
        received = 0

        async def bounded_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.settings.max_body:
                raise ValueError("body_too_large")
            return message

        async def clean_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                kept = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if not k.lower().startswith(b"access-control-")
                    and k.lower() not in {b"cache-control", b"x-content-type-options"}
                ]
                message = {**message, "headers": [*kept, *_SECURITY_HEADERS]}
            await send(message)

        await self.app(scope, bounded_receive, clean_send)
