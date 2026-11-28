"""Logical replay and prepare transaction for paper requests (#1341).

Moved out of :mod:`.paper` to keep that module small. On a run bound to a
workflow, a re-issued ``story_paper_prepare`` is one logical operation: the
receipt ledger claims it, an expired or failed owner is handed over, and the
new request row commits in the same ``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from openbb_mcp_server.story_adapters.receipts import (
    Receipt,
    ReceiptLedger,
    args_digest,
    logical_operation_key,
    run_workflow_ref,
)

if TYPE_CHECKING:
    from openbb_mcp_server.story_adapters.paper import Prepare


@dataclass(frozen=True)
class ReplayContext:
    """What the prepare transaction needs from the router that owns it."""

    principal: str
    receipts: ReceiptLedger
    request_view: Callable[[sqlite3.Row], dict[str, Any]]
    now: Callable[[], datetime]
    ttl: timedelta


def _live(row: sqlite3.Row, now: Callable[[], datetime]) -> bool:
    """Return whether a re-issued prepare should get this request back."""
    if row["status"] in ("applying", "applied"):
        return True
    return row["status"] == "pending" and (
        datetime.fromisoformat(row["expires_at"]) > now()
    )


def _logical_replay(
    connection: sqlite3.Connection,
    run,
    request: Prepare,
    *,
    sandbox_id: str,
    digest: str,
    ctx: ReplayContext,
) -> tuple[str, sqlite3.Row | None]:
    """On a bound run, return the live request a re-issued prepare made.

    Runs inside the caller's ``BEGIN IMMEDIATE`` transaction, which also
    inserts the new request, so the claim and the row commit together.
    Returns ``(logical_key, row)``; ``row`` is ``None`` when this delivery
    owns the logical operation and should create a request. An expired or
    failed owner hands the operation over (the caller marks it
    superseded), so the human is asked again with a new request and nonce.
    A claim without an owner row is in flight, never taken over.
    """
    principal, receipts = ctx.principal, ctx.receipts
    args_sha256 = args_digest(digest, sandbox_id)
    logical_key = logical_operation_key(
        tool="story_paper_prepare",
        run_id=run.run_id,
        workflow_ref=run_workflow_ref(run),
        stage_id=None,
        args_sha256=args_sha256,
    )
    receipt: Receipt = receipts.claim_on(
        connection,
        principal,
        logical_key,
        tool="story_paper_prepare",
        run_id=run.run_id,
        workflow_ref=run_workflow_ref(run),
        stage_id=None,
        args_sha256=args_sha256,
        operation_id=request.operation_id,
    )
    if receipt.operation_id == request.operation_id:
        return logical_key, None
    owner = connection.execute(
        "SELECT * FROM story_paper_requests"
        " WHERE principal = ? AND operation_id = ?",
        (principal, receipt.operation_id),
    ).fetchone()
    if owner is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "outcome_uncertain: an earlier delivery of this prepare is still"
            " in flight; retry shortly.",
        )
    if _live(owner, ctx.now):
        return logical_key, owner
    receipts.supersede_on(
        connection,
        principal,
        logical_key,
        previous_operation_id=receipt.operation_id,
        operation_id=request.operation_id,
    )
    return logical_key, None


def _retire_reprepared(
    connection: sqlite3.Connection, sandbox_id: str, ctx: ReplayContext
) -> None:
    """Supersede this sandbox's expired or failed requests (bound runs).

    A new prepare is the human being asked again: the old request can
    never apply, and the run outcome reads the new one instead.
    """
    now = ctx.now()
    principal = ctx.principal
    rows = connection.execute(
        "SELECT request_id, status, expires_at FROM story_paper_requests"
        " WHERE principal = ? AND sandbox_id = ?"
        " AND status IN ('pending', 'failed')",
        (principal, sandbox_id),
    ).fetchall()
    for row in rows:
        if row["status"] == "failed" or (
            datetime.fromisoformat(row["expires_at"]) <= now
        ):
            connection.execute(
                "UPDATE story_paper_requests SET status = 'superseded',"
                " superseded_reason = 'reprepared'"
                " WHERE request_id = ? AND status = ?",
                (row["request_id"], row["status"]),
            )


def prepare_locked(  # pylint: disable=too-many-arguments
    connection: sqlite3.Connection,
    run,
    sandbox: sqlite3.Row,
    *,
    sandbox_id: str,
    request: Prepare,
    arguments: dict[str, Any],
    digest: str,
    ctx: ReplayContext,
) -> dict | str:
    """Return a replayed view, or the ID of the request this call created."""
    principal, receipts, request_view = ctx.principal, ctx.receipts, ctx.request_view
    existing = connection.execute(
        "SELECT * FROM story_paper_requests"
        " WHERE principal = ? AND operation_id = ?",
        (principal, request.operation_id),
    ).fetchone()
    if existing is not None:
        if (
            existing["argument_sha256"] != digest
            or existing["sandbox_id"] != sandbox_id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Operation '{request.operation_id}' was already prepared"
                " for a different action.",
            )
        return request_view(existing)
    logical_key = None
    if run.binding is not None:
        logical_key, owner = _logical_replay(
            connection, run, request, sandbox_id=sandbox_id, digest=digest, ctx=ctx
        )
        if owner is not None:
            return {
                **request_view(owner),
                "replay_of": owner["operation_id"],
            }
        _retire_reprepared(connection, sandbox_id, ctx)
    request_id = uuid.uuid4().hex
    now = ctx.now()
    connection.execute(
        "INSERT INTO story_paper_requests (request_id, principal,"
        " sandbox_id, run_id, action, arguments, argument_sha256,"
        " manifest_version, expires_at, nonce, operation_id, status,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request_id,
            principal,
            sandbox_id,
            sandbox["run_id"],
            request.action,
            json.dumps(arguments, sort_keys=True),
            digest,
            run.manifest_version,
            (now + ctx.ttl).isoformat(),
            secrets.token_hex(16),
            request.operation_id,
            "pending",
            now.isoformat(),
        ),
    )
    if logical_key is not None and not receipts.record_outcome_on(
        connection,
        principal,
        logical_key,
        operation_id=request.operation_id,
        outcome_ref=request_id,
        state="prepared",
    ):
        # Another delivery owns the operation now: never two live rows.
        connection.execute(
            "UPDATE story_paper_requests SET status = 'superseded',"
            " superseded_reason = 'lost_claim' WHERE request_id = ?",
            (request_id,),
        )
    return request_id
