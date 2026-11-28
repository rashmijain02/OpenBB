"""Engine sub-router: ``run`` / ``sweep`` / ``reconcile`` (component 09.2).

The execution face of ``obb.backtest.*``. These three commands are thin
orchestration over the heavy numeric layers — they resolve the engine per the
``engine=auto|vector|event`` policy (component 09.1), build the point-in-time
feed and execution broker, invoke the engine / vectorized sweep / reconciliation
gate, and return ``OBBject``-wrapped Data models. Two cross-cutting rules from
``09-api-surface.md`` §2 are enforced here at the boundary:

- **Privacy boundary** — :func:`run` pipes every engine result through
  :func:`~openbb_backtest.router_helpers.sanitize_result`, so raw positions / lot
  detail never cross the router; only normalized returns/metrics leave.
- **Lazy engine import** — engine modules (and their optional heavy deps) are
  imported only inside :func:`_engine_for`, keeping ``import openbb`` light.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

# from __future__ import annotations  # removed: breaks FastAPI OBBject[X] resolution (#824)

import logging
from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_backtest.errors import BackendSelectionError, UnsupportedSemanticsError

# Runtime imports (formerly under `if TYPE_CHECKING`). Needed at import
# time because this file no longer uses `from __future__ import annotations`
# — see #824 for the root cause.
from openbb_backtest.interfaces import (
    Broker,
    DataFeed,
    Engine,
    Strategy,
)  # noqa: F401, E402
from openbb_backtest.modeled_differences import MODELED_DIFFERENCES
from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    ReconciliationReport,
    RunProvenance,
    SweepPoint,
    SweepResult,
)
from openbb_backtest.router_helpers import (
    build_feed,
    resolve_backend,
    resolve_engine,
    resolve_provider,
    sanitize_result,
)

logger = logging.getLogger(__name__)

router = Router(prefix="", description="Run, sweep and reconcile backtests.")


# --- collaborator seams (patched in unit tests; lazy in production) ------


def _strategy_factory(name: str):
    """Return a ``**params -> Strategy`` factory for the registered strategy ``name``.

    Defers to :func:`openbb_backtest.strategies.discovery.resolve`, which looks
    the class up in the registry (loading entry-point plugins on demand) and
    instantiates it from a params dict.
    """
    from openbb_backtest.strategies.discovery import resolve

    return lambda **params: resolve(name, params)


def _engine_for(name: str) -> Engine:
    """Lazily import the engine package and return the registered engine ``name``.

    Importing :mod:`openbb_backtest.engine` registers both concrete engines; the
    heavy modules stay out of ``import openbb`` time until a backtest is actually
    requested. ``name`` is the concrete engine name from :func:`resolve_engine`.
    """
    import openbb_backtest.engine  # noqa: F401  (registers vectorized + event)
    from openbb_backtest.registry import get_engine

    return get_engine(name)()


def _build_feed(config: BacktestConfig, provider: str) -> DataFeed:
    """Build the point-in-time :class:`DataFeed` for ``config`` from ``provider``.

    Thin seam over :func:`~openbb_backtest.router_helpers.build_feed` (the shared
    ingest/load logic) so unit tests can monkeypatch the feed per router.
    """
    return build_feed(config, provider)


def _build_broker(config: BacktestConfig) -> Broker:
    """Construct the shared execution broker from the config's cost models."""
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


def _nautilus_options() -> Any:
    """Nautilus seams for routed commands (the route always uses the defaults)."""
    # pylint: disable-next=import-outside-toplevel  # lazy: keeps Nautilus optional
    from openbb_backtest.adapters.nautilus.backend import NautilusOptions

    return NautilusOptions()


def _reviewed_only(name: str) -> bool:
    """Return whether ``name`` is a reviewed strategy the legacy registry lacks.

    Loads the built-in strategies and entry-point plugins first, exactly as the
    legacy resolution that follows would.
    """
    # Lazy imports keep Nautilus optional (C0415 intended for this whole block).
    # pylint: disable=import-outside-toplevel
    # The adapter import puts the worker source dir on sys.path; it must precede
    # the worker import below (a fresh process has no other path to the worker).
    import openbb_backtest.adapters.nautilus  # noqa: F401  # pylint: disable=unused-import
    from openbb_backtest.registry import list_strategies
    from openbb_backtest.strategies import discovery

    if not discovery._PLUGINS_LOADED:  # pylint: disable=protected-access
        discovery.load_plugins()

    try:
        from openbb_nautilus_worker.reviewed import registry as reviewed
    except ImportError:  # worker package absent: nothing is reviewed-only
        return False
    key = name.strip().lower()
    ids = {pin.strategy_id for pin in reviewed.REVIEW_LEDGER}
    return key in ids and key not in list_strategies()


