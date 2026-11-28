"""Metadata-only preflight for the Hermes finance runtime (#1338).

Usage: ``python -m openbb_agents.hermes_integration.hermes_preflight --profile P``.
Exit 0 qualified, 2 blocked, 3 usage. It never runs Hermes, pip or any service.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import provenance
from .models import (
    ComponentReport,
    FailedLayer,
    HealthLevel,
    PreflightReport,
)
from .profile import ComponentPin, FinanceRuntimeProfile, load_profile

_LAYER_ORDER = list(FailedLayer)


def _same_dir(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b)
    )


def _check_checkout(
    name: str, pin: ComponentPin, env: Mapping[str, str]
) -> ComponentReport:
    raw = env.get(pin.dir_env)
    if not raw:
        return ComponentReport(
            name=name,
            failed_layer=FailedLayer.MODULE_ORIGIN,
            detail=f"dir_env_unset: {pin.dir_env}",
        )
    directory = Path(raw)
    if not directory.is_dir():
        return ComponentReport(
            name=name,
            failed_layer=FailedLayer.MODULE_ORIGIN,
            detail=f"not_a_directory: {pin.dir_env}",
        )
    facts = provenance.git_facts(directory)
    common = {
        "name": name,
        "sha": facts.sha,
        "remote": facts.remote,
        "dirty": facts.dirty,
        "license_sha256": provenance.license_sha256(directory),
        "origin": provenance.origin_of(directory),
    }
    problems = []
    if not facts.sha or not facts.sha.startswith(pin.expected_sha):
        problems.append("wrong_sha")
    if facts.remote != provenance.normalize_remote(pin.expected_remote):
        problems.append("wrong_remote")
    if problems:
        return ComponentReport(
            **common,
            observed_sha=facts.sha,
            failed_layer=FailedLayer.MODULE_ORIGIN,
            detail=f"wrong_origin: {','.join(problems)}",
        )
    return ComponentReport(**common, level=HealthLevel.CONFIGURED)


def _check_webui(
    profile: FinanceRuntimeProfile, env: Mapping[str, str]
) -> ComponentReport:
    report = _check_checkout("hermes_webui", profile.hermes_webui, env)
    if report.failed_layer is not None:
        return report
    agent_env = profile.hermes_webui.agent_dir_env or "HERMES_WEBUI_AGENT_DIR"
    webui_agent = env.get(agent_env)
    pinned_agent = env.get(profile.hermes_agent.dir_env)
    if not webui_agent:
        detail = f"agent_dir_unset: {agent_env} would auto-discover an unpinned home"
    elif not pinned_agent or not _same_dir(webui_agent, pinned_agent):
        detail = f"agent_dir_mismatch: {agent_env} is not the pinned agent checkout"
    else:
        return report
    return report.model_copy(
        update={
            "level": None,
            "failed_layer": FailedLayer.MODULE_ORIGIN,
            "detail": detail,
        }
    )


def _check_abi(
    profile: FinanceRuntimeProfile, env: Mapping[str, str]
) -> ComponentReport:
    pin = profile.python
    raw = env.get(pin.venv_env)
    if not raw:
        return ComponentReport(
            name="python_abi", detail=f"not_evaluated: {pin.venv_env} unset"
        )
    version = provenance.read_pyvenv_version(Path(raw))
    if version is None:
        return ComponentReport(
            name="python_abi",
            failed_layer=FailedLayer.ABI,
            detail="pyvenv_cfg_unreadable",
        )
    if not provenance.python_matches(version, pin.requires, pin.supported):
        return ComponentReport(
            name="python_abi",
            failed_layer=FailedLayer.ABI,
            observed_python=version,
            detail=f"abi_mismatch: requires {pin.requires}, supported {pin.supported}",
        )
    return ComponentReport(
        name="python_abi", level=HealthLevel.CONFIGURED, observed_python=version
    )


def _check_database(
    profile: FinanceRuntimeProfile, settings: Path | None, env: Mapping[str, str]
) -> ComponentReport:
    resolved = provenance.resolve_fmp_cached_database(settings, env)
    expected = profile.database.expected
    if resolved.database != expected:
        return ComponentReport(
            name="database",
            failed_layer=FailedLayer.DATABASE,
            observed_database=resolved.database,
            presence=resolved.presence,
            detail=f"wrong_database: observed {resolved.database}, expected {expected}",
        )
    return ComponentReport(
        name="database",
        level=HealthLevel.CONFIGURED,
        observed_database=resolved.database,
        presence=resolved.presence,
        detail=f"source={resolved.source}",
    )


def run_preflight(
    profile: FinanceRuntimeProfile,
    *,
    env: Mapping[str, str] | None = None,
    openbb_settings: Path | None = None,
) -> PreflightReport:
    """Run all metadata-only checks. Never executes Hermes."""
    env = os.environ if env is None else env
    components = [
        _check_checkout("hermes_agent", profile.hermes_agent, env),
        _check_webui(profile, env),
        _check_abi(profile, env),
        _check_database(profile, openbb_settings, env),
        ComponentReport(
            name="route",
            failed_layer=FailedLayer.ROUTE,
            detail="no_local_route: no verified local backend bound (see #1338 T03)",
        ),
    ]
    failed = {c.failed_layer for c in components if c.failed_layer is not None}
    layers = [layer for layer in _LAYER_ORDER if layer in failed]
    qualified = not layers and all(c.level == HealthLevel.QUALIFIED for c in components)
    return PreflightReport(
        components=components,
        failed_layers=layers,
        failed_layer=layers[0] if layers else None,
        qualified=qualified,
    )


def _render_text(report: PreflightReport) -> str:
    lines = []
    for comp in report.components:
        parts = [
            comp.name,
            f"level={comp.level.name.lower() if comp.level else 'none'}",
            f"failed_layer={comp.failed_layer.value if comp.failed_layer else '-'}",
        ]
        for label in ("sha", "observed_sha", "remote", "observed_python"):
            value = getattr(comp, label)
            if value:
                parts.append(f"{label}={value}")
        if comp.observed_database:
            parts.append(f"db={comp.observed_database}")
        for key, flag in comp.presence.items():
            parts.append(f"{key}={flag.value}")
        if comp.detail:
            parts.append(f"detail={comp.detail}")
        lines.append(" ".join(parts))
    layer = report.failed_layer.value if report.failed_layer else "-"
    lines.append(f"qualified={report.qualified} failed_layer={layer}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="hermes_preflight", description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--openbb-settings", type=Path, default=None)
    parser.add_argument("--probe", choices=["none", "loopback"], default="none")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    if args.probe != "none":
        sys.stderr.write("probe=loopback is not implemented yet (#1338 T02)\n")
        return 3
    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"cannot load profile: {type(exc).__name__}\n")
        return 3
    report = run_preflight(profile, openbb_settings=args.openbb_settings)
    text = (
        report.model_dump_json(indent=2)
        if args.format == "json"
        else _render_text(report)
    )
    sys.stdout.write(text + "\n")
    return 0 if report.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
