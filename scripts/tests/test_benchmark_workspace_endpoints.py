"""Unit tests for ``scripts/benchmark_workspace_endpoints.py`` (#1274)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_workspace_endpoints as bench  # noqa: E402  pylint: disable=wrong-import-position


def _run(cold: float, warm: list[float], cache: str | None) -> dict:
    row = {
        "path": "/x",
        "status": 200,
        "cache_control": cache,
        "state": "demo",
        "cold_ms": cold,
        "warm_ms": warm,
    }
    return {
        "import_s": 1.0,
        "warm_repeats": len(warm),
        "rows": {"/widgets.json": row, "pi_w": {**row, "cache_control": None}},
    }


def test_percentile_nearest_rank() -> None:
    """p95 of 1..20 is 19; p50 is 10; empty is 0."""
    samples = [float(i) for i in range(1, 21)]
    assert bench.percentile(samples, 95) == 19.0
    assert bench.percentile(samples, 50) == 10.0
    assert bench.percentile([], 95) == 0.0


def test_summarize_pools_cold_per_run_and_warm_samples() -> None:
    """Cold p95 comes from first calls of each run; warm pools every repeat."""
    summary = bench.summarize(
        [_run(100.0, [1.0, 2.0], "no-store"), _run(300.0, [3.0, 4.0], "no-store")]
    )
    row = summary["rows"]["/widgets.json"]
    assert row["cold_p95_ms"] == 300.0
    assert row["warm_p95_ms"] == 4.0
    assert summary["rows"]["pi_w"]["cache_control"] == ["-"]


def test_check_flags_manifest_without_no_store_and_budgets() -> None:
    """A cacheable manifest is a CACHE finding; slow warm p95 a BUDGET one."""
    summary = bench.summarize([_run(1.0, [900.0], "max-age=60")])
    findings = bench.check(summary)
    assert any(f.startswith("CACHE /widgets.json") for f in findings)
    assert any(f.startswith("BUDGET pi_w") for f in findings)
    assert not bench.check(bench.summarize([_run(1.0, [1.0], "no-store")]))
