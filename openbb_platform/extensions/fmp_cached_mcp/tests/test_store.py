"""Persistent store semantics (#1300): keep meaningful data forever, TTL only for ephemeral.

Runs the real service + store code on the SQLite backend (same SQL paths as
MySQL except the upsert clause) with a fake FMP upstream and a fake clock.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import json
import logging
import sqlite3

import pytest

from openbb_fmp_cached_mcp.policy import resolve_policy
from openbb_fmp_cached_mcp.service import StoreBackedUpstream
from openbb_fmp_cached_mcp.store import (
    ALL_TABLES,
    EPHEMERAL_TABLE,
    PERSISTENT_TABLES,
    SqliteDatabase,
    Store,
    StoreDataError,
    StoreUnavailable,
)
from openbb_fmp_cached_mcp.upstream import UpstreamResponse

from .conftest import SNAPSHOT, load_hosted

TODAY = dt.date(2026, 11, 24)


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.timezone.utc)

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += dt.timedelta(**kw)


def _daily_rows(start: dt.date, end: dt.date, symbol="AAPL", price=100.0):
    rows, d = [], end
    while d >= start:
        if d.weekday() < 5:
            rows.append(
                {"symbol": symbol, "date": d.isoformat(), "price": price + d.day}
            )
        d -= dt.timedelta(days=1)
    return rows


class FakeFmp:
    """FMP REST double: serves range-filtered daily rows and fixed documents."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False
        self.docs: dict[str, UpstreamResponse] = {}
        self.price_shift = 0.0
        self.secret = ""
        self.clock = None  # when set, "today" follows the test clock
        self.provisional_from: dt.date | None = None  # rows >= get +0.5 (open bars)
        self.omit: set[str] = set()
        self.gate: asyncio.Event | None = None

    async def fetch(self, path, params):
        self.calls.append((path, dict(params)))
        await asyncio.sleep(0)  # a real request yields to the event loop
        if self.fail:
            raise ConnectionError("down")
        if path in self.docs:
            return self.docs[path]
        if self.gate is not None:
            await self.gate.wait()
        if path.startswith("/historical-price-eod"):
            today = self.clock().date() if self.clock else TODAY
            start = dt.date.fromisoformat(params.get("from", "2026-01-01"))
            start = max(start, dt.date(2020, 1, 2))  # first traded day in the fake
            end = dt.date.fromisoformat(params.get("to", today.isoformat()))
            end = min(end, today)
            rows = _daily_rows(start, end, params["symbol"], 100.0 + self.price_shift)
            rows = [r for r in rows if r["date"] not in self.omit]
            if self.provisional_from is not None:
                for r in rows:
                    if r["date"] >= self.provisional_from.isoformat():
                        r["price"] += 0.5
            return UpstreamResponse(200, json.dumps(rows, indent=2).encode())
        return UpstreamResponse(
            200, json.dumps([{"path": path, "n": len(self.calls)}]).encode()
        )


@pytest.fixture()
def env():
    clock = Clock()
    db = SqliteDatabase(":memory:")
    store = Store(db, now=clock)
    store.create_tables()
    fmp = FakeFmp()
    svc = StoreBackedUpstream(fmp, store, now=clock)
    return svc, fmp, store, clock


def _get(svc, tool, args):
    return asyncio.run(svc.fetch_tool(tool, args))


EOD = {"endpoint": "historical-price-eod-light", "symbol": "AAPL"}


def _range(a, b):
    return {**EOD, "from_date": a, "to_date": b}


# --- policy -------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool, args, mode, refresh",
    [
        (
            "statements",
            {
                "endpoint": "financial-reports-form-10-k-json",
                "symbol": "AAPL",
                "year": 2024,
                "period": "FY",
            },
            "document",
            None,
        ),
        (
            "statements",
            {"endpoint": "income-statement", "symbol": "AAPL"},
            "document",
            86400,
        ),
        ("directory", {"endpoint": "available-sectors"}, "document", 86400),
        ("quote", {"endpoint": "quote", "symbol": "AAPL"}, "ephemeral", 15),
        ("news", {"endpoint": "general-news"}, "ephemeral", 600),
        (
            "discountedCashFlow",
            {"endpoint": "custom-dcf-advanced", "symbol": "AAPL"},
            "no-store",
            None,
        ),
        # Series ranges are stored per request (#1310 tracks gap-fill):
        # open ranges refresh by interval, past ranges daily (split-adjusted
        # history can be re-based upstream).
        ("chart", _range("2026-11-02", "2026-11-06"), "document", 86400),
        ("chart", _range("2026-11-02", "2026-11-24"), "document", 3600),
        (
            "chart",
            {
                "endpoint": "intraday-1-min",
                "symbol": "AAPL",
                "from_date": "2026-11-20",
                "to_date": "2026-11-24",
            },
            "document",
            60,
        ),
        (
            "economics",
            {
                "endpoint": "economics-indicators",
                "name": "GDP",
                "from_date": "2026-01-01",
                "to_date": "2026-09-01",
            },
            "document",
            86400,
        ),
        (
            "marketPerformance",
            {"endpoint": "sector-performance-snapshot", "date": "2025-01-02"},
            "document",
            None,
        ),
        (
            "marketPerformance",
            {"endpoint": "sector-performance-snapshot", "date": "2026-11-24"},
            "ephemeral",
            300,
        ),
    ],
)
def test_policy(tool, args, mode, refresh):
    pol = resolve_policy(tool, args, today=TODAY)
    assert (pol.mode, pol.refresh_s) == (mode, refresh)


