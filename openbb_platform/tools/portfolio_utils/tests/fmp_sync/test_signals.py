"""Ctrl+C / Ctrl+Break through ``main()`` in a real child process (#1344 CODE-2).

The child blocks MySQL and every socket itself, fakes admission and the warmer
(no DB, no FMP), and signals readiness from inside the warm loop. The parent
then sends the console event; the run must end CANCELLED with its run file and
end receipt written.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .conftest import DISPOSABLE_DB
from .test_dispatcher import LIMITS

CHILD = r"""
import socket, sys, time, types
from pathlib import Path

import pymysql

def _no(*_a, **_k):
    raise RuntimeError("no MySQL in this test")

pymysql.connect = pymysql.Connect = _no
socket.socket.connect = lambda self, address: _no()

from portfolio_utils.fmp_sync import dispatcher
from portfolio_utils.fmp_sync.admission import Admission

def _admit(dmap, **_kw):
    return Admission(True, "ADMITTED", symbols=("AAA", "BBB"),
                     counts={"requested": 2, "skipped": 0},
                     target=dmap.target, target_class=dmap.target_class)

dispatcher.admit = _admit
ready = Path(sys.argv[1])
fake = types.ModuleType("portfolio_utils.fetch_position_history")

def _warm(*, should_cancel, **_kw):
    ready.write_text("ready", encoding="utf-8")
    end = time.monotonic() + 60
    while time.monotonic() < end:
        if should_cancel():
            return types.SimpleNamespace(success=[], failed=[], cancelled=True)
        time.sleep(0.02)
    return types.SimpleNamespace(success=[], failed=[], cancelled=False)

fake.run_position_history_warm = _warm
fake.ensure_market_holidays = lambda *_a: None
fake.check_portfolio_app_readiness = lambda *_a: {}
fake._resolve_api_key = lambda: "k"
sys.modules["portfolio_utils.fetch_position_history"] = fake
from portfolio_utils.fmp_sync.__main__ import main
sys.exit(main(sys.argv[2:]))
"""


def _map(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "source_root": str(tmp_path / "src"),
        "source_sha": "a" * 40,
        "interpreter": str(tmp_path / "venv"),
        "target": DISPOSABLE_DB,
        "target_class": "disposable",
        "profile_path": str(tmp_path / "profile.json"),
        "limits": LIMITS,
        "account_label": "acct",
    }
    path = tmp_path / "map.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _interrupt(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGINT)


def test_console_break_through_main_writes_cancelled_receipt(
    tmp_path, child_env, python_exe
):
    """Ctrl+Break (Windows) / SIGINT mid-warm -> CANCELLED run file + end receipt."""
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    ready = tmp_path / "ready"
    argv = ["prices", "--execute", "--receipt", "--map", str(_map(tmp_path))]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(  # noqa: S603
        [python_exe, str(script), str(ready), *argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
        creationflags=flags,
    )
    try:
        end = time.monotonic() + 60
        while not ready.exists() and proc.poll() is None and time.monotonic() < end:
            time.sleep(0.05)
        assert ready.exists(), proc.communicate(timeout=30)
        try:
            _interrupt(proc)
        except OSError:
            pytest.skip("no shared console to deliver the control event")
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, err
    payload = json.loads(out.strip())
    assert payload["outcome"] == "CANCELLED"
    root = Path(child_env["FMP_SYNC_STATE_ROOT"])
    run = json.loads((root / "runs" / f"{payload['run_id']}.json").read_text("utf-8"))
    assert run["outcome"]["outcome"] == "CANCELLED"
    records = [
        json.loads(line)
        for line in (root / "history.jsonl").read_text("utf-8").splitlines()
    ]
    ends = [r for r in records if r.get("kind") == "end"]
    assert [r["outcome"] for r in ends] == ["CANCELLED"]
    assert ends[0]["run_id"] == payload["run_id"]
