"""Normalized fold-return matrix (#1357 T01, A1)."""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

import pytest
from openbb_backtest.validation.matrix import (
    FoldReturnMatrix,
    assemble,
    encode_returns,
    returns_from_equity,
)
from openbb_backtest.validation.trials import AttemptRecord

from trial_helpers import wfo_cells  # pylint: disable=import-error


def test_returns_from_decimal_curve():
    curve = [
        ("2024-01-02", Decimal("10000.00")),
        ("2024-01-03", Decimal("10100.00")),
        ("2024-01-04", Decimal("9999.00")),
        ("2024-01-05", Decimal("9999.00")),
    ]
    got = returns_from_equity(curve)
    # Hand values: 10100/10000-1 = 0.01; 9999/10100-1 = -101/10100; 0.
    assert got == [
        ("2024-01-03", 0.01),
        ("2024-01-04", float(Decimal(-101) / Decimal(10100))),
        ("2024-01-05", 0.0),
    ]
    assert got[1][1] == pytest.approx(-0.01, abs=1e-12)
    with pytest.raises(ValueError, match="ascending"):
        returns_from_equity([("2024-01-03", "1"), ("2024-01-02", "1")])
    with pytest.raises(ValueError, match="non-positive"):
        returns_from_equity([("2024-01-02", "0"), ("2024-01-03", "1")])


def test_long_form_canonical_and_hash_float_hex():
    rows = [
        ("b" * 64, 0, "2024-01-03", 0.1),
        ("a" * 64, 1, "2024-01-04", -0.25),
        ("a" * 64, 0, "2024-01-03", 1 / 3),
    ]
    m1 = FoldReturnMatrix.from_rows(rows)
    m2 = FoldReturnMatrix.from_rows(list(reversed(rows)))
    assert m1.rows == m2.rows
    assert [r[0][0] + r[2] for r in m1.rows] == [
        "a2024-01-03",
        "a2024-01-04",
        "b2024-01-03",
    ]
    text = "".join(f"{c},{o},{s},{float(r).hex()}\n" for c, o, s, r in m1.rows)
    assert m1.sha256 == hashlib.sha256(text.encode("ascii")).hexdigest()
    # A one-ulp change in one return changes the hash (float.hex is exact).
    import math  # pylint: disable=import-outside-toplevel

    bumped = [rows[0], rows[1], ("a" * 64, 0, "2024-01-03", math.nextafter(1 / 3, 1))]
    assert FoldReturnMatrix.from_rows(bumped).sha256 != m1.sha256
    with pytest.raises(ValueError, match="duplicate"):
        FoldReturnMatrix.from_rows(rows + [("a" * 64, 2, "2024-01-03", 0.0)])


def test_wide_columns_sorted_by_config_id():
    rows = []
    for cfg, ret in (("c" * 64, 0.3), ("a" * 64, 0.1), ("b" * 64, 0.2)):
        rows += [(cfg, 0, "2024-01-03", ret), (cfg, 0, "2024-01-02", -ret)]
    sessions, cols, mat = FoldReturnMatrix.from_rows(rows).wide()
    assert sessions == ["2024-01-02", "2024-01-03"]
    assert cols == ["a" * 64, "b" * 64, "c" * 64]
    assert mat.tolist() == [[-0.1, -0.2, -0.3], [0.1, 0.2, 0.3]]
    with pytest.raises(ValueError, match="session index"):
        FoldReturnMatrix.from_rows(rows[:-1]).wide()


def test_empty_matrix_from_nonempty_ledger_raises(caplog):
    cells = wfo_cells(1, 1)
    cell = cells[0]
    rec = AttemptRecord(
        attempt_id="x" * 64,
        trial_id=cell.trial_id,
        config_id=cell.config_id,
        base_dataset_id=cell.config.base_dataset_id,
        window_ordinal=0,
        attempt_no=1,
        status="ok",
        result_sha256="0" * 64,
        returns=(),
    )
    with caplog.at_level(logging.WARNING, logger="openbb_backtest.validation.matrix"):
        with pytest.raises(ValueError, match="empty matrix"):
            assemble(cells, [rec])
    assert any("0 return rows" in r.getMessage() for r in caplog.records)


def test_encode_returns_roundtrip():
    enc = encode_returns([("2024-01-02", 0.1)])
    assert enc == (("2024-01-02", (0.1).hex()),)
    assert float.fromhex(enc[0][1]) == 0.1
