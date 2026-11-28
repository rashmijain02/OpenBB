"""Synthetic git repositories for the public-knowledge tests (#1378).

Every repository is created under ``tmp_path`` with real ``git`` so blob pins,
untracked files, ignored files, symlink and gitlink entries are real git states.
All content is synthetic and public-shaped.
"""

# ruff: noqa: D102, D103, S603, S607

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

_GIT_CFG = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "user.name=t",
    "-c",
    "user.email=t@invalid",
    "-c",
    "init.defaultBranch=main",
)


class SynthRepo:
    """A tiny synthetic git repository with helpers for exact git states."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True)
        self.git("init", "-q")

    def git(self, *args: str, data: bytes | None = None) -> str:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
        result = subprocess.run(
            ["git", *_GIT_CFG, "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            input=data,
            env=env,
        )
        return result.stdout.decode("utf-8").strip()

    def write(self, rel: str, content: str | bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = content.encode("utf-8") if isinstance(content, str) else content
        path.write_bytes(payload)
        return path

    def commit(self, message: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def blob(self, rel: str, rev: str = "HEAD") -> str:
        return self.git("rev-parse", f"{rev}:{rel}")

    def index_entry(self, mode: str, rel: str, target: str) -> None:
        """Add a raw index entry (symlink 120000 or gitlink 160000) without the FS."""
        sha = target
        if mode == "120000":
            sha = self.git("hash-object", "-w", "--stdin", data=target.encode())
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{rel}")


@pytest.fixture
def repo(tmp_path: Path) -> SynthRepo:
    return SynthRepo(tmp_path / "repo")


def row(source_id: str, path: str, blob_sha: str, **extra: Any) -> dict[str, Any]:
    """Return a register row with conservative defaults (unknown status, design kind)."""
    base: dict[str, Any] = {
        "source_id": source_id,
        "path": path,
        "blob_sha": blob_sha,
        "kind": "design",
        "authority": "repo_design",
        "status": "unknown",
        "status_evidence": "none",
        "privacy_class": "public_reference",
        "model_context": "allowed",
    }
    base.update(extra)
    return base


def register_doc(reviewed_commit: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "reviewed_commit": reviewed_commit, "sources": rows}


@pytest.fixture
def write_register(tmp_path: Path):
    """Write a register JSON outside the synthetic repo and return its path."""

    def _write(doc: dict[str, Any]) -> Path:
        path = tmp_path / "register" / "public_sources.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    return _write
