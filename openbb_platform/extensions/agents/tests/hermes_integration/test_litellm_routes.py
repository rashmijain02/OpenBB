"""LiteLLM alias classification and refused-backend proof (#1338-T03).

Stock tests read synthetic proxy configs only. Tests marked ``requires_agents``
run real litellm 1.106.6 code in-process (decision O5: an ephemeral interpreter
outside the repo, ``-I``); they skip cleanly where litellm is not installed.
Every server here is test-owned on loopback; "hosted" is a loopback stand-in.
"""

# ruff: noqa: D101, D102, D103, S104

from __future__ import annotations

import copy
import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration import litellm_config
from openbb_agents.hermes_integration.models import BackendKind, Presence
from openbb_agents.hermes_integration.profile import load_profile

from .conftest import FIXTURES, SENTINELS

LITELLM = FIXTURES / "litellm"
PROFILE = FIXTURES / "profiles" / "synthetic-ok.yaml"
ALIAS = "finance-private"
MASTER_SENTINEL = "sk-SYNTHETIC-MASTER-KEY-SENTINEL"
DB_SENTINEL = "postgresql://sentinel:SYNTHETIC-DB-PASSWORD@127.0.0.1:5433/x"


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _profile(tmp_path, local_port=None, allow=(ALIAS,)):
    data = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    data["private_alias_allowlist"] = list(allow)
    if local_port is not None:
        data["local_backends"] = [f"http://127.0.0.1:{local_port}"]
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_profile(out)


def _cfg_text(name, **ports) -> str:
    text = (LITELLM / name).read_text(encoding="utf-8")
    for key, value in ports.items():
        text = text.replace(key, str(value))
    return text


def _write(tmp_path, data_or_text, name="proxy.yaml") -> Path:
    out = tmp_path / name
    text = (
        data_or_text
        if isinstance(data_or_text, str)
        else yaml.safe_dump(data_or_text, sort_keys=False)
    )
    out.write_text(text, encoding="utf-8")
    return out


def _local_cfg(port=8080) -> dict:
    return yaml.safe_load(_cfg_text("finance-local.yaml", PORT_LOCAL=port))


def _verdict(tmp_path, cfg, local_port=8080):
    profile = _profile(tmp_path, local_port)
    facts = litellm_config.read_gateway_facts(_write(tmp_path, cfg), profile)
    return facts, litellm_config.evaluate_gateway(facts, profile)


# --- alias classification --------------------------------------------------------------


def test_existing_shape_hosted_only_reports_no_private_alias(tmp_path):
    facts, verdict = _verdict(tmp_path, _cfg_text("existing-shape-hosted-only.yaml"))
    assert len(facts.aliases) == 6
    assert all(a.kind is BackendKind.HOSTED for a in facts.aliases)
    assert all("hosted_provider" in a.reasons for a in facts.aliases)
    assert verdict.blocked
    assert f"alias_{ALIAS}_missing" in verdict.reasons
    assert "no_local_alias" in verdict.reasons


def test_existing_shape_via_preflight_is_route_blocked(tmp_path):
    from openbb_agents.hermes_integration.hermes_preflight import (
        PreflightOptions,
        run_preflight,
    )

    report = run_preflight(
        _profile(tmp_path, 8080),
        PreflightOptions(
            litellm_config_path=LITELLM / "existing-shape-hosted-only.yaml"
        ),
        env={},
    )
    routes = next(c for c in report.components if c.name == "litellm_routes")
    assert routes.failed_layer.value == "route"
    assert "private_route=BLOCKED local=0 hosted=6" in routes.detail
    assert report.gateway.private_route == "BLOCKED"
    assert (report.gateway.local, report.gateway.hosted) == (0, 6)
    cfg = next(c for c in report.components if c.name == "litellm_config")
    assert cfg.presence == {
        "master_key": Presence.PRESENT,
        "database_url": Presence.PRESENT,
    }


def test_local_alias_on_loopback_classified_local(tmp_path):
    facts, verdict = _verdict(tmp_path, _local_cfg())
    kinds = {a.name: a.kind for a in facts.aliases}
    assert kinds == {ALIAS: BackendKind.LOCAL, "hosted-a": BackendKind.HOSTED}
    assert not verdict.blocked, verdict.reasons


def test_local_alias_on_unlisted_port_is_not_local(tmp_path):
    facts, verdict = _verdict(tmp_path, _local_cfg(port=9999), local_port=8080)
    alias = next(a for a in facts.aliases if a.name == ALIAS)
    assert alias.kind is BackendKind.HOSTED
    assert "api_base_not_allowlisted_local_runtime" in alias.reasons
    assert f"alias_{ALIAS}_hosted" in verdict.reasons


