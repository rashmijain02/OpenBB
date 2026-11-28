"""Sweeps and folds split across spawns reproduce one matrix (#1357 T01, A1)."""

from __future__ import annotations

import random

import pytest
from openbb_backtest.validation.matrix import assemble
from openbb_backtest.validation.trials import TrialLedger, dispatch

from trial_helpers import ok_executor, wfo_cells  # pylint: disable=import-error

EXP = "3" * 64


class _Crash(BaseException):
    """Simulates the process dying mid-experiment (not caught by dispatch)."""


def _result(led):
    a = assemble(led.planned(), led.records())
    return a.matrix.sha256, a.n_trials_dsr, a.exclusions, a.status


@pytest.fixture(name="cells")
def _cells():
    return wfo_cells(3, 4)


def test_one_spawn_equals_three_shuffled_spawns(tmp_path, cells):
    one = TrialLedger.for_experiment(tmp_path / "a", EXP)
    dispatch(one, cells, ok_executor)
    reference = _result(one)
    assert reference[1] == 3 and reference[3] == "ok"

    split = TrialLedger.for_experiment(tmp_path / "b", EXP)
    order = list(cells)
    random.Random(7).shuffle(order)
    for chunk in (order[:4], order[4:9], order[9:]):
        # A spawn carries no state but the ledger; each runs its chunk in shuffled order.
        for cell in chunk:
            dispatch(split, cells, ok_executor, only=[cell.trial_id])
    assert _result(split) == reference
    assert [r.trial_id for r in split.records()] == [c.trial_id for c in order]


def test_crash_after_cell_5_then_resume(tmp_path, cells):
    ref = TrialLedger.for_experiment(tmp_path / "ref", EXP)
    dispatch(ref, cells, ok_executor)

    led = TrialLedger.for_experiment(tmp_path / "crash", EXP)
    done = []

    def dies(cell, attempt_no):
        if len(done) == 5:
            raise _Crash
        done.append(cell)
        return ok_executor(cell, attempt_no)

    with pytest.raises(_Crash):
        dispatch(led, cells, dies)
    assert len(led.records()) == 5
    assert assemble(led.planned(), led.records()).status == "incomplete"
    appended = dispatch(led, cells, ok_executor)
    assert appended == 7  # resume skips the 5 terminal cells
    assert dispatch(led, cells, ok_executor) == 0  # rerun: zero new attempts
    assert _result(led) == _result(ref)


def test_experiment_id_must_be_a_digest(tmp_path):
    with pytest.raises(ValueError):
        TrialLedger.for_experiment(tmp_path, "../escape")
