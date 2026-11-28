"""Backup, binlog and disk observability: file metadata only (#1345-T03).

Synthetic temp directories and an injected ``disk_usage``; no MySQL, no subprocess,
nothing is ever deleted.
"""

from __future__ import annotations

import ast
import json
import os
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from portfolio_utils.fmp_sync import admission, ops_observe, readiness
from portfolio_utils.fmp_sync.checks import CheckState

from .conftest import DISPOSABLE_DB
from .test_admission import FakeConn, world  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
GIB = 1024**3
Usage = namedtuple("Usage", "total used free")
FS = Path(ops_observe.__file__).parent


def _usage(total_gib: float, free_gib: float):
    def fn(_path):
        return Usage(
            int(total_gib * GIB),
            int((total_gib - free_gib) * GIB),
            int(free_gib * GIB),
        )

    return fn


def _policy(tmp_path: Path, **extra) -> ops_observe.OpsPolicy:
    return ops_observe.OpsPolicy(
        **{"backup_dir": str(tmp_path / "bk"), "volumes": [str(tmp_path)], **extra}
    )


def _file(path: Path, size: int, age: timedelta) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _by_id(checks):
    return {c.check_id: c for c in checks}


def _eval(policy, **kw):
    kw.setdefault("disk_usage_fn", _usage(100, 50))
    return _by_id(ops_observe.evaluate(policy, now=NOW, **kw))


@pytest.mark.parametrize(
    ("total", "free", "state", "code"),
    [
        (100, 16, CheckState.OK, "DISK_OK"),
        (100, 14.9, CheckState.WARN, "DISK_LOW"),
        (100, 5.1, CheckState.WARN, "DISK_LOW"),
        (1000, 40, CheckState.CRITICAL, "DISK_CRITICAL"),  # 4% free, 40 GiB
        (50, 4, CheckState.CRITICAL, "DISK_CRITICAL"),  # 8% free, < 5 GiB
        (100, 5, CheckState.WARN, "DISK_LOW"),  # exactly 5 GiB / 5% is not below
    ],
)
def test_disk_thresholds_15_5_5gib(tmp_path, total, free, state, code):
    got = _eval(_policy(tmp_path), disk_usage_fn=_usage(total, free))["ops.disk"]
    assert (got.state, got.reason_code) == (state, code)


def test_disk_unreadable_is_unknown(tmp_path):
    def boom(_path):
        raise OSError("denied")

    got = _eval(_policy(tmp_path), disk_usage_fn=boom)["ops.disk"]
    assert got.state is CheckState.UNKNOWN and got.reason_code == "DISK_UNREADABLE"


def test_backup_age_26h_critical(tmp_path):
    _file(tmp_path / "bk" / "a.sql.gz", 10, timedelta(hours=26))
    got = _eval(_policy(tmp_path))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.CRITICAL, "BACKUP_STALE")
    _file(tmp_path / "bk" / "b.sql.gz", 10, timedelta(hours=25, minutes=59))
    fresh = _eval(_policy(tmp_path))["ops.backup"]
    assert (fresh.state, fresh.reason_code) == (CheckState.OK, "BACKUP_FRESH")


def test_backup_zero_size_critical(tmp_path):
    _file(tmp_path / "bk" / "x.sql.gz", 0, timedelta(hours=1))
    got = _eval(_policy(tmp_path))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.CRITICAL, "BACKUP_EMPTY")


def test_inprogress_backup_ignored(tmp_path):
    _file(tmp_path / "bk" / "old.sql.gz", 10, timedelta(hours=2))
    _file(tmp_path / "bk" / "new.sql.gz.tmp", 0, timedelta(minutes=30))
    _file(tmp_path / "bk" / "new2.sql.gz.partial", 0, timedelta(minutes=40))
    _file(tmp_path / "bk" / "unstable.sql.gz", 0, timedelta(minutes=5))  # < 10 min
    got = _eval(_policy(tmp_path, backup_glob="*"))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.OK, "BACKUP_FRESH")


def test_no_stable_backup_is_explicit_missing(tmp_path):
    (tmp_path / "bk").mkdir()
    got = _eval(_policy(tmp_path))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.CRITICAL, "BACKUP_MISSING")


