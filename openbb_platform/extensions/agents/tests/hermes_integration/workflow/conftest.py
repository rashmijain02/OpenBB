"""Hermetic fixtures for the workflow-manifest tests (#1340).

Network denied, home directories moved to a temp root, run store in tmp. All
data is synthetic; nothing here reads a notebook, a credential or a service.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PKG = Path(__file__).resolve().parents[3] / "openbb_agents"
SHIPPED = PKG / "hermes_integration" / "workflows"
CATALOG = PKG / "notebook_guide" / "stories" / "capability_catalog.json"


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    """Fail any non-loopback connection (asyncio loops need a loopback socketpair)."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def _check(address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise AssertionError("workflow tests must not leave the loopback interface")

    def connect(self, address):
        _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        _check(address)
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point home lookups and the story run store at a temporary root."""
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(tmp_path / "runs.sqlite"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def load_fixture(name: str) -> dict:
    """Return one fixture workflow document."""
    return json.loads((FIXTURES / f"{name}.workflow.json").read_text("utf-8"))


@pytest.fixture
def shipped_document() -> dict:
    """The shipped synthetic workflow as a mutable copy."""
    path = SHIPPED / "synthetic.concentration_review.workflow.json"
    return copy.deepcopy(json.loads(path.read_text("utf-8")))


@pytest.fixture
def live_tools(shipped_document) -> dict[str, str]:
    """Live ``server:tool`` -> hash that exactly matches the shipped pins."""
    return {
        f"{pin['server']}:{pin['tool']}": pin["schema_sha256"]
        for pin in shipped_document["capabilities"].values()
    }
