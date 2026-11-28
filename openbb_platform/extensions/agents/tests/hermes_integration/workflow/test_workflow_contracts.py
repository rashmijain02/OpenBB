"""Contract tests for the notebook-free WorkflowManifest (#1340, T01)."""

from __future__ import annotations

import json

import pytest
from openbb_agents._stage_graph import check_acyclic, check_unique_stages
from openbb_agents.hermes_integration.admission import admit_workflow
from openbb_agents.hermes_integration.workflow import (
    WorkflowManifest,
    workflow_manifest_sha256,
)
from openbb_mcp_server.utils.schema_digest import (
    canonical_json_sha256,
    tool_input_schema_sha256,
)
from pydantic import ValidationError

from .conftest import CATALOG


def test_shipped_workflow_parses(shipped_document):
    manifest = WorkflowManifest.model_validate(shipped_document)
    assert manifest.workflow_id == "synthetic.concentration_review"
    assert [s.id for s in manifest.stages] == [
        "concentration",
        "construction",
        "checkpoint",
    ]


def test_workflow_digest_is_stable_across_key_order(shipped_document):
    reordered = json.loads(json.dumps(shipped_document, sort_keys=True))
    assert list(reordered) != list(shipped_document)
    assert workflow_manifest_sha256(reordered) == workflow_manifest_sha256(
        shipped_document
    )
    parsed = WorkflowManifest.model_validate(shipped_document)
    assert workflow_manifest_sha256(parsed) == workflow_manifest_sha256(
        shipped_document
    )


def test_workflow_digest_changes_with_content(shipped_document):
    before = workflow_manifest_sha256(shipped_document)
    shipped_document["title"] = "A different title"
    assert workflow_manifest_sha256(shipped_document) != before


@pytest.mark.parametrize("field", ["cells", "notebook_path", "source_sha256"])
def test_manifest_has_no_notebook_fields(shipped_document, field):
    shipped_document[field] = 1
    with pytest.raises(ValidationError):
        WorkflowManifest.model_validate(shipped_document)


def test_stage_has_no_cells_field(shipped_document):
    shipped_document["stages"][0]["cells"] = [1]
    with pytest.raises(ValidationError):
        WorkflowManifest.model_validate(shipped_document)


@pytest.mark.parametrize("kind", ["setup", "narrative"])
def test_stage_kind_excludes_tutorial_only_kinds(shipped_document, kind):
    shipped_document["stages"][0]["kind"] = kind
    with pytest.raises(ValidationError):
        WorkflowManifest.model_validate(shipped_document)


def test_schema_digest_matches_reviewed_catalog_pins():
    """Recompute reviewed pins from the live in-process tools with the shared helper."""
    # pylint: disable=import-outside-toplevel
    import asyncio

    from openbb_core.api.rest_api import app
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    settings = MCPSettings.model_validate(
        {
            "api_prefix": "/api/v1",
            "capability_profile": "portfolio-ops",
            "default_tool_categories": ["all"],
            "default_skills_dir": None,
        }
    )
    server = create_mcp_server(settings, app, auth=("pin-test", "x" * 32))
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    entries = json.loads(CATALOG.read_text("utf-8"))["entries"]
    for name in ("story_concentration", "story_construction_targets"):
        pinned = entries[f"platform:{name}"]["ref"]["schema_sha256"]
        assert tool_input_schema_sha256(tools[name].parameters) == pinned


def test_digest_helper_is_the_canonical_form():
    import hashlib  # pylint: disable=import-outside-toplevel

    expected = hashlib.sha256(b'{"a":[2,3],"b":1}').hexdigest()
    assert canonical_json_sha256({"b": 1, "a": [2, 3]}) == expected


class _S:  # minimal stage double for the shared graph rules
    def __init__(self, sid, deps):
        self.id = sid
        self.depends_on = deps
        self.inputs = []
        self.outputs = []


def test_shared_graph_rules_reject_duplicates_and_cycles():
    with pytest.raises(ValueError, match="duplicate stage 'a'"):
        check_unique_stages("w", [_S("a", []), _S("a", [])])
    stages = check_unique_stages("w", [_S("a", ["b"]), _S("b", ["a"])])
    with pytest.raises(ValueError, match="stage cycle"):
        check_acyclic("w", stages)


_LAX_VALUES = [
    (("access_version",), True),
    (("access_version",), 1.0),
    (("schema_version",), True),
    (("schema_version",), 1.0),
    (("stages", 0, "optional"), 0),
    (("stages", 0, "optional"), "false"),
    (("capabilities", "platform:story_concentration", "schema_sha256"), None),
]


@pytest.mark.parametrize(("path", "value"), _LAX_VALUES)
def test_contract_is_strict_and_never_coerces(shipped_document, path, value):
    """Coercion would make the parsed digest differ from the raw one (finding 2)."""
    node = shipped_document
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    with pytest.raises(ValidationError):
        WorkflowManifest.model_validate(shipped_document)
    admission = admit_workflow(shipped_document, live_tools={})
    assert not admission.admitted
    assert "schema_invalid" in {r.code for r in admission.rejections}


def test_parsed_digest_equals_raw_digest_for_shipped_workflow(shipped_document):
    """The registry hashes the raw file; admission hashes the parsed model."""
    manifest = WorkflowManifest.model_validate(shipped_document)
    assert workflow_manifest_sha256(manifest) == workflow_manifest_sha256(
        shipped_document
    )
