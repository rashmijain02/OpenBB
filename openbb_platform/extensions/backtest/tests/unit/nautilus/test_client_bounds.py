"""Facade client bounds (#1355 T03): deadline tree-kill, memory, env, fail-fast.

Uses the fake workers in ``fixtures/``; never imports nautilus_trader and never
opens a socket.
"""

# ruff: noqa: D103

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest
from openbb_backtest.adapters.nautilus import (
    bounds,
    client as client_mod,
)
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError

FIX = Path(__file__).parent / "fixtures"
FAKE = str(FIX / "fake_worker.py")
FACTS = str(FIX / "facts_native_ok.json")
SENTINEL = "SENTINEL-VALUE-7f3a"
MIB = 1024 * 1024


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        k32.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_wall_time_kill_kills_process_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    cmd = [sys.executable, FAKE, FACTS, "--hang-spawn", str(pidfile)]
    start = time.monotonic()
    with (
        client_mod.WorkerClient(cmd, timeout=4) as wc,
        pytest.raises(ProtocolError) as info,
    ):
        wc.describe()
    assert info.value.code is ErrorCode.PROCESS
    assert "deadline" in info.value.message
    assert time.monotonic() - start < 30
    grandchild = int(pidfile.read_text(encoding="utf-8"))
    for _ in range(50):
        if not _pid_alive(grandchild):
            break
        time.sleep(0.2)
    assert not _pid_alive(grandchild), "grandchild survived the deadline kill"


_ALLOC = (
    "import sys; sys.stdin.readline(); b = bytearray(int(sys.argv[1])); "
    "print('ALLOCATED', flush=True)"
)


def _alloc_child(memory_bytes):
    pb = bounds.ProcessBounds(memory_bytes=memory_bytes)
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _ALLOC, str(512 * MIB)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **pb.popen_kwargs(),
    )
    try:
        pb.attach(proc)
        out, err = proc.communicate(b"go\n", timeout=60)
    finally:
        pb.close()
    return proc.returncode, out, err


def test_memory_limit_job_object_stops_oversized_allocation():
    code, out, _ = _alloc_child(None)  # control: the allocation itself is fine
    assert code == 0 and b"ALLOCATED" in out
    code, out, err = _alloc_child(128 * MIB)
    assert code != 0 and b"ALLOCATED" not in out
    assert b"MemoryError" in err


def test_client_memory_limit_fails_worker_allocation():
    cmd = [sys.executable, FAKE, FACTS, "--alloc", str(512 * MIB)]
    with client_mod.WorkerClient(cmd, timeout=60) as wc:  # control: no limit
        assert wc.describe().nautilus_version
    with (
        client_mod.WorkerClient(cmd, timeout=60, memory_bytes=128 * MIB) as wc,
        pytest.raises(ProtocolError) as info,
    ):
        wc.describe()
    assert info.value.code is ErrorCode.PROCESS


def test_default_child_env_is_minimal(monkeypatch):
    monkeypatch.setenv("MY_BROKER_API_KEY", SENTINEL)
    monkeypatch.setenv("IB_ACCOUNT_ID", SENTINEL)
    monkeypatch.setenv("OPENBB_NAUTILUS_DATA_ROOT", "x")
    env = client_mod.worker_env(os.environ)
    assert "MY_BROKER_API_KEY" not in env and "IB_ACCOUNT_ID" not in env
    assert env["OPENBB_NAUTILUS_DATA_ROOT"] == "x"
    assert SENTINEL not in json.dumps(env)


def test_default_env_lets_real_worker_start_despite_parent_credentials(monkeypatch):
    """Parent has broker-shaped vars; the child gets the minimal env and serves."""
    monkeypatch.setenv("MY_BROKER_API_KEY", SENTINEL)
    worker_root = str(Path(client_mod.protocol.__file__).resolve().parents[1])
    cmd = [
        sys.executable,
        "-c",
        f"import sys; sys.path.insert(0, {worker_root!r}); "
        "from openbb_nautilus_worker.__main__ import main; raise SystemExit(main([]))",
    ]
    with (
        client_mod.WorkerClient(cmd, timeout=60) as wc,
        pytest.raises(ProtocolError) as info,
    ):
        wc.describe()
    # not ``egress``: the scrubbed env carried no credential-shaped names
    assert info.value.code is ErrorCode.MODULE_ORIGIN


def test_explicit_env_with_credentials_is_refused_by_worker(monkeypatch):
    worker_root = str(Path(client_mod.protocol.__file__).resolve().parents[1])
    cmd = [
        sys.executable,
        "-c",
        f"import sys; sys.path.insert(0, {worker_root!r}); "
        "from openbb_nautilus_worker.__main__ import main; raise SystemExit(main([]))",
    ]
    env = {**client_mod.worker_env(os.environ), "TWS_PASSWORD": SENTINEL}
    with (
        client_mod.WorkerClient(cmd, timeout=60, env=env) as wc,
        pytest.raises(ProtocolError) as info,
    ):
        wc.describe()
    assert info.value.code is ErrorCode.EGRESS
    assert "TWS_PASSWORD" in info.value.message
    assert SENTINEL not in info.value.message