def test_localhost_proxy_backed_by_hosted_model_is_not_local(tmp_path):
    # openai/... on loopback, but the port is another proxy (here: the gateway
    # itself) whose own models are hosted. Loopback alone is not "local".
    cfg = _local_cfg()
    cfg["model_list"][0]["litellm_params"]["api_base"] = "http://localhost:4000/v1"
    facts, verdict = _verdict(tmp_path, cfg)
    alias = next(a for a in facts.aliases if a.name == ALIAS)
    assert alias.kind is BackendKind.HOSTED
    assert "api_base_is_gateway" in alias.reasons
    assert verdict.blocked


@pytest.mark.parametrize(
    "model, base, reason",
    [
        ("github_copilot/x", "http://127.0.0.1:8080/v1", "hosted_provider"),
        ("openai/x", "https://api.example.invalid/v1", "api_base_not_loopback"),
        ("openai/x", None, "api_base_unset"),
    ],
)
def test_hosted_provider_or_remote_base_is_hosted(tmp_path, model, base, reason):
    cfg = _local_cfg()
    params = cfg["model_list"][0]["litellm_params"]
    params["model"] = model
    if base is None:
        params.pop("api_base")
    else:
        params["api_base"] = base
    facts, verdict = _verdict(tmp_path, cfg)
    alias = next(a for a in facts.aliases if a.name == ALIAS)
    assert alias.kind is BackendKind.HOSTED and reason in alias.reasons
    assert verdict.blocked


def test_mixed_deployments_in_private_group_is_hosted(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"].append(
        {"model_name": ALIAS, "litellm_params": {"model": "github_copilot/x"}}
    )
    facts, verdict = _verdict(tmp_path, cfg)
    alias = next(a for a in facts.aliases if a.name == ALIAS)
    assert alias.kind is BackendKind.HOSTED and "mixed_deployments" in alias.reasons
    assert f"alias_{ALIAS}_hosted" in verdict.reasons


def test_hosted_wildcard_route_capturing_private_alias_blocks(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"].append(
        {"model_name": "finance-*", "litellm_params": {"model": "github_copilot/*"}}
    )
    _, verdict = _verdict(tmp_path, cfg)
    assert f"alias_{ALIAS}_captured_by_hosted_wildcard" in verdict.reasons


# --- fallbacks, callbacks, logging -----------------------------------------------------


@pytest.mark.parametrize("section", ["router_settings", "litellm_settings"])
@pytest.mark.parametrize(
    "key",
    ["fallbacks", "context_window_fallbacks", "content_policy_fallbacks"],
)
def test_router_fallbacks_default_fallbacks_context_window_fallbacks_to_hosted_block(
    tmp_path, section, key
):
    cfg = _local_cfg()
    cfg.setdefault(section, {})[key] = [{ALIAS: ["hosted-a"]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert f"unsafe_fallback:{section}.{key}" in verdict.reasons


@pytest.mark.parametrize("section", ["router_settings", "litellm_settings"])
def test_default_fallbacks_to_hosted_block(tmp_path, section):
    cfg = _local_cfg()
    cfg.setdefault(section, {})["default_fallbacks"] = ["hosted-a"]
    _, verdict = _verdict(tmp_path, cfg)
    assert f"unsafe_fallback:{section}.default_fallbacks" in verdict.reasons


def test_fallback_between_local_aliases_is_safe_and_other_alias_fallback_ignored(
    tmp_path,
):
    cfg = _local_cfg()
    second = copy.deepcopy(cfg["model_list"][0])
    second["model_name"] = "finance-private-b"
    cfg["model_list"].append(second)
    cfg["router_settings"]["fallbacks"] = [
        {ALIAS: ["finance-private-b"]},
        {"hosted-a": ["hosted-b"]},  # not a private alias: out of scope
    ]
    _, verdict = _verdict(tmp_path, cfg)
    assert not verdict.blocked, verdict.reasons


def test_local_with_hosted_fallback_fixture_is_blocked(tmp_path):
    text = _cfg_text(
        "local-with-hosted-fallback.yaml", PORT_LOCAL=8080, PORT_HOSTED=8081
    )
    _, verdict = _verdict(tmp_path, text)
    assert verdict.reasons == ["unsafe_fallback:router_settings.fallbacks"]


def test_logging_and_callbacks_block(tmp_path):
    _, verdict = _verdict(tmp_path, _cfg_text("logging-on.yaml", PORT_LOCAL=8080))
    assert "callbacks_set:success_callback" in verdict.reasons
    assert "callbacks_set:callbacks" in verdict.reasons
    assert "message_logging_not_disabled" in verdict.reasons
    assert "prompts_stored_in_spend_logs" in verdict.reasons


def test_set_verbose_blocks(tmp_path):
    cfg = _local_cfg()
    cfg["litellm_settings"]["set_verbose"] = True
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.reasons == ["verbose_logging_enabled"]


def test_message_logging_unset_blocks(tmp_path):
    cfg = _local_cfg()
    del cfg["litellm_settings"]["turn_off_message_logging"]
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.reasons == ["message_logging_not_disabled"]


def test_empty_allowlist_blocks_even_with_local_alias(tmp_path):
    profile = _profile(tmp_path, 8080, allow=())
    facts = litellm_config.read_gateway_facts(_write(tmp_path, _local_cfg()), profile)
    verdict = litellm_config.evaluate_gateway(facts, profile)
    assert "no_private_alias_allowlisted" in verdict.reasons


# --- fail-closed gateway policy (#1338 SECURITY-2, CODE-2) ------------------------------


def _with(path, value):
    def mutate(cfg):
        node = cfg
        *head, last = path.split(".")
        for part in head:
            node = (
                node[int(part)] if isinstance(node, list) else node.setdefault(part, {})
            )
        node[last] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            _with("router_settings.model_group_alias", {ALIAS: "hosted-a"}),
            "model_group_alias_set",
        ),
        (
            _with("litellm_settings.model_alias_map", {ALIAS: "hosted-a"}),
            "model_alias_map_set",
        ),
        (
            _with("router_settings.routing_groups", [{"name": "g"}]),
            "routing_groups_set",
        ),
        (_with("include", ["more.yaml"]), "include_set"),
        (
            _with("general_settings.allow_client_side_credentials", True),
            "client_side_credentials_allowed",
        ),
        (_with("general_settings.store_model_in_db", True), "models_stored_in_db"),
        (
            _with(
                "model_list.0.litellm_params.configurable_clientside_auth_params",
                ["api_base"],
            ),
            f"alias_{ALIAS}_clientside_auth_params",
        ),
        (
            _with("model_list.0.litellm_params.base_url", "https://h.invalid"),
            f"alias_{ALIAS}_hosted",
        ),
        (
            _with("router_settings.brand_new_router_key", 1),
            "unvetted_key:router_settings.brand_new_router_key",
        ),
        (_with("litellm_settings.cache", True), "unvetted_key:litellm_settings.cache"),
        (
            _with("general_settings.pass_through_endpoints", [{}]),
            "unvetted_key:general_settings.pass_through_endpoints",
        ),
        (
            _with("environment_variables", {"X": "y"}),
            "unvetted_key:environment_variables",
        ),
        (_with("guardrails", [{}]), "unvetted_key:guardrails"),
    ],
)
def test_gateway_policy_blocks_every_unread_routing_key(tmp_path, mutate, reason):
    cfg = _local_cfg()
    mutate(cfg)
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked and reason in verdict.reasons, verdict.reasons


