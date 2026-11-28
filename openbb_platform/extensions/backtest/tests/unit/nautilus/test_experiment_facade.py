"""Nautilus experiments through the real worker entrypoint (#1357 T01).

``validate`` / ``sweep`` on ``backend="nautilus"`` run every trial cell through
the real facade path (allowlist resolution, one neutral export per window,
``WorkerClient``, the real worker entrypoint with the event-replay fake engine,
projection) into the append-only ledger. ``--fail-once`` on the fake worker
kills one attempt mid-request so the retry goes through the real client.
"""

# pylint: disable=import-outside-toplevel,redefined-outer-name

from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from openbb_backtest.adapters.nautilus import backend, experiment, export as ex, golden
from openbb_backtest.adapters.nautilus.client import WorkerClient, worker_env
from openbb_backtest.data.calendars import sessions_in_range
from openbb_backtest.models import BacktestConfig
from openbb_backtest.routers import run_router as rr, validate_router as vr
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV

START, END = "2024-01-02", "2024-03-28"
SESSIONS = [ts.date().isoformat() for ts in sessions_in_range(START, END, "XNYS")]
EXEC = {"fill_timing": "same_close"}
GRID = {
    "weights": [
        {"AAA": "0.5", "BBB": "0.5"},
        {"AAA": "0.8", "BBB": "0.2"},
        {"AAA": "0.2", "BBB": "0.7"},
        {"AAA": "0.7", "BBB": "0.7"},  # sums to 1.4: rejected by the allowlist
    ],
}
BASE = {"rebalance_every_sessions": 5, "execution": EXEC}


def _bars() -> dict[str, list[list[str]]]:
    rng = np.random.default_rng(2024)
    out: dict[str, list[list[str]]] = {}
    for sym, drift in (("AAA", 0.001), ("BBB", -0.0005)):
        price, rows = 50.0, []
        for _ in SESSIONS:
            close = price * (1 + drift + float(rng.normal(0, 0.015)))
            rows.append([f"{price:.2f}", f"{close:.2f}"])
            price = close
        out[sym] = rows
    return out


