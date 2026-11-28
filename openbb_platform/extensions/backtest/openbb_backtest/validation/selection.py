"""Selection-aware statistics over a trial matrix (#1357, plan §2.5, D3/D5).

Bridges the T01 assembler to the T02 primitives on the Nautilus path:

- PBO over **configurations as columns** (sorted ``config_id``), ``None`` when
  undefined (never 0.0).
- DSR of the selected best configuration with ``N`` from the ledger and
  ``V = var(per-config per-observation SR, ddof=1)`` over ok configurations;
  ``N = 1`` gives a zero benchmark. Skew and non-excess kurtosis are the sample
  moment ratios ``m3 / m2**1.5`` and ``m4 / m2**2`` of the selected series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from openbb_backtest.validation.matrix import FoldReturnMatrix
from openbb_backtest.validation.pbo import pbo_detail
from openbb_backtest.validation.stats import deflated_sharpe


@dataclass(frozen=True)
class SelectionStats:  # pylint: disable=too-many-instance-attributes
    """What validate reports from a complete or partial matrix."""

    n_trials: int
    config_ids: tuple[str, ...]
    sharpes: tuple[float, ...]
    best_config_id: str
    best_sharpe: float
    sr_variance: float
    skew: float
    kurt: float
    n_obs: int
    deflated_sharpe: float
    pbo: float | None
    pbo_undefined_reason: str | None


def _moments(x: np.ndarray) -> tuple[float, float]:
    d = x - x.mean()
    m2 = float(np.mean(d**2))
    if m2 == 0.0:
        return 0.0, 3.0
    return float(np.mean(d**3)) / m2**1.5, float(np.mean(d**4)) / m2**2


def selection_statistics(  # pylint: disable=too-many-locals
    matrix: FoldReturnMatrix,
    n_trials: int,
    *,
    statistic: Literal["sum", "sharpe"] = "sharpe",
    n_groups: int | None = None,
) -> SelectionStats:
    """Compute N, V, DSR and PBO from the wide view of ``matrix``."""
    _sessions, cols, mat = matrix.wide()
    if not cols or mat.shape[0] < 2:
        raise ValueError("selection statistics need >= 1 config and >= 2 sessions")
    if n_trials < len(cols):
        raise ValueError("n_trials understates the configurations in the matrix")
    std = mat.std(axis=0, ddof=1)
    if np.any(std == 0.0):
        raise ValueError("zero_variance column in the matrix")
    sharpes = mat.mean(axis=0) / std
    best = int(np.argmax(sharpes))  # first index on ties; columns are sorted
    variance = float(np.var(sharpes, ddof=1)) if len(cols) > 1 else 0.0
    skew, kurt = _moments(mat[:, best])
    dsr = deflated_sharpe(
        float(sharpes[best]), n_trials, skew, kurt, mat.shape[0], sr_variance=variance
    )
    pbo_value: float | None
    why: str | None
    if len(cols) < 2:
        pbo_value, why = None, "single_configuration"
    else:
        detail = pbo_detail(mat, n_groups=n_groups, statistic=statistic)
        pbo_value, why = detail.pbo, detail.undefined_reason
    if pbo_value is not None and math.isnan(pbo_value):
        pbo_value, why = None, "nan"
    return SelectionStats(
        n_trials=n_trials,
        config_ids=tuple(cols),
        sharpes=tuple(float(s) for s in sharpes),
        best_config_id=cols[best],
        best_sharpe=float(sharpes[best]),
        sr_variance=variance,
        skew=skew,
        kurt=kurt,
        n_obs=int(mat.shape[0]),
        deflated_sharpe=float(dsr),
        pbo=pbo_value,
        pbo_undefined_reason=why,
    )
