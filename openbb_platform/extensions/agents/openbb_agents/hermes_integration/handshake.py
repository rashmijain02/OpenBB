"""Loopback-only handshake matrix with explicit unavailable outcomes (#1338-T02).

Edges: WebUI to Hermes, Hermes to LiteLLM gateway, gateway to local backend,
Hermes to OpenBB MCP and OpenBB to MySQL. The engine never starts, installs or
reroutes anything: a stopped service is reported as unavailable with the failed
layer, and a blocked route is never probed.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .hermes_config import RouteFacts, evaluate_route, is_loopback_host
from .litellm_config import GatewayFacts, select_private_aliases
from .models import EdgeReport, EdgeStatus, FailedLayer, HealthLevel, Presence
from .profile import FinanceRuntimeProfile
from .provenance import load_credentials

logger = logging.getLogger(__name__)

_MAX_BODY = 1_000_000
_LAYER_ORDER = list(FailedLayer)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one probe: ``ok`` (a reply arrived), ``refused``, ``timeout`` or ``error``."""

    kind: str
    status: int | None = None
    body: bytes = b""


class Transport(Protocol):
    """Injectable network seam. Implementations must stay on loopback."""

    def http_get(
        self,
        host: str,
        port: int,
        path: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ProbeResult:
        """GET ``path`` on a loopback server."""

    def tcp_connect(self, host: str, port: int, timeout: float) -> ProbeResult:
        """Open and close a TCP connection to a loopback port."""


def _require_loopback(host: str) -> None:
    if not is_loopback_host(host):
        raise ValueError("non-loopback probe refused")


def _classify(exc: BaseException) -> ProbeResult:
    if isinstance(exc, ConnectionRefusedError):
        return ProbeResult("refused")
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ProbeResult("timeout")
    return ProbeResult("error")


class LoopbackTransport:
    """Real transport. Refuses any non-loopback host before connecting."""

    def http_get(
        self,
        host: str,
        port: int,
        path: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ProbeResult:
        """GET ``path``; returns a classified result instead of raising."""
        _require_loopback(host)
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path, headers=dict(headers))
            resp = conn.getresponse()
            return ProbeResult("ok", resp.status, resp.read(_MAX_BODY))
        except OSError as exc:
            return _classify(exc)
        except http.client.HTTPException:
            return ProbeResult("error")
        finally:
            conn.close()

    def tcp_connect(self, host: str, port: int, timeout: float) -> ProbeResult:
        """TCP connect and close; returns a classified result instead of raising."""
        _require_loopback(host)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return ProbeResult("ok")
        except OSError as exc:
            return _classify(exc)


def _unavailable(
    name: str, result: ProbeResult, layer: FailedLayer, what: str
) -> EdgeReport:
    if result.kind == "timeout":
        logger.warning(
            "probe timeout on edge %s (%s); reported unavailable", name, what
        )
    return EdgeReport(
        name=name,
        status=EdgeStatus.UNAVAILABLE,
        failed_layer=layer,
        detail=f"{what}_{result.kind}",
    )


def _not_evaluated(name: str, detail: str) -> EdgeReport:
    return EdgeReport(name=name, status=EdgeStatus.NOT_EVALUATED, detail=detail)


def _blocked(name: str, layer: FailedLayer, detail: str, **kw: Any) -> EdgeReport:
    return EdgeReport(
        name=name, status=EdgeStatus.BLOCKED, failed_layer=layer, detail=detail, **kw
    )


def _models_path(base_path: str) -> str:
    base = base_path.rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _alias_ids(body: bytes) -> set[str]:
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
        return {str(m["id"]) for m in data.get("data", []) if "id" in m}
    except (ValueError, AttributeError, TypeError, KeyError, RecursionError):
        return set()


def probe_gateway(
    profile: FinanceRuntimeProfile,
    facts: RouteFacts | None,
    env: Mapping[str, str],
    transport: Transport,
    timeout: float,
    *,
    gateway_facts: GatewayFacts | None = None,
) -> EdgeReport:
    """Hermes to LiteLLM: one probe of the profile gateway, only if the route is admitted.

    With the proxy config (``gateway_facts``), the served default alias must also be
    one the local-only selector admits.
    """
    name = "hermes_litellm"
    if facts is None:
        return _not_evaluated(name, "no_hermes_config")
    verdict = evaluate_route(facts, profile)
    if verdict.blocked:
        return _blocked(
            name, FailedLayer.ROUTE, "route_blocked: " + ",".join(verdict.reasons)
        )
    parts = urlsplit(profile.gateway_base_url)
    host, port = parts.hostname or "", parts.port or 80
    key_env = profile.gateway_key_env
    key = env.get(key_env) if key_env else None
    presence = {"gateway_key": Presence.PRESENT if key else Presence.ABSENT}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    result = transport.http_get(host, port, _models_path(parts.path), headers, timeout)
    if result.kind != "ok":
        edge = _unavailable(name, result, FailedLayer.BACKEND, "gateway")
        return edge.model_copy(update={"presence": presence})
    status = result.status or 0
    if status in (401, 403):
        return EdgeReport(
            name=name,
            status=EdgeStatus.BLOCKED,
            level=HealthLevel.CONFIGURED,
            failed_layer=FailedLayer.AUTH,
            detail=f"gateway_rejected_credentials: http {status}",
            presence=presence,
        )
    if status != 200:
        return EdgeReport(
            name=name,
            status=EdgeStatus.UNAVAILABLE,
            failed_layer=FailedLayer.BACKEND,
            detail=f"gateway_http_{status}",
            presence=presence,
        )
    served = _alias_ids(result.body)
    if facts.model_default not in served:
        return EdgeReport(
            name=name,
            status=EdgeStatus.BLOCKED,
            level=HealthLevel.AUTHENTICATED,
            failed_layer=FailedLayer.ROUTE,
            detail="private_alias_not_served",
            presence=presence,
        )
    # litellm 1.106.6 lists a scoped key's own models only (key models, then team
    # models, then the full proxy list); anything beyond the allowlist means the
    # key can also reach hosted aliases, so a caller-supplied fallback could too.
    if served - set(profile.private_alias_allowlist):
        return EdgeReport(
            name=name,
            status=EdgeStatus.BLOCKED,
            level=HealthLevel.AUTHENTICATED,
            failed_layer=FailedLayer.AUTH,
            detail="gateway_key_not_scoped",
            presence=presence,
        )
    if gateway_facts is not None and facts.model_default not in select_private_aliases(
        gateway_facts, profile, served
    ):
        return EdgeReport(
            name=name,
            status=EdgeStatus.BLOCKED,
            level=HealthLevel.AUTHENTICATED,
            failed_layer=FailedLayer.ROUTE,
            detail="private_alias_not_local_only",
            presence=presence,
        )
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.CALLABLE,
        detail="private_alias_served",
        presence=presence,
    )


