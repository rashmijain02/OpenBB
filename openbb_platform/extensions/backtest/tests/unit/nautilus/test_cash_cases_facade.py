"""Hand-computed cash cases through the real facade and worker (#1356 T03).

Every run case of ``fixtures/cash_cases.json`` goes through
``run_router.execute_run`` (``backend="nautilus"``), the real worker
entrypoint (guards, admission, reviewed host, independent ledger) and the
event-replay fake engine, which has no settlement or staging of its own. The
projected result must equal the literals exactly. The literals are never
produced by code: there is no regeneration path (checked below).
"""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_backtest.adapters.nautilus import golden
from openbb_nautilus_worker.reviewed import registry

FIX = Path(__file__).parent / "fixtures"
CASES_PATH = FIX / "cash_cases.json"
DATA = json.loads(CASES_PATH.read_text("utf-8"))
RUN_CASES = sorted(DATA["cases"])


def _literal(name: str) -> dict:
    exp = DATA["cases"][name]["expected"]
    return {
        "positions": exp["positions"],
        "cash": exp["cash"],
        "equity": exp["equity"],
        "trades": [
            [i, s, side, q, Decimal(p), Decimal(c)]
            for i, s, side, q, p, c in exp["trades"]
        ],
        "booking_residual": Decimal(exp["booking_residual"]),
        "warnings": exp["warnings"],
    }


@pytest.fixture(scope="module", name="rows")
def rows_fixture():
    return {
        name: golden.run_case(
            DATA["cases"][name], None, "fake", sessions=DATA["sessions"]
        )
        for name in RUN_CASES
    }


def test_source_is_hand_computed():
    assert DATA["source"] == "hand-computed"
    assert set(RUN_CASES) == {"c1", "c1p", "c2", "c2b", "c3a", "c3b", "c4"}
    assert set(DATA["planner_cases"]) == {"c6"}


@pytest.mark.parametrize("name", RUN_CASES)
def test_cash_case_through_facade_matches_literals(rows, name):
    assert rows[name]["got"] == _literal(name)


def test_cash_cases_bind_the_reviewed_tuple(rows):
    for name in RUN_CASES:
        case = DATA["cases"][name]
        pin = registry.pin_for(case["strategy"], "1.0.0")
        assert rows[name]["spec_sha256"] == pin.spec_sha256
        assert rows[name]["code_sha256"] == pin.code_sha256
        assert rows[name]["qualified"] is False
    # timing and settlement are bound to the run
    assert rows["c1"]["execution_sha256"] != rows["c1p"]["execution_sha256"]
    assert rows["c2"]["execution_sha256"] != rows["c2b"]["execution_sha256"]


def test_unsupported_settlement_fails_closed():
    from openbb_backtest.errors import UnsupportedSemanticsError

    with pytest.raises(UnsupportedSemanticsError):
        golden.run_case(
            DATA["cases"]["c2"],
            None,
            "fake",
            sessions=DATA["sessions"],
            settlement="T+0",
        )


def test_golden_cli_all_cases_exact(capsys):
    assert golden.main(["--case", "all", "--runtime", "fake", "--format", "json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["passed"] is True
    assert set(rep["cases"]) == {*RUN_CASES, "c6"}
    assert all(r["passed"] for r in rep["cases"].values())


def test_golden_cli_t0_settlement_exits_2(capsys):
    args = ["--case", "c2", "--runtime", "fake", "--settlement", "T+0"]
    assert golden.main([*args, "--format", "json"]) == 2
    row = json.loads(capsys.readouterr().out)["cases"]["c2"]
    assert row["passed"] is False and row["error"] == "UnsupportedSemanticsError"
    assert "settlement" in row["message"]


def test_no_regen_path_for_cash_cases(capsys):
    """No code writes the literals: running every case leaves the file as is,
    and no source file pairs the fixture name with a regeneration switch."""
    before = hashlib.sha256(CASES_PATH.read_bytes()).hexdigest()
    golden.main(["--case", "all", "--runtime", "fake"])
    capsys.readouterr()
    assert hashlib.sha256(CASES_PATH.read_bytes()).hexdigest() == before
    root = Path(golden.__file__).resolve().parents[3]
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts or path == Path(__file__).resolve():
            continue
        text = path.read_text("utf-8", errors="replace")
        if "cash_cases" in text:
            assert "REGEN" not in text, f"{path.name} pairs cash_cases with regen"
            assert "json.dump(" not in text, f"{path.name} could write the cases"
