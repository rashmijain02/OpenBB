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
``loopback-dev`` refuses a non-loopback ``--host``.

Trust model (#1273 review SECURITY-1):

- launcher state (pid record, launch nonce, log) lives in a per-user
  directory created ``0700`` and checked for owner and mode (POSIX); symlinks
  are refused and files are opened ``O_NOFOLLOW`` where available;
- ``start`` hands the server a fresh per-launch nonce through its
  environment. ``start``, ``status`` and ``stop`` send the bearer token to
  ``/health/details`` only after the answering server proves the nonce with
  an HMAC over a random challenge, so a process that bound the port first
  never sees the token;
- ``stop`` signals only a pid that the proven server reports, that matches
  the record and that descends from the process ``start`` spawned. A
  backend still answering after the timeout is a failure and its record is
  kept.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
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
STATE_DIR_NAME = "openbb-pi-widget-backend"
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
UNAUTHORIZED: dict[str, Any] = {"status": "unauthorized"}
_MAX_TREE_DEPTH = 64

# Indirections so the POSIX ownership checks are testable on any OS.
_IS_POSIX = os.name != "nt"
_lstat = os.lstat
_islink = os.path.islink


class LauncherError(RuntimeError):
    """Raised when launcher state is unsafe to use."""


def _getuid() -> int:
    try:
        return int(os.getuid())
    except AttributeError:  # os.getuid is absent on Windows
        return -1


def _token(environ: Mapping[str, str]) -> str | None:
    return environ.get(operator_config.TOKEN_ENV, "").strip() or None


def _unauthorized(details: Mapping[str, Any] | None) -> bool:
    return details is not None and details.get("status") == UNAUTHORIZED["status"]


# ---------------------------------------------------------------------------
# Private per-user state
# ---------------------------------------------------------------------------


def _default_state_dir() -> Path:
    """Return the per-user state directory (never the shared temp dir)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / STATE_DIR_NAME


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` as ``0700`` and refuse it unless it is private to us.

    Refuses a symlink or non-directory everywhere; on POSIX also refuses a
    directory owned by another user or accessible to group/others. On
    Windows the per-user ``LOCALAPPDATA`` ACL provides the isolation.
    """
    if _islink(path):
        raise LauncherError(f"refusing state directory {path}: it is a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise LauncherError(f"refusing state directory {path}: it is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise LauncherError(f"refusing state directory {path}: not a directory")
    if _IS_POSIX:
        if info.st_uid != _getuid():
            raise LauncherError(
                f"refusing state directory {path}: wrong owner (uid {info.st_uid})"
            )
        if info.st_mode & 0o077:
            raise LauncherError(
                f"refusing state directory {path}: mode "
                f"{stat.S_IMODE(info.st_mode):o} is not 700"
            )
    return path


def _open_private(path: Path, flags: int) -> int:
    """Open ``path`` owner-only, refusing symlinks (``O_NOFOLLOW`` on POSIX)."""
    if _islink(path):
        raise LauncherError(f"refusing {path.name}: it is a symlink")
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(fd, 0o600)
    return fd


def _state_file(state_dir: Path, port: int) -> Path:
    return state_dir / f"backend-{port}.json"


def _read_state(state: Path) -> dict[str, Any] | None:
    if not state.exists() and not _islink(state):
        return None
    fd = _open_private(state, os.O_RDONLY)
    with os.fdopen(fd, "rb") as handle:
        try:
            record = json.loads(handle.read().decode("utf-8"))
        except ValueError:
            return None
    return record if isinstance(record, dict) else None


def _write_state(state: Path, record: Mapping[str, Any]) -> None:
    fd = _open_private(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps(record).encode("utf-8"))


def _prepare_state_dir(state_dir: Path) -> bool:
    try:
        ensure_private_dir(state_dir)
    except (LauncherError, OSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return False
    return True


# ---------------------------------------------------------------------------
# Addresses and HTTP probes
# ---------------------------------------------------------------------------


def _bare(host: str) -> str:
    return host.strip().strip("[]")


def _probe_host(host: str) -> str:
    """Return the loopback address of the same family as the bind host."""
    value = _bare(host)
    if value in ("", "0.0.0.0"):  # noqa: S104
        return DEFAULT_HOST
    if value == "::":
        return "::1"
    return value


def _probe_addresses(host: str) -> list[str]:
    """Addresses that reach a server bound to ``host`` (``::`` may be dual-stack)."""
    if _bare(host) == "::":
        return ["::1", DEFAULT_HOST]
    return [_probe_host(host)]


def _url(host: str, port: int, path: str) -> str:
    value = _bare(host)
    url_host = f"[{value}]" if ":" in value else value
    return f"http://{url_host}:{port}{path}"


def _port_in_use(host: str, port: int) -> bool:
    """Return True when anything accepts TCP connections for this bind."""
    for address in _probe_addresses(host):
        try:
            infos = socket.getaddrinfo(address, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for family, socktype, proto, _canon, sockaddr in infos:
            try:
                with socket.socket(family, socktype, proto) as sock:
                    sock.settimeout(1.0)
                    if sock.connect_ex(sockaddr) == 0:
                        return True
            except OSError:
                continue
    return False


def _get_json(request: urllib.request.Request, timeout: float) -> Any:
    # Fixed http://<loopback-or-host>:<port>/health... URL; no user scheme.
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _liveness(host: str, port: int, timeout: float = 5.0) -> bool | None:
    """GET the unauthenticated ``/health``; ``None`` when nothing answers."""
    request = urllib.request.Request(_url(host, port, "/health"))  # noqa: S310
    try:
        payload = _get_json(request, timeout)
    except (OSError, ValueError):
        return None
    return isinstance(payload, dict) and payload.get("status") == "ok"


def _verify_instance(
    host: str, port: int, nonce: str, timeout: float = 5.0
) -> bool | None:
    """Check that the server on ``port`` holds this launch's nonce.

    Returns ``True`` for a valid HMAC proof over a fresh random challenge,
    ``False`` when something answers without a valid proof, and ``None``
    when nothing answers. The nonce itself is never sent.
    """
    challenge = secrets.token_hex(16)
    request = urllib.request.Request(  # noqa: S310
        _url(host, port, "/health/instance"),
        headers={operator_config.CHALLENGE_HEADER: challenge},
    )
    try:
        payload = _get_json(request, timeout)
    except urllib.error.HTTPError:
        return False
    except ValueError:
        return False
    except OSError:
        return None
    proof = payload.get("proof") if isinstance(payload, dict) else None
    if not isinstance(proof, str):
        return False
    expected = operator_config.instance_proof(nonce, challenge)
    return hmac.compare_digest(proof, expected)


def fetch_details(
    host: str, port: int, token: str | None = None, timeout: float = 5.0
) -> dict[str, Any] | None:
    """GET ``/health/details`` with the bearer token.

    Call only after ``_verify_instance`` proved the server is ours. Returns
    the payload, ``UNAUTHORIZED`` on 401/403, or ``None`` when unreachable.
    """
    request = urllib.request.Request(_url(host, port, "/health/details"))  # noqa: S310
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        payload = _get_json(request, timeout)
    except urllib.error.HTTPError as exc:
        return dict(UNAUTHORIZED) if exc.code in (401, 403) else None
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("service") != SERVICE:
        return None
    return payload


# ---------------------------------------------------------------------------
# Process tree
# ---------------------------------------------------------------------------


def _windows_parents() -> dict[int, int]:
    if sys.platform != "win32":
        return {}
    # pylint: disable=import-outside-toplevel
    import ctypes
    from ctypes import wintypes

    class _Entry(ctypes.Structure):  # pylint: disable=too-few-public-methods
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return {}
    parents: dict[int, int] = {}
    try:
        entry = _Entry(dwSize=ctypes.sizeof(_Entry))
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _proc_parents(root: Path) -> dict[int, int]:
    parents: dict[int, int] = {}
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            parents[int(entry.name)] = int(text.rpartition(")")[2].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return parents


def _ps_parents() -> dict[int, int]:
    try:
        result = subprocess.run(  # noqa: S603
            ["ps", "-A", "-o", "pid=,ppid="],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    parents: dict[int, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parents[int(parts[0])] = int(parts[1])
    return parents


def _process_parents() -> dict[int, int]:
    """Return ``{pid: parent_pid}`` for every visible process."""
    if sys.platform == "win32":
        return _windows_parents()
    proc = Path("/proc")
    if proc.is_dir():
        return _proc_parents(proc)
    return _ps_parents()


def _in_tree(pid: int, root: int, parents: Mapping[int, int]) -> bool:
    """Return True when ``pid`` is ``root`` or one of its descendants."""
    current = pid
    for _ in range(_MAX_TREE_DEPTH):
        if current == root:
            return True
        parent = parents.get(current)
        if parent is None or parent == current or parent <= 0:
            return False
        current = parent
    return False


def _descendants(root: int, parents: Mapping[int, int]) -> list[int]:
    """Return ``root``'s descendants, parents before children."""
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        if pid != parent:
            children.setdefault(parent, []).append(pid)
    ordered: list[int] = []
    queue = list(children.get(root, []))
    while queue and len(ordered) < 4096:
        pid = queue.pop(0)
        if pid in ordered or pid == root:
            continue
        ordered.append(pid)
        queue.extend(children.get(pid, []))
    return ordered


def _terminate(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def _kill_tree(root: int) -> None:
    """Terminate ``root`` and every descendant, children first (CODE-1).

    On Windows the venv ``python.exe`` is a redirector, so the real server
    is a grandchild of the spawned process; it is found and killed here.
    """
    for pid in [*reversed(_descendants(root, _process_parents())), root]:
        try:
            _terminate(pid)
        except OSError:
            continue


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _uvicorn_run(**kwargs: Any) -> None:
    import uvicorn  # pylint: disable=import-outside-toplevel

    uvicorn.run(**kwargs)


def _spawn(command: list[str], log_path: Path, env: Mapping[str, str]) -> Any:
    """Start the backend detached from this terminal; output goes to a log."""
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "env": dict(env)}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        ) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    fd = _open_private(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    with os.fdopen(fd, "ab") as log:
        return subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
            command, stdout=log, stderr=subprocess.STDOUT, **kwargs
        )


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


def _wait_for_instance(
    proc: Any, host: str, port: int, nonce: str, timeout: float
) -> bool | None:
    deadline = time.monotonic() + timeout
    while True:
        verified = _verify_instance(host, port, nonce)
        if verified is not None or proc.poll() is not None:
            return verified
        if time.monotonic() >= deadline:
            return None
        time.sleep(1.0)


def _start_failure(proc: Any, message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    _kill_tree(proc.pid)
    return EXIT_FAIL


def cmd_start(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Start the backend in the background and wait for proven health."""
    if not _preflight_or_report(environ, args.host):
        return EXIT_CONFIG
    if not _prepare_state_dir(args.state_dir):
        return EXIT_CONFIG
    state = _state_file(args.state_dir, args.port)
    log_path = args.state_dir / f"backend-{args.port}.log"
    for path in (state, log_path):
        if _islink(path):
            sys.stderr.write(f"error: refusing {path.name}: it is a symlink\n")
            return EXIT_CONFIG
    if _port_in_use(args.host, args.port):
        sys.stderr.write(
            f"error: port {args.port} is already in use; run `status` or `stop`\n"
        )
        return EXIT_FAIL
    nonce = secrets.token_urlsafe(32)
    env = dict(os.environ)
    env[operator_config.INSTANCE_NONCE_ENV] = nonce
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
    proc = _spawn(command, log_path, env)
    probe = _probe_host(args.host)
    verified = _wait_for_instance(proc, probe, args.port, nonce, args.timeout)
    if verified is None:
        return _start_failure(
            proc,
            f"backend did not report healthy within {args.timeout:.0f}s; its "
            f"process tree was stopped; see the log at {log_path}",
        )
    if not verified:
        return _start_failure(
            proc,
            f"the server on port {args.port} did not prove this launch's nonce; "
            "the token was not sent and the launched process tree was stopped",
        )
    health = fetch_details(probe, args.port, _token(environ))
    pid = health.get("pid") if health and not _unauthorized(health) else None
    if not isinstance(pid, int):
        return _start_failure(
            proc, "/health/details refused the token or answered unexpectedly"
        )
    if not _in_tree(pid, proc.pid, _process_parents()):
        return _start_failure(
            proc,
            f"the backend reports pid {pid}, which is not in the launched "
            "process tree; refusing to record it",
        )
    _write_state(
        state,
        {
            "pid": pid,
            "launcher_pid": proc.pid,
            "host": args.host,
            "port": args.port,
            "nonce": nonce,
            "log": str(log_path),
        },
    )
    sys.stdout.write(f"started pid {pid} on {args.host}:{args.port}\n")
    ok, lines = _manifest_line(health.get("manifest") if health else None)
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_OK if ok else EXIT_FAIL


def _load_record(args: argparse.Namespace) -> tuple[bool, dict[str, Any] | None]:
    if not _prepare_state_dir(args.state_dir):
        return False, None
    try:
        return True, _read_state(_state_file(args.state_dir, args.port))
    except (LauncherError, OSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return False, None


def cmd_status(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Report health, auth mode, demo mode and manifests; never the token."""
    usable, record = _load_record(args)
    if not usable:
        return EXIT_CONFIG
    host = _probe_host(str(record.get("host", args.host)) if record else args.host)
    out = [f"Portfolio Intelligence widget backend - {host}:{args.port}"]
    token_set = _token(environ) is not None
    nonce = record.get("nonce") if record else None
    out.append(
        f"  launcher: started pid {record.get('pid')}"
        if record
        else "  launcher: no background start recorded"
    )
    out.append(
        f"  this shell: {operator_config.TOKEN_ENV} "
        f"{'is set' if token_set else 'is not set'}"
    )

    def _done(line: str) -> int:
        out.append(line)
        sys.stdout.write("\n".join(out) + "\n")
        return EXIT_FAIL

    if not isinstance(nonce, str):
        alive = _liveness(host, args.port)
        if not alive:
            return _done("  health: unreachable")
        return _done(
            "  health: ok (not started by this launcher; details not queried, "
            "token not sent)"
        )
    verified = _verify_instance(host, args.port, nonce)
    if verified is None:
        return _done("  health: unreachable")
    if not verified:
        return _done(
            "  health: a process answers but was not started by this launcher "
            "(instance proof failed); token not sent"
        )
    health = fetch_details(host, args.port, _token(environ))
    if health is None:
        return _done("  health: unreachable")
    if _unauthorized(health):
        return _done(
            "  health details: unauthorized - set the backend's "
            f"{operator_config.TOKEN_ENV} in this shell (or, in loopback-dev, "
            "query from loopback)"
        )
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


def _confirmed_pid(
    args: argparse.Namespace, record: Mapping[str, Any], host: str, token: str | None
) -> int | None:
    """Return the pid to signal, or ``None`` after reporting why not."""
    health = fetch_details(host, args.port, token)
    if _unauthorized(health):
        sys.stderr.write(
            "error: /health/details refused this shell's credentials, so the "
            f"backend's pid cannot be confirmed; set {operator_config.TOKEN_ENV} "
            "to the backend's token. Nothing was signalled.\n"
        )
        return None
    pid = record.get("pid")
    reported = health.get("pid") if health else None
    if not isinstance(pid, int) or reported != pid:
        sys.stderr.write(
            f"error: the backend on port {args.port} reports pid {reported}, not "
            f"the recorded pid {pid}; refusing to signal. Stop it where it was "
            "started.\n"
        )
        return None
    root = record.get("launcher_pid", pid)
    if not isinstance(root, int) or not _in_tree(pid, root, _process_parents()):
        sys.stderr.write(
            f"error: pid {pid} is not in the process tree this launcher started; "
            "refusing to signal.\n"
        )
        return None
    return pid


def cmd_stop(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Stop a backend started by ``start`` after confirming its identity."""
    usable, record = _load_record(args)
    if not usable:
        return EXIT_CONFIG
    if record is None:
        sys.stdout.write(f"no background start recorded for port {args.port}\n")
        return EXIT_OK
    state = _state_file(args.state_dir, args.port)
    host = _probe_host(str(record.get("host", DEFAULT_HOST)))
    nonce = record.get("nonce")
    verified = _verify_instance(host, args.port, nonce) if nonce else False
    if verified is None:
        state.unlink(missing_ok=True)
        sys.stdout.write(
            "backend not responding; removed the stale record, no process signalled\n"
        )
        return EXIT_OK
    if not verified:
        sys.stderr.write(
            f"error: the process on port {args.port} did not prove this launch's "
            "nonce; refusing to send the token or signal anything.\n"
        )
        return EXIT_FAIL
    pid = _confirmed_pid(args, record, host, _token(environ))
    if pid is None:
        return EXIT_FAIL
    _terminate(pid)
    deadline = time.monotonic() + args.timeout
    while _verify_instance(host, args.port, str(nonce), timeout=2.0) is not None:
        if time.monotonic() >= deadline:
            sys.stderr.write(
                f"error: the backend is still answering on port {args.port} "
                f"{args.timeout:.0f}s after SIGTERM to pid {pid}; the record is "
                "kept.\n"
            )
            return EXIT_FAIL
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