def test_every_endpoint_resolves_to_a_policy(hosted_inventory):
    for t in hosted_inventory["tools"]:
        for ep in t["inputSchema"]["properties"]["endpoint"]["enum"]:
            assert resolve_policy(t["name"], {"endpoint": ep}, today=TODAY).mode


# --- documents ----------------------------------------------------------------


def test_immutable_document_is_fetched_once_and_kept(env):
    svc, fmp, _, clock = env
    args = {
        "endpoint": "financial-reports-form-10-k-json",
        "symbol": "AAPL",
        "year": 2024,
        "period": "FY",
    }
    first = _get(svc, "statements", args)
    clock.advance(days=400)
    second = _get(svc, "statements", args)
    assert len(fmp.calls) == 1
    assert first.response.body == second.response.body
    assert (first.state, second.state) == ("live", "cached")


def test_revisable_document_refreshes_after_interval_and_keeps_last_good(env):
    svc, fmp, _, clock = env
    args = {"endpoint": "income-statement", "symbol": "AAPL"}
    _get(svc, "statements", args)
    clock.advance(hours=23)
    assert _get(svc, "statements", args).state == "cached"
    clock.advance(hours=2)
    assert _get(svc, "statements", args).state == "live"
    assert len(fmp.calls) == 2
    clock.advance(days=2)
    fmp.fail = True
    stale = _get(svc, "statements", args)
    assert stale.state == "stale" and stale.response.status == 200
    assert stale.reason == "upstream-error"


def test_4xx_is_negative_cached_for_ten_minutes_and_never_persisted(env):
    svc, fmp, store, clock = env
    fmp.docs["/quote"] = UpstreamResponse(
        400, b"Query Error: Invalid or missing query parameter - symbol"
    )
    args = {"endpoint": "quote"}
    _get(svc, "quote", args)
    clock.advance(minutes=9)
    assert _get(svc, "quote", args).response.status == 400
    assert len(fmp.calls) == 1
    clock.advance(minutes=2)
    _get(svc, "quote", args)
    assert len(fmp.calls) == 2
    assert store.count("fmp_mcp_document") == 0


def test_ephemeral_expires_and_only_ephemeral_rows_are_prunable(env):
    svc, fmp, store, clock = env
    _get(svc, "quote", {"endpoint": "quote", "symbol": "AAPL"})
    _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    clock.advance(seconds=16)
    _get(svc, "quote", {"endpoint": "quote", "symbol": "AAPL"})
    assert len(fmp.calls) == 3
    clock.advance(days=30)
    report = store.prune_ephemeral()
    assert report[EPHEMERAL_TABLE] == 1
    svc._last_prune = clock()  # pylint: disable=protected-access
    _get(svc, "quote", {"endpoint": "quote", "symbol": "MSFT"})  # still fresh
    assert store.prune_ephemeral()[EPHEMERAL_TABLE] == 0
    assert store.count(EPHEMERAL_TABLE) == 1, "unexpired rows survive"
    assert store.count("fmp_mcp_document") == 1


def test_no_store_endpoint_is_never_stored(env):
    svc, fmp, store, _ = env
    args = {"endpoint": "custom-dcf-advanced", "symbol": "AAPL"}
    _get(svc, "discountedCashFlow", args)
    _get(svc, "discountedCashFlow", args)
    assert len(fmp.calls) == 2
    assert all(store.count(t) == 0 for t in (*PERSISTENT_TABLES, EPHEMERAL_TABLE))


def test_feed_listing_expires_but_items_are_kept(env):
    svc, fmp, store, clock = env
    items = [{"title": "a", "url": "https://x/a"}, {"title": "b", "url": "https://x/b"}]
    fmp.docs["/news/general-latest"] = UpstreamResponse(200, json.dumps(items).encode())
    _get(svc, "news", {"endpoint": "general-news"})
    clock.advance(days=60)
    store.prune_ephemeral()
    assert store.count("fmp_mcp_feed_item") == 2


# --- series -------------------------------------------------------------------


