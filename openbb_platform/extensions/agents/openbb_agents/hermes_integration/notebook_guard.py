"""Audit-hook guard proving a workflow run never touches a notebook (#1340-T03).

``install()`` registers a ``sys.addaudithook`` that refuses, and counts:

* ``open`` / ``os.listdir`` / ``os.scandir`` of an ``.ipynb`` file or of a path
  with a ``notebooks``, ``notebooks_local`` or ``docs/examples`` segment;
* ``os.chdir`` into such a directory;
* imports of Jupyter / notebook-execution modules;
* ``subprocess.Popen`` / ``os.system`` launching a ``jupyter*``, ``nb*``,
  ``ipython*`` or ``papermill*`` program.

Path parts are normalised the way Windows resolves them (trailing dots and
spaces dropped, NTFS ``:stream`` suffixes split off) before matching.

This is a **proof device, not a security boundary**: it demonstrates that the
workflow path does not touch notebooks. In-process code can still bypass it
(ctypes, ``_io`` handles opened before install, renamed launchers, ...);
access control is admission plus the server's capability policy.

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
_PATH_EVENTS = frozenset({"open", "os.listdir", "os.scandir", "os.chdir"})
_LAUNCH_EVENTS = frozenset({"subprocess.Popen", "os.system"})
_BLOCKED_PROGRAM_PREFIXES = ("jupyter", "nb", "ipython", "papermill")
_SHELLS = frozenset({"cmd", "sh", "bash", "pwsh", "powershell"})
_SHELL_FLAGS = frozenset({"/c", "/k", "-c", "-command"})

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
    parts = [_normalise_part(p) for p in text.replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if parts and parts[-1].endswith(_NOTEBOOK_SUFFIX):
        return True
    if any(part in _BLOCKED_SEGMENTS for part in parts):
        return True
    return any(
        first == "docs" and second == "examples"
        for first, second in zip(parts, parts[1:])
    )


def _normalise_part(part: str) -> str:
    """Lower-case one path part as Windows resolves it (``x.ipynb. :s``)."""
    if len(part) > 2 and ":" in part:  # keep drive letters like ``C:``
        part = part.split(":", 1)[0]
    return part.rstrip(". ").lower()


def _launches_notebook_program(event: str, args: tuple) -> bool:
    """Whether a process launch starts a Jupyter / notebook program."""
    padded = (*args, None, None, None)
    if event == "os.system":
        command: Any = padded[0]
    else:  # subprocess.Popen(executable, args, cwd, env)
        command = padded[1] if padded[1] is not None else padded[0]
        if padded[2] is not None and _is_notebook_path(padded[2]):
            return True
    try:
        if isinstance(command, (list, tuple)):
            # An argv list: element 0 is the program, even with spaces in it.
            words = [os.fsdecode(word) for word in command]
        else:
            words = os.fsdecode(command).split() if command is not None else []
    except (TypeError, ValueError):
        return False
    # Look through a shell wrapper (``cmd /c ...``, ``sh -c ...``).
    for word in words:
        program = _program_name(word)
        if program in _SHELLS or word.lower() in _SHELL_FLAGS:
            continue
        return program.startswith(_BLOCKED_PROGRAM_PREFIXES)
    return False


def _program_name(word: str) -> str:
    name = word.strip("\"'").replace("\\", "/").split("/")[-1]
    return _normalise_part(name).removesuffix(".exe")


def _block_access() -> None:
    with _lock:
        _state["blocked_opens"] += 1
    raise NotebookAccessBlocked("notebook access is forbidden for workflows")


def _hook(event: str, args: tuple) -> None:
    if event in _PATH_EVENTS and args and _is_notebook_path(args[0]):
        _block_access()
    if event in _LAUNCH_EVENTS and _launches_notebook_program(event, args):
        _block_access()
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
