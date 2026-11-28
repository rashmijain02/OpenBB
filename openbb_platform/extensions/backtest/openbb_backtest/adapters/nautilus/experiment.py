"""Nautilus experiments: plan, execute and assemble trial cells (#1357).

Bridges ``sweep`` / ``validate`` on the ``nautilus`` backend to the trial
ledger (:mod:`openbb_backtest.validation.trials`) and the fold-return matrix
(:mod:`openbb_backtest.validation.matrix`):

- :func:`plan` resolves every grid combination against the reviewed allowlist
  (an invalid combination stays in the plan and is excluded as
  ``admission_rejected``, so it still counts in ``N``), exports the base dataset
  of the full range once and builds the sorted planned cells.
- :func:`cell_executor` runs one cell through the same steps as
  ``backend.run`` (one dataset export per window, shared by every configuration,
  D2; ``build_run_body``; ``WorkerClient.run``; projection) and turns worker
  errors into a :class:`~openbb_backtest.validation.trials.CellOutcome`:
  ``process`` / ``timeout`` / ``spawn`` are retryable, ``schema`` (admission)
  and every other code are terminal.
- :func:`run` writes spec and plan, dispatches, and assembles.

No legacy engine is imported here. Ledgers hold hashes, error codes and
returns only (no positions, no account values).
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError
from openbb_nautilus_worker.reviewed import registry

from openbb_backtest.errors import BacktestError, UnsupportedSemanticsError
from openbb_backtest.models import BacktestConfig, ExperimentSummary
from openbb_backtest.settings import DEFAULT_SETTINGS
from openbb_backtest.validation.matrix import (
    Assembly,
    assemble,
    encode_returns,
    returns_from_equity,
)
from openbb_backtest.validation.trials import (
    Bounds,
    Cell,
    CellOutcome,
    ConfigIdentity,
    Executor,
    ExperimentTooLargeError,
    TrialLedger,
    Window,
    WindowPolicy,
    dispatch,
    sha256_canonical,
)

from . import backend, projection, strategies

logger = logging.getLogger(__name__)

_EXPERIMENT_V = "experiment/2"
#: Fixed precision of the event-replay fake worker (``fake_run_worker.py``).
_FAKE_PRECISION = 9


def expand_grid(
    param_grid: Mapping[str, Sequence[Any]], base: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Cartesian product of ``param_grid`` over ``base`` (legacy sweep order).

    The grid size (product of the axis lengths) is checked against
    ``experiment_max_configs`` *before* anything is expanded, so an oversized
    grid fails closed with :class:`ExperimentTooLargeError` in constant time.
    """
    names = list(param_grid)
    size = math.prod(len(param_grid[n]) for n in names)
    limit = DEFAULT_SETTINGS.experiment_max_configs
    if size > limit:
        raise ExperimentTooLargeError(
            f"experiment_too_large: {size} configs exceeds {limit}"
        )
    return [
        {**dict(base or {}), **dict(zip(names, values))}
        for values in itertools.product(*(param_grid[n] for n in names))
    ]


@dataclass(frozen=True)
class WindowSpec:
    """A planned window: its ordinal and ordered ISO sessions."""

    ordinal: int
    sessions: tuple[str, ...]


@dataclass
class Plan:  # pylint: disable=too-many-instance-attributes
    """The planned experiment (built before any worker spawn)."""

    experiment_id: str
    spec: dict[str, Any]
    cells: list[Cell]
    policy: WindowPolicy
    combos: dict[str, dict[str, Any]]
    bindings: dict[str, Any]
    rejected: dict[str, str]
    cash: str
    external_trials: int
    base_dataset_id: str
    #: ``(symbols, first, last) -> dataset_id``: one export per window (D2).
    exports: dict[tuple[tuple[str, ...], str, str], str] = field(default_factory=dict)


@dataclass
class Outcome:
    """A dispatched and assembled experiment."""

    plan: Plan
    assembly: Assembly
    appended: int
    summary: ExperimentSummary
    ledger: TrialLedger = field(repr=False)


