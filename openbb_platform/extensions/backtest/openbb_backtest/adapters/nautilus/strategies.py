r"""Reviewed strategy loader and CLI for the Nautilus backend (#1356 T01).

Usage::

    python -m openbb_backtest.adapters.nautilus.strategies verify [--root DIR] \
        [--format json|text]
    python -m openbb_backtest.adapters.nautilus.strategies list [--format json|text]

``verify`` recomputes every pinned hash from the local copy of the worker
package (or ``--root``, a copy of that package) and exits 0 only when every
reviewed strategy matches; 2 otherwise, naming the reason
(``strategy_code_drift`` is ``module_origin``). ``list`` prints the pins.
The facade never imports ``openbb_agents``; it never consults entry points.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from openbb_nautilus_worker import admission
from openbb_nautilus_worker.reviewed import registry
from openbb_nautilus_worker.reviewed.errors import ReviewedError

DEFAULT_STARTING_CASH = "10000.00"


def resolve_reviewed(
    strategy_id: Any,
    version: Any,
    params: Any,
    execution: Any = None,
    *,
    root: Path | None = None,
) -> registry.Binding:
    """Resolve a reviewed strategy against the local copy, or raise."""
    return registry.resolve(strategy_id, version, params, execution, root=root)


def build_run_body(
    binding: registry.Binding,
    dataset_id: str,
    *,
    starting_cash: str = DEFAULT_STARTING_CASH,
    deadline_seconds: int | None = None,
) -> dict[str, Any]:
    """Build and fail-fast screen a ``run`` request v2 body."""
    body: dict[str, Any] = {
        "dataset_id": dataset_id,
        **binding.request_fields(),
        "starting_cash": starting_cash,
    }
    if deadline_seconds is not None:
        body["deadline_seconds"] = deadline_seconds
    admission.screen_request(body)
    return body


def _row(pin: registry.Pin, **extra: Any) -> dict[str, Any]:
    return {
        "id": pin.strategy_id,
        "version": pin.version,
        "code_sha256": pin.code_sha256,
        "param_schema_sha256": pin.param_schema_sha256,
        "spec_sha256": pin.spec_sha256,
        **extra,
    }


def verify_all(root: Path | None = None) -> dict[str, Any]:
    """Verify every ledger entry; one row each, never stopping at the first."""
    rows = []
    for pin in registry.REVIEW_LEDGER:
        try:
            got = registry.verify(pin.strategy_id, pin.version, root=root)
            rows.append(_row(pin, status="ok", code_sha256=got.code_sha256))
        except ReviewedError as exc:
            rows.append(
                _row(
                    pin,
                    status="rejected",
                    reason=exc.reason,
                    layer=exc.code.value,
                )
            )
    return {"passed": all(r["status"] == "ok" for r in rows), "strategies": rows}


def list_pins() -> dict[str, Any]:
    """Return the reviewed pins as pinned (nothing is recomputed)."""
    return {"strategies": [_row(pin) for pin in registry.REVIEW_LEDGER]}


def _text(report: dict[str, Any]) -> str:
    lines = []
    if "passed" in report:
        lines.append("verify: " + ("PASS" if report["passed"] else "FAIL"))
    for row in report["strategies"]:
        line = f"{row['id']}@{row['version']} code={row['code_sha256'][:12]}"
        line += f" spec={row['spec_sha256'][:12]}"
        if row.get("status"):
            line += f" {row['status']}"
        if row.get("reason"):
            line += f" {row['reason']} (layer={row['layer']})"
        lines.append(line)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns the exit code (0 ok, 2 rejected or bad usage)."""
    parser = argparse.ArgumentParser(prog="strategies")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "list"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--format", choices=("json", "text"), default="text")
        if name == "verify":
            cmd.add_argument("--root", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    report = verify_all(args.root) if args.command == "verify" else list_pins()
    out = json.dumps(report, indent=2) if args.format == "json" else _text(report)
    sys.stdout.write(out + "\n")
    return 0 if report.get("passed", True) else 2


if __name__ == "__main__":
    sys.exit(main())
