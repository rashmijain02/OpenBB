"""Hermetic probe: ``PI_DEMO_MODE=only`` reaches no provider, cache or store (#1274).

Run by ``test_demo_only_isolation_1274.py`` with the environment from
``_workspace_perf_probe.hermetic_env`` (temp HOME, no credential, provider
or proxy variables). Before importing the backend it installs the network
and dotenv guards of ``_workspace_endpoint_probe.py`` and wraps every seam a
widget could use to reach outside data, recording each attempt:

- ``socket`` / ``dns``: a socket connect or DNS lookup (still refused);
- ``mysql``: ``pymysql.connect`` (raises ``OperationalError``);
- ``fmp_cached``: the fmp_cached MySQL pool and every fmp_cached fetcher;
- ``tier``: ``providers.retrofit._dispatch`` (a provider tier call);
- ``health_probe``: the provider-health reachability probe;
- ``snapshot_store``: the operator EOD snapshot store factory;
- ``sqlite``: a SQLite open under ``~/.portfolio_intel`` (operator stores).

It then calls every widget with its manifest defaults, again with a
non-demo account or basket where the widget takes one, and every chart with
``raw=true``. Only call kinds, statuses, headers and chart trace counts are
written, never response bodies.

Usage: ``python _demo_only_probe.py run OUTPUT.json``
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
from pathlib import Path
from typing import Any

UNIT = Path(__file__).resolve().parent
sys.path.insert(0, str(UNIT))

import _workspace_endpoint_probe as guards  # noqa: E402  # pylint: disable=wrong-import-position

CALLS: list[list[str]] = []
CURRENT: dict[str, str] = {"widget": "<import>"}
NON_DEMO = "acct-not-demo"


def _record(kind: str, detail: str = "") -> None:
    CALLS.append([kind, CURRENT["widget"], detail])


class BlockedCall(ConnectionError):
    """Raised by every recorded seam so callers take their failure path."""


def _wrap_socket() -> None:
    guarded_connect = socket.socket.connect
    guarded_connect_ex = socket.socket.connect_ex
    guarded_dns = socket.getaddrinfo

    def _connect(sock: socket.socket, address: Any) -> Any:
        if not getattr(
            guards._PAIRING, "active", False
        ):  # pylint: disable=protected-access
            _record("socket", str(address))
        return guarded_connect(sock, address)

    def _connect_ex(sock: socket.socket, address: Any) -> Any:
        if not getattr(
            guards._PAIRING, "active", False
        ):  # pylint: disable=protected-access
            _record("socket", str(address))
        return guarded_connect_ex(sock, address)

    def _dns(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host != "testserver":
            _record("dns", str(host))
        return guarded_dns(host, *args, **kwargs)

    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _dns


def _wrap_sqlite() -> None:
    real = sqlite3.connect
    operator_dir = (Path.home() / ".portfolio_intel").resolve()

    def _connect(database: Any, *args: Any, **kwargs: Any) -> Any:
        text = str(database)
        if not text.startswith(":") and not text.startswith("file:"):
            path = Path(text).expanduser().resolve()
            if operator_dir == path or operator_dir in path.parents:
                _record("sqlite", path.name)
        return real(database, *args, **kwargs)

    sqlite3.connect = _connect


def _wrap_mysql() -> None:
    import pymysql  # pylint: disable=import-outside-toplevel
    import pymysql.err  # pylint: disable=import-outside-toplevel

    def _connect(*_args: Any, **_kwargs: Any) -> Any:
        _record("mysql")
        raise pymysql.err.OperationalError(2003, "blocked in demo-only probe")

    pymysql.connect = _connect
    pymysql.Connect = _connect


def _wrap_fmp_cached() -> None:
    # pylint: disable=import-outside-toplevel
    from openbb_fmp_cached.utils import database

    def _pool(*_args: Any, **_kwargs: Any) -> Any:
        _record("fmp_cached", "connection_pool")
        raise BlockedCall("fmp_cached pool blocked in demo-only probe")

    database.get_connection_pool = _pool
    database.ConnectionPool.get_connection = _pool  # type: ignore[method-assign]

    from openbb_fmp_cached import fmp_cached_provider

    for name, fetcher in fmp_cached_provider.fetcher_dict.items():
        for attr in ("aextract_data", "extract_data", "fetch_data"):
            if attr not in vars(fetcher):
                continue

            def _blocked(*_args: Any, _name: str = name, **_kwargs: Any) -> Any:
                _record("fmp_cached", _name)
                raise BlockedCall("fmp_cached fetcher blocked in demo-only probe")

            setattr(fetcher, attr, staticmethod(_blocked))


def _wrap_snapshot_factory() -> None:
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.snapshot import store

    def _factory(*_args: Any, **_kwargs: Any) -> Any:
        _record("snapshot_store")
        raise BlockedCall("snapshot store blocked in demo-only probe")

    store.get_default_snapshot_store = _factory


def _wrap_backend() -> None:
    # pylint: disable=import-outside-toplevel,protected-access
    from openbb_portfolio_intel.providers import retrofit
    from openbb_portfolio_intel.widget_backend import widgets_endpoints

    def _dispatch(tier: str, family: str, **_kwargs: Any) -> Any:
        _record("tier", f"{family}:{tier}")
        raise BlockedCall("provider tier blocked in demo-only probe")

    async def _probe(tier: str, *_args: Any, **_kwargs: Any) -> Any:
        _record("health_probe", tier)
        raise BlockedCall("health probe blocked in demo-only probe")

    retrofit._dispatch = _dispatch
    widgets_endpoints.probe_tier = _probe
    widgets_endpoints._SNAPSHOT_STORE_CACHE = None
    widgets_endpoints._PROVIDER_HEALTH_CACHE.clear()


def install() -> None:
    """Install the guards and every recording seam (before the backend import)."""
    guards._install_guards()  # pylint: disable=protected-access
    _wrap_socket()
    _wrap_sqlite()
    _wrap_mysql()
    _wrap_fmp_cached()
    _wrap_snapshot_factory()
    _wrap_backend()


def _requests(widgets: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for widget_id, widget in widgets.items():
        params = {
            p["paramName"]: p["value"]
            for p in widget.get("params", [])
            if p.get("value") not in (None, "")
        }
        path = "/" + widget["endpoint"].lstrip("/")
        out.append((widget_id, path, params))
        names = {p["paramName"] for p in widget.get("params", [])}
        for key in ("account_id", "basket_id"):
            if key in names:
                out.append((f"{widget_id}[{key}]", path, {**params, key: NON_DEMO}))
        if widget.get("type") == "chart":
            out.append((f"{widget_id}[raw]", path, {**params, "raw": "true"}))
    return out


def run() -> dict[str, Any]:
    """Call every widget variant in demo-only mode; return calls and headers."""
    # pylint: disable=import-outside-toplevel
    from fastapi.testclient import TestClient
    from openbb_portfolio_intel import widget_backend
    from openbb_portfolio_intel.widget_backend.main import app

    backend = Path(widget_backend.__file__ or "").parent
    widgets = json.loads((backend / "widgets.json").read_text(encoding="utf-8"))
    client = TestClient(app, raise_server_exceptions=False)
    CALLS.clear()  # import-time work is not a widget request
    responses: dict[str, Any] = {}
    for name, path, params in _requests(widgets):
        CURRENT["widget"] = name
        response = client.get(path, params=params)
        traces = None
        if response.status_code == 200 and "[raw]" not in name:
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and isinstance(body.get("data"), list):
                traces = len(body["data"])
        responses[name] = {
            "status": response.status_code,
            "state": response.headers.get("x-pi-data-state"),
            "source": response.headers.get("x-pi-data-source"),
            "traces": traces,
        }
    return {"calls": CALLS, "responses": responses, "mode": os.environ["PI_DEMO_MODE"]}


def main() -> int:
    """Install the seams, run, write JSON to the output path."""
    output = Path(sys.argv[2])
    install()
    output.write_text(json.dumps(run()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
