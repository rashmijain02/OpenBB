"""HFP sidecar: loopback-only FastAPI app behind the WebUI extension proxy (#1342).

T01 ships the security layer, ``/health``, ``/v1/session`` and the approval route
skeleton. The plan store behind ``POST /plans/<id>/approve`` lands in T02; until then
the route answers ``501 plan_store_unavailable`` after the guard and schema pass.

Usage: ``python -m openbb_agents.hermes_integration.web.sidecar --port N``. The token
file comes from ``HERMES_EXT_SIDECAR_TOKEN_FILE`` or ``HERMES_WEBUI_STATE_DIR``.
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
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .security import EXTENSION_ID, GuardSettings, SidecarGuard, resolve_token_file

LOOPBACK_HOST = "127.0.0.1"
_PLAN_ID = re.compile(r"plan_[0-9a-f]{32}")


@dataclass(frozen=True)
class SidecarConfig:
    """Server-side facts. The principal comes from here, never from a request."""

    port: int
    principal: str
    token_file: Path | None


class ApprovalRequest(BaseModel):
    """Closed approval body: the plan hash and the one-use nonce from ``GET /plans/<id>``."""

    model_config = ConfigDict(extra="forbid")

    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_nonce: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")


def _routes(config: SidecarConfig) -> FastAPI:
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    api.state.approve_calls = 0

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/v1/session")
    def session() -> dict[str, str]:
        return {"extension_id": EXTENSION_ID, "principal": config.principal}

    @api.post("/plans/{plan_id}/approve")
    def approve(
        plan_id: str, body: ApprovalRequest  # pylint: disable=unused-argument
    ) -> JSONResponse:
        if _PLAN_ID.fullmatch(plan_id) is None:
            return JSONResponse({"error": "plan_not_found"}, status_code=404)
        api.state.approve_calls += 1
        return JSONResponse({"error": "plan_store_unavailable"}, status_code=501)

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
        self, *, principal: str, token_file: Path | None, port: int = 0
    ) -> None:
        self._sock = bind_loopback(LOOPBACK_HOST, port)
        self.bound: tuple[str, int] = self._sock.getsockname()[:2]
        self.port = self.bound[1]
        self.app = create_app(
            SidecarConfig(port=self.port, principal=principal, token_file=token_file)
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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; serves until interrupted."""
    parser = argparse.ArgumentParser(prog="hfp_sidecar", description=__doc__)
    parser.add_argument("--host", default=LOOPBACK_HOST)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--principal", default="hfp-web")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    try:
        sock = bind_loopback(args.host, args.port)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"cannot bind: {type(exc).__name__}\n")
        return 2
    # pylint: disable=import-outside-toplevel
    from ..workflow_admit import in_process_principal

    config = SidecarConfig(
        port=sock.getsockname()[1],
        principal=in_process_principal(args.principal),
        token_file=resolve_token_file(os.environ),
    )
    sys.stdout.write(f"hfp sidecar on http://{LOOPBACK_HOST}:{config.port}\n")
    _server(create_app(config)).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
