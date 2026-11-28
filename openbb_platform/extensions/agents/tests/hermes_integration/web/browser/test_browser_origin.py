"""Tier B (#1342 T01): cross-origin rejection against the real pinned WebUI and sidecar.

A page served from a second loopback port (same-site, so cookies flow) tries to reach
the approval route through the WebUI proxy (fetch with credentials, a no-cors simple
request, and a ``<form>`` POST) and directly on the sidecar port. Every attempt must be
refused and none may reach the approval handler. The same-origin control first proves
the consent gate, then that a consented, logged-in same-origin call does reach it.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROXY = "/api/extensions/openbb-hfp/sidecar/plans/plan_" + "0" * 32 + "/approve"
BODY = json.dumps({"plan_sha256": "a" * 64, "approval_nonce": "n" * 43})

_SAME_ORIGIN_POST = """async ([path, body]) => {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
  return [r.status, await r.text()];
}"""

_ATTACK_PAGE = """<!doctype html><meta charset="utf-8"><title>other loopback app</title>
<form id="f" method="POST" action="{proxy}" enctype="text/plain">
<input name='{{"plan_sha256":"{sha}","x":"' value='"}}'></form>
<script>
window.attempts = (async () => {{
  const out = {{}};
  const tries = {{
    proxy_cors_json: () => fetch("{proxy}", {{method: "POST", credentials: "include",
      headers: {{"Content-Type": "application/json"}}, body: {body}}}),
    proxy_no_cors_text: () => fetch("{proxy}", {{method: "POST", credentials: "include",
      mode: "no-cors", headers: {{"Content-Type": "text/plain"}}, body: {body}}}),
    sidecar_direct_no_cors: () => fetch("{direct}", {{method: "POST", mode: "no-cors",
      headers: {{"Content-Type": "text/plain"}}, body: {body}}}),
    sidecar_direct_cors_json: () => fetch("{direct}", {{method: "POST",
      headers: {{"Content-Type": "application/json"}}, body: {body}}}),
  }};
  for (const [name, run] of Object.entries(tries)) {{
    try {{ const r = await run(); out[name] = r.type === "opaque" ? "opaque" : r.status; }}
    catch (e) {{ out[name] = "blocked"; }}
  }}
  return out;
}})();
</script>"""


@contextmanager
def _attacker(html: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # silence
            pass

        def do_GET(self):  # noqa: N802
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/attack.html"
    finally:
        server.shutdown()
        server.server_close()


def _login(page, stack):
    page.goto(stack.webui + "/login")
    status = page.evaluate(
        """async (pw) => (await fetch('/api/auth/login', {method: 'POST',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({password: pw})})).status""",
        stack.password,
    )
    assert status == 200
    page.goto(stack.webui + "/")


def test_browser_origin(browser_context, stack):
    calls = stack.sidecar.app.state
    page = browser_context.new_page()
    _login(page, stack)

    # 1. Same-origin and logged in, but no owner consent yet: WebUI refuses.
    status, text = page.evaluate(_SAME_ORIGIN_POST, [PROXY, BODY])
    assert status == 403, text
    assert calls.approve_calls == 0
    assert not (stack.state_dir / "sidecar-auth" / "openbb-hfp.token").exists()

    # 2. Consent (the owner's Settings -> Extensions click), then the control call
    #    reaches the handler through the proxy with the injected token.
    consent = page.evaluate(
        """async () => (await fetch('/api/extensions/sidecar-proxy-consent', {method: 'POST',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({id: 'openbb-hfp', approved: true})})).status"""
    )
    assert consent == 200
    status, text = page.evaluate(_SAME_ORIGIN_POST, [PROXY, BODY])
    assert (status, json.loads(text)) == (501, {"error": "plan_store_unavailable"})
    assert calls.approve_calls == 1

    # 3. A page on another loopback port: every route to the approval is refused.
    seen: list[tuple[str, str, int]] = []
    browser_context.on(
        "response",
        lambda r: seen.append((r.request.method, r.url, r.status))
        if "/plans/" in r.url
        else None,
    )
    direct = f"http://127.0.0.1:{stack.sidecar.port}/plans/plan_{'0' * 32}/approve"
    html = _ATTACK_PAGE.format(
        proxy=stack.webui + PROXY, direct=direct, body=json.dumps(BODY), sha="a" * 64
    )
    with _attacker(html) as url:
        evil = browser_context.new_page()
        evil.goto(url)
        attempts = evil.evaluate("window.attempts")
        with evil.expect_navigation() as nav:
            evil.evaluate("document.getElementById('f').submit()")
        form_response = nav.value
    assert form_response is not None and form_response.status == 403
    assert attempts["proxy_cors_json"] in ("blocked", 403), attempts
    assert attempts["sidecar_direct_cors_json"] in ("blocked", 403), attempts
    assert calls.approve_calls == 1, (attempts, seen)
    proxied = [s for m, u, s in seen if m == "POST" and u.startswith(stack.webui)]
    direct_seen = [s for m, u, s in seen if m == "POST" and u.startswith(direct)]
    assert proxied and all(s == 403 for s in proxied), seen
    assert direct_seen and all(s == 403 for s in direct_seen), seen
    assert not [h for m, u, s in seen if m == "OPTIONS" and s < 300], seen

    # 4. Nothing left loopback. The pinned WebUI shell itself references CDN assets
    #    (xterm etc.); those were aborted. Any other aborted URL (from the extension
    #    or these flows) fails the test.
    shell = (stack.src / "static" / "index.html").read_text(encoding="utf-8")
    unexpected = [u for u in stack.aborted if u not in shell]
    assert unexpected == [], unexpected