def _versions(options: backend.NautilusOptions) -> tuple[str, str, int]:
    """``(engine_version, worker_version, fixed_precision)`` bound into config ids."""
    # pylint: disable-next=import-outside-toplevel
    from openbb_nautilus_worker.protocol import PROTOCOL_VERSION

    from .pin import load_pin  # pylint: disable=import-outside-toplevel

    pin = load_pin()
    runtime = options.runtime or DEFAULT_SETTINGS.nautilus_runtime or "unset"
    engine = f"nautilus_trader=={pin.version}@{runtime}"
    pinned = pin.runtimes.get(runtime)
    precision = pinned.fixed_precision if pinned is not None else _FAKE_PRECISION
    return engine, f"protocol/{PROTOCOL_VERSION}", precision


def _rejected_identity(
    config: BacktestConfig, params: Mapping[str, Any], execution: Any, **bound: Any
) -> ConfigIdentity:
    """Identity of a combination the allowlist rejected (still counted in N)."""
    try:
        pin = registry.pin_for(config.strategy, config.strategy_version or "1.0.0")
        spec, code = pin.spec_sha256, pin.code_sha256
    except (ProtocolError, KeyError, ValueError):
        spec = code = "unresolved"
    return ConfigIdentity(
        backend="nautilus",
        strategy_id=config.strategy.strip().lower(),
        strategy_version=str(config.strategy_version or ""),
        spec_sha256=spec,
        code_sha256=code,
        param_schema_sha256="unresolved",
        params_sha256=sha256_canonical({"params": dict(params)}),
        execution_sha256=sha256_canonical({"execution": execution}),
        **bound,
    )


def _span(config: BacktestConfig, first: str, last: str) -> BacktestConfig:
    """``config`` restricted to the sessions ``first`` .. ``last`` (ISO)."""
    return config.model_copy(
        update={"start": date.fromisoformat(first), "end": date.fromisoformat(last)}
    )


def plan(  # pylint: disable=too-many-arguments,too-many-locals
    config: BacktestConfig,
    combos: Sequence[Mapping[str, Any]],
    windows: Sequence[WindowSpec],
    *,
    command: str,
    method: str,
    policy: WindowPolicy,
    fold_params: Mapping[str, Any],
    options: backend.NautilusOptions,
    external_trials: int = 0,
) -> Plan:
    """Resolve combinations, export the base dataset and build the cells.

    Raises :class:`UnsupportedSemanticsError` for config semantics the reviewed
    path does not model (frequency, legacy costs, fractional cash) before any
    export or spawn.
    """
    if external_trials < 0:
        raise ValueError("external_trials must be >= 0")
    if not combos:
        raise ValueError("an experiment needs at least one configuration")
    if not windows:
        raise ValueError("an experiment needs at least one window")
    limits = _bounds()
    if (
        len(combos) > limits.max_configs
        or len(combos) * len(windows) > limits.max_cells
    ):
        raise ExperimentTooLargeError(  # before resolution, export or spawn
            f"experiment_too_large: {len(combos)} configs / "
            f"{len(combos) * len(windows)} cells exceeds "
            f"{limits.max_configs} / {limits.max_cells}"
        )
    cash = backend._check_config(config)  # pylint: disable=protected-access
    # pylint: disable-next=protected-access
    export = options.export or backend._default_export(options)
    engine_version, worker_version, precision = _versions(options)
    resolved: list[tuple[dict[str, Any], Any, Any, str | None]] = []
    for combo in combos:
        params, execution = backend.split_params(config, combo)
        try:
            binding = strategies.resolve_reviewed(
                config.strategy, config.strategy_version, params, execution
            )
            backend._check_universe(binding, config)  # pylint: disable=protected-access
            resolved.append((dict(combo), params, binding, None))
        except (ProtocolError, UnsupportedSemanticsError) as exc:
            resolved.append((dict(combo), params, execution, type(exc).__name__))
    lo = min(w.sessions[0] for w in windows)
    hi = max(w.sessions[-1] for w in windows)
    first = next((b for _c, _p, b, why in resolved if why is None), None)
    exports: dict[tuple[tuple[str, ...], str, str], str] = {}
    base_dataset_id = "unexported"
    if first is not None:
        span = _span(config, lo, hi)
        base_dataset_id = export(first, span)
        exports[(tuple(first.symbols), lo, hi)] = base_dataset_id
    bound: dict[str, Any] = {
        "base_dataset_id": base_dataset_id,
        "engine_version": engine_version,
        "worker_version": worker_version,
        "fixed_precision": precision,
    }
    wins = [
        Window.from_sessions(
            policy=policy,
            method=method,
            fold_params=fold_params,
            ordinal=w.ordinal,
            sessions=list(w.sessions),
        )
        for w in windows
    ]
    cells: list[Cell] = []
    by_cfg: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    config_keys: set[str] = set()
    for combo, params, binding, why in resolved:
        if why is None:
            ident = ConfigIdentity.from_binding(binding, **bound)
        else:
            ident = _rejected_identity(config, params, binding, **bound)
        cid = ident.config_id
        if cid in by_cfg:  # equivalent params normalise to one configuration
            continue
        by_cfg[cid] = combo
        config_keys.add(ident.config_key)
        if why is None:
            bindings[cid] = binding
        else:
            rejected[cid] = why
        cells.extend(Cell(config=ident, window=w) for w in wins)
    # CODE-2/2b: the experiment is keyed on a dataset-independent spec, so a
    # data refresh re-opens the same ledger and appends one new dataset
    # generation instead of a new, empty experiment that would forget the
    # configurations already tried. N counts distinct config keys over every
    # generation; the matrix comes from this plan's generation only.
    spec = {
        "v": _EXPERIMENT_V,
        "command": command,
        "backend": "nautilus",
        "strategy": config.strategy,
        "strategy_version": config.strategy_version,
        "universe": sorted(config.universe),
        "cash": cash,
        "method": method,
        "policy": policy,
        "fold_params": dict(fold_params),
        "external_trials": int(external_trials),
        "config_keys": sorted(config_keys),
        "windows": [sha256_canonical(asdict(w)) for w in wins],
    }
    return Plan(
        experiment_id=sha256_canonical(spec),
        spec=spec,
        cells=cells,
        policy=policy,
        combos=by_cfg,
        bindings=bindings,
        rejected=rejected,
        cash=cash,
        external_trials=int(external_trials),
        base_dataset_id=base_dataset_id,
        exports=exports,
    )


