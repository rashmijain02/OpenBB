"""Read-only widget access for the Workspace custom agent (#1272).

The copilot (``/agents.json`` + ``/query``) reads the widgets the user
selected in Workspace through Workspace's own ``get_widget_data`` function
call. These tests drive the real ``/query`` generator with synthetic widget
data and a fake model stream (no LLM, no network) and prove:

- discovery: ``/agents.json`` advertises widget access only when the host
  app registered a capability inventory, and never a feature the query
  handler does not implement;
- bounded reads: at most ``MAX_WIDGET_READS`` widgets, rows and context are
  capped, the model stream has a time limit;
- chart widgets are always read with ``raw=true`` (Workspace's agent contract);
- denied widgets (paper and job actions) are refused, never requested, and
  their parameters can never be set by the agent;
- provenance (``data_state`` / ``data_source`` / ``data_as_of``) reaches the
  model and the user;
- credentials in the request or in widget data never reach the model.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_ai.models import QueryRequest
from openbb_portfolio import copilot
from openbb_portfolio.agent_capabilities import (
    WidgetCapability,
    capabilities_from_manifest,
)

SENTINEL = "SENTINEL-CREDENTIAL-1272"

MANIFEST: dict[str, dict[str, Any]] = {
    "demo_chart": {
        "name": "Demo Price Chart",
        "type": "chart",
        "endpoint": "pi/demo/chart",
    },
    "demo_table": {
        "name": "Demo Holdings",
        "type": "table",
        "endpoint": "pi/demo/table",
    },
    "demo_metric": {
        "name": "Demo Risk",
        "type": "metric",
        "endpoint": "pi/demo/metric",
    },
    "demo_markdown": {
        "name": "Demo Notes",
        "type": "markdown",
        "endpoint": "pi/demo/markdown",
    },
    "demo_ticket": {
        "name": "Demo Order Ticket",
        "type": "markdown",
        "endpoint": "pi/demo/ticket",
    },
}
DENIED = {"demo_ticket": "places paper orders; use the widget's own controls"}


def _caps() -> dict[str, WidgetCapability]:
    return capabilities_from_manifest(MANIFEST, DENIED)


def _widget(widget_id: str, **params: Any) -> dict[str, Any]:
    return {
        "uuid": str(uuid4()),
        "origin": "Portfolio Intelligence",
        "widget_id": widget_id,
        "name": MANIFEST.get(widget_id, {}).get("name", widget_id),
        "description": "synthetic",
        "params": [
            {
                "name": name,
                "type": "text",
                "description": name,
                "current_value": value,
            }
            for name, value in params.items()
        ],
    }


def _request(*widgets: dict[str, Any], text: str = "Summarize this") -> QueryRequest:
    return QueryRequest(
        messages=[{"role": "human", "content": text}],
        widgets={"primary": list(widgets)},
    )


def _tool_request(
    sources: list[tuple[str, dict[str, Any]]],
    payloads: list[Any],
    **extra: Any,
) -> QueryRequest:
    """A follow-up request carrying Workspace's ``get_widget_data`` results."""
    data: list[dict[str, Any]] = []
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("error_type"):
            data.append(payload)
            continue
        content = payload if isinstance(payload, str) else json.dumps(payload)
        data.append(
            {
                "items": [
                    {
                        "content": content,
                        "data_format": {"data_type": "object", "parse_as": "table"},
                    }
                ]
            }
        )
    return QueryRequest(
        messages=[
            {"role": "human", "content": "What does this show?"},
            {
                "role": "ai",
                "content": {
                    "function": "get_widget_data",
                    "input_arguments": {
                        "data_sources": [
                            {
                                "widget_uuid": str(uuid4()),
                                "origin": "Portfolio Intelligence",
                                "id": widget_id,
                                "input_args": args,
                            }
                            for widget_id, args in sources
                        ]
                    },
                },
            },
            {
                "role": "tool",
                "function": "get_widget_data",
                "input_arguments": {
                    "data_sources": [
                        {
                            "widget_uuid": str(uuid4()),
                            "origin": "Portfolio Intelligence",
                            "id": widget_id,
                            "input_args": args,
                        }
                        for widget_id, args in sources
                    ]
                },
                "data": data,
            },
        ],
        **extra,
    )


async def _collect(agen: AsyncGenerator) -> list[dict[str, Any]]:
    return [item async for item in agen]


