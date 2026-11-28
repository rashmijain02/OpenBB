"""Rendered wrapper end to end in a child interpreter (#1344-T03). No DB, no network."""

from __future__ import annotations

import json
import subprocess

from portfolio_utils.fmp_sync import render

from .test_render import rig  # noqa: F401  (fixture)

GENERIC = "fmp_cache_prices: integrity check failed"


def _run(script, child_env, python_exe, *extra):
    return subprocess.run(  # noqa: S603
        [python_exe, str(script), *extra],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=120,
        check=False,
    )


def test_wrapper_exit0_for_recorded_unhealthy_outcome(
    rig, child_env, python_exe
):  # noqa: F811
    rig["write"](limits=None)  # execute with no limits -> BLOCKED_POLICY, no I/O
    render.apply_files(rig["map"], rig["home"])
    script = rig["home"] / "scripts" / render.WRAPPER_NAME
    done = _run(script, child_env, python_exe)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["outcome"] == "BLOCKED_POLICY" and payload["exit"] == 40
    root = render.effective_state_root(rig["map"])
    assert (root / "history.jsonl").exists() and (root / "status.json").exists()
    again = _run(script, child_env, python_exe)  # unchanged fingerprint -> silent
    assert again.returncode == 0 and again.stdout == ""


def test_wrapper_hash_mismatch_generic_nonzero(
    rig, child_env, python_exe
):  # noqa: F811
    render.apply_files(rig["map"], rig["home"])
    script = rig["home"] / "scripts" / render.WRAPPER_NAME
    script.write_text(script.read_text("utf-8") + "\n# tamper\n", encoding="utf-8")
    done = _run(script, child_env, python_exe)
    assert done.returncode == 3
    assert done.stdout.strip() == GENERIC
    assert str(rig["tmp"]) not in done.stdout + done.stderr


def test_wrapper_map_drift_generic_nonzero(rig, child_env, python_exe):  # noqa: F811
    render.apply_files(rig["map"], rig["home"])
    rig["write"](target="obb_disposable_00000000")  # map changed after render
    script = rig["home"] / "scripts" / render.WRAPPER_NAME
    done = _run(script, child_env, python_exe)
    assert done.returncode == 3
    assert done.stdout.strip() == GENERIC


def test_wrapper_ignores_argv_and_cron_env(rig, child_env, python_exe):  # noqa: F811
    rig["write"](limits=None)
    render.apply_files(rig["map"], rig["home"])
    script = rig["home"] / "scripts" / render.WRAPPER_NAME
    child_env["FMP_SYNC_MAP"] = "elsewhere.json"
    done = _run(script, child_env, python_exe, "--map", "evil.json")
    assert done.returncode == 0
    assert json.loads(done.stdout)["outcome"] == "BLOCKED_POLICY"
