"""Knowledge MCP tools behind the hermes-finance gate (#1378-T02)."""

# ruff: noqa: D103

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openbb_agents import mcp_server
from openbb_agents.hermes_integration import access
from openbb_agents.hermes_integration.knowledge import grounding, index, tools
from openbb_agents.hermes_integration.policy_probe import child_pythonpath

KNOWLEDGE_TOOLS = {"knowledge_search", "knowledge_get_section"}
PRIVATE_TOOLS = {"get_positions", "get_sector_exposure"}
# sha256 of the two tools' JSON input schemas (sorted keys); changing a
# tool signature must be a reviewed edit of this pin.
SCHEMA_SHA256 = "ef5b279ea3d8aa15b3f9ab379c015d260031a59730be3d18821ab43d5b112f5b"
_FORBIDDEN_ARGS = (
    "path",
    "dir",
    "file",
    "policy",
    "profile",
    "principal",
    "route",
    "model",
    "url",
    "host",
    "register",
    "repo",
)


@pytest.fixture
def configured(knowledge_register):
    tools.configure(knowledge_register)
    yield knowledge_register
    tools.configure(None)


def _schemas():
    descriptors = mcp_server.collect_tools([tools])
    return {d["name"]: d["schema"] for d in descriptors}


def test_knowledge_tools_absent_in_default_mode():
    names = {t["name"] for t in mcp_server.collect_tools()}
    assert names == PRIVATE_TOOLS
    tree = ast.parse(Path(mcp_server.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "hermes_integration" not in (getattr(node, "module", None) or "")
            assert not any("hermes_integration" in a.name for a in node.names)


def test_knowledge_tools_require_grant():
    for name in KNOWLEDGE_TOOLS:
        binding = access.TOOL_BINDINGS[name]
        assert binding.operation == "public_metadata"
        assert binding.scope == "knowledge.public_reference"
        assert binding.fields == index.HIT_FIELDS
        runtime = access.build_tool_gate("hermes-finance", "hermes_runtime")
        assert runtime.decide_tool(name, {"approved": True}).reason == "granted"
        for principal, reason in (
            (None, "unknown_principal"),
            ("hermes_scheduler", "no_grant"),
            ("webui_display", "no_grant"),
            ("operator", "no_grant"),
        ):
            gate = access.build_tool_gate("hermes-finance", principal)
            decision = gate.decide_tool(name, {"principal": "hermes_runtime"})
            assert (decision.allowed, decision.reason) == (False, reason)
    grants = [
        g
        for g in access.HERMES_FINANCE_POLICY.grants
        if g.scope == "knowledge.public_reference"
    ]
    assert len(grants) == 1 and grants[0].principal == "hermes_runtime"
    for principal in access.PRINCIPALS:  # private reads stay denied for all
        gate = access.build_tool_gate("hermes-finance", principal)
        assert not gate.decide_tool("get_positions", {}).allowed


def test_tool_schema_has_no_path_policy_or_model_args():
    schemas = _schemas()
    assert set(schemas) == KNOWLEDGE_TOOLS
    assert set(schemas["knowledge_search"]["properties"]) == {
        "query",
        "limit",
        "status",
    }
    assert set(schemas["knowledge_get_section"]["properties"]) == {"cite"}
    for schema in schemas.values():
        for arg in schema["properties"]:
            assert not any(word in arg for word in _FORBIDDEN_ARGS), arg
    digest = hashlib.sha256(
        json.dumps(schemas, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == SCHEMA_SHA256


def test_binding_fields_match_tool_output(configured):
    out = tools.knowledge_search("PF-15")
    assert out["result"] == "evidence"
    for hit in out["hits"]:
        assert set(hit) == access.TOOL_BINDINGS["knowledge_search"].fields
    section = tools.knowledge_get_section(out["hits"][0]["cite"])
    fields = access.TOOL_BINDINGS["knowledge_get_section"].fields
    assert set(section["hits"][0]) == fields


def test_tool_rejects_bad_arguments_with_codes(configured):
    assert tools.knowledge_search("x" * 300) == {
        "answer_contract_version": 1,
        "result": "rejected",
        "code": "query_too_long",
        "hits": [],
    }
    assert tools.knowledge_search("PF-15", status="shipped")["code"] == "bad_status"
    assert tools.knowledge_search("PF-15", limit="5")["code"] == "bad_limit"


def test_get_section_rejects_unindexed_cite(configured, knowledge_register):
    for bad in (
        "docs/Specs/gh-9-synth/spec.md",
        str(knowledge_register),
        "../CLAUDE.md",
        "[[doc:spec@000000000000#requirements]]",
    ):
        out = tools.knowledge_get_section(bad)
        assert out["result"] == "unknown_cite" and out["hits"] == []


def test_unconfigured_tools_fail_closed(tmp_path):
    tools.configure(tmp_path / "does-not-exist.json")
    try:
        with pytest.raises(tools.KnowledgeUnavailable):
            tools.knowledge_search("PF-15")
    finally:
        tools.configure(None)


def test_failed_index_build_is_cached_with_bounded_retry(tmp_path, monkeypatch):
    calls = []
    real = tools.register.load_register

    def counting(path):
        calls.append(path)
        return real(path)

    clock = [1000.0]
    monkeypatch.setattr(tools.register, "load_register", counting)
    monkeypatch.setattr(tools, "_now", lambda: clock[0])
    tools.configure(tmp_path / "does-not-exist.json")
    try:
        for _ in range(3):
            with pytest.raises(tools.KnowledgeUnavailable, match="register_unreadable"):
                tools.knowledge_search("PF-15")
            with pytest.raises(tools.KnowledgeUnavailable, match="register_unreadable"):
                tools.knowledge_get_section("x")
        assert len(calls) == 1
        clock[0] += tools.RETRY_SECONDS + 1
        with pytest.raises(tools.KnowledgeUnavailable):
            tools.knowledge_search("PF-15")
        assert len(calls) == 2
    finally:
        tools.configure(None)


def test_main_rejects_knowledge_register_without_profile(monkeypatch, capsys):
    async def fake_serve(**_kwargs):
        raise AssertionError("must not serve")

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    with pytest.raises(SystemExit):
        mcp_server.main(["--knowledge-register", "x.json"])
    err = capsys.readouterr().err
    assert "--knowledge-register requires --policy-profile" in err


def test_main_passes_knowledge_register(monkeypatch):
    seen = {}

    async def fake_serve(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    mcp_server.main(
        [
            "--policy-profile",
            "hermes-finance",
            "--principal",
            "hermes_runtime",
            "--knowledge-register",
            "r.json",
        ]
    )
    assert seen == {
        "policy_profile": "hermes-finance",
        "principal": "hermes_runtime",
        "knowledge_register": Path("r.json"),
    }


async def _session(flags, errlog, calls):
    env = os.environ.copy()
    env["PYTHONPATH"] = child_pythonpath(env.get("PYTHONPATH"))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "openbb_agents.mcp_server", *flags],
        env=env,
    )
    out = {}
    with errlog.open("w", encoding="utf-8") as err, anyio.fail_after(120):
        async with (
            stdio_client(params, errlog=err) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            out["tools"] = {t.name for t in (await session.list_tools()).tools}
            for key, (name, args) in calls.items():
                result = await session.call_tool(name, args)
                text = result.content[0].text
                out[key] = (bool(result.isError), json.loads(text))
    return out


def _flags(register_path, principal):
    return [
        "--policy-profile",
        "hermes-finance",
        "--principal",
        principal,
        "--knowledge-register",
        str(register_path),
    ]


@pytest.mark.asyncio
async def test_stdio_gated_server_answers_synthetic_question(
    knowledge_register, tmp_path
):
    errlog = tmp_path / "err.txt"
    out = await _session(
        _flags(knowledge_register, "hermes_runtime"),
        errlog,
        {
            "hit": ("knowledge_search", {"query": "PF-15"}),
            # An argument outside the schema (a path) never reaches a body.
            "path": ("knowledge_get_section", {"cite": "x", "path": "CLAUDE.md"}),
            "absent": ("knowledge_search", {"query": "capital gains harvesting"}),
            "private": ("get_positions", {"approved": True}),
        },
    )
    assert out["tools"] == PRIVATE_TOOLS | KNOWLEDGE_TOOLS
    is_error, hit = out["hit"]
    assert not is_error and hit["result"] == "evidence"
    cite = hit["hits"][0]["cite"]
    answer = f"Answers cite pinned sources (proposed, repo_requirement) {cite}."
    assert grounding.check_answer(answer, [hit]).codes == ("ok",)
    abstain = "[[abstain:no_evidence]] searched the register"
    assert grounding.check_answer(abstain, [out["absent"][1]]).codes == ("abstain_ok",)
    assert out["path"] == (
        True,
        {"error": "tool_failed", "tool": "knowledge_get_section"},
    )
    assert out["private"] == (
        True,
        {"error": "capability_denied", "tool": "get_positions", "reason": "no_grant"},
    )
    errtext = errlog.read_text(encoding="utf-8")
    assert "knowledge_index sources=7" in errtext
    assert "knowledge_egress attempts=0" in errtext


@pytest.mark.asyncio
async def test_stdio_scheduler_is_denied_knowledge_before_body(
    knowledge_register, tmp_path
):
    errlog = tmp_path / "err.txt"
    out = await _session(
        _flags(knowledge_register, "hermes_scheduler"),
        errlog,
        {
            "search": (
                "knowledge_search",
                {"query": "PF-15", "principal": "hermes_runtime"},
            )
        },
    )
    assert out["search"] == (
        True,
        {
            "error": "capability_denied",
            "tool": "knowledge_search",
            "reason": "no_grant",
        },
    )
    assert "knowledge_index" not in errlog.read_text(encoding="utf-8")
