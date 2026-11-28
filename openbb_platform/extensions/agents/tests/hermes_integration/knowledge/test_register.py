"""Register schema, status/supersession, revision pinning and sectioning (#1378-T01)."""

# ruff: noqa: D103

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openbb_agents.hermes_integration.egress_guard import egress_guard
from openbb_agents.hermes_integration.knowledge import corpus, register
from pydantic import ValidationError

from .conftest import register_doc, row

SHA_A = "a" * 40
SHA_B = "b" * 40


def _reg(rows, commit=SHA_A):
    return register.Register.model_validate_json(json.dumps(register_doc(commit, rows)))


def _doc(built, source_id):
    return next(d for d in built.documents if d.source_id == source_id)


# --- [A1] status and authority come from the register, never from prose -----


def test_status_and_authority_come_from_register_not_prose(repo):
    repo.write(
        "docs/designs/feature.md",
        "# Feature\n\nStatus: implemented\n\n## Part\n\n**Status:** implemented and shipped\n",
    )
    commit = repo.commit()
    reg = _reg(
        [
            row(
                "feature",
                "docs/designs/feature.md",
                repo.blob("docs/designs/feature.md"),
                status="proposed",
                status_evidence="issue:7",
                authority="repo_plan",
                kind="implementation_plan",
            )
        ],
        commit,
    )
    built = corpus.build_corpus(reg, repo.root)
    doc = _doc(built, "feature")
    assert doc.status == "proposed"
    assert doc.authority == "repo_plan"
    assert [s.anchor for s in doc.sections] == ["feature", "part"]
    assert {s.status for s in doc.sections} == {"proposed"}


def test_section_status_override_marks_mixed_documents(repo):
    repo.write("docs/designs/mix.md", "# Mix\n\n## Done\n\nx\n\n## Later\n\ny\n")
    commit = repo.commit()
    reg = _reg(
        [
            row(
                "mix",
                "docs/designs/mix.md",
                repo.blob("docs/designs/mix.md"),
                status="proposed",
                status_evidence="pr:12",
                section_status={"done": "implemented"},
            )
        ],
        commit,
    )
    sections = {
        s.anchor: s.status
        for s in _doc(corpus.build_corpus(reg, repo.root), "mix").sections
    }
    assert sections == {"mix": "proposed", "done": "implemented", "later": "proposed"}


# --- [A1] strict schema ------------------------------------------------------


def test_unknown_status_literal_rejected():
    with pytest.raises(ValidationError):
        _reg([row("x", "docs/designs/x.md", SHA_B, status="done")])
    with pytest.raises(ValidationError):
        _reg(
            [
                row(
                    "x",
                    "docs/designs/x.md",
                    SHA_B,
                    section_status={"a": "shipped"},
                    sections=["a"],
                )
            ]
        )


def test_extra_field_rejected_and_no_coercion():
    with pytest.raises(ValidationError):
        _reg([row("x", "docs/designs/x.md", SHA_B, note="free text")])
    doc = register_doc(SHA_A, [row("x", "docs/designs/x.md", SHA_B)])
    doc["schema_version"] = "1"
    with pytest.raises(ValidationError):
        register.Register.model_validate_json(json.dumps(doc))
    doc = register_doc(SHA_A, [row("x", "docs/designs/x.md", SHA_B)])
    doc["extra"] = True
    with pytest.raises(ValidationError):
        register.Register.model_validate_json(json.dumps(doc))
    with pytest.raises(ValidationError):  # privacy and model-context are fixed literals
        _reg([row("x", "docs/designs/x.md", SHA_B, privacy_class="private")])
    with pytest.raises(ValidationError):
        _reg([row("x", "docs/designs/x.md", SHA_B, model_context="denied")])
    with pytest.raises(ValidationError):  # abbreviated or upper-case SHAs are not pins
        _reg([row("x", "docs/designs/x.md", "B" * 40)])


def test_implemented_requires_evidence():
    with pytest.raises(ValidationError, match="status_evidence"):
        _reg([row("x", "docs/designs/x.md", SHA_B, status="implemented")])
    with pytest.raises(ValidationError, match="status_evidence"):
        _reg(
            [
                row(
                    "x",
                    "docs/designs/x.md",
                    SHA_B,
                    sections=["a"],
                    section_status={"a": "implemented"},
                )
            ]
        )
    assert _reg(
        [
            row(
                "x",
                "docs/designs/x.md",
                SHA_B,
                status="implemented",
                status_evidence="pr:1",
            )
        ]
    )


