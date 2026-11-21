"""One provenance and data-state model for every widget endpoint (#1269).

Every Portfolio Intelligence widget response says where its data came from
and how much to trust it, in the shape Workspace accepts for its type:

=============  ==============================================================
Widget type    Where the state lives
=============  ==============================================================
``chart``      ``layout.meta`` (``state``, ``source``, ``asOf``, ``reason``)
               plus an annotation for every state except ``live``
``table``      three string columns on every row: ``data_state``,
               ``data_source``, ``data_as_of`` (Workspace shows every row key
               as a column; ``columnsDefs`` only labels and orders them)
``metric``     a trailing ``Data State`` card, ``"<State>: <reason>"``
``markdown``   a closing ``**Data state:** <State>`` line in words
``raw=true``   the same three row columns as a table, so agents see it too
=============  ==============================================================

The backend also sends ``X-PI-Data-State`` / ``X-PI-Data-Source`` /
``X-PI-Data-As-Of`` headers, taken from the same per-request record, so the
header can never disagree with the body. Auth and permission denials stay
HTTP 401/403 errors (state ``forbidden``, header only); they never carry data.

``as_of`` is only set when it is observed: a snapshot's session date, a
probe's check time, or the UTC time this backend read its own state
(configuration, engine capabilities, an echoed parameter). Provider tiers do
not report when their data was observed, so their rows say ``unknown``
rather than an invented time. ``fmp_cached`` serves persisted provider
responses of unobservable age, so it is ``cached``, never ``live``.

Demo data is explicit (plan Step 6.3). ``PI_DEMO_MODE`` selects it:

- ``fallback`` (default): the stub answers when no provider does, always
  labelled ``demo`` in the body and headers.
- ``off`` (opt-in): no synthetic fallback. When no provider answers, the
  widget is ``unavailable`` with a reason and no sample values. Choosing the
  demo account or basket (``account_id=demo`` / ``basket_id=demo``) is an
  explicit selection and still shows the labelled synthetic book.
- ``only``: onboarding and tests; provider tiers are skipped entirely.
"""

from __future__ import annotations

import functools
import inspect
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

STUB = "stub"
UNKNOWN = "unknown"
#: Source of a response that has no data (demo off, nothing answered).
NO_SOURCE = "none"
DEMO_MODE_ENV = "PI_DEMO_MODE"
DEMO_MODES = ("off", "fallback", "only")
DEMO_OFF_REASON = (
    "no live provider answered and demo data is off (PI_DEMO_MODE=off); select "
    "the demo account or set PI_DEMO_MODE=fallback to see labelled sample data"
)
DATA_STATE_LABEL = "Data State"
ROW_FIELDS = ("data_state", "data_source", "data_as_of")

STATE_HEADER = "x-pi-data-state"
SOURCE_HEADER = "x-pi-data-source"
AS_OF_HEADER = "x-pi-data-as-of"


class DataState(str, Enum):
    """The seven data states a widget response can be in."""

    LIVE = "live"
    CACHED = "cached"
    DEMO = "demo"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"

    @property
    def label(self) -> str:
        """Return the user-facing word for the state, e.g. ``Demo``."""
        return self.value.capitalize()


#: States a 200 response body may carry. ``forbidden`` is only ever an HTTP
#: 401/403 error with a header, never a body.
BODY_STATES = frozenset(state.value for state in DataState) - {"forbidden"}
_LABELS = "|".join(state.label for state in DataState if state.value in BODY_STATES)
MARKDOWN_STATE_RE = re.compile(rf"\*\*Data state:\*\* ({_LABELS})\b")
METRIC_STATE_RE = re.compile(rf"^({_LABELS}):")


