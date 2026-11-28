"""Bounded exact retrieval over the synthetic public corpus (#1378-T02)."""

# ruff: noqa: D103

from __future__ import annotations

import json
import re

import pytest
from openbb_agents.hermes_integration.egress_guard import egress_guard
from openbb_agents.hermes_integration.knowledge import corpus, index, register


@pytest.fixture
def idx(knowledge_register):
    reg = register.load_register(knowledge_register)
    built = corpus.build_corpus(reg, knowledge_register.parent)
    assert not built.exclusions
    return index.KnowledgeIndex.from_corpus(built)


def _ids(payload):
    return [h["cite"].split("@")[0].removeprefix("[[doc:") for h in payload["hits"]]


def test_identifier_exact_before_fulltext(idx):
    out = idx.search("PF-15")
    assert out["result"] == "evidence"
    assert out["hits"][0]["match"] == "identifier"
    assert _ids(out) == ["spec"]  # the defining row, not the prose mention
    # The prose mention is still reachable by full text when no ID defines it.
    prose = idx.search("Zebra crossings")
    assert _ids(prose) == ["notes"] and prose["hits"][0]["match"] == "phrase"
    dotted = idx.search("documents.search")
    assert dotted["hits"][0]["match"] == "identifier"
    assert dotted["hits"][0]["section"]["anchor"] == "documentssearch"


def test_no_or_prefix_fuzzy_matching(idx):
    assert idx.search("quokk")["result"] == "no_evidence"  # no prefix
    assert idx.search("quokkas")["result"] == "no_evidence"  # no fuzzy/stem
    # All terms are required: one unknown term means no evidence (no OR).
    assert idx.search("quokka platypus")["result"] == "no_evidence"
    assert idx.search("quokka format")["hits"][0]["match"] == "phrase"
    out = idx.search("format quokka")  # not a phrase in that order
    assert {h["match"] for h in out["hits"]} == {"all_terms"}


@pytest.mark.parametrize(
    "query",
    ['"quokka" OR zebra*', "NEAR(quokka zebra)", "quokka NOT zebra", "body:quokka"],
)
def test_fts_operators_in_query_are_literal(idx, query):
    out = idx.search(query)  # never an FTS5 syntax error, never widened
    assert out["result"] == "no_evidence"


def test_fts_expressions_quote_every_token():
    tokens = index.query_tokens('a" OR b* NEAR(c)')
    assert index.all_terms_expr(tokens) == '"a" "OR" "b" "NEAR" "c"'
    assert index.phrase_expr(tokens) == '"a OR b NEAR c"'


def test_limits_enforced(idx):
    with pytest.raises(index.QueryRejected) as exc:
        idx.search("x" * 257)
    assert exc.value.code == "query_too_long"
    with pytest.raises(index.QueryRejected):
        idx.search(" ".join(f"t{i}" for i in range(13)))
    with pytest.raises(index.QueryRejected):
        idx.search("quokka", status="shipped")
    out = idx.search("widget export", limit=50)
    assert len(out["hits"]) <= index.MAX_HITS
    assert len(idx.search("widget export", limit=1)["hits"]) == 1
    small = [
        index.Entry(
            cite=index.make_cite(f"s{i}", "e" * 40, "s"),
            source_id=f"s{i}",
            path=f"docs/designs/s{i}.md",
            anchor="s",
            title="S",
            blob_sha="e" * 40,
            head_drift=False,
            kind="design",
            authority="repo_design",
            status="unknown",
            superseded_by=(),
            pointer_only=False,
            text="okapi",
        )
        for i in range(9)
    ]
    assert len(index.KnowledgeIndex(small).search("okapi", limit=50)["hits"]) == 5
    long_text = "quokka " * 2000
    entry = index.Entry(
        cite=index.make_cite("big", "f" * 40, "big"),
        source_id="big",
        path="docs/designs/big.md",
        anchor="big",
        title="Big",
        blob_sha="f" * 40,
        head_drift=False,
        kind="design",
        authority="repo_design",
        status="unknown",
        superseded_by=(),
        pointer_only=False,
        text=long_text,
    )
    many = index.KnowledgeIndex(
        [
            entry,
            *(
                index.Entry(
                    **{
                        **entry.__dict__,
                        "cite": f"[[doc:b{i}@ffffffffffff#big]]",
                        "source_id": f"b{i}",
                    }
                )
                for i in range(6)
            ),
        ]
    )
    big = many.search("quokka")
    assert len(json.dumps(big, ensure_ascii=False)) <= index.MAX_PAYLOAD
    assert all(len(h["excerpt"]["text"]) <= index.MAX_EXCERPT for h in big["hits"])
    assert all("TRUNCATED" in h["flags"] for h in big["hits"])
    section = many.get_section(entry.cite)
    assert len(json.dumps(section, ensure_ascii=False)) <= index.MAX_PAYLOAD


