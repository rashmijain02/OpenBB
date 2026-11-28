"""Anti-overfitting validation framework (WFO / CPCV / PBO / DSR)."""

from openbb_backtest.validation.cpcv import (
    atomic_test_windows,
    cpcv,
    cpcv_paths,
    n_backtest_paths,
)
from openbb_backtest.validation.pbo import PBODetail, pbo, pbo_detail
from openbb_backtest.validation.report import build_validation_report, verdict
from openbb_backtest.validation.splitters import Fold, walk_forward
from openbb_backtest.validation.stats import (
    deflated_sharpe,
    expected_max_sharpe,
    min_backtest_length,
    min_backtest_length_exact,
    probabilistic_sharpe,
)

__all__ = [
    "Fold",
    "PBODetail",
    "atomic_test_windows",
    "build_validation_report",
    "cpcv",
    "cpcv_paths",
    "deflated_sharpe",
    "expected_max_sharpe",
    "min_backtest_length",
    "min_backtest_length_exact",
    "n_backtest_paths",
    "pbo",
    "pbo_detail",
    "probabilistic_sharpe",
    "verdict",
    "walk_forward",
]
