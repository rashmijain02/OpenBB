"""Handshake matrix with unavailable-service outcomes (#1338-T02).

Probes only reach loopback servers that these tests start on ephemeral ports.
"""

# ruff: noqa: D101, D102, D103, S104

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration import handshake, hermes_config
from openbb_agents.hermes_integration.hermes_preflight import main
from openbb_agents.hermes_integration.models import (
    EdgeStatus,
    FailedLayer,
    HealthLevel,
    Presence,
)
from openbb_agents.hermes_integration.profile import load_profile

from .conftest import FIXTURES, SENTINELS

PROFILE = FIXTURES / "profiles" / "synthetic-ok.yaml"
HERMES = FIXTURES / "hermes"
SETTINGS_OK = FIXTURES / "settings" / "synthetic-user_settings.json"
ALIAS = "finance-private"
KEY_SENTINEL = "SYNTHETIC-GATEWAY-KEY-SENTINEL"
PLACEHOLDER = "http://127.0.0.1:4000"


def _free_closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Recorder(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        srv = self.server
        srv.seen.append((self.path, self.headers.get("Authorization")))
        if srv.delay:
            time.sleep(srv.delay)
        body = srv.body
        try:
            self.send_response(srv.status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


@contextmanager
def serve(status=200, body=b"{}", delay=0.0):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    srv.status, srv.body, srv.delay, srv.seen = status, body, delay, []
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _models(*ids):
    return json.dumps({"data": [{"id": i} for i in ids]}).encode()


def _profile(base, **over):
    data = load_profile(PROFILE).model_dump()
    data["gateway_base_url"] = base
    data["private_alias_allowlist"] = [ALIAS]
    data.update(over)
    return type(load_profile(PROFILE)).model_validate(data)


def _config(tmp_path, name, base=PLACEHOLDER) -> Path:
    text = (HERMES / name).read_text(encoding="utf-8").replace(PLACEHOLDER, base)
    out = tmp_path / name
    out.write_text(text, encoding="utf-8")
    return out


class Recording(handshake.LoopbackTransport):
    def __init__(self):
        self.log: list[tuple[str, str, int]] = []

    def http_get(self, host, port, path, headers, timeout):
        self.log.append(("http", host, port))
        return super().http_get(host, port, path, headers, timeout)

    def tcp_connect(self, host, port, timeout):
        self.log.append(("tcp", host, port))
        return super().tcp_connect(host, port, timeout)


def _edge(edges, name):
    return next(e for e in edges if e.name == name)


def _run(tmp_path, base, cfg="config-finance-safe.yaml", transport=None, **kw):
    profile = _profile(base)
    facts = hermes_config.read_route_facts(_config(tmp_path, cfg, base))
    env = kw.pop("env", {})
    kw.setdefault("timeout", 2.0)
    return handshake.run_handshake(
        profile,
        facts,
        env=env,
        transport=transport or Recording(),
        options=handshake.HandshakeOptions(**kw),
    )


# --- stopped model -------------------------------------------------------------


def test_refused_loopback_port_is_backend_unavailable(tmp_path):
    base = f"http://127.0.0.1:{_free_closed_port()}"
    edges = _run(tmp_path, base, timeout=10.0)  # Windows needs ~2s to report a refusal
    gw = _edge(edges, "hermes_litellm")
    assert gw.status is EdgeStatus.UNAVAILABLE
    assert gw.detail == "gateway_refused"  # a refusal, not a timeout
    assert gw.callable is False
    assert gw.failed_layer is FailedLayer.BACKEND
    down = _edge(edges, "litellm_backend")
    assert down.status is EdgeStatus.UNAVAILABLE
    assert down.failed_layer is FailedLayer.BACKEND


def test_unavailable_primary_does_not_probe_any_other_route(tmp_path):
    base = f"http://127.0.0.1:{_free_closed_port()}"
    rec = Recording()
    _run(tmp_path, base, transport=rec, backend_base_url="http://127.0.0.1:9")
    assert rec.log == [("http", "127.0.0.1", int(base.rsplit(":", 1)[1]))]


@pytest.mark.parametrize(
    "cfg",
    [
        "config-fallback-hosted.yaml",
        "config-nonloopback.yaml",
        "config-auto-provider.yaml",
    ],
)
def test_blocked_route_is_never_probed(tmp_path, cfg):
    with serve(body=_models(ALIAS)) as (srv, base):
        rec = Recording()
        edges = _run(tmp_path, base, cfg=cfg, transport=rec)
        assert rec.log == [] and srv.seen == []
    gw = _edge(edges, "hermes_litellm")
    assert gw.status is EdgeStatus.BLOCKED
    assert gw.failed_layer is FailedLayer.ROUTE


# --- authenticated vs callable --------------------------------------------------


def test_401_from_test_owned_loopback_server_is_auth_layer(tmp_path):
    with serve(status=401) as (_srv, base):
        gw = _edge(_run(tmp_path, base), "hermes_litellm")
    assert gw.failed_layer is FailedLayer.AUTH
    assert gw.callable is False
    assert gw.level is HealthLevel.CONFIGURED


def test_200_with_private_alias_is_callable_and_key_is_not_echoed(tmp_path):
    profile_kw = {"gateway_key_env": "HFP_TEST_KEY"}
    with serve(body=_models(ALIAS)) as (srv, base):
        profile = _profile(base, **profile_kw)
        facts = hermes_config.read_route_facts(
            _config(tmp_path, "config-finance-safe.yaml", base)
        )
        edges = handshake.run_handshake(
            profile,
            facts,
            env={"HFP_TEST_KEY": "SYNTHETIC-SCOPED-KEY"},
            transport=Recording(),
            options=handshake.HandshakeOptions(timeout=2.0),
        )
        assert srv.seen[0][0] == "/v1/models"
        assert srv.seen[0][1] == "Bearer SYNTHETIC-SCOPED-KEY"  # sent, never reported
    gw = _edge(edges, "hermes_litellm")
    assert gw.callable is True and gw.failed_layer is None
    assert gw.presence["gateway_key"] is Presence.PRESENT
    blob = "".join(e.model_dump_json() for e in edges)
    assert "SYNTHETIC-SCOPED-KEY" not in blob and KEY_SENTINEL not in blob


def test_200_without_private_alias_is_authenticated_not_callable(tmp_path):
    with serve(body=_models("some-hosted-alias")) as (_s, base):
        gw = _edge(_run(tmp_path, base), "hermes_litellm")
    assert gw.level is HealthLevel.AUTHENTICATED
    assert gw.callable is False
    assert gw.failed_layer is FailedLayer.ROUTE


def test_key_that_lists_hosted_aliases_is_not_scoped(tmp_path):
    with serve(body=_models(ALIAS, "hosted-a")) as (_s, base):
        edges = _run(tmp_path, base)
    gw = _edge(edges, "hermes_litellm")
    assert gw.status is EdgeStatus.BLOCKED
    assert gw.failed_layer is FailedLayer.AUTH
    assert gw.detail == "gateway_key_not_scoped"
    assert gw.callable is False
    assert "hosted-a" not in gw.model_dump_json()
    assert _edge(edges, "litellm_backend").status is EdgeStatus.NOT_EVALUATED


def test_5xx_is_backend_unavailable(tmp_path):
    with serve(status=503) as (_s, base):
        gw = _edge(_run(tmp_path, base), "hermes_litellm")
    assert gw.status is EdgeStatus.UNAVAILABLE
    assert gw.failed_layer is FailedLayer.BACKEND


def test_probe_timeout_is_unavailable_not_success(tmp_path, caplog):
    with serve(body=_models(ALIAS), delay=1.5) as (_s, base), caplog.at_level(
        logging.WARNING, logger=handshake.__name__
    ):
        gw = _edge(_run(tmp_path, base, timeout=0.2), "hermes_litellm")
    assert gw.status is EdgeStatus.UNAVAILABLE and gw.callable is False
    assert gw.failed_layer is FailedLayer.BACKEND
    warns = [r for r in caplog.records if "probe timeout" in r.getMessage()]
    assert len(warns) == 1


def test_local_backend_edge_probed_only_when_gateway_callable(tmp_path):
    with serve(body=_models(ALIAS)) as (_g, base), serve(status=200) as (bsrv, burl):
        edges = _run(tmp_path, base, backend_base_url=burl)
        assert _edge(edges, "litellm_backend").callable is True
        assert bsrv.seen  # the backend was reached through the gateway-ok path
        edges = _run(tmp_path, base)  # no backend url supplied
        assert _edge(edges, "litellm_backend").status is EdgeStatus.NOT_EVALUATED


# --- MCP admission --------------------------------------------------------------

TOOLS = [
    {"name": "get_quote", "description": "q", "inputSchema": {"type": "object"}},
    {"name": "get_scan", "description": "s", "inputSchema": {"type": "object"}},
]


def test_mcp_tool_schema_hash_matches_is_admitted(tmp_path):
    expected = handshake.catalog_sha256(TOOLS)
    edge = handshake.check_mcp_catalog(TOOLS, expected)
    assert edge.level is HealthLevel.ADMITTED and edge.failed_layer is None
    # order-insensitive
    assert handshake.catalog_sha256(list(reversed(TOOLS))) == expected


def test_mcp_tool_schema_hash_drift_blocks_admission():
    expected = handshake.catalog_sha256(TOOLS)
    drifted = [dict(TOOLS[0], inputSchema={"type": "object", "x": 1}), TOOLS[1]]
    edge = handshake.check_mcp_catalog(drifted, expected)
    assert edge.failed_layer is FailedLayer.SCHEMA
    assert edge.status is EdgeStatus.BLOCKED and edge.callable is False


def test_mcp_catalog_without_pin_is_not_admitted():
    edge = handshake.check_mcp_catalog(TOOLS, None)
    assert edge.failed_layer is FailedLayer.SCHEMA and edge.detail.startswith(
        "no_pinned_hash"
    )


def test_mcp_http_refused_is_unavailable(tmp_path):
    port = _free_closed_port()
    edge = handshake.probe_mcp_http(
        f"http://127.0.0.1:{port}", handshake.LoopbackTransport(), 1.0
    )
    assert edge.status is EdgeStatus.UNAVAILABLE
    assert edge.failed_layer is FailedLayer.BACKEND


# --- WebUI edge -------------------------------------------------------------------


def _webui_env(tmp_path, **over):
    venv = tmp_path / "venv"
    venv.mkdir(exist_ok=True)
    env = {
        "HFP_HERMES_RUNTIME_VENV": str(venv),
        "HERMES_WEBUI_PYTHON": str(venv / "Scripts" / "python.exe"),
        "HERMES_WEBUI_HOST": "127.0.0.1",
        "HERMES_WEBUI_PASSWORD": "SYNTHETIC-WEBUI-PASSWORD",
    }
    env.update(over)
    return env


def test_webui_loopback_with_password_and_same_python_passes_static_checks(tmp_path):
    edge = handshake.check_webui(
        _profile("http://127.0.0.1:1"), _webui_env(tmp_path), Recording(), 1.0
    )
    assert edge.failed_layer is None and edge.level is HealthLevel.CONFIGURED
    assert edge.presence["webui_password"] is Presence.PRESENT
    assert "SYNTHETIC-WEBUI-PASSWORD" not in edge.model_dump_json()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "::"])