def probe_backend(
    gateway: EdgeReport,
    backend_base_url: str | None,
    transport: Transport,
    timeout: float,
) -> EdgeReport:
    """Gateway to local backend. Never probed unless the gateway edge is callable."""
    name = "litellm_backend"
    if gateway.status is EdgeStatus.UNAVAILABLE:
        return EdgeReport(
            name=name,
            status=EdgeStatus.UNAVAILABLE,
            failed_layer=FailedLayer.BACKEND,
            detail="upstream_unavailable: hermes_litellm",
        )
    if not gateway.callable:
        return _not_evaluated(name, "gateway_not_callable")
    if not backend_base_url:
        return _not_evaluated(name, "no_backend_url (see litellm config, T03)")
    parts = urlsplit(backend_base_url)
    host = parts.hostname or ""
    if not is_loopback_host(host):
        return _blocked(name, FailedLayer.ROUTE, "backend_not_loopback")
    result = transport.http_get(host, parts.port or 80, parts.path or "/", {}, timeout)
    if result.kind != "ok" or (result.status or 500) >= 500:
        return _unavailable(
            name,
            result if result.kind != "ok" else ProbeResult("http_5xx"),
            FailedLayer.BACKEND,
            "backend",
        )
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.CALLABLE,
        detail="backend_replied",
    )


