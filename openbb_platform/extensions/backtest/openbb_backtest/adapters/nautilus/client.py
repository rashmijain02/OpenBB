"""Facade-side client: spawns the worker and speaks the signed stdio protocol."""

from __future__ import annotations

import os
import queue
import secrets
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openbb_nautilus_worker import protocol
from openbb_nautilus_worker.protocol import DescribeFacts, ErrorCode, ProtocolError
from pydantic import ValidationError

from .pin import NautilusPin, load_pin


def worker_command(
    runtime: str, env: Mapping[str, str], pin: NautilusPin | None = None
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
    ):
        self._command = list(command)
        self._timeout = timeout
        self._env = dict(env) if env is not None else None
        self._key = secrets.token_bytes(protocol.KEY_BYTES)
        self._seq = 0
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[bytes | None] = queue.Queue()

    def __enter__(self) -> WorkerClient:
        """Spawn the worker and deliver the signing key."""
        try:
            self._proc = subprocess.Popen(  # noqa: S603
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env,
            )
        except (OSError, ValueError) as exc:
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

    def call(self, op: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one signed request; return the verified response body."""
        self._seq += 1
        self._write(
            protocol.encode_frame(
                protocol.sign_request(self._key, self._seq, op, body or {})
            )
        )
        try:
            line = self._lines.get(timeout=self._timeout)
        except queue.Empty:
            self.close()
            raise ProtocolError(ErrorCode.PROCESS, "worker timed out") from None
        if line is None:
            raise ProtocolError(ErrorCode.PROCESS, "worker exited without a response")
        resp = protocol.verify_response(
            self._key, protocol.decode_line(line), self._seq
        )
        if not resp.ok:
            err = resp.error
            try:
                code = ErrorCode(err.code) if err else ErrorCode.SCHEMA
            except ValueError:
                code = ErrorCode.SCHEMA
            raise ProtocolError(code, err.message if err else "error without detail")
        return resp.body or {}

    def describe(self) -> DescribeFacts:
        """Ask the worker to describe its runtime."""
        try:
            return DescribeFacts.model_validate(self.call("describe"))
        except ValidationError as exc:
            raise ProtocolError(
                ErrorCode.SCHEMA, "describe facts do not match schema"
            ) from exc

    def close(self) -> None:
        """Shut the worker down; kill it if it does not exit promptly."""
        proc, self._proc = self._proc, None
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
            proc.kill()
            proc.wait()
        finally:
            if proc.stdout:
                proc.stdout.close()


__all__ = ["WorkerClient", "worker_command"]
