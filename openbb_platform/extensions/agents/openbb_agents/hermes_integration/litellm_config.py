"""Metadata-only LiteLLM proxy config reader and alias classifier (#1338-T03).

The reader keeps routing facts only. ``os.environ/NAME`` references become the env
var name plus :class:`Presence`; inline secret values become ``Presence`` and are
never kept. Nothing here imports or runs LiteLLM or contacts the proxy.

Setting names are verified against the litellm 1.106.6 runtime:
``Router.__init__`` (``fallbacks``, ``default_fallbacks``, ``context_window_fallbacks``,
``content_policy_fallbacks``, ``num_retries``), proxy ``load_config``
(``litellm_settings.callbacks|success_callback|failure_callback`` and module
attributes set with ``setattr(litellm, key, value)``, such as
``turn_off_message_logging``) and ``general_settings`` (``master_key``,
``database_url``, ``store_prompts_in_spend_logs``).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .hermes_config import (
    RouteVerdict,
    is_loopback_host,
    safe_label,
    url_has_userinfo,
)
from .models import (
    AliasReport,
    BackendKind,
    GatewayReport,
    Presence,
    SecretRef,
)
from .profile import FinanceRuntimeProfile

FALLBACK_KEYS = (
    "fallbacks",
    "default_fallbacks",
    "context_window_fallbacks",
    "content_policy_fallbacks",
)
CALLBACK_KEYS = (
    "callbacks",
    "success_callback",
    "failure_callback",
    "service_callback",
)
SECRET_KEYS = ("master_key", "database_url")

# Fail-closed allowlists, each name verified against litellm 1.106.6 (``Router``
# arguments, ``litellm`` module attributes, ``general_settings.get`` reads in
# ``litellm/proxy``, ``LiteLLM_Params`` fields). A key outside them blocks the
# private route as ``unvetted_key:<section>.<key>``.
TOP_LEVEL_VETTED = frozenset(
    {"model_list", "litellm_settings", "router_settings", "general_settings", "include"}
)
ROUTER_SETTINGS_VETTED = frozenset(
    {
        *FALLBACK_KEYS,
        "num_retries",
        "routing_strategy",
        "routing_strategy_args",
        "timeout",
        "stream_timeout",
        "retry_after",
        "allowed_fails",
        "cooldown_time",
        "disable_cooldowns",
        "enable_pre_call_checks",
        "max_fallbacks",
        "redis_host",
        "redis_port",
        "redis_password",
        "model_group_alias",  # policed: any value blocks
        "routing_groups",  # policed: any value blocks
    }
)
LITELLM_SETTINGS_VETTED = frozenset(
    {
        *FALLBACK_KEYS,
        *CALLBACK_KEYS,
        "num_retries",
        "turn_off_message_logging",
        "set_verbose",
        "drop_params",
        "modify_params",
        "model_alias_map",  # policed: any value blocks
    }
)
GENERAL_SETTINGS_VETTED = frozenset(
    {
        *SECRET_KEYS,
        "store_prompts_in_spend_logs",
        "allow_client_side_credentials",  # policed: true blocks
        "store_model_in_db",  # policed: true blocks
        "trusted_proxy_ranges",  # client-IP trust for auth, not routing
        "disable_spend_logs",
        "disable_master_key_return",
        "database_connection_timeout",
        "proxy_batch_write_at",
        "background_health_checks",
        "health_check_interval",
    }
)
MODEL_ENTRY_VETTED = frozenset({"model_name", "litellm_params", "model_info"})
LITELLM_PARAMS_VETTED = frozenset(
    {"model", "api_base", "api_key", "rpm", "tpm", "timeout", "stream_timeout"}
)
CLIENTSIDE_PARAMS = "configurable_clientside_auth_params"

# Dotted keys the reader consumes; a seam-contract test pins them against the
# fixtures and, under the O5 interpreter, against litellm 1.106.6 itself.
CONSUMED_KEYS = (
    "model_list[].model_name",
    "model_list[].litellm_params.model",
    "model_list[].litellm_params.api_base",
    "model_list[].litellm_params.api_key",
    *(f"router_settings.{k}" for k in (*FALLBACK_KEYS, "num_retries")),
    *(f"litellm_settings.{k}" for k in (*FALLBACK_KEYS, "num_retries")),
    *(f"litellm_settings.{k}" for k in CALLBACK_KEYS),
    "litellm_settings.turn_off_message_logging",
    "litellm_settings.set_verbose",
    "general_settings.master_key",
    "general_settings.database_url",
    "general_settings.store_prompts_in_spend_logs",
)

# Provider prefixes that speak to a self-hosted OpenAI-compatible or native local
# runtime. Any other prefix (``github_copilot/``, ``anthropic/``...) is hosted.
LOCAL_CAPABLE_PROVIDERS = frozenset(
    {"openai", "hosted_vllm", "ollama", "ollama_chat", "llamafile", "lm_studio"}
)


class Deployment(BaseModel):
    """One ``model_list`` entry; provider and api_base locality only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str | None
    api_host: str | None = None
    api_port: int | None = None
    api_key: SecretRef = SecretRef()
    kind: BackendKind
    reasons: list[str] = Field(default_factory=list)
    clientside_auth_params: bool = False  # callers may override api_base/api_key


