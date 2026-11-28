"""Manual CLI, openbb-jobs handler and warmer share one guard (#1344-T01, D7, D8)."""

from __future__ import annotations

import sys
from typing import Any

import portfolio_utils.jobs as jobs_module
import pytest
from openbb_core.app.jobs.models import JobContext, JobResult
from portfolio_utils import fetch_position_history as tool
from portfolio_utils.fmp_sync.locking import LockBusy, target_lock

from .conftest import DISPOSABLE_DB
from .test_locking import holder, state_root  # noqa: F401  (fixtures)


@pytest.fixture
def recorder(monkeypatch):
    """Record every DB/FMP-touching collaborator of the warmer and the CLI."""
    calls: list[tuple[str, Any]] = []

    def _holidays(start, end, database=None):
        calls.append(("holidays", database))

    def _symbols(database=None):
        calls.append(("symbols", database))
        return ["SPY"], []

    def _fetch_history(symbols, **kwargs):
        calls.append(("fetch", tuple(symbols)))
        return {
            "success": list(symbols),
            "failed": [],
            "total_rows": 0,
            "start_date": "2020-01-01",
            "end_date": "2025-01-01",
        }

    def _readiness(symbols, database=None):
        calls.append(("readiness", database))
        return {
            "target_date": "2025-01-01",
            "table_counts": {},
            "missing_price_symbols": [],
            "stale_price_symbols": [],
        }

    monkeypatch.setattr(tool, "ensure_market_holidays", _holidays)
    monkeypatch.setattr(tool, "get_portfolio_symbols", _symbols)
    monkeypatch.setattr(tool, "fetch_history", _fetch_history)
    monkeypatch.setattr(tool, "check_portfolio_app_readiness", _readiness)
    # Default args of run_position_history_warm were bound at import time.
    defaults = list(tool.run_position_history_warm.__kwdefaults__.items())
    patched = dict(defaults)
    patched.update(
        get_symbols_fn=_symbols, holiday_prestep_fn=_holidays, readiness_fn=_readiness
    )
    monkeypatch.setattr(tool.run_position_history_warm, "__kwdefaults__", patched)
    return calls


def _run_main(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["fetch_position_history", *argv])
    try:
        tool.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_manual_cli_busy_exit_75_no_fetch(
    monkeypatch, capsys, holder, recorder
):  # noqa: F811
    holder(DISPOSABLE_DB)
    code = _run_main(monkeypatch, "--symbols", "SPY", "--database", DISPOSABLE_DB)
    assert code == 75
    assert (
        recorder == []
    ), "a busy run must not touch holidays, symbols, FMP or readiness"
    assert "SKIPPED_BUSY" in capsys.readouterr().out


def test_manual_cli_runs_under_lock_when_free(
    monkeypatch, recorder, state_root
):  # noqa: F811
    code = _run_main(monkeypatch, "--symbols", "SPY", "--database", DISPOSABLE_DB)
    assert code == 0
    assert [c[0] for c in recorder] == ["holidays", "fetch", "readiness"]
    assert (state_root / f"fmp-sync.{DISPOSABLE_DB}.lock").exists()


def test_cli_dry_run_makes_no_holiday_write(
    monkeypatch, capsys, recorder, state_root
):  # noqa: F811
    """D7: --dry-run never runs the market_holidays upsert (nor takes the lock)."""
    code = _run_main(
        monkeypatch, "--dry-run", "--symbols", "SPY", "--database", DISPOSABLE_DB
    )
    assert code == 0
    assert recorder == []
    assert "DRY RUN" in capsys.readouterr().out
    assert not state_root.exists()


def test_warmer_enters_guard(holder, recorder):  # noqa: F811
    """run_position_history_warm itself takes the lock (covers every caller)."""
    holder(DISPOSABLE_DB)
    with pytest.raises(LockBusy):
        tool.run_position_history_warm(symbols=["SPY"], database=DISPOSABLE_DB)
    assert recorder == []


def test_warmer_reenters_dispatcher_lock(recorder, state_root):  # noqa: F811
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="dispatcher"):
        result = tool.run_position_history_warm(symbols=["SPY"], database=DISPOSABLE_DB)
    assert result.success == ["SPY"]


def test_jobs_handler_busy_skips(holder, recorder, home_settings):  # noqa: F811
    """The openbb-jobs handler (no database param) resolves the target and skips busy."""
    home_settings(DISPOSABLE_DB)
    holder(DISPOSABLE_DB)
    definition = {d.name: d for d in jobs_module.get_job_definitions()}[
        "portfolio.position_history"
    ]
    params = jobs_module.PositionHistoryJobParams(symbols=["SPY"])
    result = definition.handler(
        JobContext(run_id="r1", job_name=definition.name), params
    )
    assert isinstance(result, JobResult)
    assert result.summary["outcome"] == "SKIPPED_BUSY"
    assert result.warnings and "lock" in result.warnings[0]
    assert recorder == []


def test_manifest_symbols_bypass_get_portfolio_symbols(recorder):
    """Admitted manifest symbols are passed as ``symbols=``; the DB selector never runs."""

    def _boom(database=None):
        raise AssertionError("get_portfolio_symbols must not be called")

    result = tool.run_position_history_warm(
        symbols=["AAA", "BBB"],
        database=DISPOSABLE_DB,
        skip_holiday_prestep=True,
        get_symbols_fn=_boom,
    )
    assert result.requested_symbols == 2
    assert ("fetch", ("AAA", "BBB")) in recorder


def _write_map(tmp_path, state_root):  # noqa: F811
    import json  # pylint: disable=import-outside-toplevel

    path = tmp_path / "map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_root": str(tmp_path),
                "source_sha": "a" * 40,
                "interpreter": str(tmp_path / "venv"),
                "target": DISPOSABLE_DB,
                "target_class": "disposable",
                "profile_path": str(tmp_path / "profile.yaml"),
                "state_root": str(state_root),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_main_lock_status_reports_busy(
    holder, tmp_path, state_root, capsys
):  # noqa: F811
    from portfolio_utils.fmp_sync.__main__ import (
        main,
    )  # pylint: disable=import-outside-toplevel

    map_path = _write_map(tmp_path, state_root)
    assert main(["lock", "--status", "--map", str(map_path)]) == 0
    assert '"lock":"free"' in capsys.readouterr().out
    holder(DISPOSABLE_DB)
    assert main(["lock", "--status", "--map", str(map_path)]) == 0
    assert '"lock":"busy"' in capsys.readouterr().out


def test_main_execute_refused_until_dispatcher(
    tmp_path, state_root, capsys
):  # noqa: F811
    from portfolio_utils.fmp_sync.__main__ import (
        main,
    )  # pylint: disable=import-outside-toplevel

    map_path = _write_map(tmp_path, state_root)
    assert main(["prices", "--execute", "--map", str(map_path)]) == 40
    assert "EXECUTE_NOT_AVAILABLE" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert main(["prices", "--dry-run", "--map", str(bad)]) == 40
