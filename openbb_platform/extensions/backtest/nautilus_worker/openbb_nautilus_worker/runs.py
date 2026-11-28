"""Worker op ``run``: reviewed strategies on an admitted dataset (#1355, #1356).

The request carries an opaque ``dataset_id`` only. Admission
(:mod:`admission`) runs first; then, under the heavy-job lock and a hard
wall-time :class:`~guards.Deadline`, the bars are loaded and the *engine seam*
drives the reviewed host (:mod:`reviewed.host`): it replays each session's fill
event (a synthetic open print for ``next_open``, the bar close for
``same_close``) and close, submits exactly the orders the host returns and
reports its fills. Settlement, staging and sizing live in the host, never in
the engine (a Nautilus CASH account has no settlement concept).

This module then repeats the plan independently from the reported fills
(:func:`account`): every fill must equal a staged order at the event price with
the declared commission, the books never use unsettled cash, and the engine's
own final cash must equal the ledger at cents, with no tolerance. A denied or
rejected order is a loud ``process`` error, never a skipped trade. The default
engine is Nautilus' ``BacktestEngine`` (imported lazily; LIVE T03-L verifies it
reproduces the hand-computed cash cases). Tests inject a fake.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from . import (
    admission,
    catalog_build,
    guards,
)
from .protocol import ErrorCode, ProtocolError
from .reviewed import booking, host, registry, staging
from .reviewed.spec import ExecutionAssumptions

LOCK_NAME = ".heavy.lock"
MAX_SESSIONS = 50_000
_CENT = booking.CENT
#: #1355 alias ``strategy="buy_and_hold"``: fill at the decision close, zero fees.
ALIAS_EXECUTION = ExecutionAssumptions(fill_timing="same_close")
EXECUTABLE = {
    "strategy_id": ("buy_and_hold", "target_weight_rebalance"),
    "fill_timing": ("next_open", "same_close"),
    "fees": ("zero", "taker_bps"),
}


@dataclass(frozen=True)
class RunSpec:  # pylint: disable=too-many-instance-attributes
    """Everything the engine needs; prices as exact decimals per symbol."""

    symbols: tuple[str, ...]
    price_precision: dict[str, int]
    sessions: list[str]
    opens: dict[str, list[Decimal]]
    closes: dict[str, list[Decimal]]
    bars: list[dict[str, Any]]
    starting_cash: Decimal
    execution: ExecutionAssumptions
    strategy_id: str
    params: dict[str, Any]

    def make_host(self) -> host.HostCore:
        """Return a fresh reviewed host (planner and settled-cash ledger)."""
        return host.HostCore(
            symbols=self.symbols,
            cash=self.starting_cash,
            execution=self.execution,
            decide=host.decider(self.strategy_id, self.params),
        )

    def prices(self, which: str, session: int) -> dict[str, Decimal]:
        """``open`` or ``close`` of every symbol at ``session``."""
        table = self.opens if which == "open" else self.closes
        return {s: table[s][session] for s in self.symbols}


@dataclass(frozen=True)
class Fill:  # pylint: disable=too-many-instance-attributes
    """One execution reported by the engine."""

    session: str
    quantity: int
    price: Decimal
    commission: Decimal
    symbol: str = ""
    side: str = "buy"


@dataclass(frozen=True)
class EngineResult:
    """Engine identity, fills, denials and (optionally) the engine's final cash."""

    name: str
    version: str
    fills: list[Fill] = field(default_factory=list)
    final_cash: Decimal | None = None
    denied: list[str] = field(default_factory=list)


Engine = Callable[[RunSpec], EngineResult]


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT))


def _process(message: str) -> ProtocolError:
    return ProtocolError(ErrorCode.PROCESS, message)


