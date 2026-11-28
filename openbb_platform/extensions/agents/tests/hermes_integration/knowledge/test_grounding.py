"""Answer-contract validator over real index payloads (#1378-T02)."""

# ruff: noqa: D103

from __future__ import annotations

import re

import pytest
from openbb_agents.hermes_integration.knowledge import (
    corpus,
    grounding,
    index,
    register,
)


@pytest.fixture
def idx(knowledge_register):
    reg = register.load_register(knowledge_register)
    return index.KnowledgeIndex.from_corpus(
        corpus.build_corpus(reg, knowledge_register.parent)
    )


def _hit(payload, source_id):
    return next(h for h in payload["hits"] if f"doc:{source_id}@" in h["cite"])


def _codes(answer, *payloads):
    return grounding.check_answer(answer, payloads).codes


def test_cited_and_labelled_answer_is_ok(idx):
    out = idx.search("PF-15")
    cite = out["hits"][0]["cite"]
    answer = (
        f"Answers must cite pinned public sources (proposed, repo_requirement) {cite}."
    )
    verdict = grounding.check_answer(answer, [out])
    assert verdict.codes == ("ok",) and verdict.ok


def test_uncited_claim_flagged(idx):
    out = idx.search("PF-15")
    cite = out["hits"][0]["cite"]
    answer = (
        f"Answers cite sources (proposed, repo_requirement) {cite}.\n"
        "- Also the cache never expires."
    )
    assert "uncited_claim" in _codes(answer, out)


def test_unknown_cite_and_wrong_revision(idx):
    out = idx.search("PF-15")
    cite = out["hits"][0]["cite"]
    wrong_rev = re.sub(r"@[0-9a-f]{12}", "@" + "0" * 12, cite)
    answer = f"Answers cite sources (proposed, repo_requirement) {wrong_rev}."
    assert _codes(answer, out) == ("unknown_cite",)
    other = idx.search("widget export")["hits"][0]["cite"]
    # A real cite that was not returned in *this* turn is unknown too.
    assert _codes(f"Widgets export (implemented, repo_design) {other}.", out) == (
        "unknown_cite",
    )


def test_wrong_revision_near_match(idx):
    out = idx.search("payload cap")
    v1 = _hit(out, "limits.v1")
    v2 = _hit(out, "limits.v2")
    alone = (
        f"The payload cap is 3000 characters (superseded, repo_design) {v1['cite']}."
    )
    assert "superseded_without_successor" in _codes(alone, out)
    paired = (
        f"The cap was 3000 (superseded, repo_design) {v1['cite']} and is now "
        f"4000 (proposed, repo_design) {v2['cite']}."
    )
    assert _codes(paired, out) == ("ok",)


def test_proposed_vs_implemented_distinguished(idx):
    out = idx.search("documents.search")
    cite = out["hits"][0]["cite"]
    claim = f"documents.search is implemented (proposed, repo_plan) {cite}."
    assert _codes(claim, out) == ("status_mislabel",)
    wrong_label = (
        f"documents.search returns ranked sections (implemented, repo_plan) {cite}."
    )
    assert _codes(wrong_label, out) == ("status_mislabel",)
    good = (
        f"documents.search is proposed, not implemented (proposed, repo_plan) {cite}."
    )
    assert _codes(good, out) == ("ok",)
    shipped = idx.search("register reader")
    s_cite = shipped["hits"][0]["cite"]
    assert _codes(
        f"The reader is planned (implemented, repo_plan) {s_cite}.", shipped
    ) == ("status_mislabel",)


def test_authority_missing(idx):
    out = idx.search("PF-15")
    cite = out["hits"][0]["cite"]
    assert _codes(f"Answers cite sources {cite}.", out) == ("authority_missing",)
    assert _codes(f"Answers cite sources (proposed, repo_design) {cite}.", out) == (
        "authority_missing",
    )


def test_absent_evidence_returns_no_evidence_and_requires_abstention(idx):
    out = idx.search("capital gains harvesting")
    assert out["result"] == "no_evidence"
    abstain = "[[abstain:no_evidence]] Searched the public register; nothing matched."
    assert _codes(abstain, out) == ("abstain_ok",)
    assert _codes("Harvest losses in December.", out) == ("abstain_required",)
    assert _codes("[[abstain:ambiguous]] wrong marker", out) == ("abstain_required",)


def test_conflict_returns_ambiguous_and_requires_abstention(idx):
    out = idx.search("widget export")
    assert out["result"] == "ambiguous"
    cite = out["hits"][0]["cite"]
    assert _codes(f"Widget export is live (implemented, repo_design) {cite}.", out) == (
        "abstain_required",
    )
    assert _codes("[[abstain:ambiguous]] Two designs disagree.", out) == ("abstain_ok",)


def test_codes_are_closed_vocabulary(idx):
    out = idx.search("PF-15")
    for answer in ("", "x", "[[doc:nope@000000000000#a]] y", "[[abstain:no_evidence]]"):
        verdict = grounding.check_answer(answer, [out])
        assert set(verdict.codes) <= grounding.CODES
        assert verdict.codes
