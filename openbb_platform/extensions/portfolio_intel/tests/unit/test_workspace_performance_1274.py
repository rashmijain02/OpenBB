"""Hermetic performance and reliability measurement for Workspace (#1274, plan Step 11).

These tests MEASURE; they never change backend behaviour. Every widget
endpoint runs inside the hermetic subprocess ``_workspace_perf_probe.py``
(scrubbed environment, temp HOME, dotenv disabled, DNS and socket connects
refused). Provider tiers are replaced at the one dispatch seam
(``providers.retrofit._dispatch``) by a counting fake that simulates a full
outage, and the provider-health reachability probe by a counting fake, so
the provider ledger counts exactly the tier calls a Workspace app page
causes. The #1274 identical-refresh gap is fixed by the #1275 result cache.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from openbb_portfolio_intel.widget_backend.provenance import BODY_STATES

UNIT = Path(__file__).resolve().parent
PROBE = UNIT / "_workspace_perf_probe.py"
BACKEND = UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
APPS: list[dict[str, Any]] = json.loads(
    (BACKEND / "apps.json").read_text(encoding="utf-8")
)
WIDGETS: dict[str, Any] = json.loads(
    (BACKEND / "widgets.json").read_text(encoding="utf-8")
)
REFRESHES = 3
#: Longest Track A chain in providers/registry.py (fmp_cached -> fmp -> cboe
#: -> sec -> yfinance-snapshot).
MAX_CHAIN = 5


def _probe_module() -> Any:
    spec = importlib.util.spec_from_file_location("_workspace_perf_probe", PROBE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(mode: str, home: Path, **extra: str) -> Any:
    """Run one probe mode; never echo its output (it may hold bodies)."""
    output = home / f"{mode}.json"
    env = _probe_module().hermetic_env(home, sys.path, **extra)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter + in-repo probe
        [sys.executable, str(PROBE), mode, str(output)],
        cwd=home,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    returncode = completed.returncode
    del completed
    assert returncode == 0, f"perf probe {mode} exited {returncode}"
    return json.loads(output.read_text(encoding="utf-8"))


def _tabs() -> list[tuple[str, str, list[str]]]:
    return [
        (app["name"], tab_id, [w["i"] for w in tab.get("layout", [])])
        for app in APPS
        for tab_id, tab in (app.get("tabs") or {}).items()
    ]


@pytest.fixture(scope="module", name="fanout")
def _fanout(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Load every app tab REFRESHES times under a simulated provider outage."""
    return _run(
        "fanout",
        tmp_path_factory.mktemp("fanout"),
        PERF_REFRESHES=str(REFRESHES),
        # Pin the cache TTLs so the run never straddles an expiry.
        PI_PROVIDER_CACHE_TTL_S="600",
        PI_PROVIDER_CACHE_NEGATIVE_TTL_S="600",
    )


