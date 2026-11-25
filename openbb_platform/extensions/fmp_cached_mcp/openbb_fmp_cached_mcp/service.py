"""Read-through service: persistent store first, FMP only for what is missing (#1300).

``StoreBackedUpstream.fetch_tool`` answers one hosted-compatible call:

1. resolve the retention policy (``policy.py``);
2. answer from the store when it holds a fresh answer (``state="cached"``);
3. otherwise ask FMP for the missing part only (series gaps / open tail, or the
   one document), store the raw answer, and return it (``live``);
4. if FMP fails and the store holds an older answer, return that (``stale``).

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
#: Final days re-fetched with every tail refresh to detect re-based history
#: (splits, dividend adjustments).
OVERLAP_DAYS = 5
MAX_TS_LEN = 32  # fmp_mcp_series_row.ts is VARCHAR(32)
_TRANSIENT = {429, 500, 502, 503, 504}
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


class _Fallback(Exception):
    """Internal: serve this call through the document path.

    ``prefetched`` carries FMP's answer when it was fetched for exactly the
    call's own request, so the document path does not fetch it again.
    """

    def __init__(self, prefetched: UpstreamResponse | None = None) -> None:
        super().__init__()
        self.prefetched = prefetched


class _Refused(Exception):
    """Internal: FMP refused a series request (400/402/404)."""

    def __init__(self, response: UpstreamResponse) -> None:
        super().__init__()
        self.response = response


def _series_key(params: dict[str, str]) -> str:
    rest = sorted((k, v) for k, v in params.items() if k not in ("from", "to"))
    return hashlib.sha256(json.dumps(rest).encode()).hexdigest()


def _negative_key(key: str) -> str:
    """Return the 64-character key for the remembered refusal of ``key``."""
    return hashlib.sha256(f"neg:{key}".encode()).hexdigest()


def _date_rows(body: bytes) -> list[dict[str, Any]] | None:
    """Return the body's rows when every row is an object with a usable ``date``."""
    try:
        rows = json.loads(body)
    except ValueError:
        return None
    if not isinstance(rows, list) or not all(
        isinstance(r, dict)
        and isinstance(r.get("date"), str)
        and 10 <= len(r["date"]) <= MAX_TS_LEN
        for r in rows
    ):
        return None
    return rows


