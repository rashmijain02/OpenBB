"""Metadata-only Hermes ``config.yaml`` readers and route policy (#1338, #1339).

The readers keep routing and skill-source facts only. Secret-shaped keys become :class:`Presence`
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
    "memory.memory_enabled",
    "memory.user_profile_enabled",
)
# Built-in memory and the user profile persist conversation content in the Hermes
# home and inject it into later prompts; upstream defaults both to on (truthy read).
MEMORY_SWITCHES = ("memory_enabled", "user_profile_enabled")

# Fail-closed allowlists derived from Hermes ``DEFAULT_CONFIG`` at the pin
# (rashmijain02/hermes-agent 710fa8a, ``hermes_cli/config_defaults.py``). A
# top-level key outside both sets blocks the route as ``unvetted_key:<key>``.
#
# Top-level keys with no influence on which model, provider or host gets a request.
HARMLESS_TOP_LEVEL = frozenset(
    {
        "_config_version",
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
# ``agent``, ``skills`` and ``curator`` carry the skill-writer switches the skill
# reader consumes (#1339-T02); they are vetted by shape here.
POLICED_TOP_LEVEL = frozenset(
    {
        "agent",
        "auth",
        "auxiliary",
        "curator",
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
        "skills",
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

# Dotted keys the skill reader consumes (#1339-T02). The pinned example file omits
# them, so the fixture takes their defaults from ``hermes_cli/config_defaults.py``.
SKILL_CONSUMED_KEYS = (
    "skills.create_dir",
    "skills.external_dirs",
    "skills.project_discovery",
    "skills.inline_shell",
    "curator.enabled",
    "auxiliary.background_review.enabled",
    "agent.disabled_toolsets",
)

_LOOPBACK_NAMES = {"localhost"}
# Managed-scope directory default at the pin (``hermes_cli/managed_scope.py``).
_DEFAULT_MANAGED_DIR = Path("/etc/hermes")
# Root keys Hermes moves under ``model`` (``_normalize_root_model_keys``). They stay
# unvetted here as well, so a config using them still blocks (fail closed).
_ROOT_MODEL_KEYS = ("provider", "base_url", "context_length", "api_base")
_MERGE_TAG = "tag:yaml.org,2002:merge"
_ORDERED_MAP_TAGS = frozenset({"tag:yaml.org,2002:omap", "tag:yaml.org,2002:pairs"})
_YAML_VERSIONS = frozenset({(1, 1), (1, 2)})


class HermesConfigError(ValueError):
    """A Hermes config this reader refuses; ``reason`` is the report code."""

    reason = "config_unreadable"


class ConfigDuplicateKeyError(HermesConfigError):
    """Duplicate mapping key: ruamel raises, so Hermes would load a fallback config."""

    reason = "config_duplicate_key"


class ConfigOrderedMapTagError(HermesConfigError):
    """``!!omap``/``!!pairs``: ruamel's safe loader asserts, so Hermes falls back."""

    reason = "config_ordered_map_tag"


class ConfigYamlVersionError(HermesConfigError):
    """``%YAML`` other than 1.1/1.2: ruamel refuses it, so Hermes falls back."""

    reason = "config_yaml_version_unsupported"


class ManagedDirRelativeError(HermesConfigError):
    """``HERMES_MANAGED_DIR`` is relative to the Hermes process cwd, not ours."""

    reason = "managed_dir_relative"


class _HermesLoader(yaml.SafeLoader):  # pylint: disable=too-many-ancestors
    """PyYAML ``SafeLoader`` with the ruamel YAML 1.1 reading Hermes uses.

    Hermes loads configs with ``hermes_yaml.safe_load`` at the pin: ruamel
    ``typ="safe"`` with ``version=(1, 1)``, which also resolves bare ``y``/``n`` as
    booleans and raises on duplicate keys (see :func:`load_hermes_yaml`).
    """

    bool_values = {**yaml.SafeLoader.bool_values, "y": True, "n": False}


_HermesLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:y|Y|n|N)$"), list("yYnN")
)


