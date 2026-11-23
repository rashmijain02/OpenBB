"""Hermetic subprocess probe for Workspace performance and reliability (#1274).

Run by ``test_workspace_performance_1274.py`` and
``scripts/benchmark_workspace_endpoints.py`` with the environment from
:func:`hermetic_env` (temp HOME, no credential/provider/proxy variables). It
reuses the network and dotenv guards of ``_workspace_endpoint_probe.py``
before importing the backend, so no provider, database or socket is reached.

Modes (``python _workspace_perf_probe.py MODE OUTPUT.json``):

- ``selftest``: guards and fakes are in place;
- ``headers``: status and headers of ``/widgets.json`` and ``/apps.json``;
- ``bench``: cold (first) and warm latency of the manifests and every widget
  endpoint (``BENCH_WARM`` repeats), with status, Cache-Control and data state;
- ``fanout``: load every app tab ``PERF_REFRESHES`` times with every provider
  tier failing, recording each tier call (the provider ledger);
- ``outage``: call every widget once with every tier failing.

Only statuses, headers, timings and ledger keys are written, never bodies.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

UNIT = Path(__file__).resolve().parent
SCRUB_PREFIXES = ("PI_", "DB_", "FMP", "OPENBB", "MYSQL", "FRED", "POLYGON")
SCRUB_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "_PROXY")
OUTAGE = "simulated provider outage (perf probe)"


def hermetic_env(home: Path, path: list[str], **extra: str) -> dict[str, str]:
    """Return a scrubbed environment whose home and app-data dirs are ``home``."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(SCRUB_PREFIXES)
        and not any(marker in name.upper() for marker in SCRUB_MARKERS)
    }
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[name] = str(home)
    env["PI_WIDGET_BACKEND_AUTH_MODE"] = "loopback-dev"
    env["PI_DEMO_MODE"] = "fallback"
    env["PI_PAPER_ENGINE"] = "sqlite"
    env["PI_PAPER_DB"] = str(home / "paper.db")
    env["PYTHONPATH"] = os.pathsep.join(p for p in path if p)
    env.update(extra)
    return env


class Ledger:
    """Provider tier calls and health probes made by the backend."""

    def __init__(self) -> None:
        """Start an empty ledger."""
        self.where: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.position: dict[int, int] = {}
        self.health_probes = 0
        self.health_tiers: set[str] = set()


LEDGER = Ledger()


def _install_fakes() -> None:
    """Replace the tier dispatch seam and the health probe with counting fakes."""
    # pylint: disable=import-outside-toplevel,protected-access
    from openbb_portfolio_intel.providers import retrofit
    from openbb_portfolio_intel.providers.probe import TierHealth
    from openbb_portfolio_intel.widget_backend import widgets_endpoints

    def fake_dispatch(tier: str, family: str, **kwargs: Any) -> Any:
        walk = LEDGER.where.get("walk", 0)
        position = LEDGER.position.get(walk, 0)
        LEDGER.position[walk] = position + 1
        LEDGER.events.append(
            {
                **{k: LEDGER.where.get(k) for k in ("app", "tab", "refresh", "widget")},
                "family": family,
                "tier": tier,
                "kwargs": json.dumps(kwargs, sort_keys=True, default=str),
                "position": position,
            }
        )
        raise ConnectionError(OUTAGE)

    async def fake_probe(tier: str, *_args: Any, **_kwargs: Any) -> Any:
        LEDGER.health_probes += 1
        LEDGER.health_tiers.add(tier)
        return TierHealth(name=tier, status="down", latency_ms=0, note="network")

    original = retrofit.route_through_chain

    def counted_route(**kwargs: Any) -> Any:
        LEDGER.where["walk"] = LEDGER.where.get("walk", 0) + 1
        return original(**kwargs)

    retrofit._dispatch = fake_dispatch
    retrofit.route_through_chain = counted_route
    widgets_endpoints.probe_tier = fake_probe


def _client() -> tuple[Any, dict[str, Any]]:
    # pylint: disable=import-outside-toplevel
    from fastapi.testclient import TestClient
    from openbb_portfolio_intel import widget_backend
    from openbb_portfolio_intel.widget_backend.main import app

    backend = Path(widget_backend.__file__ or "").parent
    widgets = json.loads((backend / "widgets.json").read_text(encoding="utf-8"))
    return TestClient(app, raise_server_exceptions=False), widgets


def _defaults(widget: dict[str, Any]) -> dict[str, Any]:
    return {
        p["paramName"]: p["value"]
        for p in widget.get("params", [])
        if p.get("value") not in (None, "")
    }


def _call(client: Any, widgets: dict[str, Any], widget_id: str) -> Any:
    widget = widgets[widget_id]
    return client.get("/" + widget["endpoint"].lstrip("/"), params=_defaults(widget))


