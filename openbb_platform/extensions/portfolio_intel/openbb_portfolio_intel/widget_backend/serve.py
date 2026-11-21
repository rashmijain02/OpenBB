"""Supported cross-platform launcher for the Workspace backend (#1273).

Usage (any OS, from an environment where ``openbb_portfolio_intel`` is
installed)::

    python -m openbb_portfolio_intel.widget_backend.serve run     # foreground
    python -m openbb_portfolio_intel.widget_backend.serve start   # background
    python -m openbb_portfolio_intel.widget_backend.serve status
    python -m openbb_portfolio_intel.widget_backend.serve stop

Configuration comes only from the environment (never from arguments, so a
token never appears in a process listing): ``PI_WIDGET_BACKEND_AUTH_MODE``,
``PI_WIDGET_BACKEND_TOKEN``, ``PI_DEMO_MODE`` and
``PI_WIDGET_BACKEND_ALLOWED_ORIGINS``. Every command validates them first;
``loopback-dev`` refuses a non-loopback ``--host``. ``status`` reports health,
auth mode, demo mode and the manifest verdict from the authenticated
``/health/details`` (sending the token only as a bearer header) and never
prints the token. ``stop`` signals only the process whose pid the running
backend itself reports.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openbb_portfolio_intel.widget_backend import operator_config

APP_TARGET = "openbb_portfolio_intel.widget_backend.main:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6120
SERVICE = "portfolio-intel-widget-backend"
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
UNAUTHORIZED: dict[str, Any] = {"status": "unauthorized"}


def _token(environ: Mapping[str, str]) -> str | None:
    return environ.get(operator_config.TOKEN_ENV, "").strip() or None


def _unauthorized(details: Mapping[str, Any] | None) -> bool:
    return details is not None and details.get("status") == UNAUTHORIZED["status"]


def _default_state_dir() -> Path:
    return Path(tempfile.gettempdir()) / "openbb-pi-widget-backend"


def _state_file(state_dir: Path, port: int) -> Path:
    return state_dir / f"backend-{port}.json"


def _probe_host(host: str) -> str:
    """Return the address status/stop should call for a bind host."""
    return DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host  # noqa: S104


def fetch_details(
    host: str, port: int, token: str | None = None, timeout: float = 5.0
) -> dict[str, Any] | None:
    """GET ``/health/details`` with the bearer token.

    Returns the payload, ``UNAUTHORIZED`` on 401/403, or ``None`` when the
    backend is unreachable. The token is sent only in the header.
    """
    url_host = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(  # noqa: S310
        f"http://{url_host}:{port}/health/details"
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # Fixed http://<host>:<port>/health/details URL; no user-supplied scheme.
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return dict(UNAUTHORIZED) if exc.code in (401, 403) else None
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("service") != SERVICE:
        return None
    return payload


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((_probe_host(host), port)) == 0


def _uvicorn_run(**kwargs: Any) -> None:
    import uvicorn  # pylint: disable=import-outside-toplevel

    uvicorn.run(**kwargs)


def _spawn(command: list[str], log_path: Path) -> Any:
    """Start the backend detached from this terminal; output goes to a log."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        ) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as log:  # noqa: PTH123
        return subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
            command, stdout=log, stderr=subprocess.STDOUT, **kwargs
        )


