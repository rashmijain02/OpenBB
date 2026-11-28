"""Budgeted, cancellable dispatcher for guarded price warming (#1344-T02).

``run_prices`` is the single code path behind ``python -m portfolio_utils.fmp_sync
prices``. Order of operations, all under the per-target lock:

1. execute mode needs explicit limits in the deployment map (D5, no default);
2. take the lock (``SKIPPED_BUSY`` on contention, never a wait);
3. ``admit(...)`` (target, universe and, in execute mode, the session probe);
4. holiday upsert through ``current_year + 1`` (D2, execute only, non-deleting);
5. ``run_position_history_warm`` with the transport guard (execute only),
   cooperative cancellation and a monotonic deadline;
6. map the result to a sanitized :class:`FmpSyncOutcome` and write
   ``runs/<run_id>.json``.

Raw provider/warmer output goes to ``os.devnull`` (D6): nothing printed or logged
inside the warm can reach the saved stdout/stderr. Only the outcome line is
emitted by the caller.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import signal
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from portfolio_utils.fmp_sync import locking
from portfolio_utils.fmp_sync.admission import (
    DeploymentMap,
    Mode,
    TargetClass,
    admit,
)
from portfolio_utils.fmp_sync.budget import (
    DEFAULT_FMP_HOSTS,
    DEFAULT_MYSQL_PORT,
    REFUSED_PREFIX,
    BudgetLedger,
    CancelController,
    Limits,
    TransportGuard,
)
from portfolio_utils.fmp_sync.outcome import (
    BudgetUse,
    Counts,
    FmpSyncOutcome,
    Outcome,
    utcnow,
    write_run_file,
)

WARMER_MODULE = "portfolio_utils.fetch_position_history"
DEFAULT_ACCOUNT_LABEL = "default"
_DEFER_REASONS = frozenset(
    {"QUOTA", "RATE_LIMIT", "PLAN", "AUTH", "DEADLINE", "LEDGER"}
)
_REASON_OUTCOME = {
    "PLAN": Outcome.BLOCKED_PLAN,
    "AUTH": Outcome.BLOCKED_AUTH,
    "RATE_LIMIT": Outcome.DEFERRED_RATE_LIMIT,
    "QUOTA": Outcome.DEFERRED_QUOTA,
    "DEADLINE": Outcome.CANCELLED_DEADLINE,
    "CANCEL": Outcome.CANCELLED,
    "SIGNAL": Outcome.CANCELLED,
}


@contextlib.contextmanager
def quiet_output() -> Iterator[None]:
    """Send fd 1/2, ``sys.stdout``/``sys.stderr`` and root log handlers to devnull (D6)."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    saved: list[tuple[int, int]] = []
    null_fd = os.open(os.devnull, os.O_WRONLY)
    root = logging.getLogger()
    handlers = root.handlers[:]
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            try:
                for fd in (1, 2):
                    with contextlib.suppress(OSError):
                        saved.append((fd, os.dup(fd)))
                        os.dup2(null_fd, fd)
                root.handlers = [logging.NullHandler()]
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    yield
            finally:
                root.handlers = handlers
                for fd, copy in saved:
                    os.dup2(copy, fd)
                    os.close(copy)
    finally:
        os.close(null_fd)


_SIGNAL_NAMES = ("SIGINT", "SIGBREAK")
_PENDING = threading.Event()