def _book_event(
    core: host.HostCore,
    index: int,
    planned: list[staging.PlannedOrder],
    fills: list[Fill],
    prices: Mapping[str, Decimal],
) -> None:
    """Every fill of the event must be the staged order at the event price."""
    got = [(f.symbol, f.side, f.quantity) for f in fills]
    want = [(o.symbol, o.side, o.quantity) for o in planned]
    if got != want:
        raise _process(
            f"engine fills {got} differ from the staged orders {want} "
            f"at session {index}"
        )
    for fill in fills:
        if fill.price != prices[fill.symbol]:
            raise _process("engine filled away from the event price")
        fee = booking.commission(booking.notional(fill.quantity, fill.price), core.rate)
        if fill.commission != fee:
            raise _process("engine commission differs from the declared rule")
        core.on_fill(
            index, fill.symbol, fill.side, fill.quantity, fill.price, fill.commission
        )
    if core.errors:
        raise _process(f"ledger rejected a fill: {core.errors[0]}")


def account(spec: RunSpec, result: EngineResult) -> dict[str, Any]:
    """Repeat sizing and staging from the engine's fills; return the books."""
    if result.denied:
        raise _process(f"engine denied or rejected an order: {result.denied[0]}")
    index = {s: i for i, s in enumerate(spec.sessions)}
    per_session: list[list[Fill]] = [[] for _ in spec.sessions]
    for fill in result.fills:
        if (
            fill.session not in index
            or fill.symbol not in spec.symbols
            or fill.side not in ("buy", "sell")
            or fill.quantity <= 0
            or fill.commission < 0
        ):
            raise _process("engine reported an invalid fill")
        per_session[index[fill.session]].append(fill)
    core = spec.make_host()
    at_open = spec.execution.fill_timing == "next_open"
    equity = []
    for i, fills in enumerate(per_session):
        opens, closes = spec.prices("open", i), spec.prices("close", i)
        planned = core.on_open(i, opens)
        if at_open:
            _book_event(core, i, planned, fills, opens)
        planned = core.on_close(i, closes)
        if not at_open:
            _book_event(core, i, planned, fills, closes)
        equity.append(_money(core.mark(closes)))
    core.finish()
    cash = core.ledger.cash
    if result.final_cash is not None and result.final_cash.quantize(
        _CENT
    ) != cash.quantize(_CENT):
        raise _process("engine cash disagrees with the fills it reported")
    return {
        "positions": dict(core.ledger.held),
        "cash": _money(cash),
        "equity": equity,
        "booking_residual": str(core.residual),
        "warnings": list(core.warnings),
    }


def _strategy_of(adm: admission.Admitted):
    binding = adm.binding
    if binding is None:
        symbols = (adm.manifest.instruments[0].symbol,)
        return symbols, ALIAS_EXECUTION, "buy_and_hold", {"symbols": list(symbols)}
    return (
        tuple(sorted(binding.symbols)),
        binding.execution,
        binding.strategy_id,
        dict(binding.params),
    )


def _load_spec(adm: admission.Admitted) -> RunSpec:  # pylint: disable=too-many-locals
    symbols, execution, strategy_id, params = _strategy_of(adm)
    facts = {i.symbol: i for i in adm.manifest.instruments}
    all_rows = adm.bars.to_pylist()
    opens: dict[str, list[Decimal]] = {}
    closes: dict[str, list[Decimal]] = {}
    sessions: list[str] | None = None
    used: list[dict[str, Any]] = []
    for sym in symbols:
        rows = sorted(
            (r for r in all_rows if r["symbol"] == sym), key=lambda r: r["ts_event"]
        )
        if not rows:
            raise ProtocolError(ErrorCode.SCHEMA, f"dataset has no bars for {sym}")
        if len(rows) > MAX_SESSIONS:
            raise ProtocolError(ErrorCode.CONFIG, "dataset exceeds the session bound")
        days = [r["session"].isoformat() for r in rows]
        if sessions is None:
            sessions = days
        elif days != sessions:
            raise ProtocolError(
                ErrorCode.SCHEMA, "sessions_misaligned: symbols differ in sessions"
            )
        places = facts[sym].price_precision
        opens[sym] = [Decimal(r["open"]).scaleb(-places) for r in rows]
        closes[sym] = [Decimal(r["close"]).scaleb(-places) for r in rows]
        used.extend(rows)
    cash = Decimal(adm.request.starting_cash)
    spec = RunSpec(
        symbols=symbols,
        price_precision={s: facts[s].price_precision for s in symbols},
        sessions=sessions or [],
        opens=opens,
        closes=closes,
        bars=sorted(used, key=lambda r: (r["ts_event"], r["symbol"])),
        starting_cash=cash,
        execution=execution,
        strategy_id=strategy_id,
        params=params,
    )
    if strategy_id == "buy_and_hold":
        first = host.decider(strategy_id, params)(0, cash, spec.prices("close", 0))
        if not first or not any(first.values()):
            raise ProtocolError(ErrorCode.SCHEMA, "starting cash buys no whole share")
    return spec


