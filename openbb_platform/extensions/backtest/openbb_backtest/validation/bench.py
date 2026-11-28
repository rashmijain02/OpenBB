"""Bounded benchmark of realistic validation experiments (#1357 T03).

``bench`` runs a grid of reviewed strategies x resampling methods x window
policies through the same nautilus experiment path as ``validate`` and reports
counts, error codes and timings only (never returns, positions or accounts):
planned / ok / failed / excluded cells, attempts, ``N`` (trials for DSR),
matrix completeness, exclusion codes and the matrix hash.

With ``--runtime fake`` the data are generated here from a seeded generator
(synthetic, never real prices) and each cell runs through the real worker
entrypoint with the event-replay fake engine. ``native`` / ``docker`` use the
configured worker and the cached export for the spec's symbols.

Failure injection (all deterministic):

- ``kill_after=K``: dispatch only the first ``K`` cells, as if the process had
  died, then resume from the ledger; ``N`` and the matrix must not change.
- ``fail_once``: the fake worker dies in the middle of its first run; the cell
  is retried once (fake only).
- ``reject``: one extra configuration the allowlist rejects; it stays in the
  plan and in ``N`` as ``admission_rejected``.
- ``changed_data`` (fake only): the first scenario is re-planned over bars with
  one close changed; the new dataset id yields a new experiment and the first
  ledger is untouched.
"""

from __future__ import annotations

import sys
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Injections:
    """Failure injections for one bench run."""

    kill_after: int | None = None
    fail_once: bool = False
    reject: bool = False
    changed_data: bool = False


def generate_bars(gen: dict[str, Any]) -> tuple[list[str], dict[str, list[list[str]]]]:
    """Seeded synthetic ``(sessions, {symbol: [[open, close], ...]})``."""
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.data.calendars import sessions_in_range

    sessions = [
        ts.date().isoformat()
        for ts in sessions_in_range(
            gen["start"], gen["end"], gen.get("calendar", "XNYS")
        )
    ]
    rng = np.random.default_rng(int(gen["seed"]))
    bars: dict[str, list[list[str]]] = {}
    for sym, drift in gen["drifts"].items():
        price, rows = 50.0, []
        for _ in sessions:
            close = max(1.0, price * (1 + float(drift) + float(rng.normal(0, 0.015))))
            rows.append([f"{price:.2f}", f"{close:.2f}"])
            price = close
        bars[sym] = rows
    return sessions, bars


class _Probe:
    """Counts concurrently open worker clients (the heavy-job lock keeps it 1)."""

    def __init__(self, factory: Any) -> None:
        self.factory = factory
        self.active = 0
        self.peak = 0
        self.spawns = 0

    def __call__(self) -> Any:
        probe, client = self, self.factory()

        class _Ctx:
            def __enter__(self) -> Any:
                probe.active += 1
                probe.spawns += 1
                probe.peak = max(probe.peak, probe.active)
                return client.__enter__()

            def __exit__(self, *exc: Any) -> Any:
                probe.active -= 1
                return client.__exit__(*exc)

        return _Ctx()


def _fake_options(
    bars: dict[str, list[list[str]]],
    sessions: list[str],
    tmp: Path,
    runs_root: Path,
    fail_state: Path | None,
) -> tuple[Any, _Probe]:
    # pylint: disable=import-outside-toplevel,protected-access
    from openbb_backtest.adapters.nautilus import (
        backend,
        export as ex,
        golden,
    )

    root, snap = tmp / "data", tmp / "snap"
    golden._snapshot({"bars": bars}, sessions, snap)
    command = [sys.executable, str(golden.FAKE_WORKER)]
    if fail_state is not None:
        command += ["--fail-once", str(fail_state)]
    probe = _Probe(golden._client("fake", command, root))
    options = backend.NautilusOptions(
        client_factory=probe,
        execute=ex.snapshot_executor(snap),
        data_root=root,
        qualify=False,
        runtime="fake",
        runs_root=runs_root,
    )
    return options, probe


