"""Transport security: loopback default, bearer token off-loopback, import guard (#1299)."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest
from openbb_fmp_cached_mcp.app import BindError, build_http_app, check_bind, is_loopback
from openbb_fmp_cached_mcp.upstream import UpstreamResponse
from starlette.testclient import TestClient

PKG = Path(__file__).resolve().parents[1] / "openbb_fmp_cached_mcp"


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"]
)
def test_loopback_hosts(host):
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_non_loopback_hosts(host):
    assert not is_loopback(host)


def test_non_loopback_bind_without_token_is_refused():
    with pytest.raises(BindError):
        check_bind("0.0.0.0", token="")


def test_non_loopback_bind_with_short_token_is_refused():
    with pytest.raises(BindError):
        check_bind("0.0.0.0", token="short")


def test_loopback_bind_without_token_is_allowed():
    check_bind("127.0.0.1", token="")


class _Up:
    secret = ""

    async def fetch(self, path, params):
        return UpstreamResponse(200, b'[{"symbol":"AAPL","price":1.5}]')


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}
BASE = "http://127.0.0.1:8011"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _post(client, body, session=None, token=None):
    headers = dict(HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", content=json.dumps(body), headers=headers)


def test_http_requires_bearer_token_when_configured():
    token = "t" * 32
    with TestClient(build_http_app(_Up(), token=token), base_url=BASE) as client:
        assert _post(client, INIT).status_code == 401
        assert _post(client, INIT, token="x" * 32).status_code == 401
        ok = _post(client, INIT, token=token)
        assert ok.status_code == 200


def test_http_round_trip_omits_iserror_on_success_like_hosted():
    with TestClient(build_http_app(_Up(), token=""), base_url=BASE) as client:
        init = _post(client, INIT)
        sid = init.headers["mcp-session-id"]
        _post(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session=sid,
        )
        resp = _post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "quote",
                    "arguments": {"endpoint": "quote", "symbol": "AAPL"},
                },
            },
            session=sid,
        )
        result = resp.json()["result"]
        assert result["content"] == [
            {"type": "text", "text": '[{"symbol":"AAPL","price":1.5}]'}
        ]
        assert "isError" not in result
        assert result["_meta"]["openbb/provenance"]["state"] == "live"


FORBIDDEN_IMPORT_PREFIXES = (
    "openbb_portfolio",
    "openbb_portfolio_intel",
    "openbb_techtrade",
    "portfolio_export",
    "portfolio_importer",
    "openbb_mcp_server.story_adapters",
)


def test_package_imports_no_account_or_portfolio_code():
    """No account / brokerage / paper module may be reachable from the tools (R8: AST)."""
    offenders = []
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}:{n}"
                for n in names
                if n.startswith(FORBIDDEN_IMPORT_PREFIXES)
            ]
    assert offenders == []


def test_upstream_failure_log_does_not_contain_key(caplog):
    import asyncio  # pylint: disable=import-outside-toplevel

    from openbb_fmp_cached_mcp.server import (
        Scrubber,
        call_tool,
    )  # pylint: disable=C0415

    secret = "q" * 32

    class Boom:
        async def fetch(self, path, params):
            raise RuntimeError(f"https://x/?apikey={secret}")

    with caplog.at_level(logging.DEBUG, logger="openbb_fmp_cached_mcp"):
        asyncio.run(
            call_tool(
                Boom(),
                Scrubber(secret),
                "quote",
                {"endpoint": "quote", "symbol": "AAPL"},
            )
        )
    assert caplog.records, "the failure must be logged"
    assert all(secret not in r.getMessage() for r in caplog.records)


# --- Review findings (PR-A security review) -------------------------------------


@pytest.mark.parametrize("host", ["my-laptop.local", "rebind.example"])
def test_dns_names_other_than_localhost_count_as_non_loopback(host):
    assert not is_loopback(host)


def test_http_rejects_foreign_host_header_on_loopback():
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1."""
    with TestClient(build_http_app(_Up(), token="", port=8011)) as client:
        headers = dict(HEADERS, Host="evil.example:8011")
        resp = client.post("/mcp", content=json.dumps(INIT), headers=headers)
        assert resp.status_code in (403, 421)
        ok = client.post(
            "/mcp",
            content=json.dumps(INIT),
            headers=dict(HEADERS, Host="127.0.0.1:8011"),
        )
        assert ok.status_code == 200


def test_http_rejects_foreign_origin_on_loopback():
    with TestClient(build_http_app(_Up(), token="", port=8011)) as client:
        headers = dict(HEADERS, Host="127.0.0.1:8011", Origin="https://evil.example")
        resp = client.post("/mcp", content=json.dumps(INIT), headers=headers)
        assert resp.status_code == 403


def test_bearer_auth_rejects_non_http_scopes():
    import asyncio  # pylint: disable=import-outside-toplevel

    from openbb_fmp_cached_mcp.app import BearerAuth  # pylint: disable=C0415

    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "websocket.connect"}

    asyncio.run(
        BearerAuth(inner, "t" * 32)({"type": "websocket", "headers": []}, receive, send)
    )
    assert reached == []
    assert sent and sent[0]["type"] == "websocket.close"
