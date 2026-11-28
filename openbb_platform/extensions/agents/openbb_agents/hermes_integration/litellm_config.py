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

from .hermes_config import RouteVerdict, is_loopback_host
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
    params: dict[str, Any], profile: FinanceRuntimeProfile | None
) -> Deployment:
    model = params.get("model")
    provider = (
        model.split("/", 1)[0] if isinstance(model, str) and "/" in model else None
    )
    host, port = _url(params.get("api_base"))
    reasons: list[str] = []
    if provider not in LOCAL_CAPABLE_PROVIDERS:
        reasons.append("hosted_provider")
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
    return Deployment(
        provider=provider,
        api_host=host,
        api_port=port,
        api_key=_secret(params.get("api_key")),
        kind=BackendKind.HOSTED if reasons else BackendKind.LOCAL,
        reasons=reasons,
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


def read_gateway_facts(
    path: Path, profile: FinanceRuntimeProfile | None = None
) -> GatewayFacts:
    """Read and classify ``path``; raises ``OSError``/``ValueError`` when unusable."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("litellm config is not a mapping")
    groups: dict[str, list[Deployment]] = {}
    for entry in loaded.get("model_list") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("model_name"))
        params = entry.get("litellm_params")
        params = params if isinstance(params, dict) else {}
        groups.setdefault(name, []).append(_classify(params, profile))
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
    sp = gen.get("store_prompts_in_spend_logs")
    return GatewayFacts(
        aliases=aliases,
        fallbacks=fallbacks,
        num_retries=retries,
        callbacks=callbacks,
        turn_off_message_logging=tml if isinstance(tml, bool) else None,
        set_verbose=lset.get("set_verbose") is True,
        store_prompts_in_spend_logs=sp if isinstance(sp, bool) else None,
        secrets={k: _secret(gen.get(k)) for k in SECRET_KEYS},
    )


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
            applies = src == "*" or src in private or not private
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