def _reject_duplicate_keys(loader: _HermesLoader, root: yaml.Node) -> None:
    """Raise on a key repeated in one mapping, ``<<`` included, as ruamel does.

    Runs on the composed node graph before merge keys are flattened, so an explicit
    key overriding a merged one is not reported. Keys compare by constructed value
    (``1`` and ``0x1`` collide), as in ruamel.
    """
    seen_nodes: set[int] = set()
    stack: list[yaml.Node] = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        if isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
        elif isinstance(node, yaml.MappingNode):
            keys: set[Any] = set()
            for key_node, value_node in node.value:
                stack.extend((key_node, value_node))
                if key_node.tag == _MERGE_TAG:
                    key: Any = ("<<",)
                elif isinstance(key_node, yaml.ScalarNode):
                    key = loader.construct_object(key_node, deep=True)
                else:
                    continue  # complex keys: the constructor rejects unhashable ones
                if key in keys:
                    raise ConfigDuplicateKeyError("duplicate key in hermes config")
                keys.add(key)


def _reject_ruamel_refusals(loader: _HermesLoader, root: yaml.Node) -> None:
    """Raise on inputs ruamel rejects with ``AssertionError`` (Hermes then falls back)."""
    version = getattr(loader, "yaml_version", None)
    if version is not None and tuple(version) not in _YAML_VERSIONS:
        raise ConfigYamlVersionError("unsupported %YAML version in hermes config")
    seen_nodes: set[int] = set()
    stack: list[yaml.Node] = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        if node.tag in _ORDERED_MAP_TAGS:
            raise ConfigOrderedMapTagError("ordered map tag in hermes config")
        if isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
        elif isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                stack.extend((key_node, value_node))


def load_hermes_yaml(text: str) -> Any:
    """Parse a Hermes config with Hermes' YAML semantics, or fail closed.

    Mirrors ``hermes_yaml.safe_load`` (rashmijain02/hermes-agent 710fa8a): YAML 1.1
    booleans including ``y``/``Y``/``n``/``N``, and duplicate keys rejected. A ruamel
    load failure makes Hermes fall back to a backup or ``DEFAULT_CONFIG`` (provider
    ``auto``), so a duplicate raises :class:`ConfigDuplicateKeyError` here, as do
    ``!!omap``/``!!pairs`` and a ``%YAML`` version other than 1.1/1.2. Residual: other
    ruamel-only rejections are not modelled; PyYAML errors still fail closed.
    """
    loader = _HermesLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return None
        _reject_ruamel_refusals(loader, node)
        _reject_duplicate_keys(loader, node)
        return loader.construct_document(node)
    finally:
        loader.dispose()


def _normalize_root_model_keys(config: dict[str, Any]) -> dict[str, Any]:
    """Port of Hermes ``_normalize_root_model_keys``.

    Source: ``hermes_cli/config.py`` lines 1722-1818 at 710fa8a, with
    ``coerce_provider_id`` from ``hermes_cli/config_providers.py`` lines 66-70.
    Hermes applies it to the user config (``_canonicalize_config`` in
    ``_load_config_impl``, line 2399) and to the managed config before merging
    (``_merge_managed_overlay``, line 2293).
    """
    model_in = config.get("model")
    model_provider = model_in.get("provider") if isinstance(model_in, dict) else None
    needs_model_work = (
        model_provider is not None and not isinstance(model_provider, str)
    ) or (
        isinstance(model_in, dict)
        and bool(
            model_in.get("api_base")
            or model_in.get("model")
            or model_in.get("name")
            or any(
                isinstance(model_in.get(k), dict) for k in ("default", "model", "name")
            )
        )
    )
    has_root = any(config.get(k) for k in _ROOT_MODEL_KEYS)
    if not has_root and not needs_model_work:
        return config
    config = dict(config)
    raw = config.get("model")
    model: dict[str, Any] = (
        dict(raw) if isinstance(raw, dict) else {"default": raw} if raw else {}
    )
    config["model"] = model
    for key in ("default", "model", "name"):
        val = model.get(key)
        if isinstance(val, dict):
            nested_model = val.get("model") or val.get("default")
            nested_provider = str(val.get("provider") or "").strip()
            model[key] = str(nested_model or "").strip()
            if nested_provider:
                outer = str(model.get("provider") or "").strip()
                if not outer or outer == "auto":
                    model["provider"] = nested_provider
    for key in ("provider", "base_url", "context_length"):
        root_val = config.get(key)
        if root_val and not model.get(key):
            model[key] = root_val
        config.pop(key, None)
    if model.get("provider") is not None:
        model["provider"] = str(model["provider"]).strip()
    for alias_val in (config.get("api_base"), model.get("api_base")):
        if alias_val and not model.get("base_url"):
            model["base_url"] = alias_val
    config.pop("api_base", None)
    model.pop("api_base", None)
    alias = model.get("model") or model.get("name")
    if not model.get("default") and alias:
        model["default"] = alias
    if model.get("default"):
        model.pop("model", None)
        model.pop("name", None)
    return config