def test_client_screens_run_request_before_sending():
    cmd = [sys.executable, FAKE, FACTS]
    with client_mod.WorkerClient(cmd, timeout=60) as wc:
        with pytest.raises(ProtocolError) as info:
            wc.run(
                {
                    "dataset_id": "a" * 64,
                    "strategy": "buy_and_hold",
                    "api_key": SENTINEL,
                }
            )
        assert info.value.code is ErrorCode.EGRESS
        assert wc.sent_requests == 0
        assert wc.describe().nautilus_version  # session still usable


def test_docker_command_carries_memory_bound(monkeypatch):
    monkeypatch.setenv("OPENBB_NAUTILUS_IMAGE", "img@sha256:" + "0" * 64)
    cmd = client_mod.worker_command("docker", os.environ, memory_mb=2048)
    assert cmd[cmd.index("--memory") + 1] == "2048m"
    assert cmd[cmd.index("--network") + 1] == "none"


# --- CODE-3: docker hardening, container kill, native suspended-start -------

IMAGE = "img@sha256:" + "0" * 64
WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Job Object semantics")


def _docker_env(monkeypatch, data_root):
    monkeypatch.setenv("OPENBB_NAUTILUS_IMAGE", IMAGE)
    monkeypatch.setenv("OPENBB_NAUTILUS_DATA_ROOT", str(data_root))
    monkeypatch.setattr(client_mod.secrets, "token_hex", lambda _n=None: "ab" * 8)


def test_docker_command_exact_argv_is_hardened(monkeypatch, tmp_path):
    _docker_env(monkeypatch, tmp_path)
    cmd = client_mod.worker_command("docker", os.environ)
    assert cmd == [
        *("docker", "run", "--rm", "-i", "--name", "hfp-nautilus-" + "ab" * 8),
        *("--network", "none", "--read-only", "--cap-drop", "ALL"),
        *("--security-opt", "no-new-privileges"),
        *("--memory", "4096m", "--cpus", "2", "--pids-limit", "256"),
        *("--tmpfs", "/tmp"),  # noqa: S108
        *("-v", f"{tmp_path}:/data:ro"),
        *("-v", f"{tmp_path / 'runs'}:/data/runs"),  # heavy-job lock dir is rw
        *("-e", "OPENBB_NAUTILUS_DATA_ROOT=/data"),
        *("-e", "GPG_KEY="),
        IMAGE,
    ]


def test_docker_command_overrides_and_catalog_build_mount(monkeypatch, tmp_path):
    _docker_env(monkeypatch, tmp_path)
    cmd = client_mod.worker_command(
        "docker", os.environ, memory_mb=1024, cpus=1.5, build_catalog=True
    )
    assert cmd[cmd.index("--memory") + 1] == "1024m"
    assert cmd[cmd.index("--cpus") + 1] == "1.5"
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert mounts == [
        f"{tmp_path}:/data:ro",
        f"{tmp_path / 'runs'}:/data/runs",
        f"{tmp_path / 'catalogs'}:/data/catalogs",  # only runs/ + catalogs/ are rw
    ]


def test_runs_dir_is_writable_for_run_and_build_catalog(monkeypatch, tmp_path):
    """/data is ro, so the lock dir runs/ must be an rw mount on every call."""
    _docker_env(monkeypatch, tmp_path)
    for build in (False, True):
        cmd = client_mod.worker_command("docker", os.environ, build_catalog=build)
        mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
        assert f"{tmp_path / 'runs'}:/data/runs" in mounts
        assert f"{tmp_path}:/data:ro" in mounts
        assert mounts.index(f"{tmp_path}:/data:ro") < mounts.index(
            f"{tmp_path / 'runs'}:/data/runs"
        )


def test_docker_command_names_are_random_per_call(monkeypatch):
    monkeypatch.setenv("OPENBB_NAUTILUS_IMAGE", IMAGE)
    monkeypatch.delenv("OPENBB_NAUTILUS_DATA_ROOT", raising=False)
    names = {client_mod.worker_command("docker", os.environ)[5] for _ in range(3)}
    assert len(names) == 3 and all(n.startswith("hfp-nautilus-") for n in names)