@contextlib.contextmanager
def pending_signals() -> Iterator[None]:
    """Hold SIGINT/SIGBREAK as a pending cancel for a whole CLI run.

    Installed by ``python -m portfolio_utils.fmp_sync prices`` before the map is
    read, so Ctrl+C / Ctrl+Break during admission does not kill the process
    before the run file and end receipt are written: the warm starts already
    cancelled instead. Previous handlers are restored on exit.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    _PENDING.clear()
    previous = {}

    def _handler(_signum: int, _frame: Any) -> None:
        _PENDING.set()

    for name in (n for n in _SIGNAL_NAMES if hasattr(signal, n)):
        previous[name] = signal.signal(getattr(signal, name), _handler)
    try:
        yield
    finally:
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)
        _PENDING.clear()


@contextlib.contextmanager
def _signal_flag(cancel: CancelController, enabled: bool) -> Iterator[None]:
    """Turn SIGINT/SIGBREAK into the cancel flag (checked between symbols)."""
    if not enabled or threading.current_thread() is not threading.main_thread():
        yield
        return
    names = [n for n in _SIGNAL_NAMES if hasattr(signal, n)]
    previous = {}
    if _PENDING.is_set():
        cancel.signal_flag = True

    def _handler(_signum: int, _frame: Any) -> None:
        cancel.signal_flag = True

    for name in names:
        previous[name] = signal.signal(getattr(signal, name), _handler)
    try:
        yield
    finally:
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)


class _Ctx:  # pylint: disable=too-many-instance-attributes
    """Mutable per-run facts that end up in the outcome."""

    def __init__(self, dmap: DeploymentMap, mode: str, run_id: str, started: Any):
        self.dmap = dmap
        self.mode = mode
        self.run_id = run_id
        self.started = started
        self.findings: list[str] = []
        self.layer: str | None = None
        self.counts = Counts()
        self.budget = BudgetUse()
        self.target_class: str | None = dmap.target_class
        self.db_category: str | None = None
        self.manifest_id: str | None = None
        self.manifest_sha: str | None = None
        self.success: list[str] = []
        self.failed: list[str] = []
        self.deferred: list[str] = []

    def outcome(self, outcome: Outcome, *findings: str) -> FmpSyncOutcome:
        return FmpSyncOutcome(
            run_id=self.run_id,
            mode=self.mode,
            started_utc=self.started,
            ended_utc=utcnow(),
            outcome=outcome,
            target_class=self.target_class,
            db_category=self.db_category,
            manifest_id=self.manifest_id,
            manifest_sha256=self.manifest_sha,
            source_sha=self.dmap.source_sha,
            failed_layer=self.layer,
            findings=(*self.findings, *findings),
            counts=self.counts,
            budget=self.budget,
        )


def _classify(
    ctx: _Ctx, cancel: CancelController, guard: TransportGuard | None, cancelled: bool
) -> FmpSyncOutcome:
    reason = cancel.reason
    if (guard and guard.stats["denied"]) or reason in ("EGRESS", "ACCOUNTING_GAP"):
        ctx.layer = "egress"
        return ctx.outcome(
            Outcome.BLOCKED_EGRESS,
            "ACCOUNTING_GAP" if reason == "ACCOUNTING_GAP" else "EGRESS_DENIED",
        )
    if reason == "LEDGER":
        ctx.layer = "budget"
        return ctx.outcome(Outcome.FAILED_INFRA, "LEDGER_UNREADABLE")
    if reason == "AUTH":
        ctx.layer = "auth"
    if reason in _REASON_OUTCOME:
        return ctx.outcome(_REASON_OUTCOME[reason], f"STOP_{reason}")
    if cancelled:
        return ctx.outcome(Outcome.CANCELLED)
    if ctx.failed:
        return ctx.outcome(Outcome.PARTIAL if ctx.success else Outcome.FAILED_INFRA)
    return ctx.outcome(Outcome.OK)


def _warm(  # pylint: disable=too-many-arguments,too-many-locals
    ctx: _Ctx,
    admitted: tuple[str, ...] | None,
    *,
    dry: bool,
    limits: Limits | None,
    state_root: Path,
    cancel: CancelController,
    inner_send: Callable[..., Any] | None,
    now_fn: Callable[[], float],
    clock: Callable[[], float],
    fetch_one_fn: Callable[..., dict] | None,
    api_key_resolver: Callable[[], str | None] | None,
    holiday_fn: Callable[[int, int, str | None], None] | None,
    readiness_fn: Callable[[list[str], str | None], dict] | None,
    years: int,
) -> FmpSyncOutcome:
    dmap = ctx.dmap
    tool = importlib.import_module(WARMER_MODULE)
    deferred_now: list[str] = []

    def _holidays(start: int, end: int, database: str | None) -> None:
        (holiday_fn or tool.ensure_market_holidays)(
            start, max(end, date.today().year + 1), database
        )

    def _readiness(symbols: list[str], database: str | None) -> dict:
        try:
            return (readiness_fn or tool.check_portfolio_app_readiness)(
                symbols, database
            )
        except Exception:  # noqa: BLE001  pylint: disable=broad-exception-caught
            ctx.findings.append("READINESS_UNAVAILABLE")
            return {}

    def _fetch(symbol: str, **kwargs: Any) -> dict:
        try:
            if fetch_one_fn is not None:
                return fetch_one_fn(symbol, **kwargs)
            return tool._fetch_one_symbol_history(  # pylint: disable=protected-access
                symbol, database=dmap.target, **kwargs
            )
        except Exception:
            if cancel.reason in _DEFER_REASONS:
                deferred_now.append(symbol)
                raise RuntimeError(f"{REFUSED_PREFIX}:deferred") from None
            raise

    guard: TransportGuard | None = None
    stack = contextlib.ExitStack()
    if not dry:
        if limits is None:
            raise ValueError("execute mode requires limits")
        ledger = BudgetLedger(
            state_root,
            dmap.account_label or DEFAULT_ACCOUNT_LABEL,
            limits,
            now_fn=now_fn,
        )
        guard = TransportGuard(
            ledger=ledger,
            cancel=cancel,
            allowed_hosts=tuple(dmap.fmp_hosts or DEFAULT_FMP_HOSTS),
            mysql_port=dmap.mysql_port or DEFAULT_MYSQL_PORT,
            inner_send=inner_send,
            clock=clock,
        )
        stack.enter_context(guard)
    with stack, quiet_output():
        result = tool.run_position_history_warm(
            symbols=list(admitted) if admitted is not None else None,
            years=years,
            database=dmap.target,
            dry_run=dry,
            skip_holiday_prestep=dry,
            holiday_prestep_fn=_holidays,
            fetch_one_fn=None if dry else _fetch,
            api_key_resolver=api_key_resolver
            or tool._resolve_api_key,  # pylint: disable=protected-access
            readiness_fn=_readiness,
            should_cancel=cancel.should_cancel,
        )
    refused = [
        f["symbol"] for f in result.failed if f["error"].startswith(REFUSED_PREFIX)
    ]
    ctx.success = list(result.success)
    ctx.failed = [
        f["symbol"] for f in result.failed if not f["error"].startswith(REFUSED_PREFIX)
    ]
    done = {*ctx.success, *ctx.failed, *refused}
    unattempted = [s for s in (admitted or ()) if s not in done]
    ctx.deferred = [*refused, *(unattempted if result.cancelled else [])]
    ctx.counts = Counts(
        requested=ctx.counts.requested,
        skipped=ctx.counts.skipped,
        success=len(ctx.success),
        failed=len(ctx.failed),
        deferred=len(ctx.deferred),
    )
    if guard is not None:
        ctx.budget = BudgetUse(
            reserved=guard.stats["reserved"],
            sent=guard.stats["sent"],
            bytes=guard.stats["bytes"],
            denied=guard.stats["denied"],
            limits=limits.model_dump() if limits else {},
            status_classes=dict(guard.stats["status_classes"]),
        )
    return _classify(ctx, cancel, guard, result.cancelled)


def run_prices(  # pylint: disable=too-many-arguments,too-many-locals,too-many-return-statements
    dmap: DeploymentMap,
    *,
    mode: Mode,
    requested_class: TargetClass = "disposable",
    run_id: str | None = None,
    admit_kwargs: Mapping[str, Any] | None = None,
    fetch_one_fn: Callable[..., dict] | None = None,
    api_key_resolver: Callable[[], str | None] | None = None,
    holiday_fn: Callable[[int, int, str | None], None] | None = None,
    readiness_fn: Callable[[list[str], str | None], dict] | None = None,
    inner_send: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    now_fn: Callable[[], float] = time.time,
    deadline_s: float = locking.DEFAULT_DEADLINE_S,
    install_signals: bool = False,
    years: int = 5,
) -> FmpSyncOutcome:
    """Run one guarded price warm and return its sanitized outcome."""
    run_id = run_id or uuid.uuid4().hex
    ctx = _Ctx(dmap, mode, run_id, utcnow())
    dry = mode == "dry_run"
    limits: Limits | None = None
    if not dry:
        limits, code = Limits.from_map(dmap.limits)
        if limits is None:
            ctx.layer = "config"
            return ctx.outcome(Outcome.BLOCKED_POLICY, code or "LIMITS_MISSING")
    elif dmap.legacy_selector:
        # The legacy selector reads the symbol list from MySQL; a dry run opens none.
        ctx.layer = "config"
        return ctx.outcome(Outcome.BLOCKED_POLICY, "LEGACY_SELECTOR_REQUIRES_EXECUTE")
    try:
        locking.resolve_lock_database(dmap.target)
    except ValueError:
        ctx.layer = "config"
        return ctx.outcome(Outcome.BLOCKED_CONFIG, "INVALID_TARGET_IDENTIFIER")
    try:
        state_root = locking.validate_state_root(
            Path(dmap.state_root) if dmap.state_root else locking.default_state_root()
        )
        outcome = _locked_run(
            ctx,
            state_root,
            requested_class=requested_class,
            dry=dry,
            limits=limits,
            deadline_s=deadline_s,
            admit_kwargs=admit_kwargs,
            install_signals=install_signals,
            clock=clock,
            now_fn=now_fn,
            inner_send=inner_send,
            fetch_one_fn=fetch_one_fn,
            api_key_resolver=api_key_resolver,
            holiday_fn=holiday_fn,
            readiness_fn=readiness_fn,
            years=years,
        )
    except locking.LockRootRejected:
        ctx.layer = "config"
        return ctx.outcome(Outcome.BLOCKED_CONFIG, "LOCK_ROOT_REJECTED")
    except locking.LockBusy as busy:
        return ctx.outcome(Outcome.SKIPPED_BUSY, "TARGET_LOCK_BUSY", *busy.findings)
    except Exception:  # noqa: BLE001  pylint: disable=broad-exception-caught
        return ctx.outcome(Outcome.FAILED_INFRA, "UNEXPECTED_ERROR")
    if not write_run_file(
        state_root,
        outcome,
        success=ctx.success,
        failed=ctx.failed,
        deferred=ctx.deferred,
    ):
        outcome = outcome.model_copy(
            update={"findings": (*outcome.findings, "RUN_FILE_WRITE_FAILED")}
        )
    return outcome


def _locked_run(  # pylint: disable=too-many-arguments
    ctx: _Ctx,
    state_root: Path,
    *,
    requested_class: TargetClass,
    dry: bool,
    limits: Limits | None,
    deadline_s: float,
    admit_kwargs: Mapping[str, Any] | None,
    install_signals: bool,
    clock: Callable[[], float],
    now_fn: Callable[[], float],
    **warm_kwargs: Any,
) -> FmpSyncOutcome:
    dmap = ctx.dmap
    with locking.target_lock(
        dmap.target,
        root=state_root,
        entrypoint="fmp_sync.dispatcher",
        run_id=ctx.run_id,
        deadline_s=deadline_s,
    ) as handle:
        ctx.findings.extend(handle.findings)
        admission = admit(
            dmap,
            mode="dry_run" if dry else "execute",
            requested_class=requested_class,
            **(admit_kwargs or {}),
        )
        ctx.target_class = admission.target_class or ctx.target_class
        ctx.db_category = admission.db_category
        ctx.manifest_id = admission.manifest_id
        ctx.manifest_sha = admission.manifest_sha256
        ctx.counts = Counts(
            requested=admission.counts.get("requested", 0),
            skipped=admission.counts.get("skipped", 0),
        )
        if not admission.admitted:
            ctx.layer = admission.failed_layer
            try:
                outcome = Outcome(admission.code)
            except ValueError:
                outcome = Outcome.BLOCKED_POLICY
            return ctx.outcome(outcome, *admission.findings)
        ctx.findings.extend(admission.findings)
        cancel = CancelController(ctx.run_id, state_root, deadline_s, clock)
        with _signal_flag(cancel, install_signals):
            return _warm(
                ctx,
                admission.symbols,
                dry=dry,
                limits=limits,
                state_root=state_root,
                cancel=cancel,
                now_fn=now_fn,
                clock=clock,
                **warm_kwargs,
            )
