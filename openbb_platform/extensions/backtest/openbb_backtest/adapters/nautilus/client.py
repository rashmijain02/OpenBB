"""Facade-side client: spawns the worker and speaks the signed stdio protocol.

Bounds (#1355 T03): the child gets a minimal environment (never the parent's
credentials), a memory limit (Windows Job Object / POSIX ``RLIMIT_AS`` /
``docker --memory``, default 4096 MiB), and a per-call deadline after which the
whole process tree is killed (and, for Docker, ``docker kill <name>``: killing
the ``docker`` CLI alone would leave the container running). The Docker
container is hardened (named, cpu/pids/memory limits, read-only data mount).
``run`` requests are screened with the worker's own admission module before they
are sent (fail fast; the worker re-checks).
"""

from __future__ import annotations

import contextlib
import enum
import os
import queue
import secrets
import subprocess
import threading
from collections.abc import Mapping, Sequence
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
DEFAULT_MEMORY_MB = 4096
DEFAULT_MEMORY_BYTES = DEFAULT_MEMORY_MB * 1024 * 1024
DEFAULT_CPUS = 2
PIDS_LIMIT = 256
CONTAINER_PREFIX = "hfp-nautilus-"
CONTAINER_DATA_ROOT = "/data"
DOCKER_KILL_TIMEOUT = 15.0


class _Default(enum.Enum):
    """Marker: ``memory_bytes`` was not given (use the runtime default)."""

    UNSET = 0


UNSET = _Default.UNSET


def docker_container_name(command: Sequence[str]) -> str | None:
    """Return the ``--name`` of a ``docker run`` command, else ``None``."""
    is_run = len(command) > 2 and command[1] == "run"
    if is_run and Path(command[0]).stem.lower() == "docker" and "--name" in command:
        idx = command.index("--name") + 1
        return command[idx] if idx < len(command) else None
    return None


def worker_env(env: Mapping[str, str]) -> dict[str, str]:
    """Minimal child environment: only :data:`CHILD_ENV_NAMES` are copied."""
    upper = {k.upper(): v for k, v in env.items()}
    return {name: upper[name] for name in CHILD_ENV_NAMES if name in upper}


def worker_command(  # pylint: disable=too-many-arguments
    runtime: str,
    env: Mapping[str, str],
    pin: NautilusPin | None = None,
    *,
    memory_mb: int | None = None,
    cpus: float = DEFAULT_CPUS,
    build_catalog: bool = False,
) -> list[str]:
    """Build the spawn command from environment variables named in the pin.

    Docker: random ``--name`` (so a deadline can ``docker kill`` it), memory /
    cpu / pids limits, ``--tmpfs /tmp``, and the data root mounted read-only at
    ``/data``. ``<root>/runs`` is mounted writable on every call (heavy-job lock);
    ``build_catalog`` additionally mounts ``<root>/catalogs`` writable.
    """
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
        mounts: list[str] = []
        root = env.get(DATA_ROOT_ENV)
        if root:
            if not Path(root).is_absolute():
                raise ProtocolError(
                    ErrorCode.CONFIG, f"{DATA_ROOT_ENV} must be absolute"
                )
            # ``runs/`` stays writable on every call: the heavy-job lock file lives
            # there and the rest of ``/data`` is read-only.
            mounts = [
                *("-v", f"{root}:{CONTAINER_DATA_ROOT}:ro"),
                *("-v", f"{Path(root, 'runs')}:{CONTAINER_DATA_ROOT}/runs"),
            ]
            if build_catalog:
                mounts += [
                    *("-v", f"{Path(root, 'catalogs')}:{CONTAINER_DATA_ROOT}/catalogs"),
                ]
            mounts += ["-e", f"{DATA_ROOT_ENV}={CONTAINER_DATA_ROOT}"]
        return [
            *("docker", "run", "--rm", "-i"),
            *("--name", CONTAINER_PREFIX + secrets.token_hex(8)),
            *("--network", "none", "--read-only", "--cap-drop", "ALL"),
            *("--security-opt", "no-new-privileges"),
            *("--memory", f"{memory_mb or DEFAULT_MEMORY_MB}m"),
            *("--cpus", f"{cpus:g}", "--pids-limit", str(PIDS_LIMIT)),
            *("--tmpfs", "/tmp"),  # noqa: S108
            *mounts,
            # The python base image exports GPG_KEY (a public key id); blank it.
            *("-e", "GPG_KEY="),
            image,
        ]
    raise ProtocolError(ErrorCode.CONFIG, "unknown runtime")


class WorkerClient:  # pylint: disable=too-many-instance-attributes
    """One worker process. The signing key goes over stdin only (not argv/env)."""

    def __init__(
        self,
        command: list[str],
        *,
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
        memory_bytes: int | None | _Default = UNSET,
        container_name: str | None = None,
    ):
        self._command = list(command)
        derived = docker_container_name(self._command)
        self._container = container_name or derived
        self._docker = command[0] if derived and not container_name else "docker"
        self._timeout = timeout
        self._env = dict(env) if env is not None else worker_env(os.environ)
        # Docker bounds memory with ``--memory``; the Job Object covers a native child.
        if isinstance(memory_bytes, _Default):
            memory_bytes = None if derived else DEFAULT_MEMORY_BYTES
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
        # Only the fields the caller set: a v2 body must not carry the v1
        # ``fees`` default (the worker rejects it; fees come from execution).
        return self.call(
            "run",
            req.model_dump(exclude_unset=True),
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
            if proc is not None and self._container and proc.poll() is None:
                self._docker_kill()
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

    def _docker_kill(self) -> None:
        """Kill the container by name; the ``docker`` CLI dying does not stop it."""
        if self._container is None:
            return
        # best effort: the CLI process is killed next regardless
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603
                [self._docker, "kill", self._container],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=DOCKER_KILL_TIMEOUT,
                check=False,
            )

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
