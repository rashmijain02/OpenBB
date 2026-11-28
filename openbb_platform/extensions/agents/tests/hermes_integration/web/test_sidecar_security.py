"""HFP sidecar security layer (#1342 T01): auth, origin, host and content-type checks.

Two tiers: Starlette ``TestClient`` against the ASGI app, and a real loopback
uvicorn server driven with raw ``http.client`` so the Host header is ours.
"""

from __future__ import annotations

import http.client
import json
import secrets
import socket

import pytest
from openbb_agents.hermes_integration.web import security, sidecar
from starlette.testclient import TestClient

PLAN = "plan_" + "0" * 32
APPROVE = f"/plans/{PLAN}/approve"
BODY = {"plan_sha256": "a" * 64, "approval_nonce": "n" * 43}
PORT = 8799


@pytest.fixture
def token(tmp_path):
    value = secrets.token_urlsafe(32)
    path = tmp_path / "state" / "sidecar-auth" / "openbb-hfp.token"
    path.parent.mkdir(parents=True)
    path.write_text(value + "\n", encoding="utf-8")
    return path, value


def _config(token_file, port=PORT, principal="principal-from-config"):
    return sidecar.SidecarConfig(port=port, principal=principal, token_file=token_file)


@pytest.fixture
def client(token):
    path, value = token
    app = sidecar.create_app(_config(path))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        c.headers[security.TOKEN_HEADER] = value
        yield c, app


def _no_cors(response):
    leaked = [h for h in response.headers if h.lower().startswith("access-control-")]
    assert not leaked, leaked


def test_health_open_and_data_free(token):
    path, _ = token
    app = sidecar.create_app(_config(path))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        response = c.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    _no_cors(response)


def test_503_without_token_file_401_on_mismatch(tmp_path, token):
    missing = sidecar.create_app(_config(tmp_path / "absent.token"))
    with TestClient(missing, base_url=f"http://127.0.0.1:{PORT}") as c:
        r = c.get("/v1/session", headers={security.TOKEN_HEADER: "x" * 43})
        assert (r.status_code, r.json()) == (503, {"error": "token_unprovisioned"})
        assert c.get("/health").status_code == 200
    unresolved = sidecar.create_app(_config(None))
    with TestClient(unresolved, base_url=f"http://127.0.0.1:{PORT}") as c:
        assert c.get("/v1/session").status_code == 503
    path, value = token
    app = sidecar.create_app(_config(path))
    near = value[:-1] + ("B" if value.endswith("A") else "A")  # one character off
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        for headers in ({}, {security.TOKEN_HEADER: near}, {security.TOKEN_HEADER: ""}):
            r = c.get("/v1/session", headers=headers)
            assert (r.status_code, r.json()) == (401, {"error": "token_mismatch"})
        assert c.get("/v1/session", headers={security.TOKEN_HEADER: value}).status_code == 200
    # A malformed token file fails closed as unprovisioned, never as a match.
    path.write_text("short\n", encoding="utf-8")
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        r = c.get("/v1/session", headers={security.TOKEN_HEADER: "short"})
        assert r.status_code == 503


def test_token_file_resolution_never_falls_back_to_a_home(tmp_path):
    assert security.resolve_token_file({}) is None
    assert security.resolve_token_file({"LOCALAPPDATA": str(tmp_path), "HERMES_HOME": str(tmp_path)}) is None
    state = tmp_path / "state"
    assert security.resolve_token_file({"HERMES_WEBUI_STATE_DIR": str(state)}) == (
        state / "sidecar-auth" / "openbb-hfp.token"
    )
    explicit = tmp_path / "explicit.token"
    assert security.resolve_token_file(
        {"HERMES_EXT_SIDECAR_TOKEN_FILE": str(explicit), "HERMES_WEBUI_STATE_DIR": str(state)}
    ) == explicit


def test_principal_from_config_not_request(client):
    c, _ = client
    r = c.get(
        "/v1/session?principal=attacker",
        headers={"X-Principal": "attacker", "X-Forwarded-User": "attacker"},
    )
    assert r.status_code == 200
    assert r.json()["principal"] == "principal-from-config"
    r = c.post(APPROVE, json={**BODY, "principal": "attacker"})
    assert r.status_code == 422  # closed schema: an extra field is refused


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://127.0.0.1:9999"},
        {"Origin": "null"},
        {"Origin": f"http://127.0.0.1:{PORT}"},
        {"Referer": "http://127.0.0.1:9999/attack.html"},
    ],
)
def test_rejects_origin_or_referer(client, headers):
    c, app = client
    for method in ("GET", "POST"):
        r = c.request(method, APPROVE if method == "POST" else "/v1/session", json=BODY, headers=headers)
        assert (r.status_code, r.json()) == (403, {"error": "origin_rejected"})
        _no_cors(r)
    assert app.state.approve_calls == 0


@pytest.mark.parametrize("site", ["cross-site", "same-site", "bogus"])
def test_rejects_cross_site_fetch_metadata(client, site):
    c, app = client
    r = c.post(APPROVE, json=BODY, headers={"Sec-Fetch-Site": site})
    assert (r.status_code, r.json()) == (403, {"error": "fetch_metadata_rejected"})
    assert app.state.approve_calls == 0
    for ok in ("same-origin", "none"):
        assert c.get("/v1/session", headers={"Sec-Fetch-Site": ok}).status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", f"evil.example:{PORT}", f"localhost:{PORT}", "127.0.0.1:1", "127.0.0.1"],
)
def test_rejects_foreign_host_header(token, host):
    path, value = token
    app = sidecar.create_app(_config(path))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        r = c.post(APPROVE, json=BODY, headers={"Host": host, security.TOKEN_HEADER: value})
        assert (r.status_code, r.json()) == (403, {"error": "host_rejected"})
        assert c.get("/health", headers={"Host": host}).status_code == 403
    assert app.state.approve_calls == 0


