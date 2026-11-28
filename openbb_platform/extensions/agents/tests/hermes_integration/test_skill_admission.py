"""Read-only admitted skills and quarantined proposals (#1339-T02).

Every skill tree, Hermes config and ACL here lives in a temp dir the test owns.
A same-user deny ACL is tamper-evident, not immutable (plan O6).
"""

# ruff: noqa: D103, S603, S607

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration import hermes_config, skills_admission
from openbb_agents.hermes_integration.hermes_preflight import main
from openbb_agents.hermes_integration.profile import load_profile
from openbb_agents.hermes_integration.skills_admission import (
    TIER_CREATE_DIR,
    TIER_EXTERNAL,
    TIER_LOCAL,
    ProposalRejected,
)

from .conftest import FIXTURES, SENTINELS

HERMES = FIXTURES / "hermes"
PROFILE = FIXTURES / "profiles" / "synthetic-ok.yaml"
SKILL = "portfolio-review"
WHOAMI = os.path.join(os.environ.get("SYSTEMROOT", ""), "System32", "whoami.exe")
# Denying DELETE on files also breaks plain reads, so file deletion stays
# possible and is caught by the hash pin (``missing``/``drift``), not the ACL.
DENY = "(OI)(CI)(WD,AD,WEA,WA,DC)"
BODY = f"---\nname: {SKILL}\ndescription: synthetic\n---\n# Synthetic skill\n"


def _safe_config(tmp_path: Path, **overrides) -> Path:
    data = yaml.safe_load((HERMES / "config-finance-safe.yaml").read_text("utf-8"))
    for dotted, value in overrides.items():
        node = data
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    out = tmp_path / "config.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return out


def _facts(tmp_path: Path, **overrides) -> hermes_config.SkillFacts:
    return hermes_config.read_skill_facts(_safe_config(tmp_path, **overrides))


def _home(tmp_path: Path) -> Path:
    """Build a synthetic Hermes home with one admitted skill in the local tier."""
    home = tmp_path / "qual-home"
    skill = home / "skills" / "finance" / SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(BODY, encoding="utf-8")
    (skill / "references").mkdir()
    (skill / "references" / "notes.md").write_text("synthetic\n", encoding="utf-8")
    return home


def _manifest(home: Path) -> dict[str, str]:
    rel = f"finance/{SKILL}"
    return {rel: skills_admission.tree_sha256(home / "skills" / rel)}


