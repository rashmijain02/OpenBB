"""Stage-graph rules shared by tutorial story manifests and runtime workflows.

Pure functions over any stage object exposing ``id``, ``depends_on``,
``inputs`` (each with ``from_stage`` and ``output``) and ``outputs``. Moved out
of ``notebook_guide.contracts`` so the tutorial and the notebook-independent
runtime enforce one rule set. Messages are prefixed with ``label`` (the story
or workflow ID).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def check_unique_stages(label: str, stage_list: Sequence[Any]) -> dict[str, Any]:
    """Index stages by ID, rejecting duplicates."""
    stages: dict[str, Any] = {}
    for stage in stage_list:
        if stage.id in stages:
            raise ValueError(f"{label}: duplicate stage '{stage.id}'")
        stages[stage.id] = stage
    return stages


def check_dependencies_known(label: str, stages: Mapping[str, Any]) -> None:
    """Reject ``depends_on`` entries that name no stage."""
    for stage in stages.values():
        for dependency in stage.depends_on:
            if dependency not in stages:
                raise ValueError(
                    f"{label}: stage '{stage.id}' depends on unknown "
                    f"stage '{dependency}'"
                )


def upstream(stage_id: str, stages: Mapping[str, Any]) -> set[str]:
    """Return every transitive dependency of ``stage_id``."""
    seen: set[str] = set()
    pending = list(stages[stage_id].depends_on)
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(stages[current].depends_on)
    return seen


def check_acyclic(label: str, stages: Mapping[str, Any]) -> None:
    """Reject dependency cycles (iterative, safe on deep graphs)."""
    state: dict[str, str] = {}
    for root in stages:
        if state.get(root) == "done":
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        state[root] = "visiting"
        while stack:
            stage_id, index = stack.pop()
            deps = stages[stage_id].depends_on
            if index < len(deps):
                stack.append((stage_id, index + 1))
                dep = deps[index]
                if state.get(dep) == "visiting":
                    raise ValueError(f"{label}: stage cycle through '{dep}'")
                if state.get(dep) != "done":
                    state[dep] = "visiting"
                    stack.append((dep, 0))
            else:
                state[stage_id] = "done"


def check_input_bindings(label: str, stage: Any, stages: Mapping[str, Any]) -> None:
    """Every in-document input comes from a declared output of an upstream stage."""
    reachable = upstream(stage.id, stages)
    for binding in stage.inputs:
        if binding.from_stage is None:
            continue
        if binding.from_stage not in reachable:
            raise ValueError(
                f"{label}: '{binding.from_stage}' is not upstream of '{stage.id}'"
            )
        if binding.output not in stages[binding.from_stage].outputs:
            raise ValueError(
                f"{label}: stage '{binding.from_stage}' does not "
                f"declare output '{binding.output}'"
            )