@pytest.fixture(scope="module")
def snap(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("snap") / "snap"
    golden._snapshot(
        {"bars": _bars()}, SESSIONS, path
    )  # pylint: disable=protected-access
    return path


def _options(tmp: Path, snap: Path, *extra: str, exports: list | None = None):
    root = tmp / "data"
    env = worker_env({**os.environ, DATA_ROOT_ENV: str(root)})
    command = [sys.executable, str(golden.FAKE_WORKER), *extra]
    opts = backend.NautilusOptions(
        client_factory=lambda: WorkerClient(command, timeout=120, env=env),
        execute=ex.snapshot_executor(snap),
        data_root=root,
        qualify=False,
        runtime="fake",
        runs_root=tmp / "runs",
    )
    if exports is None:
        return opts
    inner = backend._default_export(opts)  # pylint: disable=protected-access

    def counting(binding, config):
        exports.append((config.start.isoformat(), config.end.isoformat()))
        return inner(binding, config)

    return backend.NautilusOptions(**{**opts.__dict__, "export": counting})


def _config(
    strategy="target_weight_rebalance", universe=("AAA", "BBB")
) -> BacktestConfig:
    return BacktestConfig(
        strategy=strategy,
        universe=list(universe),
        start=START,
        end=END,
        initial_cash=Decimal("100000.00"),
        benchmark=None,
        backend="nautilus",
    )


@pytest.fixture
def no_legacy(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("legacy path reached for a nautilus request")

    for mod in (rr, vr):
        monkeypatch.setattr(mod, "_engine_for", boom)
        monkeypatch.setattr(mod, "_strategy_factory", boom)
        monkeypatch.setattr(mod, "_build_feed", boom)


def _validate(monkeypatch, opts, params=None, **kw):
    monkeypatch.setattr(vr, "_nautilus_options", lambda: opts)
    return asyncio.run(
        vr.validate(_config(), method="wfo", strategy_params=params or BASE, **kw)
    ).results


def _ledger(tmp: Path, experiment_id: str) -> list[dict]:
    path = tmp / "runs" / "experiments" / experiment_id / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


@pytest.fixture(scope="module")
def clean(tmp_path_factory, snap):
    """One clean validate over the grid (reference for the other runs)."""
    tmp = tmp_path_factory.mktemp("clean")
    mp = pytest.MonkeyPatch()
    try:
        report = _validate(mp, _options(tmp, snap), param_grid=GRID)
    finally:
        mp.undo()
    return tmp, report


def test_validate_grid_through_real_worker(clean, no_legacy):
    tmp, report = clean
    summary = report.experiment
    assert summary is not None
    assert summary.n_planned == 4 and summary.n_ok == 3 and summary.n_excluded == 1
    assert summary.n_trials_dsr == 4, "the rejected configuration was searched"
    assert summary.matrix_complete is False
    assert [e["reason"] for e in summary.exclusions] == ["admission_rejected"]
    assert summary.matrix_sha256 is not None
    assert report.pbo is None or 0.0 <= report.pbo <= 1.0
    assert report.verdict != "robust", "an incomplete matrix is capped"
    records = _ledger(tmp, summary.experiment_id)
    assert len(records) == 4
    rejected = [r for r in records if r["status"] == "excluded"]
    assert [(r["error_code"], r["attempt_no"]) for r in rejected] == [("admission", 1)]
    ok = [r for r in records if r["status"] == "ok"]
    assert all(len(r["returns"]) == len(SESSIONS) - 1 for r in ok)
    assert all(r["binding_sha256"] for r in ok)


def test_rerun_resumes_with_zero_new_attempts(clean, monkeypatch, snap):
    tmp, report = clean
    again = _validate(monkeypatch, _options(tmp, snap), param_grid=GRID)
    assert again.experiment == report.experiment
    assert len(_ledger(tmp, report.experiment.experiment_id)) == 4


def test_retry_counts_once_end_to_end(clean, tmp_path, monkeypatch, snap):
    _tmp, ref = clean
    state = tmp_path / "fail-once.flag"
    opts = _options(tmp_path, snap, "--fail-once", str(state))
    report = _validate(monkeypatch, opts, param_grid=GRID)
    assert state.exists(), "the fake worker never failed: retry path not exercised"
    records = _ledger(tmp_path, report.experiment.experiment_id)
    failed = [r for r in records if r["status"] == "failed"]
    assert [(r["error_code"], r["attempt_no"]) for r in failed] == [("process", 1)]
    retried = [r for r in records if r["trial_id"] == failed[0]["trial_id"]]
    assert [(r["status"], r["attempt_no"]) for r in retried] == [
        ("failed", 1),
        ("ok", 2),
    ]
    assert report.experiment.n_trials_dsr == ref.experiment.n_trials_dsr == 4
    assert report.experiment.matrix_sha256 == ref.experiment.matrix_sha256
    assert report.experiment.experiment_id == ref.experiment.experiment_id
    assert report.deflated_sharpe == ref.deflated_sharpe and report.pbo == ref.pbo


def test_split_spawns_and_resume_reproduce_matrix(clean, tmp_path, snap):
    _tmp, ref = clean
    opts = _options(tmp_path, snap)
    config = _config()
    sessions = experiment.session_calendar(config)
    folds = experiment.fold_plan(sessions, "wfo", "continuous")
    combos = experiment.expand_grid(GRID, BASE)

    def make_plan():
        return experiment.plan(
            config,
            combos,
            folds.windows,
            command="validate",
            method="wfo",
            policy="continuous",
            fold_params=folds.fold_params,
            options=opts,
        )

    the_plan = make_plan()
    ids = sorted(c.trial_id for c in the_plan.cells)
    first = experiment.run(the_plan, config, opts, only=ids[2:])
    assert first.appended == 2 and first.assembly.status == "incomplete"
    second = experiment.run(make_plan(), config, opts)
    assert second.appended == 2
    assert second.summary == ref.experiment
    report = experiment.validation_report(second, folds, sessions)
    assert report.deflated_sharpe == ref.deflated_sharpe
    assert experiment.run(make_plan(), config, opts).appended == 0


def test_per_fold_exports_once_per_window(tmp_path, snap):
    exports: list = []
    opts = _options(tmp_path, snap, exports=exports)
    config = _config()
    sessions = experiment.session_calendar(config)
    folds = experiment.fold_plan(sessions, "wfo", "per_fold")
    combos = experiment.expand_grid({"weights": GRID["weights"][:2]}, BASE)
    the_plan = experiment.plan(
        config,
        combos,
        folds.windows,
        command="validate",
        method="wfo",
        policy="per_fold",
        fold_params=folds.fold_params,
        options=opts,
    )
    out = experiment.run(the_plan, config, opts)
    n_windows = len(folds.windows)
    assert n_windows >= 2
    assert out.assembly.n_ok == 2 * n_windows
    # one base export of the full span + one per window, shared by both configs
    assert len(exports) == 1 + n_windows
    assert len(set(exports)) == len(exports)
    for w in folds.windows:
        idx = [sessions.index(s) for s in w.sessions]
        assert idx == list(range(idx[0], idx[-1] + 1)), "window is not contiguous"


def test_validate_without_grid_counts_external_trials(tmp_path, monkeypatch, snap):
    report = _validate(
        monkeypatch,
        _options(tmp_path, snap),
        {**BASE, "weights": GRID["weights"][0]},
        external_trials=99,
    )
    assert report.experiment.n_trials_dsr == 100
    assert report.pbo is None, "undefined PBO is None, never 0.0"
    # CODE-1: one ok config cannot estimate V, so N=100 cannot deflate the
    # Sharpe; DSR is undefined (None + reason), never the undeflated PSR.
    assert report.deflated_sharpe is None
    assert report.dsr_undefined_reason == "dsr_undefined_insufficient_variance"
    expected = "overfit" if report.oos_metrics.sharpe <= 0.0 else "fragile"
    assert report.verdict == expected
    # N == 1 keeps the PSR (benchmark 0): a number in [0, 1], no reason code.
    alone = _validate(
        monkeypatch,
        _options(tmp_path / "n1", snap),
        {**BASE, "weights": GRID["weights"][0]},
    )
    assert alone.experiment.n_trials_dsr == 1
    assert alone.dsr_undefined_reason is None
    assert alone.deflated_sharpe is not None and 0.0 <= alone.deflated_sharpe <= 1.0


def test_sweep_through_real_worker(tmp_path, monkeypatch, snap, clean, no_legacy):
    _tmp, ref = clean
    monkeypatch.setattr(rr, "_nautilus_options", lambda: _options(tmp_path, snap))
    grid = {**{k: [v] for k, v in BASE.items()}, **GRID}
    result = asyncio.run(rr.sweep(_config(), param_grid=grid)).results
    assert len(result.results) == 3
    assert result.experiment.n_trials_dsr == 4
    assert result.experiment.n_excluded == 1
    assert result.best in [p.params for p in result.results]
    assert result.best_metrics == max(
        (p.metrics for p in result.results), key=lambda m: m.sharpe
    )
    # same configurations over the same full-range window: same matrix
    assert result.experiment.matrix_sha256 == ref.experiment.matrix_sha256


class _BarsFeed:
    """Legacy point-in-time feed over the same synthetic closes."""

    def __init__(self) -> None:
        import pandas as pd

        rows = [
            {
                "symbol": sym,
                "session": pd.Timestamp(day),
                "open": float(o),
                "high": max(float(o), float(c)),
                "low": min(float(o), float(c)),
                "close": float(c),
                "volume": 1e6,
            }
            for sym, bars in _bars().items()
            for day, (o, c) in zip(SESSIONS, bars)
        ]
        self._f = pd.DataFrame(rows)

    def history(self, symbols, end, lookback):
        import pandas as pd

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
        import pandas as pd

        s = self._f["session"]
        sel = s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))]
        return pd.DatetimeIndex(sorted(sel.unique()))


