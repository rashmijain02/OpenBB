"""Synthetic builders shared by the #1357 trial-accounting tests (no engine)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
from openbb_backtest.validation.matrix import encode_returns
from openbb_backtest.validation.trials import Cell, CellOutcome, ConfigIdentity, Window

H = "0" * 64

BASE = ConfigIdentity(
    backend="nautilus",
    strategy_id="target_weight_rebalance",
    strategy_version="1.0.0",
    spec_sha256="a" * 64,
    code_sha256="b" * 64,
    param_schema_sha256="c" * 64,
    params_sha256="d" * 64,
    execution_sha256="e" * 64,
    base_dataset_id="f" * 64,
    engine_version="nautilus_trader==1.0",
    worker_version="worker/1",
    fixed_precision=2,
)


def config(i: int, **over) -> ConfigIdentity:
    """Config number ``i`` (differs by params hash)."""
    return replace(BASE, params_sha256=f"{i:064x}", **over)


def sessions(n: int, start: date = date(2024, 1, 2)) -> list[str]:
    """``n`` consecutive calendar days as ISO strings."""
    return [(start + timedelta(days=k)).isoformat() for k in range(n)]


def wfo_cells(n_configs: int, n_windows: int, per_window: int = 5) -> list[Cell]:
    """``n_configs`` x ``n_windows`` contiguous per-fold windows."""
    days = sessions(n_windows * per_window)
    cells = []
    for i in range(n_configs):
        for w in range(n_windows):
            win = Window.from_sessions(
                policy="per_fold",
                method="wfo",
                fold_params={"n_splits": n_windows},
                ordinal=w,
                sessions=days[w * per_window : (w + 1) * per_window],
            )
            cells.append(Cell(config=config(i), window=win))
    return cells


def series_for(cell: Cell) -> tuple[tuple[str, str], ...]:
    """Deterministic synthetic returns for a cell (all sessions after the first)."""
    seed = int(cell.config_id[:8], 16) ^ cell.window.ordinal
    rng = np.random.default_rng(seed)
    days = sessions(
        cell.window.session_count, date.fromisoformat(cell.window.start_session)
    )
    rets = rng.normal(0.0005, 0.01, len(days) - 1)
    return encode_returns(zip(days[1:], rets.tolist()))


def ok_executor(cell: Cell, _attempt_no: int) -> CellOutcome:
    """Executor that always succeeds deterministically."""
    return CellOutcome(status="ok", returns=series_for(cell))
