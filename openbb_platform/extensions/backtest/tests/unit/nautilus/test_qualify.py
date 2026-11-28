"""qualify CLI + client against a fake worker (#1355 T01)."""

# ruff: noqa: D103

import json
import os
import sys
from pathlib import Path

from openbb_backtest.adapters.nautilus import (
    client as client_mod,
    qualify,
)
from openbb_backtest.adapters.nautilus.pin import load_pin

FIX = Path(__file__).parent / "fixtures"
FAKE = str(FIX / "fake_worker.py")
LICENSE_SHA = "ee907919ec88c9c017b1f8b608db20960b6598aefcc4fe58820bde955d65ed3c"


def _facts(name="facts_native_ok.json", **over):
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    d.update(over)
    return d


def _run(runtime, tmp_path, facts, extra=()):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(facts), encoding="utf-8")
    cmd = [sys.executable, FAKE, str(f), *extra]
    return qualify.qualify_runtime(load_pin(), runtime, cmd, timeout=60)


def test_qualify_records_abi_precision_license(tmp_path):
    rep = _run("native", tmp_path, _facts())
    assert rep.passed and rep.failed_layer is None
    assert rep.python_version.startswith("3.12.")
    assert rep.abi_tag == "cp312-win_amd64"
    assert rep.nautilus_version == "1.231.0"
    assert (rep.high_precision, rep.fixed_precision) == (False, 9)
    assert rep.license_sha256 == [LICENSE_SHA]
    assert rep.wheel_hash_evidence == "verified"


def test_qualify_docker_comparison_passes(tmp_path):
    rep = _run("docker", tmp_path, _facts("facts_docker_ok.json"))
    assert (
        rep.passed
        and rep.abi_tag == "cp312-manylinux_2_35_x86_64"
        and rep.high_precision is True
    )


def test_qualify_rejects_wrong_python_minor(tmp_path):
    rep = _run("native", tmp_path, _facts(python_version="3.13.1", python_tag="cp313"))
    assert not rep.passed and rep.failed_layer == "abi"


def test_qualify_rejects_wrong_platform_tag(tmp_path):
    rep = _run("native", tmp_path, _facts(platform_tag="manylinux_2_35_x86_64"))
    assert not rep.passed and rep.failed_layer == "abi"


def test_qualify_rejects_precision_mismatch(tmp_path):
    rep = _run("native", tmp_path, _facts(high_precision=True, fixed_precision=16))
    assert not rep.passed and rep.failed_layer == "abi"
    assert any(c.check == "precision" and not c.ok for c in rep.checks)


def test_qualify_rejects_wrong_version(tmp_path):
    rep = _run("native", tmp_path, _facts(nautilus_version="1.230.0"))
    assert not rep.passed and rep.failed_layer == "module_origin"


def test_qualify_rejects_wrong_dist_hash(tmp_path):
    rep = _run("native", tmp_path, _facts(wheel_sha256="f" * 64))
    assert not rep.passed and rep.failed_layer == "module_origin"


def test_qualify_rejects_module_outside_venv(tmp_path):
    rep = _run("native", tmp_path, _facts(module_origin_in_prefix=False))
    assert not rep.passed and rep.failed_layer == "module_origin"


def test_qualify_absent_wheel_hash_is_recorded_not_failed(tmp_path):
    rep = _run("native", tmp_path, _facts(wheel_sha256=None))
    assert rep.passed and rep.wheel_hash_evidence == "absent"


def test_qualify_first_failure_follows_layer_order(tmp_path):
    rep = _run(
        "native", tmp_path, _facts(nautilus_version="1.230.0", python_tag="cp313")
    )
    assert rep.failed_layer == "module_origin"


def test_qualify_bad_mac_from_worker_is_auth(tmp_path):
    rep = _run("native", tmp_path, _facts(), extra=("--bad-mac",))
    assert not rep.passed and rep.failed_layer == "auth"


def test_qualify_worker_error_code_is_propagated(tmp_path):
    rep = _run("native", tmp_path, _facts(), extra=("--error", "module_origin"))
    assert not rep.passed and rep.failed_layer == "module_origin"


def test_qualify_unreachable_worker_is_process(tmp_path):
    rep = qualify.qualify_runtime(
        load_pin(), "native", [str(tmp_path / "nope.exe")], timeout=10
    )
    assert not rep.passed and rep.failed_layer == "process"


def test_cli_exit_codes_and_json(tmp_path, capsys):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(_facts()), encoding="utf-8")
    cmd = json.dumps([sys.executable, FAKE, str(f)])
    rc = qualify.main(
        ["--runtime", "native", "--format", "json", "--worker-command-json", cmd]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["passed"] is True and out["abi_tag"] == "cp312-win_amd64"
    f.write_text(json.dumps(_facts(high_precision=True)), encoding="utf-8")
    rc = qualify.main(
        ["--runtime", "native", "--format", "json", "--worker-command-json", cmd]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["failed_layer"] == "abi"


def test_cli_missing_env_is_config_failure(monkeypatch, capsys):
    monkeypatch.delenv("OPENBB_NAUTILUS_VENV", raising=False)
    rc = qualify.main(["--runtime", "native", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["failed_layer"] == "config"


def test_native_and_docker_commands_come_from_env_not_hardcoded(monkeypatch):
    monkeypatch.setenv("OPENBB_NAUTILUS_VENV", "VENV_DIR")
    monkeypatch.setenv("OPENBB_NAUTILUS_IMAGE", "img@sha256:" + "a" * 64)
    native = client_mod.worker_command("native", os.environ)
    assert (
        native[1:4] == ["-I", "-m", "openbb_nautilus_worker"]
        and "VENV_DIR" in native[0]
    )
    docker = client_mod.worker_command("docker", os.environ)
    assert docker[:4] == ["docker", "run", "--rm", "-i"]
    assert docker[docker.index("--network") + 1] == "none" and docker[-1].startswith(
        "img@sha256:"
    )
    assert "--read-only" in docker and docker[docker.index("--cap-drop") + 1] == "ALL"


def test_client_never_passes_key_via_argv_or_env(tmp_path, monkeypatch):
    seen = {}
    real = client_mod.subprocess.Popen

    def spy(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return real(cmd, **kw)

    monkeypatch.setattr(client_mod.subprocess, "Popen", spy)
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(_facts()), encoding="utf-8")
    with client_mod.WorkerClient([sys.executable, FAKE, str(f)], timeout=60) as c:
        c.describe()
        key_hex = c.key_hex_for_tests()
    assert key_hex not in " ".join(seen["cmd"])
    assert seen["env"] is None or key_hex not in "".join(map(str, seen["env"].values()))
