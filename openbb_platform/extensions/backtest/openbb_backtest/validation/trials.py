"""Trial identity, the append-only trial ledger and the counting rules (#1357).

Pure module: no engine, no worker, no network. Identity is content-addressed
over canonical JSON (sorted keys, no whitespace, ``Decimal`` as string):

- ``config_id`` binds the backend, the reviewed strategy hashes (spec, code,
  param schema, params, execution), the base dataset, the engine/worker versions
  and the fixed precision. Equivalent params share one ``params_sha256`` (P16
  normalisation), so they are one configuration, never an inflated N.
- ``trial_id`` = ``config_id`` + window; ``attempt_id`` = trial + attempt number +
  spawn nonce.

Counting rules ("never understate", plan §2.3): ``N`` = distinct
configurations by their dataset-independent ``config_key``, over every planned
generation (failed, excluded and admission-rejected count; retries never add;
the same configuration re-run on refreshed data never adds, CODE-2b) +
``external_trials``. Two ``ok`` attempts that disagree fail the experiment
closed. Only transient errors are retried. Nothing in the ledger is ever
deleted or overwritten.

Dataset generations (CODE-2b): every planned version holds the cells of one
``base_dataset_id``; a generation is all planned cells of one dataset. The
return matrix comes from one generation only (see ``matrix.assemble``).

Experiment identity excludes the configuration set (CODE-2c): a plan with a
changed grid re-opens the same ledger and appends its new cells as a planned
version, exactly like a refresh. The matrix covers the current plan's cells
only; configurations of earlier plans affect only ``N``. ``external_trials`` is
not part of the identity either: each run's declaration is recorded in
``external.jsonl`` and the effective value is the maximum ever declared, so
``N`` never decreases.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

AttemptStatus = Literal["ok", "failed", "excluded"]
WindowPolicy = Literal["continuous", "per_fold"]

#: Error classes that may succeed on a fresh spawn (plan §2.3 rule 5).
RETRYABLE_CODES = frozenset({"process", "timeout", "spawn"})

#: Exclusion reasons (plan §2.3 rule 3).
EXCLUSION_REASONS = frozenset(
    {
        "worker_failed",
        "admission_rejected",
        "unsupported_semantics",
        "incomplete_windows",
        "zero_variance",
        "insufficient_sessions",
        "conflict",
    }
)

_CONFIG_V = "trial-config/1"
_TRIAL_V = "trial/1"


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"not canonical-JSON serialisable: {type(obj).__name__}")


def canonical(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, ``Decimal`` as string."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), default=_default, allow_nan=False
    )


def sha256_canonical(obj: Any) -> str:
    """SHA-256 hex of :func:`canonical` ``obj``."""
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfigIdentity:  # pylint: disable=too-many-instance-attributes
    """Everything that makes two runs the same configuration."""

    backend: str
    strategy_id: str
    strategy_version: str
    spec_sha256: str
    code_sha256: str
    param_schema_sha256: str
    params_sha256: str
    execution_sha256: str
    base_dataset_id: str
    engine_version: str
    worker_version: str
    fixed_precision: int

    @property
    def config_id(self) -> str:
        """Content hash of every binding field (window excluded)."""
        return sha256_canonical({"v": _CONFIG_V, **asdict(self)})

    @property
    def config_key(self) -> str:
        """Hash of every identity field except ``base_dataset_id`` (CODE-2b).

        The same configuration re-run on refreshed data keeps its key, so it
        is one trial for ``N``. The hash is the dataset-independent experiment
        spec entry, so changing it changes every ``experiment_id``.
        """
        fields = asdict(self)
        del fields["base_dataset_id"]
        return sha256_canonical(fields)

    @classmethod
    def from_binding(  # pylint: disable=too-many-arguments
        cls,
        binding: Any,
        *,
        base_dataset_id: str,
        engine_version: str,
        worker_version: str,
        fixed_precision: int,
        backend: str = "nautilus",
    ) -> ConfigIdentity:
        """Build from a reviewed ``registry.Binding`` (duck-typed)."""
        return cls(
            backend=backend,
            strategy_id=binding.strategy_id,
            strategy_version=binding.version,
            spec_sha256=binding.spec_sha256,
            code_sha256=binding.code_sha256,
            param_schema_sha256=binding.param_schema_sha256,
            params_sha256=binding.params_sha256,
            execution_sha256=binding.execution_sha256,
            base_dataset_id=base_dataset_id,
            engine_version=engine_version,
            worker_version=worker_version,
            fixed_precision=fixed_precision,
        )


@dataclass(frozen=True)
class Window:  # pylint: disable=too-many-instance-attributes
    """One evaluation window (a contiguous run of sessions)."""

    policy: WindowPolicy
    method: str
    fold_params_sha256: str
    ordinal: int
    start_session: str
    end_session: str
    session_count: int
    sessions_sha256: str

    @classmethod
    def from_sessions(
        cls,
        *,
        policy: WindowPolicy,
        method: str,
        fold_params: Mapping[str, Any],
        ordinal: int,
        sessions: Sequence[date | str],
    ) -> Window:
        """Build a window from its ordered sessions (non-empty, strictly ascending)."""
        iso = [s if isinstance(s, str) else s.isoformat() for s in sessions]
        if not iso:
            raise ValueError("a window needs at least one session")
        if any(a >= b for a, b in zip(iso, iso[1:])):
            raise ValueError("window sessions must be strictly ascending")
        return cls(
            policy=policy,
            method=method,
            fold_params_sha256=sha256_canonical(dict(fold_params)),
            ordinal=ordinal,
            start_session=iso[0],
            end_session=iso[-1],
            session_count=len(iso),
            sessions_sha256=sha256_canonical(iso),
        )


def trial_id(config_id: str, window: Window) -> str:
    """Identity of one (configuration, window) cell."""
    return sha256_canonical(
        {"v": _TRIAL_V, "config_id": config_id, "window": asdict(window)}
    )


def attempt_id(trial: str, attempt_no: int, spawn_nonce: str) -> str:
    """Identity of one attempt at a cell."""
    nonce = hashlib.sha256(spawn_nonce.encode("utf-8")).hexdigest()
    return sha256_canonical(
        {"trial_id": trial, "attempt_no": attempt_no, "nonce": nonce}
    )


@dataclass(frozen=True)
class Cell:
    """A planned unit of work: one configuration over one window."""

    config: ConfigIdentity
    window: Window
    label: str = ""

    @property
    def config_id(self) -> str:
        """The configuration hash."""
        return self.config.config_id

    @property
    def trial_id(self) -> str:
        """The cell hash."""
        return trial_id(self.config_id, self.window)

    def to_json(self) -> dict[str, Any]:
        """Planned-list record."""
        return {
            "trial_id": self.trial_id,
            "config_id": self.config_id,
            "config": asdict(self.config),
            "window": asdict(self.window),
            "label": self.label,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Cell:
        """Inverse of :meth:`to_json`; refuses a record whose hashes do not match."""
        cell = cls(
            config=ConfigIdentity(**data["config"]),
            window=Window(**data["window"]),
            label=data.get("label", ""),
        )
        if cell.trial_id != data["trial_id"] or cell.config_id != data["config_id"]:
            raise ValueError("planned cell hash mismatch (tampered planned list)")
        return cell


@dataclass(frozen=True)
class AttemptRecord:  # pylint: disable=too-many-instance-attributes
    """One attempt at one cell. Ledger records are append-only."""

    attempt_id: str
    trial_id: str
    config_id: str
    base_dataset_id: str
    window_ordinal: int
    attempt_no: int
    status: AttemptStatus
    error_code: str | None = None
    reason: str | None = None
    result_sha256: str | None = None
    window_dataset_id: str | None = None
    binding_sha256: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    #: ``[[session_iso, float.hex(ret)], ...]`` for ``ok`` attempts.
    returns: tuple[tuple[str, str], ...] = field(default=())

    def to_json(self) -> dict[str, Any]:
        """Ledger line."""
        data = asdict(self)
        data["returns"] = [list(r) for r in self.returns]
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> AttemptRecord:
        """Inverse of :meth:`to_json`."""
        values = dict(data)
        values["returns"] = tuple(
            (str(s), str(h)) for s, h in values.get("returns", ())
        )
        return cls(**values)


def returns_sha256(returns: Iterable[tuple[str, str]]) -> str:
    """Hash of an attempt's ``(session, float.hex)`` series."""
    return sha256_canonical([list(r) for r in returns])