def catalog_sha256(tools: Sequence[Mapping[str, Any]]) -> str:
    """Order-insensitive hash of the MCP tool catalog (name, description, inputSchema)."""
    canon = sorted(
        (
            {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ),
        key=lambda t: str(t["name"]),
    )
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def check_mcp_catalog(
    tools: Sequence[Mapping[str, Any]], expected_sha256: str | None
) -> EdgeReport:
    """Admission of the stdio MCP tool catalog by pinned hash; drift blocks the schema layer."""
    name = "hermes_mcp_stdio"
    if not expected_sha256:
        return _blocked(name, FailedLayer.SCHEMA, "no_pinned_hash")
    observed = catalog_sha256(tools)
    if observed != expected_sha256:
        return _blocked(
            name, FailedLayer.SCHEMA, f"schema_hash_drift: observed {observed[:12]}"
        )
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.ADMITTED,
        detail="catalog_hash_pinned",
    )


def probe_mcp_http(url: str, transport: Transport, timeout: float) -> EdgeReport:
    """Hermes to ``openbb_mcp_server`` HTTP: reachability on loopback only."""
    name = "hermes_mcp_http"
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not is_loopback_host(host):
        return _blocked(name, FailedLayer.ROUTE, "mcp_url_not_loopback")
    result = transport.http_get(host, parts.port or 80, parts.path or "/", {}, timeout)
    if result.kind != "ok":
        return _unavailable(name, result, FailedLayer.BACKEND, "mcp")
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.CONFIGURED,
        detail="mcp_listening",
    )


def _same_or_under(child: str, parent: str) -> bool:
    c = os.path.normcase(os.path.realpath(child))
    p = os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p + os.sep)


def check_webui(
    profile: FinanceRuntimeProfile,
    env: Mapping[str, str],
    transport: Transport,
    timeout: float,
) -> EdgeReport:
    """WebUI to Hermes (in-process): bind, password, shared interpreter, optional /health."""
    name = "webui_hermes"
    problems: list[tuple[FailedLayer, str]] = []
    host = env.get("HERMES_WEBUI_HOST", "127.0.0.1")
    if not is_loopback_host(host):
        problems.append((FailedLayer.AUTH, "non_loopback_bind"))
    has_password = bool(env.get("HERMES_WEBUI_PASSWORD", "").strip())
    if not has_password:
        problems.append((FailedLayer.AUTH, "no_password"))
    webui_python = env.get("HERMES_WEBUI_PYTHON")
    venv = env.get(profile.python.venv_env)
    if not webui_python or not venv:
        problems.append((FailedLayer.ABI, "webui_python_or_runtime_venv_unset"))
    elif not _same_or_under(webui_python, venv):
        problems.append((FailedLayer.ABI, "webui_python_not_hermes_runtime"))
    presence = {"webui_password": Presence.PRESENT if has_password else Presence.ABSENT}
    if problems:
        layer = min((p[0] for p in problems), key=_LAYER_ORDER.index)
        return _blocked(
            name, layer, ",".join(p[1] for p in problems), presence=presence
        )
    raw_port = env.get("HERMES_WEBUI_PORT")
    if not raw_port:
        return EdgeReport(
            name=name,
            status=EdgeStatus.OK,
            level=HealthLevel.CONFIGURED,
            detail="static_checks_passed; no port to probe",
            presence=presence,
        )
    if not raw_port.strip().isdigit():
        return _blocked(
            name, FailedLayer.PROCESS, "webui_port_not_numeric", presence=presence
        )
    result = transport.http_get(host, int(raw_port), "/health", {}, timeout)
    if result.kind != "ok":
        return _unavailable(name, result, FailedLayer.PROCESS, "webui").model_copy(
            update={"presence": presence}
        )
    if result.status != 200:
        return EdgeReport(
            name=name,
            status=EdgeStatus.UNAVAILABLE,
            failed_layer=FailedLayer.PROCESS,
            detail=f"webui_http_{result.status}",
            presence=presence,
        )
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.CALLABLE,
        detail="webui_health_200",
        presence=presence,
    )


