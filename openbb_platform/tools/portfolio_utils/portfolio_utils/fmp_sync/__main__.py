"""``python -m portfolio_utils.fmp_sync`` -- admission preview and lock status (#1344-T01).

Commands:

- ``prices --dry-run --map <map.json> [--target-class production]`` -- run the
  ordered target/universe admission and print one counts-only JSON line. Exit 0
  when admitted (preview only: no database or FMP access), 40 when blocked.
  ``--execute`` is refused (exit 40) until the budgeted dispatcher lands (T02).
- ``lock --status --map <map.json>`` -- print whether the target lock is free or
  busy. Never takes ownership.

Output never carries symbols, paths, exception text or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from portfolio_utils.fmp_sync.admission import EXIT_POLICY, admit, load_map
from portfolio_utils.fmp_sync.locking import LockRootRejected, lock_status


def _emit(payload: dict) -> None:
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))[:512]
    print(line)  # noqa: T201


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m portfolio_utils.fmp_sync")
    sub = parser.add_subparsers(dest="command", required=True)
    prices = sub.add_parser("prices", help="admission preview for the price warm")
    mode = prices.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    prices.add_argument("--map", required=True, type=Path)
    prices.add_argument(
        "--target-class", choices=("disposable", "production"), default="disposable"
    )
    lock = sub.add_parser("lock", help="target lock status")
    lock.add_argument("--status", action="store_true", required=True)
    lock.add_argument("--map", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    args = _parser().parse_args(argv)
    try:
        dmap = load_map(args.map)
    except ValueError:
        _emit(
            {
                "op": args.command,
                "outcome": "BLOCKED_CONFIG",
                "findings": ["MAP_INVALID"],
            }
        )
        return EXIT_POLICY

    if args.command == "lock":
        try:
            root = Path(dmap.state_root) if dmap.state_root else None
            status = lock_status(dmap.target, root=root)
        except (LockRootRejected, ValueError):
            _emit(
                {
                    "op": "lock",
                    "outcome": "BLOCKED_CONFIG",
                    "findings": ["LOCK_ROOT_REJECTED"],
                }
            )
            return EXIT_POLICY
        _emit({"op": "lock", "lock": status})
        return 0

    if args.execute:
        _emit(
            {
                "op": "prices",
                "mode": "execute",
                "outcome": "BLOCKED_POLICY",
                "findings": ["EXECUTE_NOT_AVAILABLE"],
            }
        )
        return EXIT_POLICY

    result = admit(dmap, mode="dry_run", requested_class=args.target_class)
    _emit(
        {
            "op": "prices",
            "mode": "dry_run",
            "outcome": "PREVIEW" if result.admitted else result.code,
            "failed_layer": result.failed_layer,
            "findings": list(result.findings),
            "target_class": result.target_class,
            "db_category": result.db_category,
            "manifest_id": result.manifest_id,
            "counts": dict(result.counts),
        }
    )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
