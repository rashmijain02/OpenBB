"""Shared fixtures for the Hermes integration tests (#1338, #1339).

Every test runs with HOME and HERMES_HOME moved to a temporary root and with
non-loopback network connections refused. All data is synthetic.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Synthetic private-shaped sentinels; they must never appear in any output.
SENTINELS = {
    "account": "ZZ-000000001",
    "amount": "$4,242,424.42",
    "name": "Sentinel Q. Owner",
}

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# The live MySQL and LiteLLM proxy ports: never contacted, whatever a test resolves.
_LIVE_PORTS = {3306, 4000}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point HOME/HERMES_HOME at a temp dir so no real state is touched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HERMES_HOME", str(home / "hermes"))
    return home


@pytest.fixture(autouse=True)
def deny_non_loopback(monkeypatch):
    """Refuse any socket connection that is not to a loopback address."""
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise OSError(f"non-loopback connect refused in tests: {host!r}")
        if isinstance(address, tuple) and address[1] in _LIVE_PORTS:
            raise ConnectionRefusedError(
                f"live service port refused in tests: {address[1]}"
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
