"""Optional tutorial traceability for workflows (#1340-T02).

A workflow is identified at runtime by its digest alone. Which notebook cells a
workflow stage was derived from, and the hash of that ``.ipynb``, are tutorial
facts: they live here, in generated files under ``traceability/``, and are read
only by the build script and CI. Nothing under ``hermes_integration`` or the
registry imports this module (an AST test enforces it).

Pure: reads JSON documents handed to it, never a notebook or a server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from openbb_agents.hermes_integration.workflow import workflow_manifest_sha256

TRACE_DIR = Path(__file__).resolve().parent / "traceability"
WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "hermes_integration" / "workflows"
STORIES_DIR = Path(__file__).resolve().parent / "stories"

# workflow_id -> (story_id, {workflow stage id: story stage id}). Reviewed by
# hand; the build fails if a mapped story stage binds different tools.
WORKFLOW_STORY_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "synthetic.basket_xray": (
        "portfolio/03",
        {
            "effective": "3-the-x-ray-look-through-via-sec-n-port-obb-etf",
            "concentration": "7-concentration-obb-portfolio-intel-risk-concent",
            "construction": "8-portfolio-construction-turning-the-x-ray-into",
        },
    ),
    "synthetic.concentration_review": (
        "portfolio/03",
        {
            "concentration": "7-concentration-obb-portfolio-intel-risk-concent",
            "construction": "8-portfolio-construction-turning-the-x-ray-into",
        },
    ),
}


class StageTrace(BaseModel):
    """The tutorial stage and cells one workflow stage was derived from."""

    model_config = ConfigDict(extra="forbid")

    story_stage_id: str
    cells: list[int] = Field(min_length=1)


class TutorialTraceabilityRef(BaseModel):
    """Build/CI-only link from a workflow to the tutorial it came from."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    workflow_id: str
    workflow_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    story_id: str
    notebook_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    stage_map: dict[str, StageTrace]


def build_traceability(
    workflow: Mapping[str, Any],
    story: Mapping[str, Any],
    stage_map: Mapping[str, str],
) -> TutorialTraceabilityRef:
    """Join a workflow document and a story manifest along ``stage_map``.

    Raises ``ValueError`` if a mapped stage is missing or binds a different set
    of capabilities than the workflow stage it is mapped to.
    """
    workflow_id = workflow["workflow_id"]
    workflow_stages = {stage["id"]: stage for stage in workflow["stages"]}
    story_stages = {stage["id"]: stage for stage in story["stages"]}
    traced: dict[str, StageTrace] = {}
    for stage_id, story_stage_id in stage_map.items():
        if stage_id not in workflow_stages:
            raise ValueError(f"{workflow_id}: unknown workflow stage '{stage_id}'")
        if story_stage_id not in story_stages:
            raise ValueError(
                f"{workflow_id}: story stage '{story_stage_id}' is not in "
                f"{story['story_id']}"
            )
        story_stage = story_stages[story_stage_id]
        wanted = sorted(workflow_stages[stage_id]["capabilities"])
        if sorted(story_stage["capabilities"]) != wanted:
            raise ValueError(
                f"{workflow_id}: stage '{stage_id}' capabilities {wanted} differ "
                f"from story stage '{story_stage_id}'"
            )
        traced[stage_id] = StageTrace(
            story_stage_id=story_stage_id, cells=list(story_stage["cells"])
        )
    return TutorialTraceabilityRef(
        workflow_id=workflow_id,
        workflow_manifest_sha256=workflow_manifest_sha256(workflow),
        story_id=story["story_id"],
        notebook_path=story["notebook_path"],
        source_sha256=story["source_sha256"],
        stage_map=traced,
    )


def render_traceability(
    workflow_id: str,
    *,
    workflow_dir: Path = WORKFLOW_DIR,
    stories_dir: Path = STORIES_DIR,
) -> str:
    """Return the canonical file text for one workflow's traceability."""
    story_id, stage_map = WORKFLOW_STORY_MAP[workflow_id]
    workflow = json.loads(
        (workflow_dir / f"{workflow_id}.workflow.json").read_text("utf-8")
    )
    story = json.loads(
        (stories_dir / f"{story_id.replace('/', '__')}.json").read_text("utf-8")
    )
    ref = build_traceability(workflow, story, stage_map)
    return json.dumps(ref.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