def _terminate(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def _preflight_or_report(environ: Mapping[str, str], host: str) -> bool:
    errors, warnings = operator_config.preflight(environ, host)
    for warning in warnings:
        sys.stderr.write(f"warning: {warning}\n")
    for error in errors:
        sys.stderr.write(f"error: {error}\n")
    return not errors


def _manifest_line(manifest: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    if not isinstance(manifest, Mapping):
        return False, ["  manifests: unknown (no report from the backend)"]
    if manifest.get("error"):
        return False, [f"  manifests: INVALID - {manifest['error']}"]
    ok = bool(manifest.get("ok"))
    lines = [
        f"  manifests: {'ok' if ok else 'INVALID'} - {manifest.get('widgets')} "
        f"widgets, {manifest.get('apps')} apps, {manifest.get('issues')} issue(s), "
        f"{manifest.get('recorded_debt')} recorded debt"
    ]
    lines += [f"    new: {item}" for item in manifest.get("new") or []]
    lines += [
        f"    stale baseline: {item}" for item in manifest.get("stale_baseline") or []
    ]
    if not ok:
        lines.append(
            "    run: python scripts/validate_portfolio_workspace_manifests.py"
        )
    return ok, lines


def cmd_run(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Run the backend in the foreground (Ctrl+C stops it)."""
    if not _preflight_or_report(environ, args.host):
        return EXIT_CONFIG
    _uvicorn_run(app=APP_TARGET, host=args.host, port=args.port, reload=args.reload)
    return EXIT_OK


def cmd_start(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Start the backend in the background and wait for ``/health/details``."""
    if not _preflight_or_report(environ, args.host):
        return EXIT_CONFIG
    state = _state_file(args.state_dir, args.port)
    if _port_in_use(args.host, args.port):
        sys.stderr.write(
            f"error: port {args.port} is already in use; run `status` or `stop`\n"
        )
        return EXIT_FAIL
    log_path = args.state_dir / f"backend-{args.port}.log"
    command = [
        sys.executable,
        "-m",
        "openbb_portfolio_intel.widget_backend.serve",
        "run",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    proc = _spawn(command, log_path)
    probe = _probe_host(args.host)
    deadline = time.monotonic() + args.timeout
    health = None
    while time.monotonic() < deadline:
        health = fetch_details(probe, args.port, _token(environ))
        if health is not None or proc.poll() is not None:
            break
        time.sleep(1.0)
    if health is None or _unauthorized(health):
        sys.stderr.write(
            f"error: backend did not report healthy within {args.timeout:.0f}s; "
            f"see the log at {log_path}\n"
        )
        if proc.poll() is None:
            proc.terminate()
        return EXIT_FAIL
    args.state_dir.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "pid": health.get("pid"),
                "launcher_pid": proc.pid,
                "host": args.host,
                "port": args.port,
                "log": str(log_path),
            }
        ),
        encoding="utf-8",
    )
    sys.stdout.write(f"started pid {health.get('pid')} on {args.host}:{args.port}\n")
    ok, lines = _manifest_line(health.get("manifest"))
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_OK if ok else EXIT_FAIL


def _read_state(state: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def cmd_status(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Report health, auth mode, demo mode and manifests; never the token."""
    record = _read_state(_state_file(args.state_dir, args.port))
    host = _probe_host(record.get("host", args.host) if record else args.host)
    health = fetch_details(host, args.port, _token(environ))
    out = [f"Portfolio Intelligence widget backend - {host}:{args.port}"]
    if record:
        out.append(f"  launcher: started pid {record.get('pid')}")
    else:
        out.append("  launcher: no background start recorded")
    token_set = bool(environ.get(operator_config.TOKEN_ENV, "").strip())
    out.append(
        f"  this shell: {operator_config.TOKEN_ENV} "
        f"{'is set' if token_set else 'is not set'}"
    )
    if health is None:
        out.append("  health: unreachable")
        sys.stdout.write("\n".join(out) + "\n")
        return EXIT_FAIL
    if _unauthorized(health):
        out.append(
            "  health details: unauthorized - set the backend's "
            f"{operator_config.TOKEN_ENV} in this shell (or, in loopback-dev, "
            "query from loopback)"
        )
        sys.stdout.write("\n".join(out) + "\n")
        return EXIT_FAIL
    out += [
        f"  health: {health.get('status')} (pid {health.get('pid')})",
        f"  auth mode: {health.get('auth_mode')}",
        f"  demo mode: {health.get('demo_mode')}",
        f"  allowed origins: {', '.join(health.get('allowed_origins') or [])}",
    ]
    ok, lines = _manifest_line(health.get("manifest"))
    out += lines
    sys.stdout.write("\n".join(out) + "\n")
    return EXIT_OK if ok and health.get("status") == "ok" else EXIT_FAIL


def cmd_stop(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Stop a backend started by ``start`` after confirming its pid."""
    state = _state_file(args.state_dir, args.port)
    record = _read_state(state)
    if record is None:
        sys.stdout.write(f"no background start recorded for port {args.port}\n")
        return EXIT_OK
    host = _probe_host(str(record.get("host", DEFAULT_HOST)))
    token = _token(environ)
    health = fetch_details(host, args.port, token)
    if _unauthorized(health):
        sys.stderr.write(
            "error: /health/details refused this shell's credentials, so the "
            f"backend's pid cannot be confirmed; set {operator_config.TOKEN_ENV} "
            "to the backend's token. Nothing was signalled.\n"
        )
        return EXIT_FAIL
    if health is None:
        state.unlink(missing_ok=True)
        sys.stdout.write(
            "backend not responding; removed the stale record, no process signalled\n"
        )
        return EXIT_OK
    pid = record.get("pid")
    if not isinstance(pid, int) or health.get("pid") != pid:
        sys.stderr.write(
            f"error: the backend on port {args.port} reports pid "
            f"{health.get('pid')}, not the recorded pid {pid}; refusing to signal. "
            "Stop it where it was started.\n"
        )
        return EXIT_FAIL
    _terminate(pid)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline and fetch_details(host, args.port, token):
        time.sleep(0.5)
    state.unlink(missing_ok=True)
    sys.stdout.write(f"stopped pid {pid}\n")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Return the launcher's argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m openbb_portfolio_intel.widget_backend.serve",
        description="Run, start, stop or inspect the Portfolio Intelligence "
        "Workspace backend.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (
        ("run", "run in the foreground"),
        ("start", "start in the background and wait for health"),
        ("status", "report health, auth mode, demo mode and manifests"),
        ("stop", "stop a backend started with `start`"),
    ):
        cmd = sub.add_parser(name, help=helptext)
        cmd.add_argument("--host", default=DEFAULT_HOST)
        cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
        cmd.add_argument("--state-dir", type=Path, default=_default_state_dir())
        cmd.add_argument(
            "--timeout",
            type=float,
            default=180.0 if name == "start" else 15.0,
            help="seconds to wait for health (start) or shutdown (stop)",
        )
        if name == "run":
            cmd.add_argument("--reload", action="store_true")
    return parser


_COMMANDS = {
    "run": cmd_run,
    "start": cmd_start,
    "status": cmd_status,
    "stop": cmd_stop,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    args = build_parser().parse_args(argv)
    return _COMMANDS[args.command](args, os.environ)


if __name__ == "__main__":
    sys.exit(main())
