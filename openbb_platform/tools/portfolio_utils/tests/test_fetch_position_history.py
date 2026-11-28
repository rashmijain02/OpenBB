"""Regression tests for explicit database propagation in position-history warmers."""

from __future__ import annotations

import argparse
from typing import Any

import pymysql
import pytest
from openbb_fmp_cached.utils import database as database_module
from openbb_fmp_cached.utils.database import (
    ConnectionPool,
    DatabaseConfig,
    get_connection_pool,
)
from portfolio_utils import fetch_position_history as tool
from portfolio_utils.fmp_sync import sessions

from .fmp_sync.conftest import DISPOSABLE_DB
from .fmp_sync.fixtures import sql_fixture as sf
from .fmp_sync.test_readiness import CLOSURES_2026_2027, FIXTURE, NOW, TARGET


def test_run_position_history_warm_threads_database_to_default_fetcher(monkeypatch):
    """The default fmp_cached fetch path scopes cache work to the explicit DB."""
    config = DatabaseConfig.__new__(DatabaseConfig)
    config.config = {
        "host": "localhost",
        "port": 3306,
        "user": "tester",
        "password": "secret",
        "database": "configured_db",
        "charset": "utf8mb4",
        "test_mode": False,
    }
    monkeypatch.setattr(database_module, "_connection_pool", ConnectionPool(config))
    observed: list[str] = []

    def fake_scoped_fetch(
        symbol: str,
        *,
        start_date: Any,
        end_date: Any,
        credentials: dict | None,
    ) -> dict[str, Any]:
        observed.append(get_connection_pool().connection_params["database"])
        return {
            "rows": 1,
            "first": str(start_date),
            "last": str(end_date),
            "cache_tag": "FETCH",
        }

    monkeypatch.setattr(tool, "_fetch_one_symbol_history_in_scope", fake_scoped_fetch)

    result = tool.run_position_history_warm(
        symbols=["MSFT"],
        years=1,
        database="alternate_db",
        skip_holiday_prestep=True,
        api_key_resolver=lambda: "test-key",
        readiness_fn=lambda symbols, database: {},
    )

    assert result.success == ["MSFT"]
    assert observed == ["alternate_db"]
    assert get_connection_pool().connection_params["database"] == "configured_db"


def test_injected_position_fetcher_keeps_existing_signature():
    """Database plumbing must not break injected job/test collaborators."""

    def injected_fetch(
        symbol: str,
        *,
        start_date: Any,
        end_date: Any,
        credentials: dict | None,
    ) -> dict[str, Any]:
        return {
            "rows": 1,
            "first": str(start_date),
            "last": str(end_date),
            "cache_tag": "FETCH",
        }

    result = tool.run_position_history_warm(
        symbols=["MSFT"],
        database="alternate_db",
        skip_holiday_prestep=True,
        fetch_one_fn=injected_fetch,
        api_key_resolver=lambda: "test-key",
        readiness_fn=lambda symbols, database: {},
    )

    assert result.success == ["MSFT"]


def test_check_portfolio_app_readiness_delegates_to_v2(monkeypatch):
    """Legacy readiness keeps its four keys and delegates to readiness v2 (#1345)."""
    seen: dict[str, Any] = {}

    class _Report:
        def legacy(self) -> dict[str, Any]:
            return {
                "target_date": "2026-11-27",
                "table_counts": {},
                "missing_price_symbols": [],
                "stale_price_symbols": [],
                "data_status": "VALIDATED",
            }

    def fake_evaluate(symbols, **kwargs):
        seen.update(kwargs, symbols=symbols)
        return _Report()

    monkeypatch.setattr(tool.readiness_v2, "evaluate", fake_evaluate)
    out = tool.check_portfolio_app_readiness(["MSFT"], "alternate_db")
    assert set(out) >= {"target_date", "table_counts", "missing_price_symbols", "stale_price_symbols"}
    assert seen["database"] == "alternate_db" and seen["symbols"] == ["MSFT"]
    assert seen["now"].tzinfo is not None
    assert seen["policy"] is None  # private counts stay opt-in


