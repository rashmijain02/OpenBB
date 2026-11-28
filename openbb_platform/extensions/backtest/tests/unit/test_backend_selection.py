"""Explicit backend selection behind the existing facade (#1356 T02).

Contracts pinned here: the ``run`` signature and result keys are unchanged
apart from the trailing ``backend`` parameter and the optional ``provenance``
field; the default backend is ``legacy`` and is recorded as the default; a
``nautilus`` request never falls back to the legacy engine; and every failure
is a typed ``BacktestError`` subclass.
"""

# ruff: noqa: D103
# pylint: disable=import-outside-toplevel,protected-access,redefined-outer-name

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("openbb_nautilus_worker")

from openbb_backtest.errors import (  # noqa: E402
    BackendSelectionError,
    BackendUnavailableError,
    BacktestError,
    UnsupportedSemanticsError,
)
from openbb_backtest.models import BacktestConfig  # noqa: E402
from openbb_backtest.routers import (
    run_router as rr,  # noqa: E402
    validate_router as vr,  # noqa: E402
)
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[5]
OLD_RESULT_KEYS = {
    "equity_curve",
    "trades",
    "positions",
    "metrics",
    "engine_used",
    "config",
}
SESSIONS = pd.bdate_range("2021-01-04", periods=6)


def _config(**kw) -> BacktestConfig:
    params = dict(
        strategy="buy_and_hold",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 11),
        benchmark=None,
    )
    params.update(kw)
    return BacktestConfig(**params)


class _Feed:
    """In-memory point-in-time feed: AAA rises 1%/day, BBB falls 1%/day."""

    def __init__(self) -> None:
        rows = []
        for sym, step in (("AAA", 1.01), ("BBB", 0.99)):
            price = 100.0
            for sess in SESSIONS:
                rows.append(
                    dict(symbol=sym, session=sess, open=price, high=price)
                    | dict(low=price, close=price, volume=1e6)
                )
                price *= step
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


@pytest.fixture
def real_legacy(monkeypatch):
    """The real legacy engines on an in-memory feed (no DB)."""
    monkeypatch.setattr(rr, "_build_feed", lambda config, provider: _Feed())


@pytest.fixture
def legacy_spy(monkeypatch):
    """Fail loudly if anything reaches the legacy engine or plugin factory."""
    calls: list[str] = []

    def _engine_for(name):
        calls.append(f"engine:{name}")
        raise AssertionError("legacy engine called for a nautilus request")

    def _factory(name):
        calls.append(f"factory:{name}")
        raise AssertionError("legacy strategy factory called")

    for mod in (rr, vr):
        monkeypatch.setattr(mod, "_engine_for", _engine_for)
        monkeypatch.setattr(mod, "_strategy_factory", _factory)
        monkeypatch.setattr(mod, "_build_feed", lambda *a: calls.append("feed"))
    return calls


def _run(config, **kw):
    if config.strategy == "buy_and_hold":
        kw.setdefault("strategy_params", {"symbols": list(config.universe)})
    return asyncio.run(rr.run(config, **kw)).results


# ---- C-a: signature and result shape -------------------------------------


def test_run_signature_backward_compatible():
    params = list(inspect.signature(rr.run).parameters.values())
    assert [(p.name, p.default) for p in params[:4]] == [
        ("config", inspect.Parameter.empty),
        ("engine", "auto"),
        ("strategy_params", None),
        ("provider", None),
    ]
    assert params[-1].name == "backend" and params[-1].default is None
    assert len(params) == 5


def test_legacy_result_keys_superset(real_legacy):
    res = _run(_config(), engine="vector")
    dumped = res.model_dump()
    assert set(dumped) == OLD_RESULT_KEYS | {"provenance"}
    assert res.positions == []
    assert res.engine_used == "vectorized"
    point = res.equity_curve[-1]
    assert isinstance(point.equity, Decimal) and isinstance(point.cash, Decimal)
    assert point.equity.as_tuple().exponent == -2
    assert set(dumped["config"]) - {"backend", "strategy_version"} == set(
        BacktestConfig.model_fields
    ) - {"backend", "strategy_version"}


