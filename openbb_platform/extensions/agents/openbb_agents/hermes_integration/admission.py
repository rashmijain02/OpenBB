"""Fail-closed admission of a notebook-free workflow (#1340, HFP-P03).

``admit_workflow`` never raises: any malformed, drifted, ungranted or
notebook-dependent document comes back as ``admitted=False`` with typed
rejection codes. Rejection details name fields and counts, never input values.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from openbb_agents.hermes_integration.workflow import (
    ACCESS_COVERS,
    ACCESS_VOCABULARIES,
    MAPPED_ACCESS,
    WorkflowManifest,
    validate_workflow,
    workflow_manifest_sha256,
)

REJECTION_CODES = (
    "schema_invalid",
    "access_version_unsupported",
    "unknown_access",
    "access_unmapped",
    "access_not_granted",
    "access_understated",
    "access_unclassified",
    "access_denied_by_policy",
    "capability_unresolved",
    "tool_absent",
    "schema_drift",
    "notebook_dependency",
    "graph_invalid",
    "multi_capability_unsupported",
)

NOTEBOOK_KEYS = frozenset({"cells", "notebook_path", "source_sha256"})
NOTEBOOK_SERVERS = frozenset({"notebook", "kernel", "jupyter", "workspace-notebook"})
_IPYNB = re.compile(r"\.ipynb", re.IGNORECASE)
_DOCS_EXAMPLES = re.compile(r"(?<![\w.-])docs[\\/]examples(?![\w-])", re.IGNORECASE)
_NOTEBOOK_DIR = re.compile(r"(?<![\w.-])notebooks(?:_local)?[\\/]", re.IGNORECASE)
_MAX_SCAN_NODES = 200_000
_MAX_DETAIL = 200


@dataclass(frozen=True)
class Rejection:
    """One reason a workflow was not admitted."""

    code: str
    detail: str


@dataclass(frozen=True)
class WorkflowAdmission:
    """The admission decision; ``admitted`` implies no rejections."""

    admitted: bool
    workflow_id: str | None
    workflow_manifest_sha256: str | None
    rejections: tuple[Rejection, ...]


def _reject(code: str, detail: str) -> Rejection:
    return Rejection(code, detail[:_MAX_DETAIL])


def _string_is_notebook_reference(value: str) -> bool:
    if _IPYNB.search(value) or _DOCS_EXAMPLES.search(value):
        return True
    if value.strip().lower() in NOTEBOOK_SERVERS:
        return True
    return _NOTEBOOK_DIR.search(value) is not None


def _scan_notebook_dependencies(document: Any) -> list[Rejection]:
    """Scan every key and string value iteratively, bounded in node count."""
    found: list[Rejection] = []
    seen_keys: set[str] = set()
    stack: list[Any] = [document]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > _MAX_SCAN_NODES:
            found.append(_reject("schema_invalid", "document too large to scan"))
            break
        if isinstance(node, Mapping):
            for key, value in node.items():
                if isinstance(key, str):
                    if key in NOTEBOOK_KEYS and key not in seen_keys:
                        seen_keys.add(key)
                        found.append(
                            _reject("notebook_dependency", f"notebook field '{key}'")
                        )
                    elif _string_is_notebook_reference(key):
                        found.append(
                            _reject("notebook_dependency", "notebook reference in key")
                        )
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, str) and _string_is_notebook_reference(node):
            found.append(
                _reject("notebook_dependency", "notebook reference in a string value")
            )
    return found


def _schema_errors(error: ValidationError) -> list[Rejection]:
    """Summarise pydantic errors by location and type only (no input values)."""
    rejections = []
    for item in error.errors(include_input=False, include_url=False)[:10]:
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        rejections.append(_reject("schema_invalid", f"{location}: {item['type']}"))
    return rejections


def _check_access(
    manifest: WorkflowManifest,
    supported_access_versions: Collection[int],
    allowed_access: Collection[str] | None,
    tool_access: Mapping[str, Collection[str]],
    denied_tools: Collection[str] = (),
) -> list[Rejection]:
    version = manifest.access_version
    vocabulary = ACCESS_VOCABULARIES.get(version)
    if version not in supported_access_versions or vocabulary is None:
        return [_reject("access_version_unsupported", f"access_version {version}")]
    found = []
    for name, pin in manifest.capabilities.items():
        if pin.access not in vocabulary:
            found.append(_reject("unknown_access", f"{name}: access literal"))
        elif pin.access not in MAPPED_ACCESS:
            found.append(
                _reject("access_unmapped", f"{name}: no policy mapping for access")
            )
        elif allowed_access is not None and pin.access not in allowed_access:
            found.append(_reject("access_not_granted", f"{name}: {pin.access}"))
        else:
            found.extend(
                _check_reviewed_class(name, pin.access, pin, tool_access, denied_tools)
            )
    return found


def _check_reviewed_class(
    name: str,
    declared: str,
    pin: Any,
    tool_access: Mapping[str, Collection[str]],
    denied_tools: Collection[str] = (),
) -> list[Rejection]:
    """Refuse a pin declaring less than the tool's reviewed access class."""
    if f"{pin.server}:{pin.tool}" in denied_tools:
        return [_reject("access_denied_by_policy", f"{name}: denied by policy")]
    real = tool_access.get(f"{pin.server}:{pin.tool}")
    if not real:
        return [_reject("access_unclassified", f"{name}: no reviewed access class")]
    if not set(real) <= ACCESS_COVERS.get(declared, frozenset()):
        return [_reject("access_understated", f"{name}: declared '{declared}'")]
    return []


