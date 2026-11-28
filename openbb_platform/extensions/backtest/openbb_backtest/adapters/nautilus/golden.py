r"""Golden cash cases through the real facade path (#1356 T02/T03).

Usage::

    python -m openbb_backtest.adapters.nautilus.golden --case all \
        --runtime fake|native [--case-file FILE] [--settlement T+0] \
        [--worker-command-json JSON] [--format json|text]

The default case file is ``tests/unit/nautilus/fixtures/cash_cases.json``:
hand-computed literals (plan section 2.6) that no code writes. Each run case's
bars are exported to a neutral dataset in a temporary data root outside the
repository, then run through ``run_router.execute_run`` with
``backend="nautilus"`` on the chosen worker, and the projected result
(positions, cash, equity, trades, booking residual, warnings) is compared with
the literals exactly. Planner-only cases (C6) run the pure staging planner.

``--runtime fake`` runs the real worker entrypoint with the event-replay fake
engine (no settlement logic), unqualified (recorded in the output).
``--runtime native`` runs the configured native worker
(``OPENBB_NAUTILUS_VENV``) qualified against the pin: LIVE T03-L only.
``--settlement`` overrides every case's settlement (an unsupported value must
fail closed). A legacy single-case file (``expected.{quantity,cash,equity}``,
#1355 oracle) is still accepted. Exit 0 = every literal matched, 2 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.reviewed import staging

from openbb_backtest.errors import BacktestError
from openbb_backtest.models import BacktestConfig

from . import (
    backend,
    export as ex,
)
from .client import WorkerClient, worker_command, worker_env

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "unit" / "nautilus"
DEFAULT_CASE_FILE = _FIXTURES / "fixtures" / "cash_cases.json"
FAKE_WORKER = _FIXTURES / "fixtures" / "fake_run_worker.py"


def _normalise(case: dict[str, Any], sessions: list[str] | None) -> dict[str, Any]:
    """Accept the #1355 oracle shape (one symbol, closes only, same_close)."""
    if "bars" in case:
        return case
    exp = case["expected"]
    return {
        "strategy": "buy_and_hold",
        "params": {"symbols": [case["symbol"]]},
        "execution": {"fill_timing": "same_close"},
        "initial_cash": case["initial_cash"],
        "sessions": case["sessions"] if sessions is None else sessions,
        "bars": {case["symbol"]: [[c, c] for c in case["closes"]]},
        "expected": {
            "positions": {case["symbol"]: exp["quantity"]},
            "cash": exp["cash"],
            "equity": exp["equity"],
        },
    }


def _snapshot(case: dict[str, Any], sessions: list[str], snap: Path) -> None:
    rows = [
        {
            "symbol": sym,
            "date": day,
            "open": o,
            "high": max(o, c, key=Decimal),
            "low": min(o, c, key=Decimal),
            "close": c,
            "volume": 1000,
            "interval_type": "1d",
            "adjustment_type": "unadjusted",
            "is_filled": 0,
            "is_valid": 1,
        }
        for sym, bars in sorted(case["bars"].items())
        for day, (o, c) in zip(sessions, bars)
    ]
    snap.mkdir()
    (snap / "equity_historical.json").write_text(json.dumps(rows), "utf-8")
    (snap / "calendar_splits.json").write_text("[]", "utf-8")
    (snap / "calendar_dividend.json").write_text("[]", "utf-8")


def _client(runtime: str, command: list[str] | None, root: Path):
    env = worker_env({**os.environ, DATA_ROOT_ENV: str(root)})
    if command is None:
        command = (
            [sys.executable, str(FAKE_WORKER)]
            if runtime == "fake"
            else worker_command(runtime, os.environ)
        )
    return lambda: WorkerClient(command, timeout=120, env=env)


def _got(result: Any, sessions: list[str]) -> dict[str, Any]:
    index = {s: i for i, s in enumerate(sessions)}
    positions: dict[str, int] = {}
    trades = []
    for t in result.trades:
        sign = 1 if t.side == "buy" else -1
        positions[t.symbol] = positions.get(t.symbol, 0) + sign * int(t.quantity)
        day = t.timestamp.date().isoformat()
        trades.append(
            [index[day], t.symbol, t.side, int(t.quantity), t.price, t.commission]
        )
    prov = result.provenance
    return {
        "positions": positions,
        "cash": str(result.equity_curve[-1].cash),
        "equity": [str(p.equity) for p in result.equity_curve],
        "trades": trades,
        "booking_residual": Decimal(prov.booking_residual or "0"),
        "warnings": list(prov.warnings),
    }


