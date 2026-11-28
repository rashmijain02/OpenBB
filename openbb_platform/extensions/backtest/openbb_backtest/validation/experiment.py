"""Experiment command line for the validation framework (#1357).

Subcommands:

- ``qualify-stats``: evaluate the DSR / PSR / E[max] / MinBTL / PBO / CPCV
  bridges against the independent reference file and print, per case,
  ``expected``, ``got``, ``tolerance`` and ``source``. Exit 0 when every case
  passes, 2 otherwise (including an unreadable or malformed reference file).
- ``run``: plan, dispatch and assemble one nautilus ``validate`` experiment
  from a spec file and print ``experiment_id``, ``N``, completeness, PBO / DSR
  and ``matrix_sha256``. Re-running the same spec resumes from the ledger
  (zero new attempts once every cell is terminal). ``--runtime fake`` runs the
  real worker entrypoint with the event-replay fake engine on the spec's
  synthetic ``bars``; ``native`` / ``docker`` use the configured worker and
  the fmp_cached export. Exit 0 on an assembled experiment, 2 on an error.
- ``bench``: bounded benchmark of realistic validation experiments (see
  :mod:`openbb_backtest.validation.bench`); prints counts, codes and timings
  only. ``--inject-kill K`` / ``--inject-fail-once`` / ``--inject-reject`` /
  ``--inject-changed-data`` add deterministic failure injection.

Run as ``python -m openbb_backtest.validation.experiment <subcommand>``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

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


def _options(spec: dict[str, Any], runtime: str, tmp: Path, runs_root: Path) -> Any:
    # pylint: disable=import-outside-toplevel  # lazy: keeps Nautilus optional
    from openbb_backtest.adapters.nautilus import (
        backend,
        export as ex,
        golden,
    )

    if runtime != "fake":
        return backend.NautilusOptions(runtime=runtime, runs_root=runs_root)
    root, snap = tmp / "data", tmp / "snap"
    golden._snapshot(  # pylint: disable=protected-access
        {"bars": spec["bars"]}, list(spec["sessions"]), snap
    )
    return backend.NautilusOptions(
        client_factory=golden._client(  # pylint: disable=protected-access
            "fake", None, root
        ),
        execute=ex.snapshot_executor(snap),
        data_root=root,
        qualify=False,
        runtime="fake",
        runs_root=runs_root,
    )


def _run(args: argparse.Namespace) -> int:
    # pylint: disable=import-outside-toplevel  # lazy: keeps Nautilus optional
    from openbb_backtest.errors import BacktestError
    from openbb_backtest.models import BacktestConfig

    try:
        from openbb_backtest.adapters.nautilus import experiment

        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        config = BacktestConfig(
            strategy=spec["strategy"],
            strategy_version=spec.get("strategy_version"),
            universe=spec["universe"],
            start=spec["start"],
            end=spec["end"],
            initial_cash=Decimal(spec["initial_cash"]),
            benchmark=None,
            backend="nautilus",
        )
        base = dict(spec.get("strategy_params") or {})
        grid = spec.get("param_grid")
        combos = experiment.expand_grid(grid, base) if grid else [base]
        runs_root = Path(args.runs_root) if args.runs_root else None
        with tempfile.TemporaryDirectory(prefix="hfp-experiment-") as tmp:
            options = _options(
                spec, args.runtime, Path(tmp), runs_root or Path(tmp) / "runs"
            )
            report, outcome = experiment.run_validation(
                config,
                combos,
                method=spec.get("method", "wfo"),
                options=options,
                external_trials=int(spec.get("external_trials", 0)),
                policy=spec.get("policy", "continuous"),
            )
    except (BacktestError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n"
        )
        return 2
    summary = outcome.summary
    row = {
        "ok": True,
        "experiment_id": summary.experiment_id,
        "n_trials_dsr": summary.n_trials_dsr,
        "status": summary.status,
        "matrix_complete": summary.matrix_complete,
        "n_planned": summary.n_planned,
        "n_ok": summary.n_ok,
        "n_failed": summary.n_failed,
        "n_excluded": summary.n_excluded,
        "exclusions": summary.exclusions,
        "matrix_sha256": summary.matrix_sha256,
        "pbo": report.pbo,
        "deflated_sharpe": report.deflated_sharpe,
        "verdict": report.verdict,
        "new_attempts": outcome.appended,
    }
    if args.format == "json":
        out = json.dumps(row, indent=2, sort_keys=True)
    else:
        out = "\n".join(f"{k}: {v}" for k, v in row.items())
    sys.stdout.write(out + "\n")
    return 0


def _bench(args: argparse.Namespace) -> int:
    # pylint: disable=import-outside-toplevel  # lazy: keeps Nautilus optional
    from openbb_backtest.errors import BacktestError
    from openbb_backtest.validation import bench

    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        report = bench.run_bench(
            spec,
            runtime=args.runtime,
            runs_root=Path(args.runs_root) if args.runs_root else None,
            injections=bench.Injections(
                kill_after=args.inject_kill,
                fail_once=args.inject_fail_once,
                reject=args.inject_reject,
                changed_data=args.inject_changed_data,
            ),
        )
    except (BacktestError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n"
        )
        return 2
    if args.format == "json":
        out = json.dumps({"ok": True, **report}, indent=2, sort_keys=True)
    else:
        lines = [
            f"{r['scenario']} planned={r['n_planned']} ok={r['n_ok']} "
            f"failed={r['n_failed']} excluded={r['n_excluded']} N={r['n_trials_dsr']} "
            f"attempts={r['attempts']} complete={r['matrix_complete']} "
            f"sha={str(r['matrix_sha256'])[:12]} elapsed_s={r['elapsed_s']}"
            for r in report["scenarios"]
        ]
        lines.append(f"totals: {report['totals']}")
        lines.append(f"peak_concurrency: {report['peak_concurrency']}")
        lines.append(f"elapsed_s: {report['elapsed_s']}")
        out = "\n".join(lines)
    sys.stdout.write(out + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    ap = argparse.ArgumentParser(prog="experiment", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    qs = sub.add_parser("qualify-stats", help="check statistics against references")
    qs.add_argument("--references", type=Path, default=qualify.DEFAULT_REFERENCES)
    qs.add_argument("--format", choices=["json", "text"], default="text")
    rn = sub.add_parser("run", help="run one nautilus validate experiment")
    rn.add_argument("--spec", type=Path, required=True)
    rn.add_argument("--runtime", choices=["fake", "native", "docker"], required=True)
    rn.add_argument(
        "--runs-root",
        default=None,
        help="ledger root (default: a temporary directory, so no resume)",
    )
    rn.add_argument("--format", choices=["json", "text"], default="text")
    bn = sub.add_parser("bench", help="bounded benchmark of validation experiments")
    bn.add_argument("--spec", type=Path, required=True)
    bn.add_argument("--runtime", choices=["fake", "native", "docker"], required=True)
    bn.add_argument("--runs-root", default=None)
    bn.add_argument("--format", choices=["json", "text"], default="text")
    bn.add_argument("--inject-kill", type=int, default=None, metavar="K")
    bn.add_argument("--inject-fail-once", action="store_true")
    bn.add_argument("--inject-reject", action="store_true")
    bn.add_argument("--inject-changed-data", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if args.command == "run":
        return _run(args)
    if args.command == "bench":
        return _bench(args)
    return _qualify_stats(args)


if __name__ == "__main__":
    sys.exit(main())