def test_default_backend_legacy_recorded_as_default(real_legacy):
    res = _run(_config())
    prov = res.provenance
    assert (prov.backend, prov.backend_source) == ("legacy", "default")
    assert prov.engine == "vectorized"
    assert prov.strategy_review == "unreviewed"
    assert prov.spec_sha256 is None and prov.dataset_id is None


def test_backend_source_records_param_and_config(real_legacy):
    by_config = _run(_config(backend="legacy")).provenance
    assert (by_config.backend, by_config.backend_source) == ("legacy", "config")
    by_param = _run(_config(backend="nautilus"), backend="legacy").provenance
    assert (by_param.backend, by_param.backend_source) == ("legacy", "param")


def test_engine_precedence_unchanged_under_default_backend(real_legacy):
    assert _run(_config(engine="event")).engine_used == "event"
    assert _run(_config(engine="event"), engine="vector").engine_used == "vectorized"


def test_default_backend_setting_is_legacy():
    from openbb_backtest.settings import BacktestSettings

    assert BacktestSettings().default_backend == "legacy"


# ---- selection errors ----------------------------------------------------


def test_unknown_backend_rejected(legacy_spy):
    with pytest.raises(BackendSelectionError, match="zipline"):
        _run(_config(), backend="zipline")
    with pytest.raises(ValueError):
        _config(backend="zipline")
    assert not legacy_spy


@pytest.mark.parametrize(
    "kw,cfg",
    [({"engine": "vector"}, {}), ({}, {"engine": "vectorized"})],
)
def test_nautilus_with_vector_engine_rejected(legacy_spy, kw, cfg):
    with pytest.raises(BackendSelectionError, match="vector"):
        _run(_config(**cfg), backend="nautilus", **kw)
    assert not legacy_spy


def test_nautilus_unavailable_never_calls_legacy(legacy_spy, monkeypatch):
    from openbb_backtest import settings

    monkeypatch.setattr(settings.DEFAULT_SETTINGS, "nautilus_runtime", None)
    with pytest.raises(BackendUnavailableError) as err:
        _run(_config(universe=["AAA"]), backend="nautilus")
    assert err.value.reason == "worker_not_configured"
    assert isinstance(err.value, BacktestError)
    assert not legacy_spy


@pytest.mark.parametrize("name", ["momentum_12_1", "techtrade_confluence"])
def test_nautilus_unreviewed_strategy_rejected(legacy_spy, name):
    with pytest.raises(UnsupportedSemanticsError) as err:
        _run(_config(strategy=name, backend="nautilus"))
    assert err.value.reason == "unknown_strategy"
    assert err.value.code == "schema"
    assert not legacy_spy


def test_legacy_rejects_reviewed_only_strategy(legacy_spy):
    cfg = _config(strategy="target_weight_rebalance")
    with pytest.raises(UnsupportedSemanticsError) as err:
        _run(cfg)
    assert err.value.reason == "reviewed_only_strategy"
    assert not legacy_spy


# ---- #1357: sweep / validate / tearsheet / reconcile route to nautilus ----

TWR = "target_weight_rebalance"
TWR_BASE = {"rebalance_every_sessions": 5, "execution": {"fill_timing": "same_close"}}
TWR_GRID = {
    "weights": [
        {"AAA": "0.5", "BBB": "0.5"},
        {"AAA": "0.8", "BBB": "0.2"},
        {"AAA": "0.3", "BBB": "0.6"},
    ]
}


def _twr_config(**kw) -> BacktestConfig:
    params = dict(
        strategy=TWR,
        start=date(2024, 1, 2),
        end=date(2024, 4, 30),
        initial_cash=Decimal("100000.00"),
        backend="nautilus",
    )
    params.update(kw)
    return _config(**params)