def test_private_alias_group_with_hosted_deployment_names_the_group(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"].append(
        {"model_name": ALIAS, "litellm_params": {"model": "github_copilot/x"}}
    )
    _, verdict = _verdict(tmp_path, cfg)
    assert f"alias_{ALIAS}_group_has_hosted_deployment" in verdict.reasons


@pytest.mark.parametrize(
    "mutate",
    [
        _with("general_settings.allow_client_side_credentials", False),
        _with("general_settings.store_model_in_db", False),
        _with("include", []),
        _with("router_settings.routing_strategy", "simple-shuffle"),
        _with("general_settings.trusted_proxy_ranges", []),
        _with(
            "model_list.1.litellm_params.configurable_clientside_auth_params",
            ["api_key"],
        ),
    ],
)
def test_gateway_policy_admits_vetted_settings(tmp_path, mutate):
    cfg = _local_cfg()
    mutate(cfg)
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked is False, verdict.reasons


@pytest.mark.requires_agents
def test_gateway_allowlists_are_real_settings_in_litellm_1_106_6(litellm_mod):
    root = Path(litellm_mod.__file__).parent
    router_args = set(litellm_mod.Router.get_valid_args())
    proxy_src = "".join(
        p.read_text(encoding="utf-8") for p in (root / "proxy").rglob("*.py")
    )
    for key in (*litellm_config.ROUTER_SETTINGS_VETTED, "model_group_alias"):
        assert key in router_args, key
    assert "routing_groups" in proxy_src
    for key in (*litellm_config.LITELLM_SETTINGS_VETTED, "model_alias_map"):
        assert hasattr(litellm_mod, key), key
    for key in litellm_config.GENERAL_SETTINGS_VETTED:
        assert f'"{key}"' in proxy_src, key
    assert "`include`" in proxy_src
    params = (root / "types" / "router.py").read_text(encoding="utf-8")
    for key in litellm_config.LITELLM_PARAMS_VETTED:
        assert f"{key}:" in params, key
    assert "configurable_clientside_auth_params:" in params


# --- secrets ----------------------------------------------------------------------------


