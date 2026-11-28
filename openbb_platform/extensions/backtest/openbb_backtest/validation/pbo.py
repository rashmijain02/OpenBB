"""Probability of Backtest Overfitting via CSCV (component 08, §2).

:func:`pbo` implements **Combinatorially-Symmetric Cross-Validation** from Bailey,
Borwein, López de Prado & Zhu, *The Probability of Backtest Overfitting*
(J. Computational Finance, 2017) — re-implemented from the public paper, never
from ``mlfinlab`` (Commons-Clause restricted, license rule §08).

Given a performance matrix ``M`` of shape ``(T_slices, N_configs)`` (each column a
strategy configuration, each row that config's performance on one time slice):

1. partition the ``T`` rows into ``S`` contiguous groups;
2. for each of the ``C(S, S/2)`` symmetric splits of the groups into equal
   in-sample (IS) / out-of-sample (OOS) halves, sum performance per config over
   each half;
3. take the IS-best config ``n*``; find its OOS **relative rank**
   ``ω = rank(n*) / (N + 1) ∈ (0, 1)`` and the logit ``λ = ln(ω / (1 − ω))``;
4. **PBO** is the fraction of partitions with ``λ ≤ 0`` — i.e. the IS-best config
   landed in the bottom OOS half (median or worse), the signature of overfitting.

:func:`pbo_detail` (#1357) exposes every partition's ``(IS-best, OOS rank,
logit)``, the declared tie rules, a ``"sharpe"`` performance statistic, and
returns ``pbo=None`` when PBO is undefined; :func:`pbo` keeps the legacy
contract (column sums, ``n_groups=16``, :class:`ValueError` when undefined).

A dominant config that always wins gives ``PBO = 0``; an anti-correlated config
whose IS win guarantees an OOS loss gives ``PBO = 1``; pure noise gives ``≈ 0.5``.
The function is pure and deterministic for a fixed matrix (no RNG inside).

See ``docs/designs/backtest-design/08-validation.md`` §2.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

import numpy as np

#: Performance statistics accepted for each IS / OOS half.
_STATISTICS: tuple[str, ...] = ("sum", "sharpe")
#: Cap on the CSCV group count chosen by :func:`pbo_detail` (``C(16, 8) = 12870``).
_MAX_AUTO_GROUPS = 16


@dataclass(frozen=True)
class PartitionOutcome:
    """One CSCV partition: the IS-best column, its OOS rank and the logit."""

    is_groups: tuple[int, ...]
    oos_groups: tuple[int, ...]
    is_best: int
    oos_rank: int
    logit: float


@dataclass(frozen=True)
class PBODetail:
    """PBO with every partition, or ``pbo=None`` when it is undefined.

    ``undefined_reason`` is one of ``fewer_than_two_configs``, ``too_few_slices``,
    ``too_few_rows_for_sharpe`` or ``zero_variance`` (``None`` when defined).
    """

    pbo: float | None
    n_groups: int
    statistic: str
    partitions: tuple[PartitionOutcome, ...]
    undefined_reason: str | None = None


def pbo(
    performance_matrix: np.ndarray,
    *,
    n_groups: int = 16,
    statistic: Literal["sum", "sharpe"] = "sum",
) -> float:
    """Probability of Backtest Overfitting of a config performance matrix.

    Parameters
    ----------
    performance_matrix
        Shape ``(T_slices, N_configs)``: column ``j`` is configuration ``j``'s
        performance (e.g. per-slice Sharpe or return) across ``T`` time slices.
    n_groups
        Number of contiguous row-groups ``S`` for CSCV (must be even and ``≤ T``);
        the partition count is ``C(S, S/2)``.
    statistic
        Performance of a config on an IS / OOS half: ``"sum"`` (default, legacy)
        of its rows, or ``"sharpe"`` = mean / sample std (``ddof=1``) of its rows,
        the paper's performance-ratio choice.

    Returns
    -------
    float
        PBO in ``[0, 1]`` — the fraction of symmetric IS/OOS partitions on which
        the in-sample-best config ranked in the bottom OOS half.

    Raises
    ------
    ValueError
        If the matrix is not 2-D, has fewer than 2 configs, ``n_groups`` is odd or
        exceeds the number of slices, or (``"sharpe"``) a half has fewer than 2
        rows or zero variance.
    """
    # Legacy contract: non-finite values are not rejected (numbers unchanged, D6).
    detail = _cscv_detail(
        performance_matrix, n_groups=n_groups, statistic=statistic, require_finite=False
    )
    if detail.pbo is None:
        shape = np.shape(performance_matrix)
        if detail.undefined_reason == "fewer_than_two_configs":
            raise ValueError(f"need at least 2 configs to compare, got {shape[1]}")
        if detail.undefined_reason == "too_few_slices":
            raise ValueError(
                f"n_groups ({n_groups}) cannot exceed the number of slices ({shape[0]})"
            )
        raise ValueError(f"PBO undefined: {detail.undefined_reason}")
    return detail.pbo


def pbo_detail(
    performance_matrix: np.ndarray,
    *,
    n_groups: int | None = None,
    statistic: Literal["sum", "sharpe"] = "sum",
) -> PBODetail:
    """CSCV over every symmetric partition, with declared tie rules.

    Columns are the compared configurations (callers order them canonically, e.g.
    by config id, because ties resolve by column position). Rules:

    - IS-best = the **first** column attaining the maximum IS performance;
    - OOS rank = ``#(oos < oos[best]) + 1``: OOS ties with the best count against
      it (conservative); ``ω = rank / (N + 1)``; a partition is overfit when
      ``logit(ω) ≤ 0`` (the exact median counts as overfit).

    ``n_groups=None`` uses the largest even count ``≤ min(T, 16)``, so a small
    matrix (``T ≤ 16``) enumerates every partition of its single-row groups.
    Undefined PBO (fewer than 2 configs or slices, a Sharpe half with fewer than 2
    rows or zero variance) is ``pbo=None`` — never ``0.0``.

    Raises
    ------
    ValueError
        If the matrix is not 2-D or not finite, ``n_groups`` is odd, or
        ``statistic`` is unknown.
    """
    return _cscv_detail(
        performance_matrix, n_groups=n_groups, statistic=statistic, require_finite=True
    )


def _cscv_detail(
    performance_matrix: np.ndarray,
    *,
    n_groups: int | None,
    statistic: str,
    require_finite: bool,
) -> PBODetail:
    """Shared CSCV body of :func:`pbo` and :func:`pbo_detail`."""
    matrix = np.asarray(performance_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"performance_matrix must be 2-D, got {matrix.ndim}-D")
    if statistic not in _STATISTICS:
        raise ValueError(f"statistic must be one of {_STATISTICS}, got {statistic!r}")
    if require_finite and not np.all(np.isfinite(matrix)):
        raise ValueError("performance_matrix must be finite")
    t_slices, n_configs = matrix.shape
    if n_groups is None:
        n_groups = min(_MAX_AUTO_GROUPS, t_slices - (t_slices % 2))
    elif n_groups % 2 != 0:
        raise ValueError(f"n_groups must be even for symmetric CSCV, got {n_groups}")

    def undefined(reason: str) -> PBODetail:
        return PBODetail(None, n_groups, statistic, (), reason)

    if n_configs < 2:
        return undefined("fewer_than_two_configs")
    if n_groups < 2 or n_groups > t_slices:
        return undefined("too_few_slices")
    if statistic == "sharpe" and t_slices // 2 < 2:
        return undefined("too_few_rows_for_sharpe")
    groups = np.array_split(np.arange(t_slices), n_groups)

    outcomes: list[PartitionOutcome] = []
    for is_groups, oos_groups in _cscv_partitions(n_groups):
        is_rows = np.concatenate([groups[g] for g in is_groups])
        oos_rows = np.concatenate([groups[g] for g in oos_groups])
        is_perf = _performance(matrix[is_rows], statistic)
        oos_perf = _performance(matrix[oos_rows], statistic)
        if is_perf is None or oos_perf is None:
            return undefined("zero_variance")

        best = int(np.argmax(is_perf))
        # Relative rank of the IS-best config among OOS performances, in (0, 1).
        rank = int(np.sum(oos_perf < oos_perf[best])) + 1
        omega = rank / (n_configs + 1)
        outcomes.append(
            PartitionOutcome(
                is_groups=tuple(is_groups),
                oos_groups=tuple(oos_groups),
                is_best=best,
                oos_rank=rank,
                logit=math.log(omega / (1.0 - omega)),
            )
        )

    overfit = np.asarray([o.logit for o in outcomes]) <= 0.0
    return PBODetail(float(np.mean(overfit)), n_groups, statistic, tuple(outcomes))


def _performance(rows: np.ndarray, statistic: str) -> np.ndarray | None:
    """Per-column performance of one half; ``None`` if a Sharpe is undefined."""
    if statistic == "sum":
        return rows.sum(axis=0)
    if rows.shape[0] < 2:
        return None
    std = rows.std(axis=0, ddof=1)
    if np.any(std == 0.0):
        return None
    return rows.mean(axis=0) / std


def _cscv_partitions(
    n_groups: int,
) -> Iterator[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Yield every symmetric ``(IS_groups, OOS_groups)`` split of ``n_groups``.

    Enumerates all ``C(S, S/2)`` ways to choose the in-sample half of the ``S``
    row-groups; the complement is the out-of-sample half. Deterministic ordering
    (``itertools.combinations``) so PBO is reproducible for a fixed matrix.
    """
    all_groups = range(n_groups)
    half = n_groups // 2
    for is_groups in combinations(all_groups, half):
        oos_groups = tuple(g for g in all_groups if g not in is_groups)
        yield is_groups, oos_groups
