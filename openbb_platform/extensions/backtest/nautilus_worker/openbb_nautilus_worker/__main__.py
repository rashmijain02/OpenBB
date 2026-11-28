"""Worker entrypoint: ``python -I -m openbb_nautilus_worker`` (stdio, no listener).

Start-up order: install the import and socket guards, read the key frame
(bounded by the idle timeout), then check the environment. A worker started
with broker-credential-shaped variables answers its first signed request with
``egress`` (names only) and exits. Otherwise it serves signed frames until
``shutdown``, EOF, an authentication failure, or ``idle_seconds`` without a
request. Heavy ops (``build_catalog``, ``run``) hold the cross-worker heavy-job
lock; ``run`` also has a hard wall-time deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
from collections.abc import Mapping
from typing import Any

from . import catalog_build, describe, guards, protocol, runs

DEFAULT_IDLE_SECONDS = 120.0
_READ_LIMIT = protocol.MAX_FRAME_BYTES + 2
_TIMEOUT = object()


class FdLines:
    """``readline`` over a raw fd with ``os.read`` (no buffered-reader lock).

    A daemon thread blocked in ``BufferedReader.readline`` can abort
    interpreter shutdown; a blocked ``os.read`` cannot.
    """

    def __init__(self, fd: int):
        self._fd = fd
        self._buf = b""

    def readline(self, limit: int) -> bytes:
        """Return one line (with newline), at most ``limit`` bytes; b"" on EOF."""
        while b"\n" not in self._buf and len(self._buf) < limit:
            chunk = os.read(self._fd, 65536)
            if not chunk:
                break
            self._buf += chunk
        end = self._buf.find(b"\n")
        cut = min(limit, end + 1) if end >= 0 else min(limit, len(self._buf))
        line, self._buf = self._buf[:cut], self._buf[cut:]
        return line


class _Lines:
    """Lines from ``stdin`` on a daemon thread, so reads can time out (idle)."""

    def __init__(self, stdin: Any):
        self._q: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._pump, args=(stdin,), daemon=True).start()

    def _pump(self, stdin: Any) -> None:
        try:
            while True:
                line = stdin.readline(_READ_LIMIT)
                self._q.put(line)
                if not line:
                    return
        except (OSError, ValueError):
            self._q.put(b"")

    def get(self, timeout: float) -> Any:
        """Next line, ``b""`` on EOF, or ``_TIMEOUT``."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return _TIMEOUT


def build_handlers(
    env: Mapping[str, str],
    *,
    engine: runs.Engine | None = None,
    fixed_precision: int | None = None,
) -> dict[str, protocol.Handler]:
    """Op handlers; heavy ops hold the heavy-job lock."""

    def build(body: dict[str, Any]) -> dict[str, Any]:
        root = catalog_build.data_root(env)
        with guards.HeavyJobLock(root / "runs" / runs.LOCK_NAME):
            return catalog_build.build_catalog(
                body, env=env, fixed_precision=fixed_precision
            )

    def run(body: dict[str, Any]) -> dict[str, Any]:
        return runs.run(body, env=env, engine=engine, fixed_precision=fixed_precision)

    return {
        "describe": describe.collect_facts,
        "build_catalog": build,
        "run": run,
        "shutdown": lambda _body: {},
    }


def _write(stdout: Any, data: bytes) -> None:
    stdout.write(data)
    stdout.flush()


def run_worker(
    stdin: Any,
    stdout: Any,
    *,
    env: Mapping[str, str],
    idle_seconds: float = DEFAULT_IDLE_SECONDS,
    engine: runs.Engine | None = None,
    fixed_precision: int | None = None,
    install: bool = True,
) -> int:
    """Serve one spawn; return the process exit code (see ``guards.EXIT_*``)."""
    if install:
        guards.install_runtime_guards()
    lines = _Lines(stdin)
    key_line = lines.get(idle_seconds)
    if key_line is _TIMEOUT:
        return guards.EXIT_AUTH
    try:
        session = protocol.Session.from_key_line(key_line)
    except protocol.ProtocolError:
        return guards.EXIT_AUTH
    refused = guards.broker_env_names(env)
    if refused:
        line = lines.get(idle_seconds)
        if line is _TIMEOUT or not line:
            return guards.EXIT_EGRESS

        def refuse(_body: dict[str, Any]) -> dict[str, Any]:
            guards.refuse_broker_env(env)
            return {}

        out, _ = session.handle(line, dict.fromkeys(protocol.KNOWN_OPS, refuse))
        _write(stdout, out)
        return guards.EXIT_EGRESS
    handlers = build_handlers(env, engine=engine, fixed_precision=fixed_precision)
    while True:
        line = lines.get(idle_seconds)
        if line is _TIMEOUT:
            return guards.EXIT_IDLE
        if not line:
            return 0
        out, stop = session.handle(line, handlers)
        _write(stdout, out)
        if stop:
            return 0 if json.loads(out).get("ok") else guards.EXIT_AUTH


def main(
    argv: list[str] | None = None,
    *,
    engine: runs.Engine | None = None,
    fixed_precision: int | None = None,
) -> int:
    """Run the worker on the process's binary stdio."""
    ap = argparse.ArgumentParser(prog="openbb_nautilus_worker")
    ap.add_argument("--idle-seconds", type=float, default=DEFAULT_IDLE_SECONDS)
    args = ap.parse_args(argv)
    return run_worker(
        FdLines(sys.stdin.fileno()),
        sys.stdout.buffer,
        env=dict(os.environ),
        idle_seconds=args.idle_seconds,
        engine=engine,
        fixed_precision=fixed_precision,
    )


if __name__ == "__main__":
    raise SystemExit(main())