def test_superseded_requires_successor():
    with pytest.raises(ValidationError, match="superseded_by"):
        _reg([row("old", "docs/designs/old.md", SHA_B, status="superseded")])
    with pytest.raises(ValidationError, match="superseded"):
        _reg(
            [
                row("old", "docs/designs/old.md", SHA_B, superseded_by=["new"]),
                row("new", "docs/designs/new.md", SHA_B, supersedes=["old"]),
            ]
        )


def test_supersession_symmetric_acyclic_and_resolvable():
    old = row(
        "old", "docs/designs/old.md", SHA_B, status="superseded", superseded_by=["new"]
    )
    new = row("new", "docs/designs/new.md", SHA_B, supersedes=["old"])
    reg = _reg([old, new])
    assert reg.source("old").superseded_by == ("new",)
    with pytest.raises(ValidationError, match="unresolved"):
        _reg([old])
    with pytest.raises(ValidationError, match="symmetric"):
        _reg([old, row("new", "docs/designs/new.md", SHA_B)])
    with pytest.raises(ValidationError, match="cycle"):
        _reg(
            [
                row(
                    "a",
                    "docs/designs/a.md",
                    SHA_B,
                    status="superseded",
                    superseded_by=["b"],
                    supersedes=["b"],
                ),
                row(
                    "b",
                    "docs/designs/b.md",
                    SHA_B,
                    status="superseded",
                    superseded_by=["a"],
                    supersedes=["a"],
                ),
            ]
        )
    with pytest.raises(ValidationError, match="duplicate"):
        _reg(
            [row("a", "docs/designs/a.md", SHA_B), row("a", "docs/designs/b.md", SHA_B)]
        )


def test_notebook_rows_require_notebook_role():
    with pytest.raises(ValidationError, match="notebook_role"):
        _reg([row("nb", "docs/examples/n.ipynb", SHA_B, kind="example_notebook")])
    with pytest.raises(ValidationError, match="notebook_role"):
        _reg([row("md", "docs/designs/x.md", SHA_B, notebook_role="analytics")])
    assert _reg(
        [
            row(
                "nb",
                "docs/examples/n.ipynb",
                SHA_B,
                kind="example_notebook",
                notebook_role="template",
            )
        ]
    )


# --- [A1] revision pinning ---------------------------------------------------


def test_blob_pin_reads_reviewed_revision_not_worktree(repo, write_register, capsys):
    repo.write("docs/designs/pin.md", "# Pin\n\nreviewed text v1\n")
    reviewed = repo.commit()
    blob = repo.blob("docs/designs/pin.md")
    doc = register_doc(reviewed, [row("pin", "docs/designs/pin.md", blob)])
    path = write_register(doc)
    reg = register.load_register(path)

    # A working-tree edit never enters: the pinned blob is served, no drift.
    repo.write("docs/designs/pin.md", "# Pin\n\nWORKTREE EDIT\n")
    built = corpus.build_corpus(reg, repo.root)
    pin = _doc(built, "pin")
    assert "reviewed text v1" in pin.sections[0].text
    assert "WORKTREE" not in pin.sections[0].text
    assert pin.head_drift is False
    assert (
        register.main(["--check", "--register", str(path), "--repo", str(repo.root)])
        == 0
    )
    capsys.readouterr()

    # A committed edit is HEAD drift: still the pinned text, flagged, --check fails.
    repo.commit("edit")
    built = corpus.build_corpus(reg, repo.root)
    pin = _doc(built, "pin")
    assert "reviewed text v1" in pin.sections[0].text
    assert pin.head_drift is True
    assert pin.blob_sha == blob
    assert (
        register.main(["--check", "--register", str(path), "--repo", str(repo.root)])
        == 1
    )
    out = capsys.readouterr().out
    assert "flag=revision_drift n=1" in out
    assert "drift id=pin" in out
    assert "WORKTREE" not in out and "reviewed text" not in out


def test_blob_not_at_reviewed_commit_rejected(repo, write_register, capsys):
    repo.write("docs/designs/pin.md", "# Pin\n\nv1\n")
    reviewed = repo.commit()
    path = write_register(
        register_doc(reviewed, [row("pin", "docs/designs/pin.md", SHA_B)])
    )
    reg = register.load_register(path)
    built = corpus.build_corpus(reg, repo.root)
    assert built.documents == ()
    assert [(e.source_id, e.code) for e in built.exclusions] == [
        ("pin", "blob_mismatch")
    ]
    assert (
        register.main(["--check", "--register", str(path), "--repo", str(repo.root)])
        == 1
    )
    assert "excluded code=blob_mismatch n=1" in capsys.readouterr().out


# --- [A1] sections -----------------------------------------------------------