def _want(exp: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    want = {k: exp[k] for k in keys}
    if "trades" in want:
        want["trades"] = [
            [i, s, side, q, Decimal(p), Decimal(c)]
            for i, s, side, q, p, c in want["trades"]
        ]
    if "booking_residual" in want:
        want["booking_residual"] = Decimal(want["booking_residual"])
    return want


def run_case(  # pylint: disable=too-many-locals
    case: dict[str, Any],
    command: list[str] | None,
    runtime: str,
    *,
    sessions: list[str] | None = None,
    settlement: str | None = None,
) -> dict[str, Any]:
    """Run one case end to end; return its comparison row."""
    from openbb_backtest.routers.run_router import (  # pylint: disable=import-outside-toplevel
        execute_run,
    )

    case = _normalise(case, sessions)
    symbols = sorted(case["bars"])
    days = list(case.get("sessions") or sessions or [])[: len(case["bars"][symbols[0]])]
    execution = dict(case["execution"])
    if settlement is not None:
        execution["settlement"] = settlement
    with tempfile.TemporaryDirectory(prefix="hfp-golden-") as tmp:
        root, snap = Path(tmp, "data"), Path(tmp, "snap")
        _snapshot(case, days, snap)
        options = backend.NautilusOptions(
            client_factory=_client(runtime, command, root),
            execute=ex.snapshot_executor(snap),
            data_root=root,
            qualify=runtime != "fake",
            runtime=runtime,
        )
        config = BacktestConfig(
            strategy=case["strategy"],
            universe=symbols,
            start=days[0],
            end=days[-1],
            initial_cash=Decimal(case["initial_cash"]),
            benchmark=None,
        )
        result = execute_run(
            config,
            backend="nautilus",
            strategy_params={**case["params"], "execution": execution},
            nautilus=options,
        )
    prov = result.provenance
    if prov is None:
        raise BacktestError("the nautilus result carries no provenance")
    exp = case["expected"]
    got = _got(result, days)
    want = _want(exp, [k for k in got if k in exp])
    got = {k: got[k] for k in want}
    return {
        "passed": got == want,
        "got": got,
        "expected": want,
        "engine": f"{prov.engine_name}@{prov.engine_version}",
        "qualified": prov.qualified,
        "spec_sha256": prov.spec_sha256,
        "code_sha256": prov.code_sha256,
        "execution_sha256": prov.execution_sha256,
        "binding_sha256": prov.binding_sha256,
    }


def run_planner_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run a planner-only case (C6) through the pure staging planner."""
    ledger = staging.Ledger(
        settled=Decimal(case["settled"]), lag=1, held=dict(case["held"])
    )
    orders = staging.plan_orders(
        ledger,
        case["targets"],
        {s: Decimal(p) for s, p in case["prices"].items()},
        Decimal(0),
    )
    got = [[o.symbol, o.side, o.quantity] for o in orders]
    want = case["expected_orders"]
    return {"passed": got == want, "got": got, "expected": want, "engine": "planner"}


def _select(data: dict[str, Any], name: str, stem: str) -> list[tuple[str, Any]]:
    if "cases" not in data:
        return [(stem, ("run", data))]
    every = [(k, ("run", v)) for k, v in data["cases"].items()]
    every += [(k, ("planner", v)) for k, v in data.get("planner_cases", {}).items()]
    if name == "all":
        return every
    chosen = [item for item in every if item[0] == name]
    if not chosen:
        raise SystemExit(f"unknown case {name!r}")
    return chosen


def _one(kind_case, args, sessions) -> dict[str, Any]:
    kind, case = kind_case
    try:
        if kind == "planner":
            return run_planner_case(case)
        return run_case(
            case,
            args.command,
            args.runtime,
            sessions=sessions,
            settlement=args.settlement,
        )
    except BacktestError as exc:
        return {
            "passed": False,
            "error": type(exc).__name__,
            "reason": getattr(exc, "reason", None),
            "message": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; 0 when every literal matched, 2 otherwise."""
    ap = argparse.ArgumentParser(prog="golden", description=__doc__)
    ap.add_argument("--case", default="all")
    ap.add_argument("--case-file", type=Path, default=DEFAULT_CASE_FILE)
    ap.add_argument("--runtime", choices=["fake", "native"], required=True)
    ap.add_argument("--worker-command-json", default=None)
    ap.add_argument("--settlement", default=None)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    try:
        args = ap.parse_args(argv)
        data = json.loads(args.case_file.read_text("utf-8"))
        chosen = _select(data, args.case, args.case_file.stem)
    except SystemExit:
        return 2
    args.command = (
        json.loads(args.worker_command_json) if args.worker_command_json else None
    )
    rows = {name: _one(kc, args, data.get("sessions")) for name, kc in chosen}
    passed = bool(rows) and all(r["passed"] for r in rows.values())
    rep = {"runtime": args.runtime, "passed": passed, "cases": rows}
    if args.format == "json":
        out = json.dumps(rep, indent=2, default=str)
    else:
        out = "\n".join(
            f"golden {name} runtime={args.runtime}: "
            + ("PASS" if r["passed"] else f"FAIL {r.get('reason') or ''}".rstrip())
            for name, r in rows.items()
        )
    sys.stdout.write(out + "\n")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
