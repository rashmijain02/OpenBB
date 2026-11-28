"""Worker op ``run``: buy-and-hold on an admitted dataset (#1355 T03).

The request carries an opaque ``dataset_id`` only. Admission
(:mod:`admission`) runs first; then, under the heavy-job lock and a hard
wall-time :class:`~guards.Deadline`, the bars are loaded, the strategy decides
its order, the *engine seam* executes it and this module does the accounting.

The engine reports fills (and optionally its own final cash, which is
cross-checked); it never computes the report. The default engine is
Nautilus' ``BacktestEngine`` on the simulated venue (imported lazily; LIVE
T03-L verifies it reproduces the hand-computed oracle). Tests inject a fake.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import pyarrow.parquet as pq

from . import (
    admission,
    catalog_build,
    dataset as ds,
    guards,
)
from .protocol import ErrorCode, ProtocolError

LOCK_NAME = ".heavy.lock"
MAX_SESSIONS = 50_000
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Order:
    """A market buy decided by the strategy at ``sessions[session_index]``."""

    symbol: str
    quantity: int
    session_index: int = 0


@dataclass(frozen=True)
class RunSpec:
    """Everything the engine needs; prices as exact decimals."""

    symbol: str
    price_precision: int
    sessions: list[str]
    closes: list[Decimal]
    bars: list[dict[str, Any]]
    starting_cash: Decimal
    order: Order


@dataclass(frozen=True)
class Fill:
    """One execution reported by the engine."""

    session: str
    quantity: int
    price: Decimal
    commission: Decimal


@dataclass(frozen=True)
class EngineResult:
    """Engine identity, fills and (optionally) the engine's own final cash."""

    name: str
    version: str
    fills: list[Fill] = field(default_factory=list)
    final_cash: Decimal | None = None


Engine = Callable[[RunSpec], EngineResult]


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT))


def buy_and_hold_order(symbol: str, closes: list[Decimal], cash: Decimal) -> Order:
    """All-in at the first close: ``floor(cash / close)`` whole shares."""
    qty = int((cash / closes[0]).to_integral_value(rounding=ROUND_FLOOR))
    if qty < 1:
        raise ProtocolError(ErrorCode.SCHEMA, "starting cash buys no whole share")
    return Order(symbol=symbol, quantity=qty)


def account(spec: RunSpec, result: EngineResult) -> dict[str, Any]:
    """Cash, position and per-session equity from the engine's fills."""
    sessions = set(spec.sessions)
    for fill in result.fills:
        if fill.session not in sessions or fill.quantity < 0 or fill.commission < 0:
            raise ProtocolError(ErrorCode.PROCESS, "engine reported an invalid fill")
    filled = sum(f.quantity for f in result.fills)
    if filled != spec.order.quantity:
        raise ProtocolError(
            ErrorCode.PROCESS,
            f"engine filled {filled} of {spec.order.quantity} shares",
        )
    cash, position, equity = spec.starting_cash, 0, []
    for session, close in zip(spec.sessions, spec.closes):
        for fill in (f for f in result.fills if f.session == session):
            cash -= fill.quantity * fill.price + fill.commission
            position += fill.quantity
        equity.append(_money(cash + position * close))
    if cash < 0:
        raise ProtocolError(ErrorCode.PROCESS, "engine overspent the cash account")
    if result.final_cash is not None and result.final_cash.quantize(
        _CENT
    ) != cash.quantize(_CENT):
        raise ProtocolError(
            ErrorCode.PROCESS, "engine cash disagrees with the fills it reported"
        )
    return {"quantity": position, "cash": _money(cash), "equity": equity}


def _load_spec(adm: admission.Admitted) -> RunSpec:
    inst = adm.manifest.instruments[0]
    rows = sorted(
        (
            r
            for r in pq.read_table(adm.dataset_dir / ds.BARS_FILE).to_pylist()
            if r["symbol"] == inst.symbol
        ),
        key=lambda r: r["ts_event"],
    )
    if not rows:
        raise ProtocolError(ErrorCode.SCHEMA, "dataset has no bars for its symbol")
    if len(rows) > MAX_SESSIONS:
        raise ProtocolError(ErrorCode.CONFIG, "dataset exceeds the session bound")
    places = inst.price_precision
    closes = [Decimal(r["close"]).scaleb(-places) for r in rows]
    cash = Decimal(adm.request.starting_cash)
    return RunSpec(
        symbol=inst.symbol,
        price_precision=places,
        sessions=[r["session"].isoformat() for r in rows],
        closes=closes,
        bars=rows,
        starting_cash=cash,
        order=buy_and_hold_order(inst.symbol, closes, cash),
    )


