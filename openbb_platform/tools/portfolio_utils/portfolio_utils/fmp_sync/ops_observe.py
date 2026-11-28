"""Backup, binlog and disk observability from file metadata only (#1345-T03).

Inputs come from the private deployment map (``ops`` block). Nothing here reads
file contents, runs a subprocess, or removes anything: directories are listed
with ``os.scandir`` and sized from ``stat``. Results carry codes and integer
counts, never paths or file names. Unknown is never reported as healthy: a
first sample, a rotation (negative delta) or a too-short interval is
``UNKNOWN``, never 0 growth.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from portfolio_utils.fmp_sync import state
from portfolio_utils.fmp_sync.checks import CheckResult, CheckState

GIB = 1024**3
OPS_CHECKS = (
    "ops.disk",
    "ops.backup",
    "ops.binlog",
    "ops.backup_task",
    "ops.restore_proof",
)
SAMPLE_NAME = "binlog.json"
_MAX_ENTRIES = 20000
_ERR_PRIVILEGE = 1227


class OpsPolicy(BaseModel):
    """``ops`` block of the private deployment map (paths stay private)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_dir: str | None = None
    backup_glob: str = Field(default="*.sql.gz", max_length=64)
    binlog_dir: str | None = None
    binlog_glob: str = Field(default="*bin*.[0-9]*", max_length=64)
    volumes: list[str] = Field(default_factory=list, max_length=8)
    data_volume: str | None = None
    show_binary_logs: bool = False
    backup_max_age_hours: float = Field(default=26.0, gt=0, le=720)
    backup_stable_minutes: float = Field(default=10.0, ge=0, le=720)
    disk_warn_free_pct: float = Field(default=15.0, gt=0, lt=100)
    disk_critical_free_pct: float = Field(default=5.0, gt=0, lt=100)
    disk_critical_free_gib: float = Field(default=5.0, gt=0)
    binlog_growth_warn_gib_day: float = Field(default=1.0, gt=0)
    binlog_min_interval_minutes: float = Field(default=60.0, ge=1, le=10080)


def _check(check_id: str, state_: CheckState, code: str, **kw: Any) -> CheckResult:
    return CheckResult(check_id=check_id, state=state_, reason_code=code, **kw)


# ------------------------------------------------------------------ disk


def _volume_state(policy: OpsPolicy, usage: Any) -> tuple[CheckState, str]:
    free, total = int(usage.free), int(usage.total)
    pct = 100.0 * free / total if total else 0.0
    if (
        pct < policy.disk_critical_free_pct
        or free < policy.disk_critical_free_gib * GIB
    ):
        return CheckState.CRITICAL, "DISK_CRITICAL"
    if pct < policy.disk_warn_free_pct:
        return CheckState.WARN, "DISK_LOW"
    return CheckState.OK, "DISK_OK"


_SEVERITY = (
    CheckState.CRITICAL,
    CheckState.UNKNOWN,
    CheckState.WARN,
    CheckState.OK,
)


def disk_check(policy: OpsPolicy, disk_usage_fn: Callable[[str], Any]) -> CheckResult:
    """Worst state over the mapped volumes (free space only)."""
    if not policy.volumes:
        return _check("ops.disk", CheckState.NOT_EVALUATED, "DISK_NOT_CONFIGURED")
    worst: tuple[CheckState, str] = (CheckState.OK, "DISK_OK")
    counts = {"volumes": len(policy.volumes), "warn": 0, "critical": 0, "unknown": 0}
    for volume in policy.volumes:
        try:
            got = _volume_state(policy, disk_usage_fn(volume))
        except (OSError, ValueError, AttributeError, TypeError):
            got = (CheckState.UNKNOWN, "DISK_UNREADABLE")
        key = {
            CheckState.CRITICAL: "critical",
            CheckState.WARN: "warn",
            CheckState.UNKNOWN: "unknown",
        }.get(got[0])
        if key:
            counts[key] += 1
        if _SEVERITY.index(got[0]) < _SEVERITY.index(worst[0]):
            worst = got
    return _check("ops.disk", worst[0], worst[1], counts=counts)


def data_volume_critical(
    policy: OpsPolicy, disk_usage_fn: Callable[[str], Any] = shutil.disk_usage
) -> bool:
    """Return True only when the data volume is measurably CRITICAL (unknown never blocks)."""
    volume = policy.data_volume or (policy.volumes[0] if policy.volumes else None)
    if volume is None:
        return False
    try:
        return _volume_state(policy, disk_usage_fn(volume))[0] is CheckState.CRITICAL
    except (OSError, ValueError, AttributeError, TypeError):
        return False


# ------------------------------------------------------------------ backup


def _scan(directory: str, pattern: str) -> list[tuple[str, os.stat_result]] | None:
    """(name, stat) of regular files matching ``pattern``; ``None`` if unreadable."""
    out: list[tuple[str, os.stat_result]] = []
    try:
        with os.scandir(directory) as entries:
            for seen, entry in enumerate(entries, start=1):
                if seen > _MAX_ENTRIES:
                    return None
                if fnmatch.fnmatch(entry.name, pattern) and entry.is_file():
                    out.append((entry.name, entry.stat()))
    except OSError:
        return None
    return out


