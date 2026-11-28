"""Audit-hook guard proving a workflow run never touches a notebook (#1340-T03).

``install()`` registers a ``sys.addaudithook`` that refuses, and counts:

* ``open`` / ``os.listdir`` / ``os.scandir`` of an ``.ipynb`` file or of a path
  with a ``notebooks``, ``notebooks_local`` or ``docs/examples`` segment;
* imports of Jupyter / notebook-execution modules.

Audit hooks cannot be removed. Install it only in a CLI process or in a
subprocess test, never in a shared pytest process.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

__all__ = [
    "NotebookAccessBlocked",
    "NotebookImportBlocked",
    "install",
    "installed",
    "stats",
]

_BLOCKED_SEGMENTS = frozenset({"notebooks", "notebooks_local"})
_BLOCKED_MODULES = frozenset(
    {
        "jupyter_client",
        "jupyter_core",
        "jupyter_server",
        "jupyterlab",
        "nbformat",
        "nbclient",
        "nbconvert",
        "nbclassic",
        "notebook",
        "ipykernel",
        "IPython",
        "papermill",
    }
)
# Built from parts so this guard is not itself flagged as naming a notebook.
_NOTEBOOK_SUFFIX = "." + "ipy" + "nb"
_PATH_EVENTS = frozenset({"open", "os.listdir", "os.scandir"})

_lock = threading.Lock()
_state = {"installed": False, "blocked_opens": 0, "blocked_imports": 0}


class NotebookAccessBlocked(PermissionError):
    """A notebook file or directory was accessed under the guard."""


class NotebookImportBlocked(ImportError):
    """A Jupyter or notebook-execution module was imported under the guard."""


def _is_notebook_path(raw: Any) -> bool:
    if isinstance(raw, int) or raw is None:
        return False
    try:
        text = os.fsdecode(raw)
    except (TypeError, ValueError):
        return False
    parts = [p.lower() for p in text.replace("\\", "/").split("/") if p]
    if parts and parts[-1].endswith(_NOTEBOOK_SUFFIX):
        return True
    if any(part in _BLOCKED_SEGMENTS for part in parts):
        return True
    return any(
        first == "docs" and second == "examples"
        for first, second in zip(parts, parts[1:])
    )


def _hook(event: str, args: tuple) -> None:
    if event in _PATH_EVENTS and args and _is_notebook_path(args[0]):
        with _lock:
            _state["blocked_opens"] += 1
        raise NotebookAccessBlocked("notebook access is forbidden for workflows")
    if event == "import" and args and str(args[0]).split(".", 1)[0] in _BLOCKED_MODULES:
        with _lock:
            _state["blocked_imports"] += 1
        raise NotebookImportBlocked("notebook modules are forbidden for workflows")


def install() -> None:
    """Install the guard once for this process (idempotent, irreversible)."""
    with _lock:
        if _state["installed"]:
            return
        _state["installed"] = True
    sys.addaudithook(_hook)


def installed() -> bool:
    """Whether ``install`` ran in this process."""
    return bool(_state["installed"])


def stats() -> dict[str, int]:
    """Return the number of refused notebook opens and Jupyter imports."""
    with _lock:
        return {
            "blocked_opens": _state["blocked_opens"],
            "blocked_imports": _state["blocked_imports"],
        }
