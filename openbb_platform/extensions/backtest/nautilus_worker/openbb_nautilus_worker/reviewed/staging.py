"""Settlement-aware sell-then-buy staging ``sell_then_buy_v1`` (#1356 T03).

Pure planner state (plan section 2.2). Nautilus' CASH account has no settlement
concept, so settled cash is OpenBB logic here, counted in sessions of the
manifest calendar:

1. At the start of each fill event, unsettled lots whose settle session is at
   or before the event's session move to settled cash.
2. Sells first, in symbol order, for every over-weight symbol. Net proceeds
   (booked notional minus booked commission) become an unsettled lot that
   settles ``k`` sessions later (T+1: ``k=1``, T+2: ``k=2``).
3. Then buys, in symbol order: the largest whole quantity, up to the target,
   whose booked notional plus booked commission fits in the settled cash left.
   Settled cash is debited on the trade date. Unsettled proceeds never fund a
   buy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from . import booking

SETTLEMENT_LAG = {"T+1": 1, "T+2": 2}


@dataclass(frozen=True)
class PlannedOrder:
    """A market order the host submits at a fill event."""

    symbol: str
    side: str  # "buy" | "sell"
    quantity: int


@dataclass
class Ledger:
    """Settled cash, unsettled lots ``(settle_session, amount)`` and holdings."""

    settled: Decimal
    lag: int
    unsettled: list[tuple[int, Decimal]] = field(default_factory=list)
    held: dict[str, int] = field(default_factory=dict)

    @property
    def cash(self) -> Decimal:
        """Settled plus unsettled cash."""
        return self.settled + sum((a for _, a in self.unsettled), Decimal(0))

    def release(self, session: int) -> None:
        """Move every lot due at or before ``session`` to settled cash."""
        due = [lot for lot in self.unsettled if lot[0] <= session]
        self.unsettled = [lot for lot in self.unsettled if lot[0] > session]
        self.settled += sum((a for _, a in due), Decimal(0))

    def apply(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: int,
        symbol: str,
        side: str,
        quantity: int,
        booked: Decimal,
        fee: Decimal,
    ) -> None:
        """Book one fill; a buy beyond settled cash or an oversell is an error."""
        held = self.held.get(symbol, 0)
        if side == "buy":
            cost = booked + fee
            if cost > self.settled:
                raise ValueError("buy exceeds settled cash")
            self.settled -= cost
            self.held[symbol] = held + quantity
        elif side == "sell":
            if quantity > held:
                raise ValueError("sell exceeds the holding (no shorting)")
            self.unsettled.append((session + self.lag, booked - fee))
            self.held[symbol] = held - quantity
        else:
            raise ValueError(f"unknown side {side!r}")


def max_affordable(budget: Decimal, price: Decimal, rate: Decimal, cap: int) -> int:
    """Largest ``q <= cap`` with ``buy_cost(q) <= budget`` (booked amounts)."""
    if cap <= 0 or budget <= 0:
        return 0
    q = min(cap, int(budget // price) + 1)
    while q > 0 and booking.buy_cost(q, price, rate) > budget:
        q -= 1
    return q


def plan_orders(
    ledger: Ledger,
    targets: Mapping[str, int],
    prices: Mapping[str, Decimal],
    rate: Decimal,
) -> list[PlannedOrder]:
    """Sells (symbol order), then buys (symbol order) against settled cash.

    Does not change the ledger: the host books the engine's fills.
    """
    sells, buys = [], []
    for sym in sorted(targets):
        held = ledger.held.get(sym, 0)
        if held > targets[sym]:
            sells.append(PlannedOrder(sym, "sell", held - targets[sym]))
    budget = ledger.settled
    for sym in sorted(targets):
        need = targets[sym] - ledger.held.get(sym, 0)
        q = max_affordable(budget, prices[sym], rate, need)
        if q > 0:
            buys.append(PlannedOrder(sym, "buy", q))
            budget -= booking.buy_cost(q, prices[sym], rate)
    return sells + buys


def pending(ledger: Ledger, targets: Mapping[str, int] | None) -> bool:
    """Whether a target is still not met."""
    if not targets:
        return False
    return any(ledger.held.get(s, 0) != q for s, q in targets.items())