def test_os_environ_and_master_key_reported_as_presence(tmp_path):
    cfg = _local_cfg()
    cfg["general_settings"]["master_key"] = MASTER_SENTINEL
    cfg["general_settings"]["database_url"] = DB_SENTINEL
    cfg["model_list"][0]["litellm_params"]["api_key"] = MASTER_SENTINEL
    profile = _profile(tmp_path, 8080)
    facts = litellm_config.read_gateway_facts(_write(tmp_path, cfg), profile)
    verdict = litellm_config.evaluate_gateway(facts, profile)
    dumped = (
        facts.model_dump_json()
        + litellm_config.gateway_report(facts, verdict).model_dump_json()
    )
    assert MASTER_SENTINEL not in dumped and "SYNTHETIC-DB-PASSWORD" not in dumped
    assert facts.secrets["master_key"].presence is Presence.PRESENT
    assert facts.secrets["master_key"].inline is True
    ref = litellm_config.read_gateway_facts(LITELLM / "finance-local.yaml", profile)
    assert ref.secrets["master_key"].env_name == "SYNTHETIC_MASTER_KEY_ENV"
    assert ref.secrets["database_url"].env_name == "SYNTHETIC_DATABASE_URL_ENV"
    assert ref.aliases[0].deployments[0].api_key.env_name == (
        "SYNTHETIC_LOCAL_RUNTIME_KEY_ENV"
    )


