r"""probe: admission matrix and buy-and-hold run against the worker (#1355 T03).

Usage::

    python -m openbb_backtest.adapters.nautilus.probe --runtime native \\
        --admission-matrix [--dataset ID] --format json
    python -m openbb_backtest.adapters.nautilus.probe --runtime native \\
        --run buy_and_hold --dataset ID [--cash 10000.00] --format json

The matrix sends every negative case *raw* to the worker (bypassing the
client's fail-fast screen) so the worker's authoritative admission is what is
measured. Exit 0 when every case is blocked with its expected layer (and the
valid control, if a dataset is given, is admitted); 2 otherwise. Output holds
layers and hashes, never paths or environment values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from openbb_nautilus_worker.protocol import ProtocolError

from .client import WorkerClient, worker_command

PLACEHOLDER_ID = "0" * 64
_SENTINEL = "probe-sentinel-not-a-secret"


def matrix_cases(dataset_id: str | None) -> list[tuple[str, dict[str, Any], str]]:
    """``(case, body, expected_layer)``; ``ok`` means admitted (control)."""
    ds_id = dataset_id or PLACEHOLDER_ID
    base = {"dataset_id": ds_id, "strategy": "buy_and_hold"}
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("absolute_path", {**base, "dataset_id": "C:\\data\\" + ds_id[:56]}, "schema"),
        ("posix_path", {**base, "dataset_id": "/etc/" + ds_id[:59]}, "schema"),
        ("unc_path", {**base, "dataset_id": "\\\\srv\\share\\" + ds_id[:52]}, "schema"),
        ("dotdot_path", {**base, "dataset_id": "../" + ds_id[:61]}, "schema"),
        ("unknown_dataset", {**base, "dataset_id": "f" * 64}, "schema"),
        ("unknown_field", {**base, "colour": "blue"}, "schema"),
        ("venue_ib", {**base, "venue": "IB"}, "egress"),
        ("endpoint_field", {**base, "base_url": "https://example.invalid"}, "egress"),
        ("host_port_value", {**base, "strategy": "127.0.0.1:7497"}, "egress"),
        ("credential_field", {**base, "api_key": _SENTINEL}, "egress"),
        ("account_field", {**base, "account_id": _SENTINEL}, "egress"),
        ("live_config", {**base, "trading_node": {"exec_clients": {}}}, "egress"),
        ("precision_high", {**base, "precision_mode": "high"}, "abi"),
    ]
    if dataset_id:
        cases.append(("control_valid", {**base, "deadline_seconds": 60}, "ok"))
    return cases


def admission_matrix(client: WorkerClient, dataset_id: str | None) -> dict[str, Any]:
    """Run every case through one worker session; report layer per case."""
    rows = []
    for case, body, expected in matrix_cases(dataset_id):
        try:
            client.call("run", body, timeout=120)
            actual = "ok"
        except ProtocolError as exc:
            actual = exc.code.value
        rows.append(
            {
                "case": case,
                "expected": expected,
                "actual": actual,
                "ok": actual == expected,
            }
        )
    return {"passed": all(r["ok"] for r in rows), "cases": rows}


def _text(rep: dict[str, Any]) -> str:
    lines = [f"{rep['runtime']}: {'PASS' if rep['passed'] else 'FAIL'}"]
    if rep.get("failed_layer"):
        lines[0] += f" (failed_layer={rep['failed_layer']})"
    for row in rep.get("cases", []):
        mark = "ok " if row["ok"] else "BAD"
        lines.append(
            f"  {mark} {row['case']}: expected {row['expected']}, got {row['actual']}"
        )
    if "report" in rep:
        run = rep["report"]
        lines.append(
            f"  {run['strategy']} {run['symbol']} qty={run['quantity']} "
            f"cash={run['cash']} final_equity={run['final_equity']} "
            f"engine={run['engine']['name']} {run['engine']['version']} "
            f"precision={run['fixed_precision']} dataset={run['dataset_id']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Exit 0 on pass, 2 on any failure."""
    ap = argparse.ArgumentParser(prog="probe", description=__doc__)
    ap.add_argument("--runtime", choices=["native", "docker"], required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--admission-matrix", action="store_true")
    mode.add_argument("--run", choices=["buy_and_hold"])
    ap.add_argument("--dataset", help="64-hex dataset id under the data root")
    ap.add_argument("--cash", default="10000.00")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--memory-mb", type=int, default=4096)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument(
        "--worker-command-json",
        help="JSON list overriding the spawn command (tests / fake worker)",
    )
    args = ap.parse_args(argv)
    if args.run and not args.dataset:
        ap.error("--run needs --dataset")
    rep: dict[str, Any] = {"runtime": args.runtime}
    try:
        command = (
            json.loads(args.worker_command_json)
            if args.worker_command_json
            else worker_command(args.runtime, os.environ, memory_mb=args.memory_mb)
        )
        memory = args.memory_mb * 1024 * 1024 if args.runtime == "native" else None
        with WorkerClient(command, timeout=args.timeout, memory_bytes=memory) as wc:
            if args.admission_matrix:
                rep.update(admission_matrix(wc, args.dataset))
            else:
                body = {
                    "dataset_id": args.dataset,
                    "strategy": args.run,
                    "starting_cash": args.cash,
                }
                rep.update(passed=True, report=wc.run(body))
    except ProtocolError as exc:
        rep.update(passed=False, failed_layer=exc.code.value, message=exc.message)
    sys.stdout.write(
        (json.dumps(rep, indent=2) if args.format == "json" else _text(rep)) + "\n"
    )
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
