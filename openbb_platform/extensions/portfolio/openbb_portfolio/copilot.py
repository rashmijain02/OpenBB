"""Custom-copilot backend for OpenBB Workspace (#1794, #1272).

Implements the OpenBB Workspace *agent* HTTP contract so the hosted Workspace
Copilot can be pointed at a **local** backend that answers using the local
``copilot-api`` proxy on ``127.0.0.1:4141`` (GitHub Copilot models exposed as an
OpenAI-compatible API) instead of the OpenBB-hosted LLM.

Two routes, mounted on the portfolio backends (``launch.py`` and the Portfolio
Intelligence widget backend):

* ``GET  /agents.json`` — agent descriptor (name, features, query URL).
* ``POST /query``       — accepts a ``QueryRequest`` and streams the answer back
  as Server-Sent Events.

Capabilities (#1272). The agent advertises only what ``/query`` implements:

* ``streaming`` — always.
* ``widget-dashboard-select`` — only when the host app registered a widget
  capability inventory (:mod:`openbb_portfolio.agent_capabilities`) on
  ``app.state``. The agent then reads the widgets the user selected, through
  Workspace's own ``get_widget_data`` function call (Workspace fetches the
  data with its own connection; this module has no HTTP client and holds no
  backend token). Chart widgets are always read with ``raw=true``. Denied
  widgets (paper orders, job triggers) and widgets outside the inventory are
  refused and never requested; the agent never sets or changes a widget
  parameter. Reads, rows, context and the model call are all bounded.

Every widget's provenance (``data_state`` / ``data_source`` / ``data_as_of``
columns, the ``Data State`` metric card, the Markdown ``Data state`` line or a
figure's ``layout.meta``) is shown to the user as a reasoning step and given
to the model, so answers can say when data is demo, cached or unavailable.
Credentials are never forwarded to the model: the request's ``api_keys`` and
tool tokens are ignored, and credential-like fields and values in widget data
are redacted.

.. note::
    This module intentionally does **not** use ``from __future__ import
    annotations`` — it keeps runtime type resolution simple for the FastAPI
    ``QueryRequest`` body parameter. It is a plain ``fastapi.APIRouter``, not
    an ``openbb_core`` ``Router.command``.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncGenerator, Mapping
from typing import Any

import openai
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from openbb_ai import get_widget_data, message_chunk, reasoning_step
from openbb_ai.models import (
    ClientFunctionCallError,
    DataContent,
    LlmClientFunctionCallResultMessage,
    QueryRequest,
    Widget,
    WidgetRequest,
)
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from openbb_portfolio.agent_capabilities import WidgetCapability
from openbb_portfolio.agent_privacy import redact_text, sanitize

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Identity + descriptor
# ---------------------------------------------------------------------------
COPILOT_ID = "portfolio_copilot_proxy"
COPILOT_NAME = "Portfolio Copilot (local proxy)"
COPILOT_DESCRIPTION = (
    "Answers using your local GitHub Copilot proxy (copilot-api on :4141) "
    "instead of the OpenBB-hosted model. Reads the Portfolio Intelligence "
    "widgets you select, read-only, and says whether their data is live, "
    "cached, demo or unavailable. The selected widget data (account and user "
    "identifiers removed, credentials redacted) is sent to the configured "
    "external model provider (GitHub Copilot by default) to answer. It cannot "
    "place, approve or cancel orders, paper trades or backtests, and it does "
    "not give investment advice."
)
DISCLOSURE = (
    "Selected widget data (identifiers removed, credentials redacted) is sent "
    "to the configured external model provider."
)

# ``app.state`` attribute a host backend sets to its widget inventory
# (``dict[str, WidgetCapability]``). Without it the agent is text-only.
CAPABILITIES_STATE = "agent_widget_capabilities"
# ``app.state`` attribute with the casefolded Workspace ``origin`` names that
# identify the host backend. Widgets from any other origin are refused.
ORIGINS_STATE = "agent_widget_origins"

# Workspace features ``/query`` implements. ``/agents.json`` never advertises
# anything outside this set.
IMPLEMENTED_FEATURES = frozenset({"streaming", "widget-dashboard-select"})

# Bounds on one question.
MAX_WIDGET_READS = 8
MAX_ROWS_PER_WIDGET = 50
MAX_CELL_CHARS = 300
MAX_TEXT_CHARS = 6000
MAX_WIDGET_CHARS = 20000
# Size caps applied before any parsing or sanitizing.
MAX_REQUEST_BYTES = 8_000_000
MAX_PAYLOAD_CHARS = 1_000_000
MAX_NESTED_ITEMS = 200
# Extra characters kept before redaction so a cut never splits a secret.
REDACTION_MARGIN = 512
MAX_CONTEXT_CHARS = 24000
MAX_ANSWER_TOKENS = 1500
DEFAULT_TIMEOUT_SECONDS = 60.0

# A restrained system prompt. The portfolio program guardrails forbid
# buy/sell/hold recommendations, so the copilot describes and explains only.
SYSTEM_PROMPT = (
    "You are the OpenBB Portfolio Copilot. You help the user understand "
    "financial data, portfolios, and single-stock analysis shown in OpenBB "
    "Workspace. Be concise and factual. Never give investment advice or "
    "buy/sell/hold recommendations; surface and explain data instead. "
    "You are read-only: you cannot place, approve, cancel or commit orders, "
    "paper trades, backtests or scans. If asked to, say so and point the user "
    "to the widget's own controls, which need the user's explicit approval."
)

DATA_RULES = (
    "Widget data selected by the user follows. Each widget starts with its "
    "data state. Always tell the user the state of the data you use: 'demo' "
    "is synthetic sample data, not the user's portfolio; 'cached' is served "
    "from a cache (give the as-of date when known); 'stale' and 'partial' are "
    "incomplete; 'unavailable' or 'forbidden' means there is no data, so do "
    "not invent any; 'unknown' means the state could not be determined, so "
    "say so. Use only the numbers shown."
)

_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Configuration (env-overridable — never hardcode secrets)
# ---------------------------------------------------------------------------
def _proxy_base_url() -> str:
    """OpenAI-compatible base URL for the LLM proxy (default copilot-api :4141)."""
    return os.getenv("COPILOT_PROXY_BASE_URL", "http://127.0.0.1:4141/v1")


def _proxy_api_key() -> str:
    """Return the API key sent to the proxy (copilot-api accepts ``copilot``)."""
    return os.getenv("COPILOT_PROXY_API_KEY", "copilot")


def _proxy_model() -> str:
    """Model id requested from the proxy.

    The copilot-api proxy accepts any id and routes to its configured Copilot
    model, so this is mostly a label; override with ``COPILOT_PROXY_MODEL`` to
    target a specific model on a compliant endpoint.
    """
    return os.getenv("COPILOT_PROXY_MODEL", "gpt-4o")


def _proxy_timeout() -> float:
    """Return the wall-clock limit for one model answer, in seconds."""
    raw = os.getenv("COPILOT_PROXY_TIMEOUT_SECONDS", "")
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------
def agents_descriptor(query_url: str, widget_access: bool = False) -> dict:
    """Return the ``/agents.json`` descriptor for this copilot."""
    return {
        COPILOT_ID: {
            "name": COPILOT_NAME,
            "description": COPILOT_DESCRIPTION,
            "endpoints": {"query": query_url},
            "features": {
                "streaming": True,
                "widget-dashboard-select": widget_access,
                "widget-dashboard-search": False,
            },
        }
    }


def _capabilities(app: Any) -> Mapping[str, WidgetCapability] | None:
    """Return the widget inventory the host app registered, if any."""
    caps = getattr(getattr(app, "state", None), CAPABILITIES_STATE, None)
    return caps if isinstance(caps, Mapping) else None


def _origins(app: Any) -> frozenset[str]:
    """Return the casefolded Workspace origins of the host app (none: no reads)."""
    names = getattr(getattr(app, "state", None), ORIGINS_STATE, None) or ()
    return frozenset(str(name).casefold() for name in names)


@router.get("/agents.json", include_in_schema=False)
async def agents_json(request: Request) -> JSONResponse:
    """Serve the agent descriptor.

    The query URL is derived from the incoming request so the descriptor is
    correct regardless of the host/port/scheme the backend is served on.
    Widget access is advertised only when this app has readable widgets.
    """
    base = str(request.base_url).rstrip("/")
    caps = _capabilities(request.app) or {}
    widget_access = any(cap.readable for cap in caps.values())
    return JSONResponse(content=agents_descriptor(f"{base}/query", widget_access))


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
_MD_STATE_RE = re.compile(r"\*\*Data state:\*\*\s*([A-Za-z]+)")
_MD_SOURCE_RE = re.compile(r"Source:\s*`([^`]+)`")
_MD_AS_OF_RE = re.compile(r"as of ([^\s][^\n]*?)\.?\s*$", re.MULTILINE)
_MD_UNAVAILABLE_RE = re.compile(r"\*\*Unavailable:\*\*")


def _provenance(state: Any, source: Any = None, as_of: Any = None) -> dict[str, str]:
    return {
        "state": str(state or _UNKNOWN).strip().lower() or _UNKNOWN,
        "source": str(source or _UNKNOWN),
        "as_of": str(as_of or _UNKNOWN),
    }


def _joined(values: list[Any]) -> str | None:
    unique = list(dict.fromkeys(str(v) for v in values if v not in (None, "")))
    return "/".join(unique) if unique else None


def _rows_provenance(rows: list[Any]) -> dict[str, str]:
    objects = [row for row in rows if isinstance(row, Mapping)]
    for row in objects:
        label = str(row.get("label", ""))
        if label in {"Data State", "Status"} and isinstance(row.get("value"), str):
            return _provenance(row["value"].split(":", 1)[0])
    state = _joined([row.get("data_state") for row in objects])
    if state is None:
        return _provenance(None)
    return _provenance(
        state,
        _joined([row.get("data_source") for row in objects]),
        _joined([row.get("data_as_of") for row in objects]),
    )


def extract_provenance(payload: Any) -> dict[str, str]:
    """Return ``{state, source, as_of}`` from any widget response shape.

    Reads (in this order) a figure's ``layout.meta``, an envelope's ``rows``,
    row ``data_state`` columns, the ``Data State`` metric card, and the
    Markdown ``**Data state:**`` line. Anything else is ``unknown``.
    """
    if isinstance(payload, Mapping):
        layout = payload.get("layout")
        meta = layout.get("meta") if isinstance(layout, Mapping) else None
        if isinstance(meta, Mapping) and meta.get("state"):
            return _provenance(meta.get("state"), meta.get("source"), meta.get("asOf"))
        if isinstance(payload.get("rows"), list):
            return _rows_provenance(payload["rows"])
        if payload.get("data_state"):
            return _rows_provenance([payload])
        return _provenance(None)
    if isinstance(payload, list):
        return _rows_provenance(payload)
    if isinstance(payload, str):
        match = _MD_STATE_RE.search(payload)
        if match:
            source = _MD_SOURCE_RE.search(payload)
            tail = payload[match.end() :]
            as_of = _MD_AS_OF_RE.search(tail)
            return _provenance(
                match.group(1),
                source.group(1) if source else None,
                as_of.group(1).strip() if as_of else None,
            )
        if _MD_UNAVAILABLE_RE.search(payload):
            return _provenance("unavailable")
    return _provenance(None)


def _describe(name: str, provenance: Mapping[str, str]) -> str:
    return (
        f"{name}: {provenance['state']} (source {provenance['source']}, "
        f"as of {provenance['as_of']})"
    )


# ---------------------------------------------------------------------------
# Planning widget reads (first turn)
# ---------------------------------------------------------------------------
def _refusal(widget: Widget, cap: WidgetCapability | None) -> str:
    label = f"{widget.name} (`{widget.widget_id}`)"
    if cap is None:
        return f"I can't read {label}: it is not a widget this agent supports."
    return (
        f"I can't read {label}: {cap.denied_reason}. Paper and execution "
        "actions are separately authorized in the widget itself and are never "
        "run by the agent."
    )


def _from_this_backend(origin: Any, origins: frozenset[str]) -> bool:
    return str(origin or "").casefold() in origins


def plan_widget_reads(
    widgets: list[Widget],
    caps: Mapping[str, WidgetCapability],
    origins: frozenset[str] = frozenset(),
) -> tuple[list[WidgetRequest], list[str]]:
    """Return the bounded, read-only widget requests and the refusal notes.

    The inventory applies only to widgets whose Workspace ``origin`` is one of
    ``origins`` (this backend); widgets from any other backend are refused.
    """
    requests: list[WidgetRequest] = []
    notes: list[str] = []
    skipped = 0
    for widget in widgets:
        if not _from_this_backend(widget.origin, origins):
            notes.append(
                f"I can't read {widget.name} (`{widget.widget_id}`): it comes "
                f"from {widget.origin!r}, not from this backend."
            )
            continue
        cap = caps.get(widget.widget_id)
        if cap is None or not cap.readable:
            notes.append(_refusal(widget, cap))
            continue
        if len(requests) >= MAX_WIDGET_READS:
            skipped += 1
            continue
        params = {param.name: param.current_value for param in widget.params}
        requests.append(
            WidgetRequest(widget=widget, input_arguments=cap.input_args(params))
        )
    if skipped:
        notes.append(
            f"{skipped} more selected widgets were not read (limit of "
            f"{MAX_WIDGET_READS} widgets per question)."
        )
    return requests, notes


# ---------------------------------------------------------------------------
# Building the model context from Workspace's widget data (second turn)
# ---------------------------------------------------------------------------
def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return content


def _payload(item: Any) -> tuple[Any, str | None]:
    """Return ``(payload, error)`` for one ``get_widget_data`` result item."""
    if isinstance(item, ClientFunctionCallError):
        return None, f"{item.error_type}: {item.content}"
    if isinstance(item, DataContent):
        size = sum(len(part.content) for part in item.items)
        if size > MAX_PAYLOAD_CHARS:
            return None, (
                f"payload too large ({size} characters; the agent reads at most "
                f"{MAX_PAYLOAD_CHARS})"
            )
        parsed = [_parse(part.content) for part in item.items]
        return (parsed[0] if len(parsed) == 1 else parsed), None
    return None, "unsupported data format for this agent"


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    if isinstance(value, Mapping):
        return {key: _clip(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item) for item in value]
    return value


def _preclip(value: Any, depth: int = 0) -> Any:
    """Bound nested lists and strings before sanitizing (with a safety margin)."""
    if isinstance(value, str):
        return value[: MAX_CELL_CHARS + REDACTION_MARGIN]
    if isinstance(value, Mapping):
        return {
            key: _preclip(item, depth + 1)
            for key, item in list(value.items())[:MAX_NESTED_ITEMS]
        }
    if isinstance(value, list):
        return [_preclip(item, depth + 1) for item in value[:MAX_NESTED_ITEMS]]
    return value


def _bound(payload: Any) -> tuple[Any, int]:
    """Limit rows (and text) before sanitizing; return it and the row total."""
    if isinstance(payload, str):
        return payload[: MAX_TEXT_CHARS + REDACTION_MARGIN], 0
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        rows = payload["rows"]
        bounded = dict(payload)
        bounded["rows"] = [_preclip(row) for row in rows[:MAX_ROWS_PER_WIDGET]]
        return _preclip(bounded), len(rows)
    if isinstance(payload, list):
        return [_preclip(row) for row in payload[:MAX_ROWS_PER_WIDGET]], len(payload)
    return _preclip(payload), 0


def _render(payload: Any, total: int = 0) -> str:
    """Render sanitized widget data for the model, bounded in size."""
    if isinstance(payload, Mapping) and isinstance(payload.get("layout"), Mapping):
        return "(chart figure without rows; only its data state is available)"
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        payload = payload["rows"]
    if isinstance(payload, list):
        shown = _clip(payload[:MAX_ROWS_PER_WIDGET])
        text = json.dumps(shown, default=str)
        omitted = max(total, len(payload)) - len(shown)
        if omitted > 0:
            text += f"\n({omitted} more rows omitted)"
        return text
    if isinstance(payload, str):
        return payload[:MAX_TEXT_CHARS]
    return json.dumps(_clip(payload), default=str)[:MAX_TEXT_CHARS]


def widget_context(
    message: LlmClientFunctionCallResultMessage,
    caps: Mapping[str, WidgetCapability],
    origins: frozenset[str] = frozenset(),
) -> tuple[str, list[str], list[str]]:
    """Return the model context, provenance lines and omitted widget names.

    Data for a widget outside the inventory or from another backend is
    dropped. Each widget block is capped at ``MAX_WIDGET_CHARS``; a block
    that would push the context past ``MAX_CONTEXT_CHARS`` is left out whole
    and named in the omitted list, so the provenance lines describe exactly
    the widgets the model sees.
    """
    sources = message.input_arguments.get("data_sources") or []
    blocks: list[str] = []
    lines: list[str] = []
    omitted: list[str] = []
    size = 0
    for index, item in enumerate(message.data):
        source = sources[index] if index < len(sources) else {}
        if not isinstance(source, Mapping):
            source = {}
        widget_id = str(source.get("id", ""))
        cap = caps.get(widget_id)
        if (
            cap is None
            or not cap.readable
            or not _from_this_backend(source.get("origin"), origins)
        ):
            logger.warning(
                "copilot dropped data for a widget outside its read inventory: %r",
                widget_id,
            )
            continue
        payload, error = _payload(item)
        if error is not None:
            provenance = _provenance("unavailable", "error")
            body = f"(no data: {redact_text(error)[:MAX_CELL_CHARS]})"
        else:
            payload, total = _bound(payload)
            payload = sanitize(payload)
            provenance = extract_provenance(payload)
            body = _render(payload, total)
        if len(body) > MAX_WIDGET_CHARS:
            body = body[:MAX_WIDGET_CHARS] + "\n(widget data truncated)"
        line = _describe(cap.name, provenance)
        block = f"### {line}\n{body}"
        if size + len(block) > MAX_CONTEXT_CHARS:
            omitted.append(cap.name)
            continue
        size += len(block) + 2
        lines.append(line)
        blocks.append(block)
    if omitted:
        blocks.append(
            "Omitted (context limit; not shown to you): " + ", ".join(omitted) + "."
        )
    return "\n\n".join(blocks), lines, omitted


# ---------------------------------------------------------------------------
# Message mapping
# ---------------------------------------------------------------------------
def _to_openai_messages(messages, context: str | None = None) -> list[dict]:
    """Map the Workspace conversation to OpenAI chat-completion messages.

    ``human`` -> ``user``, ``ai`` -> ``assistant``. Tool/function-call messages
    (non-``str`` content) are skipped; widget data reaches the model only as
    the sanitized ``context``. The system prompt is prepended.
    """
    out: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        out.append({"role": "system", "content": f"{DATA_RULES}\n\n{context}"})
    for message in messages:
        role = getattr(message.role, "value", message.role)
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            continue
        if role == "human":
            out.append({"role": "user", "content": content})
        elif role == "ai":
            out.append({"role": "assistant", "content": content})
        # role == "tool" (and anything else) is intentionally ignored.
    return out


# ---------------------------------------------------------------------------
# Proxy streaming (the seam — monkeypatched in unit tests)
# ---------------------------------------------------------------------------
async def _proxy_deltas(
    openai_messages: list[dict],
    client: Any = None,
) -> AsyncGenerator[str, None]:
    """Yield text deltas from the LLM proxy for the given messages.

    ``client`` is injectable for testing; when omitted a fresh
    ``openai.AsyncOpenAI`` pointed at the proxy is created with a request
    timeout and no retries, and the answer length is capped.
    """
    owns_client = client is None
    if client is None:
        client = openai.AsyncOpenAI(
            base_url=_proxy_base_url(),
            api_key=_proxy_api_key(),
            timeout=_proxy_timeout(),
            max_retries=0,
        )

    # Close a self-created client (and its httpx connection pool) on normal
    # completion, on error, and on cancellation.
    try:
        stream = await client.chat.completions.create(
            model=_proxy_model(),
            messages=openai_messages,
            stream=True,
            max_tokens=MAX_ANSWER_TOKENS,
        )
        async for event in stream:
            if not getattr(event, "choices", None):
                continue
            delta = event.choices[0].delta.content
            if delta:
                yield delta
    finally:
        if owns_client:
            await client.close()


async def _sse_stream(
    messages, context: str | None = None
) -> AsyncGenerator[dict, None]:
    """Stream ``copilotMessageChunk`` SSE dicts for a conversation.

    The whole answer has a wall-clock limit (``COPILOT_PROXY_TIMEOUT_SECONDS``);
    past it the stream is cut off with a visible note.
    """
    openai_messages = _to_openai_messages(messages, context)
    limit = _proxy_timeout()
    emitted = False
    failed = False
    timed_out = False
    deltas = _proxy_deltas(openai_messages)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            try:
                delta = await asyncio.wait_for(deltas.__anext__(), remaining)
            except StopAsyncIteration:
                break
            emitted = True
            yield message_chunk(delta).model_dump(exclude_none=True)
    except asyncio.TimeoutError:
        timed_out = True
        logger.warning(
            "copilot proxy at %s exceeded the %.1fs time limit for a "
            "%d-message conversation",
            _proxy_base_url(),
            limit,
            len(openai_messages),
        )
    except Exception as exc:  # noqa: BLE001 — surface any proxy failure to the user
        # ``EventSourceResponse`` has already sent the 200 + SSE headers, so
        # emit a user-visible fallback chunk instead of a broken empty stream.
        failed = True
        logger.warning(
            "copilot proxy at %s failed for a %d-message conversation: %s: %s",
            _proxy_base_url(),
            len(openai_messages),
            type(exc).__name__,
            exc,
        )
    finally:
        aclose = getattr(deltas, "aclose", None)
        if aclose is not None:
            await aclose()

    if timed_out:
        note = (
            f"\n\n(Answer cut off: the model proxy hit the {limit:g}s time limit.)"
            if emitted
            else f"(No answer from the local model proxy within the {limit:g}s "
            "time limit.)"
        )
        yield message_chunk(note).model_dump(exclude_none=True)
    elif not emitted:
        if not failed:
            # Loud empty: a conversation that produces no tokens (proxy up but
            # returning nothing) almost always means a misconfiguration.
            logger.warning(
                "copilot proxy at %s returned no content for a %d-message "
                "conversation — check the proxy is running and the model is valid",
                _proxy_base_url(),
                len(openai_messages),
            )
        yield message_chunk(
            "(No response from the local model proxy. Is copilot-api running "
            "on :4141?)"
        ).model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# One /query turn
# ---------------------------------------------------------------------------
async def _answer(
    request: QueryRequest,
    caps: Mapping[str, WidgetCapability] | None,
    origins: frozenset[str] = frozenset(),
) -> AsyncGenerator[dict, None]:
    """Stream one ``/query`` turn.

    * Last message is Workspace's ``get_widget_data`` result: show each
      widget's provenance, then answer from the sanitized, bounded data.
    * Last message is the user's, with widgets selected: refuse denied or
      unknown widgets, then ask Workspace for the readable ones (one
      ``get_widget_data`` call; Workspace calls back with the data).
    * Otherwise: a text-only answer.

    ``request.api_keys`` and ``request.tools`` are never read. Widgets are
    read only when their ``origin`` is in ``origins`` (this backend).
    """
    inventory: Mapping[str, WidgetCapability] = caps or {}
    messages = request.messages
    last = messages[-1] if messages else None
    context: str | None = None

    if (
        isinstance(last, LlmClientFunctionCallResultMessage)
        and last.function == "get_widget_data"
    ):
        context, lines, omitted = widget_context(last, inventory, origins)
        step = "Data provenance - " + ("; ".join(lines) or "no readable widget data")
        if omitted:
            step += f". Omitted (context limit): {', '.join(omitted)}"
        yield reasoning_step(f"{step}. {DISCLOSURE}").model_dump(exclude_none=True)
        if not lines:
            context = "(no readable widget data was returned)"
    elif (
        last is not None
        and getattr(last.role, "value", last.role) == "human"
        and request.widgets is not None
        and request.widgets.primary
    ):
        reads, notes = plan_widget_reads(
            list(request.widgets.primary), inventory, origins
        )
        if notes:
            yield message_chunk("\n".join(notes) + "\n\n").model_dump(exclude_none=True)
        if reads:
            yield get_widget_data(reads).model_dump(exclude_none=True)
            return
        context = "Not read: " + " ".join(notes)

    async for event in _sse_stream(messages, context):
        yield event


async def _read_body(http_request: Request) -> bytes | None:
    """Read the request body, or ``None`` once it exceeds ``MAX_REQUEST_BYTES``."""
    declared = http_request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in http_request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/query", include_in_schema=False)
async def query(http_request: Request) -> Response:
    """Stream an answer for the conversation via the local Copilot proxy.

    The body is size-capped (``MAX_REQUEST_BYTES``, HTTP 413) before it is
    parsed as a ``QueryRequest`` (HTTP 422 when invalid).
    """
    body = await _read_body(http_request)
    if body is None:
        return JSONResponse(
            status_code=413,
            content={"detail": f"request body exceeds {MAX_REQUEST_BYTES} bytes"},
        )
    try:
        request = QueryRequest.model_validate_json(body)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": f"invalid query request: {exc.error_count()} errors"},
        )
    return EventSourceResponse(
        content=_answer(
            request,
            _capabilities(http_request.app),
            _origins(http_request.app),
        ),
        media_type="text/event-stream",
    )


__all__ = [
    "router",
    "agents_descriptor",
    "extract_provenance",
    "plan_widget_reads",
    "sanitize",
    "widget_context",
    "CAPABILITIES_STATE",
    "ORIGINS_STATE",
    "COPILOT_ID",
    "COPILOT_NAME",
    "IMPLEMENTED_FEATURES",
]