def _load_mapping(path: Path, what: str) -> dict[str, Any]:
    """Load ``path`` as Hermes does (``utf-8-sig``); an empty file is ``{}``."""
    loaded = load_hermes_yaml(Path(path).read_text(encoding="utf-8-sig"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{what} is not a mapping")
    return loaded


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


# Shape checks for the skill-writer keys (#1339-T02). The skills component judges
# the values; the route policy only refuses shapes the skill reader would ignore.
_SKILL_BOOL_KEYS = (
    "skills.project_discovery",
    "skills.inline_shell",
    "curator.enabled",
    "auxiliary.background_review.enabled",
)
_SKILL_LIST_KEYS = ("skills.external_dirs", "agent.disabled_toolsets")


def _scan_skill_keys(loaded: dict[str, Any]) -> list[str]:
    issues = [
        f"{section}_unparsed"
        for section in ("agent", "skills", "curator")
        if section in loaded and not isinstance(loaded[section], dict)
    ]
    for key in _SKILL_BOOL_KEYS:
        value = _get(loaded, key)
        if value is not None and not isinstance(value, bool):
            issues.append(f"{key.replace('.', '_')}_not_bool")
    for key in _SKILL_LIST_KEYS:
        value = _get(loaded, key)
        if value is not None and not isinstance(value, (str, list)):
            issues.append(f"{key.replace('.', '_')}_not_list")
    create_dir = _get(loaded, "skills.create_dir")
    if create_dir is not None and not isinstance(create_dir, str):
        issues.append("skills_create_dir_not_str")
    return issues


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
    # Memory switches default on at the pin: only an explicit ``false`` turns them off.
    issues += [
        f"{switch}_not_false"
        for switch in MEMORY_SWITCHES
        if _get(loaded, f"memory.{switch}") is not False
    ]
    # Absent flags keep the pinned default (``False``); any other value counts as on.
    telemetry = loaded.get("telemetry")
    metrics = telemetry.get("shared_metrics") if isinstance(telemetry, dict) else None
    if (telemetry is not None and not isinstance(telemetry, dict)) or (
        metrics is not None and not isinstance(metrics, dict)
    ):
        issues.append("telemetry_unparsed")
    elif isinstance(metrics, dict) and any(
        k in metrics and metrics[k] is not False for k in ("enabled", "send")
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
        if task not in AUXILIARY_TASKS:
            # Exact names only: ``Vision`` / ``vision `` are not the pinned ``vision``
            # task, so Hermes would not read them as its route; never normalised.
            issues.append(f"auxiliary_unknown_task:{safe_label(task)}")
            if not isinstance(cfg, dict):
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
    (and yields nothing when it is not a directory), otherwise ``/etc/hermes``. A
    relative override resolves against the Hermes process cwd, which this check
    cannot know, so it raises :class:`ManagedDirRelativeError`.
    """
    env = os.environ if environ is None else environ
    override = env.get("HERMES_MANAGED_DIR", "").strip()
    if override and not Path(override).is_absolute():
        raise ManagedDirRelativeError("HERMES_MANAGED_DIR is relative")
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


def _managed_overlay(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the overlay as ``_merge_managed_overlay`` applies it at the pin."""
    loaded = _normalize_root_model_keys(raw)
    if isinstance(loaded.get("model"), str):  # bare ``model: x`` means model.default
        loaded = {**loaded, "model": {"default": loaded["model"]}}
    return loaded


def _load_config(path: Path, managed: Path | None) -> tuple[dict[str, Any], list[str]]:
    """Load ``path`` with the ``managed`` overlay deep-merged on top, as Hermes does.

    The one loader for route and skill facts: Hermes YAML semantics
    (:func:`load_hermes_yaml`), each file normalised as ``_load_config_impl`` does
    before the merge. Returns the merged mapping and the root model keys seen in
    either file. Raises ``OSError``/``ValueError`` (:class:`HermesConfigError` for
    refused shapes) when either file is unusable.
    """
    user = load_hermes_yaml(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(user, dict):
        raise ValueError("hermes config is not a mapping")
    raw_roots = [k for k in _ROOT_MODEL_KEYS if k in user]
    loaded = _normalize_root_model_keys(user)
    if managed is not None:
        raw = _load_mapping(managed, "managed hermes config")
        raw_roots += [k for k in _ROOT_MODEL_KEYS if k in raw]
        loaded = _deep_merge(loaded, _managed_overlay(raw))
    return loaded, raw_roots


def read_route_facts(path: Path, managed: Path | None = None) -> RouteFacts:
    """Read routing facts from ``path`` with the ``managed`` overlay deep-merged on top.

    Raises ``OSError``/``ValueError`` (:class:`HermesConfigError` for refused shapes)
    when either file is unusable.
    """
    loaded, raw_roots = _load_config(path, managed)
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
        unvetted_keys=[
            *dict.fromkeys(raw_roots),
            *_scan_top_level(loaded),
            *aux_unvetted,
            *surf_unvetted,
        ],
        route_issues=[
            *_scan_misc(loaded),
            *_scan_skill_keys(loaded),
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


class SkillFacts(BaseModel):
    """Skill-source and skill-writer facts from a Hermes config.

    ``None`` means the key is unset or not a boolean, so the upstream default
    applies. Directory strings are kept for path checks and never reported.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    create_dir: str | None = None
    external_dirs: list[str] = Field(default_factory=list)
    project_discovery: bool | None = None
    inline_shell: bool | None = None
    curator_enabled: bool | None = None
    background_review_enabled: bool | None = None
    disabled_toolsets: list[str] = Field(default_factory=list)


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _str_list(value: Any) -> list[str]:
    """Scalar-or-list config value as stripped strings (upstream ``parse_config_string_list``)."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError:
                parsed = None
            value = parsed if isinstance(parsed, list) else [text]
        else:
            value = [text]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def read_skill_facts(path: Path, managed: Path | None = None) -> SkillFacts:
    """Read skill facts from ``path`` with the ``managed`` overlay merged on top.

    Raises ``OSError``/``ValueError`` when either file is unusable.
    """
    loaded, _ = _load_config(path, managed)
    create_dir = _get(loaded, "skills.create_dir")
    create_dir = str(create_dir).strip() if isinstance(create_dir, str) else ""
    return SkillFacts(
        create_dir=create_dir or None,
        external_dirs=_str_list(_get(loaded, "skills.external_dirs")),
        project_discovery=_bool_or_none(_get(loaded, "skills.project_discovery")),
        inline_shell=_bool_or_none(_get(loaded, "skills.inline_shell")),
        curator_enabled=_bool_or_none(_get(loaded, "curator.enabled")),
        background_review_enabled=_bool_or_none(
            _get(loaded, "auxiliary.background_review.enabled")
        ),
        disabled_toolsets=_str_list(_get(loaded, "agent.disabled_toolsets")),
    )


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