@pytest.fixture(scope="module", name="outage")
def _outage(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Call every widget once with every tier down and demo data off."""
    return _run("outage", tmp_path_factory.mktemp("outage"), PI_DEMO_MODE="off")


# ---------------------------------------------------------------------------
# (a) manifest Cache-Control
# ---------------------------------------------------------------------------


def test_manifests_carry_designed_cache_control(tmp_path: Path) -> None:
    """``/widgets.json`` and ``/apps.json`` are ``no-store`` UTF-8 JSON."""
    headers = _run("headers", tmp_path)
    for path in ("/widgets.json", "/apps.json"):
        assert headers[path]["status"] == 200
        assert headers[path]["cache-control"] == "no-store"
        assert "charset=utf-8" in headers[path]["content-type"]


def test_probe_isolation_and_fakes_hold(tmp_path: Path) -> None:
    """Network is refused and both provider seams are replaced by the fakes."""
    checks = _run("selftest", tmp_path)
    assert checks == {name: True for name in checks}
    assert len(checks) == 4


# ---------------------------------------------------------------------------
# (b) bounded provider fan-out per app tab
# ---------------------------------------------------------------------------


def _events(fanout: dict[str, Any], app: str, tab: str, refresh: int) -> list:
    return [
        e
        for e in fanout["events"]
        if e["app"] == app and e["tab"] == tab and e["refresh"] == refresh
    ]


def test_fanout_ledger_is_not_vacuous(fanout: dict[str, Any]) -> None:
    """The fake tier seam is reached, so the bounds below are meaningful."""
    assert len(fanout["events"]) > 0
    assert fanout["health_probes"] > 0


@pytest.mark.parametrize(("app", "tab", "widgets"), _tabs())
def test_tab_provider_fanout_is_bounded(
    app: str, tab: str, widgets: list[str], fanout: dict[str, Any]
) -> None:
    """One tab load walks at most one chain per widget, each at most MAX_CHAIN deep."""
    events = _events(fanout, app, tab, 0)
    walks = [e for e in events if e["position"] == 0]
    assert len(walks) <= len(
        widgets
    ), f"{len(walks)} chain walks for {len(widgets)} widgets"
    assert len(events) <= len(widgets) * MAX_CHAIN


def test_no_duplicate_tier_fetch_within_one_tab_load(fanout: dict[str, Any]) -> None:
    """No (family, tier, kwargs) is called twice while loading one tab."""
    duplicates = {}
    for app, tab, _widgets in _tabs():
        counts = Counter(
            (e["family"], e["tier"], e["kwargs"]) for e in _events(fanout, app, tab, 0)
        )
        dup = {k: n for k, n in counts.items() if n > 1}
        if dup:
            duplicates[f"{app}/{tab}"] = len(dup)
    assert not duplicates, duplicates


# ---------------------------------------------------------------------------
# (c) repeated refreshes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("app", "tab", "widgets"), _tabs())
def test_refresh_does_not_multiply_provider_calls(
    app: str, tab: str, widgets: list[str], fanout: dict[str, Any]
) -> None:
    """Each refresh costs the same as the first load: linear, never compounding."""
    first = len(_events(fanout, app, tab, 0))
    assert first <= len(widgets) * MAX_CHAIN
    for refresh in range(1, REFRESHES):
        assert len(_events(fanout, app, tab, refresh)) <= first


def test_provider_health_probes_once_per_ttl(fanout: dict[str, Any]) -> None:
    """Health probes each distinct tier once; every later tab/refresh hits the 60s cache."""
    assert fanout["health_probes"] == fanout["distinct_health_tiers"]


def test_identical_refresh_makes_no_new_provider_calls(fanout: dict[str, Any]) -> None:
    """A second identical load inside the TTL is served without provider calls."""
    repeat = [e for e in fanout["events"] if e["refresh"] > 0]
    assert not repeat, f"{len(repeat)} provider calls on identical refreshes"


# ---------------------------------------------------------------------------
# (d) provider outage
# ---------------------------------------------------------------------------


def test_outage_reaches_provider_tiers(outage: dict[str, Any]) -> None:
    """The outage run really exercises provider-backed widgets on both variants."""
    assert any(r["attempted"] for k, r in outage.items() if k.endswith("|default"))
    assert any(r["attempted"] for k, r in outage.items() if k.endswith("|account"))


def _variants(widget_id: str, outage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key.split("|", 1)[1]: row
        for key, row in outage.items()
        if key.split("|", 1)[0] == widget_id
    }


@pytest.mark.parametrize("widget_id", sorted(WIDGETS))
def test_outage_is_explicit_unavailable_not_500(
    widget_id: str, outage: dict[str, Any]
) -> None:
    """Every widget answers a total outage without a 5xx and with a stated state.

    Demo data is off. A widget whose provider chain was walked must say
    ``unavailable``, never a success-shaped live/cached answer, unless the
    request explicitly selected the labelled demo book (``account_id=demo``,
    the manifest default). Widgets that default to the demo book are also
    called with a synthetic non-demo account, which must be ``unavailable``
    (or a 4xx ``forbidden`` for an unknown basket), never a 500.
    """
    variants = _variants(widget_id, outage)
    assert "default" in variants
    for variant, row in variants.items():
        label = f"{variant}: HTTP {row['status']} state {row['state']}"
        assert row["status"] < 500, label
        if row["status"] >= 400:
            assert row["state"] == "forbidden", label
            continue
        assert row["state"] in BODY_STATES, label
        if row["attempted"] and not row["explicit_demo"]:
            assert row["state"] == "unavailable", label