def test_series_rebuild_matches_recorded_hosted_text():
    """Stored rows re-assembled for the recorded range give the hosted text."""
    from openbb_fmp_cached_mcp.render import render_response  # pylint: disable=C0415

    rec = load_hosted(f"samples-{SNAPSHOT}/chart_historical-price-eod-light.json")
    body = gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"]))

    class Recorded(FakeFmp):
        async def fetch(self, path, params):
            self.calls.append((path, params))
            return UpstreamResponse(200, body)

    clock = Clock()
    clock.now = dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc)
    store = Store(SqliteDatabase(":memory:"), now=clock)
    store.create_tables()
    svc = StoreBackedUpstream(Recorded(), store, now=clock)
    _get(svc, "chart", rec["arguments"])
    out = _get(svc, "chart", rec["arguments"])
    assert out.state == "cached"
    text = render_response(
        tool="chart",
        arguments=rec["arguments"],
        path=rec["rest_path"],
        status=out.response.status,
        body=out.response.body,
    ).text
    assert text == rec["hosted_text"]


# --- concurrency and failure modes --------------------------------------------


def test_identical_concurrent_calls_share_one_upstream_request(env):
    svc, fmp, _, _ = env

    async def many():
        args = {"endpoint": "income-statement", "symbol": "MSFT"}
        return await asyncio.gather(
            *(svc.fetch_tool("statements", args) for _ in range(8))
        )

    asyncio.run(many())
    assert len(fmp.calls) == 1


def test_store_down_means_live_mode_with_a_warning(caplog):
    attempts = []

    class DownDb(SqliteDatabase):
        def query(self, sql, params=()):
            attempts.append(sql)
            raise StoreUnavailable("mysql down")

        def execute(self, sql, params=()):
            attempts.append(sql)
            raise StoreUnavailable("mysql down")

    clock = Clock()
    store = Store(DownDb(":memory:"), now=clock)
    fmp = FakeFmp()
    svc = StoreBackedUpstream(fmp, store, now=clock)
    with caplog.at_level(logging.WARNING, logger="openbb_fmp_cached_mcp"):
        out = _get(
            svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"}
        )
        _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    assert out.state == "live" and len(fmp.calls) == 2
    warnings = [r for r in caplog.records if "store unavailable" in r.getMessage()]
    assert len(warnings) == 1, "warn once, not per call"
    assert len(attempts) == 1, "the store is not retried inside the back-off window"
    clock.advance(seconds=61)
    _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    assert len(attempts) == 2, "retried after the back-off window"


def test_cache_keys_and_stored_queries_never_contain_the_key(env):
    svc, fmp, store, _ = env
    fmp.secret = "s" * 32
    _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    for table in (*PERSISTENT_TABLES, EPHEMERAL_TABLE):
        for row in store.dump(table):
            assert fmp.secret not in json.dumps(row, default=str)


def test_persistent_tables_are_not_prunable_in_fmp_cached():
    cache_schema = pytest.importorskip("openbb_fmp_cached.utils.cache_schema")
    assert EPHEMERAL_TABLE in cache_schema.EXPIRABLE_CACHE_TABLES
    assert not set(PERSISTENT_TABLES) & set(cache_schema.EXPIRABLE_CACHE_TABLES)
    rule = next(
        r for r in cache_schema.CACHE_EXPIRY_RULES if r.table == EPHEMERAL_TABLE
    )
    assert rule.timestamp_column == "expires_at" and rule.ttl_seconds == 0


def test_mysql_ddl_matches_the_fmp_cached_schema_registry():
    cache_schema = pytest.importorskip("openbb_fmp_cached.utils.cache_schema")
    from openbb_fmp_cached_mcp import store as store_mod  # pylint: disable=C0415

    mysql = store_mod._TYPES["mysql"]  # pylint: disable=protected-access
    for table, cols in store_mod._DDL.items():  # pylint: disable=protected-access
        assert cache_schema.FMP_MCP_TABLE_COLUMNS[table] == cols.format(**mysql), table
        assert table not in cache_schema.FLATTENED_TABLES  # not entity tables
        assert table in cache_schema.FMP_MCP_TABLE_COLUMNS


def test_server_reports_store_provenance_in_meta_and_identical_content(env):
    """Through the MCP protocol: second call is cached, content unchanged."""
    from mcp.shared.memory import (  # pylint: disable=import-outside-toplevel
        create_connected_server_and_client_session,
    )

    from openbb_fmp_cached_mcp.server import build_server  # pylint: disable=C0415

    svc, fmp, _, _ = env
    args = _range("2026-11-02", "2026-11-13")

    async def go():
        async with create_connected_server_and_client_session(build_server(svc)) as c:
            return await c.call_tool("chart", args), await c.call_tool("chart", args)

    first, second = asyncio.run(go())
    assert first.content[0].text == second.content[0].text
    assert first.meta["openbb/provenance"]["state"] == "live"
    prov = second.meta["openbb/provenance"]
    assert prov["state"] == "cached" and prov["source"] == "fmp_cached"
    assert len(fmp.calls) == 1
    assert set(prov) <= {"state", "source", "asOf", "reason"}


def test_provenance_states_are_datastate_values():
    data_state = {
        "live",
        "cached",
        "demo",
        "stale",
        "partial",
        "unavailable",
        "forbidden",
    }
    from openbb_fmp_cached_mcp import service  # pylint: disable=C0415

    src = open(service.__file__, encoding="utf-8").read()  # noqa: SIM115
    import re  # pylint: disable=import-outside-toplevel

    used = set(
        re.findall(r'"(live|cached|stale|unavailable|partial|demo|forbidden)"', src)
    )
    assert used and used <= data_state


