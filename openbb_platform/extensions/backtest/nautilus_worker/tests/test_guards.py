"""Worker guards (#1355 T03): env scrub, import guard, socket guard, bounds.

Import and socket guards are process-wide (audit hooks cannot be removed), so
those tests run in a child interpreter. No network is used: every connect is
refused before a packet is sent, and the control case only binds loopback.
"""

# ruff: noqa: D103

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from openbb_nautilus_worker import (
    __main__ as wm,
    guards,
    protocol as p,
)
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError

KEY = bytes(range(32))
SENTINEL = "SENTINEL-VALUE-7f3a"
WORKER_ROOT = str(Path(p.__file__).resolve().parents[1])
BROKER_NAMES = [
    "IB_ACCOUNT_ID",
    "TWS_PASSWORD",
    "IBKR_USERNAME",
    "ALPACA_API_KEY",
    "APCA_API_SECRET_KEY",
    "BINANCE_API_SECRET",
    "BYBIT_API_KEY",
    "DATABENTO_API_KEY",
    "TARDIS_API_KEY",
    "BETFAIR_USERNAME",
    "OKX_API_PASSPHRASE",
    "DYDX_MNEMONIC",
    "POLYMARKET_PK",
    "MY_SERVICE_API_KEY",
    "OTHER_SECRET",
    "GH_TOKEN",
    "lowercase_api_key",
]
BENIGN = {
    "PATH": "x",
    "SYSTEMROOT": "x",
    "OPENBB_NAUTILUS_DATA_ROOT": "x",
    "TOKENIZERS_PARALLELISM": "false",
    "SECRETARY_NAME": "x",
    "IBIS_HOME": "x",
    "NUMBER_OF_PROCESSORS": "8",
}


def _minimal_env(**extra: str) -> dict[str, str]:
    keep = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONPATH"] = WORKER_ROOT
    env.update(extra)
    return env


def _req(seq=1, op="describe", body=None):
    return p.encode_frame(p.sign_request(KEY, seq, op, body or {}))


# --- environment scrub ------------------------------------------------------------


def test_env_with_broker_credentials_is_refused():
    env = {**BENIGN, **{n: SENTINEL for n in BROKER_NAMES}}
    assert guards.broker_env_names(env) == sorted(BROKER_NAMES)
    assert guards.broker_env_names(BENIGN) == []
    with pytest.raises(ProtocolError) as info:
        guards.refuse_broker_env(env)
    assert info.value.code is ErrorCode.EGRESS
    assert "IB_ACCOUNT_ID" in info.value.message
    assert SENTINEL not in info.value.message


def test_env_allowlist_exempts_named_variables_only():
    env = {"MY_SERVICE_API_KEY": SENTINEL, "GH_TOKEN": SENTINEL}
    assert guards.broker_env_names(env, allow=frozenset({"GH_TOKEN"})) == [
        "MY_SERVICE_API_KEY"
    ]


def test_real_worker_refuses_to_serve_with_broker_env_names_only():
    """Entrypoint: first signed request is answered ``egress`` with names, exit 4."""
    env = _minimal_env(IB_ACCOUNT_ID=SENTINEL, MY_BROKER_API_KEY=SENTINEL)
    proc = subprocess.run(
        [sys.executable, "-m", "openbb_nautilus_worker"],
        input=p.encode_key_frame(KEY) + _req(seq=1),
        capture_output=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert proc.returncode == guards.EXIT_EGRESS, proc.stderr.decode()[:300]
    resp = p.verify_response(KEY, json.loads(proc.stdout.splitlines()[0]), 1)
    assert not resp.ok and resp.error.code == "egress"
    assert "IB_ACCOUNT_ID" in resp.error.message
    assert "MY_BROKER_API_KEY" in resp.error.message
    assert SENTINEL.encode() not in proc.stdout + proc.stderr


# --- import guard -----------------------------------------------------------------

_IMPORT_SCRIPT = textwrap.dedent("""
    import json, os, sys
    pkg = sys.argv[1]
    for rel in ("nautilus_trader/__init__.py", "nautilus_trader/live/__init__.py",
                "nautilus_trader/live/config.py", "nautilus_trader/live/node.py",
                "nautilus_trader/adapters/__init__.py",
                "nautilus_trader/adapters/interactive_brokers/__init__.py",
                "nautilus_trader/model/__init__.py", "ibapi/__init__.py",
                "databento/__init__.py"):
        path = os.path.join(pkg, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    sys.path.insert(0, pkg)
    from openbb_nautilus_worker import guards
    out = {}
    import ibapi  # imported BEFORE the guard: install must refuse
    try:
        guards.install_import_guard()
        out["preloaded"] = "installed"
    except guards.GuardError as exc:
        out["preloaded"] = exc.code.value
    del sys.modules["ibapi"]
    guards.install_import_guard()
    import importlib
    for name in ("nautilus_trader.model", "nautilus_trader.live.config",
                 "nautilus_trader.live.node", "nautilus_trader.adapters",
                 "nautilus_trader.adapters.interactive_brokers", "ibapi",
                 "databento"):
        try:
            importlib.import_module(name)
            out[name] = "ok"
        except ImportError as exc:
            out[name] = type(exc).__name__
    print(json.dumps(out))
    """)


def test_live_adapter_imports_blocked(tmp_path):
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _IMPORT_SCRIPT, str(tmp_path / "pkgs")],
        capture_output=True,
        timeout=60,
        check=False,
        env=_minimal_env(),
    )
    assert proc.returncode == 0, proc.stderr.decode()[-500:]
    out = json.loads(proc.stdout)
    assert out["preloaded"] == "egress"
    assert out["nautilus_trader.model"] == "ok"
    assert out["nautilus_trader.live.config"] == "ok"
    for name in (
        "nautilus_trader.live.node",
        "nautilus_trader.adapters",
        "nautilus_trader.adapters.interactive_brokers",
        "ibapi",
        "databento",
    ):
        assert out[name] == "BlockedImportError", name