def _selftest() -> dict[str, bool]:
    # pylint: disable=import-outside-toplevel,protected-access
    import socket

    from openbb_portfolio_intel.providers import retrofit
    from openbb_portfolio_intel.widget_backend import widgets_endpoints

    def _connect() -> None:
        with socket.socket() as sock:
            sock.connect(("127.0.0.1", 3306))

    try:
        _connect()
        blocked = False
    except OSError as exc:
        blocked = "blocked" in str(exc)
    try:
        retrofit._dispatch("fmp_cached", "equity/header", symbol="AAPL")
        dispatch_faked = False
    except ConnectionError:
        dispatch_faked = True
    asyncio.run(widgets_endpoints.probe_tier("fmp_cached"))
    return {
        "loopback_blocked": blocked,
        "home_isolated": Path.home().resolve() == Path(os.environ["HOME"]).resolve(),
        "dispatch_faked": dispatch_faked,
        "health_probe_faked": LEDGER.health_probes == 1,
    }


def _headers() -> dict[str, dict[str, Any]]:
    client, _widgets = _client()
    out = {}
    for path in ("/widgets.json", "/apps.json"):
        response = client.get(path)
        out[path] = {
            "status": response.status_code,
            "cache-control": response.headers.get("cache-control"),
            "content-type": response.headers.get("content-type"),
        }
    return out


def _bench() -> dict[str, Any]:
    start = time.perf_counter()
    client, widgets = _client()
    import_s = time.perf_counter() - start
    warm = int(os.environ.get("BENCH_WARM", "10"))
    targets: dict[str, tuple[str, dict[str, Any]]] = {
        "/widgets.json": ("/widgets.json", {}),
        "/apps.json": ("/apps.json", {}),
    }
    for widget_id, widget in widgets.items():
        targets[widget_id] = ("/" + widget["endpoint"].lstrip("/"), _defaults(widget))
    rows = {}
    for name, (path, params) in targets.items():
        samples = []
        for _ in range(warm + 1):
            t0 = time.perf_counter()
            response = client.get(path, params=params)
            samples.append((time.perf_counter() - t0) * 1000)
        rows[name] = {
            "path": path,
            "status": response.status_code,
            "cache_control": response.headers.get("cache-control"),
            "state": response.headers.get("x-pi-data-state"),
            "cold_ms": samples[0],
            "warm_ms": samples[1:],
        }
    return {"import_s": import_s, "warm_repeats": warm, "rows": rows}


def _fanout() -> dict[str, Any]:
    client, widgets = _client()
    apps = json.loads((_backend_dir() / "apps.json").read_text(encoding="utf-8"))
    refreshes = int(os.environ.get("PERF_REFRESHES", "2"))
    for refresh in range(refreshes):
        for app in apps:
            for tab_id, tab in (app.get("tabs") or {}).items():
                for item in tab.get("layout", []):
                    LEDGER.where.update(
                        app=app["name"], tab=tab_id, refresh=refresh, widget=item["i"]
                    )
                    _call(client, widgets, item["i"])
    return {
        "events": LEDGER.events,
        "health_probes": LEDGER.health_probes,
        "distinct_health_tiers": len(LEDGER.health_tiers),
    }


def _backend_dir() -> Path:
    # pylint: disable=import-outside-toplevel
    from openbb_portfolio_intel import widget_backend

    return Path(widget_backend.__file__ or "").parent


def _outage() -> dict[str, Any]:
    """Call every widget with its defaults.

    A widget that defaults to the demo book is called again with a synthetic
    non-demo account (``OUTAGE_ACCOUNT``).
    """
    client, widgets = _client()
    account = os.environ.get("OUTAGE_ACCOUNT", "Z00000001")
    out = {}
    for widget_id, widget in widgets.items():
        params = _defaults(widget)
        variants = {"default": params}
        demo_keys = [k for k in ("account_id", "basket_id") if params.get(k) == "demo"]
        if demo_keys:
            variants["account"] = {**params, **{k: account for k in demo_keys}}
        for variant, query in variants.items():
            before = len(LEDGER.events)
            LEDGER.where.update(app=None, tab=None, refresh=0, widget=widget_id)
            response = client.get("/" + widget["endpoint"].lstrip("/"), params=query)
            out[f"{widget_id}|{variant}"] = {
                "status": response.status_code,
                "state": response.headers.get("x-pi-data-state"),
                "attempted": len(LEDGER.events) > before,
                "explicit_demo": variant == "default" and bool(demo_keys),
            }
    return out


def main() -> int:
    """Install guards and fakes, run the mode, write JSON to the output path."""
    mode, output = sys.argv[1], Path(sys.argv[2])
    sys.path.insert(0, str(UNIT))
    # pylint: disable=import-outside-toplevel
    from _workspace_endpoint_probe import _install_guards

    _install_guards()
    if mode != "bench" or os.environ.get("BENCH_FAKE_TIERS", "1") == "1":
        _install_fakes()
    modes = {
        "selftest": _selftest,
        "headers": _headers,
        "bench": _bench,
        "fanout": _fanout,
        "outage": _outage,
    }
    output.write_text(json.dumps(modes[mode]()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
