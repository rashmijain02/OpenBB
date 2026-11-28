"""Rendered wrapper end to end: real child processes, no DB, no network (#1344).

The wrapper is stdlib-only and launches the pinned venv python as an isolated
child. These tests use the real ``.venv_portfolio`` (the interpreter running
the tests) as the map's venv, so the child really is that venv's python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from portfolio_utils.fmp_sync import locking, render

from .conftest import DISPOSABLE_DB, FIXTURES_1338, PORTFOLIO_UTILS_ROOT
from .test_render import rig  # noqa: F401  (fixture)

GENERIC = "fmp_cache_prices: integrity check failed"
WORKTREE = PORTFOLIO_UTILS_ROOT.parents[2]
PROFILE = FIXTURES_1338 / "profiles" / "synthetic-ok.yaml"
WINDOWS = sys.platform == "win32"


@pytest.fixture
def real(rig):  # noqa: F811
    """The T03 rig, pointed at the real venv and this checkout's source."""

    def write(**over):
        base = {
            "interpreter": sys.prefix,
            "source_root": str(WORKTREE),
            "profile_path": str(PROFILE),
        }
        return rig["write"](**{**base, **over})

    write()
    return {**rig, "write": write}


def _foreign_python() -> str:
    """Another minor version if the launcher has one (Hermes runs 3.14), else base."""
    mine = f"{sys.version_info[0]}.{sys.version_info[1]}"
    launcher = shutil.which("py")
    for minor in ("3.14", "3.13"):
        if launcher and minor != mine:
            found = subprocess.run(  # noqa: S603
                [launcher, f"-{minor}", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                check=False,
            )
            if found.returncode == 0 and found.stdout.strip():
                return found.stdout.strip()
    return getattr(sys, "_base_executable", "") or sys.executable


def _script(rig):  # noqa: F811
    return rig["home"] / "scripts" / render.WRAPPER_NAME


def _run(script, env, python_exe, *extra, cwd=None):
    return subprocess.run(  # noqa: S603
        [python_exe, str(script), *extra],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=180,
        check=False,
    )


def test_wrapper_exit0_for_recorded_unhealthy_outcome(real, child_env, python_exe):
    real["write"](limits=None)  # execute with no limits -> BLOCKED_POLICY, no I/O
    render.apply_files(real["map"], real["home"])
    done = _run(_script(real), child_env, python_exe)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["outcome"] == "BLOCKED_POLICY" and payload["exit"] == 40
    root = render.effective_state_root(real["map"])
    assert (root / "history.jsonl").exists() and (root / "status.json").exists()
    again = _run(_script(real), child_env, python_exe)  # unchanged -> silent
    assert again.returncode == 0 and again.stdout == ""


def test_wrapper_under_a_foreign_python_reaches_past_the_process_layer(
    real, child_env, python_exe
):
    """Limits set: the venv child passes process + ABI and stops at module origin.

    ``source_sha`` is fake, so admission blocks at the module-origin layer, which
    runs before any config, database or FMP step (no MySQL, no socket).
    """
    render.apply_files(real["map"], real["home"])
    # Run the wrapper under a python that is NOT the venv, as Hermes does.
    foreign = _foreign_python()
    child_env.pop("__PYVENV_LAUNCHER__", None)  # set only because tests run in the venv
    done = _run(_script(real), child_env, foreign)
    assert done.returncode == 0, done.stdout
    payload = json.loads(done.stdout)
    assert payload["outcome"] == "BLOCKED_MODULE_ORIGIN", payload
    assert payload["failed_layer"] == "module_origin"


def test_planted_modules_next_to_wrapper_are_never_imported(
    real, child_env, python_exe
):
    real["write"](limits=None)
    render.apply_files(real["map"], real["home"])
    scripts = _script(real).parent
    marker = real["tmp"] / "planted.marker"
    for name in ("hashlib", "json", "re", "subprocess", "portfolio_utils"):
        (scripts / f"{name}.py").write_text(
            f"open({str(marker)!r}, 'a').write({name!r})\n", encoding="utf-8"
        )
    child_env["PYTHONPATH"] = f"{scripts}{';' if WINDOWS else ':'}" + child_env.get(
        "PYTHONPATH", ""
    )
    done = _run(_script(real), child_env, python_exe, cwd=scripts)
    assert not marker.exists(), marker.read_text("utf-8")
    assert json.loads(done.stdout)["outcome"] == "BLOCKED_POLICY"


def test_wrapper_hash_mismatch_generic_nonzero(real, child_env, python_exe):
    render.apply_files(real["map"], real["home"])
    script = _script(real)
    script.write_text(script.read_text("utf-8") + "\n# tamper\n", encoding="utf-8")
    done = _run(script, child_env, python_exe)
    assert done.returncode == 3
    assert done.stdout.strip() == GENERIC
    assert str(real["tmp"]) not in done.stdout + done.stderr


def test_wrapper_map_drift_generic_nonzero(real, child_env, python_exe):
    render.apply_files(real["map"], real["home"])
    real["write"](target="obb_disposable_00000000")  # map changed after render
    done = _run(_script(real), child_env, python_exe)
    assert done.returncode == 3
    assert done.stdout.strip() == GENERIC


def test_wrapper_ignores_argv_and_cron_env(real, child_env, python_exe):
    real["write"](limits=None)
    render.apply_files(real["map"], real["home"])
    child_env["FMP_SYNC_MAP"] = "elsewhere.json"
    done = _run(_script(real), child_env, python_exe, "--map", "evil.json")
    assert done.returncode == 0
    assert json.loads(done.stdout)["outcome"] == "BLOCKED_POLICY"


def test_invalid_child_output_is_never_relayed(rig, monkeypatch):  # noqa: F811
    """Only a well-formed counts-only outcome line passes the relay check."""
    monkeypatch.setattr(sys, "path", sys.path[:])  # the wrapper scrubs sys.path
    namespace: dict = {"__file__": "x"}
    text = render.render_wrapper(rig["map"])
    exec(compile(text, "wrapper", "exec"), namespace)  # noqa: S102
    valid = namespace["valid_line"]
    good = {
        "op": "prices",
        "mode": "execute",
        "run_id": "a" * 32,
        "outcome": "OK",
        "exit": 0,
        "data_status": "UNVALIDATED",
        "failed_layer": None,
        "findings": ["PRIOR_RUN_INTERRUPTED"],
        "counts": {"requested": 1},
        "sent": 1,
    }
    assert valid(json.dumps(good))
    assert valid(json.dumps({"op": "prices", "outcome": "X_Y", "findings": []}))
    for bad in (
        {**good, "symbol": "AAPL"},
        {**good, "findings": ["C:\\Users\\someone"]},
        {**good, "outcome": "ok lower"},
        {**good, "exit": 1},
        {**good, "op": "other"},
    ):
        assert not valid(json.dumps(bad)), bad
    assert not valid("Traceback (most recent call last):")


# ------------------------------------------------------------------ process tree

FAKE_MAIN = """
import msvcrt, os, sys, time
fd = os.open({lock!r}, os.O_RDWR | os.O_CREAT)
msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
open({ready!r}, "w").write(str(os.getpid()))
time.sleep(120)
"""


def _fake_source(tmp: Path, lock: Path, ready: Path) -> Path:
    src = tmp / "fake_src"
    pkg = src / "openbb_platform" / "tools" / "portfolio_utils" / "portfolio_utils"
    (pkg / "fmp_sync").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "fmp_sync" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "fmp_sync" / "__main__.py").write_text(
        FAKE_MAIN.format(lock=str(lock), ready=str(ready)), encoding="utf-8"
    )
    return src