def test_empty_answer_is_never_stored_as_immutable(env):
    """A not-found today (e.g. no filing yet) may exist tomorrow."""
    svc, fmp, _, clock = env
    # A revisable name lookup (senate-trading-by-name became a feed).
    fmp.docs["/crowdfunding-offerings-search"] = UpstreamResponse(200, b"[]")
    args = {"endpoint": "crowdfunding-search", "name": "Nobody"}
    _get(svc, "Fundraisers", args)
    clock.advance(hours=12)
    assert _get(svc, "Fundraisers", args).state == "cached"
    clock.advance(hours=13)
    _get(svc, "Fundraisers", args)
    assert len(fmp.calls) == 2


# --- PR-B review findings (code + security) --------------------------------------


def test_negative_cache_keys_fit_the_char64_column(env):
    svc, fmp, store, _ = env
    fmp.docs["/quote"] = UpstreamResponse(400, b"Query Error")
    _get(svc, "quote", {"endpoint": "quote"})
    keys = [r["cache_key"] for r in store.dump(EPHEMERAL_TABLE)]
    assert keys and all(len(k) == 64 for k in keys)


def test_paged_series_endpoints_use_the_document_path():
    args = {
        "endpoint": "historical-grades",
        "symbol": "AAPL",
        "limit": 5,
        "from_date": "2026-01-01",
        "to_date": "2026-11-01",
    }
    pol = resolve_policy("analyst", args, today=TODAY)
    assert pol.mode == "document"


def test_cancelled_owner_does_not_cancel_waiters(env):
    svc, fmp, _, _ = env
    args = {"endpoint": "income-statement", "symbol": "IBM"}

    async def scenario():
        fmp.gate = asyncio.Event()
        owner = asyncio.create_task(svc.fetch_tool("statements", args))
        await asyncio.sleep(0)
        waiter = asyncio.create_task(svc.fetch_tool("statements", args))
        await asyncio.sleep(0)
        owner.cancel()
        await asyncio.sleep(0)
        fmp.gate.set()
        return await asyncio.wait_for(waiter, 5)

    result = asyncio.run(scenario())
    assert result.response.status == 200


def test_write_failure_returns_the_fetched_answer_without_refetch(caplog):
    from openbb_fmp_cached_mcp.store import StoreDataError  # pylint: disable=C0415

    class BadWrites(SqliteDatabase):
        def execute(self, sql, params=()):
            if sql.lstrip().upper().startswith("INSERT"):
                raise StoreDataError("DataError")
            return super().execute(sql, params)

    clock = Clock()
    store = Store(BadWrites(":memory:"), now=clock)
    store.create_tables()
    fmp = FakeFmp()
    svc = StoreBackedUpstream(fmp, store, now=clock)
    out = _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    assert out.response.status == 200 and len(fmp.calls) == 1
    _get(svc, "statements", {"endpoint": "income-statement", "symbol": "MSFT"})
    assert len(fmp.calls) == 2
    assert not any("store unavailable" in r.getMessage() for r in caplog.records)


def test_empty_answers_are_ephemeral_not_persistent(env):
    svc, fmp, store, _ = env
    fmp.docs["/senate-trades-by-name"] = UpstreamResponse(200, b"[]")
    _get(svc, "senate", {"endpoint": "senate-trading-by-name", "name": "Zz"})
    assert store.count("fmp_mcp_document") == 0
    assert store.count(EPHEMERAL_TABLE) == 1


def test_oversized_bodies_are_served_but_not_stored(env, monkeypatch):
    from openbb_fmp_cached_mcp import service  # pylint: disable=C0415

    svc, _, store, _ = env
    monkeypatch.setattr(service, "MAX_STORED_BODY_BYTES", 10)
    out = _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    assert out.response.status == 200
    assert store.count("fmp_mcp_document") == 0


def test_expired_ephemeral_rows_are_pruned_opportunistically(env):
    svc, _, store, clock = env
    _get(svc, "quote", {"endpoint": "quote", "symbol": "AAPL"})
    clock.advance(hours=2)
    _get(svc, "quote", {"endpoint": "quote", "symbol": "MSFT"})
    assert store.count(EPHEMERAL_TABLE) == 1, "the expired AAPL quote row was pruned"


def test_far_future_range_does_not_crash(env):
    svc, _, _, _ = env
    out = _get(svc, "chart", _range("2026-11-02", "9999-12-31"))
    assert out.response.status == 200


def test_mysql_errors_are_classified():
    from openbb_fmp_cached_mcp.store import (  # pylint: disable=C0415
        StoreDataError,
        classify_db_error,
    )

    class OperationalError(Exception):
        pass

    class DataError(Exception):
        pass

    assert isinstance(classify_db_error(OperationalError(2003, "x")), StoreUnavailable)
    assert isinstance(classify_db_error(DataError(1406, "too long")), StoreDataError)
    assert isinstance(
        classify_db_error(OperationalError(1366, "bad value")), StoreDataError
    )


