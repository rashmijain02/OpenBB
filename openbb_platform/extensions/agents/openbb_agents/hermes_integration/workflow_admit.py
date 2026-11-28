"""Admit a workflow against live tool schemas: ``python -m ...workflow_admit``.

Exit codes: 0 admitted, 2 rejected, 3 usage / unreadable input. Live hashes
come from an in-process ``portfolio-ops`` MCP server (the same construction the
tutorial catalog generator uses) or from ``--live-file`` (a JSON object of
``"<server>:<tool>" -> sha256``). Output carries codes and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from openbb_mcp_server.utils.schema_digest import tool_input_schema_sha256

from openbb_agents.hermes_integration.admission import admit_workflow

WORKFLOW_DIR = Path(__file__).resolve().parent / "workflows"
_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
# Catalog pins use the logical server name ``platform`` for the in-process app.
_PROFILE_SERVER = {"portfolio-ops": "platform"}


def build_server(profile: str = "portfolio-ops", principal: str = "workflow-admit"):
    """Build an in-process MCP server for ``profile`` (no network, no services)."""
    # pylint: disable=import-outside-toplevel
    from openbb_core.api.rest_api import app
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    settings = MCPSettings.model_validate(
        {
            "api_prefix": "/api/v1",
            "capability_profile": profile,
            "default_tool_categories": ["all"],
            "default_skills_dir": None,
        }
    )
    return create_mcp_server(settings, app, auth=(principal, "x" * 32))


async def server_tool_hashes(server, profile: str = "portfolio-ops") -> dict[str, str]:
    """Return ``"<server>:<tool>" -> input-schema SHA-256`` for a built server."""
    logical = _PROFILE_SERVER.get(profile, profile)
    return {
        f"{logical}:{tool.name}": tool_input_schema_sha256(tool.parameters)
        for tool in await server.list_tools()
    }


async def live_tool_hashes(profile: str = "portfolio-ops") -> dict[str, str]:
    """Return ``"<server>:<tool>" -> input-schema SHA-256`` from an in-process server."""
    return await server_tool_hashes(build_server(profile), profile)


def _load_document(args: argparse.Namespace) -> object:
    if args.workflow_file:
        path = Path(args.workflow_file)
    else:
        if not _ID.match(args.workflow):
            raise ValueError("invalid workflow id")
        path = WORKFLOW_DIR / f"{args.workflow}.workflow.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the admission CLI."""
    parser = argparse.ArgumentParser(prog="workflow_admit", description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--workflow", help="ID of a shipped workflow")
    source.add_argument("--workflow-file", help="path to a workflow JSON document")
    live = parser.add_mutually_exclusive_group(required=True)
    live.add_argument(
        "--live", choices=sorted(_PROFILE_SERVER), help="in-process server"
    )
    live.add_argument("--live-file", help="JSON object of '<server>:<tool>' -> sha256")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    try:
        document = _load_document(args)
        if args.live_file:
            live_tools = json.loads(Path(args.live_file).read_text(encoding="utf-8"))
        else:
            live_tools = asyncio.run(live_tool_hashes(args.live))
    except (OSError, ValueError) as error:
        sys.stderr.write(f"usage error: {type(error).__name__}\n")
        return 3

    admission = admit_workflow(document, live_tools=live_tools)
    result = {
        "admitted": admission.admitted,
        "workflow_id": admission.workflow_id,
        "workflow_manifest_sha256": admission.workflow_manifest_sha256,
        "rejections": [
            {"code": r.code, "detail": r.detail} for r in admission.rejections
        ],
    }
    if args.format == "json":
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(("admitted" if admission.admitted else "rejected") + "\n")
        for rejection in admission.rejections:
            sys.stdout.write(f"  {rejection.code}: {rejection.detail}\n")
    return 0 if admission.admitted else 2


if __name__ == "__main__":
    sys.exit(main())
