"""Loopback-only socket guard for tests and real-path probes (#1339 T03).

This is test / probe scaffolding, not a production egress boundary. Inside
:func:`egress_guard`, name lookups (``getaddrinfo``, ``gethostbyname``,
``gethostbyname_ex``), connects (``connect``, ``connect_ex``) and datagram
sends (``sendto``, ``sendmsg``) to a non-loopback host are recorded and
refused. With ``refuse_live_ports=True`` loopback connects and sends to the
live MySQL (3306) and LiteLLM proxy (4000) ports are refused too, so a probe
cannot touch a running service.

It patches Python-level ``socket`` functions in this process only. It does
not cover subprocesses, code that calls the raw ``_socket`` module, native
extensions, or asyncio's Proactor ``ConnectEx`` path on Windows.

Nested and overlapping (multi-threaded) uses are safe: the originals are
captured once under a lock, every active guard records and applies its own
policy, and the originals are restored when the last guard exits, even when
a body raises.

Records are labels only (``dns:<host>``, ``connect:<host>[:<port>]``,
``send:<host>[:<port>]``); no payload is ever inspected.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

LIVE_PORTS: frozenset[int] = frozenset({3306, 4000})
_LOOPBACK_NAMES = frozenset({"localhost"})


class EgressRefused(ConnectionRefusedError):
    """Raised for a refused connect or send inside :func:`egress_guard`."""


def is_loopback(host: object) -> bool:
    """Return True for ``localhost`` or a literal loopback IPv4/IPv6 address."""
    if host is None:
        return True  # getaddrinfo(None, ...) resolves the local wildcard
    text = host.decode() if isinstance(host, bytes) else str(host)
    if text.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _label(host: object) -> str:
    text = host.decode(errors="replace") if isinstance(host, bytes) else str(host)
    return "".join(ch for ch in text if ch.isprintable())[:128]


@dataclass(eq=False)
class _Guard:
    refuse_live_ports: bool
    attempts: list[str] = field(default_factory=list)


_LOCK = threading.RLock()
_ACTIVE: list[_Guard] = []
_ORIGINALS: dict[str, Any] = {}
_SOCKET_FUNCS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex")
_METHODS = ("connect", "connect_ex", "sendto", "sendmsg")


def _guards() -> list[_Guard]:
    with _LOCK:
        return list(_ACTIVE)


def _check_lookup(host: Any) -> None:
    if is_loopback(host):
        return
    guards = _guards()
    for guard in guards:
        guard.attempts.append(f"dns:{_label(host)}")
    if guards:
        raise socket.gaierror("non-loopback lookup refused by egress_guard")


def _check_address(kind: str, address: Any) -> None:
    if not isinstance(address, tuple) or len(address) < 2:
        return  # AF_UNIX path or no address: local by construction
    host, port = address[0], address[1]
    refused = False
    for guard in _guards():
        if not is_loopback(host):
            guard.attempts.append(f"{kind}:{_label(host)}")
            refused = True
        elif guard.refuse_live_ports and port in LIVE_PORTS:
            guard.attempts.append(f"{kind}:{_label(host)}:{port}")
            refused = True
    if refused:
        raise EgressRefused(f"{kind} refused by egress_guard")


def _guarded_lookup(name: str) -> Any:
    real = _ORIGINALS[name]

    def guarded(host: Any, *args: Any, **kwargs: Any) -> Any:
        _check_lookup(host)
        return real(host, *args, **kwargs)

    return guarded


def _guarded_connect(name: str) -> Any:
    real = _ORIGINALS[name]

    def guarded(self: socket.socket, address: Any) -> Any:
        _check_address("connect", address)
        return real(self, address)

    return guarded


def _guarded_sendto(self: socket.socket, data: Any, *args: Any) -> int:
    # sendto(data, address) or sendto(data, flags, address)
    if args:
        _check_address("send", args[-1])
    return _ORIGINALS["sendto"](self, data, *args)


def _guarded_sendmsg(self: socket.socket, buffers: Any, *args: Any) -> int:
    # sendmsg(buffers[, ancdata[, flags[, address]]])
    if len(args) >= 3:
        _check_address("send", args[2])
    return _ORIGINALS["sendmsg"](self, buffers, *args)


def _install() -> None:
    for name in _SOCKET_FUNCS:
        _ORIGINALS[name] = getattr(socket, name)
    for name in _METHODS:
        if hasattr(socket.socket, name):
            _ORIGINALS[name] = getattr(socket.socket, name)
    for name in _SOCKET_FUNCS:
        setattr(socket, name, _guarded_lookup(name))
    for name in ("connect", "connect_ex"):
        setattr(socket.socket, name, _guarded_connect(name))
    setattr(socket.socket, "sendto", _guarded_sendto)
    if "sendmsg" in _ORIGINALS:  # not on every platform
        setattr(socket.socket, "sendmsg", _guarded_sendmsg)


def _restore() -> None:
    for name in _SOCKET_FUNCS:
        setattr(socket, name, _ORIGINALS.pop(name))
    for name in _METHODS:
        if name in _ORIGINALS:
            setattr(socket.socket, name, _ORIGINALS.pop(name))


@contextmanager
def egress_guard(*, refuse_live_ports: bool = False) -> Iterator[list[str]]:
    """Refuse and record non-loopback egress; yield the attempt list."""
    guard = _Guard(refuse_live_ports=refuse_live_ports)
    with _LOCK:
        if not _ACTIVE:
            _install()
        _ACTIVE.append(guard)
    try:
        yield guard.attempts
    finally:
        with _LOCK:
            _ACTIVE.remove(guard)
            if not _ACTIVE:
                _restore()