def _run_legacy(
    config: BacktestConfig,
    *,
    engine: str,
    strategy_params: dict[str, Any] | None,
    provider: str | None,
    feed: DataFeed | None,
) -> BacktestResult:
    """Run the pre-#1356 ``run`` body unchanged; return the unsanitized result."""
    if _reviewed_only(config.strategy):
        raise UnsupportedSemanticsError(
            f"strategy '{config.strategy}' is reviewed-only: the legacy backend has"
            " no whole-share/settled-cash semantics. Use backend='nautilus'.",
            reason="reviewed_only_strategy",
        )
    provider_name = resolve_provider(provider)
    strategy: Strategy = _strategy_factory(config.strategy)(**(strategy_params or {}))
    path_dependent = bool(getattr(strategy, "path_dependent", False))
    # Precedence: explicit engine=<value> at the call site wins; when the
    # caller leaves engine at its default "auto" sentinel, fall back to
    # config.engine so the field is finally honored (bd-q7u5). Case-fold
    # for the sentinel check because resolve_engine accepts "AUTO"/"Auto".
    selected_engine = engine if engine.strip().lower() != "auto" else config.engine
    engine_name = resolve_engine(selected_engine, path_dependent=path_dependent)
    logger.debug(
        "run: strategy=%s engine=%s provider=%s",
        config.strategy,
        engine_name,
        provider_name,
    )

    feed = feed if feed is not None else _build_feed(config, provider_name)
    broker = _build_broker(config)
    return _engine_for(engine_name).run(strategy, config, feed, broker)


def execute_run(  # pylint: disable=too-many-arguments
    config: BacktestConfig,
    *,
    engine: str = "auto",
    backend: str | None = None,
    strategy_params: dict[str, Any] | None = None,
    provider: str | None = None,
    feed: DataFeed | None = None,
    nautilus: Any = None,
) -> BacktestResult:
    """Shared ``run`` path for the route and the CLIs (#1356); sanitized result.

    Backend precedence is parameter, then ``config.backend``, then the default
    (``legacy``); the source is recorded in ``result.provenance``. ``legacy``
    runs the unchanged engine path. ``nautilus`` runs a reviewed strategy on the
    worker and never falls back to the legacy engines. ``nautilus`` (the
    argument) is an optional
    :class:`~openbb_backtest.adapters.nautilus.backend.NautilusOptions`.
    """
    backend_name, source = resolve_backend(backend, config)
    if backend_name == "nautilus":
        selected = engine if engine.strip().lower() != "auto" else config.engine
        if (
            selected.strip().lower() != "auto"
            and resolve_engine(selected) == "vectorized"
        ):
            raise BackendSelectionError(
                f"engine '{selected}' cannot run on backend 'nautilus' (the"
                " vectorized engine is legacy-only); use engine='auto'.",
                reason="engine_backend_conflict",
            )
        # pylint: disable-next=import-outside-toplevel  # lazy: keeps Nautilus optional
        from openbb_backtest.adapters.nautilus import backend as nautilus_backend

        result = nautilus_backend.run(
            config,
            strategy_params=strategy_params,
            backend_source=source,
            options=nautilus,
        )
        return sanitize_result(result)
    result = _run_legacy(
        config,
        engine=engine,
        strategy_params=strategy_params,
        provider=provider,
        feed=feed,
    )
    provenance = RunProvenance(
        backend="legacy",
        backend_source=source,
        engine=result.engine_used,
        strategy_review="unreviewed",
    )
    return sanitize_result(result.model_copy(update={"provenance": provenance}))


def _sweep_nautilus(
    config: BacktestConfig, param_grid: dict[str, list], rank_by: str
) -> SweepResult:
    """Sweep on the nautilus backend: one trial per combination (#1357)."""
    # pylint: disable-next=import-outside-toplevel  # lazy: keeps Nautilus optional
    from openbb_backtest.adapters.nautilus import experiment

    combos = experiment.expand_grid(param_grid)
    result, _outcome = experiment.run_sweep(
        config, combos, rank_by=rank_by, options=_nautilus_options()
    )
    return result


