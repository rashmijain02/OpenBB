"""probe CLI against the fake-engine worker (#1355 T03 code-only real path).

The dataset is produced by the real stage-1 export from the hand-computed
oracle rows; the worker is the real entrypoint with a fake engine seam.
"""

# ruff: noqa: D103

from __future__ import annotations

import json
import sys
from pathlib import Path

from openbb_backtest.adapters.nautilus import (
    export as ex,
    probe,
)
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV

FIX = Path(__file__).parent / "fixtures"
FAKE_RUN = str(FIX / "fake_run_worker.py")
CMD = json.dumps([sys.executable, FAKE_RUN])


def _oracle():
    return json.loads((FIX / "buy_and_hold_oracle.json").read_text(encoding="utf-8"))


def _export_oracle(tmp_path) -> str:
    oracle = _oracle()
    snap = tmp_path / "snap"
    snap.mkdir()
    rows = [
        {
            "symbol": oracle["symbol"],
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
        for d, c in zip(oracle["sessions"], oracle["closes"])
    ]
    (snap / "equity_historical.json").write_text(json.dumps(rows))
    (snap / "calendar_splits.json").write_text("[]")
    (snap / "calendar_dividend.json").write_text("[]")
    out = tmp_path / "data" / "datasets"
    out.mkdir(parents=True)
    res = ex.export_dataset(
        [oracle["symbol"]],
        oracle["sessions"][0],
        oracle["sessions"][-1],
        basis="raw_plus_actions",
        out_root=out,
        execute=ex.snapshot_executor(snap),
    )
    return res.dataset_id


def _main(capsys, *args):
    code = probe.main(
        ["--runtime", "native", "--worker-command-json", CMD, "--format", "json", *args]
    )
    return code, json.loads(capsys.readouterr().out)


def test_admission_matrix_blocks_every_case_with_its_layer(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "data"))
    ds_id = _export_oracle(tmp_path)
    code, rep = _main(capsys, "--admission-matrix", "--dataset", ds_id)
    assert code == 0, rep
    assert rep["passed"] is True
    cases = {c["case"]: c for c in rep["cases"]}
    assert len(cases) >= 12
    assert all(c["ok"] for c in cases.values()), cases
    assert cases["venue_ib"]["actual"] == "egress"
    assert cases["credential_field"]["actual"] == "egress"
    assert cases["absolute_path"]["actual"] == "schema"
    assert cases["unc_path"]["actual"] == "schema"
    assert cases["unknown_dataset"]["actual"] == "schema"
    assert cases["precision_high"]["actual"] == "abi"
    assert cases["control_valid"]["actual"] == "ok"


def test_probe_run_buy_and_hold_matches_oracle(tmp_path, monkeypatch, capsys):
    oracle = _oracle()
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "data"))
    ds_id = _export_oracle(tmp_path)
    code, rep = _main(
        capsys,
        "--run",
        "buy_and_hold",
        "--dataset",
        ds_id,
        "--cash",
        oracle["initial_cash"],
    )
    assert code == 0, rep
    assert rep["passed"] is True
    run = rep["report"]
    assert run["dataset_id"] == ds_id
    assert run["quantity"] == oracle["expected"]["quantity"]
    assert run["cash"] == oracle["expected"]["cash"]
    assert run["equity"] == oracle["expected"]["equity"]
    assert run["final_equity"] == oracle["expected"]["final_equity"]
    assert run["fixed_precision"] == 9
    assert run["engine"]["name"] == "fake-fill-at-close"


def test_probe_run_unknown_dataset_exits_2_with_layer(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "data"))
    (tmp_path / "data" / "datasets").mkdir(parents=True)
    code, rep = _main(capsys, "--run", "buy_and_hold", "--dataset", "f" * 64)
    assert code == 2
    assert rep["passed"] is False and rep["failed_layer"] == "schema"