def _config(spec: dict[str, Any], strat: dict[str, Any], symbols: list[str]) -> Any:
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.models import BacktestConfig

    return BacktestConfig(
        strategy=strat["strategy"],
        strategy_version=strat.get("strategy_version"),
        universe=symbols,
        start=spec["generator"]["start"],
        end=spec["generator"]["end"],
        initial_cash=Decimal(spec["initial_cash"]),
        benchmark=None,
        backend="nautilus",
    )


def _combos(strat: dict[str, Any], symbols: list[str], reject: bool) -> list[Any]:
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.adapters.nautilus import experiment

    base = dict(strat.get("strategy_params") or {})
    grid = strat.get("param_grid")
    combos = experiment.expand_grid(grid, base) if grid else [base]
    if reject and strat["strategy"] == "target_weight_rebalance":
        bad = {s: "0.7" for s in symbols}  # sums above one: allowlist rejects it
        combos.append({**base, "weights": bad})
    return combos


def _row(
    name: str,
    outcome: Any,
    appended: int,
    elapsed: float,
    expected_n: int,
) -> dict[str, Any]:
    s = outcome.summary
    return {
        "scenario": name,
        "experiment_id": s.experiment_id,
        "n_planned": s.n_planned,
        "n_ok": s.n_ok,
        "n_failed": s.n_failed,
        "n_excluded": s.n_excluded,
        "attempts": len(outcome.ledger.records()),
        "new_attempts": appended,
        "n_trials_dsr": s.n_trials_dsr,
        "n_expected": expected_n,
        "matrix_complete": s.matrix_complete,
        "status": s.status,
        "exclusions": s.exclusions,
        "matrix_sha256": s.matrix_sha256,
        "elapsed_s": round(elapsed, 3),
    }


def _run_scenario(  # pylint: disable=too-many-arguments,too-many-locals
    spec: dict[str, Any],
    strat: dict[str, Any],
    *,
    method: str,
    policy: str,
    options: Any,
    symbols: list[str],
    inj: Injections,
) -> tuple[dict[str, Any], Any, Any]:
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.adapters.nautilus import experiment

    symbols = list(strat.get("universe") or symbols)  # buy_and_hold: one symbol
    config = _config(spec, strat, symbols)
    combos = _combos(strat, symbols, inj.reject)
    sessions = experiment.session_calendar(config)
    folds = experiment.fold_plan(sessions, method, policy)  # type: ignore[arg-type]
    the_plan = experiment.plan(
        config,
        combos,
        folds.windows,
        command="validate",
        method=method,
        policy=policy,  # type: ignore[arg-type]
        fold_params=folds.fold_params,
        options=options,
        external_trials=int(strat.get("external_trials", 0)),
    )
    t0 = time.perf_counter()
    killed: dict[str, Any] | None = None
    if inj.kill_after is not None:
        ids = [c.trial_id for c in the_plan.cells]
        first = experiment.run(the_plan, config, options, only=ids[: inj.kill_after])
        killed = {"killed_after": inj.kill_after, "attempts_before": first.appended}
    outcome = experiment.run(the_plan, config, options)
    appended = outcome.appended + (killed["attempts_before"] if killed else 0)
    name = f"{strat['strategy']}/{method}/{policy}"
    row = _row(
        name,
        outcome,
        appended,
        time.perf_counter() - t0,
        len(the_plan.combos) + the_plan.external_trials,
    )
    if killed:
        row["kill_resume"] = {**killed, "resumed_attempts": outcome.appended}
    return row, the_plan, config