def _check_capabilities(
    manifest: WorkflowManifest, live_tools: Mapping[str, str]
) -> list[Rejection]:
    found = []
    for stage in manifest.stages:
        if len(stage.capabilities) > 1:
            found.append(
                _reject("multi_capability_unsupported", f"{stage.id}: one per stage")
            )
        for name in stage.capabilities:
            if name not in manifest.capabilities:
                found.append(_reject("capability_unresolved", f"{stage.id}: '{name}'"))
    for name, pin in manifest.capabilities.items():
        live_hash = live_tools.get(f"{pin.server}:{pin.tool}")
        if live_hash is None:
            found.append(
                _reject("tool_absent", f"{name}: not on server '{pin.server}'")
            )
        elif live_hash != pin.schema_sha256:
            found.append(_reject("schema_drift", f"{name}: live input schema changed"))
    return found


def admit_workflow(
    document: Any,
    *,
    live_tools: Mapping[str, str],
    supported_access_versions: Collection[int] = frozenset({1}),
    allowed_access: Collection[str] | None = None,
    tool_access: Mapping[str, Collection[str]] | None = None,
    denied_tools: Collection[str] | None = None,
) -> WorkflowAdmission:
    """Decide whether ``document`` may run; never raises.

    ``live_tools`` maps ``"<server>:<tool>"`` to the SHA-256 of the live tool's
    canonical input schema. A same-named tool on another server never counts.
    ``tool_access`` maps ``"<server>:<tool>"`` to its reviewed access classes;
    it defaults to the reviewed capability policy (``tool_access`` module), as
    does ``denied_tools`` (tools whose disposition the policy denies).
    """
    try:
        if tool_access is None:
            # pylint: disable-next=import-outside-toplevel
            from openbb_agents.hermes_integration.tool_access import (
                reviewed_tool_policy,
            )

            reviewed = reviewed_tool_policy()
            tool_access = reviewed.classes
            if denied_tools is None:
                denied_tools = reviewed.denied
        return _admit(
            document,
            live_tools,
            supported_access_versions,
            allowed_access,
            tool_access,
            denied_tools or (),
        )
    except Exception:  # pylint: disable=broad-exception-caught
        # Fail closed on anything unforeseen (RecursionError, bad live_tools...).
        return WorkflowAdmission(
            False,
            None,
            None,
            (_reject("schema_invalid", "unexpected admission error"),),
        )


def _admit(
    document: Any,
    live_tools: Mapping[str, str],
    supported_access_versions: Collection[int],
    allowed_access: Collection[str] | None,
    tool_access: Mapping[str, Collection[str]],
    denied_tools: Collection[str] = (),
) -> WorkflowAdmission:
    rejections = _scan_notebook_dependencies(document)
    if not isinstance(document, Mapping):
        rejections.append(_reject("schema_invalid", "document is not a mapping"))
        return WorkflowAdmission(False, None, None, tuple(rejections))
    try:
        manifest = WorkflowManifest.model_validate(document)
    except ValidationError as error:
        rejections.extend(_schema_errors(error))
        return WorkflowAdmission(False, None, None, tuple(rejections))

    rejections.extend(
        _check_access(
            manifest,
            supported_access_versions,
            allowed_access,
            tool_access,
            denied_tools,
        )
    )
    rejections.extend(_check_capabilities(manifest, live_tools))
    try:
        validate_workflow(manifest)
    except ValueError as error:
        rejections.append(_reject("graph_invalid", str(error)))
    return WorkflowAdmission(
        not rejections,
        manifest.workflow_id,
        workflow_manifest_sha256(manifest),
        tuple(rejections),
    )
