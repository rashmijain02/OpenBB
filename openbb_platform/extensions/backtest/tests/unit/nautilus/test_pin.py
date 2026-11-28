"""Pin schema and lock-file tests (#1355 T01). Pure; nothing is installed."""

# ruff: noqa: D103

import re
from pathlib import Path

import pytest
import yaml
from openbb_backtest.adapters.nautilus import pin as pin_mod
from pydantic import ValidationError

WORKER_DIR = Path(pin_mod.__file__).resolve().parents[3] / "nautilus_worker"
NAUTILUS_WIN_SHA = "0697f51e9143f9d8d040f75d2e6a45218003cc34f7ea5b0eb2f9cda6935427de"
NAUTILUS_LINUX_SHA = "8c438e95c275a13df0c0ddb7012c462708b5e99ff3612e36a1b7bd49ab39c216"


def _raw():
    return yaml.safe_load((WORKER_DIR / "pin.yaml").read_text(encoding="utf-8"))


def _write(tmp_path, raw):
    f = tmp_path / "pin.yaml"
    f.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return f


def test_pin_loads_with_lead_decisions():
    pin = pin_mod.load_pin()
    assert pin.version == "1.231.0" and pin.python_tag == "cp312"
    assert pin.source_commit.startswith("d3e1685e")
    assert pin.selected_runtime == "native"
    native, docker = pin.runtimes["native"], pin.runtimes["docker"]
    assert (native.platform_tag, native.wheel_sha256) == ("win_amd64", NAUTILUS_WIN_SHA)
    assert (native.precision_mode, native.fixed_precision, native.high_precision) == (
        "standard",
        9,
        False,
    )
    assert (
        docker.platform_tag == "manylinux_2_35_x86_64"
        and docker.wheel_sha256 == NAUTILUS_LINUX_SHA
    )
    assert (docker.precision_mode, docker.high_precision) == ("high", True)
    assert pin.license_spdx == "LGPL-3.0-or-later"
    assert pin.license_file_sha256.startswith("ee907919")


def test_pin_loads_and_rejects_unknown_keys(tmp_path):
    raw = _raw()
    raw["surprise"] = 1
    with pytest.raises(ValidationError):
        pin_mod.load_pin(_write(tmp_path, raw))
    raw = _raw()
    raw["runtimes"]["native"]["extra"] = "x"
    with pytest.raises(ValidationError):
        pin_mod.load_pin(_write(tmp_path, raw))


@pytest.mark.parametrize("bad", [None, "", "abc", "G" * 64, "0" * 63])
def test_pin_requires_hash_per_platform_tag(tmp_path, bad):
    raw = _raw()
    if bad is None:
        del raw["runtimes"]["native"]["wheel_sha256"]
    else:
        raw["runtimes"]["native"]["wheel_sha256"] = bad
    with pytest.raises(ValidationError):
        pin_mod.load_pin(_write(tmp_path, raw))


def test_pin_wheel_filename_must_match_platform_and_python_tag(tmp_path):
    raw = _raw()
    raw["runtimes"]["native"][
        "wheel_filename"
    ] = "nautilus_trader-1.231.0-cp313-cp313-win_amd64.whl"
    with pytest.raises(ValidationError):
        pin_mod.load_pin(_write(tmp_path, raw))


def test_pin_rejects_prerelease_version(tmp_path):
    raw = _raw()
    raw["version"] = "2.0.0rc9"
    for rt in raw[
        "runtimes"
    ].values():  # filenames stay consistent: only the version rule may reject
        rt["wheel_filename"] = rt["wheel_filename"].replace("1.231.0", "2.0.0rc9")
    with pytest.raises(ValidationError):
        pin_mod.load_pin(_write(tmp_path, raw))


def _lock_requirements(path):
    text = re.sub(r"(?m)^\s*#.*$", "", path.read_text(encoding="utf-8"))
    text = text.replace("\\\n", " ")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


@pytest.mark.parametrize(
    "runtime,sha",
    [("native", NAUTILUS_WIN_SHA), ("docker", NAUTILUS_LINUX_SHA)],
)
def test_lock_files_pin_nautilus_hash_matches_pin_yaml(runtime, sha):
    pin = pin_mod.load_pin()
    reqs = _lock_requirements(WORKER_DIR / pin.runtimes[runtime].lock)
    nautilus = [r for r in reqs if r.lower().startswith("nautilus_trader==")]
    assert len(nautilus) == 1
    assert nautilus[0].startswith(f"nautilus_trader=={pin.version}")
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", nautilus[0])
    assert hashes == [pin.runtimes[runtime].wheel_sha256] == [sha]


def test_lock_files_exclude_broker_extras():
    banned = (
        "nautilus-ibapi",
        "nautilus_ibapi",
        "ibapi",
        "py-clob-client",
        "betfair-parser",
        "betfair_parser",
    )
    locks = sorted(WORKER_DIR.glob("requirements-*.lock"))
    assert len(locks) == 2
    for lock in locks:
        reqs = _lock_requirements(lock)
        assert reqs, lock.name
        flat = " ".join(reqs).lower()
        for b in banned:
            assert b not in flat, (lock.name, b)
        for r in reqs:
            name = re.split(r"[=<>~! \[]", r, maxsplit=1)[0].lower()
            assert name not in banned, (lock.name, name)
            assert "[" not in r.split("==")[0], f"extras not allowed: {r}"
            assert "--hash=sha256:" in r, f"unhashed requirement: {r}"


def test_lock_files_use_real_line_continuations():
    """A literal backslash followed by n would make pip reject the lock."""
    backslash = chr(92)
    for lock in sorted(WORKER_DIR.glob("requirements-*.lock")):
        text = lock.read_text(encoding="utf-8")
        assert backslash + "n" not in text, lock.name
        lines = text.splitlines()
        hash_idx = [i for i, ln in enumerate(lines) if ln.strip().startswith("--hash=")]
        assert hash_idx, lock.name
        for i in hash_idx:
            assert lines[i - 1].endswith(" " + backslash), (lock.name, i)