def _subtract(
    start: dt.date, end: dt.date, covered: list[tuple[dt.date, dt.date]]
) -> list[tuple[dt.date, dt.date]]:
    """Return the parts of ``[start, end]`` not inside any covered range."""
    gaps, cursor = [], start
    for a, b in sorted(covered):
        if b < cursor:
            continue
        if a > end:
            break
        if a > cursor:
            gaps.append((cursor, min(end, a - dt.timedelta(days=1))))
        cursor = max(cursor, b + dt.timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def _in_range(ts: str, start: dt.date, end: dt.date) -> bool:
    return start.isoformat() <= ts[:10] <= end.isoformat()


def _fresh(stored: StoredResponse | None, now: dt.datetime) -> bool:
    return stored is not None and (
        stored.fresh_until is None or now < stored.fresh_until
    )


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
            result = await self._answer(tool, args, spec, params, key)
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

    async def _answer(  # pylint: disable=too-many-arguments
        self,
        tool: str,
        args: dict[str, Any],
        spec: dict,
        params: dict[str, str],
        key: str,
    ) -> FetchResult:
        policy = resolve_policy(tool, args, today=self.now().date())
        path = spec["path"]
        call = _Call(tool, args, path, params, policy, key)

        async def live() -> FetchResult:
            return await self._live(path, params)

        if policy.mode == "no-store":
            return await live()
        if policy.mode == "series":

            async def series() -> FetchResult:
                try:
                    return await self._series(call)
                except _Fallback as fb:
                    return await self._document(call, prefetched=fb.prefetched)

            return await self._with_store(series, live)

        async def document() -> FetchResult:
            return await self._document(call)

        return await self._with_store(document, live)

    async def _live(self, path: str, params: dict[str, str]) -> FetchResult:
        resp = await self.upstream.fetch(path, params)
        return FetchResult(resp, "live", "fmp", self.now())

    def _require_store(self) -> Store:
        if self.store is None:
            raise StoreUnavailable("no store configured")
        return self.store

    # -- documents / ephemeral ------------------------------------------------

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

    async def _remember_refusal(
        self, call: _Call, resp: UpstreamResponse
    ) -> FetchResult:
        """Deterministic refusals (400/402/404): remember briefly, never persist."""
        await self._put(
            EPHEMERAL_TABLE,
            _negative_key(call.key),
            call,
            resp=resp,
            fresh_s=NEGATIVE_TTL_S,
        )
        return FetchResult(
            resp, "unavailable", "fmp", self.now(), f"upstream-{resp.status}"
        )

    async def _remember_empty(self, call: _Call, resp: UpstreamResponse) -> None:
        """Keep an empty answer as ephemeral only.

        Not found today may exist tomorrow, and arbitrary lookups must not grow
        the persistent tables.
        """
        ttl = call.policy.refresh_s if call.policy.mode == "ephemeral" else None
        await self._put(
            EPHEMERAL_TABLE,
            call.key,
            call,
            resp=resp,
            fresh_s=ttl or REVISABLE_REFRESH_S,
        )

    async def _document(
        self, call: _Call, prefetched: UpstreamResponse | None = None
    ) -> FetchResult:
        store = self._require_store()
        policy, key, now = call.policy, call.key, self.now()
        persistent = policy.mode != "ephemeral"
        negative = await self._io(
            store.get_response, EPHEMERAL_TABLE, _negative_key(key)
        )
        if negative is not None and _fresh(negative, now):
            return self._from_store(negative, "cached")
        ephemeral = await self._io(store.get_response, EPHEMERAL_TABLE, key)
        stored = ephemeral
        if persistent:
            if ephemeral is not None and _fresh(ephemeral, now):
                return self._from_store(ephemeral, "cached")  # a fresh empty answer
            stored = await self._io(store.get_response, DOCUMENT_TABLE, key)
        if stored is not None and _fresh(stored, now):
            return self._from_store(stored, "cached")
        try:
            resp = prefetched or await self.upstream.fetch(call.path, call.params)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            return self._stale_or_raise(stored, exc)
        if resp.status in _TRANSIENT:
            if stored:
                return self._from_store(stored, "stale", f"upstream-{resp.status}")
            return FetchResult(
                resp, "unavailable", "fmp", now, f"upstream-{resp.status}"
            )
        if resp.status != 200:
            return await self._remember_refusal(call, resp)
        if resp.body.strip() in _EMPTY_BODIES:
            await self._remember_empty(call, resp)
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

    # -- series ---------------------------------------------------------------

    async def _plan_segments(  # pylint: disable=too-many-arguments
        self, store: Store, call: _Call, skey: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, dt.date]]:
        """Return the date ranges to fetch: final-coverage gaps plus the open tail."""
        now = self.now()
        final_cut = now.date() - dt.timedelta(days=call.policy.final_lag_days)
        covered = [
            (a, b)
            for a, b, _ in await self._io(store.coverage, call.path, skey, "final")
        ]
        segments = (
            _subtract(start, min(end, final_cut), covered) if start <= final_cut else []
        )
        if end <= final_cut:
            return segments
        tail_from = max(start, final_cut + dt.timedelta(days=1))
        ttl = call.policy.refresh_s or 0
        tails = await self._io(store.coverage, call.path, skey, "tail")
        if any(
            a <= tail_from and b >= end and (now - fetched).total_seconds() < ttl
            for a, b, fetched in tails
        ):
            return segments
        seg_from = tail_from
        if segments and segments[-1][1] >= final_cut:
            seg_from = segments.pop()[0]  # merge an adjacent gap into the tail fetch
        overlap_from = seg_from - dt.timedelta(days=OVERLAP_DAYS)
        if any(
            a <= seg_from - dt.timedelta(days=1) and b >= overlap_from
            for a, b in covered
        ):
            seg_from = overlap_from  # re-fetch a few final days to detect re-basing
        segments.append((seg_from, end))
        return segments

    async def _cached_answer(self, store: Store, call: _Call) -> FetchResult | None:
        """Return a fresh remembered refusal or empty answer for this exact call."""
        now = self.now()
        for key in (_negative_key(call.key), call.key):
            hit = await self._io(store.get_response, EPHEMERAL_TABLE, key)
            if hit is not None and _fresh(hit, now):
                return self._from_store(hit, "cached")
        return None

    async def _series(self, call: _Call) -> FetchResult:
        store = self._require_store()
        lag = call.policy.final_lag_days
        try:
            start = dt.date.fromisoformat(call.params["from"])
            end = dt.date.fromisoformat(call.params["to"])
            # Reject ranges whose date arithmetic would overflow either way.
            _ = start - dt.timedelta(days=OVERLAP_DAYS + lag + 2)
            _ = end + dt.timedelta(days=lag + 2)
        except (KeyError, ValueError, OverflowError):
            raise _Fallback() from None
        cached = await self._cached_answer(store, call)
        if cached is not None:
            return cached
        if await self._io(store.get_response, DOCUMENT_TABLE, call.key) is not None:
            raise _Fallback()  # this request was served as a document before
        skey = _series_key(call.params)
        stored = await self._io(store.series_rows, call.path, skey, start, end)
        segments = await self._plan_segments(store, call, skey, start, end)
        if not segments:
            return self._series_result(stored, "cached", None)
        try:
            fresh = await self._fetch_segments(call, segments)
        except _Refused as exc:
            return await self._remember_refusal(call, exc.response)
        except _Fallback:
            raise
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            if not stored:
                raise exc
            logger.warning(
                "upstream failed (%s); serving stored series", type(exc).__name__
            )
            return self._series_result(stored, "stale", "upstream-error")
        if not stored and not any(rows for _, rows in fresh):
            # Unknown symbol, not listed yet, or nothing in range: no persistent
            # coverage; remember the empty answer for a day like documents do.
            empty = UpstreamResponse(200, b"[]")
            await self._remember_empty(call, empty)
            return FetchResult(empty, "live", "fmp", self.now())
        fresh, stored = await self._check_rebased(store, call, skey, fresh, stored)
        return await self._store_series(store, call, skey, fresh, stored)

    async def _check_rebased(  # pylint: disable=too-many-arguments
        self, store: Store, call: _Call, skey: str, fresh, stored
    ):
        try:
            rebased = await self._rebased(store, call, skey, fresh)
        except (StoreUnavailable, StoreDataError) as exc:
            logger.warning("re-basing check skipped (%s)", type(exc).__name__)
            return fresh, stored
        if not rebased:
            return fresh, stored
        logger.info(
            "series %s re-based upstream; re-fetching the requested range", call.path
        )
        await self._write(store.drop_series, call.path, skey)
        start = dt.date.fromisoformat(call.params["from"])
        end = dt.date.fromisoformat(call.params["to"])
        return await self._fetch_segments(call, [(start, end)]), []

    async def _store_series(  # pylint: disable=too-many-arguments
        self, store: Store, call: _Call, skey: str, fresh, stored
    ) -> FetchResult:
        now = self.now()
        start = dt.date.fromisoformat(call.params["from"])
        end = dt.date.fromisoformat(call.params["to"])
        final_cut = now.date() - dt.timedelta(days=call.policy.final_lag_days)
        merged = {ts: (rj, f) for ts, rj, f in stored}
        for (a, b), rows in fresh:
            for ts in [t for t in merged if _in_range(t, a, b)]:
                del merged[ts]  # FMP's answer for [a, b] replaces what we held
            for row in rows:
                if _in_range(row["date"], start, end):
                    merged[row["date"]] = (json.dumps(row, ensure_ascii=False), now)
            await self._write(store.replace_series_range, call.path, skey, a, b, rows)
            if a <= final_cut:
                await self._write(
                    store.add_final_coverage, call.path, skey, a, min(b, final_cut)
                )
            if b > final_cut:
                tail_from = max(a, final_cut + dt.timedelta(days=1))
                await self._write(store.set_tail, call.path, skey, tail_from, b)
        rows_out = [(ts, rj, f) for ts, (rj, f) in sorted(merged.items(), reverse=True)]
        return self._series_result(rows_out, "live", None)

    async def _fetch_segments(
        self, call: _Call, segments: list[tuple[dt.date, dt.date]]
    ) -> list[tuple[tuple[dt.date, dt.date], list[dict[str, Any]]]]:
        out = []
        for a, b in segments:
            params = {**call.params, "from": a.isoformat(), "to": b.isoformat()}
            resp = await self.upstream.fetch(call.path, params)
            own_request = params == call.params
            if resp.status != 200:
                if resp.status in _TRANSIENT:
                    raise ConnectionError(f"upstream-{resp.status}")
                raise _Refused(resp)
            rows = _date_rows(resp.body)
            if rows is None or not all(_in_range(r["date"], a, b) for r in rows):
                # Not a range series after all (FMP ignored from/to, or rows
                # without usable dates): serve FMP's answer as a document.
                raise _Fallback(resp if own_request else None)
            out.append(((a, b), rows))
        return out

    async def _rebased(self, store: Store, call: _Call, skey: str, fresh) -> bool:
        """Return True when a re-fetched row differs from a copy stored as final.

        Rows stored while still open (within the series' finality lag of their
        fetch) are expected to change and are not compared.
        """
        lag = dt.timedelta(days=call.policy.final_lag_days)
        for (a, b), rows in fresh:
            held = await self._io(store.series_rows, call.path, skey, a, b)
            old = {
                ts: rj
                for ts, rj, fetched in held
                if dt.date.fromisoformat(ts[:10]) <= fetched.date() - lag
            }
            for row in rows:
                ts = str(row["date"])
                if ts in old and json.loads(old[ts]) != row:
                    return True
        return False

    def _series_result(self, stored, state: str, reason: str | None) -> FetchResult:
        body = "[" + ",".join(rj for _, rj, _ in stored) + "]"
        as_of = min((f for _, _, f in stored), default=self.now())
        return FetchResult(
            UpstreamResponse(200, body.encode()),
            state,
            "fmp_cached" if state != "live" else "fmp",
            as_of,
            reason,
        )


def _object_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
