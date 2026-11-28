"""Pure protocol tests: no nautilus_trader import (#1355 T01)."""

# ruff: noqa: D103

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from openbb_nautilus_worker import protocol as p
from pydantic import ValidationError

KEY = bytes(range(32))
FAILED_LAYER_VALUES = {
    "process",
    "module_origin",
    "abi",
    "config",
    "auth",
    "route",
    "backend",
    "database",
    "schema",
    "skills",
    "egress",
}


def _session():
    return p.Session.from_key_line(p.encode_key_frame(KEY))


def _req(seq=1, op="describe", body=None, key=KEY):
    return p.encode_frame(p.sign_request(key, seq, op, body or {}))


def _err_code(out):
    return json.loads(out)["error"]["code"]


def test_error_codes_are_subset_of_failed_layer_values():
    values = {c.value for c in p.ErrorCode}
    assert values <= FAILED_LAYER_VALUES
    assert {"abi", "module_origin", "auth", "schema", "egress", "config"} <= values


def test_failure_codes_are_failed_layer_values():
    """Parity with #1338 FailedLayer once openbb_agents is importable."""
    models = pytest.importorskip("openbb_agents.hermes_integration.models")
    assert {c.value for c in p.ErrorCode} <= {m.value for m in models.FailedLayer}


def test_roundtrip_describe_ok():
    out, stop = _session().handle(_req(), {"describe": lambda b: {"x": 1}})
    resp = p.verify_response(KEY, json.loads(out), expected_seq=1)
    assert resp.ok and resp.body == {"x": 1} and not stop


def test_tampered_body_rejected_as_auth():
    frame = json.loads(_req(body={"a": 1}))
    frame["body"] = {"a": 2}
    out, stop = _session().handle(
        json.dumps(frame).encode() + b"\n", {"describe": lambda b: {}}
    )
    assert _err_code(out) == "auth" and stop


def test_wrong_key_rejected_as_auth():
    out, stop = _session().handle(_req(key=b"\x01" * 32), {"describe": lambda b: {}})
    assert _err_code(out) == "auth" and stop


def test_replay_and_out_of_order_seq_rejected():
    s = _session()
    ops = {"describe": lambda b: {}}
    out1, _ = s.handle(_req(seq=1), ops)
    assert json.loads(out1)["ok"] is True
    out2, stop = s.handle(_req(seq=1), ops)
    assert _err_code(out2) == "auth" and stop
    s2 = _session()
    out3, stop3 = s2.handle(_req(seq=5), ops)
    assert _err_code(out3) == "auth" and stop3


def test_missing_or_bad_key_frame_rejected():
    with pytest.raises(p.ProtocolError) as exc:
        p.Session.from_key_line(_req())  # a request frame, not a key frame
    assert exc.value.code is p.ErrorCode.AUTH
    with pytest.raises(p.ProtocolError) as exc:
        p.Session.from_key_line(b"")
    assert exc.value.code is p.ErrorCode.AUTH
    with pytest.raises(p.ProtocolError):
        p.Session.from_key_line(
            json.dumps({"v": 1, "hello": True, "key": "ab"}).encode()
        )


def test_oversize_frame_rejected():
    """A correctly signed request is still refused when the frame is over the cap."""
    req = p.sign_request(KEY, 1, "describe", {"pad": "a" * (p.MAX_FRAME_BYTES + 1)})
    line = json.dumps(req.model_dump(mode="json")).encode() + b"\n"
    assert len(line) > p.MAX_FRAME_BYTES
    out, stop = _session().handle(line, {"describe": lambda b: {"ok": 1}})
    assert _err_code(out) == "schema" and stop
    with pytest.raises(p.ProtocolError):
        p.encode_frame(req)


def test_unknown_op_and_extra_fields_are_schema_errors():
    out, _ = _session().handle(_req(op="launch_missiles"), {"describe": lambda b: {}})
    assert _err_code(out) == "schema"
    frame = json.loads(_req(seq=1))
    frame["venue"] = "IB"
    out2, _ = _session().handle(
        json.dumps(frame).encode() + b"\n", {"describe": lambda b: {}}
    )
    assert _err_code(out2) == "schema"
    with pytest.raises(ValidationError):
        p.Request(v=1, seq=1, op="describe", body={}, mac="0" * 64, venue="IB")


def test_dispatch_error_becomes_error_response_and_unexpected_is_process():
    s = _session()

    def boom(_b):
        raise p.ProtocolError(p.ErrorCode.MODULE_ORIGIN, "nautilus missing")

    out, stop = s.handle(_req(seq=1), {"describe": boom})
    assert _err_code(out) == "module_origin" and not stop

    def crash(_b):
        raise RuntimeError("secret-looking detail")

    out2, _ = s.handle(_req(seq=2), {"describe": crash})
    assert _err_code(out2) == "process"
    assert "secret-looking" not in out2.decode()


def test_shutdown_stops_session():
    out, stop = _session().handle(_req(op="shutdown"), {"shutdown": lambda b: {}})
    assert json.loads(out)["ok"] is True and stop


def test_real_worker_entrypoint_without_nautilus_reports_module_origin():
    try:
        import nautilus_trader  # noqa: F401  # pylint: disable=unused-import

        pytest.skip("nautilus_trader is installed; this negative path needs it absent")
    except ImportError:
        pass
    root = str(Path(p.__file__).resolve().parents[1])
    proc = subprocess.run(
        [sys.executable, "-m", "openbb_nautilus_worker"],
        input=p.encode_key_frame(KEY) + _req(seq=1) + _req(seq=2, op="shutdown"),
        capture_output=True,
        timeout=60,
        check=False,
        env={**os.environ, "PYTHONPATH": root},
    )
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0, proc.stderr.decode()[:300]
    first = p.verify_response(KEY, json.loads(lines[0]), expected_seq=1)
    assert not first.ok and first.error.code == "module_origin"