def _pid_alive(pid: int) -> bool:
    return locking._pid_alive(pid)  # pylint: disable=protected-access


def _start_holding_wrapper(real, child_env, python_exe):
    root = render.effective_state_root(real["map"])
    lock = locking.lock_path(
        locking.resolve_lock_database(DISPOSABLE_DB),
        locking.validate_state_root(root),
    )
    lock.parent.mkdir(parents=True, exist_ok=True)
    ready = real["tmp"] / "ready.pid"
    real["write"](source_root=str(_fake_source(real["tmp"], lock, ready)))
    render.apply_files(real["map"], real["home"])
    proc = subprocess.Popen(  # noqa: S603
        [python_exe, str(_script(real))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
    )
    end = time.monotonic() + 60
    while not ready.exists() and proc.poll() is None and time.monotonic() < end:
        time.sleep(0.05)
    assert ready.exists(), proc.communicate(timeout=30)
    time.sleep(0.2)
    holder_pid = int(ready.read_text("utf-8"))
    with pytest.raises(locking.LockBusy):
        with locking.target_lock(DISPOSABLE_DB, root=root, entrypoint="test"):
            pass
    return proc, holder_pid, root


def _lock_freed(root: Path, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with locking.target_lock(DISPOSABLE_DB, root=root, entrypoint="test"):
                return True
        except locking.LockBusy:
            time.sleep(0.1)
    return False


@pytest.mark.skipif(not WINDOWS, reason="Windows job object")
def test_killing_the_wrapper_kills_the_child_and_frees_the_lock(
    real, child_env, python_exe
):
    proc, holder_pid, root = _start_holding_wrapper(real, child_env, python_exe)
    try:
        proc.kill()  # TerminateProcess on the wrapper only, like a hard kill
        proc.communicate(timeout=30)
        assert _lock_freed(root), "the venv child outlived the wrapper"
        assert not _pid_alive(holder_pid)
    finally:
        if _pid_alive(holder_pid):
            subprocess.run(  # noqa: S603, S607
                ["taskkill", "/PID", str(holder_pid), "/F"],
                capture_output=True,
                check=False,
            )


@pytest.mark.skipif(not WINDOWS, reason="Windows job object")
def test_wrapper_deadline_terminates_the_job(real, child_env, python_exe, monkeypatch):
    monkeypatch.setattr(render, "WRAPPER_DEADLINE_S", 4.0)
    proc, holder_pid, root = _start_holding_wrapper(real, child_env, python_exe)
    try:
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 5
        assert out.strip() == "fmp_cache_prices: deadline exceeded"
        assert _lock_freed(root)
        assert not _pid_alive(holder_pid)
    finally:
        if proc.poll() is None:
            proc.kill()
        if _pid_alive(holder_pid):
            subprocess.run(  # noqa: S603, S607
                ["taskkill", "/PID", str(holder_pid), "/F"],
                capture_output=True,
                check=False,
            )


# ------------------------------------------------------------------ ctypes contract


def _load_wrapper(script: Path, monkeypatch) -> dict:
    """Exec an applied wrapper in-process (``__name__`` is not ``__main__``)."""
    monkeypatch.setattr(sys, "path", sys.path[:])  # the wrapper scrubs sys.path
    namespace: dict = {"__file__": str(script), "__name__": "wrapper_under_test"}
    exec(compile(script.read_text("utf-8"), str(script), "exec"), namespace)  # noqa: S102
    return namespace


@pytest.mark.skipif(not WINDOWS, reason="Windows job object")
def test_resume_thread_failure_is_detected(real, monkeypatch):
    """ResumeThread returns DWORD (u32): (DWORD)-1 must compare as 0xFFFFFFFF."""
    render.apply_files(real["map"], real["home"])
    namespace = _load_wrapper(_script(real), monkeypatch)
    job = namespace["_WinJob"]()
    try:
        assert job.k32.ResumeThread(None) == 0xFFFFFFFF  # NULL handle fails
    finally:
        job.close()


@pytest.mark.skipif(not WINDOWS, reason="Windows job object")
def test_failed_resume_terminates_the_job_and_exits_internal(real, monkeypatch, capfd):
    """A failed ResumeThread kills the suspended child and exits "internal"."""
    render.apply_files(real["map"], real["home"])
    namespace = _load_wrapper(_script(real), monkeypatch)
    namespace["DEADLINE_S"] = 5.0  # a missed failure would otherwise hang
    seen: list = []
    base = namespace["_WinJob"]

    class _FailingResume(base):  # type: ignore[misc, valid-type]
        def __init__(self):
            super().__init__()
            real_resume = self.k32.ResumeThread
            self.k32.ResumeThread = lambda _thread: real_resume(None)

        def adopt(self, proc):
            seen.append(proc)
            super().adopt(proc)

    namespace["_WinJob"] = _FailingResume
    code = namespace["main"]()
    out = capfd.readouterr().out
    assert code == 4
    assert out.strip() == "fmp_cache_prices: internal error"
    assert seen and seen[0].poll() is not None, "suspended child left behind"