def backup_check(policy: OpsPolicy, now: datetime) -> CheckResult:
    """Newest stable backup: missing, empty, stale or fresh (metadata only)."""
    if not policy.backup_dir:
        return _check("ops.backup", CheckState.NOT_EVALUATED, "BACKUP_NOT_CONFIGURED")
    files = _scan(policy.backup_dir, policy.backup_glob)
    if files is None:
        return _check("ops.backup", CheckState.UNKNOWN, "BACKUP_DIR_UNREADABLE")
    now_ts = now.timestamp()
    stable_s = policy.backup_stable_minutes * 60
    stable = [
        (name, st)
        for name, st in files
        if not name.endswith((".tmp", ".partial"))
        and (now_ts - st.st_mtime >= stable_s or st.st_mtime > now_ts)
    ]
    counts = {"candidates": len(files), "stable": len(stable)}
    if not stable:
        return _check(
            "ops.backup", CheckState.CRITICAL, "BACKUP_MISSING", counts=counts
        )
    newest = max(stable, key=lambda item: item[1].st_mtime)[1]
    age_s = now_ts - newest.st_mtime
    if age_s < 0:
        return _check(
            "ops.backup", CheckState.UNKNOWN, "BACKUP_CLOCK_SKEW", counts=counts
        )
    counts["age_hours"] = int(age_s // 3600)
    if newest.st_size <= 0:
        return _check("ops.backup", CheckState.CRITICAL, "BACKUP_EMPTY", counts=counts)
    if age_s >= policy.backup_max_age_hours * 3600:
        return _check("ops.backup", CheckState.CRITICAL, "BACKUP_STALE", counts=counts)
    return _check("ops.backup", CheckState.OK, "BACKUP_FRESH", counts=counts)


# ------------------------------------------------------------------ binlog


def _read_sample(root: Path) -> tuple[datetime, int] | None:
    try:
        raw = json.loads((root / "ops" / SAMPLE_NAME).read_text("utf-8"))
        stamp = datetime.fromisoformat(str(raw["sample_utc"]))
        total = int(raw["total_bytes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if stamp.tzinfo is None or total < 0:
        return None
    return stamp, total


def _write_sample(root: Path, now: datetime, total: int) -> None:
    state.atomic_write_json(
        root / "ops" / SAMPLE_NAME,
        {"sample_utc": now.isoformat(), "total_bytes": total},
    )


def binlog_check(
    policy: OpsPolicy, now: datetime, state_root: Path | None
) -> CheckResult:
    """Binlog growth per day from directory sizes against the prior sample."""
    if not policy.binlog_dir:
        return _check("ops.binlog", CheckState.NOT_EVALUATED, "BINLOG_NOT_CONFIGURED")
    files = _scan(policy.binlog_dir, policy.binlog_glob)
    if files is None:
        return _check("ops.binlog", CheckState.UNKNOWN, "BINLOG_DIR_UNREADABLE")
    total = sum(st.st_size for _name, st in files)
    counts = {"files": len(files), "total_bytes": total}
    prior = _read_sample(state_root) if state_root else None

    def record() -> None:
        if state_root:
            _write_sample(state_root, now, total)

    if prior is None:
        record()
        return _check("ops.binlog", CheckState.UNKNOWN, "FIRST_SAMPLE", counts=counts)
    when, before = prior
    elapsed = (now - when).total_seconds()
    if elapsed < policy.binlog_min_interval_minutes * 60:
        return _check(
            "ops.binlog", CheckState.UNKNOWN, "SAMPLE_TOO_SOON", counts=counts
        )
    delta = total - before
    record()
    if delta < 0:
        return _check("ops.binlog", CheckState.UNKNOWN, "BINLOG_ROTATED", counts=counts)
    per_day = int(delta * 86400 / elapsed)
    counts["growth_bytes_day"] = per_day
    if per_day > policy.binlog_growth_warn_gib_day * GIB:
        return _check(
            "ops.binlog", CheckState.WARN, "BINLOG_GROWTH_HIGH", counts=counts
        )
    return _check("ops.binlog", CheckState.OK, "BINLOG_GROWTH_OK", counts=counts)


def binlog_from_show(rows_fn: Callable[[], Any]) -> CheckResult:
    """Opt-in ``SHOW BINARY LOGS`` projection; missing privilege (1227) is UNKNOWN."""
    try:
        rows = list(rows_fn())
        total = sum(int(r["File_size"]) for r in rows)
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        args = getattr(exc, "args", ())
        code = args[0] if args and isinstance(args[0], int) else None
        reason = "BINLOG_PRIVILEGE" if code == _ERR_PRIVILEGE else "BINLOG_QUERY_FAILED"
        return _check("ops.binlog", CheckState.UNKNOWN, reason)
    return _check(
        "ops.binlog",
        CheckState.UNKNOWN,
        "FIRST_SAMPLE",
        counts={"files": len(rows), "total_bytes": total},
    )


# ------------------------------------------------------------------ entry


def evaluate(
    policy: OpsPolicy | Mapping[str, Any] | None,
    *,
    now: datetime,
    disk_usage_fn: Callable[[str], Any] = shutil.disk_usage,
    state_root: Path | None = None,
    attested: bool = False,
) -> list[CheckResult]:
    """All ops checks. ``state_root`` enables binlog sampling (read-only audits)."""
    pol = policy if isinstance(policy, OpsPolicy) else OpsPolicy(**(policy or {}))
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # The backup task and restore proof need an owner attestation the code cannot
    # verify, so they are never reported healthy from here.
    reason = "ATTEST_REF_UNVERIFIED" if attested else "OPS_ATTEST_MISSING"
    return [
        disk_check(pol, disk_usage_fn),
        backup_check(pol, now),
        binlog_check(pol, now, state_root),
        _check("ops.backup_task", CheckState.NOT_EVALUATED, reason, required=False),
        _check("ops.restore_proof", CheckState.NOT_EVALUATED, reason, required=False),
    ]


__all__ = ["OPS_CHECKS", "OpsPolicy", "evaluate"]
