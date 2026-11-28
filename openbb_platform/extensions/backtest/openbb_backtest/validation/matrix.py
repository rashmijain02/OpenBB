"""Normalized fold-return matrix and experiment assembly (#1357, plan §2.2-2.3).

The stored artifact is the **long canonical form**: rows
``(config_id, window_ordinal, session, ret)`` sorted by ``(config_id, session)``,
``ret = E_t / E_{t-1} - 1`` computed in ``Decimal`` from the projected equity
curve and stored as float64. The hash uses ``float.hex`` so it is exact and
platform-stable. The first session of a window has no prior mark and no row.

The **wide view** (rows = sessions ascending, columns = ``config_id`` sorted
lexicographically) feeds PBO/DSR; column order never depends on completion
order or worker split.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import numpy as np

from openbb_backtest.validation.trials import (
    AttemptRecord,
    Cell,
    cell_state,
    n_trials_dsr,
)

logger = logging.getLogger(__name__)

Row = tuple[str, int, str, float]


def returns_from_equity(
    curve: Sequence[tuple[date | str, Decimal | str]],
) -> list[tuple[str, float]]:
    """Return simple returns from a Decimal equity curve (one fewer row than marks)."""
    out: list[tuple[str, float]] = []
    prev: Decimal | None = None
    prev_session: str | None = None
    for session, equity in curve:
        iso = session if isinstance(session, str) else session.isoformat()
        value = Decimal(str(equity))
        if prev_session is not None and iso <= prev_session:
            raise ValueError("equity curve sessions must be strictly ascending")
        if prev is not None:
            if prev <= 0:
                raise ValueError(f"non-positive equity before {iso}; return undefined")
            out.append((iso, float(value / prev - 1)))
        prev, prev_session = value, iso
    return out


def encode_returns(returns: Iterable[tuple[str, float]]) -> tuple[tuple[str, str], ...]:
    """``(session, float.hex(ret))`` pairs as stored on an ``ok`` attempt."""
    return tuple((s, float(r).hex()) for s, r in returns)


@dataclass(frozen=True)
class FoldReturnMatrix:
    """Long canonical form plus its exact hash."""

    rows: tuple[Row, ...]

    @classmethod
    def from_rows(cls, rows: Iterable[Row]) -> FoldReturnMatrix:
        """Sort into canonical order; duplicate (config, session) is refused."""
        ordered = tuple(sorted(rows, key=lambda r: (r[0], r[2], r[1])))
        seen = set()
        for cfg, _ordinal, session, _ret in ordered:
            if (cfg, session) in seen:
                raise ValueError(f"duplicate session {session} for config {cfg[:12]}")
            seen.add((cfg, session))
        return cls(ordered)

    @property
    def sha256(self) -> str:
        """Hash over ``config_id,ordinal,session,float.hex(ret)`` lines."""
        h = hashlib.sha256()
        for cfg, ordinal, session, ret in self.rows:
            h.update(f"{cfg},{ordinal},{session},{float(ret).hex()}\n".encode("ascii"))
        return h.hexdigest()

    @property
    def config_ids(self) -> list[str]:
        """Columns of the wide view (lexicographic)."""
        return sorted({r[0] for r in self.rows})

    def to_jsonl(self) -> str:
        """Canonical JSONL text (``ret`` as ``float.hex``)."""
        return "".join(
            f'{{"config_id":"{c}","ret":"{float(r).hex()}","session":"{s}","window_ordinal":{o}}}\n'
            for c, o, s, r in self.rows
        )

    def wide(self) -> tuple[list[str], list[str], np.ndarray]:
        """``(sessions, config_ids, matrix[T, N])``; every column needs the same sessions."""
        cols = self.config_ids
        by_cfg: dict[str, dict[str, float]] = {c: {} for c in cols}
        for cfg, _o, session, ret in self.rows:
            by_cfg[cfg][session] = ret
        sessions = sorted(by_cfg[cols[0]]) if cols else []
        for c in cols:
            if sorted(by_cfg[c]) != sessions:
                raise ValueError(f"config {c[:12]} does not share the session index")
        mat = np.array([[by_cfg[c][s] for c in cols] for s in sessions], dtype=float)
        return sessions, cols, mat.reshape(len(sessions), len(cols))


@dataclass
class Assembly:  # pylint: disable=too-many-instance-attributes
    """Ledger -> counts, exclusions and (when sound) the matrix."""

    status: Literal["ok", "incomplete", "failed_closed", "mixed_dataset"]
    n_planned: int
    n_ok: int
    n_failed: int
    n_excluded: int
    n_trials_dsr: int
    external_trials: int
    matrix: FoldReturnMatrix | None
    matrix_complete: bool
    exclusions: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Fields for ``models.ExperimentSummary`` (minus id / policy)."""
        return {
            "status": self.status,
            "n_planned": self.n_planned,
            "n_ok": self.n_ok,
            "n_failed": self.n_failed,
            "n_excluded": self.n_excluded,
            "n_trials_dsr": self.n_trials_dsr,
            "external_trials": self.external_trials,
            "matrix_sha256": self.matrix.sha256 if self.matrix is not None else None,
            "matrix_complete": self.matrix_complete,
            "exclusions": list(self.exclusions),
        }


_REASON_BY_CODE: Mapping[str, str] = {
    "admission": "admission_rejected",
    "unsupported_semantics": "unsupported_semantics",
    "insufficient_sessions": "insufficient_sessions",
    "zero_variance": "zero_variance",
}


