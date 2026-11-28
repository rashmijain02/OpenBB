"""Field-level evidence projections, sentinel scanner and egress guard (#1339 T03).

All data is synthetic. The loopback "model" below is test-owned and records
request bodies only to scan them.
"""

# ruff: noqa: D103

from __future__ import annotations

import hashlib
import io
import json
import socket
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration import (
    access,
    handshake,
    hermes_config,
    litellm_config,
    projection,
)
from openbb_agents.hermes_integration.access import (
    HERMES_FINANCE_POLICY,
    Capability,
    PolicyGate,
)
from openbb_agents.hermes_integration.egress_guard import EgressRefused, egress_guard
from openbb_agents.hermes_integration.hermes_preflight import (
    PreflightOptions,
    main,
    run_preflight,
)
from openbb_agents.hermes_integration.profile import load_profile
from openbb_agents.hermes_integration.projection import (
    EvidenceProjection,
    ProjectionDenied,
    project,
    scan_text,
)

from .conftest import FIXTURES, SENTINELS

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


# --- closed vocabularies (SECURITY-1) ------------------------------------------------
# The verified leak: producer keys and codes carrying a ticker and an amount passed
# the old shape-only checks and reached the projection as names.

_VERIFIED_LEAK = {
    "run_id": "synthetic-run-1",
    "artifact_id": "synthetic-artifact-1",
    "capability_status": "granted",
    "findings": ["CONCENTRATION_HIGH", "TOP_HOLDING_NVDA", "MV_4242424_42"],
    "metrics": {"nvda_market_value": 1.0, "market_value": 2.0},
    "aggregates": {"nvda": 0.31, "top_weight": 0.31},
    "as_of": "2026-01-02",
}


def _emitted_names(proj: EvidenceProjection) -> set[str]:
    names = set(proj.finding_codes) | set(proj.aggregate_buckets)
    return names | {ref[:-2].rsplit(":", 1)[1] for ref in proj.metric_refs}


def _project_artifact(artifact, fields=ALL_FIELDS):
    return project(
        artifact, gate=HERMES_FINANCE_POLICY, principal="hermes_runtime", fields=fields
    )


def test_verified_leak_projects_only_vocabulary_names():
    proj = _project_artifact(_VERIFIED_LEAK)
    names = _emitted_names(proj)
    assert names == {"CONCENTRATION_HIGH", "market_value", "top_weight"}
    assert not [n for n in names if any(ch.isdigit() for ch in n)]
    text = proj.model_dump_json()
    assert "nvda" not in text.lower() and "4242424" not in text
    assert proj.dropped_unvetted == 4
    assert proj.as_of is not None  # the date still crosses; the ticker does not


@pytest.mark.parametrize(
    ("slot", "item"),
    [
        ("findings", "TOP_HOLDING_NVDA"),
        ("findings", "MV_4242424_42"),
        ("findings", "CONCENTRATION_HIGH_2"),
        ("aggregates", "nvda"),
        ("aggregates", "aapl_weight"),
        ("metrics", "nvda_market_value"),
        ("metrics", "market_value_2"),
    ],
)
def test_unvetted_codes_and_names_are_dropped_and_counted(slot, item):
    artifact = {"run_id": "r", "artifact_id": "a", slot: {item: 0.2}}
    if slot == "findings":
        artifact[slot] = [item]
    proj = _project_artifact(artifact)
    assert item not in proj.model_dump_json()
    assert proj.dropped_unvetted == 1
    assert _emitted_names(proj) == set()


def test_vocabulary_entries_with_digits_or_symbol_words_still_drop(monkeypatch):
    """Defense in depth: a bad vocabulary entry is still not emitted."""
    monkeypatch.setattr(
        projection,
        "FINDING_CODES",
        projection.FINDING_CODES | {"MV_4242424_42", "TOP_TICKER_HIGH"},
    )
    monkeypatch.setattr(
        projection, "AGGREGATE_NAMES", projection.AGGREGATE_NAMES | {"nvda2", "symbol_weight"}
    )
    monkeypatch.setattr(
        projection, "METRIC_NAMES", projection.METRIC_NAMES | {"cusip_value"}
    )
    proj = _project_artifact(
        {
            "findings": ["MV_4242424_42", "TOP_TICKER_HIGH"],
            "aggregates": {"nvda2": 0.1, "symbol_weight": 0.1},
            "metrics": {"cusip_value": 1},
        }
    )
    assert _emitted_names(proj) == set()
    assert proj.dropped_unvetted == 5


