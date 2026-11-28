"""Worker guards (#1355 T03): no broker credentials, no live adapters, no network.

Pure module (no nautilus_trader). Installed by the worker entrypoint before
any request is served:

* :func:`refuse_broker_env` -- refuse to serve when broker-credential-shaped
  environment variables are present. Reports names only, never values.
* :func:`install_import_guard` -- a meta-path finder that refuses Nautilus
  live/exec clients (``nautilus_trader.live.*``, ``nautilus_trader.adapters.*``)
  and broker SDKs.
* :func:`install_socket_guard` -- an audit hook refusing every socket connect,
  bind, send and name lookup. The worker needs no network at all (stdio only),
  so loopback is refused too. Defence in depth: the container uses
  ``--network none`` and the native worker an owner-run firewall rule (L4).
* :class:`HeavyJobLock`, :class:`Deadline` -- one heavy job at a time and a
  hard wall-time bound for each job.
"""

from __future__ import annotations

import importlib.abc
import os
import re
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import IO, Any

from .nautilus_closure import NAUTILUS_IMPORT_CLOSURE
from .protocol import ErrorCode, ProtocolError

# Worker exit codes (the client observes them; 0 = shutdown or EOF).
EXIT_AUTH = 3
EXIT_EGRESS = 4
EXIT_IDLE = 5
EXIT_DEADLINE = 6

# Broker / venue / data-vendor prefixes used by Nautilus adapters and SDKs.
BROKER_ENV_PREFIXES = (
    "IB",
    "IBKR",
    "IBG",
    "TWS",
    "ALPACA",
    "APCA",
    "BINANCE",
    "BYBIT",
    "DATABENTO",
    "TARDIS",
    "BETFAIR",
    "OKX",
    "DYDX",
    "POLYMARKET",
)
_PREFIX_RE = re.compile("^(?:" + "|".join(BROKER_ENV_PREFIXES) + ")_")
# Generic secret-shaped name segments (``*_API_KEY``, ``*_SECRET``, ``*_TOKEN``...).
_GENERIC_RE = re.compile(
    r"(?:^|_)(?:API_?KEY(?:_ID)?|API_?SECRET|SECRET(?:_KEY)?|ACCESS_?KEY|"
    r"(?:ACCESS_|AUTH_|REFRESH_)?TOKEN|PASSWORD|PASSPHRASE|PRIVATE_?KEY|MNEMONIC)"
    r"(?:_|$)"
)
# Owner-reviewed names that match a pattern but carry no credential. Code
# constant on purpose: an env-controlled allowlist would defeat the scrub.
ENV_ALLOWLIST: frozenset[str] = frozenset()

# Modules the worker must never import: live/exec clients and broker SDKs.
BLOCKED_IMPORT_PREFIXES = (
    "nautilus_trader.live",
    "nautilus_trader.adapters",
    "ibapi",
    "ib_insync",
    "ib_async",
    "alpaca",
    "alpaca_trade_api",
    "binance",
    "pybit",
    "databento",
    "betfairlightweight",
    "py_clob_client",
    "dydx_v4_client",
    "okx",
    "tardis_client",
    "tardis_dev",
)
# Live/exec modules that stay blocked even if a future pin pulled them into the
# closure: the live node and every venue adapter (live data/exec clients).
ALWAYS_BLOCKED_PREFIXES = ("nautilus_trader.live.node", "nautilus_trader.adapters")


def _under(name: str, prefixes: Iterable[str]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def closure_exemptions(closure: Iterable[str]) -> frozenset[str]:
    """Exact closure names under a blocked prefix, never an adapter or the node.

    ``BacktestEngine`` imports ``live.{data,execution,risk}_engine`` at module
    level through ``system.kernel``; :mod:`.nautilus_closure` holds the pinned
    list, its source commit and method. T01-L / T03-L confirm on the wheel.
    """
    return frozenset(
        name
        for name in closure
        if _under(name, BLOCKED_IMPORT_PREFIXES)
        and not _under(name, ALWAYS_BLOCKED_PREFIXES)
    )


# Exact module names (no prefixes) the import guard lets through.
IMPORT_EXEMPT = closure_exemptions(NAUTILUS_IMPORT_CLOSURE)

_SOCKET_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
    }
)


class GuardError(ProtocolError):
    """A guard refusal; ``reason`` names the specific check."""

    def __init__(self, code: ErrorCode, reason: str, message: str):
        super().__init__(code, f"{reason}: {message}")
        self.reason = reason


class BlockedImportError(ImportError):
    """Raised by the import guard for a live adapter or broker SDK."""


