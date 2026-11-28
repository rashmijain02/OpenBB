"""Sanitized structured outcome of one price-warming run (#1344-T02).

The outcome carries codes, enums and counts only. It never holds exception text,
URLs, keys, account data, amounts or symbols (symbols live only in the local
``runs/<run_id>.json`` file written by :func:`write_run_file`).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1
MAX_LINE = 512
_CODE = re.compile(r"^[A-Za-z0-9_:.\-]{1,64}$")


class Outcome(str, Enum):
    """Run outcome. Admission codes map to the matching ``BLOCKED_*`` member."""

    OK = "OK"
    PARTIAL = "PARTIAL"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    DEFERRED_QUOTA = "DEFERRED_QUOTA"
    DEFERRED_RATE_LIMIT = "DEFERRED_RATE_LIMIT"
    CANCELLED_DEADLINE = "CANCELLED_DEADLINE"
    CANCELLED = "CANCELLED"
    BLOCKED_PLAN = "BLOCKED_PLAN"
    BLOCKED_AUTH = "BLOCKED_AUTH"
    BLOCKED_EGRESS = "BLOCKED_EGRESS"
    BLOCKED_PROCESS = "BLOCKED_PROCESS"
    BLOCKED_ABI = "BLOCKED_ABI"
    BLOCKED_MODULE_ORIGIN = "BLOCKED_MODULE_ORIGIN"
    BLOCKED_CONFIG = "BLOCKED_CONFIG"
    BLOCKED_DATABASE = "BLOCKED_DATABASE"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_UNIVERSE = "BLOCKED_UNIVERSE"
    BLOCKED_EMPTY_UNIVERSE = "BLOCKED_EMPTY_UNIVERSE"
    FAILED_INFRA = "FAILED_INFRA"
    PERSIST_FAILED = "PERSIST_FAILED"


EXIT_CODES: dict[Outcome, int] = {
    Outcome.OK: 0,
    Outcome.PARTIAL: 10,
    Outcome.SKIPPED_BUSY: 10,
    Outcome.DEFERRED_QUOTA: 10,
    Outcome.DEFERRED_RATE_LIMIT: 10,
    Outcome.CANCELLED_DEADLINE: 10,
    Outcome.CANCELLED: 10,
    Outcome.BLOCKED_PLAN: 20,
    Outcome.BLOCKED_AUTH: 20,
    Outcome.BLOCKED_EGRESS: 20,
    Outcome.FAILED_INFRA: 30,
    Outcome.PERSIST_FAILED: 30,
    Outcome.BLOCKED_PROCESS: 40,
    Outcome.BLOCKED_ABI: 40,
    Outcome.BLOCKED_MODULE_ORIGIN: 40,
    Outcome.BLOCKED_CONFIG: 40,
    Outcome.BLOCKED_DATABASE: 40,
    Outcome.BLOCKED_POLICY: 40,
    Outcome.BLOCKED_UNIVERSE: 40,
    Outcome.BLOCKED_EMPTY_UNIVERSE: 40,
}


def exit_code_for(outcome: Outcome) -> int:
    """Return the business exit code for an outcome."""
    return EXIT_CODES[outcome]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Counts(_Strict):
    """Symbol counts (never symbols)."""

    requested: int = 0
    skipped: int = 0
    success: int = 0
    failed: int = 0
    deferred: int = 0


class BudgetUse(_Strict):
    """What the transport guard accounted."""

    reserved: int = 0
    sent: int = 0
    bytes: int = 0
    denied: int = 0
    limits: dict[str, int] = Field(default_factory=dict)
    status_classes: dict[str, int] = Field(default_factory=dict)


class FmpSyncOutcome(_Strict):
    """Counts-only run result with a business exit code."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    logical_job: str = "prices"
    mode: str
    started_utc: AwareDatetime
    ended_utc: AwareDatetime
    outcome: Outcome
    data_status: str = "UNVALIDATED"
    target_class: str | None = None
    db_category: str | None = None
    manifest_id: str | None = None
    manifest_sha256: str | None = None
    source_sha: str | None = None
    failed_layer: str | None = None
    findings: tuple[str, ...] = ()
    counts: Counts = Field(default_factory=Counts)
    budget: BudgetUse = Field(default_factory=BudgetUse)

    @field_validator("findings")
    @classmethod
    def _codes_only(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            if not _CODE.match(code):
                raise ValueError("findings must be stable code tokens")
        return tuple(sorted(set(value)))

    @property
    def exit_code(self) -> int:
        """Business exit code (0 ok, 10 partial/deferred/busy, 20 critical, 30 infra, 40 policy)."""
        return EXIT_CODES[self.outcome]

    def to_line(self) -> str:
        """One counts-only JSON line of at most 512 characters."""
        payload: dict[str, Any] = {
            "op": self.logical_job,
            "mode": self.mode,
            "run_id": self.run_id,
            "outcome": self.outcome.value,
            "exit": self.exit_code,
            "data_status": self.data_status,
            "failed_layer": self.failed_layer,
            "findings": list(self.findings)[:8],
            "counts": self.counts.model_dump(),
            "sent": self.budget.sent,
        }
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(line) > MAX_LINE:
            payload["findings"] = payload["findings"][:2]
            line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return line[:MAX_LINE]


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def write_run_file(
    state_root: Path,
    outcome: FmpSyncOutcome,
    *,
    success: list[str],
    failed: list[str],
    deferred: list[str],
) -> bool:
    """Write ``runs/<run_id>.json`` (outcome plus symbol lists; no error text).

    Returns ``False`` when the write fails; the caller maps that to a finding.
    """
    runs = Path(state_root) / "runs"
    target = runs / f"{outcome.run_id}.json"
    tmp = runs / f"{outcome.run_id}.{os.getpid()}.tmp"
    payload = {
        "outcome": json.loads(outcome.model_dump_json()),
        "symbols": {"success": success, "failed": failed, "deferred": deferred},
    }
    try:
        runs.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
    return True
