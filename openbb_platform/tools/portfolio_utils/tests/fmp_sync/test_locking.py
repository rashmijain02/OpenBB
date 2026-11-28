"""Cross-process target lock shared by manual, openbb-jobs and cron runs (#1344-T01)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest
from portfolio_utils.fmp_sync import locking
from portfolio_utils.fmp_sync.locking import (
    LockBusy,
    LockConflict,
    LockRootRejected,
    lock_status,
    target_lock,
)

from .conftest import DISPOSABLE_DB, HELPERS


class Holder:
    """A real second interpreter holding the lock via ``helpers/hold_lock.py``."""

    def __init__(self, python_exe: str, env: dict, root: Path, database: str):
        self.root = root
        self.ready = root.parent / f"ready-{database}"
        self.release_file = root.parent / f"release-{database}"
        self.proc = subprocess.Popen(  # noqa: S603
            [
                python_exe,
                str(HELPERS / "hold_lock.py"),
                str(root),
                database,
                str(self.ready),
                str(self.release_file),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 60
        while not self.ready.exists():
            if self.proc.poll() is not None:
                _, err = self.proc.communicate()
                raise AssertionError(
                    f"holder exited early: {err.decode(errors='replace')}"
                )
            if time.monotonic() > deadline:
                self.proc.kill()
                raise AssertionError("holder never acquired the lock")
            time.sleep(0.05)

    def release(self) -> None:
        self.release_file.write_text("go", encoding="utf-8")
        self.proc.wait(timeout=30)

    @property
    def pid(self) -> int:
        """Pid of the interpreter that holds the lock (not a venv launcher)."""
        return int(self.ready.read_text(encoding="utf-8"))

    def kill(self) -> None:
        # TerminateProcess on the real holder: no cleanup code runs. The launcher
        # (if any) exits once its child is gone, so waiting on it waits for death.
        os.kill(self.pid, signal.SIGTERM)
        self.proc.wait(timeout=30)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=30)


@pytest.fixture
def state_root(tmp_path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def holder(python_exe, child_env, state_root):
    started: list[Holder] = []

    def _start(database: str = DISPOSABLE_DB) -> Holder:
        h = Holder(python_exe, child_env, state_root, database)
        started.append(h)
        return h

    yield _start
    for h in started:
        h.close()


def _try_in_child(python_exe, env, root, database):
    start = time.monotonic()
    proc = subprocess.run(  # noqa: S603
        [python_exe, str(HELPERS / "try_lock.py"), str(root), database],
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout.decode().strip(), time.monotonic() - start


def test_two_processes_one_skipped_busy(holder, python_exe, child_env, state_root):
    """A second real process is refused immediately (non-blocking), never waits."""
    h = holder()
    code, out, _ = _try_in_child(python_exe, child_env, state_root, DISPOSABLE_DB)
    assert (code, out) == (75, "busy")

    start = time.monotonic()
    with pytest.raises(LockBusy) as excinfo:
        with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test"):
            pass
    assert time.monotonic() - start < 2.0, "busy lock must be refused without waiting"
    assert excinfo.value.database == DISPOSABLE_DB
    assert lock_status(DISPOSABLE_DB, root=state_root) == "busy"

    h.release()
    code, out, _ = _try_in_child(python_exe, child_env, state_root, DISPOSABLE_DB)
    assert (code, out) == (0, "acquired")
    assert lock_status(DISPOSABLE_DB, root=state_root) == "free"


def test_lock_is_per_target_database(holder, state_root):
    """Different target DBs never exclude each other."""
    holder("obb_disposable_00000000")
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test") as handle:
        assert handle.path.name == f"fmp-sync.{DISPOSABLE_DB}.lock"


def test_lock_released_on_kill(holder, state_root):
    """OS releases the byte-range lock on process death; next run records recovery."""
    h = holder()
    h.kill()
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test") as handle:
        assert "PRIOR_RUN_INTERRUPTED" in handle.findings
    # A clean release leaves an end marker, so the next run reports no recovery.
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test") as handle:
        assert "PRIOR_RUN_INTERRUPTED" not in handle.findings


def test_owner_metadata_written_and_overdue_holder_flagged(holder, state_root):
    h = holder()
    owner_path = state_root / f"fmp-sync.{DISPOSABLE_DB}.lock.owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    # A venv launcher on Windows re-spawns the base interpreter, so the holder's
    # pid may differ from Popen.pid; it is never this process.
    assert owner["pid"] == h.pid != os.getpid()
    assert h.proc.poll() is None
    assert owner["entrypoint"] == "test_holder"
    assert owner["ended_utc"] is None
    assert set(owner) >= {"run_id", "pid", "entrypoint", "started_utc"}

    with pytest.raises(LockBusy) as excinfo:
        with target_lock(
            DISPOSABLE_DB, root=state_root, entrypoint="t", deadline_s=0.0
        ):
            pass
    assert "LOCK_HELD_OVERDUE" in excinfo.value.findings


def test_lock_file_never_deleted(state_root):
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test") as handle:
        path = handle.path
    assert path.exists(), "the lock file must never be unlinked"
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="test"):
        pass
    assert path.exists()
    assert sorted(p.name for p in state_root.iterdir()) == [
        f"fmp-sync.{DISPOSABLE_DB}.lock",
        f"fmp-sync.{DISPOSABLE_DB}.lock.owner.json",
    ]


def test_reentrant_same_process(state_root):
    """Same thread re-enters; another thread is busy; a second target conflicts."""
    with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="outer") as outer:
        # The inner guard (no explicit root) re-enters by database, not by path.
        with target_lock(DISPOSABLE_DB, entrypoint="inner") as inner:
            assert inner.reentered and not outer.reentered
            assert inner.path == outer.path

        seen: list[object] = []

        def _other_thread():
            try:
                with target_lock(DISPOSABLE_DB, root=state_root, entrypoint="thread"):
                    seen.append("acquired")
            except LockBusy:
                seen.append("busy")

        t = threading.Thread(target=_other_thread)
        t.start()
        t.join(10)
        assert seen == ["busy"]

        with pytest.raises(LockConflict):
            with target_lock(
                "obb_disposable_99999999", root=state_root, entrypoint="x"
            ):
                pass
    # Fully released after the outer context exits.
    assert lock_status(DISPOSABLE_DB, root=state_root) == "free"


def test_rejects_invalid_database_identifier(state_root):
    with pytest.raises(ValueError):
        with target_lock("../evil", root=state_root, entrypoint="x"):
            pass


def test_rejects_unc_and_repo_root(monkeypatch, tmp_path):
    with pytest.raises(LockRootRejected, match="network"):
        locking.validate_state_root(Path(r"\\server\share\fmp-sync"))
    with pytest.raises(LockRootRejected, match="network"):
        locking.validate_state_root(Path("//server/share/fmp-sync"))
    # Inside this git checkout (worktree or main): refused.
    with pytest.raises(LockRootRejected, match="git"):
        locking.validate_state_root(Path(__file__).resolve().parent / "state")
    # A DRIVE_REMOTE (mapped network) drive: refused.
    monkeypatch.setattr(locking, "_drive_type", lambda root: locking.DRIVE_REMOTE)
    with pytest.raises(LockRootRejected, match="network"):
        locking.validate_state_root(tmp_path / "state")
    monkeypatch.undo()
    assert locking.validate_state_root(tmp_path / "ok") == (tmp_path / "ok").resolve()


def test_default_root_is_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("FMP_SYNC_STATE_ROOT")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    root = locking.default_state_root()
    if locking.IS_WINDOWS:
        assert root == tmp_path / "lad" / "OpenBB" / "fmp-sync"
    monkeypatch.setenv("FMP_SYNC_STATE_ROOT", str(tmp_path / "explicit"))
    assert locking.default_state_root() == tmp_path / "explicit"


def test_resolves_implicit_target_from_settings(home_settings):
    """``database=None`` keys the lock by the DB the settings resolve to (#1338 helper)."""
    home_settings(DISPOSABLE_DB)
    assert locking.resolve_lock_database(None) == DISPOSABLE_DB
    assert locking.resolve_lock_database("Obb_Disposable_ABCDEF12") == DISPOSABLE_DB
