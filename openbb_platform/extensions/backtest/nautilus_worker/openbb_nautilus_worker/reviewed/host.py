"""Reviewed strategy host (#1356 T03): one pure core, any engine.

:class:`HostCore` is the engine-agnostic strategy: the engine forwards each fill
event (the synthetic open print for ``next_open``, the bar close for
``same_close``) and each close, and submits exactly the orders the core returns.
The core sizes (:mod:`sizing`), stages (:mod:`staging`) and books the fills the
engine reports (:mod:`booking`). It owns settled cash; the engine does not.

:func:`nautilus_host` wraps the core in a Nautilus ``Strategy`` and imports
``nautilus_trader`` lazily, so this module stays importable without it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from . import booking, buy_and_hold, sizing, staging, target_weight_rebalance
from .params import BuyAndHoldParams, TargetWeightRebalanceParams
from .spec import ExecutionAssumptions

PENDING_AT_END = "orders_pending_at_end"

#: ``decide(session_index, equity, closes) -> targets | None``
Decide = Callable[[int, Decimal, Mapping[str, Decimal]], "dict[str, int] | None"]


def decider(strategy_id: str, params: Mapping[str, Any]) -> Decide:
    """Return the reviewed decision rule of ``strategy_id`` bound to its params."""
    if strategy_id == buy_and_hold.STRATEGY_ID:
        bah = BuyAndHoldParams.model_validate(dict(params))
        return lambda i, e, c: buy_and_hold.decide(bah, i, e, c)
    if strategy_id == target_weight_rebalance.STRATEGY_ID:
        twr = TargetWeightRebalanceParams.model_validate(dict(params))
        return lambda i, e, c: target_weight_rebalance.decide(twr, i, e, c)
    raise ValueError(f"no reviewed decision rule for {strategy_id!r}")


class HostCore:  # pylint: disable=too-many-instance-attributes
    """Pure reviewed host: decisions at closes, sell-then-buy at fill events."""

    def __init__(
        self,
        *,
        symbols: tuple[str, ...],
        cash: Decimal,
        execution: ExecutionAssumptions,
        decide: Decide,
    ) -> None:
        self.symbols = tuple(sorted(symbols))
        self.timing = execution.fill_timing
        self.rate = booking.taker_rate(execution.taker_bps)
        self.ledger = staging.Ledger(
            settled=cash,
            lag=staging.SETTLEMENT_LAG[execution.settlement],
            held={s: 0 for s in self.symbols},
        )
        self.decide = decide
        self.targets: dict[str, int] | None = None
        self.residual = Decimal("0.00")
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def _stage(
        self, session: int, prices: Mapping[str, Decimal]
    ) -> list[staging.PlannedOrder]:
        self.ledger.release(session)
        if not self.targets:
            return []
        return staging.plan_orders(self.ledger, self.targets, prices, self.rate)

    def on_open(
        self, session: int, opens: Mapping[str, Decimal]
    ) -> list[staging.PlannedOrder]:
        """Open print of ``session``: the fill event under ``next_open``."""
        if self.timing != "next_open":
            return []
        return self._stage(session, opens)

    def on_close(
        self, session: int, closes: Mapping[str, Decimal]
    ) -> list[staging.PlannedOrder]:
        """Close of ``session``: decide; the fill event under ``same_close``."""
        total = sizing.equity(self.ledger.cash, self.ledger.held, closes)
        new = self.decide(session, total, closes)
        if new is not None:
            self.targets = new
        if self.timing != "same_close":
            return []
        return self._stage(session, closes)

    def on_fill(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: int,
        symbol: str,
        side: str,
        quantity: int,
        price: Decimal,
        commission: Decimal,
    ) -> None:
        """Book one engine fill at its booked notional and reported commission."""
        booked = booking.notional(quantity, price)
        try:
            self.ledger.apply(session, symbol, side, quantity, booked, commission)
        except ValueError as exc:
            self.errors.append(str(exc))
            return
        self.residual += booking.residual(quantity, price)

    def mark(self, closes: Mapping[str, Decimal]) -> Decimal:
        """Equity at the closes, exact then HALF_EVEN cents."""
        return booking.mark(sizing.equity(self.ledger.cash, self.ledger.held, closes))

    def finish(self) -> None:
        """Drop orders still pending after the last session, with a warning."""
        if staging.pending(self.ledger, self.targets):
            self.warnings.append(PENDING_AT_END)


def nautilus_host(
    core: HostCore, instruments: Mapping[str, Any], session_of: Mapping[int, int]
) -> Any:  # pragma: no cover - needs nautilus_trader (LIVE T03-L)
    """Wrap ``core`` in a Nautilus ``Strategy`` that only forwards events.

    ``instruments`` maps symbol to ``(instrument_id, bar_type)``; ``session_of``
    maps an event ``ts`` (bar ``ts_event`` and open print ``ts_event - 1``) to
    the session index. Orders are submitted once every symbol's event of the
    session has arrived, sells first then buys, exactly as the core returns.
    """
    # pylint: disable=import-outside-toplevel,import-error
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.trading.strategy import Strategy

    by_iid = {str(iid): sym for sym, (iid, _bt) in instruments.items()}
    n = len(instruments)

    class ReviewedStrategyHost(Strategy):
        """Forward open prints, bars and fills to the pure core."""

        def __init__(self) -> None:
            super().__init__()
            self._opens: dict[int, dict[str, Decimal]] = {}
            self._closes: dict[int, dict[str, Decimal]] = {}
            self.denied: list[str] = []

        def on_start(self) -> None:
            for iid, bar_type in instruments.values():
                self.subscribe_bars(bar_type)
                self.subscribe_trade_ticks(iid)

        def _submit(self, orders) -> None:
            for order in orders:
                iid = instruments[order.symbol][0]
                side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
                self.submit_order(
                    self.order_factory.market(
                        iid, side, Quantity.from_int(order.quantity)
                    )
                )

        def on_trade_tick(self, tick) -> None:
            session = session_of[tick.ts_event]
            got = self._opens.setdefault(session, {})
            got[by_iid[str(tick.instrument_id)]] = Decimal(str(tick.price))
            if len(got) == n:
                self._submit(core.on_open(session, got))

        def on_bar(self, event_bar) -> None:
            session = session_of[event_bar.ts_event]
            got = self._closes.setdefault(session, {})
            got[by_iid[str(event_bar.bar_type.instrument_id)]] = Decimal(
                str(event_bar.close)
            )
            if len(got) == n:
                self._submit(core.on_close(session, got))

        def on_order_filled(self, event) -> None:
            fee = event.commission
            core.on_fill(
                session_of[event.ts_event],
                by_iid[str(event.instrument_id)],
                "buy" if event.order_side == OrderSide.BUY else "sell",
                int(event.last_qty.as_double()),
                Decimal(str(event.last_px)),
                Decimal(str(fee.as_decimal())) if fee is not None else Decimal(0),
            )

        def on_order_denied(self, event) -> None:
            self.denied.append(f"denied: {event.reason}")

        def on_order_rejected(self, event) -> None:
            self.denied.append(f"rejected: {event.reason}")

    return ReviewedStrategyHost()
