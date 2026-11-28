"""HFP sidecar: loopback-only FastAPI app behind the WebUI extension proxy (#1342).

Routes (all behind the T01 guard): ``/health``, ``/v1/session``, ``GET /plans/<id>``
(plan card plus a one-use approval nonce), ``POST /plans/<id>/approve`` (the human
approval, ``approve_plan``), ``GET /runs/<id>`` (run/outcome card from the shared run
and job stores) and ``GET /workflows`` (starter list; the composer is pre-filled, never
sent). No route starts a workflow, submits a job or approves a paper action. Without a
:class:`~.backend.StoryBackend` the plan routes answer ``plan_store_unavailable``.

Usage: ``python -m openbb_agents.hermes_integration.web.sidecar --port N``. The token
file comes from ``HERMES_EXT_SIDECAR_TOKEN_FILE`` or ``HERMES_WEBUI_STATE_DIR``.
The story principal is the finance-web MCP server's own (``live_story_principal``:
its ``OPENBB_MCP_SERVER_AUTH`` credentials); without them the sidecar exits 4
(``principal_unpaired``) before binding. ``--check`` runs only that check.
The listener binds ``127.0.0.1`` only. The sidecar never runs a model or Hermes.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openbb_mcp_server.story_adapters.plans import APPROVE_STATUS
from pydantic import BaseModel, ConfigDict, Field

from . import cards
from .security import EXTENSION_ID, GuardSettings, SidecarGuard, resolve_token_file

if TYPE_CHECKING:
    from .backend import StoryBackend

LOOPBACK_HOST = "127.0.0.1"
_PLAN_ID = re.compile(r"plan_[0-9a-f]{32}")
_RUN_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class SidecarConfig:
    """Server-side facts. The principal comes from here, never from a request."""

    port: int
    principal: str
    token_file: Path | None
    backend: StoryBackend | None = None


class ApprovalRequest(BaseModel):
    """Closed approval body: the plan hash and the one-use nonce from ``GET /plans/<id>``."""

    model_config = ConfigDict(extra="forbid")

    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_nonce: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")


def _json(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status)


def _routes(config: SidecarConfig) -> FastAPI:  # noqa: C901
    # pylint: disable=too-many-statements
    backend = config.backend
    if backend is not None and backend.principal != config.principal:
        raise ValueError("principal_mismatch: backend and sidecar principals differ")
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    api.state.approve_calls = 0

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/v1/session")
    def session() -> dict[str, str]:
        return {"extension_id": EXTENSION_ID, "principal": config.principal}

    @api.get("/workflows")
    def workflows() -> JSONResponse:
        if backend is None:
            return _json(503, cards.unavailable("workflows", "plan_store_unavailable"))
        return _json(200, cards.workflows_card(backend.workflow_ids()))

    @api.get("/plans/{plan_id}")
    def plan(plan_id: str) -> JSONResponse:
        if _PLAN_ID.fullmatch(plan_id) is None:
            return _json(404, {"error": "plan_not_found"})
        if backend is None:
            body = cards.unavailable("plan", "plan_store_unavailable", plan_id=plan_id)
            return _json(503, {"error": "plan_store_unavailable", **body})
        stored = backend.plan(plan_id)
        if stored is None:
            return _json(404, {"error": "plan_not_found"})
        now = datetime.now(timezone.utc)
        nonce = None
        if stored.state == "pending" and not stored.expired(now):
            nonce = backend.issue_nonce(plan_id)
        return _json(200, cards.plan_card(stored, nonce, now))

    @api.post("/plans/{plan_id}/approve")
    def approve(plan_id: str, body: ApprovalRequest) -> JSONResponse:
        if _PLAN_ID.fullmatch(plan_id) is None:
            return _json(404, {"error": "plan_not_found"})
        api.state.approve_calls += 1
        if backend is None:
            return _json(501, {"error": "plan_store_unavailable"})
        result, stored = backend.approve(
            plan_id, plan_sha256=body.plan_sha256, nonce=body.approval_nonce
        )
        status = APPROVE_STATUS[result]
        if status != 200 or stored is None:
            return _json(status, {"error": result})
        now = datetime.now(timezone.utc)
        return _json(
            200, {"result": result, "card": cards.plan_card(stored, None, now)}
        )

    @api.get("/runs/{run_id}")
    def run(run_id: str) -> JSONResponse:
        if _RUN_ID.fullmatch(run_id) is None:
            return _json(404, {"error": "run_unavailable"})
        if backend is None:
            body = cards.unavailable("run", "run_unavailable", run_id=run_id)
            return _json(503, {"error": "run_unavailable", **body})
        facts = backend.run(run_id)
        if facts is None:
            return _json(404, {"error": "run_unavailable"})
        return _json(
            200,
            cards.run_card(
                run_id=run_id,
                plan_id=facts.plan.plan_id if facts.plan else None,
                workflow_id=facts.plan.workflow_id if facts.plan else None,
                outcome=facts.outcome,
                jobs=facts.jobs,
                artifacts=facts.artifacts,
                worker_unavailable=facts.worker_unavailable,
            ),
        )

    return api


class GuardedApp:  # pylint: disable=too-few-public-methods
    """The guarded ASGI app; ``state`` is the inner FastAPI state (test counters)."""

    def __init__(self, config: SidecarConfig) -> None:
        self.inner = _routes(config)
        self.state = self.inner.state
        self._guard = SidecarGuard(
            self.inner, GuardSettings(port=config.port, token_file=config.token_file)
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Forward to the guard."""
        await self._guard(scope, receive, send)