def classify(exc: BaseException) -> CellOutcome:
    """Map a cell failure onto a ledger outcome (retryable vs terminal).

    ``process`` errors split into ``spawn`` (could not start), ``timeout``
    (deadline kill) and ``process`` (crash, closed stream): all retryable.
    ``schema`` is a worker admission rejection (terminal, ``admission``);
    unsupported semantics are excluded; every other protocol code (module
    origin, ABI, config, auth, egress) is a terminal failure.
    """
    if isinstance(exc, ProtocolError):
        reason = getattr(exc, "reason", None)
        if exc.code is ErrorCode.PROCESS:
            text = exc.message.lower()
            if "could not be started" in text:
                code = "spawn"
            elif "deadline" in text:
                code = "timeout"
            else:
                code = "process"
            return CellOutcome(status="failed", error_code=code, reason=reason)
        if exc.code is ErrorCode.SCHEMA:
            return CellOutcome(
                status="excluded", error_code="admission", reason="admission_rejected"
            )
        return CellOutcome(status="failed", error_code=exc.code.value, reason=reason)
    if isinstance(exc, UnsupportedSemanticsError):
        return CellOutcome(
            status="excluded",
            error_code="unsupported_semantics",
            reason="unsupported_semantics",
        )
    if isinstance(exc, BacktestError):
        return CellOutcome(
            status="failed",
            error_code=getattr(exc, "code", None) or "internal",
            reason=getattr(exc, "reason", None),
        )
    raise exc


