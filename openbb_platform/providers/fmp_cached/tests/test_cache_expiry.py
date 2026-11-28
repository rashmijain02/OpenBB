"""Expiry and pruning of the fmp_cached provider cache (#1292).

Hermetic: every test replaces ``cache_schema.execute_query`` (the single
seam the prune path uses) with a SQLite-backed double that honours the
real seam's contract: ``%s`` placeholders, a list of dict rows for
``SELECT`` statements and ``cursor.rowcount`` for everything else. No
MySQL connection is ever opened and every row is synthetic.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta

import pytest
from openbb_fmp_cached.utils import cache_schema, database

FAKE_PASSWORD = "synthetic-pw-7f3a"  # noqa: S105 - synthetic test value
FAKE_TARGET = "cache_user@db.invalid:3307/openbb_fmp_cache_fake"


class FakePool:
    """Synthetic stand-in for ``database.ConnectionPool`` (params only)."""

    connection_params = {
        "host": "db.invalid",
        "port": 3307,
        "user": "cache_user",
        "password": FAKE_PASSWORD,
        "database": "openbb_fmp_cache_fake",
        "charset": "utf8mb4",
    }


PROTECTED_TABLES = (
    "pi_eod_snapshot",
    "pi_eod_live_pointer",
    "snapshot_job",
    "snapshot_job_error",
    "pi_paper_account",
    "pi_paper_order",
    "_pi_paper_lot",
    "fmp_trading_state",
    "pi_execution_audit_event",
    "schema_version",
)


class SqliteSeam:
    """SQLite double for ``database.execute_query`` (same call contract)."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # SQLite's CURRENT_TIMESTAMP is UTC; MySQL's UTC_TIMESTAMP() is too.
        self.conn.create_function(
            "UTC_TIMESTAMP",
            0,
            lambda: datetime.utcnow().isoformat(sep=" ", timespec="seconds"),
        )
        self.statements: list[tuple[str, tuple]] = []

    @staticmethod
    def _adapt(value):
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        return value

    def __call__(self, query: str, params: tuple = ()):
        self.statements.append((query, tuple(params)))
        cursor = self.conn.execute(
            query.replace("%s", "?"), tuple(self._adapt(p) for p in params)
        )
        if query.strip().upper().startswith("SELECT"):
            return [dict(row) for row in cursor.fetchall()]
        self.conn.commit()
        return cursor.rowcount

    # -- fixture helpers (not part of the seam) ---------------------------
    def setup(self, sql: str) -> None:
        self.conn.executescript(sql)

    def count(self, table: str, where: str = "1=1") -> int:
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}"
        ).fetchone()
        return int(row[0])


def _id_table(name: str) -> str:
    return (
        f"CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "symbol TEXT, cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    )


def _add(name: str, symbol: str, age: str) -> str:
    return (
        f"INSERT INTO {name} (symbol, cached_at) "
        f"VALUES ('{symbol}', datetime('now', '{age}'));"
    )


