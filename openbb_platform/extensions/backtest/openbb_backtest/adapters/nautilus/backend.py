"""The ``nautilus`` backend behind ``obb.backtest.run`` (#1356 T02).

Only reviewed strategies run here. The facade resolves the strategy from the
frozen allowlist (never the legacy registry or entry points), exports the
neutral dataset, sends a ``run`` v2 body to the worker (which re-resolves and
re-hashes everything against its own copy), and projects the worker body onto
the canonical :class:`~openbb_backtest.models.BacktestResult`.

Every failure is a typed :class:`~openbb_backtest.errors.BacktestError`. This
module never imports or calls the legacy engines: there is no fallback.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError
from openbb_nautilus_worker.reviewed import registry

from openbb_backtest.errors import (
    BackendUnavailableError,
    BacktestError,
    UnsupportedSemanticsError,
)
from openbb_backtest.models import BackendSource, BacktestConfig, BacktestResult
from openbb_backtest.settings import DEFAULT_SETTINGS

from . import projection, strategies

#: The worker and loader prefix their messages with ``"<reason>: "``.
_REASON = re.compile(r"^([a-z][a-z0-9_]{0,63}): ")
#: ``config``-layer reasons that describe semantics, not an unusable runtime.
_SEMANTIC_REASONS = frozenset({"execution_not_executable"})
_CENT = Decimal("0.01")
#: Reserved ``strategy_params`` key carrying the execution assumptions.
EXECUTION_KEY = "execution"

Export = Callable[[registry.Binding, BacktestConfig], str]


@dataclass(frozen=True)
class NautilusOptions:
    """Seams for the nautilus path; the route always uses the defaults.

    ``client_factory`` returns a context-managed worker client;
    ``export`` returns a dataset id for a binding (default: export from the
    cache with ``execute`` into ``data_root``/datasets). ``qualify=False``
    skips the describe-vs-pin check and is recorded in the provenance; it is
    reachable only from code (tests, the golden CLI), never from the route.
    ``runs_root`` locates experiment ledgers for sweep / validate.
    """

    client_factory: Callable[[], Any] | None = None
    export: Export | None = None
    execute: Any = None
    data_root: Path | None = None
    qualify: bool = True
    runtime: str | None = None
    #: Experiment ledgers root (#1357); default ``settings.runs_root``.
    runs_root: Path | None = None


def map_error(exc: ProtocolError) -> BacktestError:
    """Map a worker/loader rejection onto the typed facade errors.

    ``schema`` (parameter, spec or semantics mismatch) and semantic ``config``
    reasons become :class:`UnsupportedSemanticsError`; everything else (code
    drift, process, ABI, unknown runtime) is :class:`BackendUnavailableError`.
    ``reason`` and ``code`` are kept.
    """
    code = exc.code.value
    reason = getattr(exc, "reason", None)
    if reason is None:
        match = _REASON.match(exc.message)
        reason = match.group(1) if match else None
    if exc.code is ErrorCode.SCHEMA or reason in _SEMANTIC_REASONS:
        return UnsupportedSemanticsError(
            f"nautilus backend rejected the run: {exc.message}",
            reason=reason,
            code=code,
        )
    return BackendUnavailableError(
        f"nautilus backend failed: {exc.message}", reason=reason, code=code
    )


def _unsupported(reason: str, message: str) -> UnsupportedSemanticsError:
    return UnsupportedSemanticsError(message, reason=reason, code="schema")


def _check_config(config: BacktestConfig) -> str:
    """Reject config semantics the reviewed path does not model; return cash."""
    if config.frequency != "daily":
        raise _unsupported("unsupported_frequency", "nautilus runs daily bars only")
    costs = (
        config.commission.value,
        config.commission.min_per_trade,
        config.slippage.value,
    )
    if any(v != 0 for v in costs):
        raise _unsupported(
            "legacy_cost_model",
            "commission/slippage models are legacy-only; declare fees in"
            " strategy_params['execution'] (zero or taker_bps)",
        )
    cash = config.initial_cash.quantize(_CENT)
    if cash != config.initial_cash:
        raise _unsupported("cash_not_cents", "initial_cash must be whole cents")
    return str(cash)


def split_params(
    config: BacktestConfig, strategy_params: Mapping[str, Any] | None
) -> tuple[dict[str, Any], Any]:
    """Split ``strategy_params`` into reviewed params and execution assumptions.

    ``buy_and_hold`` defaults its ``symbols`` to the config universe.
    """
    params = dict(strategy_params or {})
    execution = params.pop(EXECUTION_KEY, None)
    if config.strategy.strip().lower() == "buy_and_hold":
        params.setdefault("symbols", list(config.universe))
    return params, execution


def _check_universe(binding: registry.Binding, config: BacktestConfig) -> None:
    universe = {s.strip().upper() for s in config.universe}
    if set(binding.symbols) != universe:
        raise _unsupported(
            "universe_mismatch",
            "the strategy's symbols must equal config.universe",
        )


def _default_export(options: NautilusOptions) -> Export:
    def export(binding: registry.Binding, config: BacktestConfig) -> str:
        from . import export as ex  # pylint: disable=import-outside-toplevel

        root = options.data_root or os.environ.get(DATA_ROOT_ENV)
        if not root:
            raise BackendUnavailableError(
                f"{DATA_ROOT_ENV} is not set; the nautilus backend has no data root",
                reason="data_root_not_configured",
                code="config",
            )
        out = Path(root) / "datasets"
        out.mkdir(parents=True, exist_ok=True)
        result = ex.export_dataset(
            list(binding.symbols),
            config.start,
            config.end,
            basis="raw_plus_actions",
            out_root=out,
            execute=options.execute,
            calendar=config.calendar,
        )
        return result.dataset_id

    return export


def _client_factory(options: NautilusOptions) -> tuple[Callable[[], Any], str]:
    if options.client_factory is not None:
        return options.client_factory, options.runtime or "custom"
    runtime = DEFAULT_SETTINGS.nautilus_runtime
    if not runtime:
        raise BackendUnavailableError(
            "the nautilus worker is not configured; set"
            " OPENBB_BACKTEST_NAUTILUS_RUNTIME (native or docker)",
            reason="worker_not_configured",
            code="config",
        )
    # pylint: disable=import-outside-toplevel
    from .client import WorkerClient, worker_command

    command = worker_command(runtime, os.environ)
    timeout = DEFAULT_SETTINGS.nautilus_timeout_seconds
    return (lambda: WorkerClient(command, timeout=timeout)), runtime


def _qualify(client: Any, runtime: str) -> Any:
    """Describe the worker and judge it against the pin; raise on mismatch."""
    # pylint: disable=import-outside-toplevel
    from .pin import load_pin
    from .qualify import evaluate

    facts = client.describe()
    pin = load_pin()
    if runtime not in pin.runtimes:
        raise BackendUnavailableError(
            f"runtime '{runtime}' is not pinned",
            reason="qualify_mismatch",
            code="config",
        )
    failed = [c for c in evaluate(pin, runtime, facts) if not c.ok]
    if failed:
        raise BackendUnavailableError(
            "the worker does not match its pin: " + ", ".join(c.check for c in failed),
            reason="qualify_mismatch",
            code=failed[0].layer,
        )
    return facts


def run(
    config: BacktestConfig,
    *,
    strategy_params: Mapping[str, Any] | None,
    backend_source: BackendSource,
    options: NautilusOptions | None = None,
) -> BacktestResult:
    """Run one reviewed strategy on the worker and project its result."""
    options = options or NautilusOptions()
    cash = _check_config(config)
    params, execution = split_params(config, strategy_params)
    try:
        binding = strategies.resolve_reviewed(
            config.strategy, config.strategy_version, params, execution
        )
        _check_universe(binding, config)
        factory, runtime = _client_factory(options)
        dataset_id = (options.export or _default_export(options))(binding, config)
        body = strategies.build_run_body(binding, dataset_id, starting_cash=cash)
        with factory() as client:
            facts = _qualify(client, runtime) if options.qualify else None
            report = client.run(body)
    except ProtocolError as exc:
        raise map_error(exc) from exc
    return projection.to_backtest_result(
        report,
        config=config,
        binding=binding,
        backend_source=backend_source,
        runtime=runtime,
        facts=facts,
        qualified=options.qualify,
    )