# --- socket guard -----------------------------------------------------------------

_SOCKET_SCRIPT = textwrap.dedent("""
    import json, socket
    from openbb_nautilus_worker import guards
    out = {}
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.close()
    out["control_bind_before_guard"] = "ok"
    guards.install_socket_guard()
    def attempt(name, fn):
        try:
            fn()
            out[name] = "ok"
        except guards.EgressBlocked:
            out[name] = "blocked"
        except OSError as exc:
            out[name] = "oserror"
    attempt("connect_public", lambda: socket.create_connection(("192.0.2.1", 9), timeout=1))
    attempt("connect_loopback", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1))
    attempt("bind_loopback", lambda: socket.socket().bind(("127.0.0.1", 0)))
    attempt("resolve", lambda: socket.getaddrinfo("example.invalid", 443))
    attempt("udp_sendto", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("192.0.2.1", 9)))
    print(json.dumps(out))
    """)


def test_socket_guard_refuses_non_loopback_and_loopback():
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _SOCKET_SCRIPT],
        capture_output=True,
        timeout=60,
        check=False,
        env=_minimal_env(),
    )
    assert proc.returncode == 0, proc.stderr.decode()[-500:]
    out = json.loads(proc.stdout)
    assert out.pop("control_bind_before_guard") == "ok"
    assert out == {k: "blocked" for k in out} and len(out) == 5


# --- bounds -----------------------------------------------------------------------


def test_concurrency_lock_serializes_jobs(tmp_path):
    lock_path = tmp_path / "runs" / ".heavy.lock"
    with guards.HeavyJobLock(lock_path):
        with pytest.raises(ProtocolError) as info, guards.HeavyJobLock(lock_path):
            pass
        assert info.value.code is ErrorCode.PROCESS
    with guards.HeavyJobLock(lock_path):  # released: acquirable again
        pass


def test_lock_held_by_another_process_blocks(tmp_path):
    lock_path = tmp_path / ".heavy.lock"
    script = (
        "import sys,time;from openbb_nautilus_worker import guards;"
        "l=guards.HeavyJobLock(__import__('pathlib').Path(sys.argv[1]));l.__enter__();"
        "print('held',flush=True);sys.stdin.readline()"
    )
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=_minimal_env(),
    )
    try:
        assert child.stdout.readline().strip() == b"held"
        with pytest.raises(ProtocolError), guards.HeavyJobLock(lock_path):
            pass
    finally:
        child.communicate(b"\n", timeout=30)
    with guards.HeavyJobLock(lock_path):  # dead holder releases the OS lock
        pass


def test_deadline_fires_and_cancels():
    fired = threading.Event()
    with guards.Deadline(0.2, on_expire=fired.set):
        time.sleep(1.0)
    assert fired.is_set()
    quiet = threading.Event()
    with guards.Deadline(0.5, on_expire=quiet.set):
        pass
    time.sleep(0.8)
    assert not quiet.is_set()


def test_wall_time_kill_and_idle_exit():
    """The real entrypoint exits on idle while its stdin is still open."""
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "openbb_nautilus_worker", "--idle-seconds", "1"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_minimal_env(),
    )
    child.stdin.write(p.encode_key_frame(KEY))
    child.stdin.flush()
    start = time.monotonic()
    try:
        code = child.wait(timeout=30)
    finally:
        child.kill()
        child.communicate()
    assert code == guards.EXIT_IDLE
    assert time.monotonic() - start < 20


def test_oversize_frame_rejected_by_worker_loop():
    req = p.sign_request(KEY, 1, "describe", {"pad": "a" * p.MAX_FRAME_BYTES})
    line = json.dumps(req.model_dump(mode="json")).encode() + b"\n"
    out = io.BytesIO()
    code = wm.run_worker(
        io.BytesIO(p.encode_key_frame(KEY) + line),
        out,
        env={},
        idle_seconds=5,
        install=False,
    )
    frame = json.loads(out.getvalue().splitlines()[0])
    assert frame["error"]["code"] == "schema"
    assert code == guards.EXIT_AUTH


def test_worker_without_key_frame_exits_auth():
    code = wm.run_worker(
        io.BytesIO(_req()), io.BytesIO(), env={}, idle_seconds=5, install=False
    )
    assert code == guards.EXIT_AUTH
