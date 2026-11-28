"""Sizing and settlement-aware staging against hand-computed cases (#1356 T03).

The planner is pure. Whole runs use the real host and the real independent
ledger (:func:`runs.account`) with the event-replay fake engine, which has no
settlement or staging of its own; the expected values are the literals of
``cash_cases.json`` (plan section 2.6), never recomputed by the code under test.
"""

# ruff: noqa: D103

from __future__ import annotations

from decimal import Decimal

import fake_engine
import pytest
from openbb_nautilus_worker import runs
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError
from openbb_nautilus_worker.reviewed import booking, host, staging
from openbb_nautilus_worker.reviewed.spec import ExecutionAssumptions

D = Decimal
CASES = ("c1", "c1p", "c2", "c2b", "c3a", "c3b", "c4")


def _spec(cash_cases, name) -> runs.RunSpec:
    case = cash_cases["cases"][name]
    symbols = tuple(sorted(case["bars"]))
    n = len(case["bars"][symbols[0]])
    return runs.RunSpec(
        symbols=symbols,
        price_precision={s: 3 for s in symbols},
        sessions=cash_cases["sessions"][:n],
        opens={s: [D(o) for o, _ in case["bars"][s]] for s in symbols},
        closes={s: [D(c) for _, c in case["bars"][s]] for s in symbols},
        bars=[],
        starting_cash=D(case["initial_cash"]),
        execution=ExecutionAssumptions.model_validate(case["execution"]),
        strategy_id=case["strategy"],
        params=case["params"],
    )


def _trades(spec, result):
    index = {s: i for i, s in enumerate(spec.sessions)}
    return [
        [index[f.session], f.symbol, f.side, f.quantity, f.price, f.commission]
        for f in result.fills
    ]


@pytest.mark.parametrize("name", CASES)
def test_cash_case_through_host_and_ledger(cash_cases, name):
    spec = _spec(cash_cases, name)
    result = fake_engine.replay(spec)
    books = runs.account(spec, result)
    exp = cash_cases["cases"][name]["expected"]
    assert books["positions"] == exp["positions"]
    assert books["cash"] == exp["cash"]
    assert books["equity"] == exp["equity"]
    assert D(books["booking_residual"]) == D(exp["booking_residual"])
    assert books["warnings"] == exp["warnings"]
    want = [[i, s, side, q, D(p), D(c)] for i, s, side, q, p, c in exp["trades"]]
    assert _trades(spec, result) == want


def test_c2_discriminates_settlement(cash_cases):
    """Without settlement, 25 BBB @ 40 would be bought at S4 (cash 80.00)."""
    spec = _spec(cash_cases, "c2")
    result = fake_engine.replay(spec)
    s4 = [f for f in result.fills if f.session == spec.sessions[3]]
    assert [(f.symbol, f.side, f.quantity) for f in s4] == [("AAA", "sell", 9)]
    assert runs.account(spec, result)["cash"] == "24.00"


def test_c6_buys_in_symbol_order_against_settled_cash(cash_cases):
    case = cash_cases["planner_cases"]["c6"]
    ledger = staging.Ledger(settled=D(case["settled"]), lag=1, held=dict(case["held"]))
    orders = staging.plan_orders(
        ledger,
        case["targets"],
        {s: D(p) for s, p in case["prices"].items()},
        D(0),
    )
    assert [[o.symbol, o.side, o.quantity] for o in orders] == case["expected_orders"]


def test_unsettled_proceeds_never_fund_buys():
    ledger = staging.Ledger(settled=D(0), lag=1, held={"AAA": 0})
    ledger.unsettled.append((5, D("1000.00")))
    ledger.release(4)
    assert not staging.plan_orders(ledger, {"AAA": 5}, {"AAA": D(100)}, D(0))
    ledger.release(5)
    assert staging.plan_orders(ledger, {"AAA": 5}, {"AAA": D(100)}, D(0)) == [
        staging.PlannedOrder("AAA", "buy", 5)
    ]
    with pytest.raises(ValueError, match="settled"):
        staging.Ledger(settled=D(0), lag=1).apply(0, "AAA", "buy", 1, D(1), D(0))


def test_sells_precede_buys_in_one_event():
    ledger = staging.Ledger(settled=D(100), lag=1, held={"AAA": 0, "ZZZ": 3})
    orders = staging.plan_orders(
        ledger, {"AAA": 1, "ZZZ": 0}, {"AAA": D(60), "ZZZ": D(10)}, D(0)
    )
    assert orders == [
        staging.PlannedOrder("ZZZ", "sell", 3),
        staging.PlannedOrder("AAA", "buy", 1),
    ]


def _core(decisions, cash):
    return host.HostCore(
        symbols=("AAA",),
        cash=D(cash),
        execution=ExecutionAssumptions(fill_timing="next_open"),
        decide=lambda i, _e, _c: decisions.get(i),
    )


