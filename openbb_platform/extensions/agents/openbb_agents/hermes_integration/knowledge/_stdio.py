"""Shared stdio-probe helpers for the knowledge probes (#1378).

A closed-port, temporary-HOME environment for the gated server child, a
read-only-config git runner for synthetic repos, and the gated launch flags.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path

from ..policy_probe import child_pythonpath

_PASS_THROUGH = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC")
_EGRESS = re.compile(r"knowledge_egress attempts=(\d+)")


def _env(home: Path) -> dict[str, str]:
    env = {k: os.environ[k] for k in _PASS_THROUGH if k in os.environ}
    env["PYTHONPATH"] = child_pythonpath(os.environ.get("PYTHONPATH"))
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        env[key] = str(home)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env["DB_HOST"] = "127.0.0.1"
    env["DB_PORT"] = str(port)  # closed: nothing listens there
    return env


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=probe",
            "-c",
            "user.email=probe@invalid",
            "-C",
            str(root),
            *args,
        ],
        check=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def _flags(register_path: Path | None) -> list[str]:
    flags = ["--policy-profile", "hermes-finance", "--principal", "hermes_runtime"]
    if register_path is not None:
        flags += ["--knowledge-register", str(register_path)]
    return flags
