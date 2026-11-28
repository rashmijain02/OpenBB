"""Durable status snapshot and append-only receipts for price warming (#1344-T03).

``status.json`` holds the last recorded fingerprint; ``history.jsonl`` is an
append-only log of run-start, run-end and state-transition receipts. Records carry
codes, enums and counts only (never symbols, paths or exception text).

Replacing ``status.json`` uses tmp-then-``os.replace``. On Windows the replace can
fail with a sharing violation while a reader holds the file without
``FILE_SHARE_DELETE``; it is retried with backoff and, on exhaustion, reported as
``PERSIST_FAILED`` while the previous snapshot stays untouched. The old snapshot is
never unlinked.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_utils.fmp_sync.outcome import FmpSyncOutcome, Outcome, utcnow

REPLACE_ATTEMPTS = 8
BACKOFF_BASE_S = 0.05
BACKOFF_MAX_S = 1.0
STATUS_NAME = "status.json"
HISTORY_NAME = "history.jsonl"
HISTORY_KEYS = (
    "v",
    "kind",
    "run_id",
    "ts",
    "mode",
    "outcome",
    "exit",
    "fingerprint",
    "previous",
    "previous_outcome",
    "findings",
    "counts",
    "sent",
)
_ACL_WINERROR = 5
# The wrapper cannot see Hermes delivery: it is never inferred and never re-runs.
DELIVERY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class PersistResult:
    """Result of one atomic replacement."""

    ok: bool
    code: str | None = None
    attempts: int = 0


@dataclass(frozen=True)
class Receipt:
    """What the end-of-run recording decided."""

    outcome: FmpSyncOutcome  # possibly rewritten to PERSIST_FAILED
    transition: bool
    emit: bool
    persisted: bool


def fingerprint(outcome: FmpSyncOutcome) -> str:
    """Stable hash of the run's health state (not its identity or counts)."""
    material = {
        "outcome": outcome.outcome.value,
        "data_status": outcome.data_status,
        "failed_layer": outcome.failed_layer,
        "findings": list(outcome.findings),
        "db_category": outcome.db_category,
        "target_class": outcome.target_class,
        "manifest_id": outcome.manifest_id,
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def acl_denies_replace(path: Path) -> bool:
    """Return True only when an ACL or the read-only flag forbids replacing ``path``.

    ``os.replace`` onto a file another process holds open without
    ``FILE_SHARE_DELETE`` also fails with WinError 5, so WinError 5 alone is not
    proof of an ACL denial. Probe: opening the target for ``DELETE`` with full
    sharing fails with ERROR_ACCESS_DENIED (5) for an ACL denial and with
    ERROR_SHARING_VIOLATION (32) for a transient open handle.
    """
    if sys.platform != "win32":
        return False
    if path.exists() and not os.access(path, os.W_OK):
        return True  # read-only attribute
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = k32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    # DELETE access; FILE_SHARE_READ|WRITE|DELETE; OPEN_EXISTING; BACKUP_SEMANTICS
    handle = create(str(path), 0x00010000, 0x7, None, 3, 0x02000000, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return ctypes.get_last_error() == _ACL_WINERROR
    k32.CloseHandle(handle)
    return False


def _failure_code(
    error: OSError | None, path: Path, acl_probe: Callable[[Path], bool]
) -> str:
    if getattr(error, "winerror", None) == _ACL_WINERROR and acl_probe(path):
        return "STATE_ACL_DENIED"
    return "STATE_REPLACE_FAILED"


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    replace_fn: Callable[[Any, Any], Any] = os.replace,
    sleep_fn: Callable[[float], Any] = time.sleep,
    attempts: int = REPLACE_ATTEMPTS,
    acl_probe: Callable[[Path], bool] = acl_denies_replace,
) -> PersistResult:
    """Write ``payload`` to ``path`` via a temp file and a retried ``os.replace``."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    last: OSError | None = None
    made = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        for made in range(1, attempts + 1):
            try:
                replace_fn(tmp, path)
                return PersistResult(True, None, made)
            except PermissionError as error:  # sharing violation / ACL
                last = error
                if made < attempts:
                    sleep_fn(min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (made - 1)))
    except OSError as error:
        last = last or error
        made = made or 1
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()  # our own temp file only; the target is never unlinked
    return PersistResult(False, _failure_code(last, path, acl_probe), made)


def read_history(path: Path) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Return parsed records and findings (``HISTORY_TORN_TAIL`` when the tail is torn)."""
    findings: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return records, ()
    if raw and not raw.endswith(b"\n"):
        findings.append("HISTORY_TORN_TAIL")
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            if "HISTORY_TORN_TAIL" not in findings:
                findings.append("HISTORY_TORN_TAIL")
            continue
        if isinstance(row, dict):
            records.append(row)
    return records, tuple(findings)


def _append(path: Path, record: dict[str, Any]) -> bool:
    """Append one JSON line (on its own line even after a torn tail)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        prefix = b""
        if path.exists() and path.stat().st_size:
            with open(path, "rb") as probe:
                probe.seek(-1, os.SEEK_END)
                if probe.read(1) != b"\n":
                    prefix = b"\n"
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with open(path, "ab") as handle:
            handle.write(prefix + line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return False
    return True


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _read_status(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_status(state_root: Path) -> dict[str, Any] | None:
    """Return the last persisted ``status.json`` (``None`` when absent or unreadable)."""
    return _read_status(Path(state_root) / STATUS_NAME)


def record_heartbeat(state_root: Path, *, now: datetime | None = None) -> bool:
    """Stamp ``last_heartbeat_utc`` only; the sync watermarks are never touched."""
    root = Path(state_root)
    current = _read_status(root / STATUS_NAME)
    if current is None:
        return False
    current["last_heartbeat_utc"] = _iso(now or utcnow())
    return atomic_write_json(root / STATUS_NAME, current).ok


def _watermarks(
    previous: dict[str, Any], outcome: FmpSyncOutcome, stamp: str
) -> dict[str, Any]:
    """Per-job watermarks; only a successful execute run advances the sync session."""
    marks: dict[str, Any] = {}
    if previous.get("last_heartbeat_utc") is not None:
        marks["last_heartbeat_utc"] = previous["last_heartbeat_utc"]
    executed = outcome.mode == "execute"
    marks["last_attempt_utc"] = stamp if executed else previous.get("last_attempt_utc")
    session = previous.get("last_successful_sync_session")
    if executed and outcome.outcome is Outcome.OK and outcome.target_session:
        session = max(filter(None, (session, outcome.target_session)))
    marks["last_successful_sync_session"] = session
    validated = executed and outcome.data_status in ("VALIDATED", "WARN")
    marks["last_validation_utc"] = (
        stamp if validated else previous.get("last_validation_utc")
    )
    marks["delivery_state"] = DELIVERY_UNKNOWN
    return marks


def record_start(
    state_root: Path, run_id: str, mode: str, *, now: datetime | None = None
) -> bool:
    """Append a run-start receipt."""
    record = {
        "v": 1,
        "kind": "start",
        "run_id": run_id,
        "mode": mode,
        "ts": _iso(now or utcnow()),
    }
    return _append(Path(state_root) / HISTORY_NAME, record)


def record_end(  # pylint: disable=too-many-locals
    state_root: Path,
    outcome: FmpSyncOutcome,
    *,
    now: datetime | None = None,
    replace_fn: Callable[[Any, Any], Any] = os.replace,
    sleep_fn: Callable[[float], Any] = time.sleep,
) -> Receipt:
    """Record the run end; decide whether the wrapper must print the outcome line."""
    root = Path(state_root)
    stamp = _iso(now or utcnow())
    history = root / HISTORY_NAME
    _records, tail_findings = read_history(history)
    if tail_findings:
        outcome = outcome.model_copy(
            update={"findings": tuple(sorted({*outcome.findings, *tail_findings}))}
        )
    end = {
        "v": 1,
        "kind": "end",
        "run_id": outcome.run_id,
        "ts": stamp,
        "mode": outcome.mode,
        "outcome": outcome.outcome.value,
        "exit": outcome.exit_code,
        "fingerprint": fingerprint(outcome),
        "findings": list(outcome.findings)[:8],
        "counts": outcome.counts.model_dump(),
        "sent": outcome.budget.sent,
    }
    _append(history, end)
    if outcome.outcome is Outcome.SKIPPED_BUSY:
        return Receipt(outcome, False, False, True)  # the lock holder owns status

    previous = _read_status(root / STATUS_NAME)
    current = fingerprint(outcome)
    transition = previous is None or previous.get("fingerprint") != current
    snapshot = {
        "schema_version": 1,
        "fingerprint": current,
        "outcome": outcome.outcome.value,
        "run_id": outcome.run_id,
        "ended_utc": stamp,
        "data_status": outcome.data_status,
        "since_utc": stamp if transition else (previous or {}).get("since_utc", stamp),
        **_watermarks(previous or {}, outcome, stamp),
    }
    result = atomic_write_json(
        root / STATUS_NAME, snapshot, replace_fn=replace_fn, sleep_fn=sleep_fn
    )
    if not result.ok:
        failed = outcome.model_copy(
            update={
                "outcome": Outcome.PERSIST_FAILED,
                "findings": tuple(sorted({*outcome.findings, result.code or "STATE"})),
            }
        )
        _append(
            history,
            {
                "v": 1,
                "kind": "end",
                "run_id": outcome.run_id,
                "ts": stamp,
                "mode": outcome.mode,
                "outcome": Outcome.PERSIST_FAILED.value,
                "exit": failed.exit_code,
                "fingerprint": fingerprint(failed),
                "findings": list(failed.findings)[:8],
            },
        )
        return Receipt(failed, True, True, False)
    if transition:
        _append(
            history,
            {
                "v": 1,
                "kind": "transition",
                "run_id": outcome.run_id,
                "ts": stamp,
                "outcome": outcome.outcome.value,
                "fingerprint": current,
                "previous": (previous or {}).get("fingerprint"),
                "previous_outcome": (previous or {}).get("outcome"),
            },
        )
    return Receipt(outcome, transition, transition, True)
