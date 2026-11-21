"""Hermetic subprocess probe for Workspace endpoint contract tests (#1266).

Run only by ``test_workspace_endpoint_contracts.py`` with a scrubbed
environment whose HOME/USERPROFILE point at a temp dir, so every
import-time path (OpenBB settings, credentials, ``.env``, home databases)
binds to that temp dir. Before importing the backend it disables dotenv
loading, refuses every DNS lookup and every real socket connect (asyncio's
internal socketpair excepted), and forces the selector event loop so async
connects also pass through the guarded ``socket.connect``.

Usage: ``python _workspace_endpoint_probe.py (probe|selftest) OUTPUT.json``
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_SOCKETPAIR = socket.socketpair
_REAL_GETADDRINFO = socket.getaddrinfo
_PAIRING = threading.local()


def _socketpair(*args: Any, **kwargs: Any) -> Any:
    _PAIRING.active = True
    try:
        return _REAL_SOCKETPAIR(*args, **kwargs)
    finally:
        _PAIRING.active = False


def _guard(real: Any) -> Any:
    def _connect(sock: socket.socket, address: Any) -> Any:
        if not getattr(_PAIRING, "active", False):
            raise OSError("network blocked in contract tests: socket connect")
        return real(sock, address)

    return _connect


def _no_dns(host: Any, *args: Any, **kwargs: Any) -> Any:
    if host != "testserver":
        raise OSError(f"network blocked in contract tests: {host}")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def _install_guards() -> None:
    socket.socketpair = _socketpair
    socket.socket.connect = _guard(_REAL_CONNECT)  # type: ignore[method-assign]
    socket.socket.connect_ex = _guard(_REAL_CONNECT_EX)  # type: ignore[method-assign]
    socket.getaddrinfo = _no_dns
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )
    import dotenv  # pylint: disable=import-outside-toplevel
    import dotenv.main  # pylint: disable=import-outside-toplevel

    def _no_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

    dotenv.load_dotenv = _no_dotenv
    dotenv.main.load_dotenv = _no_dotenv


def _blocked(action: Any) -> bool:
    try:
        action()
    except OSError as exc:
        return "blocked" in str(exc)
    return False


async def _async_connect() -> None:
    await asyncio.open_connection("127.0.0.1", 9)


def _selftest() -> dict[str, Any]:
    # pylint: disable=import-outside-toplevel
    from openbb_core.app import constants

    home = Path(os.environ["HOME"]).resolve()

    def _sync_connect() -> None:
        with socket.socket() as sock:
            sock.connect(("127.0.0.1", 3306))

    return {
        "sync_loopback_blocked": _blocked(_sync_connect),
        "async_loopback_blocked": _blocked(lambda: asyncio.run(_async_connect())),
        "dns_blocked": _blocked(lambda: socket.getaddrinfo("localhost", 3306)),
        "home_isolated": Path.home().resolve() == home,
        "openbb_settings_isolated": home
        in Path(constants.USER_SETTINGS_PATH).resolve().parents,
        "dotenv_disabled": __import__("dotenv").load_dotenv() is False,
    }


def _probe() -> dict[str, list[Any]]:
    # pylint: disable=import-outside-toplevel
    from fastapi.testclient import TestClient
    from openbb_portfolio_intel import widget_backend
    from openbb_portfolio_intel.widget_backend.main import app

    backend = Path(widget_backend.__file__ or "").parent
    widgets = json.loads((backend / "widgets.json").read_text(encoding="utf-8"))
    client = TestClient(app, raise_server_exceptions=False)
    results: dict[str, list[Any]] = {}
    for widget_id, widget in widgets.items():
        params = {
            p["paramName"]: p["value"]
            for p in widget.get("params", [])
            if p.get("value") not in (None, "")
        }
        response = client.get("/" + widget["endpoint"].lstrip("/"), params=params)
        # Status, body, and the #1269 per-request provenance headers.
        results[widget_id] = [
            response.status_code,
            response.text,
            response.headers.get("x-pi-data-state"),
            response.headers.get("x-pi-data-source"),
        ]
    return results


def main() -> int:
    """Install guards, run the requested mode, write JSON to the output path."""
    mode, output = sys.argv[1], Path(sys.argv[2])
    _install_guards()
    result = _selftest() if mode == "selftest" else _probe()
    output.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
