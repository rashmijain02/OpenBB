"""Facade-side client: spawns the worker and speaks the signed stdio protocol.

Bounds (#1355 T03): the child gets a minimal environment (never the parent's
credentials), a memory limit (Windows Job Object / POSIX ``RLIMIT_AS`` /
``docker --memory``), and a per-call deadline after which the whole process
tree is killed. ``run`` requests are screened with the worker's own admission
module before they are sent (fail fast; the worker re-checks).
"""

from __future__ import annotations

import os
import queue
import secrets
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openbb_nautilus_worker import admission, protocol
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.protocol import DescribeFacts, ErrorCode, ProtocolError
from pydantic import ValidationError

from .bounds import ProcessBounds
from .pin import NautilusPin, load_pin

# Variables a child needs to start; everything else (credentials) stays behind.
CHILD_ENV_NAMES = (
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
    "TZ",
    DATA_ROOT_ENV,
)
# Grace after the request's own deadline: the worker's watchdog fires first.
DEADLINE_GRACE_SECONDS = 10.0


def worker_env(env: Mapping[str, str]) -> dict[str, str]:
    """Minimal child environment: only :data:`CHILD_ENV_NAMES` are copied."""
    upper = {k.upper(): v for k, v in env.items()}
    return {name: upper[name] for name in CHILD_ENV_NAMES if name in upper}


def worker_command(
    runtime: str,
    env: Mapping[str, str],
    pin: NautilusPin | None = None,
    *,
    memory_mb: int | None = None,
) -> list[str]:
    """Build the spawn command from environment variables named in the pin."""
    pin = pin or load_pin()
    if runtime == "native":
        venv = env.get(pin.env.venv)
        if not venv:
            raise ProtocolError(ErrorCode.CONFIG, f"{pin.env.venv} is not set")
        sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
        return [str(Path(venv, *sub)), "-I", "-m", "openbb_nautilus_worker"]
    if runtime == "docker":
        image = env.get(pin.env.image)
        if not image:
            raise ProtocolError(ErrorCode.CONFIG, f"{pin.env.image} is not set")
        return [
            *("docker", "run", "--rm", "-i"),
            *("--network", "none", "--read-only", "--cap-drop", "ALL"),
            *("--security-opt", "no-new-privileges"),
            *(("--memory", f"{memory_mb}m") if memory_mb else ()),
            image,
        ]
    raise ProtocolError(ErrorCode.CONFIG, "unknown runtime")


class WorkerClient:
    """One worker process. The signing key goes over stdin only (not argv/env)."""

    def __init__(
        self,
        command: list[str],
        *,
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
        memory_bytes: int | None = None,
    ):
        self._command = list(command)
        self._timeout = timeout
        self._env = dict(env) if env is not None else worker_env(os.environ)
        self._memory = memory_bytes
        self._bounds: ProcessBounds | None = None
        self.sent_requests = 0
        self._key = secrets.token_bytes(protocol.KEY_BYTES)
        self._seq = 0
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[bytes | None] = queue.Queue()

    def __enter__(self) -> WorkerClient:
        """Spawn the worker and deliver the signing key."""
        try:
            self._bounds = ProcessBounds(memory_bytes=self._memory)
            self._proc = subprocess.Popen(  # noqa: S603
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env,
                **self._bounds.popen_kwargs(),
            )
            self._bounds.attach(self._proc)
        except (OSError, ValueError) as exc:
            self._kill()
            raise ProtocolError(
                ErrorCode.PROCESS, "worker could not be started"
            ) from exc
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        self._write(protocol.encode_key_frame(self._key))
        return self

    def __exit__(self, *_exc) -> None:
        """Shut the worker down."""
        self.close()

    def _pump(self, proc: subprocess.Popen) -> None:
        stream = proc.stdout
        if stream is None:
            self._lines.put(None)
            return
        for line in iter(lambda: stream.readline(protocol.MAX_FRAME_BYTES + 2), b""):
            self._lines.put(line)
        self._lines.put(None)

    def _write(self, data: bytes) -> None:
        stdin = self._proc.stdin if self._proc is not None else None
        if stdin is None:
            raise ProtocolError(ErrorCode.PROCESS, "worker is not running")
        try:
            stdin.write(data)
            stdin.flush()
        except OSError as exc:
            raise ProtocolError(ErrorCode.PROCESS, "worker closed its input") from exc

    def key_hex_for_tests(self) -> str:
        """Expose the key so tests can assert it never reaches argv or env."""
        return self._key.hex()

    def call(
        self,
        op: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send one signed request; return the verified response body.

        Past the deadline (``timeout`` or the client default) the whole worker
        process tree is killed.
        """
        self._seq += 1
        self._write(
            protocol.encode_frame(
                protocol.sign_request(self._key, self._seq, op, body or {})
            )
        )
        self.sent_requests += 1
        try:
            line = self._lines.get(timeout=timeout or self._timeout)
        except queue.Empty:
            self._kill()
            raise ProtocolError(
                ErrorCode.PROCESS, "worker exceeded its deadline and was killed"
            ) from None
        if line is None:
            raise ProtocolError(ErrorCode.PROCESS, "worker exited without a response")
        raw = protocol.decode_line(line)
        # seq 0 = a signed session-level rejection (bad frame), not a reply.
        expected = 0 if raw.get("seq") == 0 else self._seq
        resp = protocol.verify_response(self._key, raw, expected)
        if not resp.ok:
            err = resp.error
            try:
                code = ErrorCode(err.code) if err else ErrorCode.SCHEMA
            except ValueError:
                code = ErrorCode.SCHEMA
            raise ProtocolError(code, err.message if err else "error without detail")
        return resp.body or {}

    def run(self, body: dict[str, Any]) -> dict[str, Any]:
        """Screen a ``run`` request locally, then run it under its deadline."""
        req = admission.screen_request(body)
        return self.call(
            "run",
            req.model_dump(),
            timeout=req.deadline_seconds + DEADLINE_GRACE_SECONDS,
        )

    def describe(self) -> DescribeFacts:
        """Ask the worker to describe its runtime."""
        try:
            return DescribeFacts.model_validate(self.call("describe"))
        except ValidationError as exc:
            raise ProtocolError(
                ErrorCode.SCHEMA, "describe facts do not match schema"
            ) from exc

    def _kill(self) -> None:
        """Kill the worker process tree now and release the bounds."""
        proc, self._proc = self._proc, None
        bounds, self._bounds = self._bounds, None
        try:
            if proc is not None and bounds is not None:
                bounds.kill_tree(proc)
            elif proc is not None:
                proc.kill()
            if proc is not None:
                proc.wait()
        finally:
            if bounds is not None:
                bounds.close()
            if proc is not None and proc.stdout:
                proc.stdout.close()

    def close(self) -> None:
        """Shut the worker down; kill its tree if it does not exit promptly."""
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                self._seq += 1
                proc.stdin.write(
                    protocol.encode_frame(
                        protocol.sign_request(self._key, self._seq, "shutdown", {})
                    )
                )
                proc.stdin.flush()
                proc.stdin.close()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self._kill()


__all__ = ["WorkerClient", "worker_command", "worker_env"]
