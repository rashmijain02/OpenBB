"""Bounded benchmark on the fake worker: invariants, never timings (#1357 T03).

Counts, completeness, determinism and failure injection run through the real
worker entrypoint with the event-replay fake engine on seeded synthetic bars.
No network, no database, no wall-clock assertions.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest
from openbb_backtest import modeled_differences as md
from openbb_backtest.validation import (
    bench,
    experiment as cli,
)

BACKTEST = Path(__file__).parents[3]
FIXTURE_SPEC = Path(__file__).parent / "fixtures" / "bench_spec.json"
DOC = (
    BACKTEST.parents[2]
    / "docs"
    / "designs"
    / "backtest-design"
    / "14-nautilus-modeling-differences.md"
)

SMALL = {
    "generator": {
        "seed": 1357,
        "start": "2024-01-02",
        "end": "2024-03-28",
        "calendar": "XNYS",
        "drifts": {"AAA": 0.001, "BBB": -0.0005},
    },
    "initial_cash": "100000.00",
    "methods": ["wfo"],
    "policies": ["continuous", "per_fold"],
    "strategies": [
        {
            "strategy": "target_weight_rebalance",
            "strategy_version": "1.0.0",
            "strategy_params": {
                "rebalance_every_sessions": 5,
                "execution": {"fill_timing": "same_close"},
            },
            "param_grid": {
                "weights": [{"AAA": "0.5", "BBB": "0.5"}, {"AAA": "0.8", "BBB": "0.2"}]
            },
        }
    ],
}


def _main(argv: list[str]) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


def _cli(tmp_path: Path, spec: dict, *flags: str) -> tuple[int, dict]:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), "utf-8")
    argv = ["bench", "--spec", str(path), "--runtime", "fake", "--format", "json"]
    return _main(argv + list(flags))


@pytest.fixture(name="clean", scope="module")
def _clean(tmp_path_factory):
    code, report = _cli(tmp_path_factory.mktemp("clean"), SMALL)
    assert code == 0, report
    return report


def _shape(report: dict, drop: tuple[str, ...] = ("elapsed_s",)) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in drop} for r in report["scenarios"]]


def test_bench_counts_cells_attempts_and_n(clean):
    cont, per_fold = clean["scenarios"]
    assert cont["scenario"] == "target_weight_rebalance/wfo/continuous"
    assert (cont["n_planned"], cont["n_ok"], cont["n_trials_dsr"]) == (2, 2, 2)
    assert (per_fold["n_planned"], per_fold["n_ok"]) == (4, 4)  # 2 configs x 2 folds
    assert per_fold["n_trials_dsr"] == 2  # N counts configurations, not folds
    totals = clean["totals"]
    assert (totals["cells"], totals["attempts"]) == (6, 6)
    assert totals["failed"] == totals["excluded"] == 0
    assert totals["n_matches_plan"] is True
    for row in clean["scenarios"]:
        assert row["matrix_complete"] is True and row["exclusions"] == []
        assert len(row["matrix_sha256"]) == 64


def test_bench_peak_concurrency_one(clean):
    assert clean["peak_concurrency"] == 1
    assert clean["worker_spawns"] == 6


def test_bench_output_has_counts_and_codes_only(clean):
    text = json.dumps(clean)
    for banned in ("returns", "equity", "positions", "cash"):
        assert f'"{banned}"' not in text


def test_bench_injected_kill_known_n(tmp_path, clean):
    code, killed = _cli(tmp_path, SMALL, "--inject-kill", "1")
    assert code == 0, killed
    drop = ("elapsed_s", "new_attempts", "kill_resume")
    assert _shape(killed, drop) == _shape(clean, drop)
    cont = killed["scenarios"][0]
    assert cont["kill_resume"] == {
        "killed_after": 1,
        "attempts_before": 1,
        "resumed_attempts": 1,
    }
    assert cont["n_trials_dsr"] == cont["n_expected"] == 2
    assert killed["totals"]["attempts"] == clean["totals"]["attempts"]


def test_bench_is_deterministic(tmp_path, clean):
    code, again = _cli(tmp_path, SMALL)
    assert code == 0
    assert _shape(again) == _shape(clean)


def test_bench_failure_injections(tmp_path, clean):
    code, rep = _cli(
        tmp_path,
        SMALL,
        "--inject-fail-once",
        "--inject-reject",
        "--inject-changed-data",
    )
    assert code == 0, rep
    assert rep["injections"]["fail_once_fired"] is True
    totals = rep["totals"]
    # the rejected configuration stays planned and counted: 1 + 2 windows
    assert totals["excluded"] == 3 and totals["failed"] == 0
    assert totals["cells"] == 9
    assert totals["attempts"] == 10  # nine cells plus exactly one retried attempt
    assert [r["n_trials_dsr"] for r in rep["scenarios"]] == [3, 3]
    for row in rep["scenarios"]:
        assert row["matrix_complete"] is False
        assert {e["reason"] for e in row["exclusions"]} == {"admission_rejected"}
    # CODE-2: same experiment, the refreshed data adds configurations to N
    changed = rep["changed_data"]
    assert changed["experiment_id_same"] is True
    assert changed["n_grew"] is True
    assert (changed["n_before"], changed["n_after"]) == (3, 6)
    assert changed["status"] == "mixed_dataset"
    assert changed["matrix_sha256"] is None
    assert (
        rep["scenarios"][0]["experiment_id"] != clean["scenarios"][0]["experiment_id"]
    )


def test_bench_rejects_over_bounds(tmp_path):
    spec = json.loads(json.dumps(SMALL))
    spec["policies"] = ["continuous"]
    spec["strategies"][0]["param_grid"] = {
        "weights": [{"AAA": f"0.{i:02d}", "BBB": "0.30"} for i in range(1, 66)]
    }
    code, out = _cli(tmp_path, spec)
    assert code == 2 and out["ok"] is False
    assert "experiment_too_large" in out["error"]


def test_native_only_injections_fail_closed_on_native():
    with pytest.raises(ValueError, match="need --runtime fake"):
        bench.run_bench(
            SMALL, runtime="native", injections=bench.Injections(fail_once=True)
        )


def test_generator_is_seeded_and_bounded():
    sessions, bars = bench.generate_bars(SMALL["generator"])
    assert (sessions, bars) == bench.generate_bars(SMALL["generator"])
    assert len(sessions) == len(bars["AAA"]) == len(bars["BBB"])
    assert bars["AAA"][0][0] == "50.00"
    spec = json.loads(FIXTURE_SPEC.read_text("utf-8"))
    assert len(bench.generate_bars(spec["generator"])[0]) == 756


def test_shipped_spec_is_inside_settings_bounds():
    from openbb_backtest.settings import DEFAULT_SETTINGS

    spec = json.loads(FIXTURE_SPEC.read_text("utf-8"))
    assert "no real prices" in spec["source"]
    for strat in spec["strategies"]:
        n = 1
        for values in strat["param_grid"].values():
            n *= len(values)
        assert n <= DEFAULT_SETTINGS.experiment_max_configs
        # CPCV(6,2) per_fold plans one window per group
        assert n * 6 <= DEFAULT_SETTINGS.experiment_max_cells


def _doc_ids() -> list[str]:
    return re.findall(r"^\*\*id:\*\* `([a-z_0-9]+)`", DOC.read_text("utf-8"), re.M)


def test_modeling_differences_doc_lists_every_reconcile_difference_id():
    assert len(set(md.MODELED_DIFFERENCES)) == len(md.MODELED_DIFFERENCES)
    assert sorted(_doc_ids()) == sorted(md.MODELED_DIFFERENCES)


def test_reconcile_reports_the_documented_ids():
    from openbb_backtest.routers import run_router

    assert run_router.MODELED_DIFFERENCES is md.MODELED_DIFFERENCES


def test_doc_records_legacy_findings_for_p18():
    text = DOC.read_text("utf-8")
    for tag in ("F1", "F2", "F3", "F4", "F5", "F6"):
        assert re.search(rf"^\| {tag} \|", text, re.M), tag
    assert "P18" in text
