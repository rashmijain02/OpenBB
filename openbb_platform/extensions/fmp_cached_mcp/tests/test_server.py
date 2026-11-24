"""End-to-end over an in-memory MCP session with a recorded-body upstream (#1299)."""

from __future__ import annotations

import asyncio
import gzip
import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from openbb_fmp_cached_mcp.server import build_server
from openbb_fmp_cached_mcp.upstream import FmpRestUpstream, UpstreamResponse

from .conftest import HOSTED, SNAPSHOT, load_hosted


class RecordedUpstream:
    """Serves recorded REST bodies; records every request it receives."""

    def __init__(self, responses: dict[str, UpstreamResponse] | None = None, secret=""):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.secret = secret

    async def fetch(self, path, params):
        self.calls.append((path, dict(params)))
        return self.responses.get(path, UpstreamResponse(200, b"[]"))


def _call(upstream, tool, arguments):
    async def go():
        server = build_server(upstream=upstream)
        async with create_connected_server_and_client_session(server) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(go())


def _sample(name):
    rec = load_hosted(f"samples-{SNAPSHOT}/{name}.json")
    body = gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"]))
    return rec, body


def test_call_returns_hosted_text_and_maps_params():
    rec, body = _sample("chart_historical-price-eod-light")
    up = RecordedUpstream({rec["rest_path"]: UpstreamResponse(200, body)})
    result = _call(up, "chart", rec["arguments"])
    assert result.isError is False
    assert [c.type for c in result.content] == ["text"]
    assert result.content[0].text == rec["hosted_text"]
    assert result.structuredContent is None
    path, params = up.calls[0]
    assert path == "/historical-price-eod/light"
    assert params == {"symbol": "AAPL", "from": "2026-11-17", "to": "2026-11-20"}


def test_array_and_bool_params_are_rest_encoded():
    up = RecordedUpstream()
    _call(up, "quote", {"endpoint": "batch-quote", "symbols": ["AAPL", "MSFT"]})
    _call(
        up, "chart", {"endpoint": "intraday-1-min", "symbol": "AAPL", "extended": True}
    )
    assert up.calls[0] == ("/batch-quote", {"symbols": "AAPL,MSFT"})
    assert up.calls[1] == (
        "/historical-chart/1min",
        {"symbol": "AAPL", "extended": "true"},
    )


def test_unknown_keys_are_not_forwarded():
    up = RecordedUpstream()
    _call(up, "quote", {"endpoint": "quote", "symbol": "AAPL", "bogus": 1})
    assert up.calls == [("/quote", {"symbol": "AAPL"})]


def test_validation_error_never_reaches_upstream(hosted_errors):
    case = next(c for c in hosted_errors if c["label"] == "invalid_enum_value")
    up = RecordedUpstream()
    result = _call(up, case["tool"], case["arguments"])
    assert result.isError is True
    assert result.content[0].text == case["response"]["result"]["content"][0]["text"]
    assert up.calls == []


def test_unknown_tool_matches_hosted(hosted_errors):
    case = next(c for c in hosted_errors if c["label"] == "unknown_tool")
    result = _call(RecordedUpstream(), case["tool"], case["arguments"])
    assert result.isError is True
    assert result.content[0].text == case["response"]["result"]["content"][0]["text"]


def test_hosted_defaults_fill_missing_required_params():
    up = RecordedUpstream()
    _call(up, "company", {"endpoint": "company-executives"})
    assert up.calls == [("/key-executives", {"symbol": "AAPL"})]
    _call(up, "quote", {"endpoint": "quote"})  # no default: FMP reports the error
    assert up.calls[-1] == ("/quote", {})


def test_upstream_400_matches_hosted():
    case = load_hosted(f"rest-errors-{SNAPSHOT}.json")["cases"][0]
    up = RecordedUpstream(
        {
            case["rest_path"]: UpstreamResponse(
                case["rest_status"], case["rest_body"].encode()
            )
        }
    )
    result = _call(up, case["tool"], case["arguments"])
    assert result.isError is True
    assert result.content[0].text == case["hosted_text"]


def test_key_is_scrubbed_from_payload_and_errors():
    secret = "k" * 32
    up = RecordedUpstream(
        {
            "/quote": UpstreamResponse(
                200, json.dumps([{"link": f"x?apikey={secret}"}]).encode()
            ),
            "/quote-short": UpstreamResponse(400, f"bad key {secret}".encode()),
        },
        secret=secret,
    )
    ok = _call(up, "quote", {"endpoint": "quote", "symbol": "AAPL"})
    err = _call(up, "quote", {"endpoint": "quote-short", "symbol": "AAPL"})
    for result in (ok, err):
        dumped = result.model_dump_json(by_alias=True)
        assert secret not in dumped
    assert "<redacted>" in ok.content[0].text


def test_upstream_exception_is_an_error_result_without_details():
    class Boom(RecordedUpstream):
        async def fetch(self, path, params):
            raise httpx.ConnectError(f"cannot reach host apikey={'s' * 32}")

    result = _call(
        Boom(secret="s" * 32), "quote", {"endpoint": "quote", "symbol": "AAPL"}
    )
    assert result.isError is True
    assert "s" * 32 not in result.content[0].text
    assert "ConnectError" in result.content[0].text


def test_provenance_is_in_meta_only():
    rec, body = _sample("quote_quote-short")
    up = RecordedUpstream({rec["rest_path"]: UpstreamResponse(200, body)})
    result = _call(up, "quote", rec["arguments"])
    prov = result.meta["openbb/provenance"]
    assert prov["state"] == "live" and prov["source"] == "fmp"
    assert "asOf" in prov
    assert "openbb" not in result.content[0].text


def test_rest_upstream_sends_key_in_header_not_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("apikey")
        return httpx.Response(200, content=b"[]")

    async def go():
        up = FmpRestUpstream("z" * 32, transport=httpx.MockTransport(handler))
        try:
            return await up.fetch("/quote", {"symbol": "AAPL"})
        finally:
            await up.aclose()

    resp = asyncio.run(go())
    assert resp.status == 200
    assert seen["key"] == "z" * 32
    assert "z" * 32 not in seen["url"]
    assert seen["url"] == "https://financialmodelingprep.com/stable/quote?symbol=AAPL"


def test_rest_upstream_requires_a_key():
    with pytest.raises(ValueError):
        FmpRestUpstream("")


def test_every_hosted_sample_round_trips_through_the_server():
    """All replayable samples, through the real MCP protocol path."""
    from .test_render import (
        REPLAY,
        _mask_keys,
    )  # pylint: disable=import-outside-toplevel

    async def go():
        failures = []
        for p in REPLAY:
            rec = json.loads(p.read_text("utf-8"))
            body = gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"]))
            up = RecordedUpstream(
                {rec["rest_path"]: UpstreamResponse(rec["rest_status"], body)}
            )
            server = build_server(upstream=up)
            async with create_connected_server_and_client_session(server) as client:
                res = await client.call_tool(rec["tool"], rec["arguments"])
            if _mask_keys(res.content[0].text) != _mask_keys(rec["hosted_text"]):
                failures.append(p.stem)
        return failures

    assert asyncio.run(go()) == []
    assert (HOSTED / f"samples-{SNAPSHOT}").is_dir()