@pytest.fixture
def seam(monkeypatch):
    """Synthetic store: expiring caches, a non-expiring cache, operator tables."""
    monkeypatch.delenv("FMP_CACHE_TEST_MODE", raising=False)
    db = SqliteSeam()
    script = [
        "CREATE TABLE aftermarket_quote (symbol TEXT PRIMARY KEY, "
        "cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_valid BOOLEAN DEFAULT 1);",
        "INSERT INTO aftermarket_quote VALUES ('FRESH', datetime('now', '-30 seconds'), 1);",
        "INSERT INTO aftermarket_quote VALUES ('STALE', datetime('now', '-5 minutes'), 1);",
        "CREATE TABLE ttl_cache (cache_name TEXT, cache_key TEXT, payload TEXT, "
        "cached_at TIMESTAMP, PRIMARY KEY (cache_name, cache_key));",
        "INSERT INTO ttl_cache VALUES ('ExchangeMarketHours', 'k-fresh', '{}', "
        "datetime('now', '-1 hours'));",
        "INSERT INTO ttl_cache VALUES ('ExchangeMarketHours', 'k-stale', '{}', "
        "datetime('now', '-2 days'));",
        # A cache_name with no registered TTL must never be touched.
        "INSERT INTO ttl_cache VALUES ('UnregisteredCache', 'k-old', '{}', "
        "datetime('now', '-400 days'));",
    ]
    for table in (
        "balance_sheet",
        "cash_flow",
        "income_statement",
        "key_metrics",
        "financial_ratios",
        "etf_holdings",
        "complementary_market_yields",
    ):  # 1-day TTL tables
        script += [
            _id_table(table),
            _add(table, "FRESH", "-1 hours"),
            _add(table, "STALE", "-2 days"),
        ]
    for table in ("equity_profile", "equity_peers", "institutional_ownership"):
        # 7-day TTL: a 3-day-old row is still fresh.
        script += [
            _id_table(table),
            _add(table, "FRESH", "-3 days"),
            _add(table, "STALE", "-8 days"),
        ]
    script += [
        _id_table("equity_quote"),
        _add("equity_quote", "FRESH", "-2 minutes"),
        _add("equity_quote", "STALE", "-10 minutes"),
        # fmp_cached MCP (#1300): per-row expiry in expires_at.
        "CREATE TABLE fmp_mcp_ephemeral (cache_key TEXT PRIMARY KEY, "
        "expires_at TIMESTAMP NOT NULL);",
        "INSERT INTO fmp_mcp_ephemeral VALUES ('k-live', datetime('now', '+1 hours'));",
        "INSERT INTO fmp_mcp_ephemeral VALUES ('k-expired', datetime('now', '-1 minutes'));",
        # Persistent MCP table: never pruned whatever its age.
        "CREATE TABLE fmp_mcp_document (cache_key TEXT PRIMARY KEY, fetched_at TIMESTAMP);",
        "INSERT INTO fmp_mcp_document VALUES ('k-ancient', datetime('now', '-900 days'));",
        # Non-expiring cache: historical bars are never TTL-evicted.
        _id_table("equity_historical"),
        _add("equity_historical", "ANCIENT", "-900 days"),
    ]
    for table in PROTECTED_TABLES:
        script += [_id_table(table), _add(table, "OPERATOR", "-900 days")]
    db.setup("\n".join(script))
    monkeypatch.setattr(cache_schema, "execute_query", db)
    # The CLI names its target from the pool's connection params; give it a
    # synthetic config so nothing reads a real settings file.
    monkeypatch.setattr(database, "get_connection_pool", lambda: FakePool())
    return db


def test_cleanup_deletes_only_expired_rows(seam):
    report = cache_schema.cleanup_expired_cache()

    for rule in cache_schema.CACHE_EXPIRY_RULES:
        if rule.table not in ("ttl_cache", "fmp_mcp_ephemeral"):
            assert seam.count(rule.table, "symbol = 'STALE'") == 0, rule.table
            assert seam.count(rule.table, "symbol = 'FRESH'") == 1, rule.table
    for table in (
        "balance_sheet",
        "equity_profile",
        "equity_quote",
        "complementary_market_yields",
        "aftermarket_quote",
    ):
        assert seam.count(table, "symbol = 'FRESH'") == 1, table
        assert seam.count(table, "symbol = 'STALE'") == 0, table
    assert seam.count("ttl_cache", "cache_key = 'k-fresh'") == 1
    assert seam.count("ttl_cache", "cache_key = 'k-stale'") == 0
    assert seam.count("ttl_cache", "cache_name = 'UnregisteredCache'") == 1
    assert seam.count("fmp_mcp_ephemeral", "cache_key = 'k-live'") == 1
    assert seam.count("fmp_mcp_ephemeral", "cache_key = 'k-expired'") == 0
    assert seam.count("fmp_mcp_document") == 1
    assert report["dry_run"] is False
    assert report["total"] == len(cache_schema.CACHE_EXPIRY_RULES)
    assert report["errors"] == {}


def test_non_expiring_and_operator_tables_are_never_touched(seam):
    cache_schema.cleanup_expired_cache()

    assert seam.count("equity_historical") == 1
    for table in PROTECTED_TABLES:
        assert seam.count(table) == 1, table
    touched = " ".join(sql for sql, _ in seam.statements)
    for table in (*PROTECTED_TABLES, "equity_historical", "fmp_mcp_document"):
        assert not re.search(rf"\b{table}\b", touched), table