@pytest.fixture
def synthetic_cells(monkeypatch, tmp_path):
    """Real plan / dispatch / assemble / statistics; cells return seeded series.

    Only the worker call is replaced: every cell returns a deterministic
    series over its own window's calendar sessions (seeded by config id), so
    configurations differ and fold structure is visible.
    """
    from openbb_backtest.adapters.nautilus import backend, experiment
    from openbb_backtest.validation.matrix import encode_returns
    from openbb_backtest.validation.trials import CellOutcome

    windows: list[tuple[str, str]] = []

    def cell_executor(the_plan, config, _options):
        calendar = experiment.session_calendar(config)

        def execute(cell, _attempt_no):
            if cell.config_id in the_plan.rejected:
                return CellOutcome(
                    status="excluded",
                    error_code="admission",
                    reason="admission_rejected",
                )
            windows.append((cell.window.start_session, cell.window.end_session))
            first = calendar.index(cell.window.start_session)
            last = calendar.index(cell.window.end_session)
            days = calendar[first : last + 1]
            rng = np.random.default_rng(int(cell.config_id[:8], 16))
            rets = rng.normal(0.0004, 0.01, len(calendar))[first + 1 : last + 1]
            return CellOutcome(
                status="ok", returns=encode_returns(zip(days[1:], rets.tolist()))
            )

        return execute

    monkeypatch.setattr(experiment, "cell_executor", cell_executor)
    opts = backend.NautilusOptions(
        export=lambda binding, config: "d" * 64,
        runtime="fake",
        runs_root=tmp_path / "runs",
    )
    for mod in (rr, vr):
        monkeypatch.setattr(mod, "_nautilus_options", lambda: opts)
    return windows


def _validate_nautilus(method="wfo", **kw):
    kw.setdefault("strategy_params", TWR_BASE)
    return asyncio.run(vr.validate(_twr_config(), method=method, **kw)).results


def test_sweep_routes_nautilus_never_calls_legacy(legacy_spy, synthetic_cells):
    grid = {**{k: [v] for k, v in TWR_BASE.items()}, **TWR_GRID}
    result = asyncio.run(rr.sweep(_twr_config(), param_grid=grid)).results
    assert not legacy_spy
    assert len(result.results) == 3
    assert result.experiment is not None and result.experiment.n_trials_dsr == 3
    assert synthetic_cells, "no cell reached the (nautilus) executor"


def test_validate_nautilus_n_is_configs_not_folds(legacy_spy, synthetic_cells):
    report = _validate_nautilus(param_grid=TWR_GRID)
    assert not legacy_spy
    assert len(report.folds) != 3, "fixture must separate folds from configs"
    assert report.experiment.n_trials_dsr == 3
    with_external = _validate_nautilus(param_grid=TWR_GRID, external_trials=7)
    assert with_external.experiment.n_trials_dsr == 10
    assert with_external.deflated_sharpe < report.deflated_sharpe


def test_validate_nautilus_uses_configs_as_pbo_columns(legacy_spy, synthetic_cells):
    from openbb_backtest.adapters.nautilus import experiment
    from openbb_backtest.validation import pbo_detail
    from openbb_backtest.validation.matrix import assemble
    from openbb_backtest.validation.trials import TrialLedger

    report = _validate_nautilus(param_grid=TWR_GRID)
    exp = report.experiment
    opts = rr._nautilus_options()  # pylint: disable=protected-access
    ledger = TrialLedger.for_experiment(opts.runs_root, exp.experiment_id)
    matrix = assemble(ledger.planned(), ledger.records()).matrix
    sessions, cols, mat = matrix.wide()
    assert len(cols) == 3
    calendar = experiment.session_calendar(_twr_config())
    oos_days = {
        calendar[j]
        for idx, _p in experiment.fold_plan(calendar, "wfo", "continuous").folds
        for j in idx
    }
    rows = [i for i, s in enumerate(sessions) if s in oos_days]
    oos = mat[rows, :]
    assert report.pbo == pytest.approx(pbo_detail(oos, statistic="sharpe").pbo)
    # folds-as-columns (the legacy F4 reading) differs on this fixture
    best = int(np.argmax(oos.mean(0) / oos.std(0, ddof=1)))
    half = len(rows) // 2
    folds_pbo = pbo_detail(
        np.column_stack([oos[:half, best], oos[half : 2 * half, best]]),
        statistic="sharpe",
    ).pbo
    assert folds_pbo != pytest.approx(report.pbo)


