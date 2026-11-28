r"""Golden cases through the real facade path (#1356 T02; cash cases in T03).

Usage::

    python -m openbb_backtest.adapters.nautilus.golden --case-file FILE \
        --runtime fake --worker-command-json JSON [--format json|text]

A case file holds hand-computed literals (``symbol``, ``sessions``, ``closes``,
``initial_cash``, ``expected.{quantity,cash,equity}``), e.g. the #1355
``buy_and_hold_oracle.json``. The rows are exported to a neutral dataset in a
temporary data root outside the repository, then run through
``run_router.execute_run`` with ``backend="nautilus"`` (``same_close``, zero
fees) on the given worker, and the projected result is compared with the
literals exactly. ``--runtime fake`` (a worker with a fake engine seam) is not
qualified against the pin; that is recorded in the output. Exit 0 = every
literal matched, 2 = mismatch or failure.
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

from openbb_backtest.errors import BacktestError
from openbb_backtest.models import BacktestConfig

from . import (
    backend,
    export as ex,
)
from .client import WorkerClient, worker_env


def _snapshot(case: dict[str, Any], snap: Path) -> None:
    rows = [
        {
            "symbol": case["symbol"],
            "date": d,
            **{k: c for k in ("open", "high", "low", "close")},
            "volume": 1000,
            "interval_type": "1d",
            "adjustment_type": "unadjusted",
            "is_filled": 0,
            "is_valid": 1,
        }
        for d, c in zip(case["sessions"], case["closes"])
    ]
    snap.mkdir()
    (snap / "equity_historical.json").write_text(json.dumps(rows), "utf-8")
    (snap / "calendar_splits.json").write_text("[]", "utf-8")
    (snap / "calendar_dividend.json").write_text("[]", "utf-8")


def run_case(case: dict[str, Any], command: list[str], runtime: str) -> dict[str, Any]:
    """Run one case end to end; return its comparison row."""
    from openbb_backtest.routers.run_router import (  # pylint: disable=import-outside-toplevel
        execute_run,
    )

    with tempfile.TemporaryDirectory(prefix="hfp-golden-") as tmp:
        root, snap = Path(tmp, "data"), Path(tmp, "snap")
        _snapshot(case, snap)
        env = worker_env({**os.environ, DATA_ROOT_ENV: str(root)})
        options = backend.NautilusOptions(
            client_factory=lambda: WorkerClient(command, timeout=120, env=env),
            execute=ex.snapshot_executor(snap),
            data_root=root,
            qualify=False,
            runtime=runtime,
        )
        config = BacktestConfig(
            strategy="buy_and_hold",
            universe=[case["symbol"]],
            start=case["sessions"][0],
            end=case["sessions"][-1],
            initial_cash=Decimal(case["initial_cash"]),
            benchmark=None,
        )
        result = execute_run(
            config,
            backend="nautilus",
            strategy_params={"execution": {"fill_timing": "same_close"}},
            nautilus=options,
        )
    exp = case["expected"]
    got = {
        "quantity": int(sum(t.quantity for t in result.trades)),
        "cash": str(result.equity_curve[-1].cash),
        "equity": [str(p.equity) for p in result.equity_curve],
    }
    want = {"quantity": exp["quantity"], "cash": exp["cash"], "equity": exp["equity"]}
    prov = result.provenance
    if prov is None:
        raise BacktestError("the nautilus result carries no provenance")
    return {
        "passed": got == want,
        "got": got,
        "expected": want,
        "engine": f"{prov.engine_name}@{prov.engine_version}",
        "qualified": prov.qualified,
        "spec_sha256": prov.spec_sha256,
        "binding_sha256": prov.binding_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; 0 when every literal matched, 2 otherwise."""
    ap = argparse.ArgumentParser(prog="golden", description=__doc__)
    ap.add_argument("--case-file", type=Path, required=True)
    ap.add_argument("--runtime", choices=["fake"], required=True)
    ap.add_argument("--worker-command-json", required=True)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    case = json.loads(args.case_file.read_text("utf-8"))
    rep: dict[str, Any] = {"runtime": args.runtime, "case": args.case_file.stem}
    try:
        rep.update(run_case(case, json.loads(args.worker_command_json), args.runtime))
    except BacktestError as exc:
        rep.update(passed=False, error=type(exc).__name__, message=str(exc))
    if args.format == "json":
        out = json.dumps(rep, indent=2)
    else:
        out = f"golden {rep['case']} runtime={rep['runtime']}: " + (
            "PASS" if rep["passed"] else "FAIL"
        )
    sys.stdout.write(out + "\n")
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