def _current_sid() -> str:
    out = subprocess.run(
        [WHOAMI, "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip().split(",")[-1].strip('"')


@contextmanager
def read_only(path: Path, *, dirs_only: bool = False):
    """Deny writes to ``path`` for the current user, then restore.

    ``dirs_only`` denies directories but leaves files writable.
    """
    if os.name == "nt":
        sid = _current_sid()
        ace = DENY.replace("(OI)", "") if dirs_only else DENY
        subprocess.run(
            ["icacls", str(path), "/deny", f"*{sid}:{ace}"],
            capture_output=True,
            check=True,
        )
        try:
            yield
        finally:
            subprocess.run(
                ["icacls", str(path), "/remove:d", f"*{sid}", "/T"],
                capture_output=True,
                check=True,
            )
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores POSIX write bits")
    modes = {}
    for root, dirs, files in os.walk(path):
        for name in [*dirs, *files, ""]:
            p = Path(root, name) if name else Path(root)
            if dirs_only and p.is_file():
                continue
            modes[p] = p.stat().st_mode
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        yield
    finally:
        for p, mode in modes.items():
            p.chmod(mode)


def _evaluate(home, manifest=None, quarantine=None, **overrides):
    facts = _facts(home.parent, **overrides)
    return skills_admission.evaluate_skills(
        facts,
        _manifest(home) if manifest is None else manifest,
        home / "skills",
        quarantine=quarantine,
    )


# --- seam contract ------------------------------------------------------------------


def test_skill_reader_consumed_keys_exist_in_pinned_defaults_fixture():
    data = yaml.safe_load((HERMES / "config-pinned-defaults.yaml").read_text("utf-8"))
    for dotted in hermes_config.SKILL_CONSUMED_KEYS:
        node = data
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, f"missing {dotted}"
            node = node[part]


def test_pinned_defaults_enable_every_skill_vector():
    facts = hermes_config.read_skill_facts(HERMES / "config-pinned-defaults.yaml")
    assert facts.project_discovery is True
    assert facts.curator_enabled is True
    assert facts.background_review_enabled is True
    assert "skills" not in facts.disabled_toolsets


def test_finance_safe_skill_facts_are_explicitly_off(tmp_path):
    facts = _facts(tmp_path)
    assert facts.project_discovery is False and facts.inline_shell is False
    assert facts.curator_enabled is False and facts.background_review_enabled is False
    assert facts.create_dir is None and facts.external_dirs == []
    assert "skills" in facts.disabled_toolsets


def _route_reasons(config: Path) -> list[str]:
    facts = hermes_config.read_route_facts(config)
    profile = load_profile(PROFILE)
    return hermes_config.evaluate_route(facts, profile).reasons


def test_finance_safe_route_still_admitted_with_background_review_block(tmp_path):
    facts = hermes_config.read_route_facts(_safe_config(tmp_path))
    assert facts.auxiliary["background_review"].provider == "custom"
    reasons = _route_reasons(_safe_config(tmp_path))
    # The skill-writer keys are vetted by the fail-closed route policy (#1338 fix).
    assert not [r for r in reasons if r.startswith("unvetted_key:")], reasons
    assert not [r for r in reasons if r.split("_")[0] in SKILL_SECTIONS], reasons


SKILL_SECTIONS = ("agent", "skills", "curator", "auxiliary")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"skills": "on"}, "skills_unparsed"),
        ({"curator": ["x"]}, "curator_unparsed"),
        ({"agent": 1}, "agent_unparsed"),
        ({"curator.enabled": "false"}, "curator_enabled_not_bool"),
        ({"skills.inline_shell": 0}, "skills_inline_shell_not_bool"),
        ({"skills.project_discovery": "no"}, "skills_project_discovery_not_bool"),
        (
            {"auxiliary.background_review.enabled": "off"},
            "auxiliary_background_review_enabled_not_bool",
        ),
        ({"skills.external_dirs": {"a": 1}}, "skills_external_dirs_not_list"),
        ({"agent.disabled_toolsets": 3}, "agent_disabled_toolsets_not_list"),
        ({"skills.create_dir": ["x"]}, "skills_create_dir_not_str"),
    ],
)
def test_route_policy_refuses_skill_key_shapes_the_reader_ignores(
    tmp_path, overrides, reason
):
    data = yaml.safe_load((HERMES / "config-finance-safe.yaml").read_text("utf-8"))
    for dotted, value in overrides.items():
        node = data
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node[part]
        node[leaf] = value
    out = tmp_path / "config.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert reason in _route_reasons(out)


# --- admission ---------------------------------------------------------------------


def test_read_only_admitted_tree_is_admitted(tmp_path):
    home = _home(tmp_path)
    with read_only(home / "skills"):
        verdict = _evaluate(home)
    assert verdict.blocked is False, verdict.reasons
    assert verdict.admitted == [f"finance/{SKILL}"]


def test_admitted_dir_writable_blocks_skills_layer(tmp_path):
    home = _home(tmp_path)
    verdict = _evaluate(home)
    assert verdict.blocked and "admitted_dir_writable" in verdict.reasons
    leftovers = [p.name for p in (home / "skills").rglob("*") if "probe" in p.name]
    assert leftovers == [], "write probe left a file behind"


def test_admitted_skill_byte_change_blocks_drift(tmp_path):
    home = _home(tmp_path)
    manifest = _manifest(home)
    md = home / "skills" / "finance" / SKILL / "SKILL.md"
    md.write_bytes(md.read_bytes() + b"x")
    with read_only(home / "skills"):
        verdict = _evaluate(home, manifest)
    assert verdict.blocked and f"drift:finance/{SKILL}" in verdict.reasons