def test_validate_nautilus_cpcv_runs_atomic_groups():
    from openbb_backtest.adapters.nautilus import experiment

    sessions = [f"2024-01-{d:02d}" for d in range(1, 31)]
    plan = experiment.fold_plan(sessions, "cpcv", "per_fold")
    assert len(plan.windows) == 6, "CPCV dedupes to n_groups windows, not C(N,k)"
    covered = []
    for w in plan.windows:
        idx = [sessions.index(s) for s in w.sessions]
        assert idx == list(range(idx[0], idx[-1] + 1)), "non-contiguous span (F2)"
        covered.extend(idx)
    assert covered == list(range(len(sessions)))


def test_validate_nautilus_path_id_from_cpcv_paths(legacy_spy, synthetic_cells):
    from openbb_backtest.validation import cpcv_paths

    report = _validate_nautilus(method="cpcv", param_grid=TWR_GRID)
    paths = cpcv_paths(6, 2)
    assert [f.path_id for f in report.folds] == [
        p for p, cells in enumerate(paths) for _cell in cells
    ]
    assert not legacy_spy


def test_validate_nautilus_without_grid_pbo_none(legacy_spy, synthetic_cells):
    params = {**TWR_BASE, "weights": TWR_GRID["weights"][0]}
    report = _validate_nautilus(strategy_params=params, external_trials=4)
    assert report.pbo is None
    assert report.experiment.n_trials_dsr == 5
    assert report.verdict != "robust"


def test_legacy_validate_rejects_nautilus_only_args(legacy_spy):
    with pytest.raises(ValueError, match="nautilus"):
        asyncio.run(vr.validate(_config(), param_grid={"x": [1]}))
    with pytest.raises(ValueError, match="nautilus"):
        asyncio.run(vr.validate(_config(), external_trials=3))
    assert not legacy_spy


def test_reconcile_nautilus_strict_rejected(legacy_spy):
    with pytest.raises(UnsupportedSemanticsError) as err:
        rr.reconcile(_config(backend="nautilus"), strict=True)
    assert err.value.reason == "reconcile_not_a_gate"
    assert not legacy_spy


def test_tearsheet_nautilus_uses_execute_run(legacy_spy, monkeypatch):
    seen = {}

    def fake_execute_run(config, **kw):
        seen.update(kw, backend=config.backend)
        raise BackendUnavailableError("stop here", reason="probe", code="config")

    monkeypatch.setattr(rr, "execute_run", fake_execute_run)
    with pytest.raises(BackendUnavailableError, match="stop here"):
        asyncio.run(vr.tearsheet(_config(backend="nautilus"), engine="event"))
    assert seen["backend"] == "nautilus" and seen["engine"] == "event"
    assert not legacy_spy


def test_reject_helper_deleted():
    from openbb_backtest import router_helpers

    assert not hasattr(router_helpers, "reject_nautilus_until_p17")


# ---- worker error mapping ------------------------------------------------