def cell_executor(
    the_plan: Plan,
    config: BacktestConfig,
    options: backend.NautilusOptions,
) -> Executor:
    """Executor running one cell per call; one dataset export per window (D2)."""
    # pylint: disable-next=protected-access
    export = options.export or backend._default_export(options)
    factory, runtime = backend._client_factory(  # pylint: disable=protected-access
        options
    )
    exported = the_plan.exports

    def window_dataset(binding: Any, cell: Cell) -> tuple[str, BacktestConfig]:
        sub = _span(config, cell.window.start_session, cell.window.end_session)
        key = (
            tuple(binding.symbols),
            cell.window.start_session,
            cell.window.end_session,
        )
        if key not in exported:
            exported[key] = export(binding, sub)
        return exported[key], sub

    def execute(cell: Cell, _attempt_no: int) -> CellOutcome:
        if cell.config_id in the_plan.rejected:
            return CellOutcome(
                status="excluded", error_code="admission", reason="admission_rejected"
            )
        binding = the_plan.bindings[cell.config_id]
        try:
            dataset_id, sub = window_dataset(binding, cell)
            body = strategies.build_run_body(
                binding, dataset_id, starting_cash=the_plan.cash
            )
            with factory() as client:
                # pylint: disable-next=protected-access
                facts = backend._qualify(client, runtime) if options.qualify else None
                report = client.run(body)
            result = projection.to_backtest_result(
                report,
                config=sub,
                binding=binding,
                backend_source="config",
                runtime=runtime,
                facts=facts,
                qualified=options.qualify,
            )
        except (ProtocolError, BacktestError) as exc:
            return classify(exc)
        curve = [(p.date.date(), p.equity) for p in result.equity_curve]
        returns = returns_from_equity(curve)
        if not returns:
            return CellOutcome(
                status="excluded",
                error_code="insufficient_sessions",
                reason="insufficient_sessions",
                window_dataset_id=dataset_id,
            )
        prov = result.provenance
        return CellOutcome(
            status="ok",
            returns=encode_returns(returns),
            window_dataset_id=dataset_id,
            binding_sha256=prov.binding_sha256 if prov is not None else None,
        )

    return execute


def _bounds() -> Bounds:
    return Bounds(
        max_configs=DEFAULT_SETTINGS.experiment_max_configs,
        max_cells=DEFAULT_SETTINGS.experiment_max_cells,
        max_attempts=DEFAULT_SETTINGS.experiment_max_attempts,
    )


def runs_root(options: backend.NautilusOptions) -> Path:
    """Where experiment ledgers live (``options.runs_root`` or settings)."""
    return Path(options.runs_root or DEFAULT_SETTINGS.runs_root)


def run(  # pylint: disable=too-many-arguments
    the_plan: Plan,
    config: BacktestConfig,
    options: backend.NautilusOptions,
    *,
    executor: Executor | None = None,
    only: Sequence[str] | None = None,
    nonce: Callable[[], str] | None = None,
    clock: Callable[[], str] | None = None,
) -> Outcome:
    """Persist spec and plan, dispatch pending cells, then assemble the ledger."""
    bounds = _bounds()
    ledger = TrialLedger.for_experiment(runs_root(options), the_plan.experiment_id)
    ledger.write_spec(the_plan.spec)
    appended = dispatch(
        ledger,
        the_plan.cells,
        executor or cell_executor(the_plan, config, options),
        bounds=bounds,
        nonce=nonce,
        clock=clock,
        only=only,
    )
    assembly = assemble(
        ledger.planned(),
        ledger.records(),
        external_trials=the_plan.external_trials,
        max_attempts=bounds.max_attempts,
        dataset_id=the_plan.base_dataset_id,
    )
    summary = ExperimentSummary(
        experiment_id=the_plan.experiment_id,
        window_policy=the_plan.policy,
        **assembly.summary(),
    )
    return Outcome(
        plan=the_plan,
        assembly=assembly,
        appended=appended,
        summary=summary,
        ledger=ledger,
    )


# --- sweep / validate over an experiment (routed from the facade) ---------


def session_calendar(config: BacktestConfig) -> list[str]:
    """ISO sessions of ``config``'s range on its calendar (same as the export)."""
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.data.calendars import sessions_in_range

    return [
        ts.date().isoformat()
        for ts in sessions_in_range(config.start, config.end, config.calendar)
    ]


@dataclass(frozen=True)
class FoldPlan:
    """Resampling folds over the session calendar, plus their windows."""

    method: str
    fold_params: dict[str, Any]
    #: Per fold: ``(test positions, path_id)``; CPCV folds are ``(split, group)``.
    folds: list[tuple[list[int], int | None]]
    windows: list[WindowSpec]