def test_webui_bound_non_loopback_blocks_auth(tmp_path, host):
    env = _webui_env(tmp_path, HERMES_WEBUI_HOST=host)
    edge = handshake.check_webui(_profile("http://127.0.0.1:1"), env, Recording(), 1.0)
    assert edge.failed_layer is FailedLayer.AUTH and "non_loopback_bind" in edge.detail


def test_webui_without_password_blocks_auth(tmp_path):
    env = _webui_env(tmp_path)
    del env["HERMES_WEBUI_PASSWORD"]
    edge = handshake.check_webui(_profile("http://127.0.0.1:1"), env, Recording(), 1.0)
    assert edge.failed_layer is FailedLayer.AUTH and "no_password" in edge.detail
    assert edge.presence["webui_password"] is Presence.ABSENT


def test_webui_python_differs_from_hermes_python_blocks_abi(tmp_path):
    env = _webui_env(
        tmp_path, HERMES_WEBUI_PYTHON=str(tmp_path / "other" / "python.exe")
    )
    edge = handshake.check_webui(_profile("http://127.0.0.1:1"), env, Recording(), 1.0)
    assert edge.failed_layer is FailedLayer.ABI


def test_webui_health_probe_refused_is_unavailable_process_layer(tmp_path):
    port = _free_closed_port()
    env = _webui_env(tmp_path, HERMES_WEBUI_PORT=str(port))
    edge = handshake.check_webui(_profile("http://127.0.0.1:1"), env, Recording(), 1.0)
    assert edge.status is EdgeStatus.UNAVAILABLE
    assert edge.failed_layer is FailedLayer.PROCESS


