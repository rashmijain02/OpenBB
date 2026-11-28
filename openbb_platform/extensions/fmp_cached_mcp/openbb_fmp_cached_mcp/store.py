"""Persistent raw-JSON store for the parity server (#1300, plan §4.3).

Tables (all raw FMP JSON, so hosted payloads can be rebuilt exactly):

``fmp_mcp_document``         one raw response per canonical request; kept forever
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
import logging
import sqlite3
import threading
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DOCUMENT_TABLE = "fmp_mcp_document"
FEED_ITEM_TABLE = "fmp_mcp_feed_item"
EPHEMERAL_TABLE = "fmp_mcp_ephemeral"
#: Kept forever; never in ``cache_prune``'s allowlist (asserted by tests).
PERSISTENT_TABLES = (DOCUMENT_TABLE, FEED_ITEM_TABLE)
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


_SQLITE_UNREACHABLE = ("locked", "busy", "unable to open", "disk i/o", "readonly")


def _sqlite_error(exc: sqlite3.Error) -> RuntimeError:
    """Map a sqlite3 error to ``StoreUnavailable`` (outage) or ``StoreDataError``."""
    text = str(exc).lower()
    if isinstance(exc, sqlite3.ProgrammingError) or any(
        word in text for word in _SQLITE_UNREACHABLE
    ):
        return StoreUnavailable(type(exc).__name__)
    return StoreDataError(type(exc).__name__)


class SqliteDatabase:
    """SQLite backend (tests and local development)."""

    dialect = "sqlite"

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def _exec(self, sql: str, params: Any, many: bool) -> sqlite3.Cursor:
        """Run one statement without committing (caller holds the lock)."""
        sql = sql.replace("%s", "?")
        if many:
            return self._conn.executemany(sql, params)
        return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return rows as dicts."""
        try:
            with self._lock:
                return [dict(r) for r in self._exec(sql, params, False).fetchall()]
        except sqlite3.Error as exc:
            raise _sqlite_error(exc) from None

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a statement and return the affected row count."""
        return self._commit([(sql, params, False)])

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """Run one statement for many parameter rows in one transaction."""
        return self._commit([(sql, rows, True)])

    def _commit(self, steps: list[tuple[str, Any, bool]]) -> int:
        with self._lock:
            try:
                count = 0
                for sql, params, many in steps:
                    count = self._exec(sql, params, many).rowcount
                self._conn.commit()
                return count
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise _sqlite_error(exc) from None
            except Exception:
                self._conn.rollback()
                raise


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
    """Typed operations over the three store tables."""

    def __init__(
        self, db: Database, *, now: Callable[[], dt.datetime] | None = None
    ) -> None:
        self.db = db
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    # -- schema ---------------------------------------------------------------

    def create_tables(self) -> None:
        """Create the store tables if they do not exist (idempotent)."""
        types = _TYPES[self.db.dialect]
        # Same table options as the fmp_cached schema registry, whichever runs first.
        options = (
            " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
            if self.db.dialect == "mysql"
            else ""
        )
        try:
            for table, cols in _DDL.items():
                self.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} "
                    f"({cols.format(**types)}){options}"
                )
        except StoreDataError:
            # MySQL checks the CREATE privilege before IF NOT EXISTS (1142), so a
            # least-privilege user fails here even when an admin pre-created the
            # tables. Accept the store only if every table is already there.
            if not self._tables_exist():
                raise

    def _tables_exist(self) -> bool:
        """Return True when every store table answers a zero-row SELECT."""
        for table in _DDL:
            try:
                self.db.query(f"SELECT 1 FROM {table} LIMIT 0")  # noqa: S608
            except StoreDataError:
                return False
        return True

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
        try:
            return StoredResponse(
                int(row["status"]),
                gzip.decompress(bytes(row["body"])),
                _parse(row["fetched_at"]),
                None if until is None else _parse(until),
            )
        except (OSError, EOFError, ValueError, TypeError, zlib.error) as exc:
            # A row that cannot be decoded is treated as missing: the caller
            # fetches again and the upsert repairs it.
            logger.warning(
                "unreadable row in %s ignored (%s)", table, type(exc).__name__
            )
            return None

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

    # -- feeds ----------------------------------------------------------------

    def put_feed_items(self, family: str, rows: list[dict[str, Any]]) -> None:
        """Keep every feed item (news article, filing, trade) for good."""
        now = _fmt(self.now())
        items = {}
        for row in rows:
            # One link can cover several transactions (a disclosure PDF, a
            # Form 4), so the id is the whole row, not the link.
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
            item_id = hashlib.sha256(canonical.encode()).hexdigest()
            items[item_id] = {
                "family": family,
                "item_id": item_id,
                "row_json": json.dumps(row, ensure_ascii=False),  # FMP key order
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
