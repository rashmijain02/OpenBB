"""Metadata-only preflight for the Hermes finance runtime (#1338).

Usage: ``python -m openbb_agents.hermes_integration.hermes_preflight --profile P``.
Exit 0 qualified, 2 blocked, 3 usage. It never runs Hermes, pip or any service.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import handshake, hermes_config, litellm_config, provenance
from .models import (
    ComponentReport,
    EdgeReport,
    FailedLayer,
    GatewayReport,
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
    base = ComponentReport(
        name=name,
        sha=facts.sha,
        remote=facts.remote,
        dirty=facts.dirty,
        license_sha256=provenance.license_sha256(directory),
        origin=provenance.origin_of(directory),
    )
    problems = []
    if not facts.sha or not facts.sha.startswith(pin.expected_sha):
        problems.append("wrong_sha")
    if facts.remote != provenance.normalize_remote(pin.expected_remote):
        problems.append("wrong_remote")
    if problems:
        return base.model_copy(
            update={
                "observed_sha": facts.sha,
                "failed_layer": FailedLayer.MODULE_ORIGIN,
                "detail": f"wrong_origin: {','.join(problems)}",
            }
        )
    return base.model_copy(update={"level": HealthLevel.CONFIGURED})


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
    category = provenance.db_category(resolved.database, profile.database.expected)
    notes = "".join(f"; {issue}" for issue in resolved.issues)
    if category != "expected":
        return ComponentReport(
            name="database",
            failed_layer=FailedLayer.DATABASE,
            observed_database=category,
            presence=resolved.presence,
            detail=f"wrong_database: observed {category}{notes}",
        )
    return ComponentReport(
        name="database",
        level=HealthLevel.CONFIGURED,
        observed_database=category,
        presence=resolved.presence,
        detail=f"source={resolved.source}{notes}",
    )


def _check_route(
    profile: FinanceRuntimeProfile, config: Path | None
) -> tuple[list[ComponentReport], hermes_config.RouteFacts | None]:
    """Route policy from the Hermes config; no config means no verified route."""
    if config is None:
        return [
            ComponentReport(
                name="route",
                failed_layer=FailedLayer.ROUTE,
                detail="no_local_route: no verified local backend bound (see #1338 T03)",
            )
        ], None
    # Hermes deep-merges a managed-scope config.yaml over the user config at load time.
    managed = hermes_config.managed_config_path()
    try:
        facts = hermes_config.read_route_facts(config, managed)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [
            ComponentReport(
                name="hermes_config",
                failed_layer=FailedLayer.CONFIG,
                detail=f"config_unreadable: {type(exc).__name__}",
            ),
            ComponentReport(
                name="route",
                failed_layer=FailedLayer.ROUTE,
                detail="no_local_route: hermes config unreadable",
            ),
        ], None
    verdict = hermes_config.evaluate_route(facts, profile)
    cfg = ComponentReport(
        name="hermes_config",
        level=HealthLevel.CONFIGURED,
        presence={"model_api_key": facts.api_key},
        detail="managed_scope_merged" if managed is not None else "",
    )
    if verdict.blocked:
        route = ComponentReport(
            name="route",
            failed_layer=FailedLayer.ROUTE,
            detail="route_blocked: " + ",".join(verdict.reasons),
        )
    else:
        route = ComponentReport(
            name="route", level=HealthLevel.ADMITTED, detail="local_route_admitted"
        )
    return [cfg, route], facts


def _check_gateway(
    profile: FinanceRuntimeProfile, config: Path | None
) -> tuple[list[ComponentReport], GatewayReport | None]:
    """Classify proxy aliases; the private route needs a local, isolated alias."""
    if config is None:
        return [], None
    try:
        facts = litellm_config.read_gateway_facts(config, profile)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [
            ComponentReport(
                name="litellm_config",
                failed_layer=FailedLayer.CONFIG,
                detail=f"config_unreadable: {type(exc).__name__}",
            )
        ], None
    verdict = litellm_config.evaluate_gateway(facts, profile)
    report = litellm_config.gateway_report(facts, verdict)
    cfg = ComponentReport(
        name="litellm_config",
        level=HealthLevel.CONFIGURED,
        presence={k: v.presence for k, v in facts.secrets.items()},
    )
    counts = f"local={report.local} hosted={report.hosted}"
    if verdict.blocked:
        route = ComponentReport(
            name="litellm_routes",
            failed_layer=FailedLayer.ROUTE,
            detail=f"private_route=BLOCKED {counts}: " + ",".join(verdict.reasons),
        )
    else:
        route = ComponentReport(
            name="litellm_routes",
            level=HealthLevel.ADMITTED,
            detail=f"private_route=ADMITTED {counts}",
        )
    return [cfg, route], report


@dataclass(frozen=True)
class PreflightOptions:
    """Inputs of one preflight run besides the profile, env and transport."""

    openbb_settings: Path | None = None
    hermes_config_path: Path | None = None
    litellm_config_path: Path | None = None
    probe: str = "none"
    mcp_tools: Sequence[Mapping[str, Any]] | None = None
    mcp_http_url: str | None = None
    backend_base_url: str | None = None
    timeout: float = 5.0


def run_preflight(
    profile: FinanceRuntimeProfile,
    options: PreflightOptions | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: handshake.Transport | None = None,
) -> PreflightReport:
    """Run all checks. ``probe="loopback"`` adds the handshake edges. Never executes Hermes."""
    opts = options or PreflightOptions()
    env = os.environ if env is None else env
    # Like ``DatabaseConfig``: no flag means the per-user settings file.
    settings = opts.openbb_settings or provenance.default_settings_path()
    route_components, facts = _check_route(profile, opts.hermes_config_path)
    gateway_components, gateway = _check_gateway(profile, opts.litellm_config_path)
    components = [
        _check_checkout("hermes_agent", profile.hermes_agent, env),
        _check_webui(profile, env),
        _check_abi(profile, env),
        _check_database(profile, settings, env),
        *route_components,
        *gateway_components,
    ]
    edges: list[EdgeReport] = []
    if opts.probe == "loopback":
        edges = handshake.run_handshake(
            profile,
            facts,
            env=env,
            transport=transport,
            options=handshake.HandshakeOptions(
                settings_path=settings,
                mcp_tools=opts.mcp_tools,
                mcp_http_url=opts.mcp_http_url,
                backend_base_url=opts.backend_base_url,
                timeout=opts.timeout,
            ),
        )
    failed = {c.failed_layer for c in components if c.failed_layer is not None}
    failed |= {e.failed_layer for e in edges if e.failed_layer is not None}
    layers = [layer for layer in _LAYER_ORDER if layer in failed]
    qualified = not layers and all(c.level == HealthLevel.QUALIFIED for c in components)
    return PreflightReport(
        components=components,
        edges=edges,
        gateway=gateway,
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
    for edge in report.edges:
        lines.append(
            f"edge {edge.name} status={edge.status.value} "
            f"level={edge.level.name.lower() if edge.level else 'none'} "
            f"callable={edge.callable} "
            f"failed_layer={edge.failed_layer.value if edge.failed_layer else '-'}"
            + (f" detail={edge.detail}" if edge.detail else "")
        )
    if report.gateway is not None:
        for alias in report.gateway.aliases:
            lines.append(
                f"alias {alias.name} kind={alias.kind.value}"
                + (f" reasons={','.join(alias.reasons)}" if alias.reasons else "")
            )
    layer = report.failed_layer.value if report.failed_layer else "-"
    lines.append(f"qualified={report.qualified} failed_layer={layer}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="hermes_preflight", description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--openbb-settings", type=Path, default=None)
    parser.add_argument("--hermes-config", type=Path, default=None)
    parser.add_argument("--litellm-config", type=Path, default=None)
    parser.add_argument("--mcp-tools", type=Path, default=None, help="JSON tool list")
    parser.add_argument("--mcp-http-url", default=None)
    parser.add_argument("--backend-url", default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--probe", choices=["none", "loopback"], default="none")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        sys.stderr.write(f"cannot load profile: {type(exc).__name__}\n")
        return 3
    tools = None
    if args.mcp_tools is not None:
        try:
            tools = json.loads(args.mcp_tools.read_text(encoding="utf-8"))
            if not isinstance(tools, list) or not all(
                isinstance(t, dict) for t in tools
            ):
                raise ValueError("tool list is not a list of objects")
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"cannot load mcp tools: {type(exc).__name__}\n")
            return 3
    report = run_preflight(
        profile,
        PreflightOptions(
            openbb_settings=args.openbb_settings,
            hermes_config_path=args.hermes_config,
            litellm_config_path=args.litellm_config,
            probe=args.probe,
            mcp_tools=tools,
            mcp_http_url=args.mcp_http_url,
            backend_base_url=args.backend_url,
            timeout=args.timeout,
        ),
    )
    text = (
        report.model_dump_json(indent=2)
        if args.format == "json"
        else _render_text(report)
    )
    sys.stdout.write(text + "\n")
    return 0 if report.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
