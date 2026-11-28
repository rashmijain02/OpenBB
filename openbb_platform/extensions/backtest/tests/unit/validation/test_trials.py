"""Trial identity (#1357 T01, A1)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from openbb_backtest.adapters.nautilus import strategies
from openbb_backtest.validation.trials import (
    Cell,
    ConfigIdentity,
    Window,
    attempt_id,
    trial_id,
)

from trial_helpers import BASE, sessions  # pylint: disable=import-error


def _win(ordinal: int, days: list[str]) -> Window:
    return Window.from_sessions(
        policy="per_fold",
        method="wfo",
        fold_params={"n": 2},
        ordinal=ordinal,
        sessions=days,
    )


def test_config_id_ignores_window_trial_id_binds_it():
    w1, w2 = _win(0, sessions(5)), _win(1, sessions(5)[1:])
    c1, c2 = Cell(BASE, w1), Cell(BASE, w2)
    assert c1.config_id == c2.config_id == BASE.config_id
    assert c1.trial_id != c2.trial_id
    assert trial_id(BASE.config_id, w1) == c1.trial_id
    assert attempt_id(c1.trial_id, 1, "n1") != attempt_id(c1.trial_id, 2, "n1")
    assert attempt_id(c1.trial_id, 1, "n1") != attempt_id(c1.trial_id, 1, "n2")
    # A same-window, different-config cell is a different trial too.
    other = dataclasses.replace(BASE, params_sha256="9" * 64)
    assert trial_id(other.config_id, w1) != c1.trial_id


@pytest.mark.parametrize("weight", [0.5, "0.5", Decimal("0.50")])
def test_equivalent_params_one_config(weight):
    binding = strategies.resolve_reviewed(
        "target_weight_rebalance",
        "1.0.0",
        {"weights": {"AAA": weight, "BBB": "0.5"}, "rebalance_every_sessions": 2},
        None,
    )
    ident = ConfigIdentity.from_binding(
        binding,
        base_dataset_id="f" * 64,
        engine_version="e",
        worker_version="w",
        fixed_precision=2,
    )
    reference = strategies.resolve_reviewed(
        "target_weight_rebalance",
        "1.0.0",
        {"weights": {"AAA": "0.5", "BBB": "0.5"}, "rebalance_every_sessions": 2},
        None,
    )
    ref = ConfigIdentity.from_binding(
        reference,
        base_dataset_id="f" * 64,
        engine_version="e",
        worker_version="w",
        fixed_precision=2,
    )
    assert ident.config_id == ref.config_id


@pytest.mark.parametrize("name", [f.name for f in dataclasses.fields(ConfigIdentity)])
def test_each_binding_field_changes_config_id(name):
    value = getattr(BASE, name)
    changed = value + 1 if isinstance(value, int) else value + "x"
    assert dataclasses.replace(BASE, **{name: changed}).config_id != BASE.config_id


@pytest.mark.parametrize("name", [f.name for f in dataclasses.fields(Window)])
def test_each_window_field_changes_trial_id(name):
    win = _win(0, sessions(5))
    value = getattr(win, name)
    changed = value + 1 if isinstance(value, int) else value + "x"
    assert trial_id(
        BASE.config_id, dataclasses.replace(win, **{name: changed})
    ) != trial_id(BASE.config_id, win)


def test_planned_cell_roundtrip_refuses_tampering():
    cell = Cell(BASE, _win(0, sessions(3)))
    data = cell.to_json()
    assert Cell.from_json(data) == cell
    data["config"]["params_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        Cell.from_json(data)