def _fill_all(core, i, orders, prices):
    for o in orders:
        core.on_fill(i, o.symbol, o.side, o.quantity, prices[o.symbol], D(0))


def test_shortfall_retried_then_superseded():
    core = _core({0: {"AAA": 20}, 2: {"AAA": 5}}, "1050.00")
    opens = [D(100), D(100), D(50), D(50)]
    seen = []
    for i, px in enumerate(opens):
        prices = {"AAA": px}
        orders = core.on_open(i, prices)
        seen.append([(o.side, o.quantity) for o in orders])
        _fill_all(core, i, orders, prices)
        core.on_close(i, prices)
    # S2: buy 10 (cash 50 left); S3: retry buys 1 @ 50; S4: new target sells 6.
    assert seen == [[], [("buy", 10)], [("buy", 1)], [("sell", 6)]]
    core.finish()
    assert not core.warnings


def test_pending_at_end_warning():
    core = _core({0: {"AAA": 20}}, "1000.00")
    for i in range(2):
        prices = {"AAA": D(100)}
        _fill_all(core, i, core.on_open(i, prices), prices)
        core.on_close(i, prices)
    core.finish()
    assert core.warnings == [host.PENDING_AT_END]


def test_buy_before_sell_engine_denial_is_loud(cash_cases):
    """An engine denial (e.g. after buy-before-sell) fails the run as process."""
    spec = _spec(cash_cases, "c2")
    result = fake_engine.replay(spec)
    denied = runs.EngineResult(result.name, result.version, result.fills, None, ["x"])
    with pytest.raises(ProtocolError) as info:
        runs.account(spec, denied)
    assert info.value.code is ErrorCode.PROCESS


def test_ledger_rejects_fills_that_differ_from_the_plan(cash_cases):
    """A missing staged fill (the S5 BBB buy) is a loud process error."""
    spec = _spec(cash_cases, "c2")
    result = fake_engine.replay(spec)
    short = runs.EngineResult("f", "0", result.fills[:-1], None)
    with pytest.raises(ProtocolError) as info:
        runs.account(spec, short)
    assert info.value.code is ErrorCode.PROCESS


def test_engine_commission_must_match_declared(cash_cases):
    spec = _spec(cash_cases, "c4")
    result = fake_engine.replay(spec)
    fill = result.fills[0]
    free = runs.Fill(fill.session, fill.quantity, fill.price, D(0), fill.symbol)
    with pytest.raises(ProtocolError) as info:
        runs.account(spec, runs.EngineResult("f", "0", [free], None))
    assert info.value.code is ErrorCode.PROCESS


def _with_bars(spec: runs.RunSpec) -> runs.RunSpec:
    """The same case with dataset-shaped bar rows (scaled ints, ns timestamps)."""
    # pylint: disable=import-outside-toplevel
    import dataclasses
    import datetime

    rows = []
    for i, day in enumerate(spec.sessions):
        d = datetime.date.fromisoformat(day)
        ts = (
            int(
                datetime.datetime(
                    d.year, d.month, d.day, 21, tzinfo=datetime.timezone.utc
                ).timestamp()
            )
            * 10**9
        )
        for sym in spec.symbols:
            o, c = spec.opens[sym][i], spec.closes[sym][i]
            scaled = {k: int(v.scaleb(3)) for k, v in (("open", o), ("close", c))}
            rows.append(
                {
                    "symbol": sym,
                    "session": d,
                    "ts_event": ts,
                    "ts_init": ts,
                    "high": max(scaled.values()),
                    "low": min(scaled.values()),
                    "volume": 1000,
                    **scaled,
                }
            )
    return dataclasses.replace(spec, bars=rows)


@pytest.mark.requires_nautilus
@pytest.mark.parametrize("name", CASES)
def test_real_engine_reproduces_cash_cases(cash_cases, name):
    """LIVE T03-L: the real BacktestEngine drives the host to the literals."""
    spec = _with_bars(_spec(cash_cases, name))
    result = runs.nautilus_engine(spec)
    books = runs.account(spec, result)
    exp = cash_cases["cases"][name]["expected"]
    assert (books["positions"], books["cash"], books["equity"]) == (
        exp["positions"],
        exp["cash"],
        exp["equity"],
    )
    assert result.name == "nautilus_trader.BacktestEngine"


@pytest.mark.requires_nautilus
def test_money_rounding_rule_matches_declared():
    """Seam contract (Rule 4): the engine's Money rounds as booking declares."""
    # pylint: disable=import-outside-toplevel,import-error
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.objects import Money

    for qty, px in ((1, "20.125"), (1, "1.005"), (9, "99.99")):
        engine = Money(float(qty) * float(px), USD).as_decimal()
        assert engine == booking.notional(qty, D(px))