def _append_jsonl(path: Path, line: str) -> None:
    """Append one fsynced JSONL line, first repairing a torn tail.

    A crash mid-append leaves a last line without a newline. Appending to it would
    glue the new record onto the fragment and the reader would drop both. The
    fragment was never committed, so it is truncated back to the last newline
    (a tail that is complete JSON merely missing its newline is kept and
    terminated instead, never losing a record).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            try:
                json.loads(data[cut:].decode("utf-8"))
                prefix = b"\n"
            except (UnicodeDecodeError, json.JSONDecodeError):
                prefix = b""
                logger.warning("dropping torn tail of %s before append", path)
                with path.open("r+b") as fh:
                    fh.truncate(cut)
                    fh.flush()
                    os.fsync(fh.fileno())
            line = prefix.decode() + line
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


class TrialLedger:
    """Append-only JSONL ledger under ``<root>/experiments/<experiment_id>/``.

    ``planned.json`` must be written before the first attempt is appended so that
    completeness is always checkable. Each record is flushed and fsynced.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @classmethod
    def for_experiment(cls, runs_root: Path, experiment_id: str) -> TrialLedger:
        """Ledger for one experiment under ``runs_root/experiments``."""
        if len(experiment_id) != 64 or any(
            c not in "0123456789abcdef" for c in experiment_id
        ):
            raise ValueError("experiment_id must be a sha256 hex digest")
        return cls(Path(runs_root) / "experiments" / experiment_id)

    @property
    def planned_path(self) -> Path:
        """``planned.json``."""
        return self.directory / "planned.json"

    @property
    def ledger_path(self) -> Path:
        """``ledger.jsonl``."""
        return self.directory / "ledger.jsonl"

    def _write_once(self, name: str, payload: Any) -> None:
        path = self.directory / name
        text = canonical(payload)
        if path.exists():
            if path.read_text(encoding="utf-8") != text:
                raise ValueError(f"{name} already exists with different content")
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def write_spec(self, spec: Mapping[str, Any]) -> None:
        """Persist the experiment spec (write-once)."""
        self._write_once("spec.json", dict(spec))

    def _planned_paths(self) -> list[Path]:
        """``planned.json`` then ``planned.v2.json`` .. in order (fail closed)."""
        if not self.planned_path.exists():
            if any(self.directory.glob("planned.v*.json")):
                raise ValueError("planned list versions without planned.json")
            return []
        paths = [self.planned_path]
        extra = sorted(self.directory.glob("planned.v*.json"))
        for version in range(2, len(extra) + 2):
            path = self.directory / f"planned.v{version}.json"
            if not path.exists():
                raise ValueError("planned list versions are not contiguous")
            paths.append(path)
        return paths

    def write_planned(self, cells: Sequence[Cell]) -> None:
        """Persist the planned cells before any dispatch (append-only, versioned).

        The first plan is ``planned.json``. A re-plan of the same experiment
        that adds cells (CODE-2: refreshed data gives new configuration ids;
        CODE-2c: a changed grid adds configurations) writes only the new cells to the next ``planned.v<k>.json``; earlier
        versions are never rewritten. A re-plan adding nothing writes nothing.
        The new cells of one write must share one ``base_dataset_id``.
        """
        known = {c.trial_id for c in self.planned()}
        fresh = [c for c in sorted(cells, key=_cell_key) if c.trial_id not in known]
        fresh = list({c.trial_id: c for c in fresh}.values())
        if not fresh:
            return
        datasets = {c.config.base_dataset_id for c in fresh}
        if len(datasets) > 1:  # one planned version = one dataset (CODE-2b)
            raise ValueError("a planned version must cover exactly one dataset")
        version = len(self._planned_paths()) + 1
        name = "planned.json" if version == 1 else f"planned.v{version}.json"
        self._write_once(name, [c.to_json() for c in fresh])

    def planned_versions(self) -> list[list[Cell]]:
        """Planned cells per version, verified (fail closed on any inconsistency).

        Raises :class:`ValueError` for a tampered cell, a trial planned twice,
        or a version whose cells disagree on ``base_dataset_id`` (a version is
        written from one plan, hence one dataset: CODE-2b).
        """
        out: list[list[Cell]] = []
        seen: set[str] = set()
        for path in self._planned_paths():
            version: list[Cell] = []
            for data in json.loads(path.read_text("utf-8")):
                cell = Cell.from_json(data)
                if cell.trial_id in seen:
                    raise ValueError("duplicate trial in planned list versions")
                seen.add(cell.trial_id)
                version.append(cell)
            if len({c.config.base_dataset_id for c in version}) > 1:
                raise ValueError(
                    f"inconsistent ledger: {path.name} mixes base datasets"
                    " (mixed_dataset)"
                )
            out.append(version)
        return out

    def planned(self) -> list[Cell]:
        """Every planned cell over all versions, in version order."""
        return [cell for version in self.planned_versions() for cell in version]

    @property
    def external_path(self) -> Path:
        """``external.jsonl``: every increase of the declared external trials."""
        return self.directory / "external.jsonl"

    def declared_external(self) -> int:
        """Largest ``external_trials`` ever declared (0 when none; fail closed).

        A torn final line is ignored like a torn ledger line; any other
        unreadable or negative entry raises :class:`ValueError`.
        """
        if not self.external_path.exists():
            return 0
        best = 0
        lines = self.external_path.read_text("utf-8").splitlines()
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                value = json.loads(line)["external_trials"]
            except (json.JSONDecodeError, TypeError, KeyError):
                if i == len(lines) - 1:
                    logger.warning("ignoring torn final line in %s", self.external_path)
                    continue
                raise ValueError("unreadable external.jsonl entry") from None
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("invalid external_trials entry in external.jsonl")
            best = max(best, value)
        return best

    def declare_external(self, external_trials: int) -> int:
        """Record this run's ``external_trials``; return the effective maximum.

        CODE-2c: the declaration is a per-run input, not part of the experiment
        identity, so changing it never opens a new ledger. The effective value
        is the maximum ever declared, so a lower declaration never lowers ``N``.
        Only an increase is appended (append-only, fsynced).
        """
        if external_trials < 0:
            raise ValueError("external_trials must be >= 0")
        prior = self.declared_external()
        if external_trials > prior:
            _append_jsonl(
                self.external_path,
                canonical({"external_trials": int(external_trials)}) + "\n",
            )
        return max(prior, int(external_trials))

    def append(self, record: AttemptRecord) -> None:
        """Append one attempt record (refused before the planned list exists)."""
        if not self.planned_path.exists():
            raise RuntimeError("planned.json must be written before any attempt")
        _append_jsonl(self.ledger_path, canonical(record.to_json()) + "\n")

    def records(self) -> list[AttemptRecord]:
        """Every attempt in append order (a torn final line is ignored).

        The returns hash of every ``ok`` record is recomputed on read; a record
        whose stored ``result_sha256`` does not match its returns (an edited
        ledger) fails closed with :class:`ValueError`, wherever it sits.
        """
        if not self.ledger_path.exists():
            return []
        out: list[AttemptRecord] = []
        lines = self.ledger_path.read_text("utf-8").splitlines()
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = AttemptRecord.from_json(json.loads(line))
            except (json.JSONDecodeError, TypeError, KeyError):
                if i == len(lines) - 1:
                    logger.warning(
                        "ignoring torn final ledger line in %s", self.ledger_path
                    )
                    continue
                raise
            if record.status == "ok" and (
                record.result_sha256 != returns_sha256(record.returns)
            ):
                raise ValueError(
                    f"ledger record {record.attempt_id[:12]} returns do not match"
                    " result_sha256 (tampered ledger)"
                )
            out.append(record)
        return out