def create_app(config: SidecarConfig) -> GuardedApp:
    """Build the guarded app for ``config``."""
    return GuardedApp(config)


def bind_loopback(host: str, port: int) -> socket.socket:
    """Bind a listening socket on ``127.0.0.1`` only; anything else is refused."""
    if host != LOOPBACK_HOST:
        raise ValueError("non_loopback_bind: the HFP sidecar binds 127.0.0.1 only")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            sock.setsockopt(
                socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0) or 0, 1
            )
        sock.bind((LOOPBACK_HOST, port))
        sock.listen(64)
    except OSError:
        sock.close()
        raise
    return sock


def _server(app: GuardedApp) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            server_header=False,
            date_header=False,
            lifespan="off",
        )
    )


class LoopbackSidecar:
    """Run the sidecar on an ephemeral (or given) loopback port in a thread."""

    def __init__(
        self,
        *,
        principal: str,
        token_file: Path | None,
        port: int = 0,
        backend: StoryBackend | None = None,
    ) -> None:
        self._sock = bind_loopback(LOOPBACK_HOST, port)
        self.bound: tuple[str, int] = self._sock.getsockname()[:2]
        self.port = self.bound[1]
        self.app = create_app(
            SidecarConfig(
                port=self.port,
                principal=principal,
                token_file=token_file,
                backend=backend,
            )
        )
        self._server = _server(self.app)
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._sock]},
            name="hfp-sidecar",
            daemon=True,
        )

    def __enter__(self) -> LoopbackSidecar:
        """Start the server thread and wait until it accepts connections."""
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("sidecar did not start")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        """Stop the server and close the listening socket."""
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        self._sock.close()

    def __exit__(self, *_exc: object) -> None:
        """Stop the server."""
        self.stop()


class PairingError(RuntimeError):
    """The sidecar cannot act as the MCP server's story principal."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def live_story_principal(settings: Any = None) -> str:
    """Return the story principal the live MCP server writes plans and runs as.

    It is derived exactly as the server derives it (``story_principal_for`` of
    its ``server_auth`` credentials), from the same settings source the server
    reads (``mcp_settings.json`` under env and no CLI overrides). Missing or
    blank credentials raise ``principal_unpaired``; the secret is never logged.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.app.app import story_principal_for
    from openbb_mcp_server.service.mcp_service import MCPService

    if settings is None:
        settings = MCPService.read_with_overrides()
    auth = getattr(settings, "server_auth", None)
    if (
        not auth
        or len(auth) != 2
        or not all(isinstance(value, str) and value.strip() for value in auth)
    ):
        raise PairingError(
            "principal_unpaired",
            "set OPENBB_MCP_SERVER_AUTH (or server_auth in mcp_settings.json)"
            " to the finance-web MCP server's credentials",
        )
    return story_principal_for((auth[0], auth[1]))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; serves until interrupted.

    Exit codes: 0 served (or ``--check`` passed), 2 cannot bind, 3 usage,
    4 ``principal_unpaired`` (no usable MCP server credentials).
    """
    parser = argparse.ArgumentParser(prog="hfp_sidecar", description=__doc__)
    parser.add_argument("--host", default=LOOPBACK_HOST)
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--check",
        action="store_true",
        help="only check the pairing with the MCP server credentials",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    # Fail closed before binding: without the MCP server's own credentials the
    # sidecar would read another principal's (empty) plan and run stores.
    try:
        principal = live_story_principal()
    except PairingError as exc:
        sys.stderr.write(f"{exc.code}: {exc.detail}\n")
        return 4
    if args.check:
        sys.stdout.write("pairing_ok\n")
        return 0
    if args.port is None:
        sys.stderr.write("usage: --port is required\n")
        return 3
    try:
        sock = bind_loopback(args.host, args.port)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"cannot bind: {type(exc).__name__}\n")
        return 2
    # pylint: disable=import-outside-toplevel
    from openbb_core.api.dependency.jobs import get_job_service
    from openbb_mcp_server.story_adapters.artifacts import default_artifact_root
    from openbb_mcp_server.story_adapters.registry import default_store_path

    from .backend import StoryBackend

    config = SidecarConfig(
        port=sock.getsockname()[1],
        principal=principal,
        token_file=resolve_token_file(os.environ),
        # The same run store and job store the workflow worker uses.
        backend=StoryBackend(
            principal=principal,
            store_path=default_store_path(),
            artifact_root=default_artifact_root(),
            service=get_job_service(),
        ),
    )
    sys.stdout.write(f"hfp sidecar on http://{LOOPBACK_HOST}:{config.port}\n")
    _server(create_app(config)).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