@pytest.mark.parametrize(
    "exc,kind,reason,code",
    [
        (
            ProtocolError(ErrorCode.CONFIG, "execution_not_executable: not yet"),
            UnsupportedSemanticsError,
            "execution_not_executable",
            "config",
        ),
        (
            ProtocolError(ErrorCode.SCHEMA, "corporate_actions_present: split"),
            UnsupportedSemanticsError,
            "corporate_actions_present",
            "schema",
        ),
        (
            ProtocolError(ErrorCode.MODULE_ORIGIN, "strategy_code_drift: differs"),
            BackendUnavailableError,
            "strategy_code_drift",
            "module_origin",
        ),
        (
            ProtocolError(ErrorCode.PROCESS, "worker exited without a response"),
            BackendUnavailableError,
            None,
            "process",
        ),
    ],
)
def test_worker_error_maps_to_typed_error(legacy_spy, exc, kind, reason, code):
    from openbb_backtest.adapters.nautilus import backend

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def run(self, body):
            raise exc

    opts = backend.NautilusOptions(
        client_factory=_Client,
        export=lambda binding, config: "0" * 64,
        qualify=False,
        runtime="fake",
    )
    with pytest.raises(kind) as err:
        rr.execute_run(
            _config(universe=["AAA"]),
            backend="nautilus",
            strategy_params={"execution": {"fill_timing": "same_close"}},
            nautilus=opts,
        )
    assert (err.value.reason, err.value.code) == (reason, code)
    assert not legacy_spy


# ---- C-g: notebook keyword calls still bind ------------------------------

NOTEBOOKS = [
    *(f"notebooks/portfolio/{n}" for n in ("06", "07", "08")),
    *(f"notebooks/portfolio_yfinance/{n}" for n in ("06", "07", "08")),
    *(f"notebooks/techtrade/{n}" for n in ("01", "04", "05")),
]
TARGETS = {"run": rr.run, "sweep": rr.sweep, "reconcile": rr.reconcile}
TARGETS |= {"validate": vr.validate, "tearsheet": vr.tearsheet}


def _backtest_calls():
    for stem in NOTEBOOKS:
        folder, prefix = stem.rsplit("/", 1)
        for path in sorted((REPO_ROOT / folder).glob(prefix + "*.ipynb")):
            cells = json.loads(path.read_text("utf-8"))["cells"]
            for cell in cells:
                if cell["cell_type"] != "code":
                    continue
                src = "".join(cell["source"])
                src = "\n".join(
                    "" if line.lstrip().startswith(("%", "!")) else line
                    for line in src.splitlines()
                )
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    fn = getattr(node, "func", None)
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(fn, ast.Attribute)
                        and fn.attr in TARGETS
                        and isinstance(fn.value, ast.Attribute)
                        and fn.value.attr == "backtest"
                    ):
                        yield path.name, fn.attr, node


def test_notebook_backtest_calls_still_bind():
    seen = 0
    for name, attr, node in _backtest_calls():
        sig = inspect.signature(TARGETS[attr])
        kwargs = {k.arg: None for k in node.keywords if k.arg}
        args = [None] * len(node.args)
        sig.bind(*args, **kwargs)  # raises TypeError on a broken call site
        assert "backend" not in kwargs, (name, attr)
        seen += 1
    assert seen >= 3, "no obb.backtest.* calls found: the scan is broken"


def test_reviewed_only_typed_error_in_fresh_process_without_worker_path():
    """A fresh process lacking the worker dir on PYTHONPATH gets the typed error."""
    import os
    import subprocess
    import sys

    import openbb_backtest

    backtest_root = str(Path(openbb_backtest.__file__).resolve().parents[1])
    code = "\n".join(
        [
            "import asyncio, sys",
            "from datetime import date",
            "assert not any('nautilus_worker' in p for p in sys.path), sys.path",
            "from openbb_backtest.errors import UnsupportedSemanticsError",
            "from openbb_backtest.models import BacktestConfig",
            "from openbb_backtest.routers import run_router as rr",
            "cfg = BacktestConfig(strategy='target_weight_rebalance',",
            "    universe=['AAA'], start=date(2024, 1, 2), end=date(2024, 3, 1))",
            "try:",
            "    asyncio.run(rr.run(cfg))",
            "except UnsupportedSemanticsError as exc:",
            "    print('typed', exc.reason)",
            "except BaseException as exc:",
            "    print('other', type(exc).__name__)",
        ]
    )
    env = dict(os.environ, PYTHONPATH=backtest_root, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip() == "typed reviewed_only_strategy", out.stdout + out.stderr