def test_cli_litellm_config_json_is_secret_free(tmp_path, capsys):
    from openbb_agents.hermes_integration.hermes_preflight import main

    cfg = yaml.safe_load(_cfg_text("existing-shape-hosted-only.yaml"))
    cfg["general_settings"]["master_key"] = MASTER_SENTINEL
    code = main(
        ["--profile", str(PROFILE), "--litellm-config", str(_write(tmp_path, cfg))]
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    assert code == 2 and report["gateway"]["private_route"] == "BLOCKED"
    assert MASTER_SENTINEL not in out
    assert "no_private_alias_allowlisted" in report["gateway"]["reasons"]


def test_cli_unreadable_litellm_config_is_config_layer(tmp_path, capsys):
    from openbb_agents.hermes_integration.hermes_preflight import main

    bad = _write(tmp_path, "- x\n")
    code = main(["--profile", str(PROFILE), "--litellm-config", str(bad)])
    report = json.loads(capsys.readouterr().out)
    cfg = next(c for c in report["components"] if c["name"] == "litellm_config")
    assert code == 2 and cfg["failed_layer"] == "config"


# --- seam contract -----------------------------------------------------------------------


def _has(data, dotted) -> bool:
    head, _, rest = dotted.partition(".")
    if head.endswith("[]"):
        items = data.get(head[:-2]) if isinstance(data, dict) else None
        return isinstance(items, list) and any(_has(i, rest) for i in items)
    if not isinstance(data, dict) or head not in data:
        return False
    return not rest or _has(data[head], rest)


def test_reader_consumed_keys_exist_in_some_fixture():
    docs = [
        yaml.safe_load(p.read_text(encoding="utf-8")) for p in LITELLM.glob("*.yaml")
    ]
    # Fallback/callback variants are exercised by parametrised tests above; the
    # fixtures must at least carry the core keys the reader depends on.
    core = [
        k
        for k in litellm_config.CONSUMED_KEYS
        if not any(
            x in k
            for x in (
                "default_fallbacks",
                "context_window",
                "content_policy",
                "failure_callback",
                "service_callback",
                "litellm_settings.fallbacks",
            )
        )
    ]
    missing = [k for k in core if not any(_has(d, k) for d in docs)]
    assert not missing, missing


# --- real litellm 1.106.6, in-process (O5) ---------------------------------------------

_OK_BODY = json.dumps(
    {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
).encode()


class _Backend(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        srv = self.server
        srv.hits += 1  # count only; request bodies are never kept
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if srv.mode == "timeout":
            time.sleep(3)
        status, body = (
            (429, b'{"error":{"message":"rate limited"}}')
            if (srv.mode == "ratelimit")
            else (200, _OK_BODY)
        )
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


@contextmanager
def _serve(mode="ok"):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    srv.mode, srv.hits = mode, 0
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.fixture
def litellm_mod(monkeypatch, tmp_path):
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    mod = pytest.importorskip("litellm")
    monkeypatch.setenv("SYNTHETIC_LOCAL_RUNTIME_KEY_ENV", "synthetic-local")
    monkeypatch.setenv("SYNTHETIC_HOSTED_KEY_ENV", "synthetic-hosted")
    # never let a github_copilot deployment find a real token directory
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path / "no-copilot"))
    return mod


@pytest.fixture
def egress(monkeypatch):
    """Record every non-loopback name lookup or connect attempt (and refuse it)."""
    attempts: list[str] = []
    real_gai = socket.getaddrinfo
    real_connect = socket.socket.connect
    loop = {"127.0.0.1", "::1", "localhost"}

    def gai(host, *a, **k):
        if host is not None and str(host) not in loop:
            attempts.append(f"dns:{host}")
            raise socket.gaierror("non-loopback lookup refused in tests")
        return real_gai(host, *a, **k)

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in loop:
            attempts.append(f"connect:{host}")
            raise OSError("non-loopback connect refused in tests")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return attempts


def _router(litellm, cfg, monkeypatch):
    """Build a Router the way the 1.106.6 proxy does from this config."""
    for key, value in (cfg.get("litellm_settings") or {}).items():
        assert hasattr(litellm, key), f"litellm 1.106.6 has no setting {key!r}"
        monkeypatch.setattr(litellm, key, value)
    rs = dict(cfg.get("router_settings") or {})
    unknown = set(rs) - set(litellm.Router.get_valid_args())
    assert not unknown, f"not Router args at 1.106.6: {unknown}"
    return litellm.Router(model_list=copy.deepcopy(cfg["model_list"]), **rs)


def _prompt():
    return [
        {
            "role": "user",
            "content": f"{SENTINELS['name']} acct {SENTINELS['account']} "
            f"holds {SENTINELS['amount']}",
        }
    ]


def _no_sentinel(*texts):
    blob = "\n".join(texts)
    return [v for v in SENTINELS.values() if v in blob]


@pytest.mark.requires_agents
@pytest.mark.parametrize("mode", ["refused", "timeout", "ratelimit"])
def test_inprocess_router_refused_local_backend_makes_no_hosted_connect(
    tmp_path, monkeypatch, caplog, capsys, litellm_mod, egress, mode
):
    """Admitted config + failing local backend: exception, zero hosted requests."""
    with _serve("ok") as (hosted, hosted_port), _serve(
        "timeout" if mode == "timeout" else "ratelimit"
    ) as (local, live_port):
        local_port = _closed_port() if mode == "refused" else live_port
        cfg = _local_cfg(local_port)
        # the coexisting hosted alias points at the loopback stand-in
        cfg["model_list"][1]["litellm_params"] = {
            "model": "openai/hosted-model-a",
            "api_base": f"http://127.0.0.1:{hosted_port}/v1",
            "api_key": "os.environ/SYNTHETIC_HOSTED_KEY_ENV",
        }
        profile = _profile(tmp_path, local_port)
        facts = litellm_config.read_gateway_facts(_write(tmp_path, cfg), profile)
        assert not litellm_config.evaluate_gateway(facts, profile).blocked
        router = _router(litellm_mod, cfg, monkeypatch)
        # INFO is the proxy's level without --detailed_debug / LITELLM_LOG=DEBUG.
        with caplog.at_level(logging.INFO), pytest.raises(Exception) as err:
            router.completion(model=ALIAS, messages=_prompt(), timeout=1)
        out = capsys.readouterr()
        assert hosted.hits == 0, "hosted stand-in received a request"
        assert egress == [], egress
        assert mode == "refused" or local.hits >= 1, "local backend never reached"
        assert not _no_sentinel(caplog.text, out.out, out.err, str(err.value))


@pytest.mark.requires_agents
def test_inprocess_hosted_fallback_positive_control_reaches_hosted(
    tmp_path, monkeypatch, litellm_mod, egress
):
    """The config the classifier rejects really does reach the hosted stand-in."""
    with _serve("ok") as (hosted, hosted_port):
        local_port = _closed_port()
        text = _cfg_text(
            "local-with-hosted-fallback.yaml",
            PORT_LOCAL=local_port,
            PORT_HOSTED=hosted_port,
        )
        cfg = yaml.safe_load(text)
        profile = _profile(tmp_path, local_port)
        facts = litellm_config.read_gateway_facts(_write(tmp_path, text), profile)
        assert litellm_config.evaluate_gateway(facts, profile).blocked
        router = _router(litellm_mod, cfg, monkeypatch)
        router.completion(model=ALIAS, messages=_prompt(), timeout=2)
        assert hosted.hits >= 1
        assert egress == []


@pytest.mark.requires_agents
def test_inprocess_request_level_fallback_bypasses_config_policy(
    tmp_path, monkeypatch, litellm_mod, egress
):
    """Gap for L3 / #1339-T03: a caller-supplied ``fallbacks`` kwarg still reaches
    a hosted alias on an admitted config. The proxy key must not reach hosted aliases.
    """
    with _serve("ok") as (hosted, hosted_port):
        cfg = _local_cfg(_closed_port())
        cfg["model_list"][1]["litellm_params"] = {
            "model": "openai/hosted-model-a",
            "api_base": f"http://127.0.0.1:{hosted_port}/v1",
            "api_key": "os.environ/SYNTHETIC_HOSTED_KEY_ENV",
        }
        router = _router(litellm_mod, cfg, monkeypatch)
        router.completion(
            model=ALIAS, messages=_prompt(), timeout=2, fallbacks=["hosted-a"]
        )
        assert hosted.hits >= 1


@pytest.mark.requires_agents
def test_inprocess_debug_logs_carry_prompt_despite_turn_off_message_logging(
    tmp_path, monkeypatch, caplog, litellm_mod, egress
):
    """Gap for L3 / #1339-T03: at DEBUG (``--detailed_debug``, ``LITELLM_LOG=DEBUG``,
    ``set_verbose``) the prompt reaches logs even with message logging off.
    """
    cfg = _local_cfg(_closed_port())
    cfg["model_list"] = cfg["model_list"][:1]  # private alias only
    router = _router(litellm_mod, cfg, monkeypatch)
    assert litellm_mod.turn_off_message_logging is True
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception):
        router.completion(model=ALIAS, messages=_prompt(), timeout=1)
    assert _no_sentinel(caplog.text), "DEBUG no longer leaks; relax the L3 check"