class EgressBlocked(PermissionError):
    """Raised by the socket audit hook: the worker has no network."""


# --- environment ------------------------------------------------------------------


def broker_env_names(
    env: Mapping[str, str], allow: Iterable[str] = ENV_ALLOWLIST
) -> list[str]:
    """Return the sorted names (never values) of credential-shaped variables."""
    allowed = {a.upper() for a in allow}
    hits = []
    for name in env:
        upper = name.upper()
        if upper in allowed:
            continue
        if _PREFIX_RE.match(upper) or _GENERIC_RE.search(upper):
            hits.append(name)
    return sorted(hits)


def refuse_broker_env(
    env: Mapping[str, str], allow: Iterable[str] = ENV_ALLOWLIST
) -> None:
    """Raise ``egress`` naming every credential-shaped variable present."""
    names = broker_env_names(env, allow)
    if names:
        raise GuardError(
            ErrorCode.EGRESS,
            "broker_env",
            "credential-shaped environment variables present: " + ", ".join(names),
        )


# --- imports ----------------------------------------------------------------------


def is_blocked_module(name: str) -> bool:
    """Return True when ``name`` is a live adapter / broker SDK module."""
    if name in IMPORT_EXEMPT:
        return False
    return any(name == p or name.startswith(p + ".") for p in BLOCKED_IMPORT_PREFIXES)


class LiveImportBlocker(importlib.abc.MetaPathFinder):
    """Meta-path finder refusing :data:`BLOCKED_IMPORT_PREFIXES`."""

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102
        del path, target  # the meta-path protocol passes them; unused here
        if is_blocked_module(fullname):
            raise BlockedImportError(f"{fullname} is blocked in the backtest worker")


def install_import_guard() -> LiveImportBlocker:
    """Install the blocker first on ``sys.meta_path``; refuse if one is loaded."""
    loaded = sorted(m for m in list(sys.modules) if is_blocked_module(m))
    if loaded:
        raise GuardError(
            ErrorCode.EGRESS, "live_module_loaded", "blocked modules already loaded"
        )
    for finder in sys.meta_path:
        if isinstance(finder, LiveImportBlocker):
            return finder
    blocker = LiveImportBlocker()
    sys.meta_path.insert(0, blocker)
    return blocker


# --- sockets ----------------------------------------------------------------------

_socket_guard_installed = threading.Event()


def _socket_audit(event: str, _args: tuple[Any, ...]) -> None:
    if event in _SOCKET_EVENTS:
        raise EgressBlocked(f"{event} refused: the backtest worker has no network")


def install_socket_guard() -> None:
    """Install the socket audit hook once (audit hooks cannot be removed)."""
    if not _socket_guard_installed.is_set():
        sys.addaudithook(_socket_audit)
        _socket_guard_installed.set()


def install_runtime_guards() -> None:
    """Import and socket guards; the env check runs once the key is known."""
    install_import_guard()
    install_socket_guard()


# --- bounds -----------------------------------------------------------------------


def _lock_fd(fh: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt  # pylint: disable=import-outside-toplevel

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl  # pylint: disable=import-outside-toplevel

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]


def _unlock_fd(fh: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt  # pylint: disable=import-outside-toplevel

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl  # pylint: disable=import-outside-toplevel

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


class HeavyJobLock:
    """Non-blocking OS file lock: one heavy job at a time across workers.

    The OS releases the lock when the holder dies, so a killed worker never
    leaves a stale lock behind.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._fh: IO[bytes] | None = None

    def __enter__(self) -> HeavyJobLock:
        """Acquire or raise ``process`` (busy)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+b")  # pylint: disable=consider-using-with
        try:
            _lock_fd(fh)
        except OSError as exc:
            fh.close()
            raise GuardError(
                ErrorCode.PROCESS, "busy", "another heavy job is running"
            ) from exc
        self._fh = fh
        return self

    def __exit__(self, *_exc) -> None:
        """Release the lock."""
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                _unlock_fd(fh)
            finally:
                fh.close()


def _hard_exit() -> None:  # pragma: no cover - terminates the process
    os._exit(EXIT_DEADLINE)  # pylint: disable=protected-access


class Deadline:
    """Wall-time bound: ``on_expire`` (default: hard process exit) after ``seconds``."""

    def __init__(self, seconds: float, on_expire: Callable[[], None] = _hard_exit):
        self._timer = threading.Timer(seconds, on_expire)
        self._timer.daemon = True

    def __enter__(self) -> Deadline:
        """Start the timer."""
        self._timer.start()
        return self

    def __exit__(self, *_exc) -> None:
        """Cancel the timer."""
        self._timer.cancel()