def _changed_data(
    spec: dict[str, Any],
    strat: dict[str, Any],
    first: dict[str, Any],
    data: tuple[list[str], list[str], dict[str, list[list[str]]]],
    *,
    tmp: Path,
    runs_root: Path,
    reject: bool,
) -> dict[str, Any]:
    """Re-run the first scenario over bars with one close changed."""
    symbols, sessions, bars = data
    sym = symbols[0]
    changed = {k: [list(r) for r in v] for k, v in bars.items()}
    old = Decimal(changed[sym][len(sessions) // 2][1])
    changed[sym][len(sessions) // 2][1] = f"{old + Decimal('0.50'):.2f}"
    (tmp / "changed").mkdir()
    options, _probe = _fake_options(changed, sessions, tmp / "changed", runs_root, None)
    _method, _policy = first["scenario"].split("/")[1:]
    row, _p, _c = _run_scenario(
        spec,
        strat,
        method=_method,
        policy=_policy,
        options=options,
        symbols=symbols,
        inj=Injections(reject=reject),
    )
    return {
        "experiment_id_changed": row["experiment_id"] != first["experiment_id"],
        "n_equal": row["n_trials_dsr"] == first["n_trials_dsr"],
        "matrix_changed": row["matrix_sha256"] != first["matrix_sha256"],
        "attempts": row["attempts"],
    }


def run_bench(
    spec: dict[str, Any],
    *,
    runtime: str,
    runs_root: Path | None = None,
    injections: Injections | None = None,
) -> dict[str, Any]:
    """Run every scenario of ``spec`` and return counts, codes and timings."""
    # pylint: disable-next=import-outside-toplevel
    from openbb_backtest.adapters.nautilus import backend

    inj = injections or Injections()
    if runtime != "fake" and (inj.fail_once or inj.changed_data):
        raise ValueError("fail_once and changed_data injections need --runtime fake")
    gen = spec["generator"]
    symbols = sorted(gen["drifts"])
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="hfp-bench-") as tmp_name:
        tmp = Path(tmp_name)
        root = runs_root or tmp / "runs"
        probe: _Probe | None = None
        sessions: list[str] = []
        bars: dict[str, list[list[str]]] = {}
        if runtime == "fake":
            sessions, bars = generate_bars(gen)
            options, probe = _fake_options(
                bars,
                sessions,
                tmp,
                root,
                tmp / "fail-once.flag" if inj.fail_once else None,
            )
        else:
            options = backend.NautilusOptions(runtime=runtime, runs_root=root)
        rows: list[dict[str, Any]] = []
        first_ctx: tuple[dict[str, Any], dict[str, Any]] | None = None
        for strat in spec["strategies"]:
            for method in spec["methods"]:
                for policy in spec["policies"]:
                    row, _p, _c = _run_scenario(
                        spec,
                        strat,
                        method=method,
                        policy=policy,
                        options=options,
                        symbols=symbols,
                        inj=inj,
                    )
                    rows.append(row)
                    first_ctx = first_ctx or (strat, row)
        report: dict[str, Any] = {
            "runtime": runtime,
            "scenarios": rows,
            "totals": {
                "scenarios": len(rows),
                "cells": sum(r["n_planned"] for r in rows),
                "ok": sum(r["n_ok"] for r in rows),
                "failed": sum(r["n_failed"] for r in rows),
                "excluded": sum(r["n_excluded"] for r in rows),
                "attempts": sum(r["attempts"] for r in rows),
                "n_trials_dsr": sum(r["n_trials_dsr"] for r in rows),
                "n_matches_plan": all(
                    r["n_trials_dsr"] == r["n_expected"] for r in rows
                ),
            },
            "peak_concurrency": probe.peak if probe else None,
            "worker_spawns": probe.spawns if probe else None,
            "injections": {
                "kill_after": inj.kill_after,
                "fail_once": inj.fail_once,
                "fail_once_fired": (tmp / "fail-once.flag").exists(),
                "reject": inj.reject,
            },
        }
        if inj.changed_data and first_ctx is not None:
            report["changed_data"] = _changed_data(
                spec,
                first_ctx[0],
                first_ctx[1],
                (symbols, sessions, bars),
                tmp=tmp,
                runs_root=root,
                reject=inj.reject,
            )
        report["elapsed_s"] = round(time.perf_counter() - started, 3)
    return report
