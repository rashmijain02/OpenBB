"""Read-through service: persistent store first, FMP only for what is missing (#1300).

``StoreBackedUpstream.fetch_tool`` answers one hosted-compatible call:

1. resolve the retention policy (``policy.py``);
2. answer from the store when it holds a fresh answer (``state="cached"``);
3. otherwise ask FMP for the missing part only (series gaps / open tail, or the
   one document), store the raw answer, and return it (``live``);
4. if FMP fails and the store holds an older answer, return that (``stale``).

A store outage degrades to live mode with a single warning; the store is
re-tried after ``STORE_RETRY_S``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openbb_fmp_cached_mcp.endpoint_map import PARAM_RENAMES, endpoint_spec
from openbb_fmp_cached_mcp.policy import (
    NEGATIVE_TTL_S,
    RECENT_DAYS,
    REVISABLE_REFRESH_S,
    Policy,
    resolve_policy,
)
from openbb_fmp_cached_mcp.store import (
    DOCUMENT_TABLE,
    EPHEMERAL_TABLE,
    Store,
    StoredResponse,
    StoreUnavailable,
    request_key,
)
from openbb_fmp_cached_mcp.upstream import Upstream, UpstreamResponse, to_rest_params

logger = logging.getLogger(__name__)

STORE_RETRY_S = 60
#: Final days re-fetched with every tail refresh to detect re-based history
#: (splits, dividend adjustments).
OVERLAP_DAYS = 5
_TRANSIENT = {429, 500, 502, 503, 504}


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
    """Internal: the series path cannot serve this call; use the document path."""


def _series_key(params: dict[str, str]) -> str:
    rest = sorted((k, v) for k, v in params.items() if k not in ("from", "to"))
    return hashlib.sha256(json.dumps(rest).encode()).hexdigest()


def _date_rows(body: bytes) -> list[dict[str, Any]] | None:
    """Return the body's rows when every row is an object with a string ``date``."""
    try:
        rows = json.loads(body)
    except ValueError:
        return None
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and isinstance(r.get("date"), str) and len(r["date"]) >= 10
        for r in rows
    ):
        return None
    return rows


