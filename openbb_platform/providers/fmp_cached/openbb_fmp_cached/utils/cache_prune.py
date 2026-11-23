"""Manual prune command for the fmp_cached provider cache (#1292).

Usage::

    python -m openbb_fmp_cached.utils.cache_prune            # dry run
    python -m openbb_fmp_cached.utils.cache_prune --apply    # delete
    python -m openbb_fmp_cached.utils.cache_prune --apply --table balance_sheet

Dry run is the default. Only tables in ``EXPIRABLE_CACHE_TABLES`` with an
expiry rule are touched; see ``cache_schema.prune_expired_cache``. Output is a
JSON report of counts only, never row contents.

Exit codes: 0 success, 1 one or more tables failed, 2 a refused table, a bad
argument or missing database configuration (nothing was deleted).
"""

import argparse
import json
import sys

from openbb_fmp_cached.utils import cache_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m openbb_fmp_cached.utils.cache_prune",
        description="Delete expired rows from the fmp_cached provider cache.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete expired rows. Without it, only count them (dry run).",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        metavar="NAME",
        help="Limit to this expiring table; repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Rows per DELETE batch (1 to 10000, default 1000).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the prune command and print its JSON report."""
    args = _parser().parse_args(argv)
    try:
        report = cache_schema.prune_expired_cache(
            dry_run=not args.apply,
            batch_size=args.batch_size,
            tables=args.tables,
        )
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