def _cell_key(cell: Cell) -> tuple[str, int, str]:
    return (cell.config_id, cell.window.ordinal, cell.trial_id)


@dataclass(frozen=True)
class CellState:
    """Terminal or pending state of one cell, derived from its attempts."""

    trial_id: str
    config_id: str
    state: Literal["ok", "failed", "excluded", "conflict", "pending"]
    attempts: int
    error_code: str | None
    reason: str | None
    ok_record: AttemptRecord | None


def cell_state(
    trial: str, config: str, records: Sequence[AttemptRecord], max_attempts: int
) -> CellState:
    """Fold one cell's attempts into a state (order-independent)."""
    mine = [r for r in records if r.trial_id == trial]
    oks = [r for r in mine if r.status == "ok"]
    if oks:
        if len({r.result_sha256 for r in oks}) > 1:
            return CellState(
                trial,
                config,
                "conflict",
                len(mine),
                "conflict",
                "nondeterministic",
                None,
            )
        best = min(oks, key=lambda r: (r.attempt_no, r.attempt_id))
        return CellState(trial, config, "ok", len(mine), None, None, best)
    if not mine:
        return CellState(trial, config, "pending", 0, None, None, None)
    excluded = sorted(
        (r for r in mine if r.status == "excluded"), key=lambda r: r.attempt_no
    )
    if excluded:
        r = excluded[0]
        return CellState(
            trial, config, "excluded", len(mine), r.error_code, r.reason, None
        )
    last = max(mine, key=lambda r: (r.attempt_no, r.attempt_id))
    terminal = (
        any(r.error_code not in RETRYABLE_CODES for r in mine)
        or len(mine) >= max_attempts
    )
    state: Literal["failed", "pending"] = "failed" if terminal else "pending"
    return CellState(
        trial, config, state, len(mine), last.error_code, last.reason, None
    )