@pytest.mark.requires_agents
def test_consumed_keys_are_real_settings_in_litellm_1_106_6(litellm_mod):
    from importlib.metadata import version

    assert version("litellm") == "1.106.6"
    router_args = set(litellm_mod.Router.get_valid_args())
    proxy_src = (
        Path(litellm_mod.__file__).parent / "proxy" / "proxy_server.py"
    ).read_text(encoding="utf-8")
    for dotted in litellm_config.CONSUMED_KEYS:
        section, _, key = dotted.partition(".")
        if section == "router_settings":
            assert key in router_args, dotted
        elif section == "litellm_settings":
            if key in litellm_config.CALLBACK_KEYS[:3]:
                assert f'key == "{key}"' in proxy_src, dotted
            else:
                assert hasattr(litellm_mod, key), dotted
        elif section == "general_settings":
            assert f'"{key}"' in proxy_src, dotted


def test_alias_names_are_stripped_of_control_chars_and_capped(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"][1]["model_name"] = "\x1b[31mhosted\r\n" + "x" * 200
    facts, verdict = _verdict(tmp_path, cfg)
    report = litellm_config.gateway_report(facts, verdict)
    names = [a.name for a in report.aliases]
    assert all(len(n) <= 64 for n in names)
    assert not any(ord(c) < 32 or ord(c) == 127 for n in names for c in n)
    assert ALIAS in names


# --- userinfo in a deployment api_base (#1338 N1) ---------------------------------------


@pytest.mark.parametrize(
    "base", ["http://hosted.invalid\\@127.0.0.1:8080/v1", "http://u@127.0.0.1:8080/v1"]
)
def test_api_base_with_userinfo_is_not_local(tmp_path, base):
    cfg = _local_cfg()
    cfg["model_list"][0]["litellm_params"]["api_base"] = base
    facts, verdict = _verdict(tmp_path, cfg)
    alias = next(a for a in facts.aliases if a.name == ALIAS)
    assert "api_base_userinfo" in alias.reasons and verdict.blocked


# --- logging toggles are on unless absent or exactly false (#1338 N2) -------------------


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", 1, None])
@pytest.mark.parametrize(
    ("dotted", "reason"),
    [
        (
            "general_settings.store_prompts_in_spend_logs",
            "prompts_stored_in_spend_logs",
        ),
        ("litellm_settings.set_verbose", "verbose_logging_enabled"),
        ("general_settings.store_model_in_db", "models_stored_in_db"),
    ],
)
def test_logging_toggle_not_exactly_false_blocks(tmp_path, dotted, reason, value):
    cfg = _local_cfg()
    _with(dotted, value)(cfg)
    _, verdict = _verdict(tmp_path, cfg)
    assert reason in verdict.reasons, verdict.reasons


@pytest.mark.parametrize(
    "dotted",
    [
        "general_settings.store_prompts_in_spend_logs",
        "litellm_settings.set_verbose",
        "general_settings.store_model_in_db",
    ],
)
def test_logging_toggle_absent_or_false_is_admitted(tmp_path, dotted):
    cfg = _local_cfg()
    _with(dotted, False)(cfg)
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked is False, verdict.reasons
    section, key = dotted.split(".")
    cfg[section].pop(key)
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked is False, verdict.reasons


# --- malformed section shapes are blocking issues, not crashes (#1338 N3) ---------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("model_list: 5\n", "model_list_unparsed"),
        ("model_list: {a: 1}\n", "model_list_unparsed"),
        ("model_list: [5]\n", "model_list_0_unparsed"),
        (
            "model_list: [{model_name: finance-private, litellm_params: [1]}]\n",
            "model_list_0_litellm_params_unparsed",
        ),
    ],
)
def test_malformed_model_list_is_a_blocking_issue(tmp_path, text, reason):
    _, verdict = _verdict(tmp_path, text)
    assert verdict.blocked and reason in verdict.reasons, verdict.reasons


