"""``python -m portfolio_utils.fmp_sync`` -- admission preview and lock status (#1344-T01).

Commands:

- ``prices --dry-run|--execute --map <map.json> [--target-class production]`` --
  take the target lock, run the ordered admission, and (execute only) warm under
  the transport budget. Prints one counts-only JSON line; the exit code is the
  business code from ``outcome.EXIT_CODES`` (0 ok, 10 partial/deferred/busy,
  20 critical, 30 infra, 40 policy/config). ``--dry-run`` opens no socket;
  ``--execute`` is blocked (40) until the map carries explicit limits.
- ``lock --status --map <map.json>`` -- print whether the target lock is free or
  busy. Never takes ownership.

Output never carries symbols, paths, exception text or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from portfolio_utils.fmp_sync.admission import EXIT_POLICY, Mode, load_map
from portfolio_utils.fmp_sync.dispatcher import run_prices
from portfolio_utils.fmp_sync.locking import LockRootRejected, lock_status


def _emit(payload: dict) -> None:
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))[:512]
    print(line)  # noqa: T201


def _emit_line(line: str) -> None:
    print(line[:512])  # noqa: T201


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


def main(
    argv: list[str] | None = None, *, runner: Callable[..., Any] | None = None
) -> int:
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

    run = runner or run_prices
    mode: Mode = "execute" if args.execute else "dry_run"
    result = run(dmap, mode=mode, requested_class=args.target_class)
    _emit_line(result.to_line())
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
