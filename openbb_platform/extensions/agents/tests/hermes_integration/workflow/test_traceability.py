"""Tutorial traceability is optional, generated and correct (#1340-T02)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openbb_agents.notebook_guide.traceability import (
    TRACE_DIR,
    TutorialTraceabilityRef,
    build_traceability,
)

REPO = Path(__file__).resolve().parents[6]
PKG = REPO / "openbb_platform" / "extensions" / "agents" / "openbb_agents"
SCRIPT = REPO / "scripts" / "build_workflow_traceability.py"
STORIES = PKG / "notebook_guide" / "stories"
WORKFLOW = "synthetic.concentration_review"
WORKFLOW_FILE = PKG / "hermes_integration" / "workflows" / f"{WORKFLOW}.workflow.json"
TRACE_FILE = TRACE_DIR / f"{WORKFLOW}.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("build_workflow_traceability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _oracle_digest(document: dict) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _committed() -> TutorialTraceabilityRef:
    return TutorialTraceabilityRef.model_validate_json(TRACE_FILE.read_text("utf-8"))


def test_traceability_matches_generator(tmp_path):
    """``--check`` is green on the committed file and red on a hand edit."""
    script = _load_script()
    assert script.main(["--check"]) == 0
    copy = tmp_path / "traceability"
    shutil.copytree(TRACE_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert script.main(["--check", "--trace-dir", str(copy)]) == 0
    edited = copy / TRACE_FILE.name
    document = json.loads(edited.read_text("utf-8"))
    document["stage_map"]["concentration"]["cells"] = [999]
    edited.write_text(json.dumps(document, indent=2) + "\n", "utf-8")
    assert script.main(["--check", "--trace-dir", str(copy)]) == 1


def test_check_cli_exits_zero_without_a_server():
    """Real path: the script runs standalone and reads no live server."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(PKG.parent)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_traceability_digest_matches_current_workflow():
    """The ref pins the digest of the workflow as shipped today."""
    document = json.loads(WORKFLOW_FILE.read_text("utf-8"))
    ref = _committed()
    assert ref.workflow_id == WORKFLOW
    assert ref.workflow_manifest_sha256 == _oracle_digest(document)
    document["title"] = "drift"
    assert ref.workflow_manifest_sha256 != _oracle_digest(document)


def test_mapped_story_stages_bind_the_same_tools():
    """Portfolio/03 stages 7 and 8 use the same tools as the workflow stages."""
    ref = _committed()
    workflow = json.loads(WORKFLOW_FILE.read_text("utf-8"))
    story = json.loads(
        (STORIES / f"{ref.story_id.replace('/', '__')}.json").read_text("utf-8")
    )
    assert ref.story_id == "portfolio/03"
    assert ref.notebook_path == story["notebook_path"]
    assert ref.source_sha256 == story["source_sha256"]
    story_stages = {s["id"]: s for s in story["stages"]}
    wf_stages = {s["id"]: s for s in workflow["stages"]}
    assert set(ref.stage_map) == {"concentration", "construction"}
    for stage_id, mapped in ref.stage_map.items():
        story_stage = story_stages[mapped.story_stage_id]
        assert mapped.cells == story_stage["cells"] and mapped.cells
        assert sorted(story_stage["capabilities"]) == sorted(
            wf_stages[stage_id]["capabilities"]
        )
    assert ref.stage_map["concentration"].story_stage_id.startswith("7-")
    assert ref.stage_map["construction"].story_stage_id.startswith("8-")


def test_build_refuses_a_mapping_that_binds_different_tools():
    """A mapping to a story stage with other tools fails the build."""
    workflow = json.loads(WORKFLOW_FILE.read_text("utf-8"))
    story = json.loads((STORIES / "portfolio__03.json").read_text("utf-8"))
    wrong = {k: v.story_stage_id for k, v in _committed().stage_map.items()}
    wrong["concentration"] = wrong["construction"]
    with pytest.raises(ValueError, match="capabilit"):
        build_traceability(workflow, story, wrong)


def test_build_refuses_unknown_story_stage():
    """A stale mapping to a removed story stage is a loud error."""
    workflow = json.loads(WORKFLOW_FILE.read_text("utf-8"))
    story = json.loads((STORIES / "portfolio__03.json").read_text("utf-8"))
    with pytest.raises(ValueError, match="stage"):
        build_traceability(workflow, story, {"concentration": "no-such-stage"})


def test_workflow_document_itself_has_no_trace_fields():
    """Cells and notebook hashes live only in the traceability file."""
    text = WORKFLOW_FILE.read_text("utf-8")
    document = json.loads(text)
    assert "cells" not in text and "notebook" not in text
    assert "source_sha256" not in document