HOLD = {"symbols": ["AAA"], "execution": EXEC}


def test_tearsheet_nautilus_through_real_worker(tmp_path, monkeypatch, snap, no_legacy):
    monkeypatch.setattr(vr, "_nautilus_options", lambda: _options(tmp_path, snap))
    sheet = asyncio.run(
        vr.tearsheet(_config("buy_and_hold", ["AAA"]), strategy_params=HOLD)
    ).results
    direct = rr.execute_run(
        _config("buy_and_hold", ["AAA"]),
        strategy_params=HOLD,
        nautilus=_options(tmp_path, snap),
    )
    from openbb_backtest.analytics import build_tearsheet, to_returns

    want = build_tearsheet(to_returns(direct.equity_curve), None, direct.trades, 252)
    assert sheet.metrics == want.metrics
    assert sheet.metrics.volatility > 0.0


def test_reconcile_nautilus_is_diagnostic(tmp_path, monkeypatch, snap):
    monkeypatch.setattr(rr, "_nautilus_options", lambda: _options(tmp_path, snap))
    monkeypatch.setattr(rr, "_build_feed", lambda config, provider: _BarsFeed())
    report = rr.reconcile(
        _config("buy_and_hold", ["AAA"]), strategy_params=HOLD
    ).results
    assert report.diagnostic_only is True
    assert report.reference_engine == "nautilus"
    assert report.candidate_engine == "event"
    assert report.modeled_differences
    assert report.max_divergence > 0.0, "whole shares vs fractional must differ"