def test_webui_health_200_is_callable(tmp_path):
    with serve(body=b"ok") as (srv, base):
        env = _webui_env(tmp_path, HERMES_WEBUI_PORT=base.rsplit(":", 1)[1])
        edge = handshake.check_webui(
            _profile("http://127.0.0.1:1"), env, Recording(), 1.0
        )
        assert srv.seen[0][0] == "/health"
    assert edge.callable is True


# --- OpenBB -> MySQL ----------------------------------------------------------------


def _settings(tmp_path, host, port):
    data = json.loads(SETTINGS_OK.read_text(encoding="utf-8"))
    data["credentials"]["mysql_host"] = host
    data["credentials"]["mysql_port"] = str(port)
    out = tmp_path / "settings.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def test_mysql_closed_loopback_port_is_database_unavailable(tmp_path):
    path = _settings(tmp_path, "127.0.0.1", _free_closed_port())
    edge = handshake.probe_mysql(path, {}, handshake.LoopbackTransport(), 10.0)
    assert edge.status is EdgeStatus.UNAVAILABLE
    assert edge.detail == "mysql_refused"
    assert edge.failed_layer is FailedLayer.DATABASE


def test_mysql_listening_port_is_reachable_but_not_callable(tmp_path):
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        path = _settings(tmp_path, "127.0.0.1", srv.getsockname()[1])
        edge = handshake.probe_mysql(path, {}, handshake.LoopbackTransport(), 1.0)
    assert edge.status is EdgeStatus.OK and edge.level is HealthLevel.CONFIGURED
    assert edge.callable is False and "tcp_reachable_only" in edge.detail


