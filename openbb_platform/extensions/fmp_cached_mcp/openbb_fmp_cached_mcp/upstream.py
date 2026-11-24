"""Upstream data sources for the parity server (#1299).

``FmpRestUpstream`` calls FMP ``/stable/<path>`` with the key in the ``apikey``
request header, so it never appears in a URL, a log line or an error. PR-B
(#1300) puts the persistent ``fmp_cached`` store in front of it.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from openbb_fmp_cached_mcp.render import js_number

REST_BASE = "https://financialmodelingprep.com/stable"


@dataclass(frozen=True)
class UpstreamResponse:
    """Raw FMP response."""

    status: int
    body: bytes
    content_type: str = "application/json"


class Upstream(Protocol):
    """Anything that can answer an FMP REST request."""

    async def fetch(self, path: str, params: dict[str, str]) -> UpstreamResponse:
        """Return the raw response for ``GET /stable<path>?<params>``."""


def to_rest_params(
    arguments: dict[str, Any], renames: dict[str, str]
) -> dict[str, str]:
    """Hosted arguments (minus ``endpoint``) -> FMP query parameters."""
    out: dict[str, str] = {}
    for key, raw in arguments.items():
        if key == "endpoint" or raw is None:
            continue
        value: Any = raw
        if isinstance(raw, list):
            value = ",".join(
                js_number(v) if isinstance(v, (int, float)) else str(v) for v in value
            )
        elif isinstance(raw, (bool, int, float)):
            value = js_number(raw)
        out[renames.get(key, key)] = str(value)
    return out


def load_fmp_key() -> str:
    """Return the FMP key from ``FMP_API_KEY`` or OpenBB ``user_settings.json``."""
    key = os.environ.get("FMP_API_KEY", "")
    if key:
        return key
    try:
        from openbb_core.app.service.user_service import (  # pylint: disable=import-outside-toplevel
            UserService,
        )

        creds = UserService().default_user_settings.credentials.model_dump(mode="json")
        return creds.get("fmp_cached_api_key") or creds.get("fmp_api_key") or ""
    except Exception:  # noqa: BLE001  # pylint: disable=broad-except
        return ""


class RateLimiter:
    """Token bucket: ``rate`` requests per second with ``burst`` capacity."""

    def __init__(self, rate: float, burst: int) -> None:
        self.rate, self.capacity = rate, float(burst)
        self.tokens, self.updated = float(burst), time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until one request may be sent."""
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.updated) * self.rate
                )
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class FmpRestUpstream:
    """FMP REST client with bounded concurrency and a request rate limit."""

    def __init__(
        self,
        key: str,
        *,
        base_url: str = REST_BASE,
        max_concurrency: int = 4,
        rate_per_second: float = 5.0,
        burst: int = 10,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not key:
            raise ValueError(
                "FMP key is not configured (FMP_API_KEY or user_settings.json)"
            )
        self._key = key
        self._base = base_url.rstrip("/")
        self._sem = asyncio.Semaphore(max_concurrency)
        self._limiter = RateLimiter(rate_per_second, burst)
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    @property
    def secret(self) -> str:
        """The key, for output scrubbing only."""
        return self._key

    async def fetch(self, path: str, params: dict[str, str]) -> UpstreamResponse:
        """GET ``/stable<path>`` with the key in the ``apikey`` header."""
        async with self._sem:
            await self._limiter.acquire()
            resp = await self._client.get(
                f"{self._base}/{path.lstrip('/')}",
                params=params,
                headers={"apikey": self._key, "Accept": "application/json"},
            )
        return UpstreamResponse(
            resp.status_code, resp.content, resp.headers.get("content-type", "")
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