def test_paged_series_with_range_params_use_the_document_path():
    args = {
        "endpoint": "historical-market-cap",
        "symbol": "AAPL",
        "limit": 5,
        "from_date": "2026-01-01",
        "to_date": "2026-11-01",
    }
    assert resolve_policy("company", args, today=TODAY).mode == "document"


def test_a_rejected_read_goes_live_without_marking_the_store_down():
    from openbb_fmp_cached_mcp.store import StoreDataError  # pylint: disable=C0415

    class BadReads(SqliteDatabase):
        def query(self, sql, params=()):
            raise StoreDataError("DataError")

    clock = Clock()
    store = Store(BadReads(":memory:"), now=clock)
    store.create_tables()
    fmp = FakeFmp()
    svc = StoreBackedUpstream(fmp, store, now=clock)
    out = _get(svc, "statements", {"endpoint": "income-statement", "symbol": "AAPL"})
    assert out.state == "live"
    assert svc._store_down_until is None  # pylint: disable=protected-access


# --- /code-review (high) findings on PR #1308 ------------------------------------


def test_constituent_histories_are_not_range_series():
    """FMP ignores from/to for these: the hosted answer is the whole history."""
    for ep in ("historical-sp-500", "historical-nasdaq", "historical-dow-jones"):
        args = {"endpoint": ep, "from_date": "2026-11-17", "to_date": "2026-11-20"}
        assert resolve_policy("indexes", args, today=TODAY).mode == "document", ep


def test_sqlite_errors_are_classified():
    from openbb_fmp_cached_mcp.store import StoreDataError  # pylint: disable=C0415

    db = SqliteDatabase(":memory:")
    with pytest.raises(StoreDataError):
        db.query("SELECT * FROM no_such_table")
    db._conn.close()  # pylint: disable=protected-access
    with pytest.raises(StoreUnavailable):
        db.query("SELECT 1")


def test_store_io_does_not_block_other_sessions():
    import time  # pylint: disable=import-outside-toplevel

    class SlowDb(SqliteDatabase):
        def query(self, sql, params=()):
            time.sleep(0.3)
            return super().query(sql, params)

    clock = Clock()
    store = Store(SlowDb(":memory:"), now=clock)
    store.create_tables()
    fmp = FakeFmp()
    svc = StoreBackedUpstream(fmp, store, now=clock)
    done: list[str] = []

    async def call(name, tool, args):
        await svc.fetch_tool(tool, args)
        done.append(name)

    async def scenario():
        await asyncio.gather(
            call(
                "store", "statements", {"endpoint": "income-statement", "symbol": "A"}
            ),
            call(
                "live",
                "discountedCashFlow",
                {"endpoint": "custom-dcf-advanced", "symbol": "B"},
            ),
        )

    asyncio.run(scenario())
    assert done[0] == "live", "a no-store call must not wait for store I/O"


def test_series_refusals_are_remembered_without_a_second_request(env):
    svc, fmp, _, _ = env
    fmp.docs["/historical-chart/1min"] = UpstreamResponse(
        402, b"Premium Query Parameter: x"
    )
    args = {
        "endpoint": "intraday-1-min",
        "symbol": "AAPL",
        "from_date": "2026-10-01",
        "to_date": "2026-10-31",
    }
    first = _get(svc, "chart", args)
    assert first.response.status == 402 and len(fmp.calls) == 1
    _get(svc, "chart", args)
    assert len(fmp.calls) == 1


def test_ranges_starting_at_date_min_do_not_crash(env):
    svc, _, _, _ = env
    out = _get(
        svc, "chart", _range("0001-01-01", "2026-11-24")
    )  # reaches the tail overlap
    assert out.response.status == 200


def test_an_empty_refresh_keeps_serving_the_stored_document(env):
    """A transient empty answer must not hide the last good copy (review #1308)."""
    svc, fmp, _, clock = env
    args = {"endpoint": "income-statement", "symbol": "AAPL"}
    good = _get(svc, "statements", args)
    clock.advance(days=2)
    fmp.docs["/income-statement"] = UpstreamResponse(200, b"[]")
    first = _get(svc, "statements", args)
    again = _get(svc, "statements", args)
    for out in (first, again):
        assert out.response.body == good.response.body
        assert out.state == "stale" and out.reason == "upstream-empty"
    assert len(fmp.calls) == 2, "the empty answer is remembered for a day, not re-asked"


def test_an_empty_answer_without_a_stored_copy_is_kept_ephemeral(env):
    svc, fmp, store, _ = env
    fmp.docs["/income-statement"] = UpstreamResponse(200, b"[]")
    args = {"endpoint": "income-statement", "symbol": "NOPE"}
    assert _get(svc, "statements", args).response.body == b"[]"
    assert _get(svc, "statements", args).state == "cached"
    assert len(fmp.calls) == 1 and store.count("fmp_mcp_document") == 0


# --- /code-review (high) round 2 on PR #1308 -------------------------------------


