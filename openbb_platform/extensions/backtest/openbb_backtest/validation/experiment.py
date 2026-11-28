"""Experiment command line for the validation framework (#1357).

Subcommands:

- ``qualify-stats``: evaluate the DSR / PSR / E[max] / MinBTL / PBO / CPCV
  bridges against the independent reference file and print, per case,
  ``expected``, ``got``, ``tolerance`` and ``source``. Exit 0 when every case
  passes, 2 otherwise (including an unreadable or malformed reference file).

Run as ``python -m openbb_backtest.validation.experiment qualify-stats``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openbb_backtest.validation import qualify


def _qualify_stats(args: argparse.Namespace) -> int:
    try:
        results = qualify.qualify(args.references)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(
            json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"})
            + "\n"
        )
        return 2
    passed = all(r.passed for r in results)
    if args.format == "json":
        out = json.dumps(
            {"passed": passed, "cases": [r.as_dict() for r in results]},
            indent=2,
            default=str,
        )
    else:
        out = "\n".join(
            f"{'PASS' if r.passed else 'FAIL'} {r.case_id}: expected={r.expected} "
            f"got={r.got} tolerance={r.tolerance} source={r.source}"
            for r in results
        )
    sys.stdout.write(out + "\n")
    return 0 if passed else 2


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    ap = argparse.ArgumentParser(prog="experiment", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    qs = sub.add_parser("qualify-stats", help="check statistics against references")
    qs.add_argument("--references", type=Path, default=qualify.DEFAULT_REFERENCES)
    qs.add_argument("--format", choices=["json", "text"], default="text")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    return _qualify_stats(args)


if __name__ == "__main__":
    sys.exit(main())
