"""Logical-operation receipts for Hermes-bound story runs (#1341).

A Hermes model that re-issues a story mutation after an "outcome uncertain"
reply sends a new ``operation_id`` for the same logical operation. The delivery
ledgers (``story_jobs``, ``story_paper_requests``) only collapse repeats of one
``operation_id``, so this ledger adds one more key: the **logical operation
key** (LOK), a hash of the tool, run, workflow digest, stage and argument hash.
The first delivery claims the LOK; later deliveries are pointed back at the
operation that owns it, so one logical operation has one outcome.

Rows hold hashes, identifiers and states only, never argument or payload
values. The ledger lives in the run store's SQLite file and is used only for
Hermes-bound runs (``RunRecord.binding``), so legacy runs keep their semantics.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openbb_mcp_server.story_adapters.registry import RunRecord

LOK_VERSION = 1


def logical_operation_key(
    *,
    tool: str,
    run_id: str,
    workflow_ref: str,
    stage_id: str | None,
    args_sha256: str,
) -> str:
    """Return the logical operation key: SHA-256 of the canonical fields.

    ``workflow_ref`` is the run's full workflow digest, or its manifest version
    for a story run, so the same arguments under another workflow are another
    operation.
    """
    canonical = json.dumps(
        {
            "v": LOK_VERSION,
            "tool": tool,
            "run_id": run_id,
            "workflow_ref": workflow_ref,
            "stage_id": stage_id,
            "args_sha256": args_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def args_digest(*parts: object) -> str:
    """SHA-256 of a canonical JSON list; used to combine existing digests."""
    canonical = json.dumps(list(parts), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Receipt:  # pylint: disable=too-many-instance-attributes
    """One logical operation: which delivery owns it and how often it arrived."""

    principal: str
    logical_key: str
    tool: str
    run_id: str
    workflow_ref: str
    stage_id: str | None
    args_sha256: str
    operation_id: str
    outcome_ref: str | None
    state: str
    deliveries: int
    created_at: str
    updated_at: str
    claimed_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReceiptLedger:
    """``story_receipts``: one row per (principal, logical key)."""

    _COLUMNS = (
        "principal, logical_key, tool, run_id, workflow_ref, stage_id,"
        " args_sha256, operation_id, outcome_ref, state, deliveries,"
        " created_at, updated_at, claimed_at"
    )

    def __init__(self, db_path: Path):
        """Bind the ledger; nothing touches disk until first use."""
        self.db_path = db_path
        self._ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        if not self._ready:
            self.create_table(connection)
        try:
            yield connection
        finally:
            connection.close()

    def create_table(self, connection: sqlite3.Connection) -> None:
        """Create ``story_receipts`` on a caller's connection to the same file."""
        connection.execute(
            "CREATE TABLE IF NOT EXISTS story_receipts ("
            " principal TEXT NOT NULL, logical_key TEXT NOT NULL,"
            " tool TEXT NOT NULL, run_id TEXT NOT NULL,"
            " workflow_ref TEXT NOT NULL, stage_id TEXT,"
            " args_sha256 TEXT NOT NULL, operation_id TEXT NOT NULL,"
            " outcome_ref TEXT, state TEXT NOT NULL,"
            " deliveries INTEGER NOT NULL, created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, claimed_at TEXT,"
            " UNIQUE (principal, logical_key))"
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(story_receipts)")
        }
        if "claimed_at" not in columns:
            # #1341: additive. ``claimed_at`` is when the current owner claimed the
            # key; deliveries leave it alone, so staleness is measurable.
            # A concurrent opener may add it first.
            with contextlib.suppress(sqlite3.OperationalError):
                connection.execute(
                    "ALTER TABLE story_receipts ADD COLUMN claimed_at TEXT"
                )
        connection.execute(
            "UPDATE story_receipts SET claimed_at = created_at"
            " WHERE claimed_at IS NULL"
        )
        self._ready = True

    def get(self, principal: str, logical_key: str) -> Receipt | None:
        """Return the receipt for one logical operation, if any."""
        with self._connect() as connection:
            return self.get_on(connection, principal, logical_key)

    def get_on(
        self, connection: sqlite3.Connection, principal: str, logical_key: str
    ) -> Receipt | None:
        """``get`` on the caller's connection (inside its transaction)."""
        row = connection.execute(
            f"SELECT {self._COLUMNS} FROM story_receipts"  # noqa: S608
            " WHERE principal = ? AND logical_key = ?",
            (principal, logical_key),
        ).fetchone()
        return Receipt(*tuple(row)) if row else None

    def claim(  # pylint: disable=too-many-arguments
        self,
        principal: str,
        logical_key: str,
        *,
        tool: str,
        run_id: str,
        workflow_ref: str,
        stage_id: str | None,
        args_sha256: str,
        operation_id: str,
    ) -> Receipt:
        """Record one delivery; return the receipt, whoever owns it.

        The first delivery inserts the row and owns the operation; every later
        delivery only increments ``deliveries``. The caller compares the
        returned ``operation_id`` with its own to know whether it is a replay.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                receipt = self.claim_on(
                    connection,
                    principal,
                    logical_key,
                    tool=tool,
                    run_id=run_id,
                    workflow_ref=workflow_ref,
                    stage_id=stage_id,
                    args_sha256=args_sha256,
                    operation_id=operation_id,
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return receipt

    def claim_on(  # pylint: disable=too-many-arguments
        self,
        connection: sqlite3.Connection,
        principal: str,
        logical_key: str,
        *,
        tool: str,
        run_id: str,
        workflow_ref: str,
        stage_id: str | None,
        args_sha256: str,
        operation_id: str,
    ) -> Receipt:
        """``claim`` inside the caller's open ``BEGIN IMMEDIATE`` transaction."""
        now = _now()
        connection.execute(
            f"INSERT INTO story_receipts ({self._COLUMNS})"  # noqa: S608
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'claimed', 0, ?, ?, ?)"
            " ON CONFLICT (principal, logical_key) DO NOTHING",
            (
                principal,
                logical_key,
                tool,
                run_id,
                workflow_ref,
                stage_id,
                args_sha256,
                operation_id,
                now,
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE story_receipts SET deliveries = deliveries + 1,"
            " updated_at = ? WHERE principal = ? AND logical_key = ?",
            (now, principal, logical_key),
        )
        receipt = self.get_on(connection, principal, logical_key)
        assert receipt is not None  # noqa: S101  # inserted or already present
        return receipt

    def record_outcome(
        self,
        principal: str,
        logical_key: str,
        *,
        operation_id: str,
        outcome_ref: str,
        state: str,
    ) -> None:
        """Attach the outcome (job, request or artifact ID) to its owner."""
        with self._connect() as connection:
            self.record_outcome_on(
                connection,
                principal,
                logical_key,
                operation_id=operation_id,
                outcome_ref=outcome_ref,
                state=state,
            )

    @staticmethod
    def record_outcome_on(  # pylint: disable=too-many-arguments
        connection: sqlite3.Connection,
        principal: str,
        logical_key: str,
        *,
        operation_id: str,
        outcome_ref: str,
        state: str,
    ) -> bool:
        """``record_outcome`` on the caller's connection; ``True`` if still owner."""
        cursor = connection.execute(
            "UPDATE story_receipts SET outcome_ref = ?, state = ?,"
            " updated_at = ? WHERE principal = ? AND logical_key = ?"
            " AND operation_id = ?",
            (outcome_ref, state, _now(), principal, logical_key, operation_id),
        )
        return cursor.rowcount == 1

    def supersede(
        self,
        principal: str,
        logical_key: str,
        *,
        previous_operation_id: str,
        operation_id: str,
    ) -> bool:
        """Hand the logical operation to a new delivery after a terminal failure.

        Compare-and-set on the previous owner, so two concurrent retries of a
        failed operation produce one new owner. Returns ``True`` if this caller
        is now the owner.
        """
        with self._connect() as connection:
            return self.supersede_on(
                connection,
                principal,
                logical_key,
                previous_operation_id=previous_operation_id,
                operation_id=operation_id,
            )

    @staticmethod
    def supersede_on(
        connection: sqlite3.Connection,
        principal: str,
        logical_key: str,
        *,
        previous_operation_id: str,
        operation_id: str,
    ) -> bool:
        """``supersede`` on the caller's connection (compare-and-set)."""
        now = _now()
        cursor = connection.execute(
            "UPDATE story_receipts SET operation_id = ?, outcome_ref = NULL,"
            " state = 'claimed', updated_at = ?, claimed_at = ?"
            " WHERE principal = ? AND logical_key = ? AND operation_id = ?",
            (
                operation_id,
                now,
                now,
                principal,
                logical_key,
                previous_operation_id,
            ),
        )
        return cursor.rowcount == 1

    def for_run(self, principal: str, run_id: str) -> list[Receipt]:
        """Every receipt of one run, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {self._COLUMNS} FROM story_receipts"  # noqa: S608
                " WHERE principal = ? AND run_id = ? ORDER BY created_at, tool",
                (principal, run_id),
            ).fetchall()
        return [Receipt(*row) for row in rows]


def run_workflow_ref(record: RunRecord) -> str:
    """Return the run's workflow: its full digest, else its manifest version."""
    return record.workflow_manifest_sha256 or record.manifest_version
