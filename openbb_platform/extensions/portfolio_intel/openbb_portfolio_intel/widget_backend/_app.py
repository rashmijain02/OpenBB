"""FastAPI ``app`` instance for the widget backend (#1007).

Leaf module holding just the ``app`` singleton so both ``main.py``
(register discovery + core endpoints) and ``widgets_endpoints.py``
(register the batch endpoints for #529-#577) can decorate routes
onto it without importing each other.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Disable openbb's import-time ``auto_build`` BEFORE openbb is ever imported in
# this process (#1962). ``openbb/__init__.py`` calls
# ``_PackageBuilder(_this_dir).auto_build()`` at import; when the committed
# ``reference.json`` differs from the installed extensions it triggers a
# multi-minute ``openbb.build()``. That build (a) is slow on every cold boot
# and (b) calls ``signal.signal(SIGTERM)`` which raises on any non-main thread
# (the lifespan warms up on an anyio worker thread) — a delete-then-fail that
# CORRUPTS the on-disk package and makes every widget serve ``stub``. The
# committed generated package already serves the live tier calls WITHOUT a
# rebuild, so the backend disables auto-build and simply primes it. ``setdefault``
# lets an operator force ``OPENBB_AUTO_BUILD=true`` back on if they really want a
# boot-time rebuild.
_AUTO_BUILD_ENV = "OPENBB_AUTO_BUILD"


def _default_auto_build_off() -> None:
    """Default ``OPENBB_AUTO_BUILD`` to ``false`` unless an operator overrode it.

    Called once at module import (before any ``import openbb``). Idempotent and
    directly unit-testable without reloading the module.
    """
    os.environ.setdefault(_AUTO_BUILD_ENV, "false")


_default_auto_build_off()

import anyio  # noqa: E402  # pylint: disable=wrong-import-position
from fastapi import (  # noqa: E402  # pylint: disable=wrong-import-position
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import (  # noqa: E402  # pylint: disable=wrong-import-position
    CORSMiddleware,
)
from fastapi.responses import (  # noqa: E402  # pylint: disable=wrong-import-position
    JSONResponse,
)
from starlette.datastructures import (  # noqa: E402  # pylint: disable=wrong-import-position
    MutableHeaders,
)

from openbb_portfolio_intel.widget_backend import (  # noqa: E402  # pylint: disable=wrong-import-position
    operator_config,
    provenance,
)

# Fail fast on a misconfigured demo mode (#1269): an invalid PI_DEMO_MODE
# stops the backend when the app is created, not with per-request 500s.
provenance.demo_mode()

logger = logging.getLogger(__name__)

# CORS: exact Workspace origins only. Defaults are the hosted and the
# self-hosted Workspace; PI_WIDGET_BACKEND_ALLOWED_ORIGINS replaces them per
# deployment and an unsafe value (wildcard, null, path) stops startup (#1273).
_ALLOWED_ORIGINS = operator_config.allowed_origins()

# Access logs keep request paths but never query values such as
# ``account_id`` / ``basket_id`` or a query-string credential (#1273, #1269).
operator_config.install_access_log_redaction()

_MANIFEST_DIR = Path(__file__).parent.resolve()
_DEBT_BASELINE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "unit"
    / "fixtures"
    / "workspace_contract_debt.json"
)
_VALIDATOR_HINT = "python scripts/validate_portfolio_workspace_manifests.py"

# Response header carrying the provider tier that served the request
# (e.g. ``fmp_cached`` vs ``stub``) so the local viewer can render a
# live-vs-demo badge (#1953). #1269 adds the data state and as-of headers.
_DATA_SOURCE_HEADER = provenance.SOURCE_HEADER
_EXPOSED_HEADERS = (
    provenance.SOURCE_HEADER,
    provenance.STATE_HEADER,
    provenance.AS_OF_HEADER,
)


def _prime_openbb() -> None:
    """Import + touch ``obb.equity`` so the lazy attribute tree materializes.

    With ``OPENBB_AUTO_BUILD=false`` (set at module load, see top of file) this
    ``import openbb`` does NOT trigger a build — openbb's import-time
    ``auto_build`` is short-circuited by ``Env().AUTO_BUILD``. The committed
    generated package under ``core/openbb/package/`` already wires the live tier
    providers (``fmp_cached`` et al.), so priming is a fast, main-thread-signal-
    free import that materializes ``obb.equity`` and makes the first real request
    pay no import cost. Safe to run on the lifespan's worker thread precisely
    because no ``signal.signal`` call happens (no build).
    """
    from openbb import obb  # pylint: disable=import-outside-toplevel

    _ = obb.equity


def _default_openbb_builder() -> None:
    """Prime the generated ``openbb`` package (the real warmup work).

    No build happens: the committed package is functional and ``auto_build`` is
    disabled (#1962). This just imports ``obb`` and touches ``obb.equity`` so the
    first request finds a materialized, live-wired package instead of paying the
    import cost mid-request (which used to exhaust the ChainedFetcher and serve
    ``stub``). Isolated from :func:`_warm_openbb` so unit tests can inject a fake
    builder.
    """
    _prime_openbb()


def _warm_openbb(builder: Callable[[], None] | None = None) -> None:
    """Prime the generated ``openbb`` package before serving (#1957, #1962).

    A cold backend whose generated package under ``core/openbb/package/`` is not
    yet materialized in-process pays a multi-second ``import openbb`` on the
    first live tier call inside the request handler; until it finishes the
    ChainedFetcher's tier dispatch raises, the chain exhausts, and the endpoint
    falls back to ``stub``. That is the recurring "everything says stub" symptom
    on a freshly-started backend — the Provider Health strip faithfully reports
    it. Priming at startup (before uvicorn accepts requests) guarantees the first
    real request finds a materialized, live-wired package and serves live.

    No ``openbb.build()`` runs: ``OPENBB_AUTO_BUILD`` is disabled at module load
    (see top of file) because the committed package already wires the live tier
    providers. This avoids the slow cold-boot rebuild AND the worker-thread
    ``signal.signal`` failure that used to corrupt the package and force stub
    (#1962).

    Best-effort: any failure is logged and swallowed so a prime hiccup never
    blocks server startup (widgets simply keep serving stub as before).
    Set ``PI_WIDGET_BACKEND_SKIP_WARMUP`` to skip (fast dev restarts). ``builder``
    is injectable for hermetic tests.
    """
    if os.environ.get("PI_WIDGET_BACKEND_SKIP_WARMUP"):
        logger.info("openbb warmup skipped (PI_WIDGET_BACKEND_SKIP_WARMUP set)")
        return
    try:
        (builder or _default_openbb_builder)()
        logger.info("openbb warmup complete — live-wired widgets ready to serve")
    except Exception:  # noqa: BLE001 - startup must not die on warmup
        logger.warning(
            "openbb warmup (prime) failed; live-wired widgets may serve stub until the generated package is importable",
            exc_info=True,
        )


def _register_health_probers() -> None:
    """Register the default provider-health reachability probers (#1956).

    Extracted from the lifespan so it can be unit-tested directly. Best-effort:
    a failure here must never abort server startup — the health strip simply
    keeps showing 'unknown' for any tier whose prober failed to register.
    """
    try:
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.providers.health_probers import (
            register_default_probers,
        )

        register_default_probers()
    except Exception:  # noqa: BLE001 - startup must not die on probe wiring
        logger.warning(
            "provider-health prober registration failed; strip will show 'unknown' until probers are available",
            exc_info=True,
        )


def _read_manifests() -> tuple[Any, Any]:
    """Read the served ``widgets.json`` and ``apps.json`` (UTF-8)."""
    return (
        json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8")),
        json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8")),
    )


def _validate_manifests_on_startup(target: Any) -> dict[str, Any]:
    """Check the manifests against the Workspace contract and log the verdict.

    Report-only (#1273): recorded debt is expected, so startup continues, but
    any new issue, stale baseline entry or unreadable manifest is logged as a
    WARNING naming each problem and the validator command. The report is kept
    on ``target.state.manifest_report`` and served by ``/health``.
    """
    try:
        widgets, apps = _read_manifests()
        routes = {getattr(route, "path", "") for route in target.routes}
        report = operator_config.manifest_report(
            widgets, apps, routes=routes, baseline=_DEBT_BASELINE
        )
    except Exception as exc:  # noqa: BLE001 - startup must not die on validation
        report = {"ok": False, "error": f"manifest unreadable: {type(exc).__name__}"}
        logger.warning(
            "Workspace manifest validation failed: %s. Run %s for detail.",
            report["error"],
            _VALIDATOR_HINT,
        )
    else:
        if report["ok"]:
            logger.info(
                "Workspace manifest validation passed: %d widgets, %d apps, "
                "%d recorded-debt issue(s)",
                report["widgets"],
                report["apps"],
                report["recorded_debt"],
            )
        else:
            problems = [*report["new"], *report["stale_baseline"]]
            logger.warning(
                "Workspace manifest validation found %d problem(s): %s. Run %s.",
                len(problems),
                "; ".join(problems),
                _VALIDATOR_HINT,
            )
    target.state.manifest_report = report
    return report


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Server lifespan — registers real provider-health probers on boot (#1956).

    This runs when uvicorn (the real server) starts. A bare ``TestClient(app)``
    used in the unit suite does NOT run lifespan, so the prober registry stays
    empty there and ``provider_health`` returns an instant 'unknown' — keeping
    unit tests hermetic (no network).

    The ``openbb`` package is warmed FIRST so the first real request finds a
    materialized package and serves live instead of stub (#1957). No
    ``openbb.build()`` runs — ``OPENBB_AUTO_BUILD`` is disabled at module load
    and the committed package already wires the live tiers; the prior
    boot-time rebuild both slowed cold starts AND corrupted the package via a
    worker-thread ``signal.signal`` failure that forced stub (#1962). Priming is
    offloaded via ``anyio.to_thread`` to keep the event loop responsive during
    the import.
    """
    provenance.demo_mode()  # re-validated on server start (#1269)
    _validate_manifests_on_startup(_app)  # reported, not fatal (#1273)
    await anyio.to_thread.run_sync(_warm_openbb)
    _register_health_probers()
    try:
        yield
    finally:
        background_tasks = set(getattr(_app.state, "background_tasks", set()))
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        _app.state.background_tasks.clear()

        # Best-effort teardown of the pooled probe client so httpx doesn't warn
        # about an unclosed client at interpreter shutdown.
        try:
            # pylint: disable=import-outside-toplevel
            from openbb_portfolio_intel.providers.health_probers import (
                aclose_shared_client,
            )

            await aclose_shared_client()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.debug("provider-health probe client close failed", exc_info=True)


app = FastAPI(
    title="OpenBB Portfolio Intelligence — Workspace backend",
    description=(
        "Custom-backend widgets for the OpenBB Workspace. Wraps the "
        "portfolio_intel extension's analytics modules as Workspace-"
        "consumable HTTP endpoints."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)
app.state.background_tasks = set()


@app.get("/health", include_in_schema=False)
def health() -> JSONResponse:
    """Unauthenticated liveness probe (#1273): ``{"status": "ok"}`` and nothing else.

    Deployment detail lives behind auth at ``/health/details``.
    """
    return JSONResponse(content={"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.get("/health/details", include_in_schema=False)
def health_details(request: Request) -> JSONResponse:
    """Return authenticated operator detail (#1273); never returns secrets.

    Requires the normal bearer token in ``required`` mode. In ``loopback-dev``
    mode (no token) it is served to loopback clients only. Reports the pid
    (the launcher confirms identity before ``stop``), the auth and demo
    modes, the CORS origins and the manifest verdict computed at startup
    (lazily when no lifespan ran).
    """
    # Lazy: `_shared` enforces the auth configuration at import, which this
    # leaf module must not do (`main` imports it first in a real server).
    # pylint: disable-next=import-outside-toplevel
    from openbb_portfolio_intel.widget_backend import _shared

    _shared.require_auth(request)
    auth_mode = _shared._AUTH_MODE  # pylint: disable=protected-access
    if auth_mode == "loopback-dev":
        client = request.client.host if request.client else ""
        if not operator_config.is_loopback_host(client):
            raise HTTPException(
                status_code=403,
                detail="health details are loopback-only in loopback-dev mode",
            )
    report = getattr(app.state, "manifest_report", None)
    if report is None:
        report = _validate_manifests_on_startup(app)
    return JSONResponse(
        content={
            "status": "ok",
            "service": "portfolio-intel-widget-backend",
            "pid": os.getpid(),
            "auth_mode": auth_mode,
            "demo_mode": provenance.demo_mode(),
            "allowed_origins": list(_ALLOWED_ORIGINS),
            "manifest": report,
        },
        headers={"Cache-Control": "no-store"},
    )


class _DataSourceHeaderMiddleware:
    """Stamp each response with its own data state and source (#1953, #1269).

    Read-only, pure-ASGI. The middleware starts a fresh per-request
    provenance record before the endpoint runs; the widget decorators publish
    the response's final record into it (sync endpoints run in a worker
    thread with a copy of this context, which still points at the same
    record). The headers are therefore taken from the very record the body
    was rendered from, so ``X-PI-Data-Source`` always equals the body's
    ``meta.source`` / ``data_source`` even under concurrent requests to the
    same path. (Before #1269 it read the shared ``_TIER_IN_USE`` ledger,
    which a concurrent request could overwrite.) A 401/403 carries
    ``X-PI-Data-State: forbidden`` and no source.
    """

    def __init__(self, asgi_app: Any) -> None:
        self.app = asgi_app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        holder, token = provenance.bind()

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                values: dict[str, str] = {}
                if message.get("status") in (401, 403):
                    values[provenance.STATE_HEADER] = "forbidden"
                elif holder.final is not None:
                    values = holder.final.headers()
                elif holder.tier:
                    values[_DATA_SOURCE_HEADER] = holder.tier
                if values:
                    headers = MutableHeaders(scope=message)
                    for name, value in values.items():
                        headers[name] = value
                    # Let the (cross-origin) Workspace read the headers too.
                    existing = headers.get("access-control-expose-headers")
                    exposed = ", ".join(_EXPOSED_HEADERS)
                    headers["access-control-expose-headers"] = (
                        exposed if not existing else f"{existing}, {exposed}"
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            provenance.unbind(token)


# Order matters: add the CORS middleware LAST so it wraps outermost (runs
# first on the way in / last on the way out), keeping preflight handling and
# CORS headers intact while the data-source middleware sits just inside it.
app.add_middleware(_DataSourceHeaderMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