def test_only_400_402_404_are_remembered_as_refusals(env):
    svc, fmp, _, clock = env
    args = {"endpoint": "income-statement", "symbol": "AAPL"}
    first = _get(svc, "statements", args)
    clock.advance(days=2)
    fmp.docs["/income-statement"] = UpstreamResponse(522, b"cloudflare")
    stale = _get(svc, "statements", args)
    assert stale.state == "stale" and stale.response.body == first.response.body
    del fmp.docs["/income-statement"]
    fresh = _get(svc, "statements", args)
    assert fresh.state == "live", "a 522 is not remembered for ten minutes"


def test_mysql_tables_are_created_with_the_schema_charset():
    seen = []

    class FakeMySql:
        dialect = "mysql"

        def execute(self, sql, params=()):
            seen.append(sql)
            return 0

        def query(self, sql, params=()):
            return []

    Store(FakeMySql()).create_tables()
    creates = [s for s in seen if s.startswith("CREATE TABLE")]
    assert creates and all(
        "CHARSET=utf8mb4" in s and "ENGINE=InnoDB" in s for s in creates
    )


# --- Series stored per exact request (PR #1308 option 1; gap-fill is #1310) -------


def test_a_series_range_is_stored_per_request(env):
    svc, fmp, store, _ = env
    first = _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    again = _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    assert len(fmp.calls) == 1 and again.state == "cached"
    assert again.response.body == first.response.body
    _get(svc, "chart", _range("2026-11-04", "2026-11-10"))
    assert len(fmp.calls) == 2, "another range is another request"
    assert store.count("fmp_mcp_document") == 2


def test_an_open_range_refreshes_hourly_and_keeps_the_last_good_copy(env):
    svc, fmp, _, clock = env
    args = _range("2026-11-16", "2026-11-24")
    _get(svc, "chart", args)
    clock.advance(minutes=50)
    assert _get(svc, "chart", args).state == "cached"
    clock.advance(minutes=20)
    fmp.fail = True
    stale = _get(svc, "chart", args)
    assert stale.state == "stale" and stale.response.status == 200


def test_a_past_range_is_kept_and_refreshed_daily(env):
    """Split-adjusted history can change upstream, so past ranges are revisable."""
    svc, fmp, _, clock = env
    args = _range("2026-10-01", "2026-10-31")
    _get(svc, "chart", args)
    clock.advance(hours=23)
    assert _get(svc, "chart", args).state == "cached"
    clock.advance(hours=2)
    fmp.price_shift = -50.0  # a split re-based the history
    out = _get(svc, "chart", args)
    assert out.state == "live"
    assert json.loads(out.response.body)[-1]["price"] == 100.0 - 50.0 + 1