def _subtract(
    start: dt.date, end: dt.date, covered: list[tuple[dt.date, dt.date]]
) -> list[tuple[dt.date, dt.date]]:
    """Parts of ``[start, end]`` not inside any covered range."""
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
        running = self._inflight.get(key)
        if running is not None:
            return await asyncio.shield(running)
        future: asyncio.Future[FetchResult] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            result = await self._answer(tool, args, spec, params, key)
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved for waiters-less futures
            raise
        finally:
            self._inflight.pop(key, None)

    # -- store availability ---------------------------------------------------

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

    async def _with_store(
        self,
        work: Callable[[], Awaitable[FetchResult]],
        live: Callable[[], Awaitable[FetchResult]],
    ) -> FetchResult:
        if not self._store_ok():
            return await live()
        try:
            return await work()
        except StoreUnavailable as exc:
            self._mark_down(exc)
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
                except _Fallback:
                    return await self._document(call)

            return await self._with_store(series, live)

        async def document() -> FetchResult:
            return await self._document(call)

        return await self._with_store(document, live)

    async def _live(self, path: str, params: dict[str, str]) -> FetchResult:
        resp = await self.upstream.fetch(path, params)
        return FetchResult(resp, "live", "fmp", self.now())

    # -- documents / ephemeral ------------------------------------------------

    def _require_store(self) -> Store:
        if self.store is None:
            raise StoreUnavailable("no store configured")
        return self.store

    async def _document(self, call: _Call) -> FetchResult:
        store = self._require_store()
        tool, args, path, params = call.tool, call.args, call.path, call.params
        policy, key = call.policy, call.key
        table = EPHEMERAL_TABLE if policy.mode == "ephemeral" else DOCUMENT_TABLE
        now = self.now()
        stored = store.get_response(table, key)
        negative = store.get_response(EPHEMERAL_TABLE, "neg:" + key)
        if negative and negative.fresh_until and now < negative.fresh_until:
            return self._from_store(negative, "cached")
        if stored and (stored.fresh_until is None or now < stored.fresh_until):
            return self._from_store(stored, "cached")
        try:
            resp = await self.upstream.fetch(path, params)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            return self._stale_or_raise(stored, exc)
        if resp.status in _TRANSIENT:
            if stored:
                return self._from_store(stored, "stale", f"upstream-{resp.status}")
            return FetchResult(
                resp, "unavailable", "fmp", now, f"upstream-{resp.status}"
            )
        if resp.status != 200:
            # Deterministic refusals (400/402/404): remember briefly, never persist.
            store.put_response(
                EPHEMERAL_TABLE,
                "neg:" + key,
                tool=tool,
                endpoint=args["endpoint"],
                path=path,
                params=params,
                retention=policy.retention,
                status=resp.status,
                body=resp.body,
                fresh_s=NEGATIVE_TTL_S,
            )
            return FetchResult(
                resp, "unavailable", "fmp", now, f"upstream-{resp.status}"
            )
        store.put_response(
            table,
            key,
            tool=tool,
            endpoint=args["endpoint"],
            path=path,
            params=params,
            retention=policy.retention,
            status=200,
            body=resp.body,
            fresh_s=_fresh_seconds(policy, resp.body),
        )
        if policy.feed:
            rows = _object_rows(resp.body)
            if rows:
                store.put_feed_items(path, rows)
        return FetchResult(resp, "live", "fmp", now)

    def _from_store(
        self, stored: StoredResponse, state: str, reason: str | None = None
    ) -> FetchResult:
        return FetchResult(
            UpstreamResponse(stored.status, stored.body),
            state,
            "fmp_cached",
            stored.fetched_at,
            reason,
        )

    def _stale_or_raise(
        self, stored: StoredResponse | None, exc: Exception
    ) -> FetchResult:
        if stored is None:
            raise exc
        logger.warning(
            "upstream failed (%s); serving stored answer", type(exc).__name__
        )
        return self._from_store(stored, "stale", "upstream-error")

    # -- series ---------------------------------------------------------------

    async def _series(self, call: _Call) -> FetchResult:
        store = self._require_store()
        path, params, policy, key = call.path, call.params, call.policy, call.key
        try:
            start = dt.date.fromisoformat(params["from"])
            end = dt.date.fromisoformat(params["to"])
        except (KeyError, ValueError):
            raise _Fallback() from None
        doc = store.get_response(DOCUMENT_TABLE, key)
        if doc is not None:  # this request was served as a document before
            raise _Fallback()
        skey = _series_key(params)
        now = self.now()
        final_cut = now.date() - dt.timedelta(days=RECENT_DAYS)
        covered = [(a, b) for a, b, _ in store.coverage(path, skey, "final")]
        gaps = (
            _subtract(start, min(end, final_cut), covered) if start <= final_cut else []
        )
        segments = list(gaps)
        tail_from = max(start, final_cut + dt.timedelta(days=1))
        tail_needed = False
        if end > final_cut:
            tails = store.coverage(path, skey, "tail")
            fresh = [
                t
                for t in tails
                if t[0] <= tail_from
                and t[1] >= end
                and (now - t[2]).total_seconds() < (policy.refresh_s or 0)
            ]
            tail_needed = not fresh
        if tail_needed:
            seg_from = tail_from
            if segments and segments[-1][1] >= final_cut:
                seg_from = segments.pop()[
                    0
                ]  # merge an adjacent gap into the tail fetch
            elif covered and any(
                a <= final_cut and b >= tail_from - dt.timedelta(days=OVERLAP_DAYS)
                for a, b in covered
            ):
                seg_from = tail_from - dt.timedelta(
                    days=OVERLAP_DAYS
                )  # re-basing check
            segments.append((seg_from, end))

        fresh_rows: list[tuple[tuple[dt.date, dt.date], list[dict[str, Any]]]] = []
        try:
            for a, b in segments:
                resp = await self.upstream.fetch(
                    path, {**params, "from": a.isoformat(), "to": b.isoformat()}
                )
                if resp.status != 200:
                    if resp.status in _TRANSIENT:
                        raise ConnectionError(f"upstream-{resp.status}")
                    raise _Fallback()  # let the document path render/remember the refusal
                rows = _date_rows(resp.body)
                if rows is None:
                    raise _Fallback()
                fresh_rows.append(((a, b), rows))
        except _Fallback:
            raise
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            stored = store.series_rows(path, skey, start, end)
            if not stored:
                raise exc
            logger.warning(
                "upstream failed (%s); serving stored series", type(exc).__name__
            )
            return self._series_result(stored, "stale", "upstream-error")

        if fresh_rows and self._rebased(store, path, skey, fresh_rows, final_cut):
            logger.info(
                "series %s re-based upstream; re-fetching the requested range", path
            )
            store.drop_series(path, skey)
            resp = await self.upstream.fetch(
                path, {**params, "from": start.isoformat(), "to": end.isoformat()}
            )
            rows = _date_rows(resp.body) if resp.status == 200 else None
            if rows is None:
                raise _Fallback()
            fresh_rows = [((start, end), rows)]

        for (a, b), rows in fresh_rows:
            store.put_series_rows(path, skey, rows)
            if a <= final_cut:
                store.add_final_coverage(path, skey, a, min(b, final_cut))
            if b > final_cut:
                store.set_tail(path, skey, max(a, final_cut + dt.timedelta(days=1)), b)
        stored = store.series_rows(path, skey, start, end)
        return self._series_result(stored, "live" if fresh_rows else "cached", None)

    @staticmethod
    def _rebased(store: Store, path: str, skey: str, fresh, final_cut: dt.date) -> bool:
        """Return True when a re-fetched final row differs from the stored copy."""
        for (a, b), rows in fresh:
            if a > final_cut:
                continue
            old = {
                ts: rj
                for ts, rj, _ in store.series_rows(path, skey, a, min(b, final_cut))
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


def _fresh_seconds(policy: Policy, body: bytes) -> int | None:
    """Policy refresh, except an empty answer is never immutable.

    A not-found today (no filing, no trade yet) may exist tomorrow, so empty
    answers are re-checked at the revisable interval.
    """
    if policy.refresh_s is None and body.strip() in (b"[]", b"{}", b""):
        return REVISABLE_REFRESH_S
    return policy.refresh_s


def _object_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