def test_dry_run_reports_counts_without_deleting(seam):
    report = cache_schema.prune_expired_cache(dry_run=True)

    assert report["dry_run"] is True
    assert report["tables"]["balance_sheet"]["rows"] == 1
    assert report["tables"]["ttl_cache[ExchangeMarketHours]"]["rows"] == 1
    assert report["total"] == len(cache_schema.CACHE_EXPIRY_RULES)
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 1
    assert seam.count("ttl_cache", "cache_key = 'k-stale'") == 1
    assert not any(
        sql.lstrip().upper().startswith("DELETE") for sql, _ in seam.statements
    )


def test_deletes_in_bounded_parameterized_batches(seam):
    seam.setup(
        "\n".join(_add("balance_sheet", f"OLD{i}", "-3 days") for i in range(25))
    )

    report = cache_schema.prune_expired_cache(tables=["balance_sheet"], batch_size=10)

    entry = report["tables"]["balance_sheet"]
    assert entry["rows"] == 26  # 25 synthetic + the fixture's STALE row
    assert entry["batches"] == 3
    assert seam.count("balance_sheet") == 1
    deletes = [
        (q, p) for q, p in seam.statements if q.lstrip().upper().startswith("DELETE")
    ]
    assert len(deletes) == 3
    for query, params in deletes:
        # Every value travels as a parameter; at most batch_size keys per batch.
        assert "OLD" not in query and "datetime(" not in query
        assert query.count("%s") == len(params)
        assert len(params) <= 10 + 1  # keys + the cutoff guard


def test_tables_filter_limits_scope(seam):
    report = cache_schema.prune_expired_cache(tables=["equity_quote"])

    assert list(report["tables"]) == ["equity_quote"]
    assert seam.count("equity_quote", "symbol = 'STALE'") == 0
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 1


@pytest.mark.parametrize(
    "table", [*PROTECTED_TABLES, "equity_historical", "x; DROP TABLE y"]
)
def test_requesting_a_table_outside_the_allowlist_raises_before_any_sql(seam, table):
    with pytest.raises(ValueError, match="not an expiring cache table"):
        cache_schema.prune_expired_cache(tables=[table])
    assert seam.statements == []


@pytest.mark.parametrize(
    "table", ["fmp_trading_state", "pi_eod_snapshot", "equity_historical"]
)
def test_allowlist_is_enforced_even_if_rules_are_extended(seam, monkeypatch, table):
    rogue = cache_schema.CacheExpiryRule(table=table, ttl_seconds=1)
    monkeypatch.setattr(
        cache_schema,
        "CACHE_EXPIRY_RULES",
        (*cache_schema.CACHE_EXPIRY_RULES, rogue),
    )

    with pytest.raises(ValueError, match="not an expiring cache table"):
        cache_schema.cleanup_expired_cache()
    assert seam.statements == []
    assert seam.count(table) == 1


def test_rules_are_inside_the_explicit_allowlist():
    allow = cache_schema.EXPIRABLE_CACHE_TABLES
    assert {r.table for r in cache_schema.CACHE_EXPIRY_RULES} <= allow
    for table in PROTECTED_TABLES:
        assert table not in allow
    for table in allow:
        assert (
            table in cache_schema.FLATTENED_TABLES
            or table in cache_schema.FMP_MCP_TABLE_COLUMNS
        ), table


def test_mcp_store_tables_are_not_entity_tables():
    """Entity scripts loop over FLATTENED_TABLES; MCP tables are not entities."""
    assert not set(cache_schema.FMP_MCP_TABLE_COLUMNS) & set(
        cache_schema.FLATTENED_TABLES
    )


def test_a_failed_clock_read_is_reported_not_raised(seam, monkeypatch):
    real = seam

    def no_utc(query, params=()):
        if "UTC_TIMESTAMP" in query.upper():
            raise RuntimeError("connection dropped")
        return real(query, params)

    monkeypatch.setattr(cache_schema, "execute_query", no_utc)
    report = cache_schema.cleanup_expired_cache()
    assert "fmp_mcp_ephemeral" in report["errors"]
    assert seam.count("equity_quote", "symbol = 'STALE'") == 0, "other tables pruned"


def test_cutoff_uses_the_database_clock(seam, monkeypatch):
    """Rows are written with CURRENT_TIMESTAMP, so expiry is measured on that clock."""
    real = seam

    def skewed(query, params=()):
        upper = query.upper()
        if ("CURRENT_TIMESTAMP" in upper or "UTC_TIMESTAMP" in upper) and (
            query.lstrip().upper().startswith("SELECT")
        ):
            # Database clock one year behind: nothing has expired yet.
            return [{"db_now": "2000-01-01 00:00:00"}]
        return real(query, params)

    monkeypatch.setattr(cache_schema, "execute_query", skewed)
    report = cache_schema.cleanup_expired_cache()

    assert report["total"] == 0
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 1