def _reconcile_nautilus(
    config: BacktestConfig,
    strategy_params: dict[str, Any] | None,
    strict: bool,
    tolerance: float | None,
    provider: str | None,
) -> ReconciliationReport:
    """Diagnostic comparison: nautilus reference vs the legacy event engine.

    The nautilus result is the reference; the legacy ``event`` engine runs the
    same strategy and params (execution assumptions dropped) as the candidate.
    Agreement is not a gate, so ``strict=True`` is rejected.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_backtest.engine.reconcile import max_equity_divergence
    from openbb_backtest.settings import DEFAULT_SETTINGS

    if strict:
        raise UnsupportedSemanticsError(
            "reconcile with backend 'nautilus' is diagnostic only; strict=True"
            " would make engine agreement a gate. Use strict=False.",
            reason="reconcile_not_a_gate",
        )
    reference = execute_run(
        config, strategy_params=strategy_params, nautilus=_nautilus_options()
    )
    legacy_params = dict(strategy_params or {})
    legacy_params.pop("execution", None)
    candidate = _run_legacy(
        config.model_copy(update={"backend": "legacy"}),
        engine="event",
        strategy_params=legacy_params,
        provider=provider,
        feed=None,
    )
    tol = DEFAULT_SETTINGS.reconcile_tolerance if tolerance is None else tolerance
    divergence = max_equity_divergence(reference, candidate)
    return ReconciliationReport(
        passed=divergence <= tol,
        max_divergence=divergence,
        tolerance=tol,
        reference_engine="nautilus",
        candidate_engine=candidate.engine_used,
        diagnostic_only=True,
        modeled_differences=list(MODELED_DIFFERENCES),
    )


# --- commands ------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Run a registered strategy with automatic engine selection.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL", "MSFT"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.run(config=config)",
            ],
        ),
        PythonEx(
            description="Force the event-driven engine for a path-dependent strategy.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="momentum_12_1", universe=["SPY"], start="2018-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.run(config=config, engine="event")',
            ],
        ),
    ],
)
async def run(
    config: BacktestConfig,
    engine: str = "auto",
    strategy_params: dict[str, Any] | None = None,
    provider: str | None = None,
    backend: str | None = None,
) -> OBBject[BacktestResult]:
    """Run a single backtest and return its normalized result.

    Resolves the strategy and engine, executes the backtest, and strips raw
    position/lot detail at the privacy boundary before returning. With
    ``engine="auto"`` a path-dependent strategy routes to the event-driven engine
    and everything else to the vectorized engine; ``"vector"``/``"event"`` force
    a concrete engine.

    Engine selection precedence (bd-q7u5)
    -------------------------------------
    Two knobs express the same choice: the ``engine=`` router parameter
    (default ``"auto"``) and the ``config.engine`` field. The router honors
    both, with the explicit call-site parameter winning:

    * If ``engine`` is anything other than the ``"auto"`` sentinel, the
      call-site value wins over ``config.engine``.
    * If ``engine="auto"`` (the default), ``config.engine`` is consulted and
      used if non-``"auto"``; otherwise the auto policy runs against
      ``strategy.path_dependent``.

    Pre-fix the router always used the parameter and silently dropped
    ``config.engine`` — a caller writing ``BacktestConfig(engine="event")``
    plus a bare ``obb.backtest.run(config=config)`` got the vectorized engine
    instead. The precedence rule keeps both APIs live without breaking any
    existing caller.

    Parameters
    ----------
    config : BacktestConfig
        Strategy name, universe, date range and cost/engine settings.
    engine : str, optional
        ``"auto"`` (default), ``"vector"``/``"vectorized"``, or ``"event"``.
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.
    backend : str, optional
        ``"legacy"`` or ``"nautilus"``. Precedence: this parameter, then
        ``config.backend``, then the default ``legacy`` (#1356). ``nautilus``
        runs reviewed strategies only and never falls back to ``legacy``.

    Returns
    -------
    OBBject[BacktestResult]
        The equity curve, trades and metrics — positions are sanitized away.
        ``provenance`` records the backend and where the choice came from.
    """
    result = execute_run(
        config,
        engine=engine,
        backend=backend,
        strategy_params=strategy_params,
        provider=provider,
    )
    return OBBject(results=result)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Sweep a parameter grid on the vectorized engine, ranked by Sharpe.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="momentum_12_1", universe=["SPY"], start="2015-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.sweep(config=config, param_grid={"lookback": [60, 120, 252]}, rank_by="sharpe")',  # noqa: E501
            ],
        ),
    ],
)
async def sweep(
    config: BacktestConfig,
    param_grid: dict[str, list],
    rank_by: str = "sharpe",
    provider: str | None = None,
) -> OBBject[SweepResult]:
    """Evaluate a strategy across a parameter grid on the vectorized engine.

    The shared returns matrix is computed once and reused across every grid
    combination (the core sweep performance lever); each combo's metrics are
    returned alongside the winning combo selected by ``rank_by``. With
    ``config.backend="nautilus"`` every combination is a reviewed trial on the
    worker (invalid combinations are excluded but still counted) and
    ``result.experiment`` carries the trial accounting; legacy is the default.

    Parameters
    ----------
    config : BacktestConfig
        Backtest settings; ``config.strategy`` names the swept strategy.
    param_grid : dict[str, list]
        Maps each strategy keyword argument to the list of values to try; the
        cartesian product is evaluated.
    rank_by : str, optional
        :class:`PerformanceMetrics` field used to pick ``best`` (default ``sharpe``).
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[SweepResult]
        Per-combo metrics plus the best combo and its metrics.
    """
    if resolve_backend(None, config)[0] == "nautilus":
        return OBBject(results=_sweep_nautilus(config, param_grid, rank_by))
    from openbb_backtest.engine.vectorized import sweep as _engine_sweep

    provider_name = resolve_provider(provider)
    feed = _build_feed(config, provider_name)
    factory = _strategy_factory(config.strategy)
    logger.debug(
        "sweep: strategy=%s combos=%s rank_by=%s", config.strategy, param_grid, rank_by
    )

    engine_result = _engine_sweep(factory, param_grid, config, feed, rank_by=rank_by)
    model = SweepResult(
        results=[
            SweepPoint(params=params, metrics=metrics)
            for params, metrics in engine_result.results
        ],
        best=engine_result.best,
        best_metrics=engine_result.best_metrics,
        rank_by=engine_result.rank_by,
    )
    return OBBject(results=model)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Reconcile the vectorized engine against the event-driven source of truth.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                "obb.backtest.reconcile(config=config)",
            ],
        ),
    ],
)
def reconcile(
    config: BacktestConfig,
    strategy_params: dict[str, Any] | None = None,
    strict: bool = False,
    tolerance: float | None = None,
    provider: str | None = None,
) -> OBBject[ReconciliationReport]:
    """Run one config through both engines and compare their equity curves.

    The event-driven engine is the source of truth; the vectorized engine is the
    candidate under test. A divergence beyond ``tolerance`` marks the report as
    failed and, when ``strict`` is set, raises ``ReconciliationError`` instead.
    With ``config.backend="nautilus"`` the nautilus run is the reference, the
    legacy event engine the candidate, and the report is ``diagnostic_only``
    (``strict=True`` is rejected).

    Parameters
    ----------
    config : BacktestConfig
        Backtest settings run identically through both engines.
    strategy_params : dict, optional
        Keyword arguments forwarded to the strategy constructor.
    strict : bool, optional
        Raise ``ReconciliationError`` on divergence instead of reporting it.
    tolerance : float, optional
        Max allowed equity divergence; defaults to the settings reconcile tolerance.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[ReconciliationReport]
        Whether the engines agreed and the largest equity divergence observed.
    """
    if resolve_backend(None, config)[0] == "nautilus":
        return OBBject(
            results=_reconcile_nautilus(
                config, strategy_params, strict, tolerance, provider
            )
        )
    from openbb_backtest.engine.reconcile import reconcile as _engine_reconcile

    provider_name = resolve_provider(provider)
    strategy: Strategy = _strategy_factory(config.strategy)(**(strategy_params or {}))
    feed = _build_feed(config, provider_name)
    broker = _build_broker(config)
    reference = _engine_for("event")
    candidate = _engine_for("vectorized")
    logger.debug(
        "reconcile: strategy=%s strict=%s tol=%s", config.strategy, strict, tolerance
    )

    report = _engine_reconcile(
        reference,
        candidate,
        strategy,
        config,
        feed,
        broker,
        tolerance=tolerance,
        strict=strict,
    )
    return OBBject(
        results=ReconciliationReport(
            passed=report.passed,
            max_divergence=report.max_divergence,
            tolerance=report.tolerance,
            reference_engine=report.reference_engine,
            candidate_engine=report.candidate_engine,
        )
    )
