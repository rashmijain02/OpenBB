"""Operator configuration for the Workspace backend (#1273).

Leaf module (stdlib plus the manifest ``contracts``; it never imports the
FastAPI app) shared by the app (``_app``) and the supported launcher
(``serve``):

- ``allowed_origins`` reads ``PI_WIDGET_BACKEND_ALLOWED_ORIGINS`` and
  rejects anything unsafe for a credentialed CORS policy;
- ``AccessLogRedactionFilter`` keeps query-string values (``account_id``,
  ``basket_id``, any query credential) out of uvicorn access logs;
- ``check_bind`` and ``preflight`` refuse an unauthenticated
  (``loopback-dev``) backend on a non-loopback interface;
- ``manifest_report`` summarises the manifest contract check against the
  recorded shrink-only debt baseline.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openbb_portfolio_intel.widget_backend import contracts, provenance

ALLOWED_ORIGINS_ENV = "PI_WIDGET_BACKEND_ALLOWED_ORIGINS"
AUTH_MODE_ENV = "PI_WIDGET_BACKEND_AUTH_MODE"
TOKEN_ENV = "PI_WIDGET_BACKEND_TOKEN"  # noqa: S105  # nosec B105 - env var name
AUTH_MODES = ("required", "loopback-dev")
DEFAULT_AUTH_MODE = "required"
DEFAULT_ALLOWED_ORIGINS = ("https://pro.openbb.co", "http://127.0.0.1:1420")

ACCESS_LOGGER = "uvicorn.access"
REDACTED = "<redacted>"
_MAX_REPORTED_ISSUES = 20


class OperatorConfigError(ValueError):
    """Raised for an unsafe or invalid operator configuration."""


# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------


def _normalize_origin(raw: str) -> str:
    """Return ``scheme://host[:port]`` or raise for an unsafe origin."""
    value = raw.strip()
    problem = f"{ALLOWED_ORIGINS_ENV}: {value!r} is not an exact origin"
    if "*" in value or value.lower() == "null":
        raise OperatorConfigError(
            f"{problem}; wildcards and 'null' are refused because the backend "
            "allows credentials"
        )
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise OperatorConfigError(f"{problem}; use http(s)://host[:port]")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise OperatorConfigError(f"{problem}; remove credentials, query or fragment")
    if parts.path not in ("", "/"):
        raise OperatorConfigError(f"{problem}; remove the path {parts.path!r}")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme.lower()}://{host}{port}"


def parse_allowed_origins(raw: str | None) -> list[str]:
    """Parse a comma-separated origin list; blank means the defaults."""
    if raw is None or not raw.strip():
        return list(DEFAULT_ALLOWED_ORIGINS)
    origins: list[str] = []
    for item in raw.split(","):
        if item.strip():
            origin = _normalize_origin(item)
            if origin not in origins:
                origins.append(origin)
    return origins


def allowed_origins(environ: Mapping[str, str] | None = None) -> list[str]:
    """Return the CORS origins configured for this deployment."""
    env = os.environ if environ is None else environ
    return parse_allowed_origins(env.get(ALLOWED_ORIGINS_ENV))


# ---------------------------------------------------------------------------
# Access-log privacy
# ---------------------------------------------------------------------------


def redact_query(target: str) -> str:
    """Keep the path and query keys of a request target; drop every value."""
    path, sep, query = target.partition("?")
    if not sep:
        return target
    pieces = []
    for item in query.split("&"):
        if not item:
            continue
        key, has_value, _ = item.partition("=")
        pieces.append(f"{key}={REDACTED}" if has_value else REDACTED)
    return f"{path}?{'&'.join(pieces)}"


class AccessLogRedactionFilter(logging.Filter):
    """Redact query-string values from uvicorn access-log records.

    uvicorn logs ``(client, method, path_with_query, http_version, status)``
    as the record args; the third element is rewritten in place so every
    handler (console, file, JSON) sees only the redacted target.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the request target and always keep the record."""
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_query(args[2]), *args[3:])
        return True


