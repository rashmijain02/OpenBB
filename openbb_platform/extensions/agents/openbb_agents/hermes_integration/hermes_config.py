"""Metadata-only Hermes ``config.yaml`` reader and route policy (#1338-T02).

The reader keeps routing facts only. Secret-shaped keys become :class:`Presence`
and URL credentials are dropped. Nothing here imports or runs Hermes.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .models import Presence
from .profile import FinanceRuntimeProfile

# Dotted keys the reader consumes. A seam-contract test pins these against a
# fixture trimmed from the pinned Hermes ``cli-config.yaml.example``.
CONSUMED_KEYS = (
    "model.default",
    "model.provider",
    "model.base_url",
    "fallback_providers",
    "delegation.fallback_providers",
    "auxiliary",
    "auth.adopt_external_logins",
)

# Fail-closed allowlists derived from Hermes ``DEFAULT_CONFIG`` at the pin
# (rashmijain02/hermes-agent 710fa8a, ``hermes_cli/config_defaults.py``). A
# top-level key outside both sets blocks the route as ``unvetted_key:<key>``.
#
# Top-level keys with no influence on which model, provider or host gets a request.
HARMLESS_TOP_LEVEL = frozenset(
    {
        "_config_version",
        "agent",
        "approvals",
        "attachments",
        "checkpoints",
        "command_allowlist",
        "compression",  # thresholds only; the summarizer is ``auxiliary.compression``
        "context_file_max_chars",
        "context_file_read_timeout",
        "database",
        "display",
        "doctor",
        "fallback",  # ``min_switch_reset_seconds`` timer only
        "file_read_max_chars",
        "human_delay",
        "logging",
        "max_concurrent_sessions",
        "max_live_sessions",
        "mcp",  # discovery settings; servers live in ``mcp_servers``
        "mcp_discovery_timeout",
        "mcp_single_query_discovery_timeout",
        "onboarding",
        "paste_collapse_char_threshold",
        "paste_collapse_threshold",
        "paste_collapse_threshold_fallback",
        "platform_toolsets",
        "privacy",
        "prompt_caching",
        "runtime",
        "session",
        "sessions",
        "streaming",
        "timezone",
        "tool_loop_guardrails",
        "tool_output",
        "toolsets",
        "updates",
        "worktrees",
    }
)
# Top-level keys this policy reads and polices (pinned plus legacy routing keys).
POLICED_TOP_LEVEL = frozenset(
    {
        "auth",
        "auxiliary",
        "custom_providers",
        "delegation",
        "fallback_model",
        "fallback_providers",
        "mcp_servers",
        "memory",
        "model",
        "model_aliases",
        "platforms",
        "providers",
        "smart_model_routing",
        "telemetry",
    }
)
# Every auxiliary task in the pinned ``DEFAULT_CONFIG["auxiliary"]``. An absent task
# means upstream ``provider: auto``, so each must be explicitly custom + loopback.
AUXILIARY_TASKS = (
    "approval",
    "background_review",
    "compression",
    "curator",
    "goal_judge",
    "kanban_decomposer",
    "mcp",
    "memory_query_rewrite",
    "moa_aggregator",
    "moa_reference",
    "monitor",
    "profile_describer",
    "review",
    "skills_hub",
    "title_generation",
    "triage_specifier",
    "tts_audio_tags",
    "vision",
    "voice_chat",
)
# Non-task ``auxiliary`` settings with no routing effect.
AUXILIARY_SETTINGS = frozenset(
    {"transient_retries", "free_only", "stream_only_base_urls"}
)
# Delegation keys that pick another route; ``backend`` is allowed only as ``default``.
DELEGATION_ROUTE_KEYS = (
    "provider",
    "base_url",
    "model",
    "api_mode",
    "backends",
    "request_overrides",  # merged into every child request (incl. extra_body)
)
_URL_KEYS = ("base_url", "url", "api", "inference_base_url")
# Leaf keys whose value is a credential, never a route: a ``${VAR}`` there is allowed.
_SECRET_LEAF = re.compile(r"(?:^|_)(?:api_key|key|token|password|secret)$")
_LABEL = re.compile(r"[^A-Za-z0-9_.-]")

_LOOPBACK_NAMES = {"localhost"}
# Managed-scope directory default at the pin (``hermes_cli/managed_scope.py``).
_DEFAULT_MANAGED_DIR = Path("/etc/hermes")


def is_loopback_host(host: str | None) -> bool:
    """Return True for ``localhost`` and loopback IP literals only."""
    if not host:
        return False
    host = host.strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def safe_label(value: object, limit: int = 40) -> str:
    """Key-like label for reason codes: ``[A-Za-z0-9_.-]`` only, length-capped."""
    return _LABEL.sub("_", str(value))[:limit] or "_"


class AuxRoute(BaseModel):
    """Routing facts of one auxiliary task. Holds no secret values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str | None = None
    host: str | None = None
    port: int | None = None
    model: str | None = None