def test_added_file_in_admitted_skill_blocks_drift(tmp_path):
    home = _home(tmp_path)
    manifest = _manifest(home)
    (home / "skills" / "finance" / SKILL / "extra.py").write_text("x=1\n", "utf-8")
    verdict = _evaluate(home, manifest)
    assert f"drift:finance/{SKILL}" in verdict.reasons


def test_missing_admitted_skill_blocks(tmp_path):
    home = _home(tmp_path)
    manifest = {**_manifest(home), "finance/absent": "0" * 64}
    assert "missing:finance/absent" in _evaluate(home, manifest).reasons


def test_unadmitted_skill_in_local_tier_blocks(tmp_path):
    home = _home(tmp_path)
    rogue = home / "skills" / "rogue"
    rogue.mkdir()
    (rogue / "SKILL.md").write_text(BODY.replace(SKILL, "rogue"), "utf-8")
    assert "unadmitted_content" in _evaluate(home).reasons


def test_missing_skills_root_blocks(tmp_path):
    facts = _facts(tmp_path)
    verdict = skills_admission.evaluate_skills(facts, {}, tmp_path / "nope" / "skills")
    assert verdict.blocked and "skills_root_missing" in verdict.reasons


@pytest.mark.parametrize("create_dir", ["skills/proposals", "skills"])
def test_create_dir_inside_search_root_blocks(tmp_path, create_dir):
    home = _home(tmp_path)
    verdict = _evaluate(home, **{"skills.create_dir": create_dir})
    if create_dir == "skills":  # upstream treats create_dir == local dir as unset
        assert not any(r.startswith("create_dir") for r in verdict.reasons)
    else:
        assert "create_dir_inside_search_root" in verdict.reasons


def test_create_dir_elsewhere_is_an_unpinned_search_root(tmp_path):
    home = _home(tmp_path)
    verdict = _evaluate(home, **{"skills.create_dir": str(tmp_path / "elsewhere")})
    assert "create_dir_set" in verdict.reasons


def test_external_dirs_block(tmp_path):
    home = _home(tmp_path)
    verdict = _evaluate(home, **{"skills.external_dirs": [str(tmp_path / "x")]})
    assert "external_dirs_set" in verdict.reasons


@pytest.mark.parametrize("value", [True, None, "false"])
def test_project_discovery_true_blocks(tmp_path, value):
    home = _home(tmp_path)
    verdict = _evaluate(home, **{"skills.project_discovery": value})
    assert "project_discovery_enabled" in verdict.reasons


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("curator.enabled", "curator_enabled"),
        ("auxiliary.background_review.enabled", "background_review_enabled"),
        ("skills.inline_shell", "inline_shell_enabled"),
    ],
)
def test_curator_or_background_review_enabled_blocks(tmp_path, key, reason):
    home = _home(tmp_path)
    assert reason in _evaluate(home, **{key: True}).reasons
    assert reason in _evaluate(home, **{key: None}).reasons  # unset = upstream default


@pytest.mark.parametrize("disabled", [[], ["web"], "skills-extra", None])
def test_skill_manage_toolset_enabled_blocks(tmp_path, disabled):
    home = _home(tmp_path)
    verdict = _evaluate(home, **{"agent.disabled_toolsets": disabled})
    assert "skill_manage_enabled" in verdict.reasons


def test_disabled_toolsets_json_string_is_parsed_like_upstream(tmp_path):
    facts = _facts(tmp_path, **{"agent.disabled_toolsets": '["web", "skills"]'})
    assert "skills" in facts.disabled_toolsets


def test_pinned_defaults_block_every_vector(tmp_path):
    home = _home(tmp_path)
    facts = hermes_config.read_skill_facts(HERMES / "config-pinned-defaults.yaml")
    verdict = skills_admission.evaluate_skills(facts, _manifest(home), home / "skills")
    for reason in (
        "project_discovery_enabled",
        "curator_enabled",
        "background_review_enabled",
        "skill_manage_enabled",
    ):
        assert reason in verdict.reasons