def test_emitted_names_are_checked_for_the_reidentifying_combination(monkeypatch):
    """A weight aggregate + a security-id metric + as_of re-identifies a holding."""
    monkeypatch.setattr(
        projection, "METRIC_NAMES", projection.METRIC_NAMES | {"security_id"}
    )
    artifact = {"metrics": {"security_id": 1}, "aggregates": {"top_weight": 0.3}}
    with pytest.raises(ProjectionDenied) as err:
        _project_artifact({**artifact, "as_of": "2026-01-02"})
    assert err.value.reason == "reidentifying_combination"
    fields = [f for f in ALL_FIELDS if f != "as_of"]
    assert "security_id" in _emitted_names(_project_artifact(artifact, fields))


def test_projection_model_rejects_unvetted_names():
    with pytest.raises(ValueError):
        EvidenceProjection(finding_codes=("TOP_HOLDING_NVDA",))
    with pytest.raises(ValueError):
        EvidenceProjection(aggregate_buckets={"nvda": "25-50%"})
    ref = f"[[metric:run_{'0' * 16}:art_{'0' * 16}:nvda_market_value]]"
    with pytest.raises(ValueError):
        EvidenceProjection(metric_refs=(ref,))
    ok = f"[[metric:run_{'0' * 16}:art_{'0' * 16}:market_value]]"
    assert EvidenceProjection(metric_refs=(ok,)).metric_refs == (ok,)


# --- keyed opaque IDs (PRIVACY-1) ------------------------------------------------------


def _key_file(tmp_path, name, data=None):
    path = tmp_path / "keys" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data if data is not None else (name * 64).encode()[:64])
    return path


def test_projected_ids_are_keyed_not_plain_sha256():
    proj = _project_artifact(_VERIFIED_LEAK)
    for prefix, raw, got in (
        ("run", "synthetic-run-1", proj.run_id),
        ("art", "synthetic-artifact-1", proj.artifact_id),
    ):
        plain = hashlib.sha256(f"{prefix}\x00{raw}".encode()).hexdigest()[:16]
        assert got != f"{prefix}_{plain}"


def test_projected_ids_are_stable_per_key_and_differ_across_keys(tmp_path, monkeypatch):
    monkeypatch.setenv(projection.PROJECTION_KEY_ENV, str(_key_file(tmp_path, "a")))
    first = _project_artifact(_VERIFIED_LEAK)
    again = _project_artifact(_VERIFIED_LEAK)
    assert (first.run_id, first.artifact_id) == (again.run_id, again.artifact_id)
    monkeypatch.setenv(projection.PROJECTION_KEY_ENV, str(_key_file(tmp_path, "b")))
    other = _project_artifact(_VERIFIED_LEAK)
    assert other.run_id != first.run_id and other.artifact_id != first.artifact_id
    assert other.metric_refs != first.metric_refs


