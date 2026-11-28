"""Notebook-independent workflow manifest contracts (#1340, HFP-P03).

A ``WorkflowManifest`` is the runtime unit of identity for a Hermes workflow:
its SHA-256 digest, not a notebook hash, names what ran. It carries no cell
numbers, notebook paths or notebook hashes; tutorial traceability lives apart
(``notebook_guide.traceability``) and is build/CI only. Capabilities are
self-contained pins (server, tool, input-schema hash, declared access), so no
external catalog file is needed at runtime.

This module is pure: no I/O, no server or notebook imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from openbb_mcp_server.utils.schema_digest import canonical_json_sha256
from pydantic import BaseModel, ConfigDict, Field, field_validator

from openbb_agents._stage_graph import (
    check_acyclic,
    check_dependencies_known,
    check_input_bindings,
    check_unique_stages,
)

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.:/-]*$")]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]

# Stages that only arrange an environment or tell a story do not exist at
# runtime, so ``setup`` and ``narrative`` are not workflow stage kinds.
WorkflowStageKind = Literal[
    "retrieval", "analysis", "artifact", "state", "job", "paper"
]

_V1_ACCESS = frozenset(
    {"metadata", "provider_read", "private_read", "analysis", "artifact", "paper"}
)
# Declared access requirements per ``access_version``. v2 literals parse but
# stay denied (``access_unmapped``) until a PolicyGate mapping exists (T01b).
ACCESS_VOCABULARIES: Mapping[int, frozenset[str]] = {
    1: _V1_ACCESS,
    2: _V1_ACCESS | {"household_meta", "tax_compute", "document_evidence"},
}
# Literals with a known policy-operation mapping. T01b extends this from the
# PolicyGate access module; until then only the legacy six are mapped.
MAPPED_ACCESS: frozenset[str] = _V1_ACCESS


class _Contract(BaseModel):
    """Strict base: unknown fields are errors and nothing is coerced.

    Strictness is what makes ``workflow_manifest_sha256`` of a parsed manifest
    equal the digest of the raw document the registry records: ``true`` or
    ``1.0`` for an ``int`` field would otherwise parse and re-serialise as ``1``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CapabilityPin(_Contract):
    """A real MCP tool pinned to the input-schema hash it was reviewed against."""

    server: Identifier
    tool: Identifier
    schema_sha256: Sha256
    access: str = Field(min_length=1)  # checked against the access vocabulary


class WorkflowInput(_Contract):
    """A typed input bound to a declared output of an upstream stage."""

    name: Identifier
    output: Identifier
    from_stage: Identifier


class WorkflowStage(_Contract):
    """One ordered step of a workflow."""

    id: Identifier
    title: str = Field(min_length=1)
    kind: WorkflowStageKind
    depends_on: list[Identifier]
    capabilities: list[Identifier]
    inputs: list[WorkflowInput]
    outputs: list[Identifier]
    optional: bool


class WorkflowManifest(_Contract):
    """A reviewed, digest-identified workflow with no notebook coupling."""

    schema_version: Literal[1]
    workflow_id: Identifier
    version: SemVer
    access_version: int
    title: str = Field(min_length=1)
    capabilities: Mapping[Identifier, CapabilityPin]
    stages: list[WorkflowStage] = Field(min_length=1)
    input_schemas: Mapping[Identifier, Sha256]
    artifact_schemas: Mapping[Identifier, Sha256]
    limitations: list[str]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_an_int(cls, value: Any) -> Any:
        # ``Literal[1]`` matches ``True`` and ``1.0`` (equal to 1) even in
        # strict mode; only a real ``int`` may pass.
        if type(value) is not int:  # pylint: disable=unidiomatic-typecheck
            raise ValueError("schema_version must be an integer")
        return value


def workflow_manifest_sha256(workflow: WorkflowManifest | Mapping[str, Any]) -> str:
    """Return the digest identifying a workflow (key-order independent).

    The document never contains its own digest. A parsed manifest and the raw
    mapping it came from hash identically.
    """
    if isinstance(workflow, WorkflowManifest):
        return canonical_json_sha256(workflow.model_dump(mode="json"))
    return canonical_json_sha256(workflow)


def validate_workflow(manifest: WorkflowManifest) -> None:
    """Raise ``ValueError`` unless the stage graph is an executable ordered DAG.

    Uses the same graph rules as tutorial story manifests
    (``openbb_agents._stage_graph``) and requires every stage to name at least
    one capability.
    """
    label = manifest.workflow_id
    stages = check_unique_stages(label, manifest.stages)
    check_dependencies_known(label, stages)
    check_acyclic(label, stages)
    for stage in manifest.stages:
        if not stage.capabilities:
            raise ValueError(f"{label}: stage '{stage.id}' has no capability")
        check_input_bindings(label, stage, stages)
