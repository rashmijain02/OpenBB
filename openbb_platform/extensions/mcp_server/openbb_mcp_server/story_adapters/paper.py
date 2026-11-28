"""Human-approved paper actions in isolated story sandboxes (#2331, N09a).

Routes under ``/api/v1/story``:

- ``POST /runs/{run_id}/paper/sandboxes`` and ``GET`` the same path: create
  and list sandboxes. A sandbox is a server-owned paper book for one run of
  one principal; nothing reaches a broker. Its engine is TechTrade's paper
  engine or, with ``engine="portfolio"``, a Portfolio Intelligence paper
  account (:mod:`.paper_portfolio`), which may open with seed positions.
- ``GET /paper/sandboxes/{sandbox_id}``: the book's account and positions,
  with TechTrade's orders and fills or Portfolio's blotter and ledger check.
- ``POST /paper/sandboxes/{sandbox_id}/prepare``: record one typed action and
  return its approval request. Preparing changes nothing.
- ``GET /paper/requests/{request_id}``: the request's status.
- ``POST /paper/requests/{request_id}/apply``: apply an approved request.

There is no approve tool. An approval is an HMAC-SHA256 over the stored
request (principal, sandbox, run, action, argument hash, manifest version,
expiry and a one-use nonce) keyed by an operator secret in
``OPENBB_STORY_APPROVAL_KEY``, which the model never sees. A person grants it
with :mod:`.paper_approve`, which shows the stored arguments, not the
caller's description of them. ``apply`` re-checks the signature, the
arguments, the expiry, the run's manifest and the sandbox, consumes the
request once, and records the result, so a re-delivered apply returns the
first result and never applies twice. Without a key, paper actions are off.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from openbb_mcp_server.story_adapters.artifacts import ArtifactStore
from openbb_mcp_server.story_adapters.receipts import (
    Receipt,
    ReceiptLedger,
    args_digest,
    logical_operation_key,
    run_workflow_ref,
)
from openbb_mcp_server.story_adapters.registry import (
    RunStore,
    WorkflowCatalog,
    default_store_path,
    default_workflow_dir,
    ensure_run_open,
    ensure_workflow_current,
)

APPROVAL_KEY_ENV = "OPENBB_STORY_APPROVAL_KEY"
PAPER_ROOT_ENV = "OPENBB_STORY_PAPER_ROOT"
APPROVAL_TTL = timedelta(minutes=15)
MIN_KEY_LENGTH = 32
MAX_SANDBOXES_PER_RUN = 5
SIGNED_FIELDS = (
    "request_id",
    "principal",
    "sandbox_id",
    "run_id",
    "action",
    "argument_sha256",
    "manifest_version",
    "expires_at",
    "nonce",
)
_TOKEN = re.compile(r"^[a-f0-9]{32}$")


class ApprovalMismatch(Exception):
    """The arguments being applied are not the ones that were approved."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def approval_key() -> bytes | None:
    """Return the operator's signing key, or ``None`` when unset or too short."""
    key = os.environ.get(APPROVAL_KEY_ENV, "")
    return key.encode("utf-8") if len(key) >= MIN_KEY_LENGTH else None


