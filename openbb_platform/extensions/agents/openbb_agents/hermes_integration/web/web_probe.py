"""Real-path probe of the HFP sidecar security layer (#1342 T01).

Usage: ``python -m openbb_agents.hermes_integration.web.web_probe --scenario security``.
Starts the real sidecar on an ephemeral ``127.0.0.1`` port with a synthetic token in a
temp dir, sends the rejection matrix with raw HTTP (so ``Host`` is the probe's), and
reports each case's status and code. Never contacts WebUI, Hermes or any other port.
Exit 0 when every case matches, 1 on a mismatch, 3 on usage errors.
"""

from __future__ import annotations

import argparse
import http.client
import json
import secrets
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .security import TOKEN_HEADER
from .sidecar import LoopbackSidecar

_APPROVE = "/plans/plan_" + "0" * 32 + "/approve"
_BODY = json.dumps({"plan_sha256": "a" * 64, "approval_nonce": "n" * 43}).encode()


@dataclass(frozen=True)
class _Case:
    name: str
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    expected_status: int
    expected_code: str | None


@dataclass
class CaseResult:
    """One probe case: what was expected and what the sidecar answered."""

    name: str
    status: int
    code: str | None
    expected_status: int
    expected_code: str | None
    ok: bool


def _send(port: int, case: _Case) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest(
            case.method, case.path, skip_host=True, skip_accept_encoding=True
        )
        for name, value in case.headers.items():
            conn.putheader(name, value)
        if case.method == "POST":
            conn.putheader("Content-Length", str(len(case.body)))
        conn.endheaders(case.body or None)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _code(data: bytes) -> str | None:
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    return payload.get("error") if isinstance(payload, dict) else None


def _cases(port: int, token: str) -> list[_Case]:
    host = {"Host": f"127.0.0.1:{port}"}
    auth = {**host, TOKEN_HEADER: token}
    js = {**auth, "Content-Type": "application/json"}
    other = "http://127.0.0.1:1"  # a page on another loopback port: same-site
    big = json.dumps({"pad": "x" * 20_000}).encode()
    rows: list[tuple[str, str, str, dict[str, str], bytes, int, str | None]] = [
        ("health_open", "GET", "/health", host, b"", 200, None),
        ("no_token", "GET", "/v1/session", host, b"", 401, "token_mismatch"),
        (
            "wrong_token",
            "GET",
            "/v1/session",
            {**host, TOKEN_HEADER: "w" * 43},
            b"",
            401,
            "token_mismatch",
        ),
        (
            "foreign_host",
            "POST",
            _APPROVE,
            {**js, "Host": f"rebind.example:{port}"},
            _BODY,
            403,
            "host_rejected",
        ),
        (
            "cross_site_origin",
            "POST",
            _APPROVE,
            {**js, "Origin": other},
            _BODY,
            403,
            "origin_rejected",
        ),
        (
            "referer",
            "POST",
            _APPROVE,
            {**js, "Referer": other + "/x"},
            _BODY,
            403,
            "origin_rejected",
        ),
        (
            "same_site_fetch",
            "POST",
            _APPROVE,
            {**js, "Sec-Fetch-Site": "same-site"},
            _BODY,
            403,
            "fetch_metadata_rejected",
        ),
        (
            "form_post",
            "POST",
            _APPROVE,
            {**auth, "Content-Type": "application/x-www-form-urlencoded"},
            b"plan_sha256=a",
            415,
            "unsupported_media_type",
        ),
        (
            "text_plain_post",
            "POST",
            _APPROVE,
            {**auth, "Content-Type": "text/plain"},
            _BODY,
            415,
            "unsupported_media_type",
        ),
        ("preflight", "OPTIONS", _APPROVE, auth, b"", 405, "method_not_allowed"),
        ("oversize", "POST", _APPROVE, js, big, 413, "body_too_large"),
    ]
    return [_Case(*row) for row in rows]


def _run_case(port: int, case: _Case) -> tuple[CaseResult, int]:
    status, headers, data = _send(port, case)
    code = _code(data)
    cors = sum(1 for name in headers if name.startswith("access-control-"))
    ok = status == case.expected_status and code == case.expected_code and not cors
    result = CaseResult(
        case.name, status, code, case.expected_status, case.expected_code, ok
    )
    return result, cors


def run_security() -> dict[str, Any]:
    """Run the rejection matrix against a real loopback sidecar; return the report."""
    results: list[CaseResult] = []
    cors_seen = 0
    with tempfile.TemporaryDirectory(prefix="hfp-probe-") as tmp:
        token = secrets.token_urlsafe(32)
        token_file = Path(tmp) / "sidecar-auth" / "openbb-hfp.token"
        token_file.parent.mkdir()
        token_file.write_text(token, encoding="utf-8")
        with LoopbackSidecar(principal="probe", token_file=token_file) as running:
            for case in _cases(running.port, token):
                result, cors = _run_case(running.port, case)
                results.append(result)
                cors_seen += cors
            rejected_calls = running.app.state.approve_calls
            bind = running.bound[0]
        missing = Path(tmp) / "absent.token"
        with LoopbackSidecar(principal="probe", token_file=missing) as running:
            case = _Case(
                "unprovisioned",
                "GET",
                "/v1/session",
                {"Host": f"127.0.0.1:{running.port}", TOKEN_HEADER: token},
                b"",
                503,
                "token_unprovisioned",
            )
            result, cors = _run_case(running.port, case)
            results.append(result)
            cors_seen += cors
    ok = all(r.ok for r in results) and rejected_calls == 0 and cors_seen == 0
    return {
        "scenario": "security",
        "bind": bind,
        "cases": [asdict(r) for r in results],
        "rejected_reached_handler": rejected_calls,
        # No plan store exists in T01, so nothing can be written; T02 counts store rows.
        "approvals_written": 0,
        "cors_headers_seen": cors_seen,
        "ok": ok,
    }


def _render_text(report: dict[str, Any]) -> str:
    lines = [
        f"case {c['name']} status={c['status']} code={c['code'] or '-'} ok={c['ok']}"
        for c in report["cases"]
    ]
    for key in (
        "bind",
        "rejected_reached_handler",
        "approvals_written",
        "cors_headers_seen",
        "ok",
    ):
        lines.append(f"{key}: {report[key]}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="web_probe", description=__doc__)
    parser.add_argument("--scenario", choices=["security"], required=True)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    report = run_security()
    text = (
        json.dumps(report, indent=2) if args.format == "json" else _render_text(report)
    )
    sys.stdout.write(text + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