def test_malformed_entry_next_to_valid_local_alias_still_blocks(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"].append("hosted-z")
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.reasons == ["model_list_2_unparsed"]


# --- wildcard fallback sources and private-alias patterns (#1338 review) ---------------


@pytest.mark.parametrize(
    "src", ["finance-*", "*", "fin?nce-private", "finance-[p]rivate"]
)
@pytest.mark.parametrize("section", ["router_settings", "litellm_settings"])
@pytest.mark.parametrize(
    "key",
    ["fallbacks", "context_window_fallbacks", "content_policy_fallbacks"],
)
def test_wildcard_fallback_source_blocks_even_to_a_local_target(
    tmp_path, section, key, src
):
    cfg = _local_cfg()
    cfg[section][key] = [{src: [ALIAS]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert f"fallback_source_wildcard:{section}.{key}" in verdict.reasons


@pytest.mark.parametrize("section", ["router_settings", "litellm_settings"])
def test_wildcard_default_fallbacks_source_blocks(tmp_path, section):
    cfg = _local_cfg()
    cfg[section]["default_fallbacks"] = [{"finance-*": ["hosted-a"]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert f"fallback_source_wildcard:{section}.default_fallbacks" in verdict.reasons


def test_bare_default_fallbacks_list_is_not_a_wildcard_source(tmp_path):
    cfg = _local_cfg()
    cfg["router_settings"]["default_fallbacks"] = [ALIAS]
    _, verdict = _verdict(tmp_path, cfg)
    assert not any(r.startswith("fallback_source_wildcard") for r in verdict.reasons)


@pytest.mark.parametrize("kind", ["local", "hosted"])
def test_model_name_pattern_matching_private_alias_blocks(tmp_path, kind):
    cfg = _local_cfg()
    model = "openai/local-finance-model" if kind == "local" else "github_copilot/*"
    params = {"model": model}
    if kind == "local":
        params["api_base"] = cfg["model_list"][0]["litellm_params"]["api_base"]
    cfg["model_list"].append({"model_name": "finance-*", "litellm_params": params})
    _, verdict = _verdict(tmp_path, cfg)
    assert f"alias_{ALIAS}_pattern_overlaps_private" in verdict.reasons


def test_model_name_pattern_not_matching_private_alias_is_admitted(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"].append(
        {
            "model_name": "other-*",
            "litellm_params": cfg["model_list"][0]["litellm_params"],
        }
    )
    _, verdict = _verdict(tmp_path, cfg)
    assert not any("pattern_overlaps" in r for r in verdict.reasons)


# --- provider-prefixed fallback source keys (#1338 N4) ----------------------------------


@pytest.mark.parametrize("src", [f"openai/{ALIAS}", f"hosted_vllm/{ALIAS}"])
@pytest.mark.parametrize("section", ["router_settings", "litellm_settings"])
def test_provider_prefixed_fallback_source_applies_to_private_alias(
    tmp_path, section, src
):
    cfg = _local_cfg()
    cfg[section]["fallbacks"] = [{src: ["hosted-a"]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert f"unsafe_fallback:{section}.fallbacks" in verdict.reasons, verdict.reasons


# --- alias names must be canonical (#1338 minor a) --------------------------------------


@pytest.mark.parametrize(
    "name", [f"{ALIAS}\t", f" {ALIAS}", f"{ALIAS} ", f"{ALIAS}\x00", "hosted\r\n", 5]
)
def test_non_canonical_alias_name_blocks(tmp_path, name):
    cfg = _local_cfg()
    cfg["model_list"].append(
        {"model_name": name, "litellm_params": {"model": "github_copilot/x"}}
    )
    _, verdict = _verdict(tmp_path, cfg)
    assert "alias_name_not_canonical" in verdict.reasons, verdict.reasons


def test_local_alias_with_trailing_tab_is_not_the_private_alias(tmp_path):
    cfg = _local_cfg()
    cfg["model_list"][0]["model_name"] = f"{ALIAS}\t"
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked and "alias_name_not_canonical" in verdict.reasons


# --- RR3: transitive fallback chains (#1338 SEC-3) ------------------------------------


def _with_local_b(port=8080, name="local-b") -> dict:
    cfg = _local_cfg(port)
    second = copy.deepcopy(cfg["model_list"][0])
    second["model_name"] = name
    cfg["model_list"].append(second)
    return cfg


def _chain_reasons(verdict):
    return [
        r for r in verdict.reasons if r.startswith("fallback_chain_reaches_hosted:")
    ]


def test_chained_fallback_through_local_alias_to_hosted_blocks(tmp_path):
    # litellm 1.106.6 re-enters ``async_function_with_fallbacks`` for the fallback
    # group (``run_async_fallback``), so local-b's own fallbacks apply in turn.
    cfg = _with_local_b()
    cfg["router_settings"]["fallbacks"] = [
        {ALIAS: ["local-b"]},
        {"local-b": ["hosted-a"]},
    ]
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked
    assert _chain_reasons(verdict) == [
        "fallback_chain_reaches_hosted:finance-private>local-b>hosted-a"
    ], verdict.reasons


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            ("router_settings", "fallbacks"),
            ("router_settings", "context_window_fallbacks"),
        ),
        (
            ("router_settings", "fallbacks"),
            ("litellm_settings", "content_policy_fallbacks"),
        ),
        (("litellm_settings", "fallbacks"), ("router_settings", "fallbacks")),
    ],
)
def test_chained_fallback_split_across_keys_blocks(tmp_path, first, second):
    cfg = _with_local_b()
    cfg.setdefault(first[0], {})[first[1]] = [{ALIAS: ["local-b"]}]
    cfg.setdefault(second[0], {})[second[1]] = [{"local-b": ["hosted-a"]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked and _chain_reasons(verdict), verdict.reasons


def test_chain_through_default_fallbacks_blocks(tmp_path):
    # bare default_fallbacks apply to every group, the private alias included
    cfg = _with_local_b()
    cfg["router_settings"]["default_fallbacks"] = ["local-b"]
    cfg["router_settings"]["fallbacks"] = [{"local-b": ["hosted-a"]}]
    _, verdict = _verdict(tmp_path, cfg)
    assert _chain_reasons(verdict) == [
        "fallback_chain_reaches_hosted:finance-private>local-b>hosted-a"
    ], verdict.reasons


def test_fallback_cycle_between_local_aliases_terminates_and_admits(tmp_path):
    cfg = _with_local_b()
    cfg["router_settings"]["fallbacks"] = [
        {ALIAS: ["local-b"]},
        {"local-b": [ALIAS]},
        {"hosted-a": ["hosted-b"]},  # unreachable from the private alias
    ]
    _, verdict = _verdict(tmp_path, cfg)
    assert not verdict.blocked, verdict.reasons


def test_chain_through_provider_prefixed_source_blocks(tmp_path):
    cfg = _with_local_b()
    cfg["router_settings"]["fallbacks"] = [
        {ALIAS: ["local-b"]},
        {"openai/local-b": ["hosted-a"]},
    ]
    _, verdict = _verdict(tmp_path, cfg)
    assert verdict.blocked and _chain_reasons(verdict), verdict.reasons


def test_provider_prefixed_private_alias_matches_unprefixed_fallback_key(tmp_path):
    prefixed = f"openai/{ALIAS}"
    cfg = _local_cfg()
    cfg["model_list"][0]["model_name"] = prefixed
    cfg["router_settings"]["fallbacks"] = [{ALIAS: ["hosted-a"]}]
    profile = _profile(tmp_path, 8080, allow=(prefixed,))
    facts = litellm_config.read_gateway_facts(_write(tmp_path, cfg), profile)
    verdict = litellm_config.evaluate_gateway(facts, profile)
    assert (
        "unsafe_fallback:router_settings.fallbacks" in verdict.reasons
    ), verdict.reasons


def test_cli_deeply_nested_litellm_config_is_config_layer(tmp_path, capsys):
    from openbb_agents.hermes_integration.hermes_preflight import main

    deep = _write(tmp_path, "include: " + "[" * 3000 + "]" * 3000 + "\n")
    code = main(["--profile", str(PROFILE), "--litellm-config", str(deep)])
    report = json.loads(capsys.readouterr().out)
    cfg = next(c for c in report["components"] if c["name"] == "litellm_config")
    assert code == 2 and cfg["detail"] == "config_unreadable: RecursionError"


@pytest.mark.requires_agents
def test_inprocess_chained_fallback_positive_control_reaches_hosted(
    tmp_path, monkeypatch, litellm_mod, egress
):
    """1.106.6 follows fallbacks transitively: private -> local-b -> hosted-a."""
    with _serve("ok") as (hosted, hosted_port):
        cfg = _with_local_b(_closed_port())
        cfg["model_list"][2]["litellm_params"][
            "api_base"
        ] = f"http://127.0.0.1:{_closed_port()}/v1"
        cfg["model_list"][1]["litellm_params"] = {
            "model": "openai/hosted-model-a",
            "api_base": f"http://127.0.0.1:{hosted_port}/v1",
            "api_key": "os.environ/SYNTHETIC_HOSTED_KEY_ENV",
        }
        cfg["router_settings"]["fallbacks"] = [
            {ALIAS: ["local-b"]},
            {"local-b": ["hosted-a"]},
        ]
        router = _router(litellm_mod, cfg, monkeypatch)
        router.completion(model=ALIAS, messages=_prompt(), timeout=2)
        assert hosted.hits >= 1
        assert egress == []
