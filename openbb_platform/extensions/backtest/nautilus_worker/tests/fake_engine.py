"""Event-replay fake engine for the ``run`` seam (#1356 T03).

Stands in for Nautilus' ``BacktestEngine`` on a CASH account: it replays each
session's open print (``next_open`` only) and close to the reviewed host,
fills every submitted order at the event price and books it the way the
engine does (``f64`` notional, ``Money`` half away from zero in cents, taker
commission on the booked notional). Like Nautilus it has **no settlement or
staging**: sale proceeds are free at once, and a buy beyond free cash or a
sell beyond the holding is denied. So settlement, sell-first staging and
sizing can only come from the code under test. Never imports nautilus_trader.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from openbb_nautilus_worker import runs


def _money_like_engine(x: float) -> Decimal:
    cents = Decimal(x * 100.0).to_integral_value(rounding=ROUND_HALF_UP)
    return cents.scaleb(-2).quantize(Decimal("0.01"))


def replay(spec: runs.RunSpec) -> runs.EngineResult:
    """Run the host over the bars; report fills, denials and the free cash."""
    core = spec.make_host()
    bps = spec.execution.taker_bps
    rate = Decimal(0) if bps is None else Decimal(bps) / 10_000
    cash, held = spec.starting_cash, dict.fromkeys(spec.symbols, 0)
    fills: list[runs.Fill] = []
    denied: list[str] = []

    def submit(i, orders, prices):
        nonlocal cash
        for order in orders:
            px = prices[order.symbol]
            notional = _money_like_engine(float(order.quantity) * float(px))
            fee = (
                _money_like_engine(float(notional * rate)) if rate else Decimal("0.00")
            )
            if order.side == "buy":
                if notional + fee > cash:
                    denied.append(f"{order.symbol} buy exceeds free cash")
                    continue
                cash -= notional + fee
                held[order.symbol] += order.quantity
            else:
                if order.quantity > held[order.symbol]:
                    denied.append(f"{order.symbol} sell exceeds the holding")
                    continue
                cash += notional - fee
                held[order.symbol] -= order.quantity
            fills.append(
                runs.Fill(
                    session=spec.sessions[i],
                    quantity=order.quantity,
                    price=px,
                    commission=fee,
                    symbol=order.symbol,
                    side=order.side,
                )
            )
            core.on_fill(i, order.symbol, order.side, order.quantity, px, fee)

    for i in range(len(spec.sessions)):
        opens, closes = spec.prices("open", i), spec.prices("close", i)
        submit(i, core.on_open(i, opens), opens)
        submit(i, core.on_close(i, closes), closes)
    return runs.EngineResult(
        name="fake-event-replay",
        version="0",
        fills=fills,
        final_cash=cash,
        denied=denied,
    )