class AliasFacts(BaseModel):
    """One model group (``model_name``). Local only if every deployment is local."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: BackendKind
    deployments: list[Deployment]
    reasons: list[str] = Field(default_factory=list)


class GatewayFacts(BaseModel):
    """Routing, logging and secret-presence facts of a proxy config. No values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aliases: list[AliasFacts]
    fallbacks: dict[str, list[tuple[str, list[str]]]] = Field(default_factory=dict)
    num_retries: dict[str, int] = Field(default_factory=dict)
    callbacks: dict[str, int] = Field(default_factory=dict)
    turn_off_message_logging: bool | None = None
    set_verbose: bool | None = None
    store_prompts_in_spend_logs: bool | None = None
    secrets: dict[str, SecretRef] = Field(default_factory=dict)
    # Fail-closed findings: setting names only, never values.
    unvetted_keys: list[str] = Field(default_factory=list)
    config_issues: list[str] = Field(default_factory=list)


def _alias_name(value: Any, limit: int = 64) -> str:
    """Alias name for reports: control characters removed, length capped."""
    text = "".join(c for c in str(value) if ord(c) >= 32 and ord(c) != 127)
    return text[:limit]


def _canonical_name(value: Any) -> bool:
    """A string with no surrounding whitespace and no control characters.

    The report name is normalised, so a non-canonical raw name could be shown as (or
    hide behind) the private alias; it blocks instead of being normalised."""
    return (
        isinstance(value, str)
        and value == value.strip()
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )


def _secret(value: Any) -> SecretRef:
    if value is None or value == "":
        return SecretRef()
    if isinstance(value, str) and value.startswith("os.environ/"):
        return SecretRef(presence=Presence.PRESENT, env_name=value.split("/", 1)[1])
    return SecretRef(presence=Presence.PRESENT, inline=True)


def _url(value: Any) -> tuple[str | None, int | None]:
    if not isinstance(value, str) or not value:
        return None, None
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None and parts.scheme in ("http", "https"):
        port = 443 if parts.scheme == "https" else 80
    return parts.hostname, port


def _local_runtimes(profile: FinanceRuntimeProfile) -> set[tuple[str, int | None]]:
    out = set()
    for url in profile.local_backends:
        host, port = _url(url)
        if host is not None and is_loopback_host(host):
            out.add((_norm_host(host), port))
    return out


def _norm_host(host: str) -> str:
    host = host.strip("[]").lower()
    return "127.0.0.1" if host == "localhost" else host


def _classify(
    entry: dict[str, Any], profile: FinanceRuntimeProfile | None
) -> Deployment:
    raw = entry.get("litellm_params")
    params: dict[str, Any] = raw if isinstance(raw, dict) else {}
    model = params.get("model")
    provider = (
        model.split("/", 1)[0] if isinstance(model, str) and "/" in model else None
    )
    host, port = _url(params.get("api_base"))
    reasons: list[str] = []
    if provider not in LOCAL_CAPABLE_PROVIDERS:
        reasons.append("hosted_provider")
    api_base = params.get("api_base")
    if isinstance(api_base, str) and url_has_userinfo(api_base):
        reasons.append("api_base_userinfo")
    if host is None:
        reasons.append("api_base_unset")
    elif not is_loopback_host(host):
        reasons.append("api_base_not_loopback")
    else:
        gw_host, gw_port = _url(profile.gateway_base_url) if profile else (None, None)
        if gw_host is not None and (_norm_host(host), port) == (
            _norm_host(gw_host),
            gw_port,
        ):
            reasons.append("api_base_is_gateway")
        elif profile is None or (_norm_host(host), port) not in _local_runtimes(
            profile
        ):
            reasons.append("api_base_not_allowlisted_local_runtime")
    # Unknown keys (``base_url``, ``api_version``...) can redirect a request.
    unknown = [k for k in entry if k not in MODEL_ENTRY_VETTED]
    unknown += [
        k for k in params if k not in LITELLM_PARAMS_VETTED and k != CLIENTSIDE_PARAMS
    ]
    if unknown:
        reasons.append("unvetted_params")
    return Deployment(
        provider=provider,
        api_host=host,
        api_port=port,
        api_key=_secret(params.get("api_key")),
        kind=BackendKind.HOSTED if reasons else BackendKind.LOCAL,
        reasons=reasons,
        clientside_auth_params=bool(params.get(CLIENTSIDE_PARAMS)),
    )


