"""CODE-2c: grid changes append planned cells; the matrix is the current plan's (#1357).

The experiment identity excludes the configuration set, so a narrowed, widened
or refreshed grid re-opens the same ledger. ``N`` keeps every configuration ever
planned or attempted (+ the largest declared ``external_trials``); the matrix,
the counts and the exclusions cover only the current plan's cells.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest
from openbb_backtest.validation.matrix import assemble
from openbb_backtest.validation.trials import (
    CellOutcome,
    TrialLedger,
    dispatch,
    returns_sha256,
)
from trial_helpers import ok_executor, wfo_cells  # pylint: disable=import-error


def _ledger(tmp_path, name="1"):
    return TrialLedger(tmp_path / name / "experiments" / ("1" * 64))


def _keys(cells):
    return sorted({c.config.config_key for c in cells})


def _regen(cells, dataset_id):
    return [
        replace(c, config=replace(c.config, base_dataset_id=dataset_id)) for c in cells
    ]


def _counting(calls):
    def execute(cell, attempt_no):
        calls.append(cell.trial_id)
        return ok_executor(cell, attempt_no)

    return execute


def test_narrowed_grid_keeps_n_and_matrix_from_current_plan(tmp_path):
    """Dropping a config: nothing re-runs, N keeps it, the matrix is complete."""
    wide = wfo_cells(3, 2)
    dropped = sorted({c.config_id for c in wide})[2]
    narrow = [c for c in wide if c.config_id != dropped]
    led = _ledger(tmp_path)
    dispatch(led, wide, ok_executor)
    calls: list[str] = []
    assert dispatch(led, narrow, _counting(calls)) == 0 and not calls
    assert not (led.directory / "planned.v2.json").exists()
    a = assemble(led.planned(), led.records(), config_keys=_keys(narrow))
    assert a.n_trials_dsr == 3, "the dropped config left N"
    assert a.status == "ok" and a.matrix_complete and not a.exclusions
    assert a.n_planned == len(narrow) == 4
    assert a.matrix.config_ids == sorted({c.config_id for c in narrow})
    # the same matrix a fresh experiment with only the narrow grid would build
    fresh = _ledger(tmp_path, "fresh")
    dispatch(fresh, narrow, ok_executor)
    assert a.matrix.sha256 == assemble(fresh.planned(), fresh.records()).matrix.sha256


def test_widened_grid_runs_only_new_cells(tmp_path):
    """Adding a config appends one planned version holding only its cells."""
    wide = wfo_cells(3, 2)
    added = sorted({c.config_id for c in wide})[2]
    first = [c for c in wide if c.config_id != added]
    led = _ledger(tmp_path)
    dispatch(led, first, ok_executor)
    calls: list[str] = []
    assert dispatch(led, wide, _counting(calls)) == 2
    assert set(calls) == {c.trial_id for c in wide if c.config_id == added}
    versions = led.planned_versions()
    assert [len(v) for v in versions] == [4, 2]
    assert {c.config_id for c in versions[1]} == {added}
    a = assemble(led.planned(), led.records(), config_keys=_keys(wide))
    assert a.n_trials_dsr == 3 and a.status == "ok" and a.matrix_complete
    assert a.matrix.config_ids == sorted({c.config_id for c in wide})


def test_same_grid_twice_appends_nothing(tmp_path):
    """Re-running the same grid adds no planned version and no attempt."""
    cells = wfo_cells(2, 2)
    led = _ledger(tmp_path)
    dispatch(led, cells, ok_executor)
    before = assemble(led.planned(), led.records(), config_keys=_keys(cells))
    assert dispatch(led, cells, ok_executor) == 0
    assert len(led.planned_versions()) == 1
    after = assemble(led.planned(), led.records(), config_keys=_keys(cells))
    assert after.matrix.sha256 == before.matrix.sha256
    assert after.n_trials_dsr == before.n_trials_dsr == 2


def test_refresh_and_grid_change_together(tmp_path):
    """New data and a changed grid: one new version; matrix from those cells only."""
    old = wfo_cells(3, 2)
    cfgs = sorted({c.config_id for c in old})
    led = _ledger(tmp_path)
    dispatch(led, old, ok_executor)
    extra = [c for c in wfo_cells(4, 2) if c.config_id not in cfgs]
    kept = [c for c in old if c.config_id == cfgs[0]]
    plan = _regen(kept + extra, "9" * 64)
    assert dispatch(led, plan, ok_executor) == 4
    assert [len(v) for v in led.planned_versions()] == [6, 4]
    a = assemble(
        led.planned(), led.records(), dataset_id="9" * 64, config_keys=_keys(plan)
    )
    assert a.n_trials_dsr == 4, "3 old configs + 1 new one"
    assert a.status == "ok" and a.matrix_complete and a.n_planned == 4
    assert a.matrix.config_ids == sorted({c.config_id for c in plan})


def test_conflict_in_a_dropped_config_still_fails_closed(tmp_path):
    """Narrowing the grid never forgets nondeterminism (decision 2)."""
    wide = wfo_cells(2, 1)
    led = _ledger(tmp_path)
    dispatch(led, wide, ok_executor)
    dropped = sorted(wide, key=lambda c: c.config_id)[1]
    rec = next(r for r in led.records() if r.trial_id == dropped.trial_id)
    other = ok_executor(wfo_cells(3, 1)[2], 1).returns
    led.append(
        replace(
            rec,
            attempt_id="9" * 64,
            attempt_no=2,
            returns=other,
            result_sha256=returns_sha256(other),
        )
    )
    narrow = [c for c in wide if c.trial_id != dropped.trial_id]
    a = assemble(led.planned(), led.records(), config_keys=_keys(narrow))
    assert a.status == "failed_closed" and a.matrix is None
    assert {"config_id": dropped.config_id, "reason": "conflict"} in a.exclusions


def test_current_plan_failure_is_counted_not_earlier_plans(tmp_path):
    """Counts cover the current plan: an earlier plan's failure is N only."""
    wide = wfo_cells(2, 2)
    bad = sorted({c.config_id for c in wide})[1]

    def fail_bad(cell, attempt_no):
        if cell.config_id == bad:
            return CellOutcome(status="failed", error_code="egress", reason="x")
        return ok_executor(cell, attempt_no)

    led = _ledger(tmp_path)
    dispatch(led, wide, fail_bad)
    narrow = [c for c in wide if c.config_id != bad]
    a = assemble(led.planned(), led.records(), config_keys=_keys(narrow))
    assert (a.n_failed, a.n_ok, a.n_trials_dsr) == (0, 2, 2)
    assert a.status == "ok" and a.matrix_complete


