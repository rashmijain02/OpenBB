"""Project a worker ``run`` body onto the canonical ``BacktestResult`` (#1356 T02).

Field rules (plan §2.4): session dates as tz-aware 00:00 UTC; equity and cash as
exact ``Decimal`` quantised to cents (HALF_EVEN); cash is re-derived here from
the reported fills and must agree with the worker's own figure; metrics come
from the same ``_metrics_from_returns`` the legacy engines use. An inconsistent
body is an error, never an empty or partial result.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

import numpy as np
from openbb_nautilus_worker.reviewed import registry

from openbb_backtest.errors import BackendUnavailableError
from openbb_backtest.models import (
    BacktestConfig,
    BackendSource,
    BacktestResult,
    EquityPoint,
    PositionSnapshot,
    RunProvenance,
    Trade,
)

_CENT = Decimal("0.01")
_SIDES = {"buy": 1, "sell": -1}


def _bad(message: str, reason: str = "inconsistent_result") -> BackendUnavailableError:
    return BackendUnavailableError(
        f"nautilus result is inconsistent: {message}", reason=reason, code="process"
    )


def _cents(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _utc(session: str) -> datetime:
    return datetime.combine(date.fromisoformat(session[:10]), time(0), timezone.utc)


def _check_binding(body: dict[str, Any], binding: registry.Binding) -> dict[str, Any]:
    """Check the worker bound exactly the tuple the facade sent; return it."""
    got = body.get("binding")
    expected = registry.run_binding(
        binding, body["dataset_id"], str(body["engine"]["version"])
    )
    if got != expected:
        raise _bad("the worker bound a different strategy tuple", "binding_mismatch")
    return expected


def _walk(body: dict[str, Any], sessions: list[str], start: Decimal):
    """Re-derive per-session cash and the position from the reported fills."""
    index = {s: i for i, s in enumerate(sessions)}
    by_session: list[list[dict[str, Any]]] = [[] for _ in sessions]
    for fill in body["fills"]:
        quantity = fill["quantity"]
        if fill["session"] not in index or fill["side"] not in _SIDES:
            raise _bad("a fill names an unknown session or side")
        if not isinstance(quantity, int) or quantity <= 0:
            raise _bad("a fill quantity is not a positive whole number")
        if Decimal(str(fill["commission"])) < 0 or Decimal(str(fill["price"])) <= 0:
            raise _bad("a fill has a negative commission or non-positive price")
        by_session[index[fill["session"]]].append(fill)
    cash, position, cash_curve = start, 0, []
    for fills in by_session:
        for fill in fills:
            sign = _SIDES[fill["side"]]
            notional = fill["quantity"] * Decimal(str(fill["price"]))
            cash += -sign * notional - Decimal(str(fill["commission"]))
            position += sign * fill["quantity"]
        cash_curve.append(cash)
    if position != body["quantity"]:
        raise _bad("fills do not add up to the reported quantity")
    if cash < 0 or position < 0:
        raise _bad("the ledger went negative")
    if _cents(cash) != _cents(body["cash"]):
        raise _bad("cash re-derived from fills disagrees with the worker")
    return cash_curve, position, by_session


def _metrics(equity: list[Decimal], start: Decimal, exposure: list[float]):
    from openbb_backtest.engine import (  # pylint: disable=import-outside-toplevel
        vectorized,
    )

    values = np.array([float(e) for e in equity])
    previous = np.concatenate([[float(start)], values[:-1]])
    returns = values / previous - 1.0
    turnover_series = np.abs(np.diff(np.array(exposure), prepend=0.0))
    # pylint: disable=protected-access
    return vectorized._metrics_from_returns(values, returns, turnover_series)


def _provenance(  # pylint: disable=too-many-arguments
    body: dict[str, Any],
    bound: dict[str, Any],
    binding: registry.Binding,
    *,
    backend_source: BackendSource,
    runtime: str,
    facts: Any,
    qualified: bool | None,
) -> RunProvenance:
    return RunProvenance(
        backend="nautilus",
        backend_source=backend_source,
        engine="nautilus",
        strategy_review="reviewed",
        runtime=runtime,
        qualified=qualified,
        engine_name=str(body["engine"]["name"]),
        engine_version=str(body["engine"]["version"]),
        python_version=getattr(facts, "python_version", None),
        wheel_tag=getattr(facts, "wheel_tag", None),
        fixed_precision=body.get("fixed_precision"),
        dataset_id=body["dataset_id"],
        bars_sha256=body.get("bars_sha256"),
        strategy_id=binding.strategy_id,
        strategy_version=binding.version,
        spec_sha256=binding.spec_sha256,
        code_sha256=binding.code_sha256,
        param_schema_sha256=binding.param_schema_sha256,
        params_sha256=binding.params_sha256,
        execution_sha256=binding.execution_sha256,
        binding_sha256=bound["binding_sha256"],
        execution=binding.execution.canonical(),
    )


def _project(  # pylint: disable=too-many-locals
    body: dict[str, Any],
    config: BacktestConfig,
    binding: registry.Binding,
    **prov: Any,
) -> BacktestResult:
    sessions = [str(s) for s in body["sessions"]]
    equity = [_cents(e) for e in body["equity"]]
    if not sessions:
        raise _bad("the worker reported no sessions")
    if len(equity) != len(sessions):
        raise _bad("equity and sessions differ in length")
    if _cents(body["final_equity"]) != equity[-1]:
        raise _bad("final equity disagrees with the equity curve")
    start = Decimal(str(body["starting_cash"]))
    if start != config.initial_cash:
        raise _bad("starting cash differs from the config")
    bound = _check_binding(body, binding)
    symbol = str(body["symbol"])
    cash_curve, position, by_session = _walk(body, sessions, start)

    curve, exposure = [], []
    for session, eq, cash in zip(sessions, equity, cash_curve):
        weight = float((eq - cash) / eq) if eq != 0 else 0.0
        exposure.append(weight)
        curve.append(
            EquityPoint(
                date=_utc(session), equity=eq, cash=_cents(cash), exposure=weight
            )
        )
    trades = [
        Trade(
            timestamp=_utc(session),
            symbol=symbol,
            side=fill["side"],
            quantity=Decimal(fill["quantity"]),
            price=Decimal(str(fill["price"])),
            commission=_cents(fill["commission"]),
            slippage=Decimal(0),
        )
        for session, fills in zip(sessions, by_session)
        for fill in fills
    ]
    positions = (
        [
            PositionSnapshot(
                date=curve[-1].date,
                symbol=symbol,
                quantity=Decimal(position),
                market_value=equity[-1] - _cents(cash_curve[-1]),
                weight=exposure[-1],
            )
        ]
        if position
        else []
    )
    return BacktestResult(
        equity_curve=curve,
        trades=trades,
        positions=positions,
        metrics=_metrics(equity, start, exposure),
        engine_used="nautilus",
        config=config,
        provenance=_provenance(body, bound, binding, **prov),
    )


def to_backtest_result(  # pylint: disable=too-many-arguments
    body: dict[str, Any],
    *,
    config: BacktestConfig,
    binding: registry.Binding,
    backend_source: BackendSource,
    runtime: str,
    facts: Any = None,
    qualified: bool | None = None,
) -> BacktestResult:
    """Project a worker ``run`` body; raise ``BackendUnavailableError`` if bad.

    The body is the single-instrument report of the #1355 runner plus its
    ``fills``; multi-instrument bodies arrive with #1356 T03.
    """
    try:
        return _project(
            body,
            config,
            binding,
            backend_source=backend_source,
            runtime=runtime,
            facts=facts,
            qualified=qualified,
        )
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError) as exc:
        raise _bad(f"malformed body ({type(exc).__name__})") from exc
