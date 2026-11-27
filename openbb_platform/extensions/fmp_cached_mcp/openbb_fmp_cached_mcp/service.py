"""Read-through service: persistent store first, FMP only for what is missing (#1300).

``StoreBackedUpstream.fetch_tool`` answers one hosted-compatible call:

1. resolve the retention policy (``policy.py``);
2. answer from the store when it holds a fresh answer (``state="cached"``);
3. otherwise ask FMP, store the raw answer, and return it (``live``);
4. if FMP fails and the store holds an older answer, return that (``stale``).

Every answer is stored per exact request (path + canonical query). Series
gap-fill, which would fetch only the missing date ranges of a stored series,
is tracked in #1310.

Store I/O runs in worker threads so a slow database never blocks other MCP
sessions. A store outage degrades to live mode with a single warning and is
re-tried after ``STORE_RETRY_S``. A rejected write (a data error, not an
outage) is logged and the fetched answer is still returned, without a second
fetch.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import functools
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openbb_fmp_cached_mcp.endpoint_map import PARAM_RENAMES, endpoint_spec
from openbb_fmp_cached_mcp.policy import (
    NEGATIVE_TTL_S,
    REVISABLE_REFRESH_S,
    Policy,
    resolve_policy,
)
from openbb_fmp_cached_mcp.store import (
    DOCUMENT_TABLE,
    EPHEMERAL_TABLE,
    Store,
    StoreDataError,
    StoredResponse,
    StoreUnavailable,
    request_key,
)
from openbb_fmp_cached_mcp.upstream import Upstream, UpstreamResponse, to_rest_params

logger = logging.getLogger(__name__)

STORE_RETRY_S = 60
PRUNE_EVERY_S = 3600
#: Bodies larger than this are served but not stored (storage-exhaustion bound).
MAX_STORED_BODY_BYTES = 32 * 1024 * 1024
#: Deterministic refusals: remembered briefly. Any other non-200 status
#: (401/403/408/429/5xx/CDN 52x) is treated as transient: stale copy if held.
_REFUSALS = {400, 402, 404}
_EMPTY_BODIES = (b"[]", b"{}", b"")


@dataclass(frozen=True)
class FetchResult:
    """A raw FMP answer plus where it came from (#1269 DataState vocabulary)."""

    response: UpstreamResponse
    state: str  # "live" | "cached" | "stale" | "unavailable"
    source: str  # "fmp" | "fmp_cached"
    as_of: dt.datetime
    reason: str | None = None


@dataclass(frozen=True)
class _Call:
    """One validated tool call, resolved to its REST request and policy."""

    tool: str
    args: dict[str, Any]
    path: str
    params: dict[str, str]
    policy: Policy
    key: str


def _negative_key(key: str) -> str:
    """Return the 64-character key for the remembered refusal of ``key``."""
    return hashlib.sha256(f"neg:{key}".encode()).hexdigest()


def _empty_key(key: str) -> str:
    """Return the key remembering "FMP answered empty" for a stored document."""
    return hashlib.sha256(f"empty:{key}".encode()).hexdigest()


def _fresh(stored: StoredResponse | None, now: dt.datetime) -> bool:
    return stored is not None and (
        stored.fresh_until is None or now < stored.fresh_until
    )


def _object_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


class StoreBackedUpstream:
    """Hosted-tool answers from the persistent store, with FMP REST behind it."""

    def __init__(
        self,
        upstream: Upstream,
        store: Store | None,
        *,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.upstream = upstream
        self.store = store
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self._inflight: dict[str, asyncio.Future[FetchResult]] = {}
        self._store_down_until: dt.datetime | None = None
        self._last_prune: dt.datetime | None = None

    @property
    def secret(self) -> str:
        """The upstream key, for output scrubbing."""
        return str(getattr(self.upstream, "secret", "") or "")

    async def fetch(self, path: str, params: dict[str, str]) -> UpstreamResponse:
        """``Upstream`` protocol: a plain live request."""
        return await self.upstream.fetch(path, params)

    async def aclose(self) -> None:
        """Close the upstream HTTP client."""
        close = getattr(self.upstream, "aclose", None)
        if close is not None:
            await close()

    # -- entry point ----------------------------------------------------------

    async def fetch_tool(self, tool: str, args: dict[str, Any]) -> FetchResult:
        """Answer one validated tool call (single-flight per request)."""
        spec = endpoint_spec(tool, args["endpoint"])
        params = to_rest_params(args, PARAM_RENAMES)
        key = request_key(spec["path"], params)
        while (running := self._inflight.get(key)) is not None:
            try:
                return await asyncio.shield(running)
            except asyncio.CancelledError:
                if not running.cancelled():
                    raise  # this waiter itself was cancelled
                # The owner was cancelled: try again (possibly as the new owner).
        future: asyncio.Future[FetchResult] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            await self._maybe_prune()
            policy = resolve_policy(tool, args, today=self.now().date())
            call = _Call(tool, args, spec["path"], params, policy, key)
            result = await self._answer(call)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # retrieved: no "never retrieved" warning
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._inflight.pop(key, None)

    # -- store access (worker threads) ----------------------------------------

    @staticmethod
    async def _io(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run blocking store I/O off the event loop."""
        return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))

    def _store_ok(self) -> bool:
        if self.store is None:
            return False
        return self._store_down_until is None or self.now() >= self._store_down_until

    def _mark_down(self, exc: Exception) -> None:
        if self._store_down_until is None or self.now() >= self._store_down_until:
            logger.warning(
                "fmp_cached store unavailable (%s); serving live from FMP for %ss",
                type(exc).__name__,
                STORE_RETRY_S,
            )
        self._store_down_until = self.now() + dt.timedelta(seconds=STORE_RETRY_S)

    async def _write(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        """Run a store write; a failure never loses the already fetched answer."""
        try:
            await self._io(fn, *args, **kwargs)
            return True
        except StoreDataError as exc:
            logger.warning("fmp_cached store rejected a write (%s)", exc)
        except StoreUnavailable as exc:
            self._mark_down(exc)
        return False

    async def _maybe_prune(self) -> None:
        if not self._store_ok() or self.store is None:
            return
        now = self.now()
        if (
            self._last_prune
            and (now - self._last_prune).total_seconds() < PRUNE_EVERY_S
        ):
            return
        self._last_prune = now
        await self._write(self.store.prune_ephemeral)

    async def _with_store(
        self,
        work: Callable[[], Awaitable[FetchResult]],
        live: Callable[[], Awaitable[FetchResult]],
    ) -> FetchResult:
        if not self._store_ok():
            return await live()
        try:
            return await work()
        except StoreUnavailable as exc:  # a read failed before any fetch
            self._mark_down(exc)
            return await live()
        except StoreDataError as exc:  # one bad read; the store itself is fine
            logger.warning("fmp_cached store rejected a read (%s)", exc)
            return await live()

    # -- dispatch -------------------------------------------------------------

    async def _answer(self, call: _Call) -> FetchResult:
        async def live() -> FetchResult:
            resp = await self.upstream.fetch(call.path, call.params)
            return FetchResult(resp, "live", "fmp", self.now())

        if call.policy.mode == "no-store":
            return await live()

        async def document() -> FetchResult:
            return await self._document(call)

        return await self._with_store(document, live)

    def _require_store(self) -> Store:
        if self.store is None:
            raise StoreUnavailable("no store configured")
        return self.store

    async def _put(  # pylint: disable=too-many-arguments
        self,
        table: str,
        key: str,
        call: _Call,
        *,
        resp: UpstreamResponse,
        fresh_s: int | None,
    ) -> None:
        if len(resp.body) > MAX_STORED_BODY_BYTES:
            logger.info(
                "not storing a %d-byte answer for %s", len(resp.body), call.path
            )
            return
        await self._write(
            self._require_store().put_response,
            table,
            key,
            tool=call.tool,
            endpoint=call.args["endpoint"],
            path=call.path,
            params=call.params,
            retention=call.policy.retention,
            status=resp.status,
            body=resp.body,
            fresh_s=fresh_s,
        )

    async def _stored_answer(
        self, store: Store, call: _Call, now: dt.datetime
    ) -> tuple[FetchResult | None, StoredResponse | None]:
        """Return ``(answer from the store or None, last stored copy or None)``."""
        key = call.key
        negative = await self._io(
            store.get_response, EPHEMERAL_TABLE, _negative_key(key)
        )
        if negative is not None and _fresh(negative, now):
            return self._from_store(negative, "cached"), None
        stored = await self._io(store.get_response, EPHEMERAL_TABLE, key)
        if call.policy.mode != "ephemeral":
            if stored is not None and _fresh(stored, now):
                return self._from_store(stored, "cached"), None  # fresh empty answer
            stored = await self._io(store.get_response, DOCUMENT_TABLE, key)
            if stored is not None and not _fresh(stored, now):
                empty = await self._io(
                    store.get_response, EPHEMERAL_TABLE, _empty_key(key)
                )
                if empty is not None and _fresh(empty, now):
                    # FMP answered empty recently: keep serving the last good copy.
                    return self._from_store(stored, "stale", "upstream-empty"), None
        if stored is not None and _fresh(stored, now):
            return self._from_store(stored, "cached"), None
        return None, stored

    async def _document(self, call: _Call) -> FetchResult:
        store = self._require_store()
        policy, key, now = call.policy, call.key, self.now()
        persistent = policy.mode != "ephemeral"
        answer, stored = await self._stored_answer(store, call, now)
        if answer is not None:
            return answer
        try:
            resp = await self.upstream.fetch(call.path, call.params)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            return self._stale_or_raise(stored, exc)
        if resp.status in _REFUSALS:
            # Deterministic refusals: remember briefly, never persist.
            await self._put(
                EPHEMERAL_TABLE,
                _negative_key(key),
                call,
                resp=resp,
                fresh_s=NEGATIVE_TTL_S,
            )
            return FetchResult(
                resp, "unavailable", "fmp", now, f"upstream-{resp.status}"
            )
        if resp.status != 200:
            if stored:
                return self._from_store(stored, "stale", f"upstream-{resp.status}")
            # Nothing held: FMP's answer is rendered exactly as the hosted
            # server renders it ("Bad request for tool ...: <FMP message>").
            return FetchResult(
                resp, "unavailable", "fmp", now, f"upstream-{resp.status}"
            )
        if resp.body.strip() in _EMPTY_BODIES and persistent and stored is not None:
            # A transient empty answer must not hide the last good copy: serve
            # it as stale and remember the empty answer for a day.
            await self._put(
                EPHEMERAL_TABLE,
                _empty_key(key),
                call,
                resp=resp,
                fresh_s=REVISABLE_REFRESH_S,
            )
            return self._from_store(stored, "stale", "upstream-empty")
        if resp.body.strip() in _EMPTY_BODIES:
            # Not found today may exist tomorrow, and arbitrary lookups must
            # not grow the persistent tables: empty answers stay ephemeral.
            ttl = policy.refresh_s if not persistent else None
            await self._put(
                EPHEMERAL_TABLE,
                key,
                call,
                resp=resp,
                fresh_s=ttl or REVISABLE_REFRESH_S,
            )
        else:
            table = DOCUMENT_TABLE if persistent else EPHEMERAL_TABLE
            await self._put(table, key, call, resp=resp, fresh_s=policy.refresh_s)
            if policy.feed:
                rows = _object_rows(resp.body)
                if rows:
                    await self._write(store.put_feed_items, call.path, rows)
        return FetchResult(resp, "live", "fmp", now)

    @staticmethod
    def _from_store(
        stored: StoredResponse, state: str, reason: str | None = None
    ) -> FetchResult:
        return FetchResult(
            UpstreamResponse(stored.status, stored.body),
            state,
            "fmp_cached",
            stored.fetched_at,
            reason,
        )

    @staticmethod
    def _stale_or_raise(stored: StoredResponse | None, exc: Exception) -> FetchResult:
        if stored is None:
            raise exc
        logger.warning(
            "upstream failed (%s); serving stored answer", type(exc).__name__
        )
        return StoreBackedUpstream._from_store(stored, "stale", "upstream-error")