def test_wrong_revision_near_match(idx):
    out = idx.search("payload cap")
    ids = _ids(out)
    assert ids[0] == "limits.v2"  # current version first
    v1 = next(h for h in out["hits"] if "limits.v1" in h["cite"])
    v2 = out["hits"][0]
    assert v1["superseded_by"] == [v2["cite"]] and "SUPERSEDED" in v1["flags"]
    assert out["result"] == "evidence"
    # A superseded hit is never returned without its successor.
    only = idx.search("payload cap", limit=1)
    assert _ids(only) == ["limits.v2"]
    # Filtered to superseded rows, v1 still never comes back alone...
    alone = idx.search("payload cap", status="superseded", limit=1)
    assert alone["result"] == "no_evidence" and alone["hits"] == []
    # ...and with room for both, its successor is attached and flagged.
    pair = idx.search("payload cap", status="superseded", limit=2)
    assert _ids(pair) == ["limits.v2", "limits.v1"]
    assert "SUCCESSOR" in pair["hits"][0]["flags"]


def test_proposed_vs_implemented_distinguished(idx):
    shipped = idx.search("register reader")
    assert shipped["hits"][0]["status"] == "implemented"
    ops = idx.search("documents.search")
    assert ops["hits"][0]["status"] == "proposed"
    assert idx.search("register reader", status="proposed")["result"] == "no_evidence"


def test_every_hit_has_cite_path_section_revision_authority_status(idx):
    for query in ("PF-15", "payload cap", "widget export", "documents.search"):
        out = idx.search(query)
        assert set(out) == index.PAYLOAD_FIELDS
        assert out["answer_contract_version"] == 1
        for hit in out["hits"]:
            assert set(hit) == index.HIT_FIELDS
            assert index.CITE_RE.fullmatch(hit["cite"])
            assert hit["cite"] in idx.cites
            assert hit["revision"]["blob_sha"][:12] in hit["cite"]
            assert hit["excerpt"]["untrusted"] is True
            assert set(hit["flags"]) <= index.FLAGS
            assert hit["match"] in index.MATCHES


def test_absent_evidence_returns_no_evidence(idx):
    out = idx.search("capital gains harvesting")
    assert out == {**out, "result": "no_evidence", "hits": []}
    assert out["scope"]["sources"] == 7


def test_conflict_returns_ambiguous(idx):
    out = idx.search("widget export")
    assert out["result"] == "ambiguous"
    assert {h["status"] for h in out["hits"]} == {"implemented", "proposed"}


def test_get_section_rejects_unindexed_cite(idx):
    cite = idx.search("PF-15")["hits"][0]["cite"]
    assert idx.get_section(cite)["hits"][0]["cite"] == cite
    wrong_rev = re.sub(r"@[0-9a-f]{12}", "@" + "0" * 12, cite)
    for bad in (wrong_rev, "docs/Specs/gh-9-synth/spec.md", "[[doc:spec@x#y]]", ""):
        out = idx.get_section(bad)
        assert out["result"] == "unknown_cite" and out["hits"] == []


def test_excerpts_strip_hidden_text():
    assert index.clean_text("a<!-- hidden -->b\u200bc\x07") == "abc"


def test_index_build_and_search_make_no_network(knowledge_register):
    with egress_guard(refuse_live_ports=True) as attempts:
        reg = register.load_register(knowledge_register)
        idx = index.KnowledgeIndex.from_corpus(
            corpus.build_corpus(reg, knowledge_register.parent)
        )
        idx.search("PF-15")
    assert attempts == []