class RouteFacts(BaseModel):
    """Routing facts from a Hermes config. Holds no secret values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_default: str | None = None
    provider: str | None = None
    base_host: str | None = None
    base_port: int | None = None
    base_path: str = ""
    base_scheme: str | None = None
    api_key: Presence = Presence.ABSENT
    fallback_providers: int = 0
    delegation_fallback_providers: int = 0
    auxiliary: dict[str, AuxRoute] = Field(default_factory=dict)
    adopt_external_logins: bool | None = None
    # ``providers``/``custom_providers`` label -> (host, port) of each URL it names.
    provider_endpoints: dict[str, list[tuple[str | None, int | None]]] = Field(
        default_factory=dict
    )
    # Fail-closed findings from keys outside the main route (labels, never values).
    unvetted_keys: list[str] = Field(default_factory=list)
    route_issues: list[str] = Field(default_factory=list)


class RouteVerdict(BaseModel):
    """Policy result; ``blocked`` holds reason codes, never values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blocked: bool
    reasons: list[str]


def _get(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _count(value: Any) -> int:
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return 1 if value else 0


def _split(url: Any) -> tuple[str | None, int | None, str, str | None]:
    if not isinstance(url, str) or not url:
        return None, None, "", None
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None and parts.scheme in ("http", "https"):
        port = 443 if parts.scheme == "https" else 80
    return parts.hostname, port, parts.path.rstrip("/"), parts.scheme or None


def _set(value: Any) -> bool:
    """Return True for a configured value; empty strings, lists and maps are unset."""
    return value not in (None, "", [], {}, ())


def _entry_local(entry: Any) -> bool:
    """Return True if the entry names URLs and every one is loopback."""
    if not isinstance(entry, dict):
        return False
    urls = [entry[k] for k in _URL_KEYS if isinstance(entry.get(k), str) and entry[k]]
    return bool(urls) and all(is_loopback_host(_split(u)[0]) for u in urls)


def url_has_userinfo(url: str) -> bool:
    """Return True for userinfo in the authority, or a backslash read as a slash."""
    return "\\" in url or "@" in urlsplit(url).netloc


def _scan_values(node: Any, path: str = "") -> list[str]:
    """Hermes expands ``${VAR}``/``${env:VAR}`` in every string (``_expand_env_vars`` at the
    pin), so an env ref can rewrite any route after this check. Block every ref outside a
    secret-valued leaf, and userinfo in every URL-valued key.
    """
    issues: list[str] = []
    items = (
        node.items()
        if isinstance(node, dict)
        else enumerate(node) if isinstance(node, list) else ()
    )
    for key, value in items:
        here = f"{path}.{key}" if path else str(key)
        if isinstance(value, (dict, list)):
            issues += _scan_values(value, here)
        elif isinstance(value, str):
            leaf = str(key).lower()
            if "${" in value and not _SECRET_LEAF.search(leaf):
                issues.append(f"env_ref:{safe_label(here, 80)}")
            if leaf in (*_URL_KEYS, "api_base") and url_has_userinfo(value):
                issues.append(f"url_userinfo:{safe_label(here, 80)}")
    return issues


def _provider_endpoints(
    loaded: dict[str, Any],
) -> dict[str, list[tuple[str | None, int | None]]]:
    """Endpoints of every ``providers``/``custom_providers`` entry, by reason label."""
    entries: list[tuple[str, Any]] = []
    providers = loaded.get("providers")
    if isinstance(providers, dict):
        entries += [(f"providers_{safe_label(n)}", e) for n, e in providers.items()]
    custom = loaded.get("custom_providers")
    if isinstance(custom, list):
        entries += [(f"custom_providers_{i}", e) for i, e in enumerate(custom)]
    out: dict[str, list[tuple[str | None, int | None]]] = {}
    for label, entry in entries:
        if isinstance(entry, dict):
            out[label] = [
                _split(entry[k])[:2]
                for k in _URL_KEYS
                if isinstance(entry.get(k), str) and entry[k]
            ]
    return out


def _scan_top_level(loaded: dict[str, Any]) -> list[str]:
    allowed = HARMLESS_TOP_LEVEL | POLICED_TOP_LEVEL
    return [safe_label(k) for k in loaded if str(k) not in allowed]


def _scan_delegation(loaded: dict[str, Any]) -> list[str]:
    deleg = loaded.get("delegation")
    if deleg is None:
        return []
    if not isinstance(deleg, dict):
        return ["delegation_unparsed"]
    issues = [
        f"delegation_{k}_set" for k in DELEGATION_ROUTE_KEYS if _set(deleg.get(k))
    ]
    if deleg.get("backend") not in (None, "", "default"):
        issues.append("delegation_backend_not_default")
    return issues


def _scan_providers(loaded: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    providers = loaded.get("providers")
    if isinstance(providers, dict):
        issues += [
            f"providers_{safe_label(name)}_not_loopback"
            for name, entry in providers.items()
            if not _entry_local(entry)
        ]
    elif _set(providers):
        issues.append("providers_unparsed")
    custom = loaded.get("custom_providers")
    if isinstance(custom, list):
        issues += [
            f"custom_providers_{i}_not_loopback"
            for i, entry in enumerate(custom)
            if not _entry_local(entry)
        ]
    elif _set(custom):
        issues.append("custom_providers_unparsed")
    return issues


def _scan_surfaces(loaded: dict[str, Any]) -> tuple[list[str], list[str]]:
    """``platforms`` (only ``api_server`` is vetted) and ``mcp_servers`` URLs."""
    unvetted: list[str] = []
    issues: list[str] = []
    platforms = loaded.get("platforms")
    if isinstance(platforms, dict):
        for name, cfg in platforms.items():
            if str(name) != "api_server":
                unvetted.append(f"platforms.{safe_label(name)}")
            elif _set(_get(cfg if isinstance(cfg, dict) else {}, "extra.model_routes")):
                issues.append("platforms_api_server_model_routes_set")
    elif _set(platforms):
        issues.append("platforms_unparsed")
    servers = loaded.get("mcp_servers")
    if isinstance(servers, dict):
        for name, entry in servers.items():
            url = entry.get("url") if isinstance(entry, dict) else None
            if not isinstance(entry, dict) or (
                url and not is_loopback_host(_split(url)[0])
            ):
                issues.append(f"mcp_servers_{safe_label(name)}_not_loopback")
    elif _set(servers):
        issues.append("mcp_servers_unparsed")
    return unvetted, issues


def _scan_misc(loaded: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if _set(loaded.get("fallback_model")):  # legacy single fallback route
        issues.append("fallback_model_set")
    if _set(loaded.get("model_aliases")):
        issues.append("model_aliases_set")
    smr = loaded.get("smart_model_routing")
    if smr is not None and not (isinstance(smr, dict) and smr.get("enabled") is False):
        issues.append("smart_model_routing_not_disabled")
    if _set(_get(loaded, "memory.provider")):  # external memory providers are hosted
        issues.append("memory_provider_set")
    metrics = _get(loaded, "telemetry.shared_metrics")
    if isinstance(metrics, dict) and True in (
        metrics.get("enabled"),
        metrics.get("send"),
    ):
        issues.append("telemetry_enabled")
    return issues


def _read_auxiliary(
    aux_raw: Any,
) -> tuple[dict[str, AuxRoute], list[str], list[str]]:
    """Task routes; unknown mapping-valued keys are treated as tasks (fail closed)."""
    routes: dict[str, AuxRoute] = {}
    unvetted: list[str] = []
    issues: list[str] = []
    if not isinstance(aux_raw, dict):
        return routes, unvetted, (["auxiliary_unparsed"] if _set(aux_raw) else [])
    for key, cfg in aux_raw.items():
        task = str(key)
        if task in AUXILIARY_SETTINGS:
            continue
        if task == "openrouter_model":
            if _set(cfg):
                issues.append("auxiliary_openrouter_model_set")
            continue
        if task not in AUXILIARY_TASKS and not isinstance(cfg, dict):
            unvetted.append(f"auxiliary.{safe_label(task)}")
            continue
        entry = cfg if isinstance(cfg, dict) else {}
        host, port, _, _ = _split(entry.get("base_url"))
        provider, model = entry.get("provider"), entry.get("model")
        routes[safe_label(task)] = AuxRoute(
            provider=str(provider) if provider is not None else None,
            host=host,
            port=port,
            model=str(model) if _set(model) else None,
        )
    return routes, unvetted, issues


def managed_config_path(environ: Mapping[str, str] | None = None) -> Path | None:
    """Return the managed-scope ``config.yaml`` Hermes would overlay, or ``None``.

    Mirrors ``get_managed_dir`` at the pin: a non-empty ``HERMES_MANAGED_DIR`` wins
    (and yields nothing when it is not a directory), otherwise ``/etc/hermes``.
    """
    env = os.environ if environ is None else environ
    override = env.get("HERMES_MANAGED_DIR", "").strip()
    directory = Path(override) if override else _DEFAULT_MANAGED_DIR
    path = directory / "config.yaml"
    return path if directory.is_dir() and path.is_file() else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Hermes ``_deep_merge``: dicts recurse, ``None`` over a dict is ignored."""
    result = dict(base)
    for key, value in override.items():
        over_dict = isinstance(result.get(key), dict)
        if over_dict and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif not (over_dict and value is None):
            result[key] = value
    return result


def _load_managed(path: Path) -> dict[str, Any]:
    """Load the overlay as Hermes applies it; a malformed file fails closed here."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("managed hermes config is not a mapping")
    if isinstance(loaded.get("model"), str):  # bare ``model: x`` means model.default
        loaded = {**loaded, "model": {"default": loaded["model"]}}
    return loaded


def read_route_facts(path: Path, managed: Path | None = None) -> RouteFacts:
    """Read routing facts from ``path`` with the ``managed`` overlay deep-merged on top.

    Raises ``OSError``/``ValueError`` when either file is unusable.
    """
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("hermes config is not a mapping")
    if managed is not None:
        loaded = _deep_merge(loaded, _load_managed(managed))
    host, port, base_path, scheme = _split(_get(loaded, "model.base_url"))
    aux, aux_unvetted, aux_issues = _read_auxiliary(loaded.get("auxiliary"))
    surf_unvetted, surf_issues = _scan_surfaces(loaded)
    adopt = _get(loaded, "auth.adopt_external_logins")
    default = _get(loaded, "model.default")
    provider = _get(loaded, "model.provider")
    return RouteFacts(
        model_default=str(default) if default is not None else None,
        provider=str(provider) if provider is not None else None,
        base_host=host,
        base_port=port,
        base_path=base_path,
        base_scheme=scheme,
        api_key=Presence.PRESENT if _get(loaded, "model.api_key") else Presence.ABSENT,
        fallback_providers=_count(loaded.get("fallback_providers")),
        delegation_fallback_providers=_count(
            _get(loaded, "delegation.fallback_providers")
        ),
        auxiliary=aux,
        adopt_external_logins=adopt if isinstance(adopt, bool) else None,
        provider_endpoints=_provider_endpoints(loaded),
        unvetted_keys=[*_scan_top_level(loaded), *aux_unvetted, *surf_unvetted],
        route_issues=[
            *_scan_misc(loaded),
            *_scan_delegation(loaded),
            *_scan_providers(loaded),
            *surf_issues,
            *aux_issues,
            *_scan_values(loaded),
        ],
    )


def _aux_reasons(
    facts: RouteFacts, profile: FinanceRuntimeProfile, gateway: tuple[Any, Any]
) -> list[str]:
    reasons = [
        f"auxiliary_{t}_unset" for t in AUXILIARY_TASKS if t not in facts.auxiliary
    ]
    for task, aux in sorted(facts.auxiliary.items()):
        if aux.provider != "custom":
            reasons.append(f"auxiliary_{task}_provider_not_custom")
        if aux.host is None:
            reasons.append(f"auxiliary_{task}_base_url_unset")
        elif not is_loopback_host(aux.host):
            reasons.append(f"auxiliary_{task}_base_url_not_loopback")
        elif (aux.host, aux.port) != gateway:
            reasons.append(f"auxiliary_{task}_base_url_not_profile_gateway")
        if aux.model is not None and aux.model not in profile.private_alias_allowlist:
            reasons.append(f"auxiliary_{task}_model_not_private_alias")
    return reasons


def evaluate_route(facts: RouteFacts, profile: FinanceRuntimeProfile) -> RouteVerdict:
    """Require an explicit, local-only route; defaults, hosted and unvetted keys block."""
    gw_host, gw_port, _, _ = _split(profile.gateway_base_url)
    reasons: list[str] = []
    if facts.provider != "custom":
        reasons.append("provider_not_custom")  # unset means upstream ``auto``
    if facts.base_host is None:
        reasons.append("base_url_unset")
    elif not is_loopback_host(facts.base_host):
        reasons.append("base_url_not_loopback")
    elif (facts.base_host, facts.base_port) != (gw_host, gw_port):
        reasons.append("base_url_not_profile_gateway")
    if facts.model_default not in profile.private_alias_allowlist:
        reasons.append("model_not_private_alias")
    if facts.fallback_providers:
        reasons.append("fallback_providers_set")
    if facts.delegation_fallback_providers:
        reasons.append("delegation_fallback_providers_set")
    reasons += _aux_reasons(facts, profile, (gw_host, gw_port))
    # A named provider is selectable per request; even on loopback it must be the gateway.
    reasons += [
        f"{label}_not_profile_gateway"
        for label, endpoints in sorted(facts.provider_endpoints.items())
        if any(ep != (gw_host, gw_port) for ep in endpoints)
    ]
    if facts.adopt_external_logins is not False:
        reasons.append("adopt_external_logins_enabled")
    reasons += facts.route_issues
    reasons += [f"unvetted_key:{key}" for key in facts.unvetted_keys]
    reasons = list(dict.fromkeys(reasons))
    return RouteVerdict(blocked=bool(reasons), reasons=reasons)
