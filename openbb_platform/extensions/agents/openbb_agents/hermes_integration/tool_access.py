"""Reviewed access class of every pinned MCP tool (#1340, review finding 3).

A workflow's ``CapabilityPin.access`` is self-declared, so admission derives
each tool's real ``AccessClass`` from the reviewed capability policy that the
capability inventory is classified by (``openbb_mcp_server`` assets
``capability_policy.json`` + ``capability_policy_operations.csv``) and refuses
a pin that declares less than that class.

Note (plan Q1): the raw inventory labels every non-GET route
``financial_mutation``. The reviewed policy reclassifies the pure-math story
analytics POST routes (``story_concentration``, ``story_construction_targets``)
as ``provider_read`` and the run registry routes as ``story_state``; this module
uses the reviewed decision. ``AccessClass`` is not widened.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

from openbb_mcp_server.service import exposure_policy
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

# Logical server name -> the reviewed operation-catalog scope it serves.
SERVER_SCOPES: Mapping[str, str] = {"platform": "portfolio-venv-core-in-process"}


# Dispositions the exposure policy admits; anything else makes a tool unadmittable.
ADMITTABLE_DISPOSITIONS = frozenset({"direct", "workspace_indirect", "metadata_only"})


class ToolPolicy(NamedTuple):
    """Reviewed access classes of admittable tools and the policy-denied tools."""

    classes: Mapping[str, frozenset[str]]
    denied: frozenset[str]


def derive_tool_policy(
    policy: Any, rows: Iterable[Mapping[str, str]], servers: Mapping[str, str]
) -> ToolPolicy:
    """Classify catalog ``rows`` with ``policy`` (fail closed).

    A tool with any row that fails classification is wholly unclassified: it
    gets no class, never a partial one. A tool with any row whose disposition
    is not admittable is denied by policy and gets no class either.
    """
    rows = list(rows)
    classes: dict[str, set[str]] = {}
    broken: set[str] = set()
    denied: set[str] = set()
    for server, scope in servers.items():
        for row in rows:
            tool = row.get("mcp_tool") or ""
            if row.get("scope") != scope or not tool:
                continue
            key = f"{server}:{tool}"
            try:
                decision = policy.classify_operation(scope, row["method"], row["path"])
            except (KeyError, ValueError):
                broken.add(key)  # unreviewed or ambiguous: unclassified
                continue
            if decision.disposition not in ADMITTABLE_DISPOSITIONS:
                denied.add(key)
            classes.setdefault(key, set()).add(decision.access_class)
    for key in broken | denied:
        classes.pop(key, None)
    return ToolPolicy(
        {key: frozenset(value) for key, value in classes.items()}, frozenset(denied)
    )


@lru_cache(maxsize=1)
def reviewed_tool_policy() -> ToolPolicy:
    """Return the reviewed ToolPolicy (fail closed).

    A tool missing from ``classes`` is unclassified and must not be admitted.
    Raises if the policy asset fails its own integrity check.
    """
    policy = ExposurePolicy.load()
    # Same location ``ExposurePolicy.load`` reads (and hash-checks) by default.
    assets = Path(exposure_policy.__file__).resolve().parents[1] / "assets"
    catalog = assets / policy.document.operation_catalog.file
    with catalog.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return derive_tool_policy(policy, rows, SERVER_SCOPES)


def reviewed_tool_access() -> Mapping[str, frozenset[str]]:
    """Return ``"<server>:<tool>" -> reviewed access classes`` (fail closed)."""
    return reviewed_tool_policy().classes


def policy_denied_tools() -> frozenset[str]:
    """Return the ``"<server>:<tool>"`` keys the reviewed policy denies."""
    return reviewed_tool_policy().denied