def _inconsistent(planned: Sequence[Cell], records: Sequence[AttemptRecord]) -> bool:
    """Return whether an attempt disagrees with its planned cell on the dataset."""
    dataset_of = {c.trial_id: c.config.base_dataset_id for c in planned}
    return any(
        r.trial_id in dataset_of and r.base_dataset_id != dataset_of[r.trial_id]
        for r in records
    )


def assemble(  # pylint: disable=too-many-locals,too-many-branches,too-many-arguments
    planned: Sequence[Cell],
    records: Sequence[AttemptRecord],
    *,
    external_trials: int = 0,
    max_attempts: int = 2,
    dataset_id: str | None = None,
    config_keys: Iterable[str] | None = None,
) -> Assembly:
    """Fold a planned list and its attempts into an :class:`Assembly`.

    Dataset generations (CODE-2b): the matrix, the cell counts and the
    exclusions cover only the generation of ``dataset_id`` (default: the
    dataset of the last planned cell, i.e. the latest planned version), so a
    data refresh never mixes datasets in one matrix and never leaves the
    experiment unusable. ``N`` counts every configuration of every generation
    (:func:`n_trials_dsr`).

    Current plan selection (CODE-2c): ``config_keys`` (default: every
    configuration of the selected generation) narrows the matrix, the cell
    counts and the exclusions to the current plan's configurations, so a
    narrowed grid still yields a complete matrix. Configurations of earlier
    plans affect only ``N``.

    Order-independent in ``records``. Matrix columns are configurations whose
    every planned window is ``ok``; every other configuration is excluded with a
    reason, and any exclusion makes the matrix incomplete. A conflict in any
    generation or earlier plan fails the experiment closed (nondeterminism is
    never forgotten by a refresh or a grid change); an attempt that disagrees with its planned cell on the
    dataset (a corrupted ledger) yields ``mixed_dataset`` and no matrix.
    """
    n = n_trials_dsr(records, external_trials, planned=planned)
    if dataset_id is None and planned:
        dataset_id = planned[-1].config.base_dataset_id
    keys = None if config_keys is None else set(config_keys)

    def in_plan(cell: Cell) -> bool:
        return cell.config.base_dataset_id == dataset_id and (
            keys is None or cell.config.config_key in keys
        )

    all_states = [
        (c, cell_state(c.trial_id, c.config_id, records, max_attempts)) for c in planned
    ]
    old_conflicts = sorted(
        {
            c.config_id
            for c, st in all_states
            if st.state == "conflict" and not in_plan(c)
        }
    )
    current = [(c, st) for c, st in all_states if in_plan(c)]
    states = [st for _c, st in current]
    counts = {
        s: sum(1 for st in states if st.state == s)
        for s in ("ok", "failed", "excluded")
    }
    by_cfg: dict[str, list[Any]] = {}
    for cell, st in current:
        by_cfg.setdefault(cell.config_id, []).append((cell, st))
    exclusions: list[dict[str, str]] = []
    good: list[str] = []
    conflict = False
    for cfg in sorted(by_cfg):
        sts = [st for _c, st in by_cfg[cfg]]
        if any(st.state == "conflict" for st in sts):
            conflict = True
            exclusions.append({"config_id": cfg, "reason": "conflict"})
        elif all(st.state == "ok" for st in sts):
            good.append(cfg)
        else:
            bad = next(st for st in sts if st.state != "ok")
            if bad.state in ("failed", "excluded"):
                reason = _REASON_BY_CODE.get(bad.error_code or "", "worker_failed")
                if bad.state == "excluded" and bad.reason in _REASON_BY_CODE.values():
                    reason = bad.reason
            else:
                reason = "incomplete_windows"
            exclusions.append({"config_id": cfg, "reason": reason})
    # A conflict on an older dataset or an earlier plan still fails closed.
    for cfg in old_conflicts:
        conflict = True
        exclusions.append({"config_id": cfg, "reason": "conflict"})
    # Attempts for configurations outside the plan still count in N; list them.
    for cfg in sorted({r.config_id for r in records} - {c.config_id for c in planned}):
        exclusions.append({"config_id": cfg, "reason": "incomplete_windows"})
    base: dict[str, Any] = {
        "n_planned": len(current),
        "n_ok": counts["ok"],
        "n_failed": counts["failed"],
        "n_excluded": counts["excluded"],
        "n_trials_dsr": n,
        "external_trials": external_trials,
        "exclusions": exclusions,
    }
    if conflict:
        return Assembly(
            status="failed_closed", matrix=None, matrix_complete=False, **base
        )
    if _inconsistent(planned, records):
        return Assembly(
            status="mixed_dataset", matrix=None, matrix_complete=False, **base
        )
    rows: list[Row] = []
    for cfg in good:
        for cell, st in by_cfg[cfg]:
            rows.extend(
                (cfg, cell.window.ordinal, s, float.fromhex(h))
                for s, h in st.ok_record.returns
            )
    if good and not rows:
        logger.warning(
            "assemble: %d ok configurations produced 0 return rows", len(good)
        )
        raise ValueError("empty matrix from a non-empty ledger (no return rows)")
    matrix = FoldReturnMatrix.from_rows(rows) if rows else None
    complete = not exclusions and matrix is not None
    return Assembly(
        status="ok" if complete else "incomplete",
        matrix=matrix,
        matrix_complete=complete,
        **base,
    )