def n_trials_dsr(
    records: Iterable[AttemptRecord],
    external_trials: int = 0,
    *,
    planned: Iterable[Cell] = (),
) -> int:
    """``N`` for DSR: distinct configurations ever planned or attempted + external.

    A configuration is its dataset-independent ``config_key`` (CODE-2b): the
    same configuration planned on several dataset generations is one trial,
    and a configuration planned only on an old dataset still counts. Every
    status counts (failed, excluded, admission-rejected, pending). An attempt
    whose cell is not in ``planned`` counts by its ``config_id`` (never less).
    """
    if external_trials < 0:
        raise ValueError("external_trials must be >= 0")
    key_of = {c.config_id: c.config.config_key for c in planned}
    keys = set(key_of.values()) | {
        key_of.get(r.config_id, r.config_id) for r in records
    }
    return len(keys) + int(external_trials)


@dataclass
class Bounds:
    """Plan-time limits; exceeding them fails closed before any spawn."""

    max_configs: int = 64
    max_cells: int = 512
    max_attempts: int = 2


class ExperimentTooLargeError(ValueError):
    """The planned experiment exceeds :class:`Bounds` (never truncated)."""


def check_bounds(cells: Sequence[Cell], bounds: Bounds) -> None:
    """Raise :class:`ExperimentTooLargeError` when the plan is over the limits."""
    n_configs = len({c.config_id for c in cells})
    if n_configs > bounds.max_configs or len(cells) > bounds.max_cells:
        raise ExperimentTooLargeError(
            f"experiment_too_large: {n_configs} configs / {len(cells)} cells exceeds "
            f"{bounds.max_configs} / {bounds.max_cells}"
        )


