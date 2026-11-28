"""Legacy-backend scenarios pinned for #1357 (sweep, validate, tearsheet, reconcile).

``capture()`` runs the four commands on the **legacy** backend with the real
engines over a seeded in-memory feed (no DB) and returns every number as
``float.hex``. The literals in ``fixtures/legacy_golden_1357.json`` were
captured by running this module against origin/portfolio's code (before #1357
touched the routers); ``test_legacy_golden_1357.py`` requires today's code to
reproduce them bit for bit. Run ``python legacy_scenarios_1357.py`` with
``PYTHONPATH`` pointing at a backtest checkout to print the capture.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

N_SESSIONS = 90
SESSIONS = pd.bdate_range("2021-01-04", periods=N_SESSIONS)
UNIVERSE = ["AAA", "BBB"]


class SeededFeed:
    """Point-in-time feed: two seeded random walks."""

    def __init__(self) -> None:
        rng = np.random.default_rng(1357)
        rows = []
        for sym, drift in (("AAA", 0.0008), ("BBB", -0.0002)):
            price = 100.0
            for sess in SESSIONS:
                rows.append(
                    {
                        "symbol": sym,
                        "session": sess,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": 1e6,
                    }
                )
                price *= 1.0 + drift + float(rng.normal(0.0, 0.012))
        self._f = pd.DataFrame(rows)

    def history(self, symbols, end, lookback):
        f = self._f
        mask = f["symbol"].isin(symbols) & (f["session"] <= pd.Timestamp(end))
        return (
            f.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):
        s = self._f["session"]
        sel = s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))]
        return pd.DatetimeIndex(sorted(sel.unique()))


def _hex(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj.hex()
    if isinstance(obj, dict):
        return {k: _hex(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_hex(v) for v in obj]
    return obj


def _dump(model: Any) -> Any:
    return _hex(model.model_dump(mode="json"))


def config(**kw: Any):
    """The scenario config (legacy backend by default)."""
    from openbb_backtest.models import (  # pylint: disable=import-outside-toplevel
        BacktestConfig,
    )

    params: dict[str, Any] = {
        "strategy": "buy_and_hold",
        "universe": UNIVERSE,
        "start": date(2021, 1, 4),
        "end": SESSIONS[-1].date(),
        "benchmark": None,
    }
    params.update(kw)
    return BacktestConfig(**params)


def capture() -> dict[str, Any]:
    """Run the four legacy commands; return their results with hex floats."""
    # pylint: disable=import-outside-toplevel
    from openbb_backtest.routers import run_router as rr, validate_router as vr

    feed = SeededFeed()
    rr._build_feed = lambda cfg, provider: feed  # pylint: disable=protected-access
    vr._build_feed = lambda cfg, provider: feed  # pylint: disable=protected-access
    hold = {"symbols": UNIVERSE}
    out: dict[str, Any] = {}
    sweep = asyncio.run(
        rr.sweep(
            config(strategy="mean_reversion"),
            param_grid={
                "symbols": [UNIVERSE],
                "lookback": [5, 10],
                "entry_z": [0.5, 1.0],
            },
        )
    ).results
    out["sweep"] = _dump(sweep)
    for method in ("wfo", "cpcv"):
        rep = asyncio.run(
            vr.validate(config(), method=method, strategy_params=hold)
        ).results
        out[f"validate_{method}"] = _dump(rep)
    for engine in ("auto", "event"):
        sheet = asyncio.run(
            vr.tearsheet(config(), engine=engine, strategy_params=hold)
        ).results
        out[f"tearsheet_{engine}"] = _dump(sheet)
    out["reconcile"] = _dump(rr.reconcile(config(), strategy_params=hold).results)
    return out


if __name__ == "__main__":
    sys.stdout.write(json.dumps(capture(), indent=1, sort_keys=True) + "\n")
