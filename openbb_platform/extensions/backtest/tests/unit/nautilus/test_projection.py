"""Normalised projection of a worker ``run`` body (#1356 T02).

The canned body is built from the hand-computed #1355 oracle literals
(``buy_and_hold_oracle.json``), never from the engine under test. The
end-to-end case runs the real facade path (``execute_run``) against the real
worker entrypoint with the fake engine seam.
"""

# ruff: noqa: D103
# pylint: disable=import-outside-toplevel,redefined-outer-name

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from openbb_backtest.adapters.nautilus import (
    backend,
    export as ex,
    projection,
    strategies,
)
from openbb_backtest.errors import BackendUnavailableError
from openbb_backtest.models import BacktestConfig
from openbb_backtest.routers import run_router as rr
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.reviewed import registry

FIX = Path(__file__).parent / "fixtures"
FAKE_RUN = str(FIX / "fake_run_worker.py")
ORACLE = json.loads((FIX / "buy_and_hold_oracle.json").read_text(encoding="utf-8"))
SAME_CLOSE = {"fill_timing": "same_close"}


def _config(**kw) -> BacktestConfig:
    params = dict(
        strategy="buy_and_hold",
        universe=[ORACLE["symbol"]],
        start=ORACLE["sessions"][0],
        end=ORACLE["sessions"][-1],
        initial_cash=Decimal(ORACLE["initial_cash"]),
        benchmark=None,
        backend="nautilus",
    )
    params.update(kw)
    return BacktestConfig(**params)


def _binding(params=None, execution=None):
    return strategies.resolve_reviewed(
        "buy_and_hold",
        None,
        params or {"symbols": [ORACLE["symbol"]]},
        execution or SAME_CLOSE,
    )


def _body(binding=None, **override):
    """The worker ``run`` body for the oracle, written from its literals."""
    binding = binding or _binding()
    exp = ORACLE["expected"]
    body = {
        "dataset_id": "d" * 64,
        "strategy": "buy_and_hold",
        "venue": "SIM",
        "symbol": ORACLE["symbol"],
        "engine": {"name": "fake-fill-at-close", "version": "0"},
        "fixed_precision": 9,
        "bars_sha256": "b" * 64,
        "sessions": ORACLE["sessions"],
        "starting_cash": ORACLE["initial_cash"],
        "final_equity": exp["final_equity"],
        "quantity": exp["quantity"],
        "cash": exp["cash"],
        "equity": exp["equity"],
        "fills": [
            {
                "session": ORACLE["sessions"][0],
                "side": "buy",
                "quantity": 100,
                "price": "100.00",
                "commission": "0.00",
            }
        ],
        "binding": registry.run_binding(binding, "d" * 64, "0"),
    }
    body.update(override)
    return body


def _project(body, binding=None, config=None):
    return projection.to_backtest_result(
        body,
        config=config or _config(),
        binding=binding or _binding(),
        backend_source="param",
        runtime="fake",
    )


def test_projection_hand_case_buy_and_hold():
    res = _project(_body())
    exp = ORACLE["expected"]
    assert res.engine_used == "nautilus"
    assert [p.equity for p in res.equity_curve] == [Decimal(e) for e in exp["equity"]]
    assert all(p.equity.as_tuple().exponent == -2 for p in res.equity_curve)
    assert [p.cash for p in res.equity_curve] == [Decimal("0.00")] * 5
    assert [p.date for p in res.equity_curve] == [
        datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        for s in ORACLE["sessions"]
    ]
    assert [p.exposure for p in res.equity_curve] == [1.0] * 5
    (trade,) = res.trades
    assert (trade.symbol, trade.side, trade.quantity) == ("BHX", "buy", Decimal(100))
    assert (trade.price, trade.commission, trade.slippage) == (
        Decimal("100.00"),
        Decimal("0.00"),
        Decimal(0),
    )
    assert trade.timestamp == res.equity_curve[0].date


def test_projection_uses_shared_metrics(monkeypatch):
    from openbb_backtest.engine import vectorized

    seen = []
    real = vectorized._metrics_from_returns  # pylint: disable=protected-access

    def spy(equity, returns, turnover_series, **kw):
        seen.append((equity, returns, turnover_series))
        return real(equity, returns, turnover_series, **kw)

    monkeypatch.setattr(vectorized, "_metrics_from_returns", spy)
    res = _project(_body())
    (args,) = seen
    equity = [float(e) for e in ORACLE["expected"]["equity"]]
    np.testing.assert_array_equal(args[0], equity)
    assert args[1][0] == 0.0  # first session: starting cash -> 10000.00
    assert args[1][1] == pytest.approx(10150 / 10000 - 1, abs=1e-15)
    np.testing.assert_array_equal(args[2], [1.0, 0, 0, 0, 0])
    assert res.metrics == real(*args)


