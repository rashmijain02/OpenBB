"""Workflow access words map onto the PolicyGate vocabulary (#1340-T01b).

Workflow manifests keep the design access names (plan Q1). Each word maps to
one operation (and, where the gate defines one, a scope) of
``hermes_integration.access``; ``tax_compute`` stays unmapped until the tax
PBI. Admission consults the gate's live vocabulary, so renaming or removing an
operation or scope there makes affected workflows fail admission.
"""

from __future__ import annotations

from typing import get_args

import pytest
from openbb_agents.hermes_integration import access
from openbb_agents.hermes_integration.admission import admit_workflow
from openbb_agents.hermes_integration.workflow import (
    ACCESS_COVERS,
    ACCESS_OPERATIONS,
    ACCESS_VOCABULARIES,
    mapped_access,
)
from openbb_mcp_server.models.capability import AccessClass

from .conftest import load_fixture

ALL_WORDS = frozenset().union(*ACCESS_VOCABULARIES.values())
MUTATING = frozenset(
    {
        "filesystem_write",
        "cache_maintenance",
        "job_control",
        "workspace_mutation",
        "financial_mutation",
    }
)


def codes(admission) -> set[str]:
    return {r.code for r in admission.rejections}


def test_every_workflow_access_literal_maps_to_a_policy_operation():
    for word in ALL_WORDS - {"tax_compute"}:
        target = ACCESS_OPERATIONS[word]
        assert target.operation in access.OPERATIONS, word
        assert target.scope is None or target.scope in access.KNOWN_SCOPES, word
    assert mapped_access() == ALL_WORDS - {"tax_compute"}


def test_tax_compute_stays_unmapped_until_the_tax_pbi():
    assert "tax_compute" not in ACCESS_OPERATIONS
    assert "tax_compute" not in mapped_access()
    assert "tax_compute" not in ACCESS_COVERS


def test_reviewed_mapping_table():
    table = {
        word: (target.operation, target.scope)
        for word, target in ACCESS_OPERATIONS.items()
    }
    assert table == {
        "metadata": ("public_metadata", None),
        "provider_read": ("provider_read", None),
        "analysis": ("provider_read", None),
        "private_read": ("private_portfolio_read", None),
        "artifact": ("story_state", None),
        "paper": ("story_paper", None),
        "household_meta": ("household_read", "household.summary"),
        "document_evidence": ("evidence_projection_read", "evidence.projection"),
    }


def test_access_covers_is_consistent_with_the_operation_map():
    assert set(ACCESS_COVERS) == set(ACCESS_OPERATIONS)
    classes = frozenset(get_args(AccessClass))
    for word, target in ACCESS_OPERATIONS.items():
        covered = ACCESS_COVERS[word]
        assert covered <= classes, word
        assert not covered & MUTATING, word
        if target.operation in classes:
            assert target.operation in covered, word
        else:  # gate-only operations never cover a private or state class
            assert covered <= {"public_metadata", "provider_read"}, word


@pytest.mark.parametrize("word", ["household_meta", "document_evidence"])
def test_mapped_v2_word_admits_when_v2_is_supported(shipped_document, live_tools, word):
    shipped_document["access_version"] = 2
    shipped_document["capabilities"]["platform:story_concentration"]["access"] = word
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, supported_access_versions={1, 2}
    )
    assert admission.admitted, admission.rejections


# --- Seam contract: admission reads the gate's vocabulary at decision time.


def test_removed_household_operation_fails_household_workflow(live_tools, monkeypatch):
    monkeypatch.setattr(access, "OPERATIONS", access.OPERATIONS - {"household_read"})
    admission = admit_workflow(
        load_fixture("v2-household"),
        live_tools=live_tools,
        supported_access_versions={1, 2},
    )
    assert codes(admission) == {"access_unmapped"}


def test_removed_evidence_scope_fails_evidence_workflow(
    shipped_document, live_tools, monkeypatch
):
    shipped_document["access_version"] = 2
    pin = shipped_document["capabilities"]["platform:story_concentration"]
    pin["access"] = "document_evidence"
    monkeypatch.setattr(
        access, "KNOWN_SCOPES", access.KNOWN_SCOPES - {"evidence.projection"}
    )
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, supported_access_versions={1, 2}
    )
    assert codes(admission) == {"access_unmapped"}


def test_renamed_state_operation_fails_the_shipped_workflow(
    shipped_document, live_tools, monkeypatch
):
    renamed = (access.OPERATIONS - {"story_state"}) | {"story_state_v2"}
    monkeypatch.setattr(access, "OPERATIONS", renamed)
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert not admission.admitted
    assert codes(admission) == {"access_unmapped"}
