"""WebUI finance-web profile and Hermes tool-allowlist preflight checks (#1342 T01).

Synthetic env and configs only. The preflight reads metadata; it never starts
WebUI or Hermes and never prints an env value.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration import hermes_config
from openbb_agents.hermes_integration.hermes_preflight import (
    PreflightOptions,
    main,
    run_preflight,
)
from openbb_agents.hermes_integration.models import FailedLayer, HealthLevel
from openbb_agents.hermes_integration.profile import load_profile
from openbb_agents.hermes_integration.web import bundle

from ..conftest import FIXTURES

WEB_CONFIG = FIXTURES / "hermes" / "config-finance-web.yaml"
PINNED = json.loads(
    (
        Path(bundle.__file__).resolve().parent / "pinned_toolsets.json"
    ).read_text(encoding="utf-8")
)
# Toolsets named in plan §3.6 as the ones a finance-web session must never carry.
RISKY = [
    "terminal", "code_execution", "file", "web", "search", "x_search", "browser",
    "computer_use", "delegation", "cronjob", "skills", "memory", "kanban",
    "session_search", "connections", "project", "image_gen", "video_gen", "video",
    "vision", "tts", "debugging", "bot_room", "desktop_ui", "onboarding", "catalog",
    "discord", "discord_admin", "feishu_doc", "feishu_drive", "yuanbao",
]  # fmt: skip


@pytest.fixture
def web_env(tmp_path):
    """A complete, admitted finance-web env over a freshly rendered bundle."""
    ext_dir = tmp_path / "bundle"
    sha = bundle.render_bundle(ext_dir, port=8799)
    state = tmp_path / "webui-state"
    state.mkdir()
    base = yaml.safe_load(
        (FIXTURES / "profiles" / "synthetic-ok.yaml").read_text(encoding="utf-8")
    )
    base["web"] = {"mcp_server": "openbb", "extension_tree_sha256": sha}
    profile_path = tmp_path / "profile-web.yaml"
    profile_path.write_text(yaml.safe_dump(base), encoding="utf-8")
    env = {
        "HERMES_WEBUI_HOST": "127.0.0.1",
        "HERMES_WEBUI_PORT": "8787",
        "HERMES_WEBUI_PASSWORD": "synthetic-test-password",
        "HERMES_WEBUI_STATE_DIR": str(state),
        "HERMES_WEBUI_EXTENSION_DIR": str(ext_dir),
        "HERMES_WEBUI_EXTENSION_MANIFEST": "manifest.json",
    }
    return profile_path, env, ext_dir


def _component(profile_path, env, name, config=WEB_CONFIG):
    report = run_preflight(
        load_profile(profile_path),
        PreflightOptions(hermes_config_path=config),
        env=env,
    )
    return next(c for c in report.components if c.name == name)


def test_webui_profile_admitted_for_complete_env(web_env):
    profile_path, env, _ = web_env
    comp = _component(profile_path, env, "webui_profile")
    assert comp.failed_layer is None, comp.detail
    assert comp.level == HealthLevel.ADMITTED
    tools = _component(profile_path, env, "web_toolsets")
    assert tools.failed_layer is None, tools.detail
    assert tools.level == HealthLevel.ADMITTED


def test_profile_without_web_section_emits_no_web_rows(tmp_path):
    report = run_preflight(
        load_profile(FIXTURES / "profiles" / "synthetic-ok.yaml"),
        PreflightOptions(hermes_config_path=WEB_CONFIG),
        env={},
    )
    names = {c.name for c in report.components}
    assert not names & {"webui_profile", "web_toolsets"}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HERMES_WEBUI_GATEWAY_BASE_URL", "http://127.0.0.1:8642"),
        ("HERMES_WEBUI_GATEWAY_API_KEY", "synthetic"),
        ("HERMES_WEBUI_CHAT_BACKEND", "gateway"),
        ("HERMES_WEBUI_RUNNER_BASE_URL", "http://127.0.0.1:8650"),
        ("HERMES_WEBUI_RUNNER_API_KEY", "synthetic"),
        ("HERMES_WEBUI_RUNTIME_ADAPTER", "runner-local"),
    ],
)
def test_webui_profile_blocks_gateway_or_runner_backend(web_env, name, value):
    profile_path, env, _ = web_env
    comp = _component(profile_path, {**env, name: value}, "webui_profile")
    assert comp.failed_layer == FailedLayer.PROCESS
    assert name in comp.detail


def test_webui_profile_allows_explicit_legacy_direct(web_env):
    profile_path, env, _ = web_env
    env = {**env, "HERMES_WEBUI_RUNTIME_ADAPTER": "legacy-direct"}
    assert _component(profile_path, env, "webui_profile").failed_layer is None


@pytest.mark.parametrize(
    "name",
    [
        "HERMES_WEBUI_ALLOWED_ORIGINS",
        "HERMES_WEBUI_TRUST_FORWARDED_HOST",
        "HERMES_WEBUI_TRUST_FORWARDED_PROTO",
        "HERMES_WEBUI_TRUST_FORWARDED_FOR",
        "HERMES_WEBUI_TRUSTED_AUTH_HEADER",
        "HERMES_WEBUI_TRUSTED_PROXY_CIDRS",
        "HERMES_WEBUI_CSP_CONNECT_EXTRA",
        "HERMES_WEBUI_CSP_FRAME_EXTRA",
        "HERMES_WEBUI_CSP_IMG_EXTRA",
    ],
)
def test_webui_profile_blocks_allowed_origins_and_forwarded_trust(web_env, name):
    profile_path, env, _ = web_env
    comp = _component(profile_path, {**env, name: "http://127.0.0.1:9999"}, "webui_profile")
    assert comp.failed_layer == FailedLayer.AUTH
    assert f"env_must_be_unset:{name}" in comp.detail


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"HERMES_WEBUI_HOST": "0.0.0.0"}, "non_loopback_bind"),
        ({"HERMES_WEBUI_PASSWORD": ""}, "no_password"),
    ],
)
def test_webui_profile_requires_loopback_and_password(web_env, override, code):
    profile_path, env, _ = web_env
    comp = _component(profile_path, {**env, **override}, "webui_profile")
    assert comp.failed_layer == FailedLayer.AUTH
    assert code in comp.detail


def test_webui_profile_requires_state_dir_and_manifest(web_env):
    profile_path, env, _ = web_env
    env = {k: v for k, v in env.items() if k != "HERMES_WEBUI_STATE_DIR"}
    env["HERMES_WEBUI_EXTENSION_MANIFEST"] = "extensions.json"
    comp = _component(profile_path, env, "webui_profile")
    assert comp.failed_layer == FailedLayer.CONFIG
    assert "state_dir_unset" in comp.detail
    assert "extension_manifest_not_manifest_json" in comp.detail


def test_webui_profile_requires_extension_dir_outside_git_and_pinned(web_env, tmp_path):
    profile_path, env, ext_dir = web_env
    # Drift: one byte changed in the bundle after the pin was taken.
    css = ext_dir / "hfp.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n/* drift */\n", encoding="utf-8")
    comp = _component(profile_path, env, "webui_profile")
    assert comp.failed_layer == FailedLayer.SCHEMA
    assert "extension_tree_drift" in comp.detail

    # A bundle inside a git work tree is refused even when its hash is pinned.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    sha = bundle.render_bundle(tmp_path / "staged", port=8799)  # render refuses git trees
    inside = repo / "bundle"
    shutil.move(str(tmp_path / "staged"), str(inside))
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    data["web"]["extension_tree_sha256"] = sha
    profile_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    comp = _component(profile_path, {**env, "HERMES_WEBUI_EXTENSION_DIR": str(inside)}, "webui_profile")
    assert comp.failed_layer == FailedLayer.SCHEMA
    assert "extension_dir_in_git_tree" in comp.detail


def test_webui_profile_unpinned_bundle_blocks(web_env):
    profile_path, env, _ = web_env
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    data["web"].pop("extension_tree_sha256")
    profile_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    comp = _component(profile_path, env, "webui_profile")
    assert comp.failed_layer == FailedLayer.SCHEMA
    assert "extension_tree_unpinned" in comp.detail


def test_profile_never_prints_env_values(web_env, monkeypatch, capsys):
    profile_path, env, _ = web_env
    sentinel = "SENTINEL-ENV-VALUE-1342"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in (
        "HERMES_WEBUI_GATEWAY_BASE_URL",
        "HERMES_WEBUI_ALLOWED_ORIGINS",
        "HERMES_WEBUI_RUNNER_API_KEY",
    ):
        monkeypatch.setenv(name, f"http://127.0.0.1:1/{sentinel}")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", sentinel)
    for fmt in ("json", "text"):
        code = main(
            ["--profile", str(profile_path), "--hermes-config", str(WEB_CONFIG), "--format", fmt]
        )
        out = capsys.readouterr()
        assert code == 2
        assert "webui_profile" in out.out
        assert sentinel not in out.out + out.err
        assert str(profile_path.parent) not in out.out


# ---- finance-web Hermes toolset allowlist ---------------------------------------------


def _config_with(tmp_path, mutate) -> Path:
    data = yaml.safe_load(WEB_CONFIG.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_finance_web_config_allowlist_only_openbb_and_clarify(web_env, tmp_path):
    profile_path, env, _ = web_env
    facts = hermes_config.read_toolset_facts(WEB_CONFIG)
    assert facts.cli_toolsets == ["mcp-openbb", "clarify"]
    # A non-allowlisted extra entry, a wildcard, or a missing cli list each block.
    for cli, code in (
        (["mcp-openbb", "clarify", "todo"], "cli_toolset_not_allowed:todo"),
        (["all"], "cli_toolset_not_allowed:all"),
        (["clarify"], "openbb_toolset_missing"),
        (None, "cli_toolsets_unset"),
    ):
        def mutate(data, cli=cli):
            if cli is None:
                data.pop("platform_toolsets")
            else:
                data["platform_toolsets"]["cli"] = cli

        comp = _component(profile_path, env, "web_toolsets", _config_with(tmp_path, mutate))
        assert comp.failed_layer == FailedLayer.CONFIG, (cli, comp.detail)
        assert code in comp.detail


def test_second_mcp_server_blocks(web_env, tmp_path):
    profile_path, env, _ = web_env
    cfg = _config_with(
        tmp_path,
        lambda d: d["mcp_servers"].update({"other": {"url": "http://127.0.0.1:9/mcp"}}),
    )
    comp = _component(profile_path, env, "web_toolsets", cfg)
    assert comp.failed_layer == FailedLayer.CONFIG
    assert "mcp_server_not_allowed:other" in comp.detail


@pytest.mark.parametrize("toolset", RISKY)
def test_any_enabled_risky_toolset_blocks(web_env, tmp_path, toolset):
    profile_path, env, _ = web_env
    # Enabled two ways: listed on the cli surface, or merely not disabled.
    listed = _config_with(
        tmp_path, lambda d: d["platform_toolsets"]["cli"].append(toolset)
    )
    comp = _component(profile_path, env, "web_toolsets", listed)
    assert f"cli_toolset_not_allowed:{toolset}" in comp.detail
    undisabled = _config_with(
        tmp_path,
        lambda d: d["agent"].update(
            disabled_toolsets=[t for t in d["agent"]["disabled_toolsets"] if t != toolset]
        ),
    )
    comp = _component(profile_path, env, "web_toolsets", undisabled)
    assert comp.failed_layer == FailedLayer.CONFIG
    assert f"toolset_not_disabled:{toolset}" in comp.detail


def test_disabled_toolsets_cover_every_pinned_toolset_but_allowlist():
    facts = hermes_config.read_toolset_facts(WEB_CONFIG)
    expected = set(PINNED["basic"]) - {"clarify"}
    assert set(facts.disabled_toolsets) == expected
    assert PINNED["agent_sha"].startswith(
        load_profile(FIXTURES / "profiles" / "synthetic-ok.yaml").hermes_agent.expected_sha
    )


def test_toolset_list_for_another_agent_pin_blocks(web_env):
    profile_path, env, _ = web_env
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    data["hermes_agent"]["expected_sha"] = "0123456789abcdef0123456789abcdef01234567"
    profile_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    comp = _component(profile_path, env, "web_toolsets")
    assert comp.failed_layer == FailedLayer.SCHEMA
    assert "toolset_list_not_for_agent_pin" in comp.detail


def test_pinned_toolset_asset_matches_agent_checkout():
    """Contract: the shipped list equals ``TOOLSETS`` keys at the pinned agent commit."""
    agent_dir = os.environ.get("HFP_HERMES_AGENT_DIR")
    if not agent_dir:
        pytest.skip("HFP_HERMES_AGENT_DIR unset: pinned hermes-agent clone not available")
    source = subprocess.run(
        ["git", "-C", agent_dir, "show", f"{PINNED['agent_sha']}:toolsets.py"],
        capture_output=True, check=True, text=True, encoding="utf-8",
    ).stdout  # fmt: skip
    keys: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TOOLSETS":
            keys = [k.value for k in node.value.keys]  # type: ignore[union-attr]
    assert sorted(keys) == sorted(PINNED["basic"] + PINNED["composite"])
