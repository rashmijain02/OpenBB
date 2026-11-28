"""Transport-accounted request budget, egress allowlist, deadline and cancellation (#1344-T02).

Accounting happens at ``requests.Session.send`` inside the dispatcher process
only (no provider edit): every FMP request must first reserve one unit against
per-run, per-minute and per-day request limits and a per-day byte cap, kept in a
durable daily ledger under the state root. A refused reservation raises
**before** any socket opens. After the response the status class and body size
are recorded; 429 persists a ``defer_until`` and 402/401/403 stop the run
without retries.

A ``sys.addaudithook`` allowlist (FMP host names, loopback MySQL port only)
refuses everything else while a guard is active, so a run cannot reach an LLM
gateway or any other service; a non-loopback connect without an in-flight
reservation fails closed (``ACCOUNTING_GAP``).

Ledgers hold counts only: no URL, symbol, key or response text.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from portfolio_utils.fmp_sync import locking

REFUSED_PREFIX = "FMPSYNC_REFUSED"
DEFAULT_FMP_HOSTS = ("financialmodelingprep.com",)
DEFAULT_MYSQL_PORT = 3306
DEFAULT_RETRY_AFTER_S = 60.0
MAX_SEND_TIMEOUT_S = 60.0
DEADLINE_RESERVE_S = 5.0
ACCOUNT_LABEL_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"  # no dots or separators
_LABEL = re.compile(ACCOUNT_LABEL_PATTERN)
_LEDGER_LOCK_WAIT_S = 2.0

LIMITS_MISSING = "LIMITS_MISSING"
LIMITS_INVALID = "LIMITS_INVALID"


LEDGER_UNREADABLE = "ledger_unreadable"


class BudgetExhausted(RuntimeError):
    """A reservation was refused before any socket opened."""

    def __init__(self, kind: str):
        super().__init__(f"{REFUSED_PREFIX}:{kind}")
        self.kind = kind


class DeadlineExceeded(RuntimeError):
    """No time left for another request."""

    def __init__(self) -> None:
        super().__init__(f"{REFUSED_PREFIX}:deadline")


class EgressDenied(RuntimeError):
    """A connection outside the allowlist (or without a reservation) was refused."""

    def __init__(self, code: str = "EGRESS"):
        super().__init__("egress denied")
        self.code = code


class Limits(BaseModel):
    """Operator-supplied quota limits. There is no built-in default (D5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    per_run: int = Field(gt=0)
    per_minute: int = Field(gt=0)
    per_day: int = Field(gt=0)
    bytes_per_day: int = Field(gt=0)

    @classmethod
    def from_map(
        cls, raw: Mapping[str, int] | None
    ) -> tuple[Limits | None, str | None]:
        """Return ``(limits, None)`` or ``(None, finding_code)``."""
        if not raw:
            return None, LIMITS_MISSING
        try:
            return cls.model_validate(dict(raw)), None
        except ValidationError:
            return None, LIMITS_INVALID


# ------------------------------------------------------------------ ledger

_LEDGER_THREAD_LOCK = threading.Lock()


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    for attempt in range(6):
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def _read_json(path: Path) -> dict:
    """Read a ledger file; a missing file is empty, anything unreadable fails closed.

    Counters are never reset: a corrupt or unreadable ledger raises
    ``BudgetExhausted("ledger_unreadable")`` and is left untouched.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise BudgetExhausted(LEDGER_UNREADABLE) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:  # includes UnicodeDecodeError
        raise BudgetExhausted(LEDGER_UNREADABLE) from exc
    if not isinstance(data, dict):
        raise BudgetExhausted(LEDGER_UNREADABLE)
    return data


class BudgetLedger:
    """Durable daily request/byte ledger under ``<state>/budget/<label>/``."""

    def __init__(
        self,
        state_root: Path,
        account_label: str,
        limits: Limits,
        *,
        now_fn: Callable[[], float] = time.time,
    ):
        if not _LABEL.fullmatch(account_label):
            raise ValueError("invalid account label")
        self.dir = Path(state_root) / "budget" / account_label
        self.limits = limits
        self.now = now_fn
        self.run_reserved = 0

    def _day_path(self, now: float) -> Path:
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        return self.dir / f"{day}.json"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with _LEDGER_THREAD_LOCK:
            # pylint: disable=protected-access
            fd = locking._open_lock_file(self.dir / "ledger.lock")
            deadline = time.monotonic() + _LEDGER_LOCK_WAIT_S
            try:
                while not locking._os_try_lock(fd):
                    if time.monotonic() > deadline:
                        raise BudgetExhausted("ledger")
                    time.sleep(0.02)
                try:
                    yield
                finally:
                    locking._os_unlock(fd)
            finally:
                os.close(fd)

    def _load(self, now: float) -> dict:
        data = _read_json(self._day_path(now))
        data.setdefault("reserved", 0)
        data.setdefault("sent", 0)
        data.setdefault("bytes", 0)
        data.setdefault("status", {})
        data.setdefault("recent", [])
        return data

    def snapshot(self) -> dict:
        """Today's counters plus the persisted ``defer_until``."""
        now = self.now()
        data = self._load(now)
        data["defer_until"] = float(_read_json(self.dir / "defer.json").get("until", 0))
        return data

    def reserve(self) -> None:
        """Reserve one request or raise :class:`BudgetExhausted` (before any socket)."""
        now = self.now()
        limits = self.limits
        with self._locked():
            defer_until = float(_read_json(self.dir / "defer.json").get("until", 0))
            if defer_until > now:
                raise BudgetExhausted("defer")
            data = self._load(now)
            recent = [t for t in data["recent"] if t > now - 60.0]
            if self.run_reserved >= limits.per_run:
                raise BudgetExhausted("per_run")
            if len(recent) >= limits.per_minute:
                raise BudgetExhausted("per_minute")
            if data["reserved"] >= limits.per_day:
                raise BudgetExhausted("per_day")
            if data["bytes"] >= limits.bytes_per_day:
                raise BudgetExhausted("bytes")
            recent.append(now)
            data["recent"] = recent
            data["reserved"] += 1
            data["date"] = self._day_path(now).stem
            _atomic_write_json(self._day_path(now), data)
            self.run_reserved += 1

    def record(self, status: int, nbytes: int) -> None:
        """Record one sent request's status class and body size."""
        now = self.now()
        with self._locked():
            data = self._load(now)
            data["sent"] += 1
            data["bytes"] += max(int(nbytes), 0)
            klass = f"{int(status) // 100}xx"
            data["status"][klass] = data["status"].get(klass, 0) + 1
            _atomic_write_json(self._day_path(now), data)

    def set_defer(self, until: float) -> None:
        """Persist ``defer_until`` (epoch seconds); only ever moves forward."""
        with self._locked():
            current = float(_read_json(self.dir / "defer.json").get("until", 0))
            if until > current:
                _atomic_write_json(self.dir / "defer.json", {"until": until})


# ------------------------------------------------------------------ cancellation


class CancelController:
    """Cooperative cancellation: deadline, budget stop, cancel file or signal."""

    def __init__(
        self,
        run_id: str,
        state_root: Path,
        deadline_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.run_id = run_id
        self.state_root = Path(state_root)
        self.deadline_s = deadline_s
        self._clock = clock
        self._start = clock()
        self.reason: str | None = None
        self.signal_flag = False

    def mark(self, reason: str) -> None:
        """Record why the run is stopping; the first reason wins."""
        if self.reason is None:
            self.reason = reason

    def remaining(self) -> float:
        """Seconds left before the monotonic deadline."""
        return self.deadline_s - (self._clock() - self._start)

    def should_cancel(self) -> bool:
        """Poll for cancellation (called between symbols by the warmer)."""
        if self.reason is not None:
            return True
        if self.signal_flag:
            self.mark("SIGNAL")
        elif self.remaining() <= 0:
            self.mark("DEADLINE")
        elif (self.state_root / "cancel" / self.run_id).exists():
            self.mark("CANCEL")
        return self.reason is not None


# ------------------------------------------------------------------ transport guard


class _Registry:
    """Process-wide state for the audit hook (hooks cannot be removed)."""

    active: TransportGuard | None = None
    hook_installed = False


_LOCAL = threading.local()


def _audit_hook(event: str, args: tuple) -> None:
    guard = _Registry.active
    if guard is None:
        return
    if event == "socket.connect":
        guard.check_connect(args[1])
    elif event == "socket.getaddrinfo":
        guard.check_resolve(args[0], args[1])


def _install_hook() -> None:
    if not _Registry.hook_installed:
        sys.addaudithook(_audit_hook)
        _Registry.hook_installed = True


def _is_loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TransportGuard:
    """Context manager wrapping ``requests.Session.send`` with the budget (one process)."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        ledger: BudgetLedger,
        cancel: CancelController,
        allowed_hosts: tuple[str, ...] = DEFAULT_FMP_HOSTS,
        mysql_port: int = DEFAULT_MYSQL_PORT,
        inner_send: Callable[..., requests.Response] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ledger = ledger
        self.cancel = cancel
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self.mysql_port = mysql_port
        self.inner_send = inner_send
        self._clock = clock
        self._original: Callable[..., requests.Response] | None = None
        self.stats: dict[str, Any] = {
            "reserved": 0,
            "sent": 0,
            "bytes": 0,
            "denied": 0,
            "status_classes": {},
        }

    # -- audit hook checks -------------------------------------------------

    def _deny(self, code: str) -> None:
        self.stats["denied"] += 1
        self.cancel.mark("EGRESS" if code == "EGRESS" else "ACCOUNTING_GAP")
        raise EgressDenied(code)

    def check_connect(self, address: Any) -> None:
        """Audit ``socket.connect``: loopback MySQL port, or a reserved FMP send."""
        if not isinstance(address, tuple) or len(address) < 2:
            self._deny("EGRESS")
        host, port = address[0], _port(address[1])
        if _is_loopback(host):
            if port != self.mysql_port:
                self._deny("EGRESS")
            return
        if not getattr(_LOCAL, "inflight", False):
            self._deny("ACCOUNTING_GAP")

    def check_resolve(self, host: Any, port: Any) -> None:
        """Audit ``socket.getaddrinfo``: FMP names and loopback MySQL only."""
        if isinstance(host, bytes):
            host = host.decode("ascii", "ignore")
        if isinstance(host, str) and host.lower() in self.allowed_hosts:
            return
        if _is_loopback(host) and _port(port) == self.mysql_port:
            return
        self._deny("EGRESS")

    # -- send wrapper ------------------------------------------------------

    def _cap_timeout(self, original: Any, remaining: float) -> Any:
        cap = max(min(MAX_SEND_TIMEOUT_S, remaining - DEADLINE_RESERVE_S), 0.1)
        if isinstance(original, tuple):
            return tuple(min(x, cap) if x is not None else cap for x in original)
        return cap if original is None else min(original, cap)

    def _note_status(self, response: requests.Response) -> None:
        status = response.status_code
        if status == 429:
            retry = DEFAULT_RETRY_AFTER_S
            header = response.headers.get("Retry-After", "")
            try:
                retry = max(float(header), 1.0)
            except ValueError:
                with contextlib.suppress(TypeError, ValueError):
                    parsed = parsedate_to_datetime(header)
                    retry = max(
                        parsed.timestamp() - self.ledger.now(), 1.0
                    )  # pylint: disable=protected-access
            self.ledger.set_defer(
                self.ledger.now() + retry
            )  # pylint: disable=protected-access
            self.cancel.mark("RATE_LIMIT")
        elif status == 402:
            self.cancel.mark("PLAN")
        elif status in (401, 403):
            self.cancel.mark("AUTH")

    def send_wrapped(
        self, session: Any, request: Any, **kwargs: Any
    ) -> requests.Response:
        """Account, cap and forward one ``Session.send`` (raises before any socket)."""
        host = (urlsplit(str(request.url)).hostname or "").lower()
        if host not in self.allowed_hosts:
            self._deny("EGRESS")
        if self.cancel.reason in ("PLAN", "AUTH"):
            raise BudgetExhausted(self.cancel.reason.lower())
        remaining = self.cancel.remaining()
        if remaining - DEADLINE_RESERVE_S <= 0:
            self.cancel.mark("DEADLINE")
            raise DeadlineExceeded()
        try:
            self.ledger.reserve()
        except BudgetExhausted as exc:
            if exc.kind == LEDGER_UNREADABLE:
                self.cancel.mark("LEDGER")
            else:
                self.cancel.mark("RATE_LIMIT" if exc.kind == "defer" else "QUOTA")
            raise
        self.stats["reserved"] += 1
        kwargs["timeout"] = self._cap_timeout(kwargs.get("timeout"), remaining)
        inner = self.inner_send or self._original
        if inner is None:
            raise RuntimeError("transport guard used outside its context")
        self.stats["sent"] += 1
        _LOCAL.inflight = True
        try:
            response = inner(session, request, **kwargs)
        finally:
            _LOCAL.inflight = False
        try:
            nbytes = len(response.content)
        except Exception:  # noqa: BLE001  pylint: disable=broad-exception-caught
            nbytes = 0
        self.stats["bytes"] += nbytes
        klass = f"{response.status_code // 100}xx"
        classes = self.stats["status_classes"]
        classes[klass] = classes.get(klass, 0) + 1
        self.ledger.record(response.status_code, nbytes)
        self._note_status(response)
        return response

    def __enter__(self) -> TransportGuard:
        """Patch ``requests.Session.send`` and activate the egress allowlist."""
        self._original = requests.Session.send
        guard = self

        def _patched(session: Any, request: Any, **kwargs: Any) -> requests.Response:
            return guard.send_wrapped(session, request, **kwargs)

        requests.Session.send = _patched  # type: ignore[method-assign,assignment]
        _install_hook()
        _Registry.active = self
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """Restore ``requests.Session.send`` and deactivate the allowlist."""
        _Registry.active = None
        if self._original is None:
            raise RuntimeError("transport guard exited without being entered")
        requests.Session.send = self._original  # type: ignore[method-assign]