def test_no_series_tables_are_created():
    store = Store(SqliteDatabase(":memory:"), now=Clock())
    store.create_tables()
    names = {
        r["name"]
        for r in store.db.query("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert names == {"fmp_mcp_document", "fmp_mcp_feed_item", "fmp_mcp_ephemeral"}


def test_mysql_upsert_uses_the_row_alias_form():
    seen = []

    class FakeMySql:
        dialect = "mysql"

        def execute(self, sql, params=()):
            seen.append(sql)
            return 1

        def executemany(self, sql, rows):
            seen.append(sql)
            return len(rows)

        def query(self, sql, params=()):
            return []

    Store(FakeMySql()).put_response(
        "fmp_mcp_document",
        "k" * 64,
        tool="t",
        endpoint="e",
        path="/x",
        params={},
        retention="revisable",
        status=200,
        body=b"[]",
        fresh_s=60,
    )
    sql = next(q for q in seen if q.lstrip().upper().startswith("INSERT"))
    assert " AS new ON DUPLICATE KEY UPDATE " in sql and "VALUES(" not in sql


def test_first_call_upstream_error_renders_the_hosted_text(env):
    """No stored copy + FMP 429: the hosted 'Bad request ...' text, not an exception."""
    from openbb_fmp_cached_mcp.server import (
        Scrubber,
        call_tool,
    )  # pylint: disable=C0415

    svc, fmp, _, _ = env
    fmp.docs["/historical-price-eod/full"] = UpstreamResponse(429, b"Limit Reach")
    args = {
        "endpoint": "historical-price-eod-full",
        "symbol": "AAPL",
        "from_date": "2026-11-02",
        "to_date": "2026-11-06",
    }
    result = asyncio.run(call_tool(svc, Scrubber(), "chart", args))
    assert result.isError is True
    assert result.content[0].text == (
        'Bad request for tool "chart" (endpoint /historical-price-eod/full): Limit Reach'
    )


def test_registry_creates_unprefixed_mcp_tables_in_test_mode(monkeypatch):
    cache_schema = pytest.importorskip("openbb_fmp_cached.utils.cache_schema")
    seen = []
    monkeypatch.setenv("FMP_CACHE_TEST_MODE", "true")
    monkeypatch.setattr(
        cache_schema, "execute_query", lambda sql, p=(): seen.append(sql)
    )
    for name in ("fmp_mcp_document", "fmp_mcp_feed_item", "fmp_mcp_ephemeral"):
        cache_schema.create_fmp_mcp_tables(only=[name])
    assert all("test_fmp_mcp" not in s for s in seen) and len(seen) == 3


# --- /code-review (high) round 4 on PR #1308 ---------------------------------------


def test_a_corrupt_stored_row_degrades_to_a_live_fetch(env):
    svc, fmp, store, _ = env
    args = {"endpoint": "as-reported-income-statements", "symbol": "AAPL"}
    _get(svc, "statements", args)
    store.db.execute("UPDATE fmp_mcp_document SET body = %s", (b"not gzip",))
    out = _get(svc, "statements", args)
    assert out.state == "live" and out.response.status == 200
    assert len(fmp.calls) == 2
    assert _get(svc, "statements", args).state == "cached", "the bad row was repaired"


# --- /code-review (high) round 5 on PR #1308 ---------------------------------------


def test_an_empty_answer_is_held_no_longer_than_the_request_refresh(env):
    """Intraday before the open: empty now, data a minute later."""
    svc, fmp, _, clock = env
    fmp.docs["/historical-chart/1min"] = UpstreamResponse(200, b"[]")
    args = {
        "endpoint": "intraday-1-min",
        "symbol": "AAPL",
        "from_date": "2026-11-24",
        "to_date": "2026-11-24",
    }
    _get(svc, "chart", args)
    clock.advance(seconds=61)
    fmp.docs["/historical-chart/1min"] = UpstreamResponse(
        200, b'[{"date": "2026-11-24 09:30:00"}]'
    )
    out = _get(svc, "chart", args)
    assert out.state == "live" and out.response.body != b"[]"


def test_a_refusal_while_a_copy_is_stored_serves_the_copy_as_stale(env):
    svc, fmp, _, clock = env
    args = {"endpoint": "profile-symbol", "symbol": "AAPL"}
    good = _get(svc, "company", args)
    clock.advance(days=2)
    fmp.docs["/profile"] = UpstreamResponse(402, b"Premium Query Parameter: x")
    first = _get(svc, "company", args)
    again = _get(svc, "company", args)
    for out in (first, again):
        assert out.state == "stale" and out.response.body == good.response.body
        assert out.reason == "upstream-402"
    assert len(fmp.calls) == 2, "the refusal is remembered; FMP is not re-asked"


# --- /code-review (high) round 6 on PR #1308 ---------------------------------------


@pytest.mark.parametrize(
    "tool, args, refresh",
    [
        ("calendar", {"endpoint": "dividends-company", "symbol": "AAPL"}, 86400),
        (
            "statements",
            {"endpoint": "financial-reports-dates", "symbol": "AAPL"},
            86400,
        ),
        (
            "secFilings",
            {
                "endpoint": "search-by-symbol",
                "symbol": "AAPL",
                "from_date": "2026-11-01",
                "to_date": "2027-01-01",
            },
            86400,
        ),
        (
            "secFilings",
            {
                "endpoint": "search-by-symbol",
                "symbol": "AAPL",
                "from_date": "2025-01-01",
                "to_date": "2025-03-01",
            },
            None,
        ),
        (
            "statements",
            {
                "endpoint": "financial-reports-form-10-k-json",
                "symbol": "AAPL",
                "year": 2024,
                "period": "FY",
            },
            None,
        ),
    ],
)
def test_growing_lists_refresh_and_only_fixed_reports_are_immutable(
    tool, args, refresh
):
    pol = resolve_policy(tool, args, today=TODAY)
    assert (pol.mode, pol.refresh_s) == ("document", refresh)


# Final review: symbol news and congressional-trade searches are feeds. New
# items appear all day, so the listing lives 10 minutes and every item is kept.
_FEED_SEARCHES = [
    ("senate", {"endpoint": "senate-trading", "symbol": "AAPL"}),
    ("senate", {"endpoint": "senate-trading-by-name", "name": "Jerry"}),
    ("senate", {"endpoint": "house-trading", "symbol": "AAPL"}),
    ("senate", {"endpoint": "house-trading-by-name", "name": "Nancy"}),
    ("news", {"endpoint": "search-stock-news", "symbols": ["AAPL"]}),
    ("news", {"endpoint": "search-press-releases", "symbols": ["AAPL"]}),
    ("news", {"endpoint": "search-crypto-news", "symbols": ["BTCUSD"]}),
    ("news", {"endpoint": "search-forex-news", "symbols": ["EURUSD"]}),
]


@pytest.mark.parametrize("tool, args", _FEED_SEARCHES)
def test_symbol_news_and_trade_searches_are_feeds(tool, args):
    pol = resolve_policy(tool, args, today=TODAY)
    assert (pol.mode, pol.refresh_s, pol.feed) == ("ephemeral", 600, True)


def test_past_dated_news_search_is_immutable_and_keeps_items():
    pol = resolve_policy(
        "news",
        {
            "endpoint": "search-stock-news",
            "symbols": ["AAPL"],
            "from_date": "2025-01-01",
            "to_date": "2025-01-31",
        },
        today=TODAY,
    )
    assert (pol.mode, pol.refresh_s, pol.feed) == ("document", None, True)


def test_symbol_trade_search_listing_refreshes_and_items_are_kept(env):
    svc, fmp, store, clock = env
    rows = [{"symbol": "AAPL", "amount": "$1,001 - $15,000", "n": i} for i in (1, 2)]
    fmp.docs["/senate-trades"] = UpstreamResponse(200, json.dumps(rows).encode())
    args = {"endpoint": "senate-trading", "symbol": "AAPL"}
    _get(svc, "senate", args)
    clock.advance(seconds=300)
    _get(svc, "senate", args)
    assert len(fmp.calls) == 1, "fresh within the 10-minute listing TTL"
    clock.advance(seconds=400)
    _get(svc, "senate", args)
    assert len(fmp.calls) == 2, "listing refreshed after 10 minutes, not 24 h"
    clock.advance(days=60)
    store.prune_ephemeral()
    assert store.count("fmp_mcp_feed_item") == 2


def test_feed_rows_sharing_a_link_are_all_kept(env):
    """Several transactions share one disclosure link (recorded senate-latest)."""
    _, _, store, _ = env
    rec = load_hosted(f"samples-{SNAPSHOT}/senate_senate-latest.json")
    rows = json.loads(gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"])))
    assert len({r.get("link") for r in rows}) < len(rows), "fixture must share links"
    store.put_feed_items("/senate-latest", rows)
    kept = store.dump("fmp_mcp_feed_item")
    assert len(kept) == len(rows)
    assert [json.loads(k["row_json"]) for k in kept] and all(
        list(json.loads(k["row_json"])) == list(rows[0]) for k in kept[:1]
    ), "stored rows keep FMP key order"


def test_past_date_feed_calls_still_keep_their_items(env):
    pol = resolve_policy(
        "secFilings",
        {"endpoint": "8k-latest", "from_date": "2024-01-01", "to_date": "2024-03-01"},
        today=TODAY,
    )
    assert pol.mode == "document" and pol.refresh_s is None and pol.feed


# --- Final review: least-privilege MySQL user with pre-created tables --------


class _NoCreateDb(SqliteDatabase):
    """Reachable DB whose user lacks CREATE: MySQL checks the privilege before
    ``IF NOT EXISTS`` and answers 1142 even when the table already exists."""

    def __init__(self, path, precreate=()):
        super().__init__(path)
        for table in precreate:
            super().execute(f"CREATE TABLE {table} (x INTEGER)")
        self.creates = 0

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith("CREATE"):
            self.creates += 1
            raise StoreDataError("OperationalError 1142")
        return super().execute(sql, params)


def test_create_denied_but_tables_exist_accepts_the_store():
    db = _NoCreateDb(":memory:", precreate=ALL_TABLES)
    Store(db).create_tables()  # no raise
    assert db.creates >= 1, "CREATE was attempted and refused"


@pytest.mark.parametrize("precreate", [(), PERSISTENT_TABLES])
def test_create_denied_and_tables_missing_reraises_the_original_error(precreate):
    db = _NoCreateDb(":memory:", precreate=precreate)
    with pytest.raises(StoreDataError, match="1142"):
        Store(db).create_tables()


# --- /code-review (high) round 8 on PR #1308 ---------------------------------------

TEN_K_ARGS = {
    "endpoint": "financial-reports-form-10-k-json",
    "symbol": "AAPL",
    "year": 2024,
    "period": "FY",
}


@pytest.mark.parametrize(
    "body",
    [
        b'{"Error Message":"Limit Reach . Please upgrade your plan"}',
        b"<html>maintenance</html>",
    ],
    ids=["fmp-error-object", "html-page"],
)
def test_error_body_under_200_is_never_stored_as_a_document(env, body):
    svc, fmp, store, clock = env
    fmp.docs["/financial-reports-json"] = UpstreamResponse(200, body)
    first = _get(svc, "statements", TEN_K_ARGS)
    assert first.response.body == body, "rendered as FMP sent it"
    assert store.dump("fmp_mcp_document") == []
    clock.advance(hours=1)
    _get(svc, "statements", TEN_K_ARGS)
    assert len(fmp.calls) == 2, "an error body is retried, not kept forever"


def test_error_body_under_200_does_not_replace_a_stored_document(env):
    svc, fmp, store, clock = env
    args = {"endpoint": "financial-reports-dates", "symbol": "AAPL"}
    good = b'[{"symbol":"AAPL","fiscalYear":2024}]'
    fmp.docs["/financial-reports-dates"] = UpstreamResponse(200, good)
    _get(svc, "statements", args)
    clock.advance(days=2)
    fmp.docs["/financial-reports-dates"] = UpstreamResponse(
        200, b'{"Error Message":"x"}'
    )
    again = _get(svc, "statements", args)
    assert (again.state, again.response.body) == ("stale", good)
    assert [r["body"] for r in store.dump("fmp_mcp_document")] != [], "kept"
