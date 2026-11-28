"""One cross-process lock per target database for every price-warming entry point (#1344).

The manual CLI, the openbb-jobs handler and the Hermes cron dispatcher all reach
``run_position_history_warm``; its guard and the outer callers use the same
lock file ``<root>/fmp-sync.<database-lowercase>.lock``.

Semantics
---------
* Non-blocking only: contention raises :class:`LockBusy` immediately (the run is
  reported ``SKIPPED_BUSY``); there is no wait loop and no second worker.
* Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` on a handle opened with
  ``O_NOINHERIT``. The byte-range lock belongs to the handle and the OS releases
  it on handle close or process death (including ``TerminateProcess``).
  Elsewhere: ``fcntl.flock(LOCK_EX | LOCK_NB)``.
* The lock file is never deleted (unlink races break exclusion).
* Reentrant per thread by target database; another thread of the same process is
  busy; holding one target while asking for another is :class:`LockConflict`.
* ``<lock>.owner.json`` is diagnostic only: a previous owner without an end
  marker yields ``PRIOR_RUN_INTERRUPTED``; a live holder older than twice the
  deadline yields ``LOCK_HELD_OVERDUE``. No PID kill, no stale override.
* Roots on UNC paths, ``DRIVE_REMOTE`` drives or inside a git checkout are
  refused: network locks are not mutual exclusion.
* Writers that do not use this guard (Workspace, MCP, other hosts) are not
  excluded; that is a standing limitation, not a claim.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import msvcrt
else:  # pragma: no cover - exercised off Windows only
    import fcntl

STATE_ROOT_ENV = "FMP_SYNC_STATE_ROOT"
DRIVE_REMOTE = 4  # GetDriveTypeW
DEFAULT_DEADLINE_S = 900.0
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

PRIOR_RUN_INTERRUPTED = "PRIOR_RUN_INTERRUPTED"
LOCK_HELD_OVERDUE = "LOCK_HELD_OVERDUE"
OWNER_WRITE_FAILED = "OWNER_WRITE_FAILED"


class LockBusy(RuntimeError):
    """Another process or thread holds the target lock (outcome ``SKIPPED_BUSY``)."""

    def __init__(self, database: str, findings: tuple[str, ...] = ()):
        super().__init__(f"fmp-sync lock busy for target {database}")
        self.database = database
        self.findings = findings


class LockConflict(RuntimeError):
    """This thread already holds a lock for a different target (programming error)."""


class LockRootRejected(ValueError):
    """The lock/state root cannot provide mutual exclusion."""


@dataclass
class LockHandle:
    """What a caller learns from holding the lock."""

    database: str
    path: Path
    run_id: str
    reentered: bool = False
    findings: tuple[str, ...] = ()


@dataclass
class _Held:
    database: str
    path: Path
    fd: int
    run_id: str
    depth: int = 0
    findings: tuple[str, ...] = ()
    thread_id: int = field(default_factory=threading.get_ident)


_REGISTRY_LOCK = threading.Lock()
_KEY_LOCKS: dict[str, threading.Lock] = {}
_HELD: dict[str, _Held] = {}


# ------------------------------------------------------------------ roots


def default_state_root() -> Path:
    r"""``FMP_SYNC_STATE_ROOT`` else ``%LOCALAPPDATA%\\OpenBB\\fmp-sync`` (D3)."""
    explicit = os.environ.get(STATE_ROOT_ENV)
    if explicit:
        return Path(explicit)
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "OpenBB" / "fmp-sync"
    return Path.home() / ".local" / "state" / "openbb" / "fmp-sync"  # pragma: no cover


def _drive_type(root: str) -> int:
    r"""Return ``GetDriveTypeW`` for a drive root such as ``C:\\`` (0 off Windows)."""
    if not IS_WINDOWS:  # pragma: no cover
        return 0
    import ctypes  # pylint: disable=import-outside-toplevel

    return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))


def _inside_git_checkout(path: Path) -> bool:
    return any((candidate / ".git").exists() for candidate in (path, *path.parents))


def validate_state_root(root: Path) -> Path:
    """Return the resolved root, or raise :class:`LockRootRejected`."""
    raw = str(root)
    if raw.startswith(("\\\\", "//")):
        raise LockRootRejected("lock root on a network (UNC) path is refused")
    resolved = Path(os.path.abspath(raw))
    if IS_WINDOWS:
        drive = resolved.drive
        if drive.startswith("\\\\"):
            raise LockRootRejected("lock root on a network (UNC) path is refused")
        if drive and _drive_type(drive + "\\") == DRIVE_REMOTE:
            raise LockRootRejected("lock root on a network drive is refused")
    resolved = resolved.resolve()
    if _inside_git_checkout(resolved):
        raise LockRootRejected("lock root inside a git checkout is refused")
    return resolved


# ------------------------------------------------------------------ target


def _normalize(database: str) -> str:
    if not isinstance(database, str) or not _IDENTIFIER.match(database):
        raise ValueError("target database is not a safe identifier")
    return database.lower()


def resolve_lock_database(database: str | None) -> str:
    """Explicit ``database`` else the DB the fmp_cached settings/env resolve to.

    Resolution reuses #1338's ``provenance.resolve_fmp_cached_database`` (lazy,
    D9). When ``openbb_agents`` is not importable (it is not installed in
    ``.venv_portfolio``) the provider's own ``DatabaseConfig`` is read instead;
    it only reads settings/env and opens no connection.
    """
    if database:
        return _normalize(database)
    try:
        # pylint: disable=import-outside-toplevel
        from openbb_agents.hermes_integration import provenance

        resolved = provenance.resolve_fmp_cached_database(
            provenance.default_settings_path(), os.environ
        ).database
    except ImportError:
        # pylint: disable=import-outside-toplevel
        from openbb_fmp_cached.utils.database import DatabaseConfig

        resolved = str(DatabaseConfig().config["database"])
    return _normalize(resolved)


def lock_path(database: str, root: Path) -> Path:
    """``<root>/fmp-sync.<database-lowercase>.lock``."""
    return Path(root) / f"fmp-sync.{_normalize(database)}.lock"


# ------------------------------------------------------------------ OS lock


def _os_try_lock(fd: int) -> bool:
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        if IS_WINDOWS:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def _os_unlock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    with contextlib.suppress(OSError):
        if IS_WINDOWS:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _open_lock_file(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


# ------------------------------------------------------------------ owner file


def _owner_path(path: Path) -> Path:
    return path.with_name(path.name + ".owner.json")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_owner(path: Path) -> dict | None:
    try:
        data = json.loads(_owner_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_owner(path: Path, data: dict) -> bool:
    target = _owner_path(path)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
    return True


def _overdue(owner: dict | None, deadline_s: float) -> bool:
    if not owner or owner.get("ended_utc"):
        return False
    try:
        started = datetime.fromisoformat(str(owner["started_utc"]))
    except (KeyError, ValueError):
        return False
    return (_utcnow() - started).total_seconds() >= 2 * deadline_s


# ------------------------------------------------------------------ public API


def _held_by_this_thread() -> _Held | None:
    me = threading.get_ident()
    return next((h for h in _HELD.values() if h.thread_id == me), None)


@contextlib.contextmanager
def target_lock(
    database: str | None,
    *,
    root: Path | None = None,
    entrypoint: str,
    run_id: str | None = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
) -> Iterator[LockHandle]:
    """Hold the target lock for ``database`` (``None`` = resolved default target)."""
    target = resolve_lock_database(database)
    mine = _held_by_this_thread()
    if mine is not None:
        if mine.database != target:
            raise LockConflict("already holding the fmp-sync lock for another target")
        mine.depth += 1
        try:
            yield LockHandle(target, mine.path, mine.run_id, True, mine.findings)
        finally:
            mine.depth -= 1
        return

    path = lock_path(target, validate_state_root(root or default_state_root()))
    key = str(path).lower()
    with _REGISTRY_LOCK:
        key_lock = _KEY_LOCKS.setdefault(key, threading.Lock())
    if not key_lock.acquire(blocking=False):
        raise LockBusy(target)
    try:
        fd = _open_lock_file(path)
        if not _os_try_lock(fd):
            os.close(fd)
            owner = _read_owner(path)
            findings = (LOCK_HELD_OVERDUE,) if _overdue(owner, deadline_s) else ()
            raise LockBusy(target, findings)
        held = _Held(target, path, fd, run_id or uuid.uuid4().hex, depth=1)
        previous = _read_owner(path)
        findings_list = []
        if previous is not None and not previous.get("ended_utc"):
            findings_list.append(PRIOR_RUN_INTERRUPTED)
        owner = {
            "run_id": held.run_id,
            "pid": os.getpid(),
            "entrypoint": entrypoint,
            "started_utc": _utcnow().isoformat(),
            "ended_utc": None,
        }
        if not _write_owner(path, owner):
            findings_list.append(OWNER_WRITE_FAILED)
        held.findings = tuple(findings_list)
        _HELD[key] = held
        try:
            yield LockHandle(target, path, held.run_id, False, held.findings)
        finally:
            _HELD.pop(key, None)
            owner["ended_utc"] = _utcnow().isoformat()
            _write_owner(path, owner)
            _os_unlock(fd)
            os.close(fd)
    finally:
        key_lock.release()


def lock_status(
    database: str | None, *, root: Path | None = None
) -> Literal["free", "busy", "held"]:
    """Probe the lock without taking ownership (no owner file is written)."""
    target = resolve_lock_database(database)
    path = lock_path(target, validate_state_root(root or default_state_root()))
    key = str(path).lower()
    if key in _HELD:
        return "held"
    fd = _open_lock_file(path)
    try:
        if not _os_try_lock(fd):
            return "busy"
        _os_unlock(fd)
        return "free"
    finally:
        os.close(fd)
