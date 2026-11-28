"""SQLite stand-in for the readiness read path (#1345-T01).

Portable DDL for ``equity_historical`` / ``market_holidays`` (shape of
``openbb_fmp_cached.utils.cache_schema`` and the out-of-band holiday table) plus
optional private tables, seeded with synthetic rows only. Real SQL aggregate and
NULL semantics run; the connection translates the two MySQL-only spellings the
allowlist uses (``%s`` -> ``?``, ``<=>`` -> ``IS``), answers the session
variables, and records every statement so tests can assert read-only behaviour.
Injected errors carry real pymysql error classes and MySQL error numbers.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import date

import pymysql

EQUITY_DDL = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    interval_type VARCHAR(10) DEFAULT '1d',
    adjustment_type VARCHAR(20) DEFAULT 'splits_only',
    is_filled BOOLEAN DEFAULT 0,
    is_valid BOOLEAN DEFAULT 1,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (symbol, date, interval_type, adjustment_type)
)
"""
HOLIDAY_DDL = """
CREATE TABLE market_holidays (
    holiday_date DATE NOT NULL,
    market VARCHAR(10) NOT NULL DEFAULT 'US',
    holiday_name VARCHAR(100),
    year INTEGER,
    PRIMARY KEY (holiday_date, market)
)
"""
PROFILE_DDL = """
CREATE TABLE equity_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(50),
    date DATE,
    currency VARCHAR(10),
    price REAL,
    market_cap INTEGER
)
"""
_WRITE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|DROP|CREATE|ALTER|TRUNCATE)\b", re.I
)


class _Cursor:
    def __init__(self, conn: SqliteConn):
        self.conn = conn
        self._rows: list[tuple] = []
        self.description: tuple | None = None

    def execute(self, sql: str, params: Iterable = ()) -> None:
        self.conn.sql.append(sql)
        params = tuple(params or ())
        for needle, code in self.conn.errors.items():
            if needle in sql:
                cls = (
                    pymysql.err.ProgrammingError
                    if code == 1146
                    else pymysql.err.OperationalError
                )
                raise cls(code, "synthetic")
        upper = sql.strip().upper()
        if upper.startswith(("SET ", "START TRANSACTION")):
            self._set([], ())
            return
        if "DATABASE() AS DB" in upper and "FROM" not in upper:
            self._set([(self.conn.database,)], ("db",))
            return
        if "@@LOWER_CASE_TABLE_NAMES" in upper:
            self._set([(self.conn.lctn,)], ("lctn",))
            return
        if "INFORMATION_SCHEMA.TABLES" in upper:
            names = self.conn.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            rows = [(n,) for (n,) in names if n not in self.conn.hidden]
            self._set(rows, ("name",))
            return
        lite = sql.replace("<=>", "IS").replace("%s", "?")
        try:
            cur = self.conn.db.execute(lite, params)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                raise pymysql.err.ProgrammingError(1146, "synthetic") from None
            raise
        self.description = cur.description
        self._rows = cur.fetchall()

    def _set(self, rows: list[tuple], names: tuple[str, ...]) -> None:
        self._rows = rows
        self.description = tuple((n, None, None, None, None, None, None) for n in names)

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def close(self) -> None:
        return None


class SqliteConn:
    """pymysql-shaped connection over an in-memory SQLite database."""

    def __init__(self, database: str, lctn: int = 0):
        self.db = sqlite3.connect(":memory:")
        self.database = database
        self.lctn = lctn
        self.sql: list[str] = []
        self.errors: dict[str, int] = {}
        self.hidden: set[str] = set()
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True

    def writes(self) -> list[str]:
        """Every recorded statement that would modify data or schema."""
        return [s for s in self.sql if _WRITE.match(s)]


def build(  # pylint: disable=too-many-arguments
    database: str,
    *,
    prices: Iterable[tuple] = (),
    holidays: Iterable[date] = (),
    private: Mapping[str, int] | None = None,
    equity_name: str = "equity_historical",
    with_holidays: bool = True,
    raw_rows: Iterable[Mapping] = (),
    profiles: Iterable[tuple] | None = None,
    lctn: int = 0,
) -> SqliteConn:
    """Seed a connection. ``prices`` rows: (symbol, date, interval, adjustment, valid, filled).

    ``raw_rows`` are dict inserts (any equity column); ``profiles`` rows are
    (symbol, date, currency, price, market_cap) for ``equity_profile``.
    """
    conn = SqliteConn(database, lctn)
    conn.db.execute(EQUITY_DDL.format(name=equity_name))
    for symbol, day, interval, adjustment, valid, filled in prices:
        conn.db.execute(
            f"INSERT INTO {equity_name} (symbol, date, close, interval_type, adjustment_type,"
            " is_valid, is_filled) VALUES (?, ?, 1.0, ?, ?, ?, ?)",
            (symbol, day.isoformat(), interval, adjustment, valid, filled),
        )
    for raw in raw_rows:
        cols = ", ".join(raw)
        marks = ", ".join("?" for _ in raw)
        conn.db.execute(
            f"INSERT INTO {equity_name} ({cols}) VALUES ({marks})",
            [v.isoformat() if isinstance(v, date) else v for v in raw.values()],
        )
    if profiles is not None:
        conn.db.execute(PROFILE_DDL)
        for symbol, day, currency, price, cap in profiles:
            conn.db.execute(
                "INSERT INTO equity_profile (symbol, date, currency, price, market_cap)"
                " VALUES (?, ?, ?, ?, ?)",
                (symbol, day.isoformat() if day else None, currency, price, cap),
            )
    if with_holidays:
        conn.db.execute(HOLIDAY_DDL)
        for day in holidays:
            conn.db.execute(
                "INSERT INTO market_holidays VALUES (?, 'US', 'synthetic', ?)",
                (day.isoformat(), day.year),
            )
    for table, rows in (private or {}).items():
        conn.db.execute(f"CREATE TABLE {table} (id INTEGER)")
        conn.db.executemany(
            f"INSERT INTO {table} VALUES (?)", [(i,) for i in range(rows)]
        )
    conn.db.commit()
    return conn


def row(
    symbol: str,
    day: date,
    *,
    valid=1,
    filled=0,
    interval="1d",
    adjustment="splits_only",
):
    """One synthetic price row tuple for :func:`build`."""
    return (symbol, day, interval, adjustment, valid, filled)