def test_table_error_is_reported_and_other_tables_still_pruned(seam, caplog):
    seam.setup("DROP TABLE equity_quote;")

    with caplog.at_level(logging.WARNING, logger=cache_schema.__name__):
        report = cache_schema.cleanup_expired_cache()

    assert "equity_quote" in report["errors"]
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 0
    assert any("equity_quote" in r.getMessage() for r in caplog.records)


def test_counts_are_logged(seam, caplog):
    with caplog.at_level(logging.INFO, logger=cache_schema.__name__):
        cache_schema.cleanup_expired_cache()

    messages = [r.getMessage() for r in caplog.records]
    assert any("balance_sheet" in m and "rows=1" in m for m in messages)
    assert any("total=" in m for m in messages)


@pytest.mark.parametrize("bad", [0, -1, 10_001])
def test_batch_size_is_bounded(seam, bad):
    with pytest.raises(ValueError, match="batch_size"):
        cache_schema.prune_expired_cache(batch_size=bad)
    assert seam.statements == []


def test_test_mode_prunes_the_prefixed_complementary_table(seam, monkeypatch):
    monkeypatch.setenv("FMP_CACHE_TEST_MODE", "true")
    seam.setup(
        _id_table("test_complementary_market_yields")
        + _add("test_complementary_market_yields", "STALE", "-2 days")
    )

    cache_schema.prune_expired_cache(tables=["complementary_market_yields"])

    assert seam.count("test_complementary_market_yields") == 0
    assert seam.count("complementary_market_yields", "symbol = 'STALE'") == 1


# ---------------------------------------------------------------------------
# Contract: every rule's TTL equals the TTL its reader uses. A shorter rule
# would delete rows a reader still treats as fresh.
# ---------------------------------------------------------------------------


def _reader_ttls() -> dict[str, int]:
    from openbb_fmp_cached.complementary import free_yield_service
    from openbb_fmp_cached.models import (
        aftermarket_quote,
        balance_sheet,
        cash_flow,
        equity_peers,
        equity_profile,
        equity_quote,
        etf_holdings,
        exchange_market_hours,
        financial_ratios,
        income_statement,
        institutional_ownership,
        key_metrics,
    )

    day = 86400
    return {
        "aftermarket_quote": aftermarket_quote._TTL_SECONDS,
        "ttl_cache[ExchangeMarketHours]": exchange_market_hours._TTL_SECONDS,
        "complementary_market_yields": free_yield_service.DEFAULT_TTL_HOURS * 3600,
        "balance_sheet": balance_sheet.BALANCE_SHEET_TTL_DAYS * day,
        "cash_flow": cash_flow.CASH_FLOW_TTL_DAYS * day,
        "income_statement": income_statement.INCOME_STATEMENT_TTL_DAYS * day,
        "key_metrics": key_metrics.KEY_METRICS_TTL_DAYS * day,
        "financial_ratios": financial_ratios.FINANCIAL_RATIOS_TTL_DAYS * day,
        "etf_holdings": etf_holdings.ETF_HOLDINGS_TTL_DAYS * day,
        "equity_profile": equity_profile.PROFILE_TTL_DAYS * day,
        "equity_peers": equity_peers.PEERS_TTL_DAYS * day,
        "institutional_ownership": institutional_ownership.INSTITUTIONAL_OWNERSHIP_TTL_DAYS
        * day,
        "equity_quote": equity_quote.QUOTE_TTL_SECONDS,
        # fmp_cached MCP (#1300): expiry is per row in expires_at.
        "fmp_mcp_ephemeral": 0,
    }


def test_rule_ttls_match_reader_ttls():
    rules = {r.label: r.ttl_seconds for r in cache_schema.CACHE_EXPIRY_RULES}
    assert rules == _reader_ttls()


# ---------------------------------------------------------------------------
# Manual prune command: python -m openbb_fmp_cached.utils.cache_prune
# ---------------------------------------------------------------------------


def test_cli_defaults_to_dry_run(seam, capsys):
    import json

    from openbb_fmp_cached.utils import cache_prune

    code = cache_prune.main([])

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["dry_run"] is True
    assert report["tables"]["balance_sheet"]["rows"] == 1
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 1