def _denied(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(projection.PROJECTION_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(projection.PROJECTION_KEY_ENV, value)
    with pytest.raises(ProjectionDenied) as err:
        _project_artifact(_VERIFIED_LEAK)
    return err.value.reason


def test_projection_without_a_usable_key_fails_closed(tmp_path, monkeypatch):
    assert _denied(monkeypatch, None) == "projection_key_unconfigured"
    assert _denied(monkeypatch, "") == "projection_key_unconfigured"
    assert _denied(monkeypatch, "relative.key") == "projection_key_unconfigured"
    missing = str(tmp_path / "missing.key")
    assert _denied(monkeypatch, missing) == "projection_key_unconfigured"
    short = _key_file(tmp_path, "short", b"x" * 31)
    assert _denied(monkeypatch, str(short)) == "projection_key_unconfigured"


def test_projection_key_inside_a_git_work_tree_fails_closed(tmp_path, monkeypatch):
    tree = tmp_path / "clone"
    (tree / ".git").mkdir(parents=True)
    key = tree / "sub" / "projection.key"
    key.parent.mkdir()
    key.write_bytes(b"k" * 64)
    assert _denied(monkeypatch, str(key)) == "projection_key_in_repo"


def test_opaque_id_refuses_a_short_key():
    with pytest.raises(ProjectionDenied):
        projection.opaque_id("run", "x", b"short")


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
    assert proj["dropped_unvetted"] >= 4 and proj["unvetted_names_emitted"] == 0
    assert "NVDA" not in out and "4242424" not in out
    assert summary["scan_hits"] == []
    assert scan_text(out) == []


def test_policy_probe_projection_fails_closed_without_a_key(monkeypatch):
    from openbb_agents.hermes_integration import policy_probe

    monkeypatch.delenv(projection.PROJECTION_KEY_ENV)
    ok, summary = policy_probe._projection_check()
    assert ok is False
    assert summary["denied"] == "projection_key_unconfigured"


def test_policy_probe_counts_unvetted_names():
    from openbb_agents.hermes_integration import policy_probe

    leaky = EvidenceProjection.model_construct(
        finding_codes=("TOP_HOLDING_NVDA",),
        aggregate_buckets={"nvda": "25-50%", "top_weight": "25-50%"},
        metric_refs=(f"[[metric:run_{'0' * 16}:art_{'0' * 16}:market_value_2]]",),
    )
    assert policy_probe._unvetted_names(leaky) == 3


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


# --- local-only routing (#1339-T03 part B) -------------------------------------------
# Hermes side: memory, user profile and shared metrics; LiteLLM side: the private
# alias selector. All configs are synthetic fixtures.

HERMES_FX = FIXTURES / "hermes"
LITELLM_FX = FIXTURES / "litellm"
PROFILE_FX = FIXTURES / "profiles" / "synthetic-ok.yaml"
PRIVATE = "finance-private"
LOCAL_PORT = 8080
_DROP = object()


def _route_profile(tmp_path: Path, allow=(PRIVATE,)):
    data = yaml.safe_load(PROFILE_FX.read_text(encoding="utf-8"))
    data["private_alias_allowlist"] = list(allow)
    data["local_backends"] = [f"http://127.0.0.1:{LOCAL_PORT}"]
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_profile(out), out


def _hermes_verdict(tmp_path: Path, mutate=None, name="config-finance-safe.yaml"):
    data = yaml.safe_load((HERMES_FX / name).read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(data)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(data), encoding="utf-8")
    profile, _ = _route_profile(tmp_path)
    return hermes_config.evaluate_route(hermes_config.read_route_facts(cfg), profile)


def _memory(**values):
    def mutate(data):
        for key, value in values.items():
            if value is _DROP:
                data["memory"].pop(key, None)
            else:
                data["memory"][key] = value

    return mutate


def test_finance_safe_fixture_admits_the_route_with_memory_off(tmp_path):
    verdict = _hermes_verdict(tmp_path)
    assert verdict.blocked is False, verdict.reasons


@pytest.mark.parametrize(
    ("mutate", "reasons"),
    [
        (_memory(memory_enabled=True), {"memory_enabled_not_false"}),
        (_memory(memory_enabled=_DROP), {"memory_enabled_not_false"}),
        (_memory(memory_enabled="false"), {"memory_enabled_not_false"}),
        (_memory(user_profile_enabled=True), {"user_profile_enabled_not_false"}),
        (_memory(user_profile_enabled=_DROP), {"user_profile_enabled_not_false"}),
        (_memory(user_profile_enabled=0), {"user_profile_enabled_not_false"}),
        (
            lambda d: d.pop("memory"),  # upstream default: both on
            {"memory_enabled_not_false", "user_profile_enabled_not_false"},
        ),
        (
            lambda d: d.__setitem__("memory", "off"),
            {"memory_enabled_not_false", "user_profile_enabled_not_false"},
        ),
    ],
)
def test_route_policy_blocks_hermes_memory_or_user_profile_enabled(
    tmp_path, mutate, reasons
):
    verdict = _hermes_verdict(tmp_path, mutate)
    assert verdict.blocked and reasons <= set(verdict.reasons), verdict.reasons


@pytest.mark.parametrize(
    "metrics",
    [{"enabled": True}, {"enabled": True, "send": True}, {"send": True}],
)
def test_route_policy_blocks_shared_metrics_enabled(tmp_path, metrics):
    def mutate(data):
        data["telemetry"]["shared_metrics"] = metrics

    verdict = _hermes_verdict(tmp_path, mutate)
    assert verdict.blocked and "telemetry_enabled" in verdict.reasons


def test_memory_keys_are_consumed_keys():
    # The seam-contract test pins every consumed key in the upstream-trimmed fixture.
    assert {"memory.memory_enabled", "memory.user_profile_enabled"} <= set(
        hermes_config.CONSUMED_KEYS
    )


def test_hosted_fallback_config_blocks_the_route_naming_the_fallback(tmp_path):
    verdict = _hermes_verdict(tmp_path, name="config-fallback-hosted.yaml")
    assert verdict.blocked and "fallback_providers_set" in verdict.reasons


# LiteLLM side: which aliases the private operation may use.


def _gateway(tmp_path: Path, name="finance-local.yaml", mutate=None):
    text = (LITELLM_FX / name).read_text(encoding="utf-8")
    text = text.replace("PORT_LOCAL", str(LOCAL_PORT)).replace("PORT_HOSTED", "8081")
    data = yaml.safe_load(text)
    if mutate is not None:
        mutate(data)
    cfg = tmp_path / f"proxy-{name}"
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    profile, _ = _route_profile(tmp_path)
    return litellm_config.read_gateway_facts(cfg, profile), profile


def _local_entry(name):
    return {
        "model_name": name,
        "litellm_params": {
            "model": "openai/local-other",
            "api_base": f"http://127.0.0.1:{LOCAL_PORT}/v1",
        },
    }


def test_private_selector_admits_the_local_allowlisted_served_alias(tmp_path):
    facts, profile = _gateway(tmp_path)
    assert litellm_config.select_private_aliases(facts, profile) == (PRIVATE,)
    assert litellm_config.select_private_aliases(
        facts, profile, served={PRIVATE, "hosted-a"}
    ) == (PRIVATE,)


def test_private_selector_excludes_local_aliases_outside_the_allowlist(tmp_path):
    facts, profile = _gateway(
        tmp_path, mutate=lambda d: d["model_list"].append(_local_entry("scratch"))
    )
    assert litellm_config.select_private_aliases(facts, profile) == (PRIVATE,)


def test_private_selector_excludes_aliases_the_gateway_does_not_serve(tmp_path):
    facts, profile = _gateway(tmp_path)
    assert litellm_config.select_private_aliases(facts, profile, served=set()) == ()
    assert (
        litellm_config.select_private_aliases(facts, profile, served={"hosted-a"}) == ()
    )


def _hosted_member(data):
    data["model_list"].append(
        {"model_name": PRIVATE, "litellm_params": {"model": "github_copilot/x"}}
    )


def _hosted_wildcard(data):
    data["model_list"].append(
        {"model_name": "finance-*", "litellm_params": {"model": "github_copilot/x"}}
    )


def _logging_on(data):
    data["litellm_settings"]["turn_off_message_logging"] = False


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("finance-local.yaml", _hosted_member),  # group with a hosted member
        ("finance-local.yaml", _hosted_wildcard),  # captured by a hosted group
        ("local-with-hosted-fallback.yaml", None),  # hosted fallback target
        ("finance-local.yaml", _logging_on),  # gateway itself not admitted
        ("existing-shape-hosted-only.yaml", None),  # alias is hosted
    ],
)
def test_private_selector_is_empty_unless_the_gateway_is_local_only(
    tmp_path, name, mutate
):
    facts, profile = _gateway(tmp_path, name=name, mutate=mutate)
    assert litellm_config.select_private_aliases(facts, profile) == ()
    assert litellm_config.select_private_aliases(facts, profile, served={PRIVATE}) == ()