@pytest.mark.parametrize(
    "ctype",
    [
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "text/plain",
        "text/plain;charset=UTF-8",
        "application/json-patch+json",
        None,
    ],
)
def test_post_requires_json_content_type(client, ctype):
    c, app = client
    headers = {} if ctype is None else {"Content-Type": ctype}
    r = c.post(APPROVE, content=json.dumps(BODY).encode(), headers=headers)
    assert (r.status_code, r.json()) == (415, {"error": "unsupported_media_type"})
    assert app.state.approve_calls == 0


def test_json_post_reaches_handler_and_is_bounded(client):
    c, app = client
    r = c.post(APPROVE, content=json.dumps(BODY), headers={"Content-Type": "application/json; charset=utf-8"})
    assert (r.status_code, r.json()) == (501, {"error": "plan_store_unavailable"})
    assert app.state.approve_calls == 1
    big = json.dumps({**BODY, "pad": "x" * security.MAX_BODY_BYTES})
    r = c.post(APPROVE, content=big, headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()) == (413, {"error": "body_too_large"})
    assert app.state.approve_calls == 1


@pytest.mark.parametrize("method", ["OPTIONS", "PUT", "DELETE", "PATCH", "HEAD"])
def test_no_cors_headers_ever(client, method):
    c, _ = client
    r = c.request(
        method,
        APPROVE,
        headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 405
    _no_cors(r)
    for response in (c.get("/health"), c.get("/v1/session"), c.post(APPROVE, json=BODY)):
        _no_cors(response)


def test_inner_app_cors_headers_are_stripped(token):
    """Even if a route tried to add CORS headers, the guard removes them."""
    path, value = token

    async def leaky(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"access-control-allow-origin", b"*"), (b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"x"})

    guarded = security.SidecarGuard(leaky, security.GuardSettings(port=PORT, token_file=path))
    # No ``with``: the bare test app does not speak the lifespan protocol.
    c = TestClient(guarded, base_url=f"http://127.0.0.1:{PORT}")
    r = c.get("/anything", headers={security.TOKEN_HEADER: value})
    assert r.status_code == 200
    _no_cors(r)


def test_binds_loopback_only(token):
    path, _ = token
    for host in ("0.0.0.0", "::", "192.168.1.10", "localhost", ""):
        with pytest.raises(ValueError, match="non_loopback_bind"):
            sidecar.bind_loopback(host, 0)
    sock = sidecar.bind_loopback("127.0.0.1", 0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


# ---- real loopback server ------------------------------------------------------------


def _raw(port, method, path, headers, body=b""):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        if body or method == "POST":
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body or None)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, dict(resp.getheaders()), data
    finally:
        conn.close()


def test_real_loopback_server_rejection_matrix(token):
    path, value = token
    with sidecar.LoopbackSidecar(principal="principal-from-config", token_file=path) as running:
        port = running.port
        host = {"Host": f"127.0.0.1:{port}"}
        auth = {**host, security.TOKEN_HEADER: value}
        js = {**auth, "Content-Type": "application/json"}
        body = json.dumps(BODY).encode()
        cases = [
            ("GET", "/health", host, b"", 200),
            ("GET", "/v1/session", host, b"", 401),
            ("GET", "/v1/session", {"Host": f"evil.example:{port}", security.TOKEN_HEADER: value}, b"", 403),
            ("POST", APPROVE, {**js, "Origin": "http://127.0.0.1:9"}, body, 403),
            ("POST", APPROVE, {**js, "Sec-Fetch-Site": "same-site"}, body, 403),
            ("POST", APPROVE, {**auth, "Content-Type": "text/plain"}, body, 415),
            ("OPTIONS", APPROVE, {**host, "Origin": "http://127.0.0.1:9"}, b"", 403),
            ("OPTIONS", APPROVE, auth, b"", 405),
            ("POST", APPROVE, {**js, "X-Forwarded-Host": "127.0.0.1", "Host": "evil.example"}, body, 403),
        ]
        for method, target, headers, payload, expected in cases:
            status, resp_headers, _ = _raw(port, method, target, headers, payload)
            assert status == expected, (method, target, headers, status)
            assert not [h for h in resp_headers if h.lower().startswith("access-control-")]
            assert "server" not in {h.lower() for h in resp_headers}
        assert running.app.state.approve_calls == 0
        status, _, data = _raw(port, "POST", APPROVE, js, body)
        assert (status, json.loads(data)) == (501, {"error": "plan_store_unavailable"})
        assert running.app.state.approve_calls == 1
        # The listener is loopback-only: the bound address is 127.0.0.1.
        assert running.bound[0] == "127.0.0.1"
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


@pytest.mark.parametrize("method", ["OPTIONS", "PUT", "DELETE", "PATCH"])
def test_guard_refuses_methods_even_if_a_route_would_answer(token, method):
    """The guard, not FastAPI routing, refuses every method but GET and POST."""
    path, value = token

    async def permissive(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    guarded = security.SidecarGuard(permissive, security.GuardSettings(port=PORT, token_file=path))
    c = TestClient(guarded, base_url=f"http://127.0.0.1:{PORT}")
    r = c.request(method, "/anything", headers={security.TOKEN_HEADER: value})
    assert (r.status_code, r.json()) == (405, {"error": "method_not_allowed"})
    _no_cors(r)
