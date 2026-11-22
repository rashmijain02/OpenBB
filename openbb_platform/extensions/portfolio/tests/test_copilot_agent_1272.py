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
import time
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
ORIGIN = "Portfolio Intelligence"
# Case-insensitive: Workspace shows the connector name as the user typed it.
ORIGINS = frozenset({"portfolio intelligence"})

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


def _widget(widget_id: str, _origin: str = ORIGIN, **params: Any) -> dict[str, Any]:
    return {
        "uuid": str(uuid4()),
        "origin": _origin,
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
    origin: str = ORIGIN,
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
                                "origin": origin,
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
                            "origin": origin,
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, caps, ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    assert not _events(events, "copilotFunctionCall")
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "Demo Order Ticket" in text
    assert len(recorder.calls) == 1
    system = recorder.calls[0][0]["content"]
    assert "cannot place" in system.lower()


def test_widget_reads_are_capped(monkeypatch):
    _no_model(monkeypatch)
    many = [_widget("demo_table", n=i) for i in range(copilot.MAX_WIDGET_READS + 3)]
    events = asyncio.run(_collect(copilot._answer(_request(*many), _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
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


# ---------------------------------------------------------------------------
# Review fixes (#1272 round 2): privacy, redaction, safe default, origin, cap
# ---------------------------------------------------------------------------
SYN_ACCOUNT = "ACCT-SYNTHETIC-1272"


def test_identifier_columns_never_reach_the_model(monkeypatch):
    """PRIVACY-1a: account, basket, owner and user identifiers are dropped."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    rows = [
        {
            "symbol": "AAPL",
            "weight": 0.12,
            "account_id": SYN_ACCOUNT,
            "accountId": SYN_ACCOUNT,
            "account_number": SYN_ACCOUNT,
            "basket_id": SYN_ACCOUNT,
            "owner_name": SYN_ACCOUNT,
            "user_id": SYN_ACCOUNT,
            "customerId": SYN_ACCOUNT,
            "note": f"rebalanced account_id={SYN_ACCOUNT} today",
            "data_state": "demo",
        }
    ]
    req = _tool_request([("demo_table", {"account_id": SYN_ACCOUNT})], [rows])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sent = json.dumps(recorder.calls[0])
    assert SYN_ACCOUNT not in sent
    assert "AAPL" in sent and "0.12" in sent


def test_markdown_identifiers_are_masked(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    text = f"## Book\n\n- **Account ID:** {SYN_ACCOUNT}\n- basket_id: {SYN_ACCOUNT}\n"
    req = _tool_request([("demo_markdown", {})], [text])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    assert SYN_ACCOUNT not in json.dumps(recorder.calls[0])


def test_external_model_provider_is_disclosed(monkeypatch):
    """PRIVACY-1b: description and the in-session step say where data goes."""
    assert "sent to" in copilot.COPILOT_DESCRIPTION
    assert "model provider" in copilot.COPILOT_DESCRIPTION
    monkeypatch.setattr(copilot, "_proxy_deltas", _Recorder())
    req = _tool_request([("demo_table", {})], [_ROWS])
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "model provider" in steps


_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzeW50aGV0aWMifQ.c3ludGhldGljLXNpZw"
_AWS = "AKIA" + "SYNTHETIC1272ABC"


@pytest.mark.parametrize(
    "row",
    [
        {"authToken": SENTINEL},
        {"sessionId": SENTINEL},
        {"jwt": SENTINEL},
        {"apiKey": SENTINEL},
        {"accessKey": SENTINEL},
        {"x-api-key": SENTINEL},
        {"client_secret": SENTINEL},
        {"note": f"https://x.test/a?key={SENTINEL}"},
        {"note": f"https://x.test/a?access_key={SENTINEL}&b=1"},
        {"note": f"https://x.test/a?sig={SENTINEL}"},
        {"note": f"Authorization: Basic {SENTINEL}"},
        {"note": f"token: {SENTINEL}"},
        {"note": f"password : {SENTINEL}"},
        {"note": f"https://user:{SENTINEL}@db.example.test/x"},
        {"note": f"jwt {_JWT}"},
        {"note": f"aws {_AWS}"},
    ],
)
def test_broad_credential_redaction(monkeypatch, row):
    """SECURITY-1: camelCase/joined keys and common secret value shapes."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request([("demo_table", {})], [[{"symbol": "AAPL", **row}]])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sent = json.dumps(recorder.calls[0])
    for secret in (SENTINEL, _JWT, _AWS):
        assert secret not in sent
    assert "AAPL" in sent


def test_ordinary_columns_survive_redaction():
    row = {
        "signal": "BUY",
        "as_of_session": "2026-07-01",
        "author": "Jane Analyst",
        "monkey": "ok",
        "key_stat": "pe",
        "data_source": "stub",
        "description": "Data state: Demo",
        "sector": "Basic Materials",
        "summary": "Basic Materials led; Bearer instruments were flat",
    }
    assert copilot.sanitize(row) == row


def test_action_like_widgets_are_denied_by_default():
    """SECURITY-2: a new action-like widget is denied unless allowlisted."""
    manifest = {
        **MANIFEST,
        "demo_paper_rebalance": {
            "name": "Rebalance",
            "type": "markdown",
            "endpoint": "pi/paper/rebalance",
        },
        "demo_confirm": {
            "name": "Confirm",
            "type": "markdown",
            "endpoint": "pi/demo/do",
            "params": [{"paramName": "confirm", "value": "false"}],
        },
        "demo_execute": {"name": "Exec", "type": "table", "endpoint": "tt/execute/submit"},
        "demo_post": {
            "name": "Post",
            "type": "table",
            "endpoint": "pi/demo/post",
            "method": "POST",
        },
        "demo_backtest": {
            "name": "BT",
            "type": "markdown",
            "endpoint": "pi/demo/run",
            "category": "Backtest",
        },
    }
    caps = capabilities_from_manifest(manifest, DENIED)
    action_like = (
        "demo_paper_rebalance",
        "demo_confirm",
        "demo_execute",
        "demo_post",
        "demo_backtest",
    )
    for widget_id in action_like:
        assert not caps[widget_id].readable, widget_id
        assert "allowlist" in (caps[widget_id].denied_reason or ""), widget_id
    assert caps["demo_table"].readable
    allowed = capabilities_from_manifest(
        manifest, DENIED, allow={"demo_paper_rebalance"}
    )
    assert allowed["demo_paper_rebalance"].readable


def test_allowlist_must_name_an_action_like_manifest_widget():
    with pytest.raises(ValueError, match="demo_table"):
        capabilities_from_manifest(MANIFEST, DENIED, allow={"demo_table"})
    with pytest.raises(ValueError, match="ghost"):
        capabilities_from_manifest(MANIFEST, DENIED, allow={"ghost"})


def test_widgets_from_another_backend_are_refused(monkeypatch):
    """Code note (a): the inventory applies only to this backend's origin."""
    _no_model(monkeypatch)
    req = _request(
        _widget("demo_table", _origin="Another Backend"),
        _widget("demo_chart", _origin="PORTFOLIO INTELLIGENCE", symbol="AAPL"),
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sources = _events(events, "copilotFunctionCall")[0]["input_arguments"][
        "data_sources"
    ]
    assert [s["id"] for s in sources] == ["demo_chart"]
    text = "".join(c["delta"] for c in _events(events, "copilotMessageChunk"))
    assert "Another Backend" in text


def test_no_origins_means_no_widget_reads(monkeypatch):
    monkeypatch.setattr(copilot, "_proxy_deltas", _Recorder())
    req = _request(_widget("demo_table"))
    events = asyncio.run(_collect(copilot._answer(req, _caps())))
    assert not _events(events, "copilotFunctionCall")


def test_data_from_another_backend_is_dropped(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request(
        [("demo_table", {})],
        [[{"x": "foreign-body-1272", "data_state": "demo"}]],
        origin="Another Backend",
    )
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    assert "foreign-body-1272" not in json.dumps(recorder.calls[0])


def test_context_cap_reports_only_included_widgets(monkeypatch):
    """Code note (b): widgets cut by the context cap are named as omitted."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    big = [{"i": i, "n": "y" * 280, "data_state": "demo"} for i in range(50)]
    req = _tool_request(
        [("demo_table", {}), ("demo_chart", {"raw": True}), ("demo_metric", {})],
        [big, big, [{"label": "Data State", "value": "Cached: x"}]],
    )
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "Demo Holdings: demo" in steps
    assert "Demo Risk: cached" in steps
    assert "Demo Price Chart: demo" not in steps
    assert "omitted" in steps.lower() and "Demo Price Chart" in steps
    context = "\n".join(m["content"] for m in recorder.calls[0])
    assert len(context) < copilot.MAX_CONTEXT_CHARS + 4000
    assert "Demo Price Chart" in context and "omitted" in context.lower()


# ---------------------------------------------------------------------------
# Review fixes (#1272 round 3)
# ---------------------------------------------------------------------------
SYN_ID = "IDENT-SYNTHETIC-1273X"


@pytest.mark.parametrize(
    "key",
    [
        "acct_id",
        "primary_account_id",
        "pm_user",
        "portfolio_id",
        "accountID",
        "AcctNo",
        "primaryaccountid",
        "userName",
        "basketRef",
        "household_id",
        "CUSTOMER_NUMBER",
        "owner",
        "client",
    ],
)
def test_identifier_keys_by_token_are_dropped(monkeypatch, key):
    """PRIVACY-1a: identifier keys at any position and case are dropped."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    rows = [{"symbol": "AAPL", key: SYN_ID, "meta": {"inner": {key: SYN_ID}}}]
    req = _tool_request([("demo_table", {})], [rows])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sent = json.dumps(recorder.calls[0])
    assert SYN_ID not in sent
    assert "AAPL" in sent


def test_non_identifier_columns_are_kept():
    row = {
        "ownership_pct": 1.5,
        "portfolio_value": 10.0,
        "portfolio_weight": 0.2,
        "holder": "Example Fund LP",
        "accrued": 1,
        "users_note": None,
    }
    kept = copilot.sanitize(row)
    for key in ("ownership_pct", "portfolio_value", "portfolio_weight", "holder", "accrued"):
        assert key in kept, key


def test_markdown_table_identifier_columns_are_masked(monkeypatch):
    """PRIVACY-1b: a header cell matching the identifier rule masks its column."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    text = (
        "## Holdings\n\n"
        "| Symbol | Acct ID | Weight | Portfolio Id |\n"
        "|:---|---|---:|---|\n"
        f"| AAPL | {SYN_ID} | 0.25 | {SYN_ID}-P |\n"
        f"| MSFT | {SYN_ID}2 | 0.75 | {SYN_ID}-Q |\n\n"
        "| Note |\n|---|\n| keep-me-1273 |\n"
    )
    req = _tool_request([("demo_markdown", {})], [text])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sent = json.dumps(recorder.calls[0])
    assert SYN_ID not in sent
    for kept in ("AAPL", "MSFT", "0.25", "0.75", "keep-me-1273", "Acct ID"):
        assert kept in sent, kept


@pytest.mark.parametrize(
    "payload",
    [
        {"columns": ["symbol", "account_id"], "data": [["AAPL", SYN_ID]]},
        {"columns": [{"field": "portfolio_id"}, {"field": "symbol"}], "rows": [[SYN_ID, "AAPL"]]},
        {"columns": [{"name": "pm_user"}, {"headerName": "symbol"}], "values": [[SYN_ID, "AAPL"]]},
        {"index": [0], "columns": ["AcctNo", "symbol"], "data": [[SYN_ID, "AAPL"]]},
        [["acct_id", "symbol"], [SYN_ID, "AAPL"]],
    ],
)
def test_column_oriented_identifier_columns_are_dropped(monkeypatch, payload):
    """PRIVACY-1b: column/row-oriented payloads lose identifier columns."""
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    req = _tool_request([("demo_table", {})], [payload])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    sent = json.dumps(recorder.calls[0])
    assert SYN_ID not in sent
    assert "AAPL" in sent


@pytest.mark.parametrize(
    "text",
    [
        "a-" * 100_000 + "://",
        "x://" + "a" * 200_000,
        "account id" + " " * 200_000 + "x",
        "**Account ID" + " " * 100_000 + "**" + " " * 100_000 + "x",
        "token" + " " * 200_000 + "x",
        "bearer " + "a" * 200_000,
        "| account | x |\n" * 20_000,
    ],
)
def test_redaction_is_linear_on_adversarial_input(text):
    """ReDoS: large adversarial strings are redacted well inside a second."""
    start = time.perf_counter()
    copilot.redact_text(text)
    assert time.perf_counter() - start < 1.0


def test_oversized_widget_payload_is_refused_before_sanitize(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(copilot, "_proxy_deltas", recorder)
    calls = {"n": 0}
    real = copilot.sanitize

    def counting(value):
        calls["n"] += 1
        return real(value)

    monkeypatch.setattr(copilot, "sanitize", counting)
    huge = "z" * (copilot.MAX_PAYLOAD_CHARS + 1)
    req = _tool_request([("demo_markdown", {})], [huge])
    events = asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    steps = " ".join(s["message"] for s in _events(events, "copilotStatusUpdate"))
    assert "Demo Notes: unavailable" in steps
    assert calls["n"] == 0
    assert huge[:1000] not in json.dumps(recorder.calls[0])


def test_rows_are_limited_before_sanitize(monkeypatch):
    seen: list[int] = []
    real = copilot.sanitize

    def spy(value):
        if isinstance(value, list):
            seen.append(len(value))
        return real(value)

    monkeypatch.setattr(copilot, "sanitize", spy)
    monkeypatch.setattr(copilot, "_proxy_deltas", _Recorder())
    rows = [{"i": i, "data_state": "demo"} for i in range(5000)]
    req = _tool_request([("demo_table", {})], [rows])
    asyncio.run(_collect(copilot._answer(req, _caps(), ORIGINS)))
    assert seen and max(seen) <= copilot.MAX_ROWS_PER_WIDGET


def test_query_body_size_is_capped(monkeypatch):
    monkeypatch.setattr(copilot, "MAX_REQUEST_BYTES", 2000)
    _no_model(monkeypatch)
    client = TestClient(_app(_caps()))
    body = {"messages": [{"role": "human", "content": "x" * 5000}]}
    assert client.post("/query", json=body).status_code == 413
    small = {"messages": [{"role": "human", "content": "hi"}], "widgets": {"primary": []}}
    monkeypatch.setattr(copilot, "_proxy_deltas", _Recorder(("ok",)))
    assert client.post("/query", json=small).status_code == 200
    assert client.post("/query", content=b"{not json").status_code == 422


@pytest.mark.parametrize(
    "widget",
    [
        {"name": "A", "type": "table", "endpoint": "pi/demo/place-order"},
        {"name": "B", "type": "table", "endpoint": "pi/demo/x", "category": "Paper-Trading"},
        {
            "name": "C",
            "type": "table",
            "endpoint": "pi/demo/y",
            "params": [{"paramName": "confirmed", "value": "false"}],
        },
        {
            "name": "D",
            "type": "table",
            "endpoint": "pi/demo/z",
            "params": [{"paramName": "confirm_order", "value": "false"}],
        },
    ],
)
def test_action_classification_splits_hyphens_and_confirm_prefixes(widget):
    caps = capabilities_from_manifest({**MANIFEST, "demo_new": widget}, DENIED)
    assert not caps["demo_new"].readable


def test_lowercase_basic_token_is_redacted():
    assert SENTINEL not in copilot.redact_text(f"authorization: basic {SENTINEL}")


def test_qualified_identifier_keys_are_dropped():
    """``portfolio``/``book``/``member`` count only next to an id-like token."""
    kept = copilot.sanitize(
        {"book_id": SYN_ID, "id_portfolio": SYN_ID, "member-no": SYN_ID, "book": "x"}
    )
    assert kept == {"book": "x"}


def test_chunked_query_body_is_capped(monkeypatch):
    """A body without Content-Length is still cut off at the stream cap."""
    monkeypatch.setattr(copilot, "MAX_REQUEST_BYTES", 2000)
    _no_model(monkeypatch)
    client = TestClient(_app(_caps()))

    def chunks():
        yield b'{"messages": [{"role": "human", "content": "'
        yield b"x" * 3000
        yield b'"}]}'

    assert client.post("/query", content=chunks()).status_code == 413


def test_declared_oversize_body_is_refused_without_reading(monkeypatch):
    monkeypatch.setattr(copilot, "MAX_REQUEST_BYTES", 2000)
    from starlette.requests import Request  # pylint: disable=import-outside-toplevel

    async def receive():
        raise AssertionError("the body must not be read")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/query",
        "headers": [(b"content-length", b"999999999")],
    }
    assert asyncio.run(copilot._read_body(Request(scope, receive))) is None
