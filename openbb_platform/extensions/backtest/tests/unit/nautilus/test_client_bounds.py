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