SMALL = Path(__file__).parents[1] / "validation" / "fixtures" / "experiment_small.json"
SMALL_EXPERIMENT_ID = "b39311fb551569931d303f94a25836598d8462b81ccf96ee9e6b7fe57ac1c8af"
SMALL_MATRIX_SHA = "aeb710591c644eea1cfccd4d431cd42de4d54cd9c5d4ff7f0fae050f36191c11"


def test_experiment_run_cli_then_resume(tmp_path, capsys):
    from openbb_backtest.validation import experiment as cli

    argv = ["run", "--spec", str(SMALL), "--runtime", "fake", "--format", "json"]
    argv += ["--runs-root", str(tmp_path / "runs")]
    rows = []
    for _ in range(2):
        assert cli.main(argv) == 0
        rows.append(json.loads(capsys.readouterr().out))
    first, second = rows
    assert first["experiment_id"] == SMALL_EXPERIMENT_ID
    assert first["matrix_sha256"] == SMALL_MATRIX_SHA
    assert (first["n_trials_dsr"], first["n_ok"], first["n_excluded"]) == (4, 3, 1)
    assert first["matrix_complete"] is False and first["new_attempts"] == 4
    assert second["new_attempts"] == 0
    assert {k: v for k, v in second.items() if k != "new_attempts"} == {
        k: v for k, v in first.items() if k != "new_attempts"
    }


def test_experiment_run_cli_bad_spec_exits_2(tmp_path, capsys):
    from openbb_backtest.validation import experiment as cli

    bad = tmp_path / "bad.json"
    bad.write_text("{}", "utf-8")
    assert cli.main(["run", "--spec", str(bad), "--runtime", "fake"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize(
    "exc,status,code",
    [
        ("process:worker could not be started", "failed", "spawn"),
        ("process:worker exceeded its deadline and was killed", "failed", "timeout"),
        ("process:worker exited without a response", "failed", "process"),
        ("schema:bad_request: invalid fields", "excluded", "admission"),
        ("module_origin:code drift", "failed", "module_origin"),
        ("egress:endpoint_field", "failed", "egress"),
    ],
)
def test_classify_protocol_errors(exc, status, code):
    from openbb_backtest.validation.trials import RETRYABLE_CODES
    from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError

    layer, message = exc.split(":", 1)
    out = experiment.classify(ProtocolError(ErrorCode(layer), message))
    assert (out.status, out.error_code) == (status, code)
    assert (code in RETRYABLE_CODES) is (code in {"spawn", "timeout", "process"})


def test_classify_unsupported_semantics_is_excluded():
    from openbb_backtest.errors import UnsupportedSemanticsError

    out = experiment.classify(
        UnsupportedSemanticsError("x", reason="universe_mismatch")
    )
    assert (out.status, out.reason) == ("excluded", "unsupported_semantics")
