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
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from openbb_mcp_server.service import exposure_policy
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

# Logical server name -> the reviewed operation-catalog scope it serves.
SERVER_SCOPES: Mapping[str, str] = {"platform": "portfolio-venv-core-in-process"}


@lru_cache(maxsize=1)
def reviewed_tool_access() -> Mapping[str, frozenset[str]]:
    """Return ``"<server>:<tool>" -> reviewed access classes`` (fail closed).

    A tool missing from the result is unclassified and must not be admitted.
    Raises if the policy asset fails its own integrity check.
    """
    policy = ExposurePolicy.load()
    # Same location ``ExposurePolicy.load`` reads (and hash-checks) by default.
    assets = Path(exposure_policy.__file__).resolve().parents[1] / "assets"
    catalog = assets / policy.document.operation_catalog.file
    with catalog.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    classes: dict[str, set[str]] = {}
    for server, scope in SERVER_SCOPES.items():
        for row in rows:
            tool = row.get("mcp_tool") or ""
            if row.get("scope") != scope or not tool:
                continue
            try:
                decision = policy.classify_operation(scope, row["method"], row["path"])
            except (KeyError, ValueError):
                continue  # unreviewed or ambiguous: stays unclassified
            classes.setdefault(f"{server}:{tool}", set()).add(decision.access_class)
    return {key: frozenset(value) for key, value in classes.items()}