def fold_plan(sessions: Sequence[str], method: str, policy: WindowPolicy) -> FoldPlan:
    """Folds and windows for ``method`` (``wfo``, ``cpcv`` or ``sweep``).

    ``continuous`` = one window over the full range (folds are index views);
    ``per_fold`` = one window per atomic test window (WFO test window or CPCV
    group, never a non-contiguous span). CPCV folds are emitted per
    ``(split, group)`` cell with ``path_id`` from :func:`cpcv_paths`.
    """
    # pylint: disable=import-outside-toplevel
    import numpy as np

    from openbb_backtest.validation import cpcv, cpcv_paths, walk_forward

    total = len(sessions)
    folds: list[tuple[list[int], int | None]] = []
    atoms: list[list[int]]
    if method == "sweep":
        params: dict[str, Any] = {"method": "sweep"}
        atoms = [list(range(total))]
    elif method == "cpcv":
        n_groups, k = 6, 2
        params = {"method": "cpcv", "n_groups": n_groups, "n_test_groups": k}
        cpcv(sessions, n_groups=n_groups, n_test_groups=k)  # validates sizes
        groups = [g.tolist() for g in np.array_split(np.arange(total), n_groups)]
        for path, path_cells in enumerate(cpcv_paths(n_groups, k)):
            for _split, group in path_cells:
                folds.append((groups[group], path))
        atoms = groups
    elif method == "wfo":
        train, test = max(1, total // 2), max(1, total // 4)
        params = {"method": "wfo", "train": train, "test": test, "step": test}
        for fold in walk_forward(sessions, train, test, test):
            folds.append((fold.test_idx.tolist(), None))
        atoms = [f for f, _p in folds]
    else:
        raise ValueError(f"unknown experiment method '{method}'")
    if policy == "continuous":
        windows = [WindowSpec(0, tuple(sessions))]
    else:
        windows = [
            WindowSpec(i, tuple(sessions[j] for j in atom))
            for i, atom in enumerate(atoms)
        ]
    return FoldPlan(method=method, fold_params=params, folds=folds, windows=windows)


def _series(matrix: Any, config_id: str, keep: set[str] | None = None) -> Any:
    import pandas as pd  # pylint: disable=import-outside-toplevel

    pairs = [
        (s, r)
        for c, _o, s, r in matrix.rows
        if c == config_id and (keep is None or s in keep)
    ]
    return pd.Series(
        [r for _s, r in pairs],
        index=pd.DatetimeIndex([s for s, _r in pairs]),
        dtype=float,
        name="returns",
    )


def _require_matrix(outcome: Outcome) -> Any:
    matrix = outcome.assembly.matrix
    if matrix is None or not matrix.rows:
        raise UnsupportedSemanticsError(
            f"experiment {outcome.plan.experiment_id[:12]} produced no usable"
            f" configuration ({outcome.assembly.status}; exclusions:"
            f" {outcome.assembly.exclusions})",
            reason="experiment_no_matrix",
        )
    return matrix


def sweep_result(outcome: Outcome, rank_by: str, sessions_per_year: int = 252) -> Any:
    """``SweepResult`` over the ok configurations (excluded ones only counted)."""
    # pylint: disable=import-outside-toplevel
    from openbb_backtest.analytics import compute_metrics
    from openbb_backtest.engine.vectorized import select_best
    from openbb_backtest.models import SweepPoint, SweepResult

    matrix = _require_matrix(outcome)
    results = [
        (
            outcome.plan.combos[cid],
            compute_metrics(_series(matrix, cid), None, [], sessions_per_year),
        )
        for cid in matrix.config_ids
    ]
    best, best_metrics = select_best(results, rank_by)
    return SweepResult(
        results=[SweepPoint(params=p, metrics=m) for p, m in results],
        best=best,
        best_metrics=best_metrics,
        rank_by=rank_by,
        experiment=outcome.summary,
    )


def validation_report(  # pylint: disable=too-many-locals
    outcome: Outcome,
    folds: FoldPlan,
    sessions: Sequence[str],
    *,
    thresholds: dict[str, float] | None = None,
    sessions_per_year: int = 252,
) -> Any:
    """Selection-aware ``ValidationReport`` (configs as PBO columns, N from ledger).

    Statistics run on the out-of-sample sessions of the matrix (the union of
    the fold test windows); the verdict is capped at ``fragile`` when PBO or DSR
    is undefined or the matrix is incomplete (D3). An undefined DSR stays
    ``None`` with its reason code (CODE-1), never 0.0.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_backtest.analytics import compute_metrics
    from openbb_backtest.models import FoldResult, ValidationReport
    from openbb_backtest.validation import min_backtest_length
    from openbb_backtest.validation.matrix import FoldReturnMatrix
    from openbb_backtest.validation.report import (
        _effective_thresholds,
        capped_verdict,
    )
    from openbb_backtest.validation.selection import selection_statistics

    matrix = _require_matrix(outcome)
    oos = {sessions[j] for idx, _p in folds.folds for j in idx}
    sub = FoldReturnMatrix.from_rows(r for r in matrix.rows if r[2] in oos)
    try:
        stats = selection_statistics(sub, outcome.assembly.n_trials_dsr)
    except ValueError as exc:
        raise UnsupportedSemanticsError(
            f"validation statistics are undefined: {exc}",
            reason="statistics_undefined",
        ) from exc
    best = stats.best_config_id
    fold_results = [
        FoldResult(
            fold=i,
            metrics=compute_metrics(
                _series(sub, best, {sessions[j] for j in idx}),
                None,
                [],
                sessions_per_year,
            ),
            path_id=path,
        )
        for i, (idx, path) in enumerate(folds.folds)
    ]
    oos_metrics = compute_metrics(_series(sub, best), None, [], sessions_per_year)
    minbtl = (
        min_backtest_length(oos_metrics.sharpe, stats.n_trials)
        if oos_metrics.sharpe > 0.0
        else 0.0
    )
    dsr = stats.deflated_sharpe
    if dsr is not None and not math.isfinite(dsr):
        dsr = 0.0
    return ValidationReport(
        method="cpcv" if folds.method == "cpcv" else "wfo",
        folds=fold_results,
        oos_metrics=oos_metrics,
        pbo=stats.pbo,
        deflated_sharpe=dsr,
        dsr_undefined_reason=stats.dsr_undefined_reason,
        min_backtest_length_years=minbtl,
        verdict=capped_verdict(
            pbo=stats.pbo,
            dsr=dsr,
            oos_sharpe=oos_metrics.sharpe,
            matrix_complete=outcome.assembly.matrix_complete,
            thresholds=thresholds,
        ),
        thresholds=_effective_thresholds(thresholds),
        experiment=outcome.summary,
    )


def run_validation(  # pylint: disable=too-many-arguments
    config: BacktestConfig,
    combos: Sequence[Mapping[str, Any]],
    *,
    method: str,
    options: backend.NautilusOptions,
    thresholds: dict[str, float] | None = None,
    external_trials: int = 0,
    policy: WindowPolicy = "continuous",
) -> tuple[Any, Outcome]:
    """Plan, dispatch and report one nautilus ``validate`` experiment."""
    sessions = session_calendar(config)
    folds = fold_plan(sessions, method, policy)
    the_plan = plan(
        config,
        combos,
        folds.windows,
        command="validate",
        method=method,
        policy=policy,
        fold_params=folds.fold_params,
        options=options,
        external_trials=external_trials,
    )
    outcome = run(the_plan, config, options)
    report = validation_report(outcome, folds, sessions, thresholds=thresholds)
    return report, outcome


def run_sweep(
    config: BacktestConfig,
    combos: Sequence[Mapping[str, Any]],
    *,
    rank_by: str,
    options: backend.NautilusOptions,
) -> tuple[Any, Outcome]:
    """Plan, dispatch and rank one nautilus ``sweep`` experiment."""
    sessions = session_calendar(config)
    folds = fold_plan(sessions, "sweep", "continuous")
    the_plan = plan(
        config,
        combos,
        folds.windows,
        command="sweep",
        method="sweep",
        policy="continuous",
        fold_params=folds.fold_params,
        options=options,
    )
    outcome = run(the_plan, config, options)
    return sweep_result(outcome, rank_by), outcome