# --- #1345 fix: DB problems must never print READY / report success -----------------

_NOT_READY = ("UNKNOWN", "UNAVAILABLE", "CRITICAL", "BLOCKED", "UNVALIDATED")


def _db_down(code: int):
    def connect():
        raise pymysql.err.OperationalError(code, "synthetic")

    return connect


def _timeout_conn():
    conn = _fixture_conn()
    conn.errors["MAX(date)"] = 3024
    return lambda: conn


def _missing_table_conn():
    return lambda: _fixture_conn(with_holidays=False)


def _fixture_conn(**kwargs):
    kwargs.setdefault("holidays", CLOSURES_2026_2027)
    return sf.build(
        DISPOSABLE_DB, prices=[sf.row("MSFT", TARGET)], **kwargs
    )


_DB_PROBLEMS = {
    "connect_failure_2003": lambda: _db_down(2003),
    "query_timeout_3024": _timeout_conn,
    "missing_table": _missing_table_conn,
}


def _readiness_for(connect_fn) -> dict[str, Any]:
    return tool.check_portfolio_app_readiness(
        ["MSFT"],
        now=NOW,
        calendar=sessions.SyntheticCalendar.from_json(FIXTURE),
        connect_fn=connect_fn,
    )


def _cli_args():
    return argparse.Namespace(
        symbols="MSFT", years=1, database=None, skip_holiday_prestep=True, dry_run=False
    )


@pytest.mark.parametrize("problem", sorted(_DB_PROBLEMS))
def test_db_problem_is_never_ready_in_legacy_cli(problem, monkeypatch, capsys):
    """Readiness v2 turns DB trouble into check states; the CLI must not say READY."""
    readiness = _readiness_for(_DB_PROBLEMS[problem]())
    assert readiness["data_status"] in _NOT_READY, readiness["data_status"]
    # The reason it used to lie: the legacy lists are empty on DB trouble.
    assert not readiness["missing_price_symbols"] or problem == "missing_table"

    monkeypatch.setattr(
        tool,
        "run_position_history_warm",
        lambda **_kw: tool.PositionHistoryWarmResult(
            requested_symbols=1, success=["MSFT"], readiness=readiness
        ),
    )
    tool._run_cli_locked(_cli_args())  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert "READY" not in out.replace("NOT READY", "")
    assert f"Status: {readiness['data_status']}" in out


def test_healthy_readiness_still_prints_ready(monkeypatch, capsys):
    readiness = _readiness_for(lambda: _fixture_conn())
    assert readiness["data_status"] == "VALIDATED", readiness
    monkeypatch.setattr(
        tool,
        "run_position_history_warm",
        lambda **_kw: tool.PositionHistoryWarmResult(
            requested_symbols=1, success=["MSFT"], readiness=readiness
        ),
    )
    tool._run_cli_locked(_cli_args())  # pylint: disable=protected-access
    assert "Status: READY" in capsys.readouterr().out


@pytest.mark.parametrize("problem", sorted(_DB_PROBLEMS))
def test_to_summary_carries_data_status(problem):
    readiness = _readiness_for(_DB_PROBLEMS[problem]())
    result = tool.PositionHistoryWarmResult(requested_symbols=1, readiness=readiness)
    assert result.to_summary()["readiness"]["data_status"] == readiness["data_status"]
    assert not result.readiness_ok()


def test_readiness_ok_rules():
    ok = tool.PositionHistoryWarmResult
    assert ok(readiness={}).readiness_ok()  # dry run: nothing evaluated
    for status in ("VALIDATED", "WARN"):
        assert ok(readiness={"data_status": status}).readiness_ok()
    assert not ok(readiness={"data_status": "UNKNOWN"}).readiness_ok()
    assert not ok(readiness={"target_date": "2026-11-27"}).readiness_ok()  # no status
    assert not ok(
        readiness={"data_status": "VALIDATED", "missing_price_symbols": ["X"]}
    ).readiness_ok()
