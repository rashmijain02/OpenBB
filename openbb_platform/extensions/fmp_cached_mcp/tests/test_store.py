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

import pytest

from openbb_fmp_cached_mcp.policy import resolve_policy
from openbb_fmp_cached_mcp.service import StoreBackedUpstream
from openbb_fmp_cached_mcp.store import (
    EPHEMERAL_TABLE,
    PERSISTENT_TABLES,
    SqliteDatabase,
    Store,
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

    async def fetch(self, path, params):
        self.calls.append((path, dict(params)))
        await asyncio.sleep(0)  # a real request yields to the event loop
        if self.fail:
            raise ConnectionError("down")
        if path in self.docs:
            return self.docs[path]
        if path.startswith("/historical-price-eod"):
            start = dt.date.fromisoformat(params.get("from", "2026-01-01"))
            end = dt.date.fromisoformat(params.get("to", TODAY.isoformat()))
            end = min(end, TODAY)
            rows = _daily_rows(start, end, params["symbol"], 100.0 + self.price_shift)
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
            {"endpoint": "as-reported-income-statements", "symbol": "AAPL"},
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
        ("chart", _range("2026-11-02", "2026-11-06"), "series", 3600),
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
    args = {"endpoint": "as-reported-income-statements", "symbol": "AAPL"}
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
    _get(svc, "quote", {"endpoint": "quote", "symbol": "MSFT"})  # still fresh
    report = store.prune_ephemeral()
    assert report[EPHEMERAL_TABLE] == 1
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


def test_closed_range_is_served_from_store_forever(env):
    svc, fmp, _, clock = env
    first = _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    clock.advance(days=365)
    again = _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    assert len(fmp.calls) == 1
    assert again.state == "cached"
    assert json.loads(again.response.body) == json.loads(first.response.body)


def test_sub_range_is_served_without_a_call_and_matches_fmp(env):
    svc, fmp, _, _ = env
    _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    sub = _get(svc, "chart", _range("2026-11-04", "2026-11-10"))
    assert len(fmp.calls) == 1
    expected = _daily_rows(dt.date(2026, 11, 4), dt.date(2026, 11, 10))
    assert json.loads(sub.response.body) == expected


def test_only_the_gaps_are_fetched(env):
    svc, fmp, _, _ = env
    _get(svc, "chart", _range("2026-11-05", "2026-11-10"))
    _get(svc, "chart", _range("2026-11-02", "2026-11-13"))
    assert [c[1] for c in fmp.calls[1:]] == [
        {"symbol": "AAPL", "from": "2026-11-02", "to": "2026-11-04"},
        {"symbol": "AAPL", "from": "2026-11-11", "to": "2026-11-13"},
    ]


def test_open_tail_is_refetched_until_final(env):
    svc, fmp, _, clock = env
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    clock.advance(minutes=30)
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    assert len(fmp.calls) == 1, "tail TTL not yet passed"
    clock.advance(hours=2)
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    assert len(fmp.calls) == 2
    tail = fmp.calls[1][1]
    assert tail["to"] == "2026-11-24" and tail["from"] < "2026-11-22"
    clock.advance(days=10)  # the whole range is now final
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    assert len(fmp.calls) == 3


def test_price_adjustment_in_overlap_invalidates_the_series(env):
    svc, fmp, _, clock = env
    _get(svc, "chart", _range("2026-10-01", "2026-11-24"))
    clock.advance(days=1, hours=2)
    fmp.price_shift = -50.0  # e.g. a split re-based all history
    out = _get(svc, "chart", _range("2026-10-01", "2026-11-25"))
    rows = json.loads(out.response.body)
    assert rows[-1]["date"] == "2026-10-01"
    assert rows[-1]["price"] == 100.0 - 50.0 + 1, "old rows must be re-fetched"


def test_series_upstream_failure_serves_stored_rows_as_stale(env):
    svc, fmp, _, clock = env
    _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    clock.advance(hours=3)
    fmp.fail = True
    out = _get(svc, "chart", _range("2026-11-16", "2026-11-24"))
    assert out.state == "stale" and out.response.status == 200


def test_series_without_date_rows_falls_back_to_document(env):
    svc, fmp, store, _ = env
    fmp.docs["/historical-price-eod/light"] = UpstreamResponse(200, b'[{"x": 1}]')
    out = _get(svc, "chart", _range("2026-11-02", "2026-11-06"))
    assert out.response.body == b'[{"x": 1}]'
    assert store.count("fmp_mcp_series_row") == 0


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
        assert table in cache_schema.FLATTENED_TABLES


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
    fmp.docs["/senate-trades-by-name"] = UpstreamResponse(200, b"[]")
    args = {"endpoint": "senate-trading-by-name", "name": "Nobody"}
    _get(svc, "senate", args)
    clock.advance(hours=12)
    assert _get(svc, "senate", args).state == "cached"
    clock.advance(hours=13)
    _get(svc, "senate", args)
    assert len(fmp.calls) == 2