@dataclass(frozen=True)
class CellOutcome:
    """What an executor reports for one attempt."""

    status: AttemptStatus
    error_code: str | None = None
    reason: str | None = None
    returns: tuple[tuple[str, str], ...] = ()
    window_dataset_id: str | None = None
    binding_sha256: str | None = None


Executor = Callable[[Cell, int], CellOutcome]


def dispatch(  # pylint: disable=too-many-arguments,too-many-locals
    ledger: TrialLedger,
    cells: Sequence[Cell],
    executor: Executor,
    *,
    bounds: Bounds | None = None,
    nonce: Callable[[], str] | None = None,
    clock: Callable[[], str] | None = None,
    only: Iterable[str] | None = None,
) -> int:
    """Run every non-terminal cell once at a time, appending each attempt.

    Writes the planned list first, resumes from the ledger (skips terminal cells,
    continues attempt numbers) and retries only :data:`RETRYABLE_CODES` up to
    ``bounds.max_attempts``. ``only`` (trial ids) restricts this spawn to a
    subset of the plan; the planned list is always the full ``cells``. Returns
    the number of attempts appended.
    """
    bounds = bounds or Bounds()
    check_bounds(cells, bounds)
    ledger.write_planned(cells)
    nonce = nonce or (lambda: os.urandom(16).hex())
    clock = clock or (lambda: datetime.now().astimezone().isoformat())
    subset = None if only is None else set(only)
    appended = 0
    for cell in sorted(cells, key=_cell_key):
        if subset is not None and cell.trial_id not in subset:
            continue
        while True:
            records = ledger.records()
            state = cell_state(
                cell.trial_id, cell.config_id, records, bounds.max_attempts
            )
            if state.state != "pending":
                break
            attempt_no = state.attempts + 1
            started = clock()
            try:
                outcome = executor(cell, attempt_no)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "cell %s attempt %d raised %s",
                    cell.trial_id[:12],
                    attempt_no,
                    type(exc).__name__,
                )
                outcome = CellOutcome(
                    status="failed", error_code="internal", reason=type(exc).__name__
                )
            ledger.append(
                AttemptRecord(
                    attempt_id=attempt_id(cell.trial_id, attempt_no, nonce()),
                    trial_id=cell.trial_id,
                    config_id=cell.config_id,
                    base_dataset_id=cell.config.base_dataset_id,
                    window_ordinal=cell.window.ordinal,
                    attempt_no=attempt_no,
                    status=outcome.status,
                    error_code=outcome.error_code,
                    reason=outcome.reason,
                    result_sha256=(
                        returns_sha256(outcome.returns)
                        if outcome.status == "ok"
                        else None
                    ),
                    window_dataset_id=outcome.window_dataset_id,
                    binding_sha256=outcome.binding_sha256,
                    started_at=started,
                    ended_at=clock(),
                    returns=tuple(outcome.returns) if outcome.status == "ok" else (),
                )
            )
            appended += 1
    return appended
