"""Qualify the statistical bridges against independent reference values (#1357).

Reads ``independent_references.json`` (hand-derived closed-form values, exact
CSCV / CPCV enumerations, and paper values verified against the public text),
evaluates each case through the production functions in
:mod:`~openbb_backtest.validation.stats`, :mod:`~openbb_backtest.validation.pbo`
and :mod:`~openbb_backtest.validation.cpcv`, and compares under the tolerance the
case declares:

- ``exact``: equality (rationals as ``"p/q"`` strings, integers, index tables);
- ``abs``: ``|got - expected| <= value``;
- ``half_ulp_published``: ``|got - published| <= 0.5 * 10**-digits`` (paper
  digits, checked as a separate ``<id>#paper`` row).

The reference file is data only; nothing here can regenerate it. Exposed through
``python -m openbb_backtest.validation.experiment qualify-stats``.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from openbb_backtest.validation import stats

# ``validation/__init__`` re-exports the ``pbo`` / ``cpcv`` functions under the
# submodule names; import the modules themselves.
_pbo = importlib.import_module("openbb_backtest.validation.pbo")
_cpcv = importlib.import_module("openbb_backtest.validation.cpcv")

DEFAULT_REFERENCES = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "unit"
    / "validation"
    / "fixtures"
    / "independent_references.json"
)


@dataclass(frozen=True)
class CaseResult:
    """One evaluated reference case."""

    case_id: str
    kind: str
    expected: Any
    got: Any
    tolerance: dict
    source: str
    passed: bool

    def as_dict(self) -> dict:
        """JSON-ready row: ``id``, ``kind``, ``expected``, ``got``, ``tolerance``, ``source``, ``passed``."""
        return {
            "id": self.case_id,
            "kind": self.kind,
            "expected": self.expected,
            "got": self.got,
            "tolerance": self.tolerance,
            "source": self.source,
            "passed": self.passed,
        }


def _dsr(inp: dict) -> float:
    return stats.deflated_sharpe(
        inp["sr"],
        inp["n_trials"],
        inp["skew"],
        inp["kurt"],
        inp["n_obs"],
        sr_variance=inp["sr_variance"],
    )


def _psr(inp: dict) -> float:
    return stats.probabilistic_sharpe(
        inp["sr"], inp["sr_benchmark"], inp["skew"], inp["kurt"], inp["n_obs"]
    )


def _expected_max(inp: dict) -> float:
    return stats.expected_max_sharpe(
        inp["n_trials"], sr_variance=inp.get("sr_variance", 1.0)
    )


def _pbo_case(inp: dict) -> dict:
    detail = _pbo.pbo_detail(
        np.asarray(inp["matrix"], dtype=float),
        n_groups=inp["n_groups"],
        statistic=inp["statistic"],
    )
    return {
        "pbo": detail.pbo,
        "partitions": [[p.is_best, p.oos_rank] for p in detail.partitions],
    }


def _cpcv_case(inp: dict) -> list[dict]:
    folds = _cpcv.cpcv(
        np.arange(inp["n_sessions"]),
        n_groups=inp["n_groups"],
        n_test_groups=inp["n_test_groups"],
        embargo=inp["embargo"],
        label_span=inp["label_span"],
    )
    return [
        {
            "test_idx": f.test_idx.tolist(),
            "train_idx": f.train_idx.tolist(),
            "test_windows": [w.tolist() for w in _cpcv.atomic_test_windows(f.test_idx)],
        }
        for f in folds
    ]


def _cpcv_paths(inp: dict) -> list:
    return [
        [list(cell) for cell in path]
        for path in _cpcv.cpcv_paths(inp["n_groups"], inp["n_test_groups"])
    ]


_EVALUATORS: dict[str, Callable[[dict], Any]] = {
    "dsr": _dsr,
    "psr": _psr,
    "expected_max": _expected_max,
    "expected_max_gap": lambda inp: stats.expected_max_sharpe(inp["n_trials"]),
    "minbtl_exact": lambda inp: stats.min_backtest_length_exact(
        inp["target_sr"], inp["n_trials"]
    ),
    "minbtl_approx": lambda inp: stats.min_backtest_length(
        inp["target_sr"], inp["n_trials"]
    ),
    "pbo": _pbo_case,
    "cpcv": _cpcv_case,
    "cpcv_paths": _cpcv_paths,
    "n_paths": lambda inp: _cpcv.n_backtest_paths(
        inp["n_groups"], inp["n_test_groups"]
    ),
}

_CPCV_KEYS = ("test_idx", "train_idx", "test_windows")


def _within(got: float, expected: float, tolerance: dict) -> bool:
    kind = tolerance["kind"]
    if kind == "abs":
        return abs(got - expected) <= float(tolerance["value"])
    if kind == "half_ulp_published":
        return abs(got - expected) <= 0.5 * 10.0 ** (-int(tolerance["digits"]))
    raise ValueError(f"tolerance kind {kind!r} is not numeric")


def _compare(case: dict, got: Any) -> tuple[Any, bool]:
    """Return ``(expected_view, passed)`` for one case."""
    kind, expected, tol = case["kind"], case["expected"], case["tolerance"]
    if kind == "pbo":
        want = {
            "pbo": float(Fraction(expected)),
            "partitions": [[r["is_best"], r["oos_rank"]] for r in case["partitions"]],
        }
        return want, got == want
    if kind == "cpcv":
        splits = [{k: split[k] for k in _CPCV_KEYS} for split in expected]
        return splits, got == splits
    if kind == "expected_max_gap":
        return expected, 0.0 < expected - got <= float(tol["value"])
    if tol["kind"] == "exact":
        return expected, got == expected
    return expected, _within(float(got), float(expected), tol)


def evaluate_case(case: dict) -> list[CaseResult]:
    """Evaluate one case (plus its ``#paper`` row when it carries a ``paper_check``)."""
    kind = case["kind"]
    if kind not in _EVALUATORS:
        raise ValueError(f"unknown reference kind {kind!r} in case {case['id']!r}")
    got = _EVALUATORS[kind](case["inputs"])
    expected, passed = _compare(case, got)
    rows = [
        CaseResult(
            case["id"], kind, expected, got, case["tolerance"], case["source"], passed
        )
    ]
    check = case.get("paper_check")
    if check:
        rows.append(
            CaseResult(
                f"{case['id']}#paper",
                kind,
                check["published"],
                got,
                check["tolerance"],
                check["source"],
                _within(float(got), float(check["published"]), check["tolerance"]),
            )
        )
    return rows


def qualify(path: Path = DEFAULT_REFERENCES) -> list[CaseResult]:
    """Evaluate every case in the reference file at ``path``.

    Raises
    ------
    ValueError
        If the file has no cases (an empty qualification is not a pass).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    if not cases:
        raise ValueError(f"no reference cases in {path}")
    results: list[CaseResult] = []
    for case in cases:
        results.extend(evaluate_case(case))
    return results
