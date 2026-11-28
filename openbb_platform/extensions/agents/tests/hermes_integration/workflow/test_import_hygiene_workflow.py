"""Production workflow paths never import notebook or Jupyter code (#1340-T02).

AST based (CLAUDE.md testing rule 8): comments and docstrings cannot satisfy or
defeat it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[3]
PKG = AGENTS / "openbb_agents"
REGISTRY = (
    AGENTS.parent
    / "mcp_server"
    / "openbb_mcp_server"
    / "story_adapters"
    / "registry.py"
)
PRODUCTION = sorted((PKG / "hermes_integration").rglob("*.py")) + [REGISTRY]

FORBIDDEN_PREFIXES = (
    "openbb_agents.notebook_guide",
    "scripts",
    "nbformat",
    "nbclient",
    "nbconvert",
    "jupyter_client",
    "jupyter_core",
    "ipykernel",
    "IPython",
    "papermill",
)
NOTEBOOK_SUFFIX = ".ipy" + "nb"
# Reviewed exceptions: a synthetic notebook path the #1378 adversarial probe
# writes into a temporary repo only (never read from the real tree).
ALLOWED_LITERALS = {"adversarial.py": {"docs/examples/adv_pangolin.ipynb"}}


def _hits(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_PREFIXES
    )


def violations(source: str) -> list[str]:
    """Return every forbidden import or notebook-path constant in ``source``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _hits(a.name)]
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            if _hits(base) or any(_hits(f"{base}.{a.name}") for a in node.names):
                found.append(base)
            if node.level and "notebook_guide" in base.split("."):
                found.append(base)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.rstrip().lower()
            # An escaped ``\.ipynb`` is a refusal pattern, not a notebook path.
            if text.endswith(NOTEBOOK_SUFFIX) and not text.endswith(
                "\\" + NOTEBOOK_SUFFIX
            ):
                found.append(node.value)
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import nbformat",
        "import IPython.display",
        "from openbb_agents.notebook_guide import readiness",
        "from openbb_agents import notebook_guide",
        "from openbb_agents.notebook_guide.contracts import StoryManifest",
        "from ..notebook_guide import traceability",
        "from scripts.build_story_manifests import main",
        "from jupyter_client import KernelManager",
        "PATH = 'notebooks/portfolio/03.ipynb'",
    ],
)
def test_detector_flags_forbidden_sources(source):
    """The detector itself discriminates (reverse check for the real scan)."""
    assert violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from openbb_agents._stage_graph import check_acyclic",
        r"PATTERN = r'\.ipynb'",
        "# import nbformat",
        r"PATTERN = r'\.ipynb'",
    ],
)
def test_detector_accepts_clean_sources(source):
    """Comments and prose do not trip it."""
    assert not violations(source)


def test_production_paths_are_found():
    """Loud empty: the scan must cover the workflow modules and the registry."""
    names = {path.name for path in PRODUCTION}
    assert {"workflow.py", "admission.py", "workflow_admit.py", "registry.py"} <= names


def _unallowed(path: Path) -> list[str]:
    allowed = ALLOWED_LITERALS.get(path.name, set())
    return [v for v in violations(path.read_text("utf-8")) if v not in allowed]


def test_runtime_modules_never_import_notebook_code():
    """No production workflow module imports notebook, script or Jupyter code."""
    offenders = {path.name: _unallowed(path) for path in PRODUCTION}
    assert {name: hits for name, hits in offenders.items() if hits} == {}


def test_allowlist_entries_are_still_used():
    """A stale allowlist entry fails, so exceptions cannot outlive their use."""
    by_name = {path.name: path for path in PRODUCTION}
    for name, literals in ALLOWED_LITERALS.items():
        assert name in by_name, f"allowlisted module {name} is gone"
        found = set(violations(by_name[name].read_text("utf-8")))
        assert literals <= found, f"stale allowlist entry in {name}: {literals - found}"