def nautilus_engine(
    spec: RunSpec,
) -> EngineResult:  # pragma: no cover - needs nautilus_trader (LIVE T03-L)
    """Drive the reviewed host through ``BacktestEngine`` on venue SIM.

    Netting OMS, CASH account, no borrowing. ``next_open`` adds a synthetic
    open print (``TradeTick`` at ``bar.ts_event - 1`` ns, price = bar open) per
    symbol and session; the dataset schema is unchanged. ``taker_bps`` fees are
    the instrument's taker fee.
    """
    # pylint: disable=import-outside-toplevel,import-error,too-many-locals
    try:
        import nautilus_trader
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
        from nautilus_trader.model.currencies import USD
        from nautilus_trader.model.data import Bar, BarType, TradeTick
        from nautilus_trader.model.enums import AccountType, AggressorSide, OmsType
        from nautilus_trader.model.identifiers import (
            InstrumentId,
            Symbol,
            TradeId,
            Venue,
        )
        from nautilus_trader.model.instruments import Equity
        from nautilus_trader.model.objects import Money, Price, Quantity
    except ImportError as exc:
        raise ProtocolError(
            ErrorCode.MODULE_ORIGIN, "nautilus_trader is not importable"
        ) from exc

    venue = Venue(catalog_build.VENUE)
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True))
    )
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=USD,
        starting_balances=[Money(spec.starting_cash, USD)],
        bar_execution=True,
        trade_execution=True,
    )
    fee = booking.taker_rate(spec.execution.taker_bps)
    instruments: dict[str, Any] = {}
    for sym in spec.symbols:
        iid = InstrumentId.from_str(f"{sym}.{catalog_build.VENUE}")
        places = spec.price_precision[sym]
        engine.add_instrument(
            Equity(
                instrument_id=iid,
                raw_symbol=Symbol(sym),
                currency=USD,
                price_precision=places,
                price_increment=Price.from_str(catalog_build.scaled_to_str(1, places)),
                lot_size=Quantity.from_int(1),
                ts_event=0,
                ts_init=0,
                maker_fee=fee,
                taker_fee=fee,
            )
        )
        instruments[sym] = (iid, BarType.from_str(catalog_build.bar_type_str(sym)))

    def price(sym: str, value: int) -> Any:
        return Price.from_str(
            catalog_build.scaled_to_str(value, spec.price_precision[sym])
        )

    data: list[Any] = []
    session_of: dict[int, int] = {}
    index = {s: i for i, s in enumerate(spec.sessions)}
    for n, r in enumerate(spec.bars):
        sym, ts = r["symbol"], r["ts_event"]
        session_of[ts] = session_of[ts - 1] = index[r["session"].isoformat()]
        if spec.execution.fill_timing == "next_open":
            data.append(
                TradeTick(
                    instruments[sym][0],
                    price(sym, r["open"]),
                    Quantity.from_int(r["volume"] or 1),
                    AggressorSide.NO_AGGRESSOR,
                    TradeId(f"open-{n}"),
                    ts - 1,
                    ts - 1,
                )
            )
        data.append(
            Bar(
                instruments[sym][1],
                price(sym, r["open"]),
                price(sym, r["high"]),
                price(sym, r["low"]),
                price(sym, r["close"]),
                Quantity.from_int(r["volume"]),
                ts,
                r["ts_init"],
            )
        )
    engine.add_data(data)
    strategy = host.nautilus_host(spec.make_host(), instruments, session_of)
    engine.add_strategy(strategy)
    engine.run()
    by_iid = {str(iid): sym for sym, (iid, _bt) in instruments.items()}
    fills = [
        Fill(
            session=spec.sessions[session_of[ev.ts_event]],
            quantity=int(ev.last_qty.as_double()),
            price=Decimal(str(ev.last_px)),
            commission=Decimal(str(ev.commission.as_decimal())),
            symbol=by_iid[str(ev.instrument_id)],
            side="buy" if ev.order_side.name == "BUY" else "sell",
        )
        for order in engine.cache.orders()
        for ev in order.events
        if type(ev).__name__ == "OrderFilled"
    ]
    fills.sort(key=lambda f: (index[f.session], f.side != "sell", f.symbol))
    final_cash = engine.portfolio.account(venue).balance_total(USD).as_decimal()
    engine.dispose()
    return EngineResult(
        name="nautilus_trader.BacktestEngine",
        version=str(nautilus_trader.__version__),
        fills=fills,
        final_cash=Decimal(str(final_cash)),
        denied=list(strategy.denied),
    )


