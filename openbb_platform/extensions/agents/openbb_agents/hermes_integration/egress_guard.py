"""Loopback-only socket guard for real-path probes (#1339 T03).

Inside :func:`egress_guard`, every name lookup or connect to a non-loopback
host is recorded and refused. With ``refuse_live_ports=True`` loopback
connects to the live MySQL (3306) and LiteLLM proxy (4000) ports are refused
too, so a probe cannot touch a running service. The original socket
functions are restored on exit, even when the body raises.

Records are labels only (``dns:<host>``, ``connect:<host>[:<port>]``); no
payload is ever inspected.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

LIVE_PORTS: frozenset[int] = frozenset({3306, 4000})
_LOOPBACK_NAMES = frozenset({"localhost"})


class EgressRefused(ConnectionRefusedError):
    """Raised for a refused lookup or connect inside :func:`egress_guard`."""


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


@contextmanager
def egress_guard(*, refuse_live_ports: bool = False) -> Iterator[list[str]]:
    """Refuse and record non-loopback egress; yield the attempt list."""
    attempts: list[str] = []
    real_gai = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address: Any) -> None:
        if not isinstance(address, tuple):
            return  # AF_UNIX path: local by construction
        host, port = address[0], address[1]
        if not is_loopback(host):
            attempts.append(f"connect:{_label(host)}")
            raise EgressRefused("non-loopback connect refused by egress_guard")
        if refuse_live_ports and port in LIVE_PORTS:
            attempts.append(f"connect:{_label(host)}:{port}")
            raise EgressRefused("live service port refused by egress_guard")

    def guarded_gai(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_loopback(host):
            attempts.append(f"dns:{_label(host)}")
            raise socket.gaierror("non-loopback lookup refused by egress_guard")
        return real_gai(host, *args, **kwargs)

    def guarded_connect(self: socket.socket, address: Any) -> None:
        _check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        _check(address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = guarded_gai  # type: ignore[assignment]
    socket.socket.connect = guarded_connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign,assignment]
    try:
        yield attempts
    finally:
        socket.getaddrinfo = real_gai  # type: ignore[assignment]
        socket.socket.connect = real_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign,assignment]