def test_deadline_kill_runs_docker_kill_with_the_container_name(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        client_mod.subprocess,
        "run",
        lambda argv, **kw: calls.append((argv, kw)),
    )
    cmd = [sys.executable, FAKE, FACTS, "--hang-spawn", str(tmp_path / "x.pid")]
    with (
        client_mod.WorkerClient(
            cmd, timeout=3, container_name="hfp-nautilus-feedface"
        ) as wc,
        pytest.raises(ProtocolError) as info,
    ):
        wc.describe()
    assert "deadline" in info.value.message
    assert [a for a, _ in calls] == [["docker", "kill", "hfp-nautilus-feedface"]]
    assert 0 < calls[0][1]["timeout"] <= 30  # bounded


def test_container_name_is_taken_from_the_docker_command(monkeypatch, tmp_path):
    _docker_env(monkeypatch, tmp_path)
    cmd = client_mod.worker_command("docker", os.environ)
    assert client_mod.docker_container_name(cmd) == "hfp-nautilus-" + "ab" * 8
    assert client_mod.docker_container_name([sys.executable, FAKE]) is None


def test_clean_shutdown_does_not_docker_kill(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_mod.subprocess, "run", lambda argv, **kw: calls.append(argv)
    )
    cmd = [sys.executable, FAKE, FACTS]
    with client_mod.WorkerClient(cmd, timeout=30, container_name="hfp-nautilus-x"):
        pass
    assert calls == []


def test_native_default_memory_limit_is_4096_mib():
    assert client_mod.DEFAULT_MEMORY_BYTES == 4096 * MIB
    wc = client_mod.WorkerClient([sys.executable, FAKE, FACTS])
    assert wc._memory == 4096 * MIB  # pylint: disable=protected-access
    assert (
        client_mod.WorkerClient([sys.executable, "x"], memory_bytes=None)._memory
        is None  # pylint: disable=protected-access
    )
    docker = client_mod.WorkerClient(["docker", "run", "--name", "n", "img"])
    assert docker._memory is None  # pylint: disable=protected-access


def _slow_attach(monkeypatch, seconds=1.5):
    real = bounds.ProcessBounds.attach

    def attach(self, proc):
        time.sleep(seconds)  # a child that is not suspended runs during this
        real(self, proc)

    monkeypatch.setattr(bounds.ProcessBounds, "attach", attach)


@WINDOWS_ONLY
def test_native_child_is_in_the_job_before_it_runs(monkeypatch, tmp_path):
    _slow_attach(monkeypatch)
    report = tmp_path / "start.txt"
    cmd = [
        *(sys.executable, FAKE, FACTS),
        *("--alloc-at-start", str(300 * MIB), "--start-report", str(report)),
    ]
    with client_mod.WorkerClient(cmd, timeout=60, memory_bytes=160 * MIB) as wc:
        assert wc.describe().nautilus_version
    # the 160 MiB job limit was already live when the child's first line ran
    assert report.read_text(encoding="utf-8") == "limited"


@WINDOWS_ONLY
def test_failed_resume_terminates_the_job_and_raises(monkeypatch):
    spawned = []
    real_popen = subprocess.Popen

    def spy(*a, **kw):
        proc = real_popen(*a, **kw)
        spawned.append(proc)
        return proc

    def boom(self, _proc):
        raise OSError(5, "ResumeThread failed")

    monkeypatch.setattr(client_mod.subprocess, "Popen", spy)
    monkeypatch.setattr(bounds.ProcessBounds, "_resume_main_thread", boom)
    # bounds level: attach itself terminates the job (no client cleanup involved)
    pb = bounds.ProcessBounds(memory_bytes=None)
    proc = spy(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        **pb.popen_kwargs(),
    )
    with pytest.raises(OSError, match="ResumeThread"):
        pb.attach(proc)
    for _ in range(50):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    assert proc.poll() is not None, "suspended child survived a failed resume"
    pb.close()
    # client level: the failure surfaces as a PROCESS error, child dead
    with pytest.raises(ProtocolError) as info:
        client_mod.WorkerClient([sys.executable, FAKE, FACTS]).__enter__()
    assert info.value.code is ErrorCode.PROCESS
    assert all(p.poll() is not None for p in spawned)


class _FailingResume:
    """kernel32 proxy whose ``ResumeThread`` reports failure (0xFFFFFFFF)."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @staticmethod
    def ResumeThread(_handle):  # noqa: N802
        return 0xFFFFFFFF


@WINDOWS_ONLY
def test_resume_thread_failure_value_is_detected_and_job_terminated():
    pb = bounds.ProcessBounds(memory_bytes=None)
    assert (
        pb._k32.ResumeThread.restype is wintypes.DWORD
    )  # pylint: disable=protected-access
    pb._k32 = _FailingResume(pb._k32)  # pylint: disable=protected-access
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        **pb.popen_kwargs(),
    )
    with pytest.raises(OSError, match="ResumeThread"):
        pb.attach(proc)
    for _ in range(50):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    assert proc.poll() is not None
    pb.close()