def _mysql_endpoint(
    settings_path: Path | None, env: Mapping[str, str]
) -> tuple[str, int]:
    """Host and port only; mirrors ``DatabaseConfig`` keys. Credentials are never read."""
    creds, _ = load_credentials(settings_path)
    host = next(
        (creds[k] for k in ("mysql_host", "db_host", "database_host") if creds.get(k)),
        None,
    )
    port = next(
        (creds[k] for k in ("mysql_port", "db_port", "database_port") if creds.get(k)),
        None,
    )
    host = host or env.get("DB_HOST") or "localhost"
    port = port or env.get("DB_PORT") or 3306
    try:
        return str(host), int(str(port))
    except (TypeError, ValueError):
        return str(host), 3306


def probe_mysql(
    settings_path: Path | None,
    env: Mapping[str, str],
    transport: Transport,
    timeout: float,
) -> EdgeReport:
    """OpenBB to MySQL: TCP reachability only. A listener proves nothing about auth."""
    name = "openbb_mysql"
    host, port = _mysql_endpoint(settings_path, env)
    if not is_loopback_host(host):
        return _blocked(name, FailedLayer.DATABASE, "mysql_host_not_loopback")
    result = transport.tcp_connect(host, port, timeout)
    if result.kind != "ok":
        return _unavailable(name, result, FailedLayer.DATABASE, "mysql")
    return EdgeReport(
        name=name,
        status=EdgeStatus.OK,
        level=HealthLevel.CONFIGURED,
        detail="tcp_reachable_only; auth and database name need the live step",
    )


@dataclass(frozen=True)
class HandshakeOptions:
    """Optional handshake inputs; an unset input leaves its edge not evaluated."""

    settings_path: Path | None = None
    mcp_tools: Sequence[Mapping[str, Any]] | None = None
    mcp_http_url: str | None = None
    backend_base_url: str | None = None
    timeout: float = 5.0
    gateway_facts: GatewayFacts | None = None  # LiteLLM proxy config, when supplied


def run_handshake(
    profile: FinanceRuntimeProfile,
    facts: RouteFacts | None,
    *,
    env: Mapping[str, str],
    transport: Transport | None = None,
    options: HandshakeOptions | None = None,
) -> list[EdgeReport]:
    """Evaluate every edge once. Never starts, installs or falls back."""
    opts = options or HandshakeOptions()
    timeout = opts.timeout
    transport = transport or LoopbackTransport()
    gateway = probe_gateway(
        profile, facts, env, transport, timeout, gateway_facts=opts.gateway_facts
    )
    edges = [
        check_webui(profile, env, transport, timeout),
        gateway,
        probe_backend(gateway, opts.backend_base_url, transport, timeout),
    ]
    if opts.mcp_tools is not None:
        edges.append(check_mcp_catalog(opts.mcp_tools, profile.mcp_catalog_sha256))
    else:
        edges.append(_not_evaluated("hermes_mcp_stdio", "no_tool_catalog_supplied"))
    if opts.mcp_http_url:
        edges.append(probe_mcp_http(opts.mcp_http_url, transport, timeout))
    if opts.settings_path is not None:
        edges.append(probe_mysql(opts.settings_path, env, transport, timeout))
    else:
        edges.append(_not_evaluated("openbb_mysql", "no_openbb_settings"))
    return edges
