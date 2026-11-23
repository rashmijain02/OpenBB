"""Benchmark the Portfolio Intelligence Workspace endpoints hermetically (#1274).

Plan Step 11 measurement. Each cold run is a fresh subprocess
(``tests/unit/_workspace_perf_probe.py bench``) with a scrubbed environment,
a temp HOME, dotenv disabled and every DNS lookup and socket connect refused,
``PI_DEMO_MODE=fallback``. Provider tiers are a failing fake by default (so
the numbers are backend overhead plus the labelled demo fallback);
``--real-tiers`` keeps the real tier code, still network-blocked.

For ``/widgets.json``, ``/apps.json`` and every widget endpoint it reports
cold (first call in a fresh process) and warm (repeat) p50/p95, the HTTP
status, the ``Cache-Control`` header and the data state, then writes
``report.json`` and ``report.md`` under ``--out-dir`` (git-ignored
``.dev-cycle/`` by default). Calls go through the ASGI app in-process, so
socket and uvicorn time are excluded.

Usage (with PYTHONPATH covering the extension packages)::

    python scripts/benchmark_workspace_endpoints.py --cold-runs 3 --warm 10

Exit codes: 0 = measured; 1 = a manifest lacks ``Cache-Control: no-store``,
or ``--enforce`` and a plan budget is exceeded.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PROBE = (
    REPO
    / "openbb_platform/extensions/portfolio_intel/tests/unit/_workspace_perf_probe.py"
)
MANIFESTS = ("/widgets.json", "/apps.json")
#: Plan section 8 performance targets (planning defaults, to be measured).
MANIFEST_P95_MS = 300.0
CACHED_P95_MS = 500.0


def percentile(samples: list[float], pct: float) -> float:
    """Return the nearest-rank percentile of ``samples`` (0 for none)."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _probe_env(home: Path, extra: dict[str, str]) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("_workspace_perf_probe", PROBE)
    if spec is None or spec.loader is None:
        raise RuntimeError("perf probe not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.hermetic_env(home, sys.path, **extra)


def run_bench(warm: int, real_tiers: bool) -> dict[str, Any]:
    """Run one fresh hermetic bench subprocess and return its JSON."""
    with tempfile.TemporaryDirectory(prefix="pi-bench-") as tmp:
        home = Path(tmp)
        extra = {
            "BENCH_WARM": str(warm),
            "BENCH_FAKE_TIERS": "0" if real_tiers else "1",
        }
        output = home / "bench.json"
        completed = subprocess.run(  # noqa: S603 - fixed interpreter + in-repo probe
            [sys.executable, str(PROBE), "bench", str(output)],
            cwd=home,
            env=_probe_env(home, extra),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            # Never echo probe output: it may contain response content.
            raise RuntimeError(f"bench probe exited {completed.returncode}")
        return json.loads(output.read_text(encoding="utf-8"))


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cold and warm samples per target across runs."""
    targets: dict[str, dict[str, Any]] = {}
    for run in runs:
        for name, row in run["rows"].items():
            entry = targets.setdefault(
                name,
                {
                    "path": row["path"],
                    "cold": [],
                    "warm": [],
                    "status": set(),
                    "cache_control": set(),
                    "state": set(),
                },
            )
            entry["cold"].append(row["cold_ms"])
            entry["warm"].extend(row["warm_ms"])
            entry["status"].add(row["status"])
            entry["cache_control"].add(row["cache_control"] or "-")
            entry["state"].add(row["state"] or "-")
    rows = {
        name: {
            "path": e["path"],
            "cold_p50_ms": round(percentile(e["cold"], 50), 2),
            "cold_p95_ms": round(percentile(e["cold"], 95), 2),
            "warm_p50_ms": round(percentile(e["warm"], 50), 2),
            "warm_p95_ms": round(percentile(e["warm"], 95), 2),
            "status": sorted(e["status"]),
            "cache_control": sorted(e["cache_control"]),
            "state": sorted(e["state"]),
        }
        for name, e in targets.items()
    }
    return {
        "cold_runs": len(runs),
        "warm_repeats": runs[0]["warm_repeats"] if runs else 0,
        "import_s": [round(r["import_s"], 2) for r in runs],
        "rows": rows,
    }


def check(summary: dict[str, Any]) -> list[str]:
    """Return budget and cache-header findings (``CACHE`` ones always fail)."""
    findings = []
    for name, row in summary["rows"].items():
        if name in MANIFESTS:
            if row["cache_control"] != ["no-store"]:
                findings.append(f"CACHE {name}: Cache-Control {row['cache_control']}")
            if row["warm_p95_ms"] > MANIFEST_P95_MS:
                findings.append(f"BUDGET {name}: warm p95 {row['warm_p95_ms']} ms")
        elif row["warm_p95_ms"] > CACHED_P95_MS:
            findings.append(f"BUDGET {name}: warm p95 {row['warm_p95_ms']} ms")
    return findings


def render_markdown(summary: dict[str, Any], findings: list[str]) -> str:
    """Return the Markdown report (slowest cold p95 first)."""
    lines = [
        "# Workspace endpoint benchmark (hermetic)",
        "",
        f"Cold runs: {summary['cold_runs']}; warm repeats per run: "
        f"{summary['warm_repeats']}; backend import s: {summary['import_s']}.",
        f"Budgets: manifest p95 < {MANIFEST_P95_MS:.0f} ms; "
        f"cached widget p95 < {CACHED_P95_MS:.0f} ms.",
        "",
        "| Target | Cold p50 | Cold p95 | Warm p50 | Warm p95 | Status "
        "| Cache-Control | State |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    ordered = sorted(
        summary["rows"].items(), key=lambda kv: kv[1]["cold_p95_ms"], reverse=True
    )
    for name, row in ordered:
        lines.append(
            f"| `{name}` | {row['cold_p50_ms']} | {row['cold_p95_ms']} | "
            f"{row['warm_p50_ms']} | {row['warm_p95_ms']} | "
            f"{','.join(map(str, row['status']))} | "
            f"{','.join(row['cache_control'])} | {','.join(row['state'])} |"
        )
    lines += ["", "## Findings", ""]
    lines += [f"- {f}" for f in findings] or ["- none"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and write the reports."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--cold-runs", type=int, default=3)
    parser.add_argument("--warm", type=int, default=10)
    parser.add_argument("--real-tiers", action="store_true")
    parser.add_argument("--enforce", action="store_true", help="fail on budgets")
    parser.add_argument(
        "--out-dir", type=Path, default=REPO / ".dev-cycle" / "workspace-bench"
    )
    args = parser.parse_args(argv)
    runs = [run_bench(args.warm, args.real_tiers) for _ in range(args.cold_runs)]
    summary = summarize(runs)
    findings = check(summary)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {**summary, "findings": findings}
    (args.out_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (args.out_dir / "report.md").write_text(
        render_markdown(summary, findings), encoding="utf-8"
    )
    sys.stdout.write(f"{len(summary['rows'])} targets; findings: {len(findings)}\n")
    for finding in findings:
        sys.stdout.write(finding + "\n")
    failed = any(f.startswith("CACHE") for f in findings) or (
        args.enforce and any(f.startswith("BUDGET") for f in findings)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