def test_mysql_non_loopback_host_is_blocked_and_not_probed(tmp_path):
    rec = Recording()
    path = _settings(tmp_path, "db.example.invalid", 3306)
    edge = handshake.probe_mysql(path, {}, rec, 1.0)
    assert rec.log == []
    assert (
        edge.status is EdgeStatus.BLOCKED and edge.failed_layer is FailedLayer.DATABASE
    )
    assert SENTINELS["account"] not in edge.model_dump_json()


# --- transport contract ----------------------------------------------------------------


def test_webui_non_numeric_port_is_blocked_process_layer(tmp_path):
    rec = Recording()
    edge = handshake.check_webui(
        _profile("http://127.0.0.1:1"),
        _webui_env(tmp_path, HERMES_WEBUI_PORT="80a"),
        rec,
        1.0,
    )
    assert edge.status is EdgeStatus.BLOCKED
    assert edge.failed_layer is FailedLayer.PROCESS
    assert edge.detail == "webui_port_not_numeric" and rec.log == []


def test_mysql_endpoint_from_non_mapping_settings_uses_env_fallback(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text('"just a string"', encoding="utf-8")
    port = _free_closed_port()
    rec = Recording()
    edge = handshake.probe_mysql(bad, {"DB_PORT": str(port)}, rec, 1.0)
    assert rec.log == [("tcp", "localhost", port)]
    assert edge.status is EdgeStatus.UNAVAILABLE


def test_transport_refuses_non_loopback_host_before_any_connect():
    t = handshake.LoopbackTransport()
    with pytest.raises(ValueError):
        t.http_get("203.0.113.9", 80, "/", {}, 1.0)
    with pytest.raises(ValueError):
        t.tcp_connect("gateway.example.invalid", 80, 1.0)


# --- route facts reader (seam contract + policy) -----------------------------------------


def test_reader_consumed_keys_exist_in_pinned_defaults_fixture():
    data = yaml.safe_load(
        (HERMES / "config-pinned-defaults.yaml").read_text(encoding="utf-8")
    )
    for dotted in hermes_config.CONSUMED_KEYS:
        node = data
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, f"missing {dotted}"
            node = node[part]


def test_secret_shaped_route_keys_are_presence_only(tmp_path):
    cfg = _config(tmp_path, "config-finance-safe.yaml")
    facts = hermes_config.read_route_facts(cfg)
    assert facts.api_key is Presence.PRESENT
    assert KEY_SENTINEL not in facts.model_dump_json()


def _verdict(tmp_path, name, base=PLACEHOLDER):
    facts = hermes_config.read_route_facts(_config(tmp_path, name, base))
    return hermes_config.evaluate_route(facts, _profile(base))


def test_finance_safe_config_is_admitted(tmp_path):
    verdict = _verdict(tmp_path, "config-finance-safe.yaml")
    assert verdict.blocked is False and verdict.reasons == []


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("config-auto-provider.yaml", "provider_not_custom"),
        ("config-fallback-hosted.yaml", "fallback_providers_set"),
        ("config-adopt-logins.yaml", "adopt_external_logins_enabled"),
        ("config-nonloopback.yaml", "base_url_not_loopback"),
        ("config-pinned-defaults.yaml", "provider_not_custom"),
    ],
)
def test_route_policy_blocks_hosted_vectors(tmp_path, name, reason):
    verdict = _verdict(tmp_path, name)
    assert verdict.blocked and reason in verdict.reasons


