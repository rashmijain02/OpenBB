"""``PI_DEMO_MODE=only`` makes no provider, cache, MySQL or operator-store call (#1274).

The real self-hosted Workspace run with ``PI_DEMO_MODE=only`` showed widgets
that still dialled MySQL and FMP (``pi_equity_analyst_forecasts``), probed
provider reachability (``pi_provider_health``) and opened the operator
snapshot store under ``~/.portfolio_intel``. Every widget is called in a
hermetic subprocess (``_demo_only_probe.py``) whose network, pymysql,
fmp_cached, tier-dispatch, health-probe and snapshot-store seams record each
attempt. A ``fallback`` control run proves the seams are not vacuous.

HOME is a sentinel temp dir that already holds a ``.portfolio_intel/
snapshot.db`` that is not a database, so opening it would also be visible.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

UNIT = Path(__file__).resolve().parent
PROBE = UNIT / "_demo_only_probe.py"
PERF_PROBE = UNIT / "_workspace_perf_probe.py"
SENTINEL = b"sentinel: the operator snapshot store must not be opened\n"
#: Data sources that would mean a provider or probe answered in demo-only mode.
PROVIDER_SOURCES = {"fmp_cached", "fmp", "cboe", "sec", "yfinance-snapshot"}


def _hermetic_env(home: Path, **extra: str) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("_workspace_perf_probe", PERF_PROBE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.hermetic_env(home, sys.path, **extra)


def _run(home: Path, mode: str) -> dict[str, Any]:
    store = home / ".portfolio_intel"
    store.mkdir(parents=True)
    (store / "snapshot.db").write_bytes(SENTINEL)
    output = home / "demo-only.json"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter + in-repo probe
        [sys.executable, str(PROBE), "run", str(output)],
        cwd=home,
        env=_hermetic_env(home, PI_DEMO_MODE=mode),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    # Never echo probe output: it could contain response content.
    returncode = completed.returncode
    del completed
    assert returncode == 0, f"demo-only probe ({mode}) exited {returncode}"
    result = json.loads(output.read_text(encoding="utf-8"))
    result["sentinel_intact"] = (store / "snapshot.db").read_bytes() == SENTINEL
    result["store_entries"] = sorted(p.name for p in store.iterdir())
    return result


@pytest.fixture(scope="module", name="only")
def _only(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _run(tmp_path_factory.mktemp("only"), "only")


@pytest.fixture(scope="module", name="fallback")
def _fallback(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _run(tmp_path_factory.mktemp("fallback"), "fallback")


def _by_kind(calls: list[list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kind, widget, _detail in calls:
        out.setdefault(kind, [])
        if widget not in out[kind]:
            out[kind].append(widget)
    return out


def test_control_run_shows_the_seams_record_real_calls(
    fallback: dict[str, Any],
) -> None:
    """In ``fallback`` mode the same seams see tier, MySQL and probe calls."""
    kinds = _by_kind(fallback["calls"])
    assert fallback["mode"] == "fallback"
    assert {"tier", "health_probe", "snapshot_store"} <= set(kinds), sorted(kinds)


def test_demo_only_mode_makes_no_provider_cache_or_store_call(
    only: dict[str, Any],
) -> None:
    """No widget reaches a tier, fmp_cached, MySQL, a socket or a store."""
    assert only["mode"] == "only"
    assert _by_kind(only["calls"]) == {}


def test_demo_only_mode_never_opens_the_operator_snapshot_store(
    only: dict[str, Any],
) -> None:
    """The sentinel ``~/.portfolio_intel/snapshot.db`` is untouched."""
    assert only["sentinel_intact"]
    assert only["store_entries"] == ["snapshot.db"]


def test_demo_only_responses_are_labelled_demo_or_explicit(
    only: dict[str, Any],
) -> None:
    """Every widget answers without a 5xx and never claims a provider source."""
    responses = only["responses"]
    assert len(responses) > 61
    failures = {k: v for k, v in responses.items() if v["status"] >= 500}
    assert not failures
    provider = {
        k: v["source"]
        for k, v in responses.items()
        if v["source"] in PROVIDER_SOURCES or v["state"] == "cached"
    }
    assert not provider


def test_demo_only_provider_health_reports_not_probed(only: dict[str, Any]) -> None:
    """Provider health says demo / not probed, never healthy or live."""
    health = only["responses"]["pi_provider_health"]
    assert health["status"] == 200
    assert health["state"] == "demo"


def test_every_chart_figure_has_a_trace_workspace_will_draw(
    only: dict[str, Any],
) -> None:
    """Unavailable and demo figures keep a trace, so Workspace mounts Plotly."""
    charts = {k: v for k, v in only["responses"].items() if v["traces"] is not None}
    assert "tt_segment_movers" in charts and "tt_simulate_result" in charts
    assert "pi_xray_sector[account_id]" in charts
    blank = sorted(k for k, v in charts.items() if v["traces"] < 1)
    assert not blank