def test_cli_apply_deletes_selected_tables(seam, capsys):
    import json

    from openbb_fmp_cached.utils import cache_prune

    code = cache_prune.main(
        ["--apply", "--table", "balance_sheet", "--table", "equity_quote"]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["dry_run"] is False
    assert sorted(report["tables"]) == ["balance_sheet", "equity_quote"]
    assert seam.count("balance_sheet", "symbol = 'STALE'") == 0
    assert seam.count("cash_flow", "symbol = 'STALE'") == 1


def test_cli_rejects_protected_table(seam, capsys):
    from openbb_fmp_cached.utils import cache_prune

    code = cache_prune.main(["--apply", "--table", "fmp_trading_state"])

    assert code == 2
    assert "not an expiring cache table" in capsys.readouterr().err
    assert seam.statements == []


def test_cli_exit_code_reports_table_errors(seam, capsys):
    from openbb_fmp_cached.utils import cache_prune

    seam.setup("DROP TABLE equity_quote;")

    assert cache_prune.main(["--apply"]) == 1
    capsys.readouterr()


@pytest.mark.parametrize(
    "table", ["fmp_trading_state", "pi_eod_snapshot", "snapshot_job"]
)
def test_operator_tables_refused_even_if_added_to_the_allowlist(
    seam, monkeypatch, table
):
    monkeypatch.setattr(
        cache_schema,
        "EXPIRABLE_CACHE_TABLES",
        cache_schema.EXPIRABLE_CACHE_TABLES | {table},
    )
    monkeypatch.setattr(
        cache_schema,
        "CACHE_EXPIRY_RULES",
        (cache_schema.CacheExpiryRule(table=table, ttl_seconds=1),),
    )

    with pytest.raises(ValueError, match="not an expiring cache table"):
        cache_schema.cleanup_expired_cache()
    assert seam.statements == []
    assert seam.count(table) == 1


def test_row_refreshed_between_select_and_delete_survives(seam, monkeypatch):
    """The DELETE re-checks expiry, so a concurrent refresh is not lost."""

    def refreshing(query, params=()):
        result = seam(query, params)
        if "FROM balance_sheet" in query and "ORDER BY" in query:
            seam.conn.execute(
                "UPDATE balance_sheet SET cached_at = CURRENT_TIMESTAMP "
                "WHERE symbol = 'STALE'"
            )
        return result

    monkeypatch.setattr(cache_schema, "execute_query", refreshing)
    report = cache_schema.prune_expired_cache(tables=["balance_sheet"])

    assert seam.count("balance_sheet", "symbol = 'STALE'") == 1
    assert report["tables"]["balance_sheet"]["rows"] == 0


# ---------------------------------------------------------------------------
# CLI target naming, failure handling and logging (review follow-ups)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["--apply"]])
def test_cli_report_names_target_without_password(seam, capsys, argv):
    import json

    from openbb_fmp_cached.utils import cache_prune

    assert cache_prune.main(argv) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["target"] == FAKE_TARGET
    assert FAKE_PASSWORD not in captured.out + captured.err


def test_cli_connection_failure_exits_2_with_one_clean_line(seam, monkeypatch, capsys):
    import pymysql

    from openbb_fmp_cached.utils import cache_prune

    def unreachable(query, params=()):
        raise pymysql.err.OperationalError(
            2003,
            f"Can't connect to MySQL server on 'secret-host.internal' "
            f"(user=other_user pw={FAKE_PASSWORD})",
        )

    monkeypatch.setattr(cache_schema, "execute_query", unreachable)

    code = cache_prune.main(["--apply"])

    err = capsys.readouterr().err
    error_lines = [line for line in err.splitlines() if line.startswith("error:")]
    assert code == 2
    assert len(error_lines) == 1
    assert FAKE_TARGET in error_lines[0]
    assert "OperationalError" in error_lines[0]
    for leaked in ("Traceback", FAKE_PASSWORD, "secret-host", "other_user"):
        assert leaked not in err


def test_cli_missing_config_exits_2_with_one_clean_line(seam, monkeypatch, capsys):
    from openbb_fmp_cached.utils import cache_prune

    def no_config():
        raise ValueError("Missing MySQL credential(s): user, password.")

    monkeypatch.setattr(database, "get_connection_pool", no_config)

    code = cache_prune.main([])

    err = capsys.readouterr().err
    assert code == 2
    assert [line for line in err.splitlines() if line.startswith("error:")] == [
        "error: Missing MySQL credential(s): user, password."
    ]
    assert "Traceback" not in err
    assert seam.statements == []


def test_cli_configures_info_logging_to_stderr(seam, monkeypatch, capsys):
    import sys

    from openbb_fmp_cached.utils import cache_prune

    calls = []
    monkeypatch.setattr(
        cache_prune.logging, "basicConfig", lambda **kw: calls.append(kw)
    )

    cache_prune.main([])
    capsys.readouterr()

    assert len(calls) == 1
    assert calls[0]["level"] == logging.INFO
    assert calls[0]["stream"] is sys.stderr


def test_cli_logs_counts_not_row_contents(seam, caplog, capsys):
    from openbb_fmp_cached.utils import cache_prune

    with caplog.at_level(logging.INFO):
        cache_prune.main(["--apply"])
    capsys.readouterr()

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "rows=" in text
    for value in ("STALE", "FRESH", "k-stale", FAKE_PASSWORD):
        assert value not in text


def test_table_error_text_is_not_echoed(seam, monkeypatch, caplog, capsys):
    """A mid-run DB error is reported by type and code, never by its text."""
    import pymysql

    from openbb_fmp_cached.utils import cache_prune

    def flaky(query, params=()):
        if "equity_quote" in query:
            raise pymysql.err.OperationalError(
                2013, f"Lost connection to 'secret-host.internal' pw={FAKE_PASSWORD}"
            )
        return seam(query, params)

    monkeypatch.setattr(cache_schema, "execute_query", flaky)
    with caplog.at_level(logging.INFO):
        code = cache_prune.main(["--apply"])

    captured = capsys.readouterr()
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert code == 1
    assert "OperationalError 2013" in captured.out
    for leaked in ("secret-host", FAKE_PASSWORD):
        assert leaked not in captured.out + captured.err + logs


# ---------------------------------------------------------------------------
# #1309: fmp_mcp_ephemeral stamps expires_at in UTC, so its cutoff must be UTC
# even when the MySQL session clock is not.
# ---------------------------------------------------------------------------


def test_utc_stamped_rule_uses_the_utc_clock(seam, monkeypatch):
    real = seam

    def ist_session(query, params=()):
        if "CURRENT_TIMESTAMP" in query.upper() and query.lstrip().upper().startswith(
            "SELECT"
        ):
            # Session clock at UTC+05:30: 5.5 hours ahead of the UTC stamps.
            ahead = datetime.utcnow() + timedelta(hours=5, minutes=30)
            return [{"db_now": ahead.isoformat(sep=" ", timespec="seconds")}]
        return real(query, params)

    seam.setup(
        "INSERT INTO fmp_mcp_ephemeral VALUES "
        "('k-3h-left', datetime('now', '+3 hours'));"
    )
    monkeypatch.setattr(cache_schema, "execute_query", ist_session)
    cache_schema.prune_expired_cache(tables=["fmp_mcp_ephemeral"])

    assert seam.count("fmp_mcp_ephemeral", "cache_key = 'k-3h-left'") == 1
    assert seam.count("fmp_mcp_ephemeral", "cache_key = 'k-expired'") == 0


def test_only_the_mcp_ephemeral_rule_is_utc_stamped():
    utc = {r.table for r in cache_schema.CACHE_EXPIRY_RULES if r.utc_clock}
    assert utc == {"fmp_mcp_ephemeral"}


def test_prune_skips_the_mcp_table_on_databases_without_it(seam):
    """Databases provisioned before the MCP server existed have no such table."""
    seam.setup("DROP TABLE fmp_mcp_ephemeral;")
    report = cache_schema.cleanup_expired_cache()
    assert report["errors"] == {}
    assert report["tables"]["fmp_mcp_ephemeral"]["rows"] == 0


def test_create_all_flattened_tables_does_not_create_mcp_tables(monkeypatch):
    created = []
    monkeypatch.setattr(
        cache_schema,
        "FLATTENED_TABLES",
        {"alpha": {"schema": lambda: created.append("alpha")}},
    )
    monkeypatch.setattr(
        cache_schema, "execute_query", lambda *a, **k: created.append("sql")
    )
    cache_schema.create_all_flattened_tables()
    assert created == ["alpha"], "the MCP server creates its own tables"
