"""``run`` op: buy-and-hold against the oracle dataset (#1355 T03).

The engine seam is a fake that fills the strategy's order at the first close
(what a market order on bar data does in Nautilus). Sizing, data loading,
accounting and the report are the real :mod:`runs` code; the expected values
come from the hand-computed oracle JSON, never from the code under test. The
real-engine run is ``requires_nautilus`` (worker venv, LIVE T03-L).
"""

# ruff: noqa: D103

from __future__ import annotations

from decimal import Decimal

import pytest
from openbb_nautilus_worker import guards, runs
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError


def fill_at_first_close(spec: runs.RunSpec) -> runs.EngineResult:
    return runs.EngineResult(
        name="fake-fill-at-close",
        version="0",
        fills=[
            runs.Fill(
                session=spec.sessions[0],
                quantity=spec.order.quantity,
                price=spec.closes[0],
                commission=Decimal(0),
            )
        ],
    )


def _setup(tmp_path, make_dataset):
    ds_id = make_dataset(tmp_path / "datasets")
    env = {DATA_ROOT_ENV: str(tmp_path)}
    body = {"dataset_id": ds_id, "strategy": "buy_and_hold"}
    return ds_id, env, body


def _run(body, env, engine=fill_at_first_close, oracle=None):
    if oracle is not None:
        body = {**body, "starting_cash": oracle["initial_cash"]}
    return runs.run(body, env=env, engine=engine, fixed_precision=9)


def test_buy_and_hold_fake_engine_matches_oracle(tmp_path, make_dataset, oracle):
    ds_id, env, body = _setup(tmp_path, make_dataset)
    rep = _run(body, env, oracle=oracle)
    exp = oracle["expected"]
    assert rep["dataset_id"] == ds_id
    assert rep["symbol"] == oracle["symbol"]
    assert rep["quantity"] == exp["quantity"]
    assert rep["cash"] == exp["cash"]
    assert rep["equity"] == exp["equity"]
    assert rep["final_equity"] == exp["final_equity"]
    assert rep["sessions"] == oracle["sessions"]
    assert rep["engine"] == {"name": "fake-fill-at-close", "version": "0"}
    assert rep["fixed_precision"] == 9 and rep["venue"] == "SIM"
    assert len(rep["bars_sha256"]) == 64


def test_engine_cash_disagreement_is_process(tmp_path, make_dataset, oracle):
    _, env, body = _setup(tmp_path, make_dataset)

    def lying(spec):
        res = fill_at_first_close(spec)
        return runs.EngineResult(res.name, res.version, res.fills, Decimal("5.00"))

    with pytest.raises(ProtocolError) as info:
        _run(body, env, lying, oracle)
    assert info.value.code is ErrorCode.PROCESS


def test_engine_fill_quantity_mismatch_is_process(tmp_path, make_dataset, oracle):
    _, env, body = _setup(tmp_path, make_dataset)

    def partial(spec):
        res = fill_at_first_close(spec)
        fill = res.fills[0]
        half = runs.Fill(fill.session, fill.quantity // 2, fill.price, Decimal(0))
        return runs.EngineResult(res.name, res.version, [half])

    with pytest.raises(ProtocolError) as info:
        _run(body, env, partial, oracle)
    assert info.value.code is ErrorCode.PROCESS


def test_run_holds_the_heavy_job_lock(tmp_path, make_dataset, oracle):
    _, env, body = _setup(tmp_path, make_dataset)
    seen = {}

    def probe_lock(spec):
        try:
            with guards.HeavyJobLock(tmp_path / "runs" / runs.LOCK_NAME):
                seen["second"] = "acquired"
        except ProtocolError as exc:
            seen["second"] = exc.code.value
        return fill_at_first_close(spec)

    _run(body, env, probe_lock, oracle)
    assert seen["second"] == "process"


def test_cash_below_one_share_is_rejected_loudly(tmp_path, make_dataset):
    _, env, body = _setup(tmp_path, make_dataset)
    with pytest.raises(ProtocolError) as info:
        _run({**body, "starting_cash": "50.00"}, env)
    assert info.value.code is ErrorCode.SCHEMA


def test_default_engine_without_nautilus_is_module_origin(tmp_path, make_dataset):
    try:
        import nautilus_trader  # noqa: F401  # pylint: disable=unused-import

        pytest.skip("nautilus_trader is installed; this negative path needs it absent")
    except ImportError:
        pass
    _, env, body = _setup(tmp_path, make_dataset)
    with pytest.raises(ProtocolError) as info:
        runs.run(body, env=env, fixed_precision=9)
    assert info.value.code is ErrorCode.MODULE_ORIGIN


@pytest.mark.requires_nautilus
def test_buy_and_hold_independent_case(tmp_path, make_dataset, oracle):
    """Real BacktestEngine reproduces the hand-computed oracle (LIVE T03-L)."""
    _, env, body = _setup(tmp_path, make_dataset)
    rep = runs.run({**body, "starting_cash": oracle["initial_cash"]}, env=env)
    assert rep["quantity"] == oracle["expected"]["quantity"]
    assert rep["cash"] == oracle["expected"]["cash"]
    assert rep["equity"] == oracle["expected"]["equity"]
    assert rep["engine"]["name"] == "nautilus_trader.BacktestEngine"


def _swap_bars_after(monkeypatch, module, attr, dataset_dir_of):
    """Wrap ``module.attr`` so ``bars.parquet`` is replaced right after it returns."""
    # pylint: disable=import-outside-toplevel
    import pyarrow.parquet as pq
    from openbb_nautilus_worker import dataset as ds

    real = getattr(module, attr)

    def wrapped(*args, **kwargs):
        out = real(*args, **kwargs)
        path = dataset_dir_of(args) / ds.BARS_FILE
        table = pq.read_table(path)
        doubled = table.set_column(
            table.schema.get_field_index("close"),
            "close",
            [[c * 2 for c in table.column("close").to_pylist()]],
        )
        pq.write_table(doubled, path)
        return out

    monkeypatch.setattr(module, attr, wrapped)


def test_bars_swapped_after_admission_do_not_change_the_run(
    tmp_path, make_dataset, oracle, monkeypatch
):
    """SECURITY-1: the run uses the verified bytes, not a re-read of the file."""
    # pylint: disable=import-outside-toplevel
    from openbb_nautilus_worker import admission

    ds_id, env, body = _setup(tmp_path, make_dataset)
    _swap_bars_after(
        monkeypatch,
        admission,
        "admit_run",
        lambda _args: tmp_path / "datasets" / ds_id,
    )
    rep = _run(body, env, oracle=oracle)
    exp = oracle["expected"]
    assert (rep["quantity"], rep["cash"]) == (exp["quantity"], exp["cash"])
    assert rep["final_equity"] == exp["final_equity"]