# --- search roots and quarantine ----------------------------------------------------


def test_search_roots_follow_pinned_precedence(tmp_path):
    home = tmp_path / "h"
    facts = _facts(
        tmp_path,
        **{"skills.create_dir": "made", "skills.external_dirs": ["~/ext", "ext2"]},
    )
    roots = skills_admission.search_roots(home, facts)
    assert [t for t, _ in roots] == [
        TIER_LOCAL,
        TIER_CREATE_DIR,
        TIER_EXTERNAL,
        TIER_EXTERNAL,
    ]
    assert roots[0][1] == (home / "skills").resolve()
    assert roots[1][1] == (home / "made").resolve()  # relative to HERMES_HOME
    assert roots[3][1] == (home / "ext2").resolve()


def test_proposal_written_only_to_quarantine_and_not_loadable(tmp_path):
    home = _home(tmp_path)
    quarantine = tmp_path / "proposals"
    facts = _facts(tmp_path)
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    path = skills_admission.write_proposal(
        quarantine,
        "new-idea",
        BODY.replace(SKILL, "new-idea"),
        facts=facts,
        skills_root=home / "skills",
        admitted=_manifest(home),
    )
    after = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert [p for p in after if p not in before] == [path]
    assert path == quarantine / "new-idea" / "SKILL.md"
    for _tier, root in skills_admission.search_roots(home, facts):
        assert not skills_admission.overlaps(path, root)
    with read_only(home / "skills"):
        verdict = _evaluate(home, quarantine=quarantine)
    assert verdict.blocked is False, verdict.reasons


def test_quarantine_inside_search_root_rejected(tmp_path):
    home = _home(tmp_path)
    quarantine = home / "skills" / ".proposals"
    with pytest.raises(ProposalRejected, match="quarantine_inside_search_root"):
        skills_admission.write_proposal(
            quarantine,
            "idea",
            BODY,
            facts=_facts(tmp_path),
            skills_root=home / "skills",
            admitted=_manifest(home),
        )
    assert not quarantine.exists()
    assert (
        "quarantine_inside_search_root"
        in _evaluate(home, quarantine=quarantine).reasons
    )


@pytest.mark.parametrize(
    ("name", "body"),
    [
        (SKILL, BODY),  # same dir name
        ("innocent", BODY),  # frontmatter name shadows
        ("innocent", BODY.replace(SKILL, SKILL.upper())),  # case-insensitive
    ],
)
def test_proposal_shadowing_admitted_name_rejected(tmp_path, name, body):
    home = _home(tmp_path)
    quarantine = tmp_path / "proposals"
    with pytest.raises(ProposalRejected, match="shadows_admitted"):
        skills_admission.write_proposal(
            quarantine,
            name,
            body,
            facts=_facts(tmp_path),
            skills_root=home / "skills",
            admitted=_manifest(home),
        )
    assert not (quarantine / name).exists()


def test_existing_shadowing_proposal_blocks_admission(tmp_path):
    home = _home(tmp_path)
    quarantine = tmp_path / "proposals"
    (quarantine / "dup").mkdir(parents=True)
    (quarantine / "dup" / "SKILL.md").write_text(BODY, "utf-8")
    verdict = _evaluate(home, quarantine=quarantine)
    assert f"proposal_shadows_admitted:{SKILL}" in verdict.reasons


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden", "x" * 80])
def test_proposal_name_must_be_a_plain_slug(tmp_path, name):
    home = _home(tmp_path)
    with pytest.raises(ProposalRejected, match="invalid_name"):
        skills_admission.write_proposal(
            tmp_path / "q",
            name,
            BODY,
            facts=_facts(tmp_path),
            skills_root=home / "skills",
            admitted={},
        )


# --- Windows same-user ACL (tamper-evident, not immutable) --------------------------


