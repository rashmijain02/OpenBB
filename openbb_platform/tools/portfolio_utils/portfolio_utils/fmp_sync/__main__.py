"""``python -m portfolio_utils.fmp_sync`` -- admission preview and lock status (#1344-T01).

Commands:

- ``prices --dry-run|--execute --map <map.json> [--target-class production]`` --
  take the target lock, run the ordered admission, and (execute only) warm under
  the transport budget. Prints one counts-only JSON line; the exit code is the
  business code from ``outcome.EXIT_CODES`` (0 ok, 10 partial/deferred/busy,
  20 critical, 30 infra, 40 policy/config). ``--dry-run`` opens no socket;
  ``--execute`` is blocked (40) until the map carries explicit limits.
  ``--receipt`` (used by the cron wrapper) also appends the start/end receipts
  under the state root, prints the line only when the recorded state changed
  and exits 0 once the outcome is persisted. ``--run-id <32 hex>`` fixes the
  run id (the cron wrapper chooses it so it knows the cancel file
  ``<state root>/cancel/<run_id>``). Cancellation is cooperative: Ctrl+C /
  Ctrl+Break in a console, or that cancel file, end the run ``CANCELLED`` and
  the run file and receipts are still written. Under the cron wrapper the
  child has no console (CREATE_NO_WINDOW), so the wrapper turns its own
  Ctrl+C / Ctrl+Break and its deadline into the cancel file, waits a bounded
  grace period, and only then kills the job (see the wrapper docstring).
- ``lock --status --map <map.json>`` -- print whether the target lock is free or
  busy. Never takes ownership.
- ``audit --dry-run|--read-only --map <map.json> [--now <ISO aware>]`` (#1345) --
  readiness v2. ``--dry-run`` evaluates calendar/session checks with zero
  sockets and lists database checks ``NOT_EVALUATED``
  (``data_status=UNVALIDATED``). ``--read-only`` runs admission, then only the
  allowlisted SELECTs inside a read-only transaction; it never takes the target
  lock and writes a local ``runs/<run_id>.json`` (opt-in private counts stay
  there). Exit 0 for a recorded outcome, 30 database unavailable, 40 policy.

Output never carries symbols, paths, exception text or secrets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_utils.fmp_sync import readiness, state
from portfolio_utils.fmp_sync.admission import (
    EXIT_POLICY,
    DeploymentMap,
    Mode,
    load_map,
)
from portfolio_utils.fmp_sync.dispatcher import pending_signals, run_prices
from portfolio_utils.fmp_sync.locking import (
    LockRootRejected,
    default_state_root,
    lock_status,
    validate_state_root,
)


def _emit(payload: dict) -> None:
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))[:512]
    print(line)  # noqa: T201


def _emit_line(line: str) -> None:
    print(line[:512])  # noqa: T201


_RUN_ID = re.compile(r"^[0-9a-f]{32}$")


def _run_id(value: str) -> str:
    if not _RUN_ID.match(value):
        raise argparse.ArgumentTypeError("run id must be 32 lowercase hex characters")
    return value


def _aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--now must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--now must carry a UTC offset")
    return parsed


def _checks(value: str) -> tuple[str, ...]:
    groups = ("readiness", "integrity", "fundamentals")
    names = (
        groups
        if value.strip() == "all"
        else tuple(n for n in (p.strip() for p in value.split(",")) if n)
    )
    if not names or any(n not in groups for n in names):
        raise argparse.ArgumentTypeError(
            "--checks takes readiness, integrity, fundamentals or all"
        )
    return names


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
    prices.add_argument("--receipt", action="store_true")
    prices.add_argument("--run-id", type=_run_id, default=None)
    audit = sub.add_parser("audit", help="readiness audit (dry run or read-only)")
    amode = audit.add_mutually_exclusive_group(required=True)
    amode.add_argument("--dry-run", action="store_true")
    amode.add_argument("--read-only", action="store_true")
    audit.add_argument("--map", required=True, type=Path)
    audit.add_argument("--now", type=_aware, default=None)
    audit.add_argument(
        "--target-class", choices=("disposable", "production"), default="disposable"
    )
    audit.add_argument("--run-id", type=_run_id, default=None)
    audit.add_argument(
        "--checks",
        type=_checks,
        default=("readiness",),
        help="comma list of readiness,integrity,fundamentals, or all",
    )
    lock = sub.add_parser("lock", help="target lock status")
    lock.add_argument("--status", action="store_true", required=True)
    lock.add_argument("--map", required=True, type=Path)
    return parser


def _blocked_root(op: str = "prices") -> int:
    _emit(
        {
            "op": op,
            "outcome": "BLOCKED_CONFIG",
            "findings": ["LOCK_ROOT_REJECTED"],
        }
    )
    return EXIT_POLICY


def _prices(
    dmap: DeploymentMap, args: argparse.Namespace, run: Callable[..., Any]
) -> int:
    mode: Mode = "execute" if args.execute else "dry_run"
    kwargs = {"mode": mode, "requested_class": args.target_class}
    if not args.receipt:
        result = run(dmap, install_signals=True, run_id=args.run_id, **kwargs)
        _emit_line(result.to_line())
        return result.exit_code
    try:
        root = validate_state_root(
            Path(dmap.state_root) if dmap.state_root else default_state_root()
        )
    except LockRootRejected:
        return _blocked_root()
    run_id = args.run_id or uuid.uuid4().hex
    state.record_start(root, run_id, mode)
    result = run(dmap, install_signals=True, run_id=run_id, **kwargs)
    receipt = state.record_end(root, result)
    if receipt.emit:
        _emit_line(receipt.outcome.to_line())
    return 0 if receipt.persisted else receipt.outcome.exit_code


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., Any] | None = None,
    audit_kwargs: Mapping[str, Any] | None = None,
) -> int:
    """Entry point; returns the process exit code."""
    args = _parser().parse_args(argv)
    if args.command == "prices":
        with pending_signals():
            return _main(args, runner)
    return _main(args, runner, audit_kwargs)


def _audit(
    dmap: DeploymentMap, args: argparse.Namespace, extra: Mapping[str, Any] | None
) -> int:
    try:
        result = readiness.run_audit(
            dmap,
            mode="read_only" if args.read_only else "dry_run",
            now=args.now or readiness.utc_now(),
            requested_class=args.target_class,
            run_id=args.run_id,
            checks=args.checks,
            **(extra or {}),
        )
    except LockRootRejected:
        return _blocked_root("audit")
    _emit_line(result.to_line())
    return result.exit_code


def _main(
    args: argparse.Namespace,
    runner: Callable[..., Any] | None,
    audit_kwargs: Mapping[str, Any] | None = None,
) -> int:
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

    if args.command == "audit":
        return _audit(dmap, args, audit_kwargs)
    return _prices(dmap, args, runner or run_prices)


if __name__ == "__main__":
    sys.exit(main())
