"""Counting rules: never understate the multiple-testing penalty (#1357 T01, A2)."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace

import numpy as np
import pytest
from openbb_backtest.validation.matrix import FoldReturnMatrix, assemble, encode_returns
from openbb_backtest.validation.report import capped_verdict
from openbb_backtest.validation.selection import selection_statistics
from openbb_backtest.validation.trials import (
    Bounds,
    CellOutcome,
    ExperimentTooLargeError,
    TrialLedger,
    dispatch,
    n_trials_dsr,
)
from scipy.stats import norm

from trial_helpers import (
    ok_executor,
    series_for,
    wfo_cells,
)  # pylint: disable=import-error


def _ledger(tmp_path):
    return TrialLedger(tmp_path / "experiments" / ("1" * 64))


def test_retry_after_process_failure_counts_once(tmp_path):
    cells = wfo_cells(2, 2)
    calls = []

    def flaky(cell, attempt_no):
        calls.append((cell.trial_id, attempt_no))
        if cell is cells[0] and attempt_no == 1:
            return CellOutcome(status="failed", error_code="process", reason="crash")
        return ok_executor(cell, attempt_no)

    led = _ledger(tmp_path)
    assert dispatch(led, cells, flaky) == 5
    recs = led.records()
    a = assemble(led.planned(), recs)
    assert [r.attempt_no for r in recs if r.trial_id == cells[0].trial_id] == [1, 2]
    assert a.n_trials_dsr == n_trials_dsr(recs) == 2
    assert a.status == "ok" and a.matrix_complete and a.n_ok == 4


def test_deterministic_rejection_not_retried(tmp_path):
    cells = wfo_cells(2, 1)
    seen = []

    def reject_first(cell, attempt_no):
        seen.append(attempt_no)
        if cell.config_id == cells[0].config_id:
            return CellOutcome(
                status="excluded", error_code="admission", reason="admission_rejected"
            )
        return ok_executor(cell, attempt_no)

    def schema_fail(cell, attempt_no):
        return CellOutcome(status="failed", error_code="schema", reason="bad")

    led = _ledger(tmp_path)
    dispatch(led, cells, reject_first)
    assert seen == [1, 1]
    led2 = TrialLedger(tmp_path / "experiments" / ("2" * 64))
    assert dispatch(led2, cells, schema_fail) == 2  # one attempt per cell, no retry
    a = assemble(led2.planned(), led2.records())
    assert a.n_failed == 2 and a.n_trials_dsr == 2 and a.matrix is None


def test_failed_and_excluded_configs_count_in_n(tmp_path):
    cells = wfo_cells(4, 2)
    cfgs = sorted({c.config_id for c in cells})

    def mixed(cell, attempt_no):
        if cell.config_id == cfgs[0]:
            return CellOutcome(
                status="excluded", error_code="admission", reason="admission_rejected"
            )
        if cell.config_id == cfgs[1] and cell.window.ordinal == 1:
            return CellOutcome(status="failed", error_code="timeout", reason="deadline")
        return ok_executor(cell, attempt_no)

    led = _ledger(tmp_path)
    dispatch(led, cells, mixed)
    a = assemble(led.planned(), led.records(), external_trials=0)
    assert a.n_trials_dsr == 4  # not 2 (the ok columns)
    assert a.matrix.config_ids == cfgs[2:]
    assert {e["config_id"]: e["reason"] for e in a.exclusions} == {
        cfgs[0]: "admission_rejected",
        cfgs[1]: "worker_failed",
    }
    assert not a.matrix_complete and a.status == "incomplete"
    # The DSR from the partial matrix still uses N=4, not the 2 surviving columns.
    st = selection_statistics(a.matrix, a.n_trials_dsr)
    assert st.n_trials == 4
    with pytest.raises(ValueError, match="understates"):
        selection_statistics(a.matrix, 1)


def test_changed_dataset_is_new_trial(tmp_path):
    cells = wfo_cells(2, 1)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    before = assemble(led.planned(), led.records())
    assert before.n_trials_dsr == 2 and before.status == "ok"
    changed = replace(
        cells[0], config=replace(cells[0].config, base_dataset_id="9" * 64)
    )
    assert changed.config_id != cells[0].config_id
    led2 = _ledger(tmp_path / "b")
    dispatch(led2, cells + [changed], ok_executor)
    after = assemble(led2.planned(), led2.records())
    assert after.n_trials_dsr == 3
    assert after.status == "mixed_dataset" and after.matrix is None


def test_conflicting_ok_attempts_fail_closed(tmp_path):
    cells = wfo_cells(2, 1)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    recs = led.records()
    other = replace(
        recs[0],
        attempt_id="z" * 64,
        attempt_no=2,
        returns=encode_returns([("2024-01-03", 0.5)]),
        result_sha256="f" * 64,
    )
    a = assemble(led.planned(), recs + [other])
    assert a.status == "failed_closed" and a.matrix is None
    assert {"config_id": recs[0].config_id, "reason": "conflict"} in a.exclusions
    assert a.n_trials_dsr == 2
    # Identical duplicate ok attempts (same result hash) are one cell, not a conflict.
    same = replace(recs[0], attempt_id="y" * 64, attempt_no=2)
    assert assemble(led.planned(), recs + [same]).status == "ok"


def test_n_monotone_under_permutations(tmp_path):
    cells = wfo_cells(3, 2)
    cfgs = sorted({c.config_id for c in cells})

    def ex(cell, attempt_no):
        if cell.config_id == cfgs[0] and cell.window.ordinal == 0:
            return CellOutcome(status="failed", error_code="schema", reason="bad")
        return ok_executor(cell, attempt_no)

    led = _ledger(tmp_path)
    dispatch(led, cells, ex)
    recs = led.records()
    assert len(recs) == 6
    planned = led.planned()
    ref = assemble(planned, recs)
    for perm in itertools.permutations(recs):
        got = assemble(planned, list(perm))
        assert (got.n_trials_dsr, got.matrix.sha256, got.exclusions) == (
            ref.n_trials_dsr,
            ref.matrix.sha256,
            ref.exclusions,
        )
        prefix_n = [n_trials_dsr(perm[:k]) for k in range(len(perm) + 1)]
        assert prefix_n == sorted(prefix_n)  # appending never lowers N
        assert prefix_n[-1] == 3


def test_external_trials_added(tmp_path):
    cells = wfo_cells(2, 1)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    assert (
        assemble(led.planned(), led.records(), external_trials=100).n_trials_dsr == 102
    )
    with pytest.raises(ValueError):
        n_trials_dsr(led.records(), -1)


def test_exclusion_caps_verdict_at_fragile():
    strong = {"dsr": 0.99, "oos_sharpe": 1.5}
    assert capped_verdict(pbo=0.05, matrix_complete=True, **strong) == "robust"
    assert capped_verdict(pbo=0.05, matrix_complete=False, **strong) == "fragile"
    assert capped_verdict(pbo=None, matrix_complete=True, **strong) == "fragile"
    assert (
        capped_verdict(pbo=None, matrix_complete=True, dsr=0.01, oos_sharpe=1.0)
        == "overfit"
    )
    assert capped_verdict(pbo=0.9, matrix_complete=False, **strong) == "overfit"


def test_bounds_reject_before_spawn(tmp_path):
    cells = wfo_cells(3, 2)
    spy = []

    def executor(cell, attempt_no):
        spy.append(cell)
        return ok_executor(cell, attempt_no)

    led = _ledger(tmp_path)
    with pytest.raises(ExperimentTooLargeError, match="experiment_too_large"):
        dispatch(led, cells, executor, bounds=Bounds(max_configs=2))
    with pytest.raises(ExperimentTooLargeError):
        dispatch(led, cells, executor, bounds=Bounds(max_cells=5))
    assert spy == [] and not led.planned_path.exists()


def test_planned_written_before_first_attempt(tmp_path):
    cells = wfo_cells(1, 2)
    led = _ledger(tmp_path)

    def check(cell, attempt_no):
        assert len(led.planned()) == 2  # the full plan is on disk before dispatch
        return ok_executor(cell, attempt_no)

    dispatch(led, cells, check)
    first = led.planned_path.read_bytes()
    led.write_planned(cells[:1])  # nothing new: no rewrite, no new version
    assert led.planned_path.read_bytes() == first
    assert not list(led.directory.glob("planned.v*.json"))


def test_replan_appends_planned_version_never_rewrites(tmp_path):
    """CODE-2: new cells go to planned.v2.json; planned.json is never rewritten."""
    cells = wfo_cells(2, 1)
    led = _ledger(tmp_path)
    led.write_planned(cells[:1])
    first = led.planned_path.read_bytes()
    led.write_planned(cells)
    assert led.planned_path.read_bytes() == first
    v2 = led.directory / "planned.v2.json"
    assert v2.exists() and cells[1].trial_id in v2.read_text("utf-8")
    assert cells[0].trial_id not in v2.read_text("utf-8")
    assert [c.trial_id for c in led.planned()] == [c.trial_id for c in cells[:2]]
    # fail closed on a gap in the versions or a duplicated trial
    (led.directory / "planned.v4.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="contiguous"):
        led.planned()
    (led.directory / "planned.v4.json").unlink()
    (led.directory / "planned.v3.json").write_text(
        v2.read_text("utf-8"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        led.planned()


def _dsr_reference(sr, n, v, skew, kurt, t):
    """Independent closed form (Bailey & Lopez de Prado 2014, eqs. for SR0 and DSR)."""
    gamma = 0.5772156649015329
    sr0 = (
        0.0
        if n == 1
        else math.sqrt(v)
        * ((1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * math.e)))
    )
    return norm.cdf(
        (sr - sr0)
        * math.sqrt(t - 1)
        / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2)
    )


def test_validate_statistics_from_matrix_literal():
    """3 configs x 12 sessions through the assembler -> literal N, V, DSR, PBO."""
    r = np.array(
        [
            [0.010, 0.004, -0.002],
            [-0.005, 0.006, 0.003],
            [0.012, -0.003, 0.001],
            [0.002, 0.005, -0.004],
            [-0.004, 0.002, 0.006],
            [0.008, -0.001, 0.002],
            [0.003, 0.007, -0.003],
            [-0.006, 0.001, 0.004],
            [0.009, 0.004, 0.000],
            [0.001, -0.002, 0.005],
            [0.007, 0.003, -0.001],
            [-0.002, 0.006, 0.002],
        ]
    )
    cfgs = ["c" * 64, "a" * 64, "b" * 64]  # deliberately unsorted input
    days = [f"2024-02-{d:02d}" for d in range(1, 13)]
    rows = [(cfgs[j], 0, days[i], float(r[i, j])) for i in range(12) for j in range(3)]
    st = selection_statistics(
        FoldReturnMatrix.from_rows(rows), n_trials=5, n_groups=4, statistic="sum"
    )
    # Independent: columns re-ordered a, b, c = r[:, 1], r[:, 2], r[:, 0].
    cols = r[:, [1, 2, 0]]
    sr = cols.mean(0) / cols.std(0, ddof=1)
    best = int(np.argmax(sr))
    x = cols[:, best]
    d = x - x.mean()
    skew = float((d**3).mean() / (d**2).mean() ** 1.5)
    kurt = float((d**4).mean() / (d**2).mean() ** 2)
    v = float(np.var(sr, ddof=1))
    assert st.config_ids == ("a" * 64, "b" * 64, "c" * 64)
    assert st.n_trials == 5 and st.n_obs == 12
    assert st.best_config_id == ["a" * 64, "b" * 64, "c" * 64][best]
    assert st.sr_variance == pytest.approx(v, rel=1e-12)
    assert st.skew == pytest.approx(skew, rel=1e-12) and st.kurt == pytest.approx(
        kurt, rel=1e-12
    )
    assert st.deflated_sharpe == pytest.approx(
        _dsr_reference(sr[best], 5, v, skew, kurt, 12), rel=1e-9
    )
    # PBO by brute-force CSCV: 4 groups of 3 rows, C(4,2)=6 partitions, sum statistic.
    groups = np.split(cols, 4)
    over = 0
    for is_g in itertools.combinations(range(4), 2):
        oos_g = [g for g in range(4) if g not in is_g]
        is_perf = np.vstack([groups[g] for g in is_g]).sum(0)
        oos_perf = np.vstack([groups[g] for g in oos_g]).sum(0)
        b = int(np.argmax(is_perf))
        rank = int((oos_perf < oos_perf[b]).sum()) + 1
        w = rank / (3 + 1)
        over += math.log(w / (1 - w)) <= 0
    assert st.pbo == pytest.approx(over / 6)
    # Discriminating: folds-as-columns or N = ok columns would differ.
    assert st.deflated_sharpe != pytest.approx(
        _dsr_reference(sr[best], 3, v, skew, kurt, 12), rel=1e-6
    )


def test_single_config_pbo_undefined_not_zero(tmp_path):
    cells = wfo_cells(1, 1, per_window=8)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    a = assemble(led.planned(), led.records())
    st = selection_statistics(a.matrix, a.n_trials_dsr)
    assert st.pbo is None and st.pbo_undefined_reason == "single_configuration"
    assert series_for(cells[0])  # helper sanity


def _three_config_matrix(t=252):
    """3 configs x ``t`` sessions, seeded, distinct drifts (V > 0, DSR unsaturated)."""
    rng = np.random.default_rng(1357)
    days = series_days(t)
    rows = []
    for i, mu in enumerate((0.0015, 0.0008, 0.0002)):
        rets = rng.normal(mu, 0.01, t)
        rows += [(f"{i:064x}", 0, d, float(x)) for d, x in zip(days, rets)]
    return FoldReturnMatrix.from_rows(rows)


def series_days(t):
    """``t`` ISO days (independent of the helper module)."""
    start = np.datetime64("2024-01-02")
    return [str(start + np.timedelta64(k, "D")) for k in range(t)]


def test_dsr_deflates_with_n_when_two_or_more_ok_configs():
    """CODE-1 (b): with >= 2 ok configs V > 0, so N=100 deflates below N=1."""
    from openbb_backtest.validation.stats import deflated_sharpe

    m = _three_config_matrix()
    st100 = selection_statistics(m, 100)
    st3 = selection_statistics(m, 3)
    assert st100.dsr_undefined_reason is None and st100.sr_variance > 0.0
    dsr1 = deflated_sharpe(
        st3.best_sharpe, 1, st3.skew, st3.kurt, st3.n_obs, sr_variance=st3.sr_variance
    )
    assert st100.deflated_sharpe < st3.deflated_sharpe < dsr1
    for st, n in ((st100, 100), (st3, 3)):
        assert st.deflated_sharpe == pytest.approx(
            _dsr_reference(st.best_sharpe, n, st.sr_variance, st.skew, st.kurt, 252),
            rel=1e-9,
        )
    # literal anchors (independent closed form above; pinned to 4 dp)
    assert round(st100.deflated_sharpe, 4) == 0.2974
    assert round(dsr1, 4) == 0.9963


def test_dsr_undefined_when_n_exceeds_one_and_single_config(tmp_path):
    """CODE-1: N > 1 with one ok config -> DSR None + reason, never the PSR."""
    cells = wfo_cells(1, 1, per_window=40)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    a = assemble(led.planned(), led.records(), external_trials=99)
    st = selection_statistics(a.matrix, a.n_trials_dsr)
    assert st.n_trials == 100
    assert st.deflated_sharpe is None
    assert st.dsr_undefined_reason == "dsr_undefined_insufficient_variance"
    one = selection_statistics(a.matrix, 1)  # N == 1 keeps the PSR (benchmark 0)
    assert one.dsr_undefined_reason is None
    assert one.deflated_sharpe == pytest.approx(
        _dsr_reference(one.best_sharpe, 1, 0.0, one.skew, one.kurt, one.n_obs)
    )


def test_dsr_undefined_when_cross_config_variance_is_zero():
    """CODE-1: two identical columns give V = 0; with N > 1 DSR is undefined."""
    days = series_days(30)
    rets = np.random.default_rng(7).normal(0.001, 0.01, 30)
    rows = [
        (cfg, 0, d, float(x))
        for cfg in ("a" * 64, "b" * 64)
        for d, x in zip(days, rets)
    ]
    st = selection_statistics(FoldReturnMatrix.from_rows(rows), 2)
    assert st.sr_variance == 0.0 and st.deflated_sharpe is None
    assert st.dsr_undefined_reason == "dsr_undefined_insufficient_variance"


def test_undefined_dsr_caps_verdict():
    """CODE-1: an undefined DSR never helps; overfit triggers still win."""
    good = {"oos_sharpe": 1.5, "matrix_complete": True}
    assert capped_verdict(pbo=0.05, dsr=None, **good) == "fragile"
    assert capped_verdict(pbo=None, dsr=None, **good) == "fragile"
    assert capped_verdict(pbo=0.6, dsr=None, **good) == "overfit"
    assert (
        capped_verdict(pbo=0.05, dsr=None, oos_sharpe=0.0, matrix_complete=True)
        == "overfit"
    )