@pytest.mark.skipif(os.name != "nt", reason="icacls is Windows-only")
def test_icacls_deny_write_on_tmp_dir_detected(tmp_path):
    home = _home(tmp_path)
    assert "admitted_dir_writable" in _evaluate(home).reasons
    with read_only(home / "skills"):
        verdict = _evaluate(home)
        assert verdict.reasons == []
        with pytest.raises(PermissionError):
            (home / "skills" / "finance" / SKILL / "SKILL.md").write_text("x", "utf-8")
    assert "admitted_dir_writable" in _evaluate(home).reasons  # ACE removed again
    shutil.rmtree(home)


# --- preflight wiring ----------------------------------------------------------------


def _cli_profile(tmp_path: Path, manifest: dict[str, str]) -> Path:
    data = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    data["admitted_skills"] = manifest
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return out


def _skills_component(argv, capsys):
    code = main([*argv, "--format", "json"])
    out = capsys.readouterr().out
    report = json.loads(out)
    comp = next(c for c in report["components"] if c["name"] == "skills")
    return code, comp, report, out


def test_cli_skills_admitted_then_drift_blocks(tmp_path, capsys):
    home = _home(tmp_path)
    argv = [
        "--profile",
        str(_cli_profile(tmp_path, _manifest(home))),
        "--hermes-config",
        str(_safe_config(tmp_path)),
        "--skills-root",
        str(home / "skills"),
        "--probe",
        "none",
    ]
    with read_only(home / "skills"):
        code, comp, _, _ = _skills_component(argv, capsys)
    assert comp["level"] == 3 and comp["failed_layer"] is None, comp  # ADMITTED
    md = home / "skills" / "finance" / SKILL / "SKILL.md"
    md.write_bytes(md.read_bytes() + b"x")
    with read_only(home / "skills"):
        code, comp, report, out = _skills_component(argv, capsys)
    assert code == 2 and comp["failed_layer"] == "skills"
    assert f"drift:finance/{SKILL}" in comp["detail"]
    assert "skills" in report["failed_layers"]
    assert str(tmp_path) not in out and not any(v in out for v in SENTINELS.values())


def test_cli_without_skills_root_is_not_evaluated(tmp_path, capsys):
    _, comp, report, _ = _skills_component(["--profile", str(PROFILE)], capsys)
    assert comp["failed_layer"] is None and comp["level"] is None
    assert comp["detail"].startswith("not_evaluated")
    assert "skills" not in report["failed_layers"]


def test_cli_skills_root_without_hermes_config_blocks(tmp_path, capsys):
    home = _home(tmp_path)
    argv = ["--profile", str(PROFILE), "--skills-root", str(home / "skills")]
    code, comp, _, _ = _skills_component(argv, capsys)
    assert code == 2 and comp["failed_layer"] == "skills"
    assert "no_hermes_config" in comp["detail"]


def test_unreadable_admitted_file_is_reported_not_skipped(tmp_path):
    """An unreadable file must never hash as if it were absent."""
    home = _home(tmp_path)
    manifest = _manifest(home)
    notes = home / "skills" / "finance" / SKILL / "references" / "notes.md"
    if os.name == "nt":
        sid = _current_sid()
        subprocess.run(
            ["icacls", str(notes), "/deny", f"*{sid}:(RD)"],
            capture_output=True,
            check=True,
        )
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root ignores POSIX read bits")
        notes.chmod(0)
    try:
        reasons = _evaluate(home, manifest).reasons
    finally:
        if os.name == "nt":
            subprocess.run(
                ["icacls", str(notes), "/remove:d", f"*{sid}"],
                capture_output=True,
                check=True,
            )
        else:
            notes.chmod(0o644)
    assert f"unreadable:finance/{SKILL}" in reasons
    assert f"drift:finance/{SKILL}" not in reasons


def test_writable_file_in_read_only_dir_blocks(tmp_path):
    """The per-file probe catches a writable SKILL.md under a denied directory."""
    home = _home(tmp_path)
    with read_only(home / "skills", dirs_only=True):
        reasons = _evaluate(home).reasons
    assert "admitted_file_writable" in reasons
    assert "admitted_dir_writable" not in reasons
