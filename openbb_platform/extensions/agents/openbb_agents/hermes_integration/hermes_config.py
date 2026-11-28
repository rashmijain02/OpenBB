"""Metadata-only Hermes ``config.yaml`` reader and route policy (#1338-T02).

The reader keeps routing facts only. Secret-shaped keys become :class:`Presence`
and URL credentials are dropped. Nothing here imports or runs Hermes.
"""

from __future__ import annotations

import ipaddress
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

_LOOPBACK_NAMES = {"localhost"}


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
    auxiliary: dict[str, str | None] = Field(default_factory=dict)
    auxiliary_hosts: dict[str, str | None] = Field(default_factory=dict)
    adopt_external_logins: bool | None = None


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


def read_route_facts(path: Path) -> RouteFacts:
    """Read routing facts from ``path``; raises ``OSError``/``ValueError`` when unusable."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("hermes config is not a mapping")
    host, port, base_path, scheme = _split(_get(loaded, "model.base_url"))
    aux_raw = loaded.get("auxiliary")
    aux: dict[str, str | None] = {}
    aux_hosts: dict[str, str | None] = {}
    if isinstance(aux_raw, dict):
        for task, cfg in aux_raw.items():
            entry = cfg if isinstance(cfg, dict) else {}
            provider = entry.get("provider")
            aux[str(task)] = str(provider) if provider is not None else None
            aux_hosts[str(task)] = _split(entry.get("base_url"))[0]
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
        auxiliary_hosts=aux_hosts,
        adopt_external_logins=adopt if isinstance(adopt, bool) else None,
    )


def evaluate_route(facts: RouteFacts, profile: FinanceRuntimeProfile) -> RouteVerdict:
    """Require an explicit, local-only route; defaults and hosted vectors block."""
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
    for task, provider in sorted(facts.auxiliary.items()):
        if provider != "custom":
            reasons.append(f"auxiliary_{task}_provider_not_custom")
        host = facts.auxiliary_hosts.get(task)
        if host is not None and not is_loopback_host(host):
            reasons.append(f"auxiliary_{task}_base_url_not_loopback")
    if facts.adopt_external_logins is not False:
        reasons.append("adopt_external_logins_enabled")
    return RouteVerdict(blocked=bool(reasons), reasons=reasons)