@pytest.mark.parametrize(
    "override",
    [
        {
            "equity": ORACLE["expected"]["equity"][:-1],
            "final_equity": ORACLE["expected"]["equity"][-2],
        },
        {"cash": "1.00"},
        {"quantity": 99},
        {"sessions": [], "equity": []},
        {"final_equity": "10299.99"},
        {"fills": [{**_body()["fills"][0], "session": "2024-03-11"}]},
    ],
    ids=["length", "cash", "quantity", "empty", "final", "fill_session"],
)
def test_projection_rejects_inconsistent_body(override):
    with pytest.raises(BackendUnavailableError) as err:
        _project(_body(**override))
    assert err.value.reason == "inconsistent_result"


def test_provenance_binds_all_hashes():
    base = _binding()
    prov = _project(_body(base), base).provenance
    pin = registry.pin_for("buy_and_hold", "1.0.0")
    assert (prov.backend, prov.backend_source, prov.engine) == (
        "nautilus",
        "param",
        "nautilus",
    )
    assert prov.strategy_review == "reviewed"
    assert (prov.code_sha256, prov.spec_sha256) == (pin.code_sha256, pin.spec_sha256)
    assert prov.params_sha256 == base.params_sha256
    assert prov.execution_sha256 == base.execution_sha256
    assert prov.binding_sha256 == _body(base)["binding"]["binding_sha256"]
    assert (prov.dataset_id, prov.bars_sha256) == ("d" * 64, "b" * 64)
    assert (prov.engine_name, prov.engine_version) == ("fake-fill-at-close", "0")
    assert prov.execution["fill_timing"] == "same_close"

    other_params = _binding({"symbols": ["BHX", "ZZZ"]})
    other_exec = _binding(execution={"fill_timing": "next_open"})
    assert other_params.params_sha256 != base.params_sha256
    assert other_exec.execution_sha256 != base.execution_sha256
    # a body bound to different params or execution is refused
    for other in (other_params, other_exec):
        with pytest.raises(BackendUnavailableError) as err:
            _project(_body(other), base)
        assert err.value.reason == "binding_mismatch"


# ---- end to end: real facade + real worker entrypoint + fake engine ------


def _snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "snap"
    snap.mkdir()
    rows = [
        {
            "symbol": ORACLE["symbol"],
            "date": d,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1000,
            "interval_type": "1d",
            "adjustment_type": "unadjusted",
            "is_filled": 0,
            "is_valid": 1,
        }
        for d, c in zip(ORACLE["sessions"], ORACLE["closes"])
    ]
    (snap / "equity_historical.json").write_text(json.dumps(rows))
    (snap / "calendar_splits.json").write_text("[]")
    (snap / "calendar_dividend.json").write_text("[]")
    return snap


def _options(tmp_path: Path) -> backend.NautilusOptions:
    from openbb_backtest.adapters.nautilus.client import WorkerClient, worker_env

    root = tmp_path / "data"
    env = worker_env({**os.environ, DATA_ROOT_ENV: str(root)})
    return backend.NautilusOptions(
        client_factory=lambda: WorkerClient(
            [sys.executable, FAKE_RUN], timeout=120, env=env
        ),
        execute=ex.snapshot_executor(_snapshot(tmp_path)),
        data_root=root,
        qualify=False,
        runtime="fake",
    )


def test_execute_run_end_to_end_matches_oracle(tmp_path, monkeypatch):
    def _no_legacy(name):
        raise AssertionError("legacy engine called")

    monkeypatch.setattr(rr, "_engine_for", _no_legacy)
    res = rr.execute_run(
        _config(),
        strategy_params={"execution": SAME_CLOSE},
        nautilus=_options(tmp_path),
    )
    exp = ORACLE["expected"]
    assert [str(p.equity) for p in res.equity_curve] == exp["equity"]
    assert str(res.equity_curve[-1].cash) == exp["cash"]
    assert res.trades[0].quantity == Decimal(exp["quantity"])
    assert res.provenance.backend_source == "config"
    assert res.provenance.runtime == "fake"
    assert res.provenance.qualified is False
    assert res.provenance.spec_sha256 == registry.pin_for(
        "buy_and_hold", "1.0.0"
    ).spec_sha256


def test_nautilus_result_positions_sanitised(tmp_path):
    raw = _project(_body())
    assert len(raw.positions) == 1  # the projection reports the final holding
    res = rr.execute_run(
        _config(),
        strategy_params={"execution": SAME_CLOSE},
        nautilus=_options(tmp_path),
    )
    assert res.positions == []


def test_golden_cli_fake_runtime_matches_literals(tmp_path, capsys):
    from openbb_backtest.adapters.nautilus import golden

    cmd = json.dumps([sys.executable, FAKE_RUN])
    args = ["--case-file", str(FIX / "buy_and_hold_oracle.json")]
    args += ["--runtime", "fake", "--worker-command-json", cmd, "--format", "json"]
    assert golden.main(args) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["passed"] is True and rep["qualified"] is False
    bad = {**ORACLE, "expected": {**ORACLE["expected"], "cash": "0.01"}}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), "utf-8")
    args[1] = str(path)
    assert golden.main(args) == 2