def request_signature(key: bytes, request: dict[str, Any]) -> str:
    """HMAC-SHA256 over the signed fields of a stored request."""
    message = json.dumps(
        {field: request[field] for field in SIGNED_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def argument_digest(action: str, arguments: dict[str, Any]) -> str:
    """Hash of the normalized action and arguments."""
    canonical = json.dumps(
        {"action": action, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Actions ----------------------------------------------------------------

_Amount = Annotated[
    Decimal, Field(gt=0, max_digits=20, decimal_places=8, allow_inf_nan=False)
]
# Empty, or not starting with a character a spreadsheet would evaluate.
# Characters that could forge or hide lines in the approval prompt: C0 and C1
# controls, DEL, line and paragraph separators, and bidirectional overrides.
_UNSAFE = r"\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069"
# Empty, or free of those and not starting with a spreadsheet formula lead.
_Text = Annotated[
    str,
    Field(max_length=200, pattern=rf"^(?:[^=+\-@{_UNSAFE}][^{_UNSAFE}]*)?$"),
]
_OrderId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ticket(_Strict):
    """One TechTrade order ticket."""

    symbol: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9./\-]{0,15}$")]
    action: Literal["Buy", "Sell", "BuyToCover", "SellShort"]
    quantity: _Amount
    order_type: Literal["Market", "Limit", "StopLoss", "StopLimit"] = "Market"
    limit_price: _Amount | None = None
    tif: Literal["Day", "GTC", "IOC", "FOK"] = "Day"
    notes: _Text = ""


class Gate(_Strict):
    """One validation gate the batch was checked against."""

    name: _Text
    threshold: _Text
    actual: _Text
    passed: bool


class SubmitBatch(_Strict):
    """Submit a validated batch; every ticket becomes a PENDING order."""

    plan_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    tickets: list[Ticket] = Field(min_length=1, max_length=50)
    verdict_gate_pass: bool
    verdict_gates: list[Gate] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _passed_verdict(self) -> SubmitBatch:
        failed = [gate.name for gate in self.verdict_gates if not gate.passed]
        if not self.verdict_gate_pass or failed:
            raise ValueError(
                "the batch's verdict did not pass"
                + (f" (failed gates: {', '.join(failed)})" if failed else "")
                + "; a failed verdict cannot be submitted"
            )
        return self


class RecordFill(_Strict):
    """Record an operator-reported fill against a submitted order."""

    order_id: _OrderId
    price: _Amount
    filled_qty: _Amount
    at: AwareDatetime
    commission: Annotated[
        Decimal, Field(ge=0, max_digits=20, decimal_places=8, allow_inf_nan=False)
    ] = Decimal("0")


class CancelOrder(_Strict):
    """Cancel a pending or partially filled order."""

    order_id: _OrderId
    reason: _Text = ""


ACTIONS: dict[str, type[_Strict]] = {
    "submit_batch": SubmitBatch,
    "record_fill": RecordFill,
    "cancel_order": CancelOrder,
}
PaperAction = Literal["submit_batch", "record_fill", "cancel_order", "submit_order"]
ENGINES = ("techtrade", "portfolio")


def engine_actions(engine: str) -> dict[str, type[_Strict]]:
    """Return the actions a sandbox of ``engine`` accepts."""
    if engine == "portfolio":
        # pylint: disable=import-outside-toplevel,cyclic-import
        from openbb_mcp_server.story_adapters import paper_portfolio

        return paper_portfolio.ACTIONS
    return ACTIONS


def normalize(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate the arguments of ``action`` and return their canonical form."""
    for engine in ENGINES:
        model = engine_actions(engine).get(action)
        if model is not None:
            return model.model_validate(arguments).model_dump(mode="json")
    raise ValueError(f"Unknown paper action {action!r}.")


# --- Engine -----------------------------------------------------------------


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _techtrade_engine(db_path: Path, starting_cash: Decimal):
    from openbb_techtrade.execution.paper_engine import (  # pylint: disable=import-outside-toplevel
        SqlitePaperEngine,
    )

    return SqlitePaperEngine(db_path, account_id="paper", starting_cash=starting_cash)


def engine_errors() -> tuple[type[Exception], ...]:
    """Exceptions that mean the engine refused the action."""
    from openbb_techtrade.execution.paper_engine import (  # pylint: disable=import-outside-toplevel
        PaperEngineError,
    )

    return (PaperEngineError, ValueError)


def run_action(engine: Any, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Apply one validated action to a TechTrade paper engine."""
    typed = ACTIONS[action].model_validate(arguments)
    if isinstance(typed, SubmitBatch):
        # pylint: disable=import-outside-toplevel
        from openbb_techtrade.execution.order_sink import (
            OrderBatch,
            OrderTicket,
            PlanContext,
            VerdictGate,
        )

        batch = OrderBatch(
            tickets=tuple(
                OrderTicket(**ticket.model_dump()) for ticket in typed.tickets
            ),
            plan_id=typed.plan_id,
            verdict_gate_pass=typed.verdict_gate_pass,
            plan_context=PlanContext(
                verdict_gates=tuple(
                    VerdictGate(**gate.model_dump()) for gate in typed.verdict_gates
                )
            ),
        )
        order_ids = engine.submit_batch(batch, plan_id=typed.plan_id)
        return {"order_ids": order_ids, "batch_sha256": batch.sha256()}
    if isinstance(typed, RecordFill):
        fill = engine.record_fill(
            typed.order_id, typed.price, typed.filled_qty, typed.at, typed.commission
        )
        return {"fill": _plain(fill)}
    assert isinstance(typed, CancelOrder)  # noqa: S101  # ACTIONS is closed
    engine.cancel_order(typed.order_id, typed.reason)
    return {"cancelled": typed.order_id}


def engine_state(engine: Any) -> dict[str, Any]:
    """Account, positions, orders and fills of one paper book."""
    account = _plain(engine.get_account())
    return {
        "account": {
            key: account[key] for key in ("starting_cash", "cash", "realized_pl")
        },
        "positions": [
            {k: v for k, v in p.items() if k != "account_id"}
            for p in _plain(engine.get_positions())
        ],
        "orders": [
            {k: v for k, v in o.items() if k != "account_id"}
            for o in _plain(engine.get_orders())
        ],
        "fills": _plain(engine.get_fills()),
    }


class _TechTradeBook:
    """A TechTrade paper engine behind the sandbox book interface."""

    def __init__(self, engine: Any):
        self.engine = engine
        self.errors = engine_errors()

    def run(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Apply one validated action."""
        return run_action(self.engine, action, arguments)

    def state(self) -> dict[str, Any]:
        """Account, positions, orders and fills."""
        return engine_state(self.engine)

    def close(self) -> None:
        """Close the engine's database."""
        self.engine.close()


# --- Store ------------------------------------------------------------------


def default_paper_root() -> Path:
    """Sandbox location: ``$OPENBB_STORY_PAPER_ROOT`` or the user directory."""
    override = os.environ.get(PAPER_ROOT_ENV)
    if override:
        return Path(override)
    return Path.home() / ".openbb_platform" / "story_paper"


class UnsafeLocation(RuntimeError):
    """A sandbox directory is a link or resolves outside the root."""


class PaperStore:
    """Sandboxes and approval requests, in the run store's SQLite file."""

    def __init__(self, db_path: Path, root: Path):
        """Bind the store; nothing touches disk until first use."""
        self.db_path = db_path
        self.root = root
        self._ready = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open the store, creating its tables on first use."""
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        if not self._ready:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS story_paper_sandboxes ("
                " sandbox_id TEXT PRIMARY KEY, principal TEXT NOT NULL,"
                " run_id TEXT NOT NULL, engine TEXT NOT NULL,"
                " starting_cash TEXT NOT NULL, created_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS story_paper_requests ("
                " request_id TEXT PRIMARY KEY, principal TEXT NOT NULL,"
                " sandbox_id TEXT NOT NULL, run_id TEXT NOT NULL,"
                " action TEXT NOT NULL, arguments TEXT NOT NULL,"
                " argument_sha256 TEXT NOT NULL, manifest_version TEXT NOT NULL,"
                " expires_at TEXT NOT NULL, nonce TEXT NOT NULL,"
                " operation_id TEXT NOT NULL, status TEXT NOT NULL,"
                " result TEXT, error TEXT, created_at TEXT NOT NULL,"
                " UNIQUE (principal, operation_id));"
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(story_paper_requests)")
            }
            # #1341: nullable, so older rows and outstanding approvals stay valid.
            for column in ("superseded_reason", "applying_at"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE story_paper_requests ADD COLUMN {column} TEXT"
                    )
            self._ready = True
        try:
            yield connection
        finally:
            connection.close()

    def sandbox_dir(self, principal: str, sandbox_id: str, *, create: bool) -> Path:
        """Return the sandbox directory, refusing links and escapes."""
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        directory = self.root / ArtifactStore.principal_key(principal) / sandbox_id
        for part in (self.root, directory.parent, directory):
            if part.is_symlink() or _is_junction(part):
                raise UnsafeLocation("A paper sandbox directory is a link.")
            if create and part is not self.root:
                part.mkdir(exist_ok=True)
        expected = self.root.resolve() / directory.relative_to(self.root)
        if directory.resolve() != expected:
            raise UnsafeLocation("A paper sandbox resolves outside its root.")
        return directory

    def engine(
        self,
        principal: str,
        sandbox: sqlite3.Row,
        *,
        create: bool = False,
        seeds: list[SeedLot] | None = None,
    ):
        """Open the sandbox's paper book; ``create`` also opens its account."""
        directory = self.sandbox_dir(principal, sandbox["sandbox_id"], create=create)
        starting_cash = Decimal(sandbox["starting_cash"])
        if sandbox["engine"] != "portfolio":
            return _TechTradeBook(
                _techtrade_engine(directory / "techtrade.sqlite", starting_cash)
            )
        # pylint: disable=import-outside-toplevel,cyclic-import
        from openbb_mcp_server.story_adapters.paper_portfolio import PortfolioBook

        book = PortfolioBook(
            directory,
            user_id=ArtifactStore.principal_key(principal),
            account_id=sandbox["sandbox_id"],
            starting_cash=starting_cash,
        )
        if create:
            book.open_account(
                seeds or [], at=datetime.fromisoformat(sandbox["created_at"])
            )
        return book

    def sandbox(self, principal: str, sandbox_id: str) -> sqlite3.Row | None:
        """Return a sandbox this principal owns."""
        if not _TOKEN.fullmatch(sandbox_id):
            return None
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM story_paper_sandboxes"
                " WHERE sandbox_id = ? AND principal = ?",
                (sandbox_id, principal),
            ).fetchone()

    def request(self, request_id: str, principal: str | None = None):
        """Return a stored request; ``principal=None`` is the approver's view."""
        if not _TOKEN.fullmatch(request_id):
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM story_paper_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None or (principal is not None and row["principal"] != principal):
            return None
        return row


def _is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def signed_view(row: sqlite3.Row) -> dict[str, Any]:
    """Return the fields of a stored request that an approval signs."""
    return {field: row[field] for field in SIGNED_FIELDS}


# --- Routes -----------------------------------------------------------------


class SeedLot(_Strict):
    """A position a Portfolio sandbox opens with."""

    symbol: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9./\-]{0,15}$")]
    quantity: _Amount
    avg_cost: _Amount


class SandboxCreate(_Strict):
    """A new paper book for one run; a Portfolio book may hold seed lots."""

    engine: Literal["techtrade", "portfolio"] = "techtrade"
    starting_cash: Annotated[
        Decimal, Field(gt=0, le=1_000_000_000, decimal_places=2, allow_inf_nan=False)
    ] = Decimal("100000")
    initial_positions: list[SeedLot] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _seeds_fit_the_engine(self) -> SandboxCreate:
        if self.initial_positions and self.engine != "portfolio":
            raise ValueError("only a portfolio sandbox opens with positions")
        symbols = [seed.symbol for seed in self.initial_positions]
        if len(set(symbols)) != len(symbols):
            raise ValueError("each seed position needs its own symbol")
        return self


class Prepare(_Strict):
    """One action to prepare for approval."""

    operation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    action: PaperAction
    arguments: dict[str, Any] = Field(default_factory=dict)


class Apply(_Strict):
    """An approval and the exact action it approves."""

    approval: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    action: PaperAction
    arguments: dict[str, Any] = Field(default_factory=dict)


def withdraw_pending_requests(
    db_path: Path, principal: str, run_id: str
) -> dict[str, int]:
    """Withdraw a run's ``pending`` requests; count ``applying`` ones left alone.

    Used by ``story_run_cancel`` (#1341). A withdrawn request can never be
    applied: apply only claims ``pending`` rows. An ``applying`` request is
    never touched, because its engine call may already have taken effect.
    """
    counts = {"withdrawn": 0, "applying": 0}
    if not db_path.exists():
        return counts
    connection = sqlite3.connect(db_path, isolation_level=None, timeout=30)
    try:
        has_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'story_paper_requests'"
        ).fetchone()
        if has_table is None:
            return counts
        counts["withdrawn"] = connection.execute(
            "UPDATE story_paper_requests SET status = 'withdrawn'"
            " WHERE principal = ? AND run_id = ? AND status = 'pending'",
            (principal, run_id),
        ).rowcount
        counts["applying"] = connection.execute(
            "SELECT COUNT(*) FROM story_paper_requests"
            " WHERE principal = ? AND run_id = ? AND status = 'applying'",
            (principal, run_id),
        ).fetchone()[0]
    finally:
        connection.close()
    return counts


def _sandbox_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sandbox_id": row["sandbox_id"],
        "run_id": row["run_id"],
        "engine": row["engine"],
        "starting_cash": row["starting_cash"],
        "created_at": row["created_at"],
    }


def _request_view(row: sqlite3.Row) -> dict[str, Any]:
    view = {
        key: row[key]
        for key in (
            "request_id",
            "sandbox_id",
            "run_id",
            "action",
            "argument_sha256",
            "manifest_version",
            "expires_at",
            "nonce",
            "operation_id",
            "status",
        )
    }
    if (
        view["status"] == "pending"
        and datetime.fromisoformat(row["expires_at"]) <= _now()
    ):
        # Derived, never stored: a new prepare and a new decision are needed.
        view["status"] = "expired"
    view["arguments"] = json.loads(row["arguments"])
    view["result"] = json.loads(row["result"]) if row["result"] else None
    view["error"] = row["error"]
    return view


def _unprocessable(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        detail: Any = error.errors(
            include_url=False, include_context=False, include_input=False
        )
    else:
        detail = str(error)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def build_router(  # pylint: disable=too-many-statements
    runs: RunStore,
    store: PaperStore,
    principal: str,
    workflows: WorkflowCatalog | None = None,
) -> APIRouter:
    """Return the paper routes bound to one principal."""
    workflow_catalog = workflows or WorkflowCatalog(default_workflow_dir())
    router = APIRouter(prefix="/api/v1/story", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]
    receipts = ReceiptLedger(store.db_path)

    def _live(row: sqlite3.Row) -> bool:
        """Return whether a re-issued prepare should get this request back."""
        if row["status"] in ("applying", "applied"):
            return True
        return row["status"] == "pending" and (
            datetime.fromisoformat(row["expires_at"]) > _now()
        )

    def _logical_replay(
        run, request: Prepare, sandbox_id: str, digest: str
    ) -> tuple[str, sqlite3.Row | None]:
        """On a bound run, return the live request a re-issued prepare made.

        Returns ``(logical_key, row)``; ``row`` is ``None`` when this delivery
        owns the logical operation and should create a request. An expired,
        failed or missing owner hands the operation to this delivery, so the
        human is asked again with a new request and nonce.
        """
        args_sha256 = args_digest(digest, sandbox_id)
        logical_key = logical_operation_key(
            tool="story_paper_prepare",
            run_id=run.run_id,
            workflow_ref=run_workflow_ref(run),
            stage_id=None,
            args_sha256=args_sha256,
        )
        receipt: Receipt | None = receipts.claim(
            principal,
            logical_key,
            tool="story_paper_prepare",
            run_id=run.run_id,
            workflow_ref=run_workflow_ref(run),
            stage_id=None,
            args_sha256=args_sha256,
            operation_id=request.operation_id,
        )
        while receipt is not None and receipt.operation_id != request.operation_id:
            with store.connect() as connection:
                owner = connection.execute(
                    "SELECT * FROM story_paper_requests"
                    " WHERE principal = ? AND operation_id = ?",
                    (principal, receipt.operation_id),
                ).fetchone()
            if owner is not None and _live(owner):
                return logical_key, owner
            if receipts.supersede(
                principal,
                logical_key,
                previous_operation_id=receipt.operation_id,
                operation_id=request.operation_id,
            ):
                break
            receipt = receipts.get(principal, logical_key)
        return logical_key, None

    def _route(method: str, path: str, name: str):
        return getattr(router, method)(
            path,
            operation_id=name,
            dependencies=authenticated,
            openapi_extra={"mcp_config": {"name": name}},
        )

    def _key() -> bytes:
        key = approval_key()
        if key is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Paper actions need an approval key of at least {MIN_KEY_LENGTH}"
                f" characters in {APPROVAL_KEY_ENV}.",
            )
        return key

    def _owned_run(run_id: str, *, mutating: bool = False):
        record = runs.get(principal, run_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        if mutating:
            ensure_workflow_current(record, workflow_catalog)
            ensure_run_open(record)
        return record

    def _supersede(request_id: str, reason: str) -> None:
        """Mark a pending request superseded; its approval can never apply."""
        with store.connect() as connection:
            connection.execute(
                "UPDATE story_paper_requests SET status = 'superseded',"
                " superseded_reason = ? WHERE request_id = ? AND status = 'pending'",
                (reason, request_id),
            )

    def _owned_sandbox(sandbox_id: str) -> sqlite3.Row:
        row = store.sandbox(principal, sandbox_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sandbox.")
        return row

    def _engine(sandbox: sqlite3.Row, *, create: bool = False, seeds=None):
        try:
            return store.engine(principal, sandbox, create=create, seeds=seeds)
        except UnsafeLocation as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    @_route("post", "/runs/{run_id}/paper/sandboxes", "story_paper_sandbox_create")
    def story_paper_sandbox_create(run_id: str, request: SandboxCreate) -> dict:
        """Create an empty, isolated paper book for one run."""
        _owned_run(run_id, mutating=True)
        with store.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM story_paper_sandboxes"
                " WHERE principal = ? AND run_id = ?",
                (principal, run_id),
            ).fetchone()[0]
            if count >= MAX_SANDBOXES_PER_RUN:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"A run holds at most {MAX_SANDBOXES_PER_RUN} paper sandboxes.",
                )
            sandbox_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO story_paper_sandboxes VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sandbox_id,
                    principal,
                    run_id,
                    request.engine,
                    str(request.starting_cash),
                    _now().isoformat(),
                ),
            )
        row = _owned_sandbox(sandbox_id)
        _engine(row, create=True, seeds=request.initial_positions).close()
        return _sandbox_view(row)

    @_route("get", "/runs/{run_id}/paper/sandboxes", "story_paper_sandbox_list")
    def story_paper_sandbox_list(run_id: str) -> list[dict]:
        """List this run's paper sandboxes."""
        _owned_run(run_id)
        with store.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM story_paper_sandboxes WHERE principal = ?"
                " AND run_id = ? ORDER BY created_at",
                (principal, run_id),
            ).fetchall()
        return [_sandbox_view(row) for row in rows]

    @_route("get", "/paper/sandboxes/{sandbox_id}", "story_paper_state")
    def story_paper_state(sandbox_id: str) -> dict:
        """Return a sandbox's account, positions and order history."""
        sandbox = _owned_sandbox(sandbox_id)
        book = _engine(sandbox)
        try:
            return {**_sandbox_view(sandbox), **book.state()}
        finally:
            book.close()

    @_route("post", "/paper/sandboxes/{sandbox_id}/prepare", "story_paper_prepare")
    def story_paper_prepare(sandbox_id: str, request: Prepare) -> dict:
        """Record one action for a person to approve; nothing changes yet."""
        _key()
        sandbox = _owned_sandbox(sandbox_id)
        run = _owned_run(sandbox["run_id"], mutating=True)
        if request.action not in engine_actions(sandbox["engine"]):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"A {sandbox['engine']} sandbox has no action '{request.action}'.",
            )
        try:
            arguments = normalize(request.action, request.arguments)
        except (ValidationError, ValueError) as error:
            raise _unprocessable(error) from error
        digest = argument_digest(request.action, arguments)
        with store.connect() as connection:
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
                return _request_view(existing)
            logical_key = None
            if run.binding is not None:
                logical_key, owner = _logical_replay(run, request, sandbox_id, digest)
                if owner is not None:
                    return {
                        **_request_view(owner),
                        "replay_of": owner["operation_id"],
                    }
            request_id = uuid.uuid4().hex
            now = _now()
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
                    (now + APPROVAL_TTL).isoformat(),
                    secrets.token_hex(16),
                    request.operation_id,
                    "pending",
                    now.isoformat(),
                ),
            )
        if logical_key is not None:
            receipts.record_outcome(
                principal,
                logical_key,
                operation_id=request.operation_id,
                outcome_ref=request_id,
                state="prepared",
            )
        return _request_view(store.request(request_id, principal))

    @_route("get", "/paper/requests/{request_id}", "story_paper_request")
    def story_paper_request(request_id: str) -> dict:
        """Return a prepared request and, once applied, its result."""
        row = store.request(request_id, principal)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request.")
        return _request_view(row)

    @_route("post", "/paper/requests/{request_id}/apply", "story_paper_apply")
    def story_paper_apply(  # noqa: PLR0912  # pylint: disable=too-many-branches
        request_id: str, request: Apply
    ) -> dict:
        """Apply an approved request exactly once."""
        key = _key()
        row = store.request(request_id, principal)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request.")
        if not hmac.compare_digest(
            request.approval, request_signature(key, signed_view(row))
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "The approval does not match this request."
            )
        try:
            arguments = normalize(request.action, request.arguments)
        except (ValidationError, ValueError) as error:
            raise _unprocessable(error) from error
        if (
            request.action != row["action"]
            or argument_digest(request.action, arguments) != row["argument_sha256"]
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "approval_mismatch: these arguments were not the ones approved;"
                " prepare and approve the new action.",
            )
        if row["status"] == "applied":
            return _request_view(row)
        if row["status"] == "applying":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "An earlier apply of this request did not report back; its outcome"
                " is uncertain. Inspect the sandbox before preparing anything new.",
            )
        if row["status"] != "pending":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The request is {row['status']}; prepare and approve a new action.",
            )
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            raise HTTPException(status.HTTP_410_GONE, "The approval has expired.")
        run = _owned_run(row["run_id"])
        try:
            ensure_workflow_current(run, workflow_catalog)
        except HTTPException:
            _supersede(request_id, "workflow_changed")
            raise
        ensure_run_open(run)
        if run.manifest_version != row["manifest_version"]:
            _supersede(request_id, "manifest_changed")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The run's manifest changed since approval; approve again.",
            )
        sandbox = _owned_sandbox(row["sandbox_id"])
        with store.connect() as connection:
            claimed = connection.execute(
                "UPDATE story_paper_requests SET status = 'applying', applying_at = ?"
                " WHERE request_id = ? AND status = 'pending'",
                (_now().isoformat(), request_id),
            ).rowcount
        if claimed != 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The request was applied concurrently."
            )
        book = _engine(sandbox)
        try:
            result = book.run(row["action"], json.loads(row["arguments"]))
        except book.errors as error:
            with store.connect() as connection:
                connection.execute(
                    "UPDATE story_paper_requests SET status = 'failed', error = ?"
                    " WHERE request_id = ?",
                    (str(error)[:1000], request_id),
                )
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)[:1000]
            ) from error
        finally:
            book.close()
        with store.connect() as connection:
            connection.execute(
                "UPDATE story_paper_requests SET status = 'applied', result = ?"
                " WHERE request_id = ?",
                (json.dumps(result, sort_keys=True), request_id),
            )
        return _request_view(store.request(request_id, principal))

    return router


def compose_story_paper_app(
    source_app: FastAPI,
    *,
    principal: str,
    store_path: Path | None = None,
    paper_root: Path | None = None,
    workflow_dir: Path | None = None,
) -> FastAPI:
    """Add the paper routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("Story paper actions require an authenticated principal")
    db_path = store_path if store_path is not None else default_store_path()
    store = PaperStore(
        db_path, paper_root if paper_root is not None else default_paper_root()
    )
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    workflows = WorkflowCatalog(
        workflow_dir if workflow_dir is not None else default_workflow_dir()
    )
    composed.include_router(
        build_router(RunStore(db_path), store, principal, workflows)
    )
    composed.openapi_schema = None
    return composed
