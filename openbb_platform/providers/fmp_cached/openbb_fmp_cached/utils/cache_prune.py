"""Manual prune command for the fmp_cached provider cache (#1292).

Usage::

    python -m openbb_fmp_cached.utils.cache_prune            # dry run
    python -m openbb_fmp_cached.utils.cache_prune --apply    # delete
    python -m openbb_fmp_cached.utils.cache_prune --apply --table balance_sheet

Dry run is the default. Only tables in ``EXPIRABLE_CACHE_TABLES`` with an
expiry rule are touched; see ``cache_schema.prune_expired_cache``. Output is a
JSON report of counts only, never row contents, and names the target as
``user@host:port/database`` (never the password). INFO progress lines go to
stderr.

Exit codes: 0 success, 1 one or more tables failed, 2 a refused table, a bad
argument, missing database configuration or an unreachable database. Exit 2
prints one ``error:`` line and nothing was deleted.
"""

import argparse
import json
import logging
import sys

from openbb_fmp_cached.utils import cache_schema, database


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


def _describe_target() -> str:
    """Return ``user@host:port/database`` for the active connection settings."""
    params = database.get_connection_pool().connection_params
    return (
        f"{params.get('user')}@{params.get('host')}:{params.get('port')}"
        f"/{params.get('database')}"
    )


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the prune command and print its JSON report."""
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        target = _describe_target()
    except ValueError as exc:  # missing or invalid configuration
        return _fail(" ".join(str(exc).split()))
    try:
        report = cache_schema.prune_expired_cache(
            dry_run=not args.apply,
            batch_size=args.batch_size,
            tables=args.tables,
        )
    except ValueError as exc:  # refused table or bad batch size
        return _fail(" ".join(str(exc).split()))
    except Exception as exc:  # noqa: BLE001 - DB unreachable; never echo its text
        detail = cache_schema.describe_db_error(exc)
        return _fail(f"cannot use database {target}: {detail}; nothing was deleted")
    report["target"] = target
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
