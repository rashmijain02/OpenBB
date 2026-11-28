"""Field-level evidence projections, sentinel scanner and egress guard (#1339 T03).

All data is synthetic. The loopback "model" below is test-owned and records
request bodies only to scan them.
"""

# ruff: noqa: D103

from __future__ import annotations

import io
import json
import socket
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from openbb_agents.hermes_integration import access, projection
from openbb_agents.hermes_integration.access import (
    HERMES_FINANCE_POLICY,
    Capability,
    PolicyGate,
)
from openbb_agents.hermes_integration.egress_guard import EgressRefused, egress_guard
from openbb_agents.hermes_integration.projection import (
    EvidenceProjection,
    ProjectionDenied,
    project,
    scan_text,
)

from .conftest import SENTINELS

ALL_FIELDS = sorted(access.EVIDENCE_PROJECTION_FIELDS)


def _artifact() -> dict:
    """Return a private-shaped artifact with every sentinel class in every slot."""
    return {
        "run_id": SENTINELS["account"],
        "artifact_id": SENTINELS["name"],
        "capability_status": SENTINELS["amount"],
        "findings": [
            "CONCENTRATION_HIGH",
            SENTINELS["amount"],
            f"owner {SENTINELS['name']}",
            SENTINELS["account"],
        ],
        "metrics": {
            "market_value": SENTINELS["amount"],
            SENTINELS["name"]: 1,
            "top_weight": 0.31,
        },
        "aggregates": {
            "top_weight": 0.31,
            "position_count": 12,
            "cash_share": 0.04,
            SENTINELS["account"]: 4242424.42,
            "total_value": 4242424.42,
        },
        "as_of": "2026-01-02",
        "account_number": SENTINELS["account"],
        "owner_name": SENTINELS["name"],
        "market_value": SENTINELS["amount"],
    }


def _project(fields=ALL_FIELDS, principal="hermes_runtime", gate=None):
    return project(
        _artifact(),
        gate=gate or HERMES_FINANCE_POLICY,
        principal=principal,
        fields=fields,
    )


def test_sentinels_match_the_shared_test_sentinels():
    assert dict(projection.SENTINELS) == SENTINELS


def test_projection_of_sentinel_artifact_has_no_sentinel():
    proj = _project()
    text = proj.model_dump_json()
    assert scan_text(text) == [], scan_text(text)
    assert not [v for v in SENTINELS.values() if v in text]
    assert proj.finding_codes == ("CONCENTRATION_HIGH",)
    assert proj.capability_status == "unavailable"
    assert proj.run_id and proj.run_id.startswith("run_")
    assert proj.artifact_id and proj.artifact_id.startswith("art_")
    assert len(proj.metric_refs) == 2  # the sentinel-named metric is dropped
    assert all(
        r.startswith(f"[[metric:{proj.run_id}:{proj.artifact_id}:")
        for r in proj.metric_refs
    )
    assert proj.aggregate_buckets == {
        "cash_share": "0-5%",
        "position_count": "10-99",
        "top_weight": "25-50%",
        "total_value": "1000+",
    }
    assert str(proj.as_of) == "2026-01-02"


def test_projection_carries_only_requested_fields():
    proj = _project(fields=["finding_codes"])
    assert proj.finding_codes == ("CONCENTRATION_HIGH",)
    assert proj.run_id is None and proj.metric_refs == () and proj.as_of is None


@pytest.mark.parametrize(
    "fields",
    [
        ["run_id", "market_value"],
        ["account_number"],
        ["owner_name", "finding_codes"],
        ["metric_ref"],
        ["*"],
    ],
)
def test_unlisted_projection_fields_fail_closed(fields):
    with pytest.raises(ProjectionDenied) as err:
        _project(fields=fields)
    assert err.value.reason == "field_not_granted"


def test_other_principals_cannot_read_projections():
    with pytest.raises(ProjectionDenied) as err:
        _project(principal="webui_display")
    assert err.value.reason == "no_grant"
    with pytest.raises(ProjectionDenied) as err:
        _project(principal="intruder")
    assert err.value.reason == "unknown_principal"


def test_combination_reidentification_fields_denied():
    """Weight + ticker + date fails closed even when a gate grants all three."""
    wide = PolicyGate(
        grants=frozenset(
            {
                Capability(
                    principal="hermes_runtime",
                    operation="evidence_projection_read",
                    scope="evidence.projection",
                    fields=frozenset({"weight_pct", "symbol", "as_of", "run_id"}),
                )
            }
        )
    )
    with pytest.raises(ProjectionDenied) as err:
        _project(fields=["weight_pct", "symbol", "as_of"], gate=wide)
    assert err.value.reason == "reidentifying_combination"
    # any two of the three are not the combination; they still fail closed here
    # because the projection model has no such fields
    with pytest.raises(ProjectionDenied) as err:
        _project(fields=["symbol", "as_of"], gate=wide)
    assert err.value.reason == "field_not_projectable"


def test_projection_model_rejects_raw_values():
    with pytest.raises(ValueError):
        EvidenceProjection(run_id=SENTINELS["account"])
    with pytest.raises(ValueError):
        EvidenceProjection(finding_codes=(SENTINELS["amount"],))
    with pytest.raises(ValueError):
        EvidenceProjection(metric_refs=(f"[[metric:{SENTINELS['name']}]]",))
    with pytest.raises(ValueError):
        EvidenceProjection(aggregate_buckets={"x": SENTINELS["amount"]})
    with pytest.raises(ValueError):
        EvidenceProjection(market_value=SENTINELS["amount"])