def test_route_policy_blocks_delegation_fallback_and_auxiliary_provider(tmp_path):
    cfg = _config(tmp_path, "config-finance-safe.yaml")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["delegation"]["fallback_providers"] = [{"provider": "openrouter"}]
    data["auxiliary"]["vision"]["provider"] = "auto"
    cfg.write_text(yaml.safe_dump(data), encoding="utf-8")
    verdict = hermes_config.evaluate_route(
        hermes_config.read_route_facts(cfg), _profile(PLACEHOLDER)
    )
    assert "delegation_fallback_providers_set" in verdict.reasons
    assert "auxiliary_vision_provider_not_custom" in verdict.reasons


def test_route_policy_blocks_base_url_not_the_profile_gateway(tmp_path):
    facts = hermes_config.read_route_facts(
        _config(tmp_path, "config-finance-safe.yaml")
    )
    verdict = hermes_config.evaluate_route(facts, _profile("http://127.0.0.1:4999"))
    assert "base_url_not_profile_gateway" in verdict.reasons


def test_route_policy_blocks_alias_outside_allowlist(tmp_path):
    facts = hermes_config.read_route_facts(
        _config(tmp_path, "config-finance-safe.yaml")
    )
    verdict = hermes_config.evaluate_route(
        facts, _profile(PLACEHOLDER, private_alias_allowlist=["other"])
    )
    assert "model_not_private_alias" in verdict.reasons


