"""F2 (#1342): the sidecar acts as the live MCP server's own story principal.

Temporary credentials only: the settings file path points into ``tmp_path`` and
the secret is generated per test, so no real credential is read or printed.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import ast
import inspect
import json
import secrets

import pytest
from openbb_agents.hermes_integration.web import sidecar
from openbb_agents.hermes_integration.workflow_admit import in_process_principal
from openbb_mcp_server.app.app import story_principal_for
from openbb_mcp_server.service.mcp_service import MCPService


@pytest.fixture
def no_settings_file(tmp_path, monkeypatch):
    """Point the MCP settings file at an empty temp dir; clear the auth env."""
    monkeypatch.setattr(MCPService, "MCP_SETTINGS_PATH", tmp_path / "mcp_settings.json")
    monkeypatch.delenv("OPENBB_MCP_SERVER_AUTH", raising=False)
    return tmp_path / "mcp_settings.json"


def test_principal_is_the_mcp_servers_own(no_settings_file, monkeypatch):
    """Same credentials, same derivation: the server's story principal exactly."""
    secret = secrets.token_hex(16)
    monkeypatch.setenv("OPENBB_MCP_SERVER_AUTH", json.dumps(["hfp-test", secret]))
    principal = sidecar.live_story_principal()
    assert principal == story_principal_for(("hfp-test", secret))
    assert principal != in_process_principal("hfp-test")
    assert secret not in principal


def test_principal_from_the_settings_file(no_settings_file):
    """The server's other source, ``mcp_settings.json``, pairs the same way."""
    secret = secrets.token_hex(16)
    no_settings_file.write_text(
        json.dumps({"server_auth": ["hfp-file", secret]}), encoding="utf-8"
    )
    assert sidecar.live_story_principal() == story_principal_for(("hfp-file", secret))


@pytest.mark.parametrize("auth", [None, '["hfp-test", "   "]', '["only-one"]'])
def test_unpaired_fails_closed_before_binding(
    no_settings_file, monkeypatch, capsys, auth
):
    """No usable credentials: exit 4 ``principal_unpaired``; nothing binds."""
    if auth is not None:
        monkeypatch.setenv("OPENBB_MCP_SERVER_AUTH", auth)

    def no_bind(*_a, **_k):
        raise AssertionError("bound a socket without a paired principal")

    monkeypatch.setattr(sidecar, "bind_loopback", no_bind)
    with pytest.raises(sidecar.PairingError) as caught:
        sidecar.live_story_principal()
    assert caught.value.code == "principal_unpaired"
    assert sidecar.main(["--port", "0"]) == 4
    assert sidecar.main(["--check"]) == 4
    assert "principal_unpaired" in capsys.readouterr().err


def test_check_passes_and_never_prints_the_secret(
    no_settings_file, monkeypatch, capsys
):
    """``--check`` with temp credentials prints only ``pairing_ok``."""
    secret = secrets.token_hex(16)
    monkeypatch.setenv("OPENBB_MCP_SERVER_AUTH", json.dumps(["hfp-test", secret]))
    assert sidecar.main(["--check"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "pairing_ok"
    assert secret not in out.out + out.err


def test_main_takes_its_principal_from_live_story_principal():
    """AST: ``main`` calls ``live_story_principal`` and no constant-secret helper."""
    tree = ast.parse(inspect.getsource(sidecar))
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert "in_process_principal" not in names
    assert "_IN_PROCESS_SECRET" not in names
    main = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    calls = {
        n.func.id
        for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "live_story_principal" in calls


FAKE_SECRET = "FAKESECRET123"  # noqa: S105


def _assert_no_leak(capsys, caplog):
    out = capsys.readouterr()
    assert FAKE_SECRET not in out.out + out.err
    assert FAKE_SECRET not in caplog.text
    assert all(FAKE_SECRET not in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "auth",
    [
        f"FAKEUSER:{FAKE_SECRET}",
        json.dumps(["FAKEUSER", FAKE_SECRET, "extra"]),
        json.dumps(["FAKEUSER"]),
        json.dumps({"user": "FAKEUSER", "pw": FAKE_SECRET}),
    ],
)
def test_malformed_env_server_auth_does_not_leak(
    no_settings_file, monkeypatch, capsys, caplog, auth
):
    """A malformed env ``server_auth`` fails closed without echoing its value."""
    monkeypatch.setenv("OPENBB_MCP_SERVER_AUTH", auth)
    caplog.set_level("DEBUG")
    with pytest.raises(sidecar.PairingError) as caught:
        sidecar.live_story_principal()
    assert caught.value.code == "principal_unpaired"
    assert FAKE_SECRET not in str(caught.value)
    assert sidecar.main(["--check"]) == 4
    _assert_no_leak(capsys, caplog)


@pytest.mark.parametrize(
    "auth",
    [
        ["FAKEUSER", FAKE_SECRET, "extra"],
        ["FAKEUSER"],
        {"user": "FAKEUSER", "pw": FAKE_SECRET},
    ],
)
def test_malformed_file_server_auth_does_not_leak(
    no_settings_file, capsys, caplog, auth
):
    """A malformed ``server_auth`` in the settings file fails closed, no leak."""
    no_settings_file.write_text(json.dumps({"server_auth": auth}), encoding="utf-8")
    caplog.set_level("DEBUG")
    with pytest.raises(sidecar.PairingError) as caught:
        sidecar.live_story_principal()
    assert caught.value.code == "principal_unpaired"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert sidecar.main(["--check"]) == 4
    _assert_no_leak(capsys, caplog)