def _events(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [json.loads(e["data"]) for e in events if e["event"] == name]


class _Recorder:
    """Fake model stream that records the exact messages sent to the model."""

    def __init__(self, reply: tuple[str, ...] = ("ok",)) -> None:
        self.calls: list[list[dict]] = []
        self.reply = reply

    async def __call__(self, openai_messages: list[dict]):
        self.calls.append(openai_messages)
        for piece in self.reply:
            yield piece


def _no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(_messages):  # noqa: ANN001
        raise AssertionError("the model must not be called here")
        yield  # pragma: no cover

    monkeypatch.setattr(copilot, "_proxy_deltas", fail)


# ---------------------------------------------------------------------------
# Capability inventory
# ---------------------------------------------------------------------------
def test_capabilities_follow_manifest_types_and_denials():
    caps = _caps()
    assert set(caps) == set(MANIFEST)
    assert {k: c.kind for k, c in caps.items()} == {
        k: w["type"] for k, w in MANIFEST.items()
    }
    assert [k for k, c in caps.items() if not c.readable] == ["demo_ticket"]
    assert caps["demo_ticket"].denied_reason == DENIED["demo_ticket"]


def test_denial_of_unknown_widget_is_rejected():
    """A denial list that names no manifest widget is drift, not a no-op."""
    with pytest.raises(ValueError, match="not_a_widget"):
        capabilities_from_manifest(MANIFEST, {"not_a_widget": "x"})


def test_chart_input_args_force_raw_true_and_keep_params():
    caps = _caps()
    assert caps["demo_chart"].input_args({"symbol": "AAPL", "raw": "false"}) == {
        "symbol": "AAPL",
        "raw": True,
    }
    assert caps["demo_table"].input_args({"symbol": "AAPL"}) == {"symbol": "AAPL"}


# ---------------------------------------------------------------------------
# Discovery and initialization: /agents.json
# ---------------------------------------------------------------------------
def _app(caps: dict[str, WidgetCapability] | None) -> FastAPI:
    app = FastAPI()
    if caps is not None:
        setattr(app.state, copilot.CAPABILITIES_STATE, caps)
    app.include_router(copilot.router)
    return app


def test_agents_json_advertises_widget_access_only_with_an_inventory():
    with_caps = TestClient(_app(_caps())).get("/agents.json").json()
    without = TestClient(_app(None)).get("/agents.json").json()
    features = with_caps[copilot.COPILOT_ID]["features"]
    assert features["widget-dashboard-select"] is True
    assert without[copilot.COPILOT_ID]["features"]["widget-dashboard-select"] is False


def test_agents_json_advertises_only_implemented_features():
    """Every feature set true is one the query handler implements."""
    body = TestClient(_app(_caps())).get("/agents.json").json()
    features = body[copilot.COPILOT_ID]["features"]
    enabled = {name for name, value in features.items() if value}
    assert enabled == {"streaming", "widget-dashboard-select"}
    assert enabled <= copilot.IMPLEMENTED_FEATURES


def test_query_without_widgets_keeps_text_only_behaviour(monkeypatch):
    recorder = _Recorder(("hi",))
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = QueryRequest(messages=[{"role": "human", "content": "hello"}])
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    assert [e["event"] for e in events] == ["copilotMessageChunk"]
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# Bounded, read-only widget reads
# ---------------------------------------------------------------------------
def test_selected_widgets_become_one_get_widget_data_call(monkeypatch):
    _no_model(monkeypatch)
    req = _request(
        _widget("demo_chart", symbol="AAPL"),
        _widget("demo_table", account_id="demo"),
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    calls = _events(events, "copilotFunctionCall")
    assert len(calls) == 1
    assert calls[0]["function"] == "get_widget_data"
    sources = calls[0]["input_arguments"]["data_sources"]
    assert [s["id"] for s in sources] == ["demo_chart", "demo_table"]
    assert sources[0]["input_args"] == {"symbol": "AAPL", "raw": True}
    assert sources[1]["input_args"] == {"account_id": "demo"}


def test_every_chart_read_requests_raw_true(monkeypatch):
    """Fails if any chart widget is fetched without ``raw=true``."""
    _no_model(monkeypatch)
    caps = _caps()
    charts = [k for k, c in caps.items() if c.kind == "chart" and c.readable]
    req = _request(*(_widget(k, raw="false") for k in charts))
    events = asyncio.run(_collect(copilot._answer(req, caps)))
    sources = _events(events, "copilotFunctionCall")[0]["input_arguments"][
        "data_sources"
    ]
    assert {s["id"] for s in sources} == set(charts)
    assert all(s["input_args"]["raw"] is True for s in sources)


def test_denied_widget_is_refused_and_never_requested(monkeypatch):
    _no_model(monkeypatch)
    req = _request(
        _widget("demo_ticket", side="buy", quantity="100", confirm="true"),
        _widget("demo_table"),
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    sources = _events(events, "copilotFunctionCall")[0]["input_arguments"][
        "data_sources"
    ]
    assert [s["id"] for s in sources] == ["demo_table"]
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "Demo Order Ticket" in text
    assert DENIED["demo_ticket"] in text


def test_unknown_widget_is_refused(monkeypatch):
    _no_model(monkeypatch)
    req = _request(_widget("someone_elses_widget"), _widget("demo_table"))
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    sources = _events(events, "copilotFunctionCall")[0]["input_arguments"][
        "data_sources"
    ]
    assert [s["id"] for s in sources] == ["demo_table"]
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "someone_elses_widget" in text


def test_only_denied_widgets_answer_with_refusal_and_model(monkeypatch):
    recorder = _Recorder(("I can only read data.",))
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _request(_widget("demo_ticket", confirm="true"), text="Buy 100 AAPL")
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    assert not _events(events, "copilotFunctionCall")
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "Demo Order Ticket" in text
    assert len(recorder.calls) == 1
    system = recorder.calls[0][0]["content"]
    assert "cannot place" in system.lower()


def test_widget_reads_are_capped(monkeypatch):
    _no_model(monkeypatch)
    many = [_widget("demo_table", n=i) for i in range(copilot.MAX_WIDGET_READS + 3)]
    events = asyncio.run(_collect(copilot._answer(_request(*many), _caps())))
    sources = _events(events, "copilotFunctionCall")[0]["input_arguments"][
        "data_sources"
    ]
    assert len(sources) == copilot.MAX_WIDGET_READS
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "3" in text and "limit" in text.lower()


def test_agent_never_emits_any_function_but_get_widget_data(monkeypatch):
    """Across denied, unknown, chart and table selections."""
    _no_model(monkeypatch)
    req = _request(
        _widget("demo_ticket", confirm="true"),
        _widget("unknown"),
        _widget("demo_chart"),
        _widget("demo_markdown"),
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    functions = {c["function"] for c in _events(events, "copilotFunctionCall")}
    assert functions == {"get_widget_data"}


def test_copilot_module_has_no_http_client_of_its_own():
    """The agent reaches widget data only through Workspace, never directly.

    So it holds no backend token and cannot call any endpoint, mutation or
    otherwise; the only network peer is the model proxy (``openai``).
    """
    tree = ast.parse(Path(copilot.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"httpx", "requests", "urllib", "aiohttp", "socket"})
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not any("PI_WIDGET_BACKEND_TOKEN" in s for s in strings)


# ---------------------------------------------------------------------------
# Answering from widget data: provenance, bounds, errors, credentials
# ---------------------------------------------------------------------------
_ROWS = [
    {
        "date": "2026-07-01",
        "close": 101.5,
        "data_state": "demo",
        "data_source": "stub",
        "data_as_of": "unknown",
    }
]


def test_provenance_reaches_user_and_model(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request(
        [("demo_chart", {"raw": True}), ("demo_metric", {})],
        [
            _ROWS,
            [
                {"label": "Beta", "value": 1.1},
                {"label": "Data State", "value": "Cached: served from fmp_cached"},
            ],
        ],
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "Demo Price Chart: demo" in steps
    assert "Demo Risk: cached" in steps
    context = json.dumps(recorder.calls[0])
    assert "demo (source stub, as of unknown)" in context
    assert "Demo Risk: cached" in context


@pytest.mark.parametrize(
    ("payload", "state"),
    [
        (_ROWS, "demo"),
        ([{"message": "Unavailable: no rows", "data_state": "unavailable"}], "unavailable"),
        ([{"label": "Data State", "value": "Demo: sample book"}], "demo"),
        (
            "## Notes\n\n---\n\n**Data state:** Cached - served from cache. "
            "Source: `fmp_cached`; as of 2026-07-01.",
            "cached",
        ),
        ({"data": [], "layout": {"meta": {"state": "partial", "source": "stub"}}}, "partial"),
        ({"rows": [{"a": 1, "data_state": "stale"}]}, "stale"),
        ([{"a": 1}], "unknown"),
    ],
)
def test_extract_provenance_shapes(payload, state):
    assert copilot.extract_provenance(payload)["state"] == state


def test_unknown_provenance_is_said_out_loud(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request([("demo_table", {})], [[{"a": 1}]])
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "Demo Holdings: unknown" in steps


def test_rows_and_context_are_bounded(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    rows = [
        {"i": i, "note": "x" * 500, "data_state": "demo", "data_source": "stub"}
        for i in range(copilot.MAX_ROWS_PER_WIDGET * 4)
    ]
    req = _tool_request([("demo_table", {})], [rows])
    asyncio.run(_collect(copilot._answer(req, _caps())))
    context = "\n".join(m["content"] for m in recorder.calls[0])
    assert f'"i": {copilot.MAX_ROWS_PER_WIDGET - 1}' in context
    assert f'"i": {copilot.MAX_ROWS_PER_WIDGET},' not in context
    assert "rows omitted" in context
    assert len(context) < copilot.MAX_CONTEXT_CHARS + 4000


def test_widget_error_is_reported_as_unavailable(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request(
        [("demo_table", {})],
        [{"error_type": "widget_error", "content": "HTTP 503 provider down"}],
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "Demo Holdings: unavailable" in steps
    assert "HTTP 503 provider down" in json.dumps(recorder.calls[0])


def test_data_for_denied_widget_is_dropped(monkeypatch):
    """Even if Workspace returns data for a denied widget, it never reaches the model."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request(
        [("demo_ticket", {"confirm": "true"})],
        ["## Paper Order - COMMITTED ticket-body-1272"],
    )
    asyncio.run(_collect(copilot._answer(req, _caps())))
    assert "ticket-body-1272" not in json.dumps(recorder.calls[0])


def test_credentials_never_reach_the_model(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    rows = [
        {
            "symbol": "AAPL",
            "api_key": SENTINEL,
            "Authorization": f"Bearer {SENTINEL}",
            "link": f"https://example.test/x?apikey={SENTINEL}&q=1",
            "note": f"token={SENTINEL}",
            "author": "Jane Analyst",
            "data_state": "demo",
        }
    ]
    req = _tool_request(
        [("demo_table", {})],
        [rows],
        api_keys={"openai_api_key": SENTINEL},
        tools=[
            {
                "name": "t",
                "url": "https://example.test/mcp",
                "auth_token": SENTINEL,
            }
        ],
    )
    asyncio.run(_collect(copilot._answer(req, _caps())))
    sent = json.dumps(recorder.calls[0])
    assert SENTINEL not in sent
    assert "AAPL" in sent and "Jane Analyst" in sent


def test_markdown_credentials_are_redacted(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request(
        [("demo_markdown", {})],
        [f"See https://x.test/?api_key={SENTINEL} with Bearer {SENTINEL}"],
    )
    asyncio.run(_collect(copilot._answer(req, _caps())))
    assert SENTINEL not in json.dumps(recorder.calls[0])


# ---------------------------------------------------------------------------
# Bounded model invocation
# ---------------------------------------------------------------------------
def test_model_stream_has_a_time_limit(monkeypatch, caplog):
    async def slow(_messages):  # noqa: ANN001
        yield "partial"
        await asyncio.sleep(30)
        yield "never"

    monkeypatch.setattr(copilot, "_proxy_deltas", slow)
    monkeypatch.setenv("COPILOT_PROXY_TIMEOUT_SECONDS", "0.2")
    req = QueryRequest(messages=[{"role": "human", "content": "hi"}])
    with caplog.at_level(logging.WARNING, logger="openbb_portfolio.copilot"):
        events = asyncio.run(
            asyncio.wait_for(_collect(copilot._answer(req, None)), timeout=10)
        )
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert text.startswith("partial")
    assert "never" not in text
    assert "time limit" in text
    assert [r for r in caplog.records if "time limit" in r.getMessage()]


def test_proxy_request_is_bounded(monkeypatch):
    seen: dict[str, Any] = {}

    class _Stream:
        def __aiter__(self):
            async def gen():
                return
                yield  # pragma: no cover

            return gen()

    class _Completions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return _Stream()

    class _Client:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.chat = type("C", (), {"completions": _Completions()})()

        async def close(self):
            return None

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _Client)
    monkeypatch.setenv("COPILOT_PROXY_TIMEOUT_SECONDS", "7")

    async def run():
        return [d async for d in copilot._proxy_deltas([{"role": "user", "content": "x"}])]

    asyncio.run(run())
    assert seen["client"]["timeout"] == 7.0
    assert seen["client"]["max_retries"] == 0
    assert seen["max_tokens"] == copilot.MAX_ANSWER_TOKENS