def install_access_log_redaction(
    logger: logging.Logger | None = None,
) -> AccessLogRedactionFilter:
    """Attach the redaction filter to the access logger once (idempotent)."""
    target = logger or logging.getLogger(ACCESS_LOGGER)
    for existing in target.filters:
        if isinstance(existing, AccessLogRedactionFilter):
            return existing
    redaction = AccessLogRedactionFilter()
    target.addFilter(redaction)
    return redaction


# ---------------------------------------------------------------------------
# Bind and environment preflight
# ---------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """Return True for ``localhost`` and loopback IP literals only."""
    value = host.strip().strip("[]").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def check_bind(host: str, auth_mode: str) -> str | None:
    """Refuse an unauthenticated non-loopback bind; warn for an exposed one.

    Returns a warning string for ``required`` mode on a non-loopback host
    and ``None`` when the bind is loopback.
    """
    if is_loopback_host(host):
        return None
    if auth_mode == "loopback-dev":
        raise OperatorConfigError(
            f"refusing to bind {host!r}: PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev "
            "is unauthenticated and may only bind a loopback address "
            "(127.0.0.1, ::1 or localhost). Use required mode with a token."
        )
    return (
        f"binding non-loopback host {host!r}: serve it only behind a TLS "
        "reverse proxy or private network, with the bearer token configured "
        "on the Workspace connection"
    )


def preflight(environ: Mapping[str, str], host: str) -> tuple[list[str], list[str]]:
    """Validate the launch environment; return ``(errors, warnings)``.

    Never includes the token value in any message.
    """
    errors: list[str] = []
    warnings: list[str] = []
    mode = environ.get(AUTH_MODE_ENV, DEFAULT_AUTH_MODE).strip().lower()
    if mode not in AUTH_MODES:
        errors.append(f"{AUTH_MODE_ENV} must be one of {list(AUTH_MODES)}")
    elif mode == "required" and not environ.get(TOKEN_ENV, "").strip():
        errors.append(
            f"{TOKEN_ENV} must be set in required auth mode "
            f"(or set {AUTH_MODE_ENV}=loopback-dev for local development)"
        )
    demo = environ.get(provenance.DEMO_MODE_ENV, "fallback").strip().lower()
    if (demo or "fallback") not in provenance.DEMO_MODES:
        errors.append(
            f"{provenance.DEMO_MODE_ENV} must be one of {list(provenance.DEMO_MODES)}"
        )
    try:
        parse_allowed_origins(environ.get(ALLOWED_ORIGINS_ENV))
    except OperatorConfigError as exc:
        errors.append(str(exc))
    try:
        warning = check_bind(host, mode)
    except OperatorConfigError as exc:
        errors.append(str(exc))
    else:
        if warning:
            warnings.append(warning)
    return errors, warnings


# ---------------------------------------------------------------------------
# Manifest verdict
# ---------------------------------------------------------------------------


def manifest_report(
    widgets: Any,
    apps: Any,
    *,
    routes: Iterable[str],
    baseline: Path | None = None,
) -> dict[str, Any]:
    """Validate the manifests and compare with the recorded debt baseline.

    ``ok`` is True when there is no issue beyond the baseline and no stale
    baseline entry (the same verdict as
    ``scripts/validate_portfolio_workspace_manifests.py``). Without a
    baseline file every issue counts as new.
    """
    issues = contracts.collect_manifest_issues(widgets, apps, routes=routes)
    recorded: dict[tuple[str, str], str] = {}
    if baseline is not None and baseline.is_file():
        recorded = {
            **contracts.load_debt_baseline(baseline, prefix="widgets."),
            **contracts.load_debt_baseline(baseline, prefix="apps."),
        }
    new, resolved = contracts.compare_with_baseline(issues, recorded)
    return {
        "ok": not new and not resolved,
        "widgets": len(widgets) if isinstance(widgets, dict) else 0,
        "apps": len(apps) if isinstance(apps, list) else 0,
        "issues": len(issues),
        "recorded_debt": len(recorded) - len(resolved),
        "new": [
            f"{issue.code} {issue.path}: {issue.message}"
            for issue in new[:_MAX_REPORTED_ISSUES]
        ],
        "stale_baseline": [
            f"{code} {path}" for code, path in resolved[:_MAX_REPORTED_ISSUES]
        ],
    }