def now_iso() -> str:
    """Return the current UTC time, the observation time of local state."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Provenance:
    """Where a response's data came from and how much to trust it."""

    state: DataState
    source: str
    reason: str
    as_of: str | None = None

    @property
    def label(self) -> str:
        """Return the user-facing state word."""
        return self.state.label

    def summary(self) -> str:
        """Return ``"<State>: <reason>"`` (the metric card text)."""
        return f"{self.label}: {self.reason}"

    def meta(self) -> dict[str, str]:
        """Return the chart ``layout.meta`` fields."""
        return {
            "state": self.state.value,
            "source": self.source,
            "asOf": self.as_of or UNKNOWN,
            "reason": self.reason,
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> Provenance:
        """Rebuild the record a figure's ``layout.meta`` carries."""
        as_of = meta.get("asOf")
        return cls(
            state=DataState(meta["state"]),
            source=str(meta.get("source") or STUB),
            reason=str(meta.get("reason") or ""),
            as_of=None if as_of in (None, UNKNOWN) else str(as_of),
        )

    def row_fields(self) -> dict[str, str]:
        """Return the three string columns added to every table/raw row."""
        return {
            "data_state": self.state.value,
            "data_source": self.source,
            "data_as_of": self.as_of or UNKNOWN,
        }

    def markdown(self) -> str:
        """Return the closing Markdown line that states the data state."""
        return (
            f"\n\n---\n\n**Data state:** {self.label} - {self.reason}. "
            f"Source: `{self.source}`; as of {self.as_of or UNKNOWN}."
        )

    def metric_card(self) -> dict[str, str]:
        """Return the trailing ``Data State`` metric card."""
        return {"label": DATA_STATE_LABEL, "value": self.summary()}

    def headers(self) -> dict[str, str]:
        """Return the response headers for this record (ASCII-safe values)."""
        return {
            STATE_HEADER: self.state.value,
            SOURCE_HEADER: self.source,
            AS_OF_HEADER: self.as_of or UNKNOWN,
        }


def state_for_tier(tier: str) -> DataState:
    """Classify the provider tier that served a request.

    ``stub`` is the synthetic fallback (``demo``); a persisted copy
    (``fmp_cached``, a ``*-snapshot`` tier) is ``cached``; every other tier is
    a provider answer (``live``). Shared by endpoint responses and the
    provenance widget.
    """
    if tier == STUB:
        return DataState.DEMO
    if tier == NO_SOURCE:
        return DataState.UNAVAILABLE
    if "cached" in tier or "snapshot" in tier:
        return DataState.CACHED
    return DataState.LIVE


def tier_provenance(tier: str) -> Provenance:
    """Return the record for rows a non-stub provider tier served."""
    if state_for_tier(tier) is DataState.CACHED:
        reason = (
            f"served from persisted provider responses ({tier}); "
            "their age is not reported"
        )
    else:
        reason = f"served by the {tier} provider, which does not report an as-of time"
    return Provenance(state_for_tier(tier), tier, reason)


def demo_mode() -> str:
    """Return the configured demo mode (``fallback`` unless configured)."""
    mode = os.environ.get(DEMO_MODE_ENV, "fallback").strip().lower() or "fallback"
    if mode not in DEMO_MODES:
        raise RuntimeError(f"{DEMO_MODE_ENV} must be one of {DEMO_MODES}")
    return mode


def explicit_demo(params: Mapping[str, Any]) -> bool:
    """Return True when the request explicitly selected the demo book."""
    return "demo" in (params.get("account_id"), params.get("basket_id"))


def gate_demo(record: Provenance, *, explicit: bool) -> tuple[Provenance, bool]:
    """Apply ``PI_DEMO_MODE=off`` to a resolved record.

    Returns ``(record, withheld)``: an unselected ``demo`` record becomes
    ``unavailable`` (source ``none``) and ``withheld`` tells the caller to
    drop the synthetic body.
    """
    if record.state is DataState.DEMO and not explicit and demo_mode() == "off":
        return Provenance(DataState.UNAVAILABLE, NO_SOURCE, DEMO_OFF_REASON), True
    return record, False


def unavailable_row(record: Provenance) -> dict[str, str]:
    """Return the one marker row a table/raw response carries with no data."""
    return {"message": f"Unavailable: {record.reason}", **record.row_fields()}


# ---------------------------------------------------------------------------
# Per-request record
# ---------------------------------------------------------------------------


@dataclass
class RequestProvenance:
    """Mutable per-request record shared by the endpoint and the middleware.

    ``tier`` is set by ``record_tier_used``, ``marked`` by an endpoint that
    knows its own state (unavailable, snapshot freshness), and ``final`` by
    the widget decorator once the response is built.
    """

    tier: str | None = None
    marked: Provenance | None = None
    final: Provenance | None = None


_CURRENT: ContextVar[RequestProvenance | None] = ContextVar(
    "pi_request_provenance", default=None
)


def bind() -> tuple[RequestProvenance, Any]:
    """Start a fresh record for one HTTP request; return it and its token.

    Called by the ASGI middleware. FastAPI runs sync endpoints in a worker
    thread with a *copy* of this context, so the endpoint sees the same
    record object and its writes are visible to the middleware.
    """
    holder = RequestProvenance()
    return holder, _CURRENT.set(holder)


def unbind(token: Any) -> None:
    """Drop the record started by :func:`bind`."""
    _CURRENT.reset(token)


def record_tier(tier: str) -> None:
    """Record the tier that served the current request (no-op outside one)."""
    holder = _CURRENT.get()
    if holder is not None:
        holder.tier = tier


def mark(
    state: DataState,
    reason: str,
    *,
    source: str | None = None,
    as_of: str | None = None,
) -> None:
    """Record a state the endpoint observed itself (e.g. ``unavailable``)."""
    holder = _CURRENT.get()
    if holder is not None:
        holder.marked = Provenance(
            state, source or holder.tier or STUB, reason, as_of=as_of
        )


def mark_unavailable(reason: str) -> None:
    """Record that the endpoint has no real data for these parameters."""
    mark(DataState.UNAVAILABLE, reason)


def published() -> Provenance | None:
    """Return the record the current request's widget published, if any."""
    holder = _CURRENT.get()
    return None if holder is None else holder.final


def publish(provenance: Provenance) -> None:
    """Publish the final record for the current request (read by headers)."""
    holder = _CURRENT.get()
    if holder is not None:
        holder.final = provenance


@contextmanager
def scope() -> Iterator[RequestProvenance]:
    """Give one endpoint call a clean record (reusing the request's, if bound).

    Outside an HTTP request (a direct call, or a route cloned into the MCP
    app without this backend's middleware) a private record is created, so
    the body still carries the state.
    """
    holder = _CURRENT.get()
    token = None
    if holder is None:
        holder = RequestProvenance()
        token = _CURRENT.set(holder)
    else:
        holder.tier = holder.marked = holder.final = None
    try:
        yield holder
    finally:
        if token is not None:
            _CURRENT.reset(token)


def resolve(
    holder: RequestProvenance,
    *,
    demo: str | None = None,
    source: str | None = None,
    reason: str | None = None,
) -> Provenance:
    """Return the record for what the endpoint just served.

    An explicit :func:`mark` wins. Otherwise a provider tier means ``live``
    (or ``cached`` for a snapshot tier); the stub fallback, or an endpoint
    that only has synthetic data, means ``demo`` with the ``demo`` reason; an
    endpoint that reads local backend state (``source``) is ``live`` as of
    the request. An endpoint with none of these is a programming error, never a
    silent default.
    """
    if holder.marked is not None:
        return holder.marked
    tier = holder.tier
    if tier is not None and tier != STUB:
        return tier_provenance(tier)
    if demo is not None:
        return Provenance(DataState.DEMO, STUB, demo)
    if source is not None:
        return Provenance(DataState.LIVE, source, reason or source, as_of=now_iso())
    raise RuntimeError("widget endpoint served no provenance (tier, mark or demo)")


def stamp_rows(rows: Any, provenance: Provenance) -> Any:
    """Return copies of table/raw rows with the provenance columns added.

    Anything that is not a list of objects (a #1271 shape-debt envelope) is
    returned unchanged; the headers still carry its state.
    """
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return rows
    fields = provenance.row_fields()
    return [{**row, **fields} for row in rows]


def _render(kind: str, result: Any, provenance: Provenance, withheld: bool) -> Any:
    if kind == "table":
        if withheld:
            return [unavailable_row(provenance)]
        return stamp_rows(result, provenance)
    if kind == "markdown":
        text = f"**Unavailable:** {provenance.reason}." if withheld else result
        return f"{text}{provenance.markdown()}"
    if kind == "metric":
        cards = [{"label": "Status", "value": "Unavailable"}] if withheld else result
        return [*cards, provenance.metric_card()]
    raise ValueError(f"unknown widget kind {kind!r}")


def widget(
    kind: str,
    *,
    demo: str | None = None,
    source: str | None = None,
    reason: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Stamp a ``table``/``markdown``/``metric`` endpoint's response state.

    Apply directly under ``@app.get``. ``functools.wraps`` keeps the wrapped
    signature and return annotation, so FastAPI's parameters and response
    model are unchanged (every row annotation already admits strings).
    """
    if kind not in {"table", "markdown", "metric"}:
        raise ValueError(f"unknown widget kind {kind!r}")

    def finish(holder: RequestProvenance, result: Any, params: Mapping) -> Any:
        provenance = resolve(holder, demo=demo, source=source, reason=reason)
        provenance, withheld = gate_demo(
            provenance, explicit=holder.marked is not None or explicit_demo(params)
        )
        publish(provenance)
        return _render(kind, result, provenance, withheld)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with scope() as holder:
                    return finish(holder, await func(*args, **kwargs), kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with scope() as holder:
                return finish(holder, func(*args, **kwargs), kwargs)

        return wrapper

    return decorator


def with_state(provenance: Provenance, state: DataState, reason: str) -> Provenance:
    """Return ``provenance`` moved to ``state`` (same source and as-of)."""
    return replace(provenance, state=state, reason=reason)