def _fallback_pairs(value: Any) -> list[tuple[str, list[str]]]:
    """Normalise ``[{src: [targets]}]`` and ``default_fallbacks: [targets]``."""
    pairs: list[tuple[str, list[str]]] = []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [("*", ["<unparsed>"])] if value else []
    for item in value:
        if isinstance(item, dict):
            for src, targets in item.items():
                tl = targets if isinstance(targets, list) else [targets]
                pairs.append((str(src), [str(t) for t in tl]))
        else:  # default_fallbacks: a bare list of targets applying to every alias
            pairs.append(("*", [str(item)]))
    return pairs


def _model_entries(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Mapping entries of ``model_list``; any other shape is a blocking issue, not a crash."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["model_list_unparsed"]
    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            issues.append(f"model_list_{i}_unparsed")
            continue
        if not isinstance(entry.get("litellm_params"), dict):
            issues.append(f"model_list_{i}_litellm_params_unparsed")
        entries.append(entry)
    return entries, issues


def read_gateway_facts(
    path: Path, profile: FinanceRuntimeProfile | None = None
) -> GatewayFacts:
    """Read and classify ``path``; raises ``OSError``/``ValueError`` when unusable."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("litellm config is not a mapping")
    entries, shape_issues = _model_entries(loaded.get("model_list"))
    groups: dict[str, list[Deployment]] = {}
    for entry in entries:
        raw_name = entry.get("model_name")
        if not _canonical_name(raw_name):
            shape_issues.append("alias_name_not_canonical")
        name = _alias_name(raw_name)
        groups.setdefault(name, []).append(_classify(entry, profile))
    aliases = []
    for name, deps in groups.items():
        reasons = sorted({r for d in deps for r in d.reasons})
        if len(deps) > 1 and len({d.kind for d in deps}) > 1:
            reasons.append("mixed_deployments")
        hosted = any(d.kind is BackendKind.HOSTED for d in deps)
        aliases.append(
            AliasFacts(
                name=name,
                kind=BackendKind.HOSTED if hosted else BackendKind.LOCAL,
                deployments=deps,
                reasons=reasons,
            )
        )
    fallbacks: dict[str, list[tuple[str, list[str]]]] = {}
    retries: dict[str, int] = {}
    callbacks: dict[str, int] = {}
    for section in ("router_settings", "litellm_settings"):
        block = loaded.get(section)
        block = block if isinstance(block, dict) else {}
        for key in FALLBACK_KEYS:
            pairs = _fallback_pairs(block.get(key))
            if pairs:
                fallbacks[f"{section}.{key}"] = pairs
        if isinstance(block.get("num_retries"), int):
            retries[section] = block["num_retries"]
    lset = loaded.get("litellm_settings")
    lset = lset if isinstance(lset, dict) else {}
    for key in CALLBACK_KEYS:
        value = lset.get(key)
        count = len(value) if isinstance(value, list) else (1 if value else 0)
        if count:
            callbacks[key] = count
    gen = loaded.get("general_settings")
    gen = gen if isinstance(gen, dict) else {}
    tml = lset.get("turn_off_message_logging")
    return GatewayFacts(
        aliases=aliases,
        fallbacks=fallbacks,
        num_retries=retries,
        callbacks=callbacks,
        turn_off_message_logging=tml if isinstance(tml, bool) else None,
        set_verbose=_toggle_on(lset, "set_verbose"),
        store_prompts_in_spend_logs=_toggle_on(gen, "store_prompts_in_spend_logs"),
        secrets={k: _secret(gen.get(k)) for k in SECRET_KEYS},
        unvetted_keys=_unvetted(loaded),
        config_issues=[*dict.fromkeys(shape_issues), *_config_issues(loaded)],
    )


def _toggle_on(block: dict[str, Any], key: str) -> bool | None:
    """``None`` if absent, ``False`` only for YAML ``false``; anything else counts as on.

    litellm 1.106.6 reads these leniently: ``store_prompts_in_spend_logs`` accepts the
    string ``"true"`` in any case and module settings such as ``set_verbose`` are set with
    ``setattr(litellm, key, value)``, so any truthy value enables them."""
    if key not in block:
        return None
    return block[key] is not False


def _section(loaded: dict[str, Any], name: str) -> dict[str, Any]:
    block = loaded.get(name)
    return block if isinstance(block, dict) else {}


def _unvetted(loaded: dict[str, Any]) -> list[str]:
    """Names of settings outside the allowlists, as ``section.key``."""
    out = [safe_label(k) for k in loaded if str(k) not in TOP_LEVEL_VETTED]
    for name, vetted in (
        ("router_settings", ROUTER_SETTINGS_VETTED),
        ("litellm_settings", LITELLM_SETTINGS_VETTED),
        ("general_settings", GENERAL_SETTINGS_VETTED),
    ):
        if loaded.get(name) is not None and not isinstance(loaded.get(name), dict):
            out.append(name)
        out += [
            f"{name}.{safe_label(k)}"
            for k in _section(loaded, name)
            if str(k) not in vetted
        ]
    return out


def _config_issues(loaded: dict[str, Any]) -> list[str]:
    """List settings that re-route or widen who can route, whatever the aliases."""
    router = _section(loaded, "router_settings")
    lset = _section(loaded, "litellm_settings")
    gen = _section(loaded, "general_settings")
    checks = (
        (router.get("model_group_alias"), "model_group_alias_set"),
        (router.get("routing_groups"), "routing_groups_set"),
        (lset.get("model_alias_map"), "model_alias_map_set"),
        (loaded.get("include"), "include_set"),
        (
            gen.get("allow_client_side_credentials") is True,
            "client_side_credentials_allowed",
        ),
        (_toggle_on(gen, "store_model_in_db"), "models_stored_in_db"),
    )
    return [reason for value, reason in checks if value]


def evaluate_gateway(
    facts: GatewayFacts, profile: FinanceRuntimeProfile
) -> RouteVerdict:
    """Private route admitted only if every allowlisted alias is local and isolated."""
    by_name = {a.name: a for a in facts.aliases}
    local = {a.name for a in facts.aliases if a.kind is BackendKind.LOCAL}
    private = list(profile.private_alias_allowlist)
    reasons: list[str] = []
    if not private:
        reasons.append("no_private_alias_allowlisted")
    if not local:
        reasons.append("no_local_alias")
    for name in private:
        alias = by_name.get(name)
        if alias is None:
            reasons.append(f"alias_{name}_missing")
        elif alias.kind is not BackendKind.LOCAL:
            reasons.append(f"alias_{name}_hosted")
            if any(d.kind is BackendKind.LOCAL for d in alias.deployments):
                reasons.append(f"alias_{name}_group_has_hosted_deployment")
        if alias is not None and any(
            d.clientside_auth_params for d in alias.deployments
        ):
            reasons.append(f"alias_{name}_clientside_auth_params")
        # A wildcard route that is hosted can capture a private alias name.
        for other in facts.aliases:
            if (
                other.name != name
                and any(c in other.name for c in "*?[")
                and fnmatch.fnmatchcase(name, other.name)
                and other.kind is BackendKind.HOSTED
            ):
                reasons.append(f"alias_{name}_captured_by_hosted_wildcard")
    for key, pairs in sorted(facts.fallbacks.items()):
        for src, targets in pairs:
            # litellm also looks up ``<provider>/<group>`` keys for a group named
            # without a slash (``_provider_prefixed_model_group``), so match on the
            # last path segment too (a superset, so it fails closed).
            bare = src.rsplit("/", 1)[-1]
            applies = src == "*" or src in private or bare in private or not private
            if applies and any(t not in local for t in targets):
                reasons.append(f"unsafe_fallback:{key}")
                break
    for key in sorted(facts.callbacks):
        reasons.append(f"callbacks_set:{key}")
    if facts.turn_off_message_logging is not True:
        reasons.append("message_logging_not_disabled")
    # DEBUG logs carry prompts even with turn_off_message_logging (1.106.6).
    if facts.set_verbose:
        reasons.append("verbose_logging_enabled")
    if facts.store_prompts_in_spend_logs is True:
        reasons.append("prompts_stored_in_spend_logs")
    reasons += facts.config_issues
    reasons += [f"unvetted_key:{key}" for key in facts.unvetted_keys]
    reasons = list(dict.fromkeys(reasons))
    return RouteVerdict(blocked=bool(reasons), reasons=reasons)


def gateway_report(facts: GatewayFacts, verdict: RouteVerdict) -> GatewayReport:
    """Compact report: per-alias kind, counts, verdict and secret presence."""
    aliases = [
        AliasReport(
            name=a.name,
            kind=a.kind,
            providers=[d.provider for d in a.deployments],
            reasons=a.reasons,
        )
        for a in facts.aliases
    ]
    local = sum(a.kind is BackendKind.LOCAL for a in aliases)
    return GatewayReport(
        aliases=aliases,
        local=local,
        hosted=len(aliases) - local,
        private_route="BLOCKED" if verdict.blocked else "ADMITTED",
        reasons=verdict.reasons,
        secrets=facts.secrets,
    )