# --- fail-closed route policy (#1338 SECURITY-1) ------------------------------------


def _mutated_verdict(tmp_path, mutate):
    cfg = _config(tmp_path, "config-finance-safe.yaml")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    mutate(data)
    cfg.write_text(yaml.safe_dump(data), encoding="utf-8")
    return hermes_config.evaluate_route(
        hermes_config.read_route_facts(cfg), _profile(PLACEHOLDER)
    )


def _drop_aux(task):
    return lambda d: d["auxiliary"].pop(task)


def _set_path(dotted, value):
    def mutate(data):
        node = data
        *head, last = dotted.split(".")
        for part in head:
            node = node.setdefault(part, {})
        node[last] = value

    return mutate


HOSTED = "https://hosted.invalid/v1"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_set_path("fallback_model", {"provider": "openrouter"}), "fallback_model_set"),
        (_set_path("delegation.provider", "openrouter"), "delegation_provider_set"),
        (_set_path("delegation.base_url", HOSTED), "delegation_base_url_set"),
        (_set_path("delegation.model", "hosted-model"), "delegation_model_set"),
        (_set_path("delegation.backend", "codex"), "delegation_backend_not_default"),
        (
            _set_path("delegation.backends", {"x": {"model_map": {"a": "b"}}}),
            "delegation_backends_set",
        ),
        (_drop_aux("title_generation"), "auxiliary_title_generation_unset"),
        (_drop_aux("moa_aggregator"), "auxiliary_moa_aggregator_unset"),
        (
            _set_path("auxiliary.review.base_url", "http://127.0.0.1:4999/v1"),
            "auxiliary_review_base_url_not_profile_gateway",
        ),
        (
            _set_path("auxiliary.curator.model", "hosted-alias"),
            "auxiliary_curator_model_not_private_alias",
        ),
        (
            _set_path("auxiliary.openrouter_model", "x/y"),
            "auxiliary_openrouter_model_set",
        ),
        (
            _set_path("platforms.api_server.extra.model_routes", {"a": {"model": "m"}}),
            "platforms_api_server_model_routes_set",
        ),
        (
            _set_path("platforms.telegram.enabled", True),
            "unvetted_key:platforms.telegram",
        ),
        (
            _set_path("smart_model_routing", {"enabled": True}),
            "smart_model_routing_not_disabled",
        ),
        (
            _set_path("providers", {"openrouter": {"api_key": "SYNTHETIC"}}),
            "providers_openrouter_not_loopback",
        ),
        (
            _set_path("custom_providers", [{"name": "x", "base_url": HOSTED}]),
            "custom_providers_0_not_loopback",
        ),
        (_set_path("model_aliases", {"fast": "hosted"}), "model_aliases_set"),
        (_set_path("memory.provider", "honcho"), "memory_provider_set"),
        (_set_path("telemetry.shared_metrics.enabled", True), "telemetry_enabled"),
        (
            _set_path("mcp_servers", {"notes": {"url": HOSTED}}),
            "mcp_servers_notes_not_loopback",
        ),
        (_set_path("x_search", {"model": "hosted"}), "unvetted_key:x_search"),
        (_set_path("brand_new_key", 1), "unvetted_key:brand_new_key"),
    ],
)
def test_route_policy_blocks_every_unread_routing_key(tmp_path, mutate, reason):
    verdict = _mutated_verdict(tmp_path, mutate)
    assert verdict.blocked and reason in verdict.reasons, verdict.reasons


@pytest.mark.parametrize(
    "mutate",
    [
        _set_path("smart_model_routing", {"enabled": False}),
        _set_path("providers", {"local": {"base_url": "http://127.0.0.1:8080/v1"}}),
        _set_path("mcp_servers", {"openbb": {"command": "uvx"}}),
        _set_path("display", {"compact": True}),
        _set_path("delegation.backend", "default"),
    ],
)
def test_route_policy_admits_vetted_harmless_keys(tmp_path, mutate):
    verdict = _mutated_verdict(tmp_path, mutate)
    assert verdict.blocked is False, verdict.reasons