def _assert_executable(binding: registry.Binding | None) -> None:
    """Fail closed on reviewed semantics this runner does not implement.

    Both reviewed strategies run with ``next_open`` or ``same_close`` fills and
    zero or taker-bps fees (#1356 T03); anything else is never approximated.
    """
    if binding is None:
        return
    execution = binding.execution
    if (
        binding.strategy_id not in EXECUTABLE["strategy_id"]
        or execution.fill_timing not in EXECUTABLE["fill_timing"]
        or execution.fees not in EXECUTABLE["fees"]
    ):
        raise ProtocolError(
            ErrorCode.CONFIG,
            "execution_not_executable: reviewed but not runnable "
            f"({binding.strategy_id}, {execution.fill_timing}, fees={execution.fees})",
        )


def _fills(result: EngineResult) -> list[dict[str, Any]]:
    return [
        {
            "session": f.session,
            "symbol": f.symbol,
            "side": f.side,
            "quantity": f.quantity,
            "price": str(f.price),
            "commission": _money(f.commission),
        }
        for f in result.fills
    ]


def run(
    body: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    engine: Engine | None = None,
    fixed_precision: int | None = None,
    on_deadline: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Admit, then run the reviewed host under the heavy-job lock and a deadline."""
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
    _assert_executable(adm.binding)
    deadline = guards.Deadline(
        req.deadline_seconds, **({"on_expire": on_deadline} if on_deadline else {})
    )
    with guards.HeavyJobLock(root / "runs" / LOCK_NAME), deadline:
        spec = _load_spec(adm)
        result = (engine or nautilus_engine)(spec)
        books = account(spec, result)
    report = {
        "dataset_id": req.dataset_id,
        "strategy": req.strategy or (adm.binding.strategy_id if adm.binding else None),
        "venue": req.venue,
        "symbols": list(spec.symbols),
        "engine": {"name": result.name, "version": result.version},
        "fixed_precision": fixed_precision,
        "bars_sha256": adm.manifest.content.bars_sha256,
        "sessions": spec.sessions,
        "closes": {s: [str(c) for c in spec.closes[s]] for s in spec.symbols},
        "starting_cash": _money(spec.starting_cash),
        "final_equity": books["equity"][-1],
        **books,
        # The fills the books were derived from, so the facade can re-derive and
        # cross-check cash and project trades (#1356 T02/T03).
        "fills": _fills(result),
    }
    if len(spec.symbols) == 1:  # the #1355 single-instrument report keys
        report["symbol"] = spec.symbols[0]
        report["quantity"] = books["positions"][spec.symbols[0]]
    if adm.binding is not None:
        report["binding"] = registry.run_binding(
            adm.binding, req.dataset_id, result.version
        )
    return report
