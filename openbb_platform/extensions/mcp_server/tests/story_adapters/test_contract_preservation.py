"""Story tool input contracts are unchanged by #1341 (resumable Hermes runs).

The fixture was captured from ``origin/portfolio`` before #1341 changed any
code. Every ``story_*`` tool except ``story_run_create`` (which gains the
optional ``binding`` input, decision D7) must keep its exact input schema, so
Portfolio and TechTrade callers see no contract change.
"""

# pylint: disable=import-outside-toplevel

import asyncio
import json
from pathlib import Path

import pytest

PINS = Path(__file__).resolve().parent / "contract_schema_pins.json"


@pytest.fixture(scope="module")
def live_digests(tmp_path_factory) -> dict[str, str]:
    """Input-schema digests of the in-process portfolio-ops MCP tools."""
    import os

    from openbb_core.api.rest_api import app
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings
    from openbb_mcp_server.utils.schema_digest import tool_input_schema_sha256

    store = tmp_path_factory.mktemp("pins") / "runs.sqlite"
    previous = os.environ.get("OPENBB_STORY_RUN_STORE")
    os.environ["OPENBB_STORY_RUN_STORE"] = str(store)
    try:
        settings = MCPSettings.model_validate(
            {
                "api_prefix": "/api/v1",
                "capability_profile": "portfolio-ops",
                "default_tool_categories": ["all"],
                "default_skills_dir": None,
            }
        )
        server = create_mcp_server(settings, app, auth=("pin-test", "x" * 32))
        tools = asyncio.run(server.list_tools())
    finally:
        if previous is None:
            os.environ.pop("OPENBB_STORY_RUN_STORE", None)
        else:
            os.environ["OPENBB_STORY_RUN_STORE"] = previous
    return {
        tool.name: tool_input_schema_sha256(tool.parameters)
        for tool in tools
        if tool.name.startswith("story_")
    }


def _pins() -> dict[str, str]:
    return json.loads(PINS.read_text("utf-8"))["tools"]


def test_fixture_covers_every_paper_job_and_artifact_tool():
    pins = _pins()
    for prefix, minimum in (
        ("story_paper_", 8),
        ("story_job_", 4),
        ("story_artifact_", 7),
    ):
        assert sum(name.startswith(prefix) for name in pins) >= minimum, prefix
    assert "story_run_create" not in pins


@pytest.mark.parametrize("tool", sorted(_pins()))
def test_story_tool_input_schema_is_unchanged(live_digests, tool):
    assert live_digests.get(tool) == _pins()[tool], (
        f"{tool} input schema changed; Portfolio/TechTrade contracts must be"
        " preserved (#1341)"
    )


def test_no_story_tool_disappeared(live_digests):
    assert set(_pins()) <= set(live_digests)