# --- external_trials: a per-run declaration, max over history ---------------


def test_declared_external_never_decreases(tmp_path):
    """Only increases are recorded; the effective value is the maximum."""
    led = _ledger(tmp_path)
    assert led.declared_external() == 0
    assert led.declare_external(0) == 0
    assert not led.external_path.exists(), "zero needs no record"
    assert led.declare_external(5) == 5
    assert led.declare_external(2) == 5, "a lower declaration lowered N"
    assert led.declare_external(7) == 7
    assert led.declare_external(7) == 7
    lines = led.external_path.read_text("utf-8").splitlines()
    assert lines == ['{"external_trials":5}', '{"external_trials":7}']
    with pytest.raises(ValueError, match=">= 0"):
        led.declare_external(-1)


def test_declared_external_fails_closed_on_tampering(tmp_path):
    """A torn final line is ignored; any other bad entry fails closed."""
    led = _ledger(tmp_path)
    led.declare_external(3)
    with led.external_path.open("a", encoding="utf-8") as fh:
        fh.write('{"external_trials":')  # torn final line: ignored
    assert led.declared_external() == 3
    led.external_path.write_text('{"external_trials":-4}\n', "utf-8")
    with pytest.raises(ValueError, match="invalid"):
        led.declared_external()
    led.external_path.write_text('garbage\n{"external_trials":1}\n', "utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        led.declared_external()


# --- torn tails: appends never glue onto a crash fragment -------------------


def test_declare_external_after_torn_tail_is_not_lost(tmp_path):
    """A crash fragment is dropped before the next declaration is appended."""
    led = _ledger(tmp_path)
    led.directory.mkdir(parents=True)
    led.external_path.write_bytes(b'{"external_trials":3}\n{"external_trials":9')
    assert led.declared_external() == 3
    assert led.declare_external(5) == 5
    assert led.declared_external() == 5, "the declaration was glued to the fragment"
    assert led.declare_external(4) == 5
    assert led.declare_external(8) == 8
    assert led.declared_external() == 8, "the file became unreadable"
    values = [
        json.loads(x)["external_trials"]
        for x in led.external_path.read_text("utf-8").splitlines()
    ]
    assert values == sorted(values) and values == [3, 5, 8]


def test_declare_external_keeps_complete_unterminated_tail(tmp_path):
    """A tail that is complete JSON only lacks a newline: it is kept, never lost."""
    led = _ledger(tmp_path)
    led.directory.mkdir(parents=True)
    led.external_path.write_bytes(b'{"external_trials":3}\n{"external_trials":9}')
    assert led.declared_external() == 9
    assert led.declare_external(12) == 12
    assert led.declared_external() == 12


def test_ledger_append_after_torn_tail_keeps_every_record(tmp_path):
    """A torn ledger line is dropped; the next record is not swallowed with it."""
    led = _ledger(tmp_path)
    cells = wfo_cells(1, 2)
    dispatch(led, cells, ok_executor)
    before = led.records()
    assert len(before) == len(cells)
    with led.ledger_path.open("ab") as fh:
        fh.write(b'{"attempt_id":"torn')
    assert len(led.records()) == len(before)
    led.append(replace(before[0], attempt_no=before[0].attempt_no + 1))
    after = led.records()
    assert len(after) == len(before) + 1, "the new record was glued to the fragment"
    led.append(replace(before[1], attempt_no=before[1].attempt_no + 1))
    assert len(led.records()) == len(before) + 2, "the ledger became unreadable"


# --- concurrent planned-version writers: exclusive claim, never overwrite ----


def _racing(monkeypatch, rival_cells):
    """Make a rival writer claim the next version between read and claim."""
    real = TrialLedger._claim
    state = {"fired": False, "names": []}

    def claim(self, name, text):
        state["names"].append(name)
        if not state["fired"]:
            state["fired"] = True
            rival = TrialLedger(self.directory)
            monkeypatch.setattr(TrialLedger, "_claim", real)
            rival.write_planned(rival_cells)
            monkeypatch.setattr(TrialLedger, "_claim", claim)
        return real(self, name, text)

    monkeypatch.setattr(TrialLedger, "_claim", claim)
    return state


def test_racing_planned_version_is_not_overwritten(tmp_path, monkeypatch):
    """A rival claims v2 first: the loser lands at v3 with only its new cells."""
    wide = wfo_cells(4, 2)
    ids = sorted({c.config_id for c in wide})
    base = [c for c in wide if c.config_id == ids[0]]
    ours = [c for c in wide if c.config_id == ids[1]]
    theirs = [c for c in wide if c.config_id == ids[2]]
    led = _ledger(tmp_path)
    led.write_planned(base)
    state = _racing(monkeypatch, theirs)
    led.write_planned(base + ours)
    assert state["names"][:2] == ["planned.v2.json", "planned.v3.json"]
    versions = led.planned_versions()
    assert [{c.config_id for c in v} for v in versions] == [
        {ids[0]},
        {ids[2]},
        {ids[1]},
    ], "the rival's version was overwritten or ours lost"


def test_racing_identical_plan_appends_nothing_extra(tmp_path, monkeypatch):
    """A rival that planned the same new cells makes our write a no-op."""
    wide = wfo_cells(2, 2)
    ids = sorted({c.config_id for c in wide})
    base = [c for c in wide if c.config_id == ids[0]]
    new = [c for c in wide if c.config_id == ids[1]]
    led = _ledger(tmp_path)
    led.write_planned(base)
    _racing(monkeypatch, new)
    led.write_planned(base + new)
    assert [len(v) for v in led.planned_versions()] == [len(base), len(new)]
    assert not (led.directory / "planned.v3.json").exists()


def test_planned_claim_fails_closed_after_bounded_retries(tmp_path, monkeypatch):
    """A claim that always loses raises a clear error instead of looping."""
    wide = wfo_cells(2, 1)
    led = _ledger(tmp_path)

    def always_taken(self, name, text):
        raise FileExistsError(name)

    monkeypatch.setattr(TrialLedger, "_claim", always_taken)
    with pytest.raises(RuntimeError, match="could not claim"):
        led.write_planned(wide)


def test_planned_temp_files_are_unique_and_harmless(tmp_path, monkeypatch):
    """No shared ``.tmp`` name; a stray temp never breaks version discovery."""
    seen: list[str] = []
    real_link = os.link

    def spy(src, dst):
        seen.append(os.path.basename(src))
        return real_link(src, dst)

    monkeypatch.setattr(os, "link", spy)
    wide = wfo_cells(3, 1)
    ids = sorted({c.config_id for c in wide})
    led = _ledger(tmp_path)
    led.write_planned([c for c in wide if c.config_id == ids[0]])
    led.write_planned([c for c in wide if c.config_id != ids[2]])
    led.write_spec({"a": 1})
    led.write_spec({"a": 1})
    assert len(seen) == len(set(seen)) == 4
    assert not any(n in {"planned.json.tmp", "planned.v2.json.tmp"} for n in seen)
    (led.directory / ".planned.v3.json.stray.tmp").write_text("{", "utf-8")
    (led.directory / "planned.v3.json.tmp").write_text("{", "utf-8")
    assert [len(v) for v in led.planned_versions()] == [1, 1]
    assert list(led.directory.glob(".planned*")) == [
        led.directory / ".planned.v3.json.stray.tmp"
    ], "own temp files were left behind"
    with pytest.raises(ValueError, match="different content"):
        led.write_spec({"a": 2})
