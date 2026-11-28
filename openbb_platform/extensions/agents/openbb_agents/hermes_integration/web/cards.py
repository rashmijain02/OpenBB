"""Card payloads of the HFP WebUI extension (#1342 T02).

Every card is built from server-stored facts only: ids, states, codes, counts
and the synthetic plan document. No model text and no free-form server
message reaches a card. A missing fact is an explicit unavailable code, never
an empty success. Paper-action approvals stay terminal-only (W3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from openbb_mcp_server.story_adapters.plans import Plan
from openbb_mcp_server.story_adapters.run_outcome import RunOutcome

UnavailableCode = Literal[
    "plan_store_unavailable",
    "plan_not_found",
    "run_unavailable",
    "outcome_unavailable",
    "worker_unavailable",
]
PAPER_APPROVAL = "paper_approval_terminal_only"
# Outcomes after which the run card stops polling.
TERMINAL_OUTCOMES = frozenset(
    {"succeeded", "failed", "cancelled", "partial", "blocked"}
)
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _code(value: object) -> str | None:
    """Pass a server code through; anything that is not a code reads ``unspecified``."""
    if value is None:
        return None
    text = str(value)
    return text if _CODE.fullmatch(text) else "unspecified"


def unavailable(kind: str, code: UnavailableCode, **ids: str) -> dict[str, Any]:
    """Build an explicit unavailable card of ``kind`` carrying only ids and a code."""
    return {
        "kind": kind,
        "state": "unavailable",
        "code": code,
        **ids,
        "paper_approval": PAPER_APPROVAL,
    }


def plan_card(plan: Plan, nonce: str | None, now: datetime) -> dict[str, Any]:
    """Build the plan card: the stored plan document, its hash and its state.

    ``approval_nonce`` is present only while the plan is pending and unexpired.
    """
    state = "expired" if plan.expired(now) else plan.state
    document = plan.plan
    can_approve = state == "pending" and nonce is not None
    return {
        "kind": "plan",
        "state": state,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "workflow_id": plan.workflow_id,
        "version": str(document.get("version", "")),
        "workflow_manifest_sha256": document.get("workflow_manifest_sha256"),
        "inputs": (document.get("inputs") or {}).get("kind"),
        "stages": [stage.get("id") for stage in document.get("stages", [])],
        "capabilities": sorted(document.get("capabilities") or {}),
        "expires_at": plan.expires_at.isoformat(),
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        "run_id": plan.run_id,
        "can_approve": can_approve,
        "approval_nonce": nonce if can_approve else None,
        "paper_approval": PAPER_APPROVAL,
    }


def run_card(  # pylint: disable=too-many-arguments
    *,
    run_id: str,
    plan_id: str | None,
    workflow_id: str | None,
    outcome: RunOutcome | None,
    jobs: Iterable[tuple[str, str]],
    artifacts: Iterable[tuple[str, str, str]],
    worker_unavailable: bool = False,
) -> dict[str, Any]:
    """Build the run/outcome card.

    ``ok`` is true for ``succeeded`` only (never ``partial``). A non-terminal
    run whose job waits with no live worker reads ``worker_unavailable``; the
    card keeps polling, since a worker may come back.
    """
    base: dict[str, Any] = {
        "kind": "run",
        "run_id": run_id,
        "plan_id": plan_id,
        "workflow_id": workflow_id,
        "jobs": [
            {"job_id": job_id, "status": _code(status)} for job_id, status in jobs
        ],
        "artifacts": [
            {"artifact_id": artifact_id, "sha256": sha256, "kind": _code(kind)}
            for artifact_id, sha256, kind in artifacts
        ],
        "paper_approval": PAPER_APPROVAL,
    }
    if outcome is None:
        return {
            **base,
            "state": "unavailable",
            "code": "outcome_unavailable",
            "outcome": None,
            "ok": False,
            "terminal": False,
        }
    terminal = outcome.outcome in TERMINAL_OUTCOMES
    stalled = worker_unavailable and not terminal
    return {
        **base,
        "state": "unavailable" if stalled else "available",
        **({"code": "worker_unavailable"} if stalled else {}),
        "outcome": outcome.outcome,
        "ok": outcome.outcome == "succeeded",
        "terminal": terminal,
        "uncertain": outcome.uncertain,
        "reason": _code(outcome.reason),
        "workflow_current": outcome.workflow_current,
        "stages": {
            str(stage): _code(status) for stage, status in outcome.stages.items()
        },
        "job_counts": {_code(k): v for k, v in outcome.jobs.items()},
    }


def workflows_card(workflows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Starter list: pre-fills the composer with a preview prompt; never auto-sends (W4)."""
    return {
        "kind": "workflows",
        "state": "available",
        "auto_send": False,
        "workflows": [
            {
                "workflow_id": item["workflow_id"],
                "version": item["version"],
                "stages": item["stages"],
                "prompt": (
                    f"Preview the {item['workflow_id']} workflow with synthetic"
                    " inputs using story_plan_preview."
                ),
            }
            for item in workflows
        ],
        "paper_approval": PAPER_APPROVAL,
    }