def nautilus_engine(
    spec: RunSpec,
) -> EngineResult:  # pragma: no cover - needs nautilus_trader (LIVE T03-L)
    """Run the order through ``BacktestEngine`` on venue SIM (netting, cash)."""
    # pylint: disable=import-outside-toplevel,import-error,too-many-locals
    try:
        import nautilus_trader
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
        from nautilus_trader.model.currencies import USD
        from nautilus_trader.model.data import Bar, BarType
        from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
        from nautilus_trader.model.instruments import Equity
        from nautilus_trader.model.objects import Money, Price, Quantity
        from nautilus_trader.trading.strategy import Strategy
    except ImportError as exc:
        raise ProtocolError(
            ErrorCode.MODULE_ORIGIN, "nautilus_trader is not importable"
        ) from exc

    venue = Venue(catalog_build.VENUE)
    iid = InstrumentId.from_str(f"{spec.symbol}.{catalog_build.VENUE}")
    places = spec.price_precision
    bar_type = BarType.from_str(catalog_build.bar_type_str(spec.symbol))

    def price(value: int) -> Any:
        return Price.from_str(catalog_build.scaled_to_str(value, places))

    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True))
    )
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=USD,
        starting_balances=[Money(spec.starting_cash, USD)],
    )
    engine.add_instrument(
        Equity(
            instrument_id=iid,
            raw_symbol=Symbol(spec.symbol),
            currency=USD,
            price_precision=places,
            price_increment=Price.from_str(catalog_build.scaled_to_str(1, places)),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )
    )
    engine.add_data(
        [
            Bar(
                bar_type,
                price(r["open"]),
                price(r["high"]),
                price(r["low"]),
                price(r["close"]),
                Quantity.from_int(r["volume"]),
                r["ts_event"],
                r["ts_init"],
            )
            for r in spec.bars
        ]
    )

    class BuyAndHold(Strategy):  # pylint: disable=too-few-public-methods
        """Submit the decided market buy on the first bar, then hold."""

        done = False

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)

        def on_bar(self, _bar) -> None:
            if not self.done:
                self.done = True
                self.submit_order(
                    self.order_factory.market(
                        iid, OrderSide.BUY, Quantity.from_int(spec.order.quantity)
                    )
                )

    engine.add_strategy(BuyAndHold())
    engine.run()
    ts_to_session = {r["ts_event"]: r["session"].isoformat() for r in spec.bars}
    fills = [
        Fill(
            session=ts_to_session.get(order.ts_last, ""),
            quantity=int(order.filled_qty.as_double()),
            price=Decimal(str(order.avg_px)),
            commission=sum(
                (Decimal(str(c.as_decimal())) for c in order.commissions()),
                Decimal(0),
            ),
        )
        for order in engine.cache.orders()
        if order.filled_qty.as_double() > 0
    ]
    final_cash = engine.portfolio.account(venue).balance_total(USD).as_decimal()
    engine.dispose()
    return EngineResult(
        name="nautilus_trader.BacktestEngine",
        version=str(nautilus_trader.__version__),
        fills=fills,
        final_cash=Decimal(str(final_cash)),
    )


def run(
    body: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    engine: Engine | None = None,
    fixed_precision: int | None = None,
    on_deadline: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Admit, then run buy-and-hold under the heavy-job lock and a deadline."""
    req = admission.screen_request(body)
    root = catalog_build.data_root(os.environ if env is None else env)
    if fixed_precision is None:
        try:
            fixed_precision = catalog_build.runtime_fixed_precision()
        except ImportError as exc:
            raise ProtocolError(
                ErrorCode.MODULE_ORIGIN, "nautilus_trader is not importable"
            ) from exc
    adm = admission.admit_run(req, root / "datasets", fixed_precision)
    deadline = guards.Deadline(
        req.deadline_seconds, **({"on_expire": on_deadline} if on_deadline else {})
    )
    with guards.HeavyJobLock(root / "runs" / LOCK_NAME), deadline:
        spec = _load_spec(adm)
        result = (engine or nautilus_engine)(spec)
        books = account(spec, result)
    return {
        "dataset_id": req.dataset_id,
        "strategy": req.strategy,
        "venue": req.venue,
        "symbol": spec.symbol,
        "engine": {"name": result.name, "version": result.version},
        "fixed_precision": fixed_precision,
        "bars_sha256": adm.manifest.content.bars_sha256,
        "sessions": spec.sessions,
        "starting_cash": _money(spec.starting_cash),
        "final_equity": books["equity"][-1],
        **books,
    }