class _Served(handshake.LoopbackTransport):
    """Gateway stand-in whose scoped key serves only the private alias."""

    def http_get(self, host, port, path, headers, timeout):
        body = json.dumps({"data": [{"id": PRIVATE}]}).encode()
        return handshake.ProbeResult(kind="ok", status=200, body=body)


def test_gateway_edge_blocks_a_served_alias_that_is_not_local_only(tmp_path):
    hosted, profile = _gateway(tmp_path, name="local-with-hosted-fallback.yaml")
    local, _ = _gateway(tmp_path)
    cfg = tmp_path / "hermes.yaml"
    cfg.write_text(
        (HERMES_FX / "config-finance-safe.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    facts = hermes_config.read_route_facts(cfg)

    def edge(gw):
        return handshake.probe_gateway(
            profile, facts, {}, _Served(), 1.0, gateway_facts=gw
        )

    blocked = edge(hosted)
    assert blocked.failed_layer is not None and blocked.failed_layer.value == "route"
    assert blocked.detail == "private_alias_not_local_only"
    assert edge(local).detail == "private_alias_served"
    assert edge(None).detail == "private_alias_served"  # no proxy config: unchanged


def _preflight(tmp_path, capsys, hermes, litellm=None):
    _, profile_path = _route_profile(tmp_path)
    argv = ["--profile", str(profile_path), "--hermes-config", str(hermes)]
    if litellm is not None:
        argv += ["--litellm-config", str(litellm)]
    code = main([*argv, "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    return code, {c["name"]: c for c in report["components"]}, report


def test_preflight_hosted_fallback_config_fails_the_route_layer(tmp_path, capsys):
    code, comps, report = _preflight(
        tmp_path, capsys, HERMES_FX / "config-fallback-hosted.yaml"
    )
    assert code == 2 and "route" in report["failed_layers"]
    assert comps["route"]["failed_layer"] == "route"
    assert "fallback_providers_set" in comps["route"]["detail"]


def test_preflight_reports_the_selectable_private_aliases(tmp_path, capsys):
    text = (LITELLM_FX / "finance-local.yaml").read_text(encoding="utf-8")
    proxy = tmp_path / "proxy.yaml"
    proxy.write_text(text.replace("PORT_LOCAL", str(LOCAL_PORT)), encoding="utf-8")
    _, comps, _ = _preflight(
        tmp_path, capsys, HERMES_FX / "config-finance-safe.yaml", proxy
    )
    assert comps["route"]["failed_layer"] is None, comps["route"]
    assert comps["litellm_routes"]["detail"].startswith("private_route=ADMITTED")
    assert "selectable=1" in comps["litellm_routes"]["detail"]


def test_preflight_probe_passes_the_proxy_config_to_the_gateway_edge(tmp_path):
    # The transport answers every HTTP probe with the private alias only and
    # refuses every TCP connect, so no real service is contacted.
    class _Offline(_Served):
        def tcp_connect(self, host, port, timeout):
            return handshake.ProbeResult(kind="refused")

    text = (LITELLM_FX / "local-with-hosted-fallback.yaml").read_text(encoding="utf-8")
    proxy = tmp_path / "proxy.yaml"
    proxy.write_text(
        text.replace("PORT_LOCAL", str(LOCAL_PORT)).replace("PORT_HOSTED", "8081"),
        encoding="utf-8",
    )
    profile, _ = _route_profile(tmp_path)
    report = run_preflight(
        profile,
        PreflightOptions(
            openbb_settings=FIXTURES / "settings" / "synthetic-user_settings.json",
            hermes_config_path=HERMES_FX / "config-finance-safe.yaml",
            litellm_config_path=proxy,
            probe="loopback",
        ),
        env={},
        transport=_Offline(),
    )
    edge = next(e for e in report.edges if e.name == "hermes_litellm")
    assert edge.detail == "private_alias_not_local_only", edge


# --- memory switches under Hermes YAML semantics and the managed overlay ------------


def _safe_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    text = (HERMES_FX / "config-finance-safe.yaml").read_text(encoding="utf-8")
    cfg.write_text(text, encoding="utf-8")
    return cfg


def _managed_memory(tmp_path: Path, text: str) -> Path:
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text(text, encoding="utf-8")
    return managed / "config.yaml"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("memory:\n  memory_enabled: y\n", "memory_enabled_not_false"),
        ("memory:\n  user_profile_enabled: Y\n", "user_profile_enabled_not_false"),
        ("memory:\n  memory_enabled: 'false'\n", "memory_enabled_not_false"),
        ("memory: on\n", "memory_enabled_not_false"),
    ],
)
def test_managed_overlay_cannot_turn_memory_on_unseen(tmp_path, text, reason):
    profile, _ = _route_profile(tmp_path)
    facts = hermes_config.read_route_facts(
        _safe_cfg(tmp_path), _managed_memory(tmp_path, text)
    )
    verdict = hermes_config.evaluate_route(facts, profile)
    assert verdict.blocked and reason in verdict.reasons, verdict.reasons


def test_memory_n_is_yaml11_false_as_in_hermes(tmp_path):
    profile, _ = _route_profile(tmp_path)
    text = "memory:\n  memory_enabled: n\n  user_profile_enabled: N\n"
    facts = hermes_config.read_route_facts(
        _safe_cfg(tmp_path), _managed_memory(tmp_path, text)
    )
    verdict = hermes_config.evaluate_route(facts, profile)
    memory = {"memory_enabled_not_false", "user_profile_enabled_not_false"}
    assert not memory & set(verdict.reasons), verdict.reasons


def test_duplicate_memory_key_is_refused(tmp_path):
    text = "memory:\n  memory_enabled: false\n  memory_enabled: true\n"
    with pytest.raises(hermes_config.ConfigDuplicateKeyError):
        hermes_config.read_route_facts(
            _safe_cfg(tmp_path), _managed_memory(tmp_path, text)
        )