def test_backup_dir_denied_unknown(tmp_path, monkeypatch):
    (tmp_path / "bk").mkdir()

    def denied(_path):
        raise PermissionError

    monkeypatch.setattr(ops_observe.os, "scandir", denied)
    got = _eval(_policy(tmp_path))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "BACKUP_DIR_UNREADABLE")
    monkeypatch.undo()
    gone = _eval(ops_observe.OpsPolicy(backup_dir=str(tmp_path / "nope")))["ops.backup"]
    assert gone.state is CheckState.UNKNOWN


def test_backup_future_mtime_unknown(tmp_path):
    _file(tmp_path / "bk" / "a.sql.gz", 10, timedelta(hours=-3))
    got = _eval(_policy(tmp_path))["ops.backup"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "BACKUP_CLOCK_SKEW")


def test_unconfigured_paths_not_evaluated():
    got = _eval(ops_observe.OpsPolicy())
    assert got["ops.backup"].state is CheckState.NOT_EVALUATED
    assert got["ops.binlog"].state is CheckState.NOT_EVALUATED
    assert got["ops.disk"].state is CheckState.NOT_EVALUATED


def test_attestation_never_fabricates_health(tmp_path):
    for attested in (False, True):
        got = _eval(_policy(tmp_path), attested=attested)
        for key in ("ops.backup_task", "ops.restore_proof"):
            assert got[key].state is CheckState.NOT_EVALUATED
            assert got[key].required is False


def _binlogs(tmp_path: Path, total: int) -> ops_observe.OpsPolicy:
    _file(tmp_path / "bl" / "binlog.000001", total, timedelta(hours=1))
    return _policy(tmp_path, binlog_dir=str(tmp_path / "bl"))


def test_binlog_first_sample_unknown(tmp_path):
    root = tmp_path / "st"
    got = _eval(_binlogs(tmp_path, 100), state_root=root)["ops.binlog"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "FIRST_SAMPLE")
    assert (root / "ops" / "binlog.json").exists()
    assert "growth_bytes_day" not in got.counts


def test_binlog_without_state_root_never_writes(tmp_path):
    got = _eval(_binlogs(tmp_path, 100))["ops.binlog"]
    assert got.reason_code == "FIRST_SAMPLE"
    assert not (tmp_path / "st").exists()


def _sample(root: Path, total: int, age: timedelta) -> None:
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "binlog.json").write_text(
        json.dumps({"sample_utc": (NOW - age).isoformat(), "total_bytes": total}),
        encoding="utf-8",
    )


def test_binlog_rotation_negative_unknown(tmp_path):
    root = tmp_path / "st"
    _sample(root, 5000, timedelta(hours=24))
    got = _eval(_binlogs(tmp_path, 100), state_root=root)["ops.binlog"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "BINLOG_ROTATED")
    saved = json.loads((root / "ops" / "binlog.json").read_text("utf-8"))
    assert saved["total_bytes"] == 100  # re-baselined


def test_binlog_interval_too_short_unknown_keeps_prior(tmp_path):
    root = tmp_path / "st"
    _sample(root, 10, timedelta(minutes=30))
    got = _eval(_binlogs(tmp_path, GIB), state_root=root)["ops.binlog"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "SAMPLE_TOO_SOON")
    saved = json.loads((root / "ops" / "binlog.json").read_text("utf-8"))
    assert saved["total_bytes"] == 10


def test_binlog_growth_over_1gib_day_warn(tmp_path):
    root = tmp_path / "st"
    _sample(root, 0, timedelta(hours=24))
    warn = _eval(_binlogs(tmp_path, GIB + 1), state_root=root)["ops.binlog"]
    assert (warn.state, warn.reason_code) == (CheckState.WARN, "BINLOG_GROWTH_HIGH")
    root2 = tmp_path / "st2"
    _sample(root2, 0, timedelta(hours=48))  # same delta over two days = half the rate
    ok = _eval(_binlogs(tmp_path, GIB + 1), state_root=root2)["ops.binlog"]
    assert (ok.state, ok.reason_code) == (CheckState.OK, "BINLOG_GROWTH_OK")


