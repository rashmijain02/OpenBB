"""Persistent raw-JSON store for the parity server (#1300, plan §4.3).

Tables (all raw FMP JSON, so hosted payloads can be rebuilt exactly):

``fmp_mcp_document``         one raw response per canonical request; kept forever
``fmp_mcp_series_row``       one raw FMP row per (path, series key, timestamp); kept forever
``fmp_mcp_series_coverage``  date ranges already fetched (``final``) plus the open ``tail``
``fmp_mcp_feed_item``        news / filings / trades items by id; kept forever
``fmp_mcp_ephemeral``        short-lived answers (quotes, snapshots, feed listings,
                             remembered 4xx); the **only** prunable table

Two backends share the SQL: ``MySqlDatabase`` (the ``fmp_cached`` connection
pool) and ``SqliteDatabase`` (tests and local development).
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

DOCUMENT_TABLE = "fmp_mcp_document"
SERIES_ROW_TABLE = "fmp_mcp_series_row"
SERIES_COVERAGE_TABLE = "fmp_mcp_series_coverage"
FEED_ITEM_TABLE = "fmp_mcp_feed_item"
EPHEMERAL_TABLE = "fmp_mcp_ephemeral"
#: Kept forever; never in ``cache_prune``'s allowlist (asserted by tests).
PERSISTENT_TABLES = (
    DOCUMENT_TABLE,
    SERIES_ROW_TABLE,
    SERIES_COVERAGE_TABLE,
    FEED_ITEM_TABLE,
)
ALL_TABLES = (*PERSISTENT_TABLES, EPHEMERAL_TABLE)


class StoreUnavailable(RuntimeError):
    """The database cannot be reached; callers fall back to live mode."""


class StoreDataError(RuntimeError):
    """The database rejected one statement (bad value, too long); not an outage."""


#: MySQL client/server error codes that mean "cannot reach the server".
_UNREACHABLE_CODES = {1040, 1045, 1049, 2002, 2003, 2005, 2006, 2013, 2055}


def classify_db_error(exc: BaseException) -> RuntimeError:
    """Map a driver error to ``StoreUnavailable`` (outage) or ``StoreDataError``."""
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    name = type(exc).__name__
    if code in _UNREACHABLE_CODES or name in ("InterfaceError", "ConnectionError"):
        return StoreUnavailable(f"{name} {code}" if code else name)
    if name == "OperationalError" and code is None:
        return StoreUnavailable(name)
    return StoreDataError(f"{name} {code}" if code else name)


class Database(Protocol):
    """Minimal DB-API seam. SQL uses ``%s`` placeholders."""

    dialect: str

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return rows as dicts."""

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a statement and return the affected row count."""

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """Run one statement for many parameter rows (one round trip / commit)."""


class SqliteDatabase:
    """SQLite backend (tests and local development)."""

    dialect = "sqlite"

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return rows as dicts."""
        with self._lock:
            cur = self._conn.execute(sql.replace("%s", "?"), params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a statement and return the affected row count."""
        with self._lock:
            cur = self._conn.execute(sql.replace("%s", "?"), params)
            self._conn.commit()
            return cur.rowcount

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """Run one statement for many parameter rows in one transaction."""
        with self._lock:
            cur = self._conn.executemany(sql.replace("%s", "?"), rows)
            self._conn.commit()
            return cur.rowcount


class MySqlDatabase:
    """MySQL backend over the ``fmp_cached`` provider's connection pool."""

    dialect = "mysql"

    def __init__(self) -> None:
        # pylint: disable-next=import-outside-toplevel
        from openbb_fmp_cached.utils import database

        self._db = database

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return rows as dicts."""
        try:
            return list(self._db.execute_query(sql, params) or [])
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            raise classify_db_error(exc) from None

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a statement and return the affected row count."""
        try:
            return int(self._db.execute_query(sql, params) or 0)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            raise classify_db_error(exc) from None

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """Run one statement for many parameter rows."""
        try:
            return int(self._db.execute_many(sql, rows) or 0)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            raise classify_db_error(exc) from None


_DDL = {
    DOCUMENT_TABLE: (
        "cache_key CHAR(64) NOT NULL PRIMARY KEY, tool VARCHAR(64) NOT NULL, "
        "endpoint VARCHAR(96) NOT NULL, path VARCHAR(128) NOT NULL, query_json {text} NOT NULL, "
        "retention VARCHAR(16) NOT NULL, status SMALLINT NOT NULL, body {blob} NOT NULL, "
        "fetched_at {ts} NOT NULL, refresh_after {ts} NULL"
    ),
    EPHEMERAL_TABLE: (
        "cache_key CHAR(64) NOT NULL PRIMARY KEY, tool VARCHAR(64) NOT NULL, "
        "endpoint VARCHAR(96) NOT NULL, path VARCHAR(128) NOT NULL, query_json {text} NOT NULL, "
        "retention VARCHAR(16) NOT NULL, status SMALLINT NOT NULL, body {blob} NOT NULL, "
        "fetched_at {ts} NOT NULL, expires_at {ts} NOT NULL"
    ),
    SERIES_ROW_TABLE: (
        "family VARCHAR(128) NOT NULL, series_key CHAR(64) NOT NULL, ts VARCHAR(32) NOT NULL, "
        "row_json {text} NOT NULL, fetched_at {ts} NOT NULL, "
        "PRIMARY KEY (family, series_key, ts)"
    ),
    SERIES_COVERAGE_TABLE: (
        "family VARCHAR(128) NOT NULL, series_key CHAR(64) NOT NULL, kind VARCHAR(8) NOT NULL, "
        "range_from VARCHAR(10) NOT NULL, range_to VARCHAR(10) NOT NULL, fetched_at {ts} NOT NULL, "
        "PRIMARY KEY (family, series_key, kind, range_from)"
    ),
    FEED_ITEM_TABLE: (
        "family VARCHAR(128) NOT NULL, item_id CHAR(64) NOT NULL, row_json {text} NOT NULL, "
        "fetched_at {ts} NOT NULL, PRIMARY KEY (family, item_id)"
    ),
}
_TYPES = {
    "mysql": {"blob": "LONGBLOB", "text": "MEDIUMTEXT", "ts": "DATETIME"},
    "sqlite": {"blob": "BLOB", "text": "TEXT", "ts": "TEXT"},
}


def request_key(path: str, params: dict[str, str]) -> str:
    """sha256 of the path and the canonical (sorted) query; never includes the key."""
    canon = json.dumps([path, sorted(params.items())], separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def _fmt(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value
    return dt.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt.timezone.utc
    )


@dataclass(frozen=True)
class StoredResponse:
    """A stored raw response."""

    status: int
    body: bytes
    fetched_at: dt.datetime
    fresh_until: dt.datetime | None  # None = immutable


class Store:
    """Typed operations over the five store tables."""

    def __init__(
        self, db: Database, *, now: Callable[[], dt.datetime] | None = None
    ) -> None:
        self.db = db
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    # -- schema ---------------------------------------------------------------

    def create_tables(self) -> None:
        """Create the store tables if they do not exist (idempotent)."""
        types = _TYPES[self.db.dialect]
        for table, cols in _DDL.items():
            self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ({cols.format(**types)})"
            )

    def _upsert_sql(self, table: str, cols: list[str], keys: Iterable[str]) -> str:
        marks = ", ".join(["%s"] * len(cols))
        update = [c for c in cols if c not in set(keys)]
        if self.db.dialect == "mysql":
            # Row-alias form (MySQL 8.0.19+); VALUES() is deprecated since 8.0.20.
            tail = "AS new ON DUPLICATE KEY UPDATE " + ", ".join(
                f"{c}=new.{c}" for c in update
            )
        else:
            tail = f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET " + ", ".join(
                f"{c}=excluded.{c}" for c in update
            )
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks}) {tail}"  # noqa: S608

    def _upsert(self, table: str, row: dict[str, Any], keys: Iterable[str]) -> None:
        sql = self._upsert_sql(table, list(row), keys)
        self.db.execute(sql, tuple(row.values()))

    def _upsert_many(
        self, table: str, rows: list[dict[str, Any]], keys: Iterable[str]
    ) -> None:
        if not rows:
            return
        cols = list(rows[0])
        self.db.executemany(
            self._upsert_sql(table, cols, keys),
            [tuple(r[c] for c in cols) for r in rows],
        )

    # -- documents and ephemeral answers --------------------------------------

    def get_response(self, table: str, key: str) -> StoredResponse | None:
        """Return the stored response for ``key`` in ``table`` (fresh or not)."""
        limit_col = "expires_at" if table == EPHEMERAL_TABLE else "refresh_after"
        rows = self.db.query(
            f"SELECT status, body, fetched_at, {limit_col} AS until "  # noqa: S608
            f"FROM {table} WHERE cache_key = %s",
            (key,),
        )
        if not rows:
            return None
        row = rows[0]
        until = row["until"]
        return StoredResponse(
            int(row["status"]),
            gzip.decompress(bytes(row["body"])),
            _parse(row["fetched_at"]),
            None if until is None else _parse(until),
        )

    def put_response(  # pylint: disable=too-many-arguments
        self,
        table: str,
        key: str,
        *,
        tool: str,
        endpoint: str,
        path: str,
        params: dict[str, str],
        retention: str,
        status: int,
        body: bytes,
        fresh_s: int | None,
    ) -> None:
        """Store a raw response; ``fresh_s=None`` marks it immutable."""
        now = self.now()
        until = None if fresh_s is None else _fmt(now + dt.timedelta(seconds=fresh_s))
        if table == EPHEMERAL_TABLE and until is None:
            raise ValueError("ephemeral rows need a TTL")
        row = {
            "cache_key": key,
            "tool": tool,
            "endpoint": endpoint,
            "path": path,
            "query_json": json.dumps(sorted(params.items())),
            "retention": retention,
            "status": status,
            "body": gzip.compress(body, mtime=0),
            "fetched_at": _fmt(now),
            ("expires_at" if table == EPHEMERAL_TABLE else "refresh_after"): until,
        }
        self._upsert(table, row, ("cache_key",))

    # -- series ---------------------------------------------------------------

    def series_rows(
        self, family: str, skey: str, start: dt.date, end: dt.date
    ) -> list[tuple[str, str, dt.datetime]]:
        """Rows with ``start <= date <= end``, newest first: ``(ts, row_json, fetched_at)``."""
        rows = self.db.query(
            f"SELECT ts, row_json, fetched_at FROM {SERIES_ROW_TABLE} "  # noqa: S608
            "WHERE family = %s AND series_key = %s AND ts >= %s AND ts < %s ORDER BY ts DESC",
            (family, skey, start.isoformat(), (end + dt.timedelta(days=1)).isoformat()),
        )
        return [(r["ts"], r["row_json"], _parse(r["fetched_at"])) for r in rows]

    def put_series_rows(
        self, family: str, skey: str, rows: list[dict[str, Any]]
    ) -> None:
        """Upsert raw rows keyed by their ``date`` value (one batched statement)."""
        now = _fmt(self.now())
        self._upsert_many(
            SERIES_ROW_TABLE,
            [
                {
                    "family": family,
                    "series_key": skey,
                    "ts": str(row["date"]),
                    "row_json": json.dumps(row, ensure_ascii=False),
                    "fetched_at": now,
                }
                for row in rows
            ],
            ("family", "series_key", "ts"),
        )

    def replace_series_range(
        self,
        family: str,
        skey: str,
        start: dt.date,
        end: dt.date,
        rows: list[dict[str, Any]],
    ) -> None:
        """Make FMP's answer for ``[start, end]`` the stored rows for that range."""
        self.db.execute(
            f"DELETE FROM {SERIES_ROW_TABLE} "  # noqa: S608
            "WHERE family = %s AND series_key = %s AND ts >= %s AND ts < %s",
            (family, skey, start.isoformat(), (end + dt.timedelta(days=1)).isoformat()),
        )
        self.put_series_rows(family, skey, rows)

    def coverage(
        self, family: str, skey: str, kind: str
    ) -> list[tuple[dt.date, dt.date, dt.datetime]]:
        """Return fetched ranges of ``kind`` (``final`` or ``tail``)."""
        rows = self.db.query(
            f"SELECT range_from, range_to, fetched_at FROM {SERIES_COVERAGE_TABLE} "  # noqa: S608
            "WHERE family = %s AND series_key = %s AND kind = %s ORDER BY range_from",
            (family, skey, kind),
        )
        return [
            (
                dt.date.fromisoformat(r["range_from"]),
                dt.date.fromisoformat(r["range_to"]),
                _parse(r["fetched_at"]),
            )
            for r in rows
        ]

    def add_final_coverage(
        self, family: str, skey: str, start: dt.date, end: dt.date
    ) -> None:
        """Record ``[start, end]`` as fetched and final, merging overlapping ranges."""
        ranges = [(a, b) for a, b, _ in self.coverage(family, skey, "final")] + [
            (start, end)
        ]
        ranges.sort()
        merged: list[list[dt.date]] = []
        for a, b in ranges:
            if merged and a <= merged[-1][1] + dt.timedelta(days=1):
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.db.execute(
            f"DELETE FROM {SERIES_COVERAGE_TABLE} "  # noqa: S608
            "WHERE family = %s AND series_key = %s AND kind = 'final'",
            (family, skey),
        )
        now = _fmt(self.now())
        for a, b in merged:
            self.db.execute(
                f"INSERT INTO {SERIES_COVERAGE_TABLE} "  # noqa: S608
                "(family, series_key, kind, range_from, range_to, fetched_at) "
                "VALUES (%s, %s, 'final', %s, %s, %s)",
                (family, skey, a.isoformat(), b.isoformat(), now),
            )

    def set_tail(self, family: str, skey: str, start: dt.date, end: dt.date) -> None:
        """Record the open tail ``[start, end]`` as fetched now."""
        self.db.execute(
            f"DELETE FROM {SERIES_COVERAGE_TABLE} "  # noqa: S608
            "WHERE family = %s AND series_key = %s AND kind = 'tail'",
            (family, skey),
        )
        self.db.execute(
            f"INSERT INTO {SERIES_COVERAGE_TABLE} "  # noqa: S608
            "(family, series_key, kind, range_from, range_to, fetched_at) "
            "VALUES (%s, %s, 'tail', %s, %s, %s)",
            (family, skey, start.isoformat(), end.isoformat(), _fmt(self.now())),
        )

    def drop_series(self, family: str, skey: str) -> None:
        """Forget one series (rows and coverage), e.g. after a price re-basing."""
        for table in (SERIES_ROW_TABLE, SERIES_COVERAGE_TABLE):
            self.db.execute(
                f"DELETE FROM {table} WHERE family = %s AND series_key = %s",  # noqa: S608
                (family, skey),
            )

    # -- feeds ----------------------------------------------------------------

    def put_feed_items(self, family: str, rows: list[dict[str, Any]]) -> None:
        """Keep every feed item (news article, filing, trade) for good."""
        now = _fmt(self.now())
        items = {}
        for row in rows:
            ident = row.get("url") or row.get("link") or row.get("finalLink")
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True)
            item_id = hashlib.sha256(str(ident or raw).encode()).hexdigest()
            items[item_id] = {
                "family": family,
                "item_id": item_id,
                "row_json": raw,
                "fetched_at": now,
            }
        self._upsert_many(FEED_ITEM_TABLE, list(items.values()), ("family", "item_id"))

    # -- maintenance ----------------------------------------------------------

    def prune_ephemeral(self) -> dict[str, int]:
        """Delete expired ephemeral rows. Persistent tables are never touched."""
        deleted = self.db.execute(
            f"DELETE FROM {EPHEMERAL_TABLE} WHERE expires_at < %s",  # noqa: S608
            (_fmt(self.now()),),
        )
        return {EPHEMERAL_TABLE: int(deleted)}

    def count(self, table: str) -> int:
        """Row count (diagnostics and tests)."""
        if table not in ALL_TABLES:
            raise ValueError(table)
        sql = f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608  (allowlisted)
        return int(self.db.query(sql)[0]["n"])

    def dump(self, table: str) -> list[dict[str, Any]]:
        """All rows of a store table (tests only)."""
        if table not in ALL_TABLES:
            raise ValueError(table)
        return self.db.query(f"SELECT * FROM {table}")  # noqa: S608