def test_route_policy_unvetted_key_label_is_sanitised(tmp_path):
    verdict = _mutated_verdict(tmp_path, _set_path("evil\nkey" + "x" * 80, 1))
    keys = [r for r in verdict.reasons if r.startswith("unvetted_key:")]
    assert keys and "\n" not in keys[0] and len(keys[0]) <= len("unvetted_key:") + 40


def test_allowlists_are_derived_from_pinned_default_config():
    pinned = yaml.safe_load(
        (HERMES / "pinned-default-keys.yaml").read_text(encoding="utf-8")
    )
    assert tuple(sorted(pinned["auxiliary_tasks"])) == hermes_config.AUXILIARY_TASKS
    assert hermes_config.AUXILIARY_SETTINGS <= set(pinned["auxiliary_settings"])
    legacy = {
        "fallback_model",
        "custom_providers",
        "smart_model_routing",
        "platforms",
        "model_aliases",
        "platform_toolsets",
        "mcp_servers",
    }
    vetted = hermes_config.HARMLESS_TOP_LEVEL | hermes_config.POLICED_TOP_LEVEL
    assert vetted <= set(pinned["top_level"]) | legacy


def test_unreadable_config_raises_value_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        hermes_config.read_route_facts(bad)


# --- CLI ------------------------------------------------------------------------------------


def _cli_profile(tmp_path, base) -> Path:
    data = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    data["gateway_base_url"] = base
    data["private_alias_allowlist"] = [ALIAS]
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return out


def test_cli_probe_loopback_closed_gateway_exit_2_with_backend_edges(tmp_path, capsys):
    base = f"http://127.0.0.1:{_free_closed_port()}"
    code = main(
        [
            "--profile",
            str(_cli_profile(tmp_path, base)),
            "--hermes-config",
            str(_config(tmp_path, "config-finance-safe.yaml", base)),
            "--probe",
            "loopback",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    assert code == 2
    edges = {e["name"]: e for e in report["edges"]}
    assert edges["hermes_litellm"]["failed_layer"] == "backend"
    assert edges["hermes_litellm"]["callable"] is False
    assert edges["litellm_backend"]["status"] == "unavailable"
    route = next(c for c in report["components"] if c["name"] == "route")
    assert route["failed_layer"] is None  # the route policy itself passed
    assert KEY_SENTINEL not in out and "backend" in report["failed_layers"]


def test_cli_probe_loopback_blocked_route_is_not_probed(tmp_path, capsys):
    with serve(body=_models(ALIAS)) as (srv, base):
        code = main(
            [
                "--profile",
                str(_cli_profile(tmp_path, base)),
                "--hermes-config",
                str(_config(tmp_path, "config-fallback-hosted.yaml", base)),
                "--probe",
                "loopback",
            ]
        )
        assert srv.seen == []
    report = json.loads(capsys.readouterr().out)
    route = next(c for c in report["components"] if c["name"] == "route")
    assert code == 2 and route["failed_layer"] == "route"
    assert "fallback_providers_set" in route["detail"]


def test_cli_without_hermes_config_keeps_route_blocked(tmp_path, capsys):
    code = main(["--profile", str(PROFILE), "--probe", "none"])
    report = json.loads(capsys.readouterr().out)
    route = next(c for c in report["components"] if c["name"] == "route")
    assert code == 2 and route["failed_layer"] == "route"


def test_cli_unreadable_hermes_config_is_config_layer(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- x\n", encoding="utf-8")
    code = main(["--profile", str(PROFILE), "--hermes-config", str(bad)])
    report = json.loads(capsys.readouterr().out)
    cfg = next(c for c in report["components"] if c["name"] == "hermes_config")
    assert code == 2 and cfg["failed_layer"] == "config"