_MD = """intro line

# Title

Body.

## Usage

first

```bash
# not a heading
## nor this
```

## Usage

second

Setext Heading
--------------

under setext

### `documents.search` (proposed)

deep
"""


def test_section_anchors_and_section_sha_stable():
    sections = corpus.split_sections(_MD)
    assert [(s.anchor, s.level) for s in sections] == [
        ("_preamble", 0),
        ("title", 1),
        ("usage", 2),
        ("usage-1", 2),
        ("setext-heading", 2),
        ("documentssearch-proposed", 3),
    ]
    by = {s.anchor: s for s in sections}
    assert "# not a heading" in by["usage"].text  # fenced lines stay body text
    assert "second" not in by["usage"].text
    assert "deep" in by["setext-heading"].text  # runs to next equal-or-higher heading
    assert "second" not in by["setext-heading"].text
    assert "deep" in by["title"].text
    again = corpus.split_sections(_MD.replace("\n", "\r\n"))
    assert [s.sha256 for s in again] == [s.sha256 for s in sections]
    changed = corpus.split_sections(_MD.replace("second", "Second"))
    assert by["usage"].sha256 == {s.anchor: s for s in changed}["usage"].sha256
    assert by["usage-1"].sha256 != {s.anchor: s for s in changed}["usage-1"].sha256


def test_sections_allowlist_limits_indexed_anchors(repo):
    repo.write("docs/designs/s.md", "# S\n\n## Keep\n\nk\n\n## Other\n\no\n")
    commit = repo.commit()
    reg = _reg(
        [
            row(
                "s",
                "docs/designs/s.md",
                repo.blob("docs/designs/s.md"),
                sections=["keep", "absent"],
            )
        ],
        commit,
    )
    built = corpus.build_corpus(reg, repo.root)
    assert [s.anchor for s in _doc(built, "s").sections] == ["keep"]
    assert [(e.source_id, e.anchor, e.code) for e in built.exclusions] == [
        ("s", "absent", "section_missing")
    ]


# --- [A1] official tax sources are pointer-only rows -------------------------

_RESEARCH = """# Research

## 8. Official tax-source register

| ID | Primary source | Requirement supported |
|---|---|---|
| T01 | [Pub 550](https://www.irs.gov/publications/p550) | Basis and wash sales. |
| T02 | [Topic 427](https://www.irs.gov/taxtopics/tc427) | Stock options. |

## 9. Other

unrelated
"""


def test_tax_pointer_rows_are_pointer_only(repo):
    repo.write("docs/Specs/gh-1/research.md", _RESEARCH)
    commit = repo.commit()
    blob = repo.blob("docs/Specs/gh-1/research.md")
    anchor = "8-official-tax-source-register"

    def tax(pid, **kw):
        return row(
            f"tax.{pid.lower()}",
            "docs/Specs/gh-1/research.md",
            blob,
            kind="tax_source_pointer",
            authority="official_primary",
            content="pointer_only",
            pointer_id=pid,
            sections=[anchor],
            **kw,
        )

    reg = _reg(
        [tax("T01"), tax("T02", effective={"tax_year": 2025}), tax("T03")], commit
    )
    with egress_guard(refuse_live_ports=True) as attempts:
        built = corpus.build_corpus(reg, repo.root)
    assert attempts == []
    t01 = _doc(built, "tax.t01")
    assert [s.anchor for s in t01.sections] == [anchor]
    assert t01.sections[0].text.startswith("| T01 |")
    assert "T02" not in t01.sections[0].text and "unrelated" not in t01.sections[0].text
    assert (
        "https://www.irs.gov/publications/p550" in t01.sections[0].text
    )  # URL kept as text
    assert [(e.source_id, e.code) for e in built.exclusions] == [
        ("tax.t03", "pointer_missing")
    ]
    with pytest.raises(ValidationError, match="pointer"):
        _reg(
            [
                row(
                    "tax.x",
                    "docs/Specs/gh-1/research.md",
                    blob,
                    kind="tax_source_pointer",
                    authority="official_primary",
                )
            ]
        )
    with pytest.raises(ValidationError, match="official_primary"):
        _reg([row("d", "docs/designs/d.md", blob, authority="official_primary")])


# --- the committed register guards the real file -----------------------------


def test_committed_register_validates():
    reg = register.load_register(register.DEFAULT_REGISTER)
    assert len(reg.sources) > 0
    repo_root = Path(register.__file__).resolve().parents[6]
    report = register.check(reg, repo_root)
    assert report.ok, [
        line for line in report.lines if not line.startswith(("status=", "kind="))
    ]
    for src in reg.sources:
        assert corpus.path_code(src.path) is None, src.source_id
        if src.status == "implemented":
            assert src.status_evidence != "none"
