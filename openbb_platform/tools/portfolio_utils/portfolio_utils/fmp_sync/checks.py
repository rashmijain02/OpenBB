"""Shared check vocabulary for readiness and audits (#1345-T01).

A :class:`CheckResult` carries a state, a stable reason code and integer counts;
never row content, symbols, exception text or paths. :func:`aggregate` folds
the required checks into one ``data_status`` without fabricating health: an
``UNKNOWN`` or ``UNAVAILABLE`` required check can never yield ``VALIDATED``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

_CODE = re.compile(r"^[A-Za-z0-9_:.\-]{1,64}$")


class CheckState(str, Enum):
    """State of one check."""

    OK = "OK"
    WARN = "WARN"
    CRITICAL = "CRITICAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


# Aggregate data_status values, worst first. UNVALIDATED = not (fully) evaluated.
DATA_STATUSES = (
    "BLOCKED",
    "CRITICAL",
    "UNKNOWN",
    "UNVALIDATED",
    "WARN",
    "VALIDATED",
)

_STATE_STATUS = {
    CheckState.BLOCKED: "BLOCKED",
    CheckState.CRITICAL: "CRITICAL",
    CheckState.UNKNOWN: "UNKNOWN",
    CheckState.UNAVAILABLE: "UNKNOWN",
    CheckState.NOT_EVALUATED: "UNVALIDATED",
    CheckState.WARN: "WARN",
    CheckState.OK: "VALIDATED",
}


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class CheckResult(BaseModel):
    """One evaluated (or deliberately not evaluated) check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    state: CheckState
    reason_code: str
    scope: str = "target"
    observed_utc: AwareDatetime = Field(default_factory=utcnow)
    counts: dict[str, int] = Field(default_factory=dict)
    required: bool = True

    @field_validator("check_id", "reason_code", "scope")
    @classmethod
    def _code(cls, value: str) -> str:
        if not _CODE.match(value):
            raise ValueError("check fields must be stable code tokens")
        return value


def aggregate(results: Iterable[CheckResult]) -> str:
    """Worst ``data_status`` over the required checks (``UNVALIDATED`` when none ran)."""
    statuses = [
        _STATE_STATUS[r.state]
        for r in results
        if r.required and r.state is not CheckState.NOT_APPLICABLE
    ]
    if not statuses:
        return "UNVALIDATED"
    return min(statuses, key=DATA_STATUSES.index)


def findings(results: Iterable[CheckResult]) -> tuple[str, ...]:
    """Sorted reason codes of every check that is not ``OK``/``NOT_APPLICABLE``."""
    quiet = (CheckState.OK, CheckState.NOT_APPLICABLE)
    return tuple(sorted({r.reason_code for r in results if r.state not in quiet}))


def state_counts(results: Iterable[CheckResult]) -> dict[str, int]:
    """Count checks per state (states only, for the stdout line)."""
    out: dict[str, int] = {}
    for result in results:
        out[result.state.value] = out.get(result.state.value, 0) + 1
    return dict(sorted(out.items()))
