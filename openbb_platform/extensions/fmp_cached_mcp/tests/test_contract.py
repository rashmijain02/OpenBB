"""Parity contract: our tools/list and endpoint map vs the recorded hosted server (#1299)."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from openbb_fmp_cached_mcp.endpoint_map import RETENTION_CLASSES, load_endpoint_map
from openbb_fmp_cached_mcp.server import build_server


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


async def _session_call(fn):
    server = build_server(upstream=None)
    async with create_connected_server_and_client_session(server) as client:
        return await fn(client)


def test_tools_list_equals_hosted_inventory(hosted_inventory):
    async def go(client):
        res = await client.list_tools()
        return [
            t.model_dump(mode="json", by_alias=True, exclude_none=True)
            for t in res.tools
        ]

    ours = asyncio.run(_session_call(go))
    hosted = hosted_inventory["tools"]
    assert [t["name"] for t in ours] == [t["name"] for t in hosted]
    for mine, theirs in zip(ours, hosted):
        assert _canon(mine) == _canon(theirs), f"tools/list drift in {theirs['name']}"


def test_initialize_reports_tools_only_capability():
    async def go(client):
        return client.get_server_capabilities()

    caps = asyncio.run(_session_call(go))
    assert caps.tools is not None and caps.tools.listChanged is True
    assert caps.prompts is None and caps.resources is None


@pytest.mark.parametrize("method", ["list_prompts", "list_resources"])
def test_prompts_and_resources_are_method_not_found(method):
    async def go(client):
        with pytest.raises(McpError) as exc:
            await getattr(client, method)()
        return exc.value.error.code

    assert asyncio.run(_session_call(go)) == -32601


def test_endpoint_map_covers_every_hosted_endpoint_once(hosted_inventory):
    emap = load_endpoint_map()
    hosted = {
        (t["name"], e)
        for t in hosted_inventory["tools"]
        for e in t["inputSchema"]["properties"]["endpoint"]["enum"]
    }
    ours = {(tool, ep) for tool, eps in emap.items() for ep in eps}
    assert len(hosted) == 208
    assert ours == hosted


def test_endpoint_map_paths_match_recorded_paths(hosted_paths):
    emap = load_endpoint_map()
    for key, rec in hosted_paths.items():
        tool, ep = key.split("/", 1)
        assert emap[tool][ep]["path"] == rec["path"], key


def test_every_endpoint_has_a_retention_class():
    for tool, eps in load_endpoint_map().items():
        for ep, spec in eps.items():
            assert spec["retention"] in RETENTION_CLASSES, f"{tool}/{ep}"
