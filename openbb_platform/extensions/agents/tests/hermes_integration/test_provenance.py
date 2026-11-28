"""Metadata-only provenance checks: wrong origin, wrong database, ABI (#1338-T01)."""

# ruff: noqa: D103, S603

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from openbb_agents.hermes_integration import provenance
from openbb_agents.hermes_integration.hermes_preflight import (
    PreflightOptions,
    main,
    run_preflight,
)
from openbb_agents.hermes_integration.models import (
    FailedLayer,
    HealthLevel,
    Presence,
)
from openbb_agents.hermes_integration.profile import load_profile

from .conftest import FIXTURES, SENTINELS

PROFILE = FIXTURES / "profiles" / "synthetic-ok.yaml"
WRONG_ORIGIN_PROFILE = FIXTURES / "profiles" / "synthetic-wrong-origin.yaml"
SETTINGS_OK = FIXTURES / "settings" / "synthetic-user_settings.json"
SETTINGS_DEFAULT_DB = FIXTURES / "settings" / "synthetic-user_settings-default-db.json"
FMP_DB_MODULE = (
    Path(__file__).resolve().parents[4]
    / "providers"
    / "fmp_cached"
    / "openbb_fmp_cached"
    / "utils"
    / "database.py"
)
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _make_repo(path: Path, remote: str) -> str:
    path.mkdir(parents=True)
    subprocess.run([*GIT, "init", "-q", str(path)], check=True)
    (path / "LICENSE").write_text("MIT synthetic", encoding="utf-8")
    subprocess.run([*GIT, "-C", str(path), "add", "."], check=True)
    subprocess.run([*GIT, "-C", str(path), "commit", "-q", "-m", "x"], check=True)
    subprocess.run(
        [*GIT, "-C", str(path), "remote", "add", "origin", remote], check=True
    )
    out = subprocess.run(
        [*GIT, "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    agent = tmp_path / "agent"
    webui = tmp_path / "webui"
    a_sha = _make_repo(agent, "https://github.com/rashmijain02/hermes-agent.git")
    w_sha = _make_repo(
        webui, "https://token123@github.com/rashmijain02/hermes-webui.git"
    )
    return {"agent": agent, "webui": webui, "a_sha": a_sha, "w_sha": w_sha}


def _profile(repos, agent_sha=None, agent_remote=None):
    prof = load_profile(PROFILE)
    data = prof.model_dump()
    data["hermes_agent"]["expected_sha"] = agent_sha or repos["a_sha"]
    if agent_remote:
        data["hermes_agent"]["expected_remote"] = agent_remote
    data["hermes_webui"]["expected_sha"] = repos["w_sha"]
    return type(prof).model_validate(data)


def _env(repos, **extra):
    env = {
        "HFP_HERMES_AGENT_DIR": str(repos["agent"]),
        "HFP_HERMES_WEBUI_DIR": str(repos["webui"]),
        "HERMES_WEBUI_AGENT_DIR": str(repos["agent"]),
    }
    env.update(extra)
    return env


def _run(repos, profile=None, settings=SETTINGS_OK, env=None):
    return run_preflight(
        profile or _profile(repos),
        PreflightOptions(openbb_settings=settings),
        env=env if env is not None else _env(repos),
    )


def _comp(report, name):
    return next(c for c in report.components if c.name == name)


def test_profile_fixtures_load_and_pin_expected_shas():
    prof = load_profile(PROFILE)
    assert prof.hermes_agent.expected_sha.startswith("710fa8a")
    assert prof.hermes_webui.expected_sha.startswith("22d9840")
    assert prof.database.expected == "openbb_fmp_cache_test"
    wrong = load_profile(WRONG_ORIGIN_PROFILE)
    assert wrong.hermes_agent.dir_env != prof.hermes_agent.dir_env


def test_report_lists_sha_remote_dirty_licence_for_each_component(repos):
    report = _run(repos)
    agent, webui = _comp(report, "hermes_agent"), _comp(report, "hermes_webui")
    assert agent.sha == repos["a_sha"] and webui.sha == repos["w_sha"]
    assert agent.remote == "github.com/rashmijain02/hermes-agent"
    assert agent.dirty is False
    assert agent.license_sha256 and len(agent.license_sha256) == 64
    assert agent.level is HealthLevel.CONFIGURED
    assert webui.level is HealthLevel.CONFIGURED
    # credentials embedded in a remote URL are stripped
    assert webui.remote == "github.com/rashmijain02/hermes-webui"
    assert "token123" not in report.model_dump_json()


def test_dirty_checkout_is_reported(repos):
    (repos["agent"] / "scratch.txt").write_text("x", encoding="utf-8")
    assert _comp(_run(repos), "hermes_agent").dirty is True


def test_secret_shaped_settings_reported_as_presence_only(repos, capsys):
    report = _run(repos)
    blob = report.model_dump_json()
    for needle in ("SYNTHETIC-PASSWORD-SENTINEL", "SYNTHETIC-APIKEY-SENTINEL"):
        assert needle not in blob
    db = _comp(report, "database")
    assert db.presence["mysql_password"] is Presence.PRESENT
    assert db.presence["fmp_cached_api_key"] is Presence.PRESENT
    for fmt in ("json", "text"):
        main(
            [
                "--profile",
                str(PROFILE),
                "--openbb-settings",
                str(SETTINGS_OK),
                "--probe",
                "none",
                "--format",
                fmt,
            ]
        )
    out = capsys.readouterr().out
    assert "database" in out  # the output is not vacuous
    assert "SYNTHETIC-" not in out
    assert not any(v in out for v in SENTINELS.values())


def test_module_origin_has_no_absolute_paths(repos):
    report = _run(repos)
    blob = report.model_dump_json().replace("\\\\", "/")
    assert repos["agent"].parent.as_posix() not in blob
    assert _comp(report, "hermes_agent").origin.startswith("external://")


def test_wrong_remote_or_sha_blocks_module_origin(repos):
    other_sha = "710fa8a073f9a8136e10749b083a16779341faef"
    report = _run(repos, profile=_profile(repos, agent_sha=other_sha))
    agent = _comp(report, "hermes_agent")
    assert report.failed_layer is FailedLayer.MODULE_ORIGIN
    assert agent.failed_layer is FailedLayer.MODULE_ORIGIN
    assert agent.level is None
    assert agent.observed_sha == repos["a_sha"]  # what was actually found
    assert report.qualified is False

    report = _run(
        repos,
        profile=_profile(repos, agent_remote="github.com/NousResearch/hermes-agent"),
    )
    assert _comp(report, "hermes_agent").failed_layer is FailedLayer.MODULE_ORIGIN


def test_missing_dir_env_blocks_module_origin(repos):
    env = _env(repos)
    del env["HFP_HERMES_AGENT_DIR"]
    report = _run(repos, env=env)
    assert _comp(report, "hermes_agent").failed_layer is FailedLayer.MODULE_ORIGIN


def test_webui_agent_dir_unset_resolves_to_unpinned_home_blocks(repos):
    env = _env(repos)
    del env["HERMES_WEBUI_AGENT_DIR"]
    report = _run(repos, env=env)
    webui = _comp(report, "hermes_webui")
    assert webui.failed_layer is FailedLayer.MODULE_ORIGIN
    assert "agent_dir" in webui.detail
    assert report.failed_layer is FailedLayer.MODULE_ORIGIN


def test_webui_agent_dir_pointing_elsewhere_blocks(repos, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    report = _run(repos, env=_env(repos, HERMES_WEBUI_AGENT_DIR=str(other)))
    assert _comp(report, "hermes_webui").failed_layer is FailedLayer.MODULE_ORIGIN


def test_default_fmp_cached_db_name_blocks_wrong_database(repos):
    report = _run(repos, settings=SETTINGS_DEFAULT_DB)
    db = _comp(report, "database")
    assert db.observed_database == "legacy_default"
    assert db.failed_layer is FailedLayer.DATABASE
    assert FailedLayer.DATABASE in report.failed_layers
    assert "wrong_database" in db.detail


def test_expected_db_name_passes(repos):
    report = _run(repos, settings=SETTINGS_OK)
    db = _comp(report, "database")
    assert db.observed_database == "expected"
    assert db.failed_layer is None
    assert FailedLayer.DATABASE not in report.failed_layers


def test_env_db_name_and_test_mode_resolution(tmp_path):
    missing = tmp_path / "none.json"
    r = provenance.resolve_fmp_cached_database(missing, env={})
    assert (r.database, r.source) == ("openbb_fmp_cache", "default")
    r = provenance.resolve_fmp_cached_database(missing, env={"DB_NAME": "x_db"})
    assert (r.database, r.source) == ("x_db", "env")
    r = provenance.resolve_fmp_cached_database(
        missing, env={"FMP_CACHE_TEST_MODE": "true"}
    )
    assert r.database == "openbb_fmp_cache_test"


def test_resolver_matches_real_fmp_cached_load_config(tmp_path, monkeypatch):
    """Seam contract: our resolver agrees with the production DatabaseConfig."""
    database = pytest.importorskip("openbb_fmp_cached.utils.database")
    for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FMP_CACHE_TEST_MODE", raising=False)
    seen = set()
    for settings in (SETTINGS_OK, SETTINGS_DEFAULT_DB, tmp_path / "absent.json"):
        home = tmp_path / f"h-{settings.stem}"
        (home / ".openbb_platform").mkdir(parents=True)
        target = home / ".openbb_platform" / "user_settings.json"
        if settings.exists():
            target.write_text(settings.read_text("utf-8"), encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        real = database.DatabaseConfig._load_config(  # noqa: SLF001
            object.__new__(database.DatabaseConfig)
        )
        mine = provenance.resolve_fmp_cached_database(target, env={})
        assert mine.database == real["database"], settings.name
        seen.add(real["database"])
    assert seen == {"openbb_fmp_cache", "openbb_fmp_cache_test"}


def test_resolver_keys_are_pinned_to_fmp_cached_source():
    assert FMP_DB_MODULE.exists(), FMP_DB_MODULE
    tree = ast.parse(FMP_DB_MODULE.read_text("utf-8"))
    constants = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    consumed = (
        set(provenance.SETTINGS_DB_KEYS)
        | set(provenance.SETTINGS_ANY_KEYS)
        | set(provenance.ENV_VARS)
        | {provenance.DEFAULT_DB, provenance.TEST_DB}
    )
    assert consumed <= constants, sorted(consumed - constants)


def test_pyvenv_version_outside_hermes_requires_python_blocks_abi(repos, tmp_path):
    venv = tmp_path / "venv"
    venv.mkdir()
    cfg = venv / "pyvenv.cfg"

    def abi(text):
        cfg.write_text(text, encoding="utf-8")
        env = _env(repos, HFP_HERMES_RUNTIME_VENV=str(venv))
        return _run(repos, env=env)

    report = abi("home = x\nversion = 3.12.15\n")
    assert report.failed_layer is FailedLayer.ABI
    assert _comp(report, "python_abi").observed_python == "3.12.15"

    report = abi("home = x\nversion_info = 3.14.2.final.0\n")
    assert FailedLayer.ABI not in report.failed_layers
    assert _comp(report, "python_abi").level is HealthLevel.CONFIGURED

    # inside <3.15 and >=3.11 but not the supported 3.14: still blocked
    assert FailedLayer.ABI in abi("home = x\nversion = 3.11.9\n").failed_layers


def test_t01_has_no_local_route_so_route_layer_fails(repos):
    report = _run(repos)
    assert FailedLayer.ROUTE in report.failed_layers
    assert report.failed_layer is FailedLayer.ROUTE
    assert report.qualified is False


def test_exit_codes_blocked_is_2_usage_is_3(capsys):
    argv = ["--profile", str(PROFILE), "--probe", "none", "--format", "json"]
    # no checkout env vars set -> module_origin blocked
    assert main(argv) == 2
    assert json.loads(capsys.readouterr().out)["qualified"] is False
    assert main(["--profile", str(PROFILE.with_name("nope.yaml"))]) == 3
    assert main(["--profile", str(PROFILE), "--format", "bogus"]) == 3


def test_preflight_never_spawns_hermes_or_pip(repos, monkeypatch):
    calls: list[str] = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def guard(args):
        exe = args[0] if isinstance(args, (list, tuple)) else str(args).split()[0]
        name = Path(str(exe)).name
        calls.append(name)
        assert name == "git", f"non-git executable: {exe!r}"

    def run(args, *a, **kw):
        guard(args)
        return real_run(args, *a, **kw)

    class Popen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):
            guard(args)
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", Popen)
    _run(repos)
    assert calls and set(calls) == {"git"}
    assert "hermes_cli" not in sys.modules


# --- review fixes: default settings path, malformed inputs (#1338 CODE-3, CODE-4) ---------


def _home_settings(home, credentials):
    path = home / ".openbb_platform" / "user_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"credentials": credentials}), encoding="utf-8")
    return path


def test_wrong_db_in_home_settings_is_caught_without_the_flag(repos, isolated_home):
    _home_settings(isolated_home, {"mysql_user": "u", "mysql_database": "other_db"})
    report = run_preflight(_profile(repos), env=_env(repos))
    db = _comp(report, "database")
    assert db.failed_layer is FailedLayer.DATABASE
    assert db.observed_database == "other"
    assert "other_db" not in report.model_dump_json()


def test_non_loopback_mysql_host_in_home_settings_blocks_without_the_flag(
    repos, isolated_home
):
    from openbb_agents.hermes_integration import handshake

    _home_settings(isolated_home, {"mysql_host": "db.example.invalid"})
    seen = []

    class NoNet(handshake.LoopbackTransport):
        def tcp_connect(self, host, port, timeout):
            seen.append((host, port))
            return handshake.ProbeResult("refused")

    report = run_preflight(
        _profile(repos),
        PreflightOptions(probe="loopback"),
        env=_env(repos),
        transport=NoNet(),
    )
    mysql = next(e for e in report.edges if e.name == "openbb_mysql")
    assert mysql.detail == "mysql_host_not_loopback" and seen == []


def test_non_mapping_settings_json_falls_back_with_a_reason(repos, tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    report = _run(repos, settings=bad)
    db = _comp(report, "database")
    assert db.observed_database == "legacy_default"
    assert "settings_not_a_mapping" in db.detail


def test_malformed_profile_yaml_exits_3(tmp_path, capsys):
    bad = tmp_path / "profile.yaml"
    bad.write_text("a: [b\n", encoding="utf-8")
    assert main(["--profile", str(bad)]) == 3


@pytest.mark.parametrize("payload", ["[1, 2]", '["x"]', '[{"name": "t"}, 3]'])
def test_mcp_tools_with_non_mapping_items_exits_3(tmp_path, payload):
    tools = tmp_path / "tools.json"
    tools.write_text(payload, encoding="utf-8")
    assert main(["--profile", str(PROFILE), "--mcp-tools", str(tools)]) == 3


def test_db_name_rendered_as_category_only(repos):
    report = _run(repos, settings=SETTINGS_OK)
    text = report.model_dump_json()
    assert _comp(report, "database").observed_database == "expected"
    assert "openbb_fmp_cache_test" not in text


def test_git_runs_with_fsmonitor_disabled(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        raise OSError("not run")

    monkeypatch.setattr(provenance.subprocess, "run", fake_run)
    provenance.git_facts(tmp_path)
    assert calls and all(c[:3] == ["git", "-c", "core.fsmonitor=false"] for c in calls)