def test_binlog_dir_unreadable_unknown(tmp_path):
    policy = _policy(tmp_path, binlog_dir=str(tmp_path / "missing"))
    got = _eval(policy, state_root=tmp_path / "st")["ops.binlog"]
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "BINLOG_DIR_UNREADABLE")


def test_show_binary_logs_1227_unknown():
    def denied():
        raise RuntimeError(1227, "need SUPER or BINLOG ADMIN")

    got = ops_observe.binlog_from_show(denied)
    assert (got.state, got.reason_code) == (CheckState.UNKNOWN, "BINLOG_PRIVILEGE")

    def broken():
        raise OSError("x")

    assert ops_observe.binlog_from_show(broken).state is CheckState.UNKNOWN
    sized = ops_observe.binlog_from_show(lambda: [{"File_size": 5}, {"File_size": 7}])
    assert sized.counts["total_bytes"] == 12


def test_output_carries_no_paths(tmp_path):
    _file(tmp_path / "bk" / "secret-name.sql.gz", 10, timedelta(hours=1))
    checks = ops_observe.evaluate(
        _policy(tmp_path), now=NOW, disk_usage_fn=_usage(100, 50)
    )
    blob = json.dumps([c.model_dump(mode="json") for c in checks])
    assert "secret-name" not in blob and str(tmp_path) not in blob


_FORBIDDEN_NAMES = {
    "unlink",
    "remove",
    "rmtree",
    "rmdir",
    "removedirs",
    "truncate",
    "rename",
    "replace",
    "subprocess",
    "Popen",
    "system",
    "schtasks",
    "popen",
}


@pytest.mark.parametrize("module", ["ops_observe.py", "recovery.py"])
def test_no_delete_or_purge_paths(module):
    tree = ast.parse((FS / module).read_text(encoding="utf-8"))
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            seen.add(node.attr)
        elif isinstance(node, ast.Name):
            seen.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            seen.update(a.name.split(".")[0] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                seen.add(node.module.split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            assert "purge" not in low and "schtasks" not in low
    assert not seen & _FORBIDDEN_NAMES, seen & _FORBIDDEN_NAMES


def test_ops_never_reads_file_contents():
    tree = ast.parse((FS / "ops_observe.py").read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not attrs & {"read_bytes", "write_bytes", "write_text"}
    assert "open" not in names


def _ok_conn():
    return FakeConn(DISPOSABLE_DB)


def test_disk_critical_blocks_execute_not_read_only(world):  # noqa: F811
    make, kwargs = world
    dmap = make(ops={"volumes": ["V"], "backup_dir": "B"})
    crit = {**kwargs, "disk_usage_fn": _usage(100, 1)}
    blocked = admission.admit(dmap, mode="execute", connect_fn=_ok_conn, **crit)
    assert not blocked.admitted and blocked.code == "BLOCKED_POLICY"
    assert "DISK_CRITICAL" in blocked.findings
    dry = admission.admit(dmap, mode="dry_run", **crit)
    assert dry.admitted  # reads and dry runs stay allowed
    ok = {**kwargs, "disk_usage_fn": _usage(100, 50)}
    assert admission.admit(dmap, mode="execute", connect_fn=_ok_conn, **ok).admitted
    plain = make()
    assert admission.admit(plain, mode="execute", connect_fn=_ok_conn, **crit).admitted


def test_ops_group_is_opt_in_and_dry_run_has_no_db(tmp_path):
    assert "ops" in readiness.CHECK_GROUPS
    _file(tmp_path / "bk" / "x.sql.gz", 0, timedelta(hours=1))
    report = readiness.evaluate(
        [],
        now=NOW,
        checks=("ops",),
        dry_run=True,
        ops_policy=_policy(tmp_path),
        disk_usage_fn=_usage(100, 1),
    )
    by = _by_id(report.checks)
    assert by["ops.backup"].reason_code == "BACKUP_EMPTY"
    assert by["ops.disk"].state is CheckState.CRITICAL
    assert by["ops.binlog"].state is CheckState.NOT_EVALUATED
    plain = readiness.evaluate([], now=NOW, dry_run=True)
    assert not any(c.check_id.startswith("ops.") for c in plain.checks)
