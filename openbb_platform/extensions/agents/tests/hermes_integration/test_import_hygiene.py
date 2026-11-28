"""AST guard: hermes_integration never imports config probing, litellm, ADK or Hermes."""

# ruff: noqa: D103

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "openbb_agents" / "hermes_integration"
FORBIDDEN_ROOTS = {"litellm", "google", "hermes", "hermes_cli", "hermes_agent"}


def _violations(source: str, filename: str = "<src>") -> list[str]:
    tree = ast.parse(source, filename)
    bad: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:  # relative: resolve against openbb_agents.hermes_integration
                base = ["openbb_agents", "hermes_integration"]
                base = base[: len(base) - (node.level - 1)]
                mod = ".".join(base + ([mod] if mod else []))
            names = [mod] + [f"{mod}.{a.name}" for a in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] in FORBIDDEN_ROOTS or name in (
                "openbb_agents.config",
                "openbb_agents.mcp_server",
            ):
                bad.append(name)
    return bad


def test_hermes_integration_never_imports_config_or_litellm():
    files = sorted(PKG.glob("*.py"))
    assert files, "package has no modules; wrong path?"
    found = {f.name: _violations(f.read_text("utf-8"), f.name) for f in files}
    assert {k: v for k, v in found.items() if v} == {}


def test_guard_detects_each_forbidden_import_shape():
    # the scanner itself must discriminate, otherwise the test above is ceremonial
    for src in (
        "import litellm",
        "from litellm import completion",
        "from openbb_agents import config",
        "from openbb_agents.config import X",
        "from .. import config",
        "from ..config import X",
        "import google.adk",
    ):
        assert _violations(src), src
    assert _violations("import yaml\nfrom pydantic import BaseModel") == []
