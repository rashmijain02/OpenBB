"""Facade side of the reviewed-strategy loader and ``strategies`` CLI (#1356 T01).

The facade resolves against the shared reviewed modules, builds the ``run``
request v2 fields the worker re-checks, and ships ``verify`` / ``list`` for
operators. Tampered copies are real files on disk, not mocks.
"""

# ruff: noqa: D103

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openbb_backtest.adapters.nautilus import strategies
from openbb_backtest.registry import register_strategy
from openbb_nautilus_worker import admission
from openbb_nautilus_worker.reviewed import registry as worker_registry
from openbb_nautilus_worker.reviewed.errors import ReviewedError

PKG = Path(worker_registry.__file__).resolve().parents[1]
BACKTEST = Path(strategies.__file__).resolve().parents[3]
BAH, TWR = "buy_and_hold", "target_weight_rebalance"


def _copy(tmp_path: Path) -> Path:
    dst = tmp_path / "pkg"
    shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKTEST), str(BACKTEST / "nautilus_worker")]
    )
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "openbb_backtest.adapters.nautilus.strategies", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def test_resolve_builds_a_request_the_worker_screen_accepts():
    binding = strategies.resolve_reviewed(
        BAH, "1.0.0", {"symbols": ["BHX"]}, {"fill_timing": "same_close"}
    )
    body = strategies.build_run_body(binding, "0" * 64, starting_cash="10000.00")
    req = admission.screen_request(body)
    assert (
        req.strategy_ref.code_sha256
        == worker_registry.pin_for(BAH, "1.0.0").code_sha256
    )
    assert req.execution.fill_timing == "same_close"
    # the worker's independent resolution agrees hash for hash
    again = worker_registry.resolve_request(req)
    assert again.params_sha256 == binding.params_sha256
    assert again.execution_sha256 == binding.execution_sha256


def test_facade_rejects_unreviewed_and_plugin_strategies():
    for name in ("momentum_12_1", "techtrade_confluence", "pkg.mod:Cls"):
        with pytest.raises(ReviewedError):
            strategies.resolve_reviewed(name, None, {}, None)


def test_legacy_registry_entry_cannot_shadow_reviewed(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("entry points read")),
    )

    @register_strategy("target_weight_rebalance")
    class Shadow:  # pragma: no cover - registered only to prove no shadowing
        pass

    binding = strategies.resolve_reviewed(TWR, "1.0.0", _twr(), None)
    assert binding.code_sha256 == worker_registry.pin_for(TWR, "1.0.0").code_sha256


def _twr():
    return {"weights": {"AAA": "0.5", "BBB": "0.5"}, "rebalance_every_sessions": 2}


def test_facade_detects_tampered_local_copy(tmp_path):
    root = _copy(tmp_path)
    path = root / "reviewed" / "buy_and_hold.py"
    path.write_bytes(path.read_bytes() + b"#")
    with pytest.raises(ReviewedError) as info:
        strategies.resolve_reviewed(BAH, "1.0.0", {"symbols": ["BHX"]}, None, root=root)
    assert info.value.reason == "strategy_code_drift"
    assert info.value.code.value == "module_origin"


def test_cli_verify_ok_lists_both_strategies():
    proc = _cli("verify", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["passed"] is True
    rows = {(r["id"], r["version"]): r for r in report["strategies"]}
    assert set(rows) == {(BAH, "1.0.0"), (TWR, "1.0.0")}
    for (sid, ver), row in rows.items():
        pin = worker_registry.pin_for(sid, ver)
        assert row["status"] == "ok"
        assert row["code_sha256"] == pin.code_sha256
        assert row["spec_sha256"] == pin.spec_sha256
        assert row["param_schema_sha256"] == pin.param_schema_sha256


def test_cli_verify_tampered_root_exits_2_with_code_drift(tmp_path):
    root = _copy(tmp_path)
    path = root / "reviewed" / "params.py"
    path.write_bytes(path.read_bytes() + b" ")
    proc = _cli("verify", "--root", str(root), "--format", "json")
    assert proc.returncode == 2
    report = json.loads(proc.stdout)
    assert report["passed"] is False
    assert {r["reason"] for r in report["strategies"]} == {"strategy_code_drift"}
    assert {r["layer"] for r in report["strategies"]} == {"module_origin"}
    text = _cli("verify", "--root", str(root))
    assert text.returncode == 2 and "strategy_code_drift" in text.stdout


def test_cli_verify_root_that_is_not_a_package_exits_2(tmp_path):
    proc = _cli("verify", "--root", str(tmp_path / "missing"), "--format", "json")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["passed"] is False


def test_cli_list_shows_pins_without_recomputing(tmp_path):
    proc = _cli("list", "--format", "json")
    assert proc.returncode == 0
    rows = json.loads(proc.stdout)["strategies"]
    assert [(r["id"], r["version"]) for r in rows] == [(BAH, "1.0.0"), (TWR, "1.0.0")]
    assert all(len(r["code_sha256"]) == 64 for r in rows)


def test_cli_rejects_unknown_command():
    assert _cli("run").returncode == 2


def test_dependency_direction_is_one_way():
    """The facade never imports openbb_agents; the worker never imports the facade."""

    def imports(root: Path) -> set[str]:
        found: set[str] = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    found.add((node.module or "").split(".")[0])
        return found

    assert "openbb_agents" not in imports(BACKTEST / "openbb_backtest")
    assert "openbb_backtest" not in imports(PKG)