# --- scanner -------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(SENTINELS))
def test_scanner_reports_each_sentinel_by_label_only(label):
    assert scan_text(f"x {SENTINELS[label]} y") == [f"sentinel:{label}"]


@pytest.mark.parametrize(
    ("text", "hits"),
    [
        ("sk-SYNTHETIC-MASTER-KEY-SENTINEL", ["marker:SENTINEL"]),
        ("sentinel lower case is prose", []),
        ('{"api_key": "present", "token": "absent", "password": null}', []),
        ('{"master_key": "sk-abc123"}', ["secret_value:master_key"]),
        ("DB_PASSWORD=hunter2", ["secret_value:db_password"]),
        ("secret: 'x'", ["secret_value:secret"]),
        ("the key idea is speed", []),
        ('{"completion_tokens": 1, "max_tokens": 5, "keyboard": "x"}', []),
        ("apiKey=abc", ["secret_value:apikey"]),
    ],
)
def test_scanner_markers_and_secret_values(text, hits):
    assert scan_text(text) == hits


def test_scan_stdin_cli_exit_codes_and_labels_only(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"acct {SENTINELS['account']}\n"))
    assert projection.main(["--scan-stdin"]) == 1
    out = capsys.readouterr().out
    assert "scan_hit label=sentinel:account" in out
    assert SENTINELS["account"] not in out
    monkeypatch.setattr("sys.stdin", io.StringIO('{"api_key": "present"}\n'))
    assert projection.main(["--scan-stdin"]) == 0
    assert "scan_result hits=0" in capsys.readouterr().out
    assert projection.main([]) == 3


# --- egress guard ----------------------------------------------------------------------


def test_egress_guard_refuses_and_records_non_loopback():
    with egress_guard() as attempts:
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("example.invalid", 443)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(EgressRefused):
                sock.connect(("192.0.2.10", 9))
            with pytest.raises(EgressRefused):
                sock.connect_ex(("198.51.100.7", 9))
        finally:
            sock.close()
    assert attempts == [
        "dns:example.invalid",
        "connect:192.0.2.10",
        "connect:198.51.100.7",
    ]


def test_egress_guard_refuses_live_ports_on_loopback_when_asked():
    with egress_guard(refuse_live_ports=True) as attempts:
        for port in (3306, 4000):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with pytest.raises(EgressRefused):
                    sock.connect(("127.0.0.1", port))
            finally:
                sock.close()
    assert attempts == ["connect:127.0.0.1:3306", "connect:127.0.0.1:4000"]


def test_egress_guard_allows_loopback_and_restores_on_exit():
    before = (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex)
    with (
        _model_server() as (srv, port),
        pytest.raises(RuntimeError),
        egress_guard() as attempts,
    ):
        assert socket.socket.connect is not before[1]
        _post(port, {"ok": True})
        raise RuntimeError("body fails; guard must still restore")
    assert attempts == []
    assert srv.bodies == [b'{"ok": true}']
    assert (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    ) == before


# --- loopback "model" ---------------------------------------------------------------


class _Model(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.server.bodies.append(self.rfile.read(length))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _model_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    srv.bodies = []
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _post(port, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as resp:
        return resp.read()


def test_fake_local_backend_receives_no_sentinel():
    proj = _project()
    with (
        _model_server() as (srv, port),
        egress_guard(refuse_live_ports=True) as attempts,
    ):
        _post(port, {"messages": [{"role": "user", "content": proj.model_dump_json()}]})
        # positive control: the capture and scanner do see a raw artifact
        _post(
            port, {"messages": [{"role": "user", "content": json.dumps(_artifact())}]}
        )
    assert attempts == []
    projected, raw = (b.decode() for b in srv.bodies)
    assert scan_text(projected) == []
    assert {f"sentinel:{k}" for k in SENTINELS} <= set(scan_text(raw))


# --- policy_probe --projection (real path) ---------------------------------------------


def test_policy_probe_projection_real_path(capsys):
    from openbb_agents.hermes_integration import policy_probe

    assert policy_probe.main(["--synthetic", "--projection"]) == 0
    out = capsys.readouterr().out
    summary = json.loads(out)
    proj = summary["projection"]
    assert proj["result"] == "projected"
    assert proj["model_requests"] == 1
    assert proj["model_capture_scan_hits"] == [] and proj["egress_attempts"] == []
    assert proj["unlisted_field_denied"] == "field_not_granted"
    assert proj["reidentifying_denied"] == "reidentifying_combination"
    assert summary["scan_hits"] == []
    assert scan_text(out) == []


@pytest.mark.parametrize(
    "leak",
    [SENTINELS["amount"], "trace SENTINEL", '"api_key": "sk-live-1"'],
)
def test_policy_probe_evaluate_uses_the_scanner(leak):
    from openbb_agents.hermes_integration import policy_probe

    denied = json.dumps({"error": "capability_denied", "reason": "no_grant"})
    calls = {t: {"isError": True, "text": denied} for t in policy_probe._TOOLS}
    audit = "policy_decision a\npolicy_decision b\n"
    assert policy_probe._evaluate(calls, audit)[0] is True
    ok, summary = policy_probe._evaluate(calls, audit + leak)
    assert ok is False and summary["scan_hits"]
    assert leak not in json.dumps(summary)
