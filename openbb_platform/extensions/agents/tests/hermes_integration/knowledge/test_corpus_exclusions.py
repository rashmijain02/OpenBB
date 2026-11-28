"""Corpus admission: tracked, allowlisted, denylist-wins, notebook and content scans (#1378-T01)."""

# ruff: noqa: D103

from __future__ import annotations

import json

import pytest
from openbb_agents.hermes_integration.knowledge import corpus, register
from openbb_agents.hermes_integration.projection import SENTINELS, scan_text

from .conftest import register_doc, row


def _build(repo, rows, commit):
    reg = register.Register.model_validate_json(json.dumps(register_doc(commit, rows)))
    return corpus.build_corpus(reg, repo.root)


def _codes(built):
    return sorted((e.source_id, e.code) for e in built.exclusions)


def _all_text(built):
    return "\n".join(s.text for d in built.documents for s in d.sections)


# --- [A2] untracked and ignored paths never enter -----------------------------


def test_untracked_and_ignored_paths_rejected(repo):
    repo.write(".gitignore", "notebooks_local/\ndocs/designs/ignored.md\n")
    repo.write("docs/designs/tracked.md", "# Tracked\n\nok\n")
    commit = repo.commit()
    repo.write("docs/designs/untracked.md", "# U\n\nUNTRACKED_BODY\n")
    repo.write("docs/designs/ignored.md", "# I\n\nIGNORED_BODY\n")
    repo.write("notebooks_local/x.md", "# L\n\nLOCAL_BODY\n")
    fake = "c" * 40
    rows = [
        row("tracked", "docs/designs/tracked.md", repo.blob("docs/designs/tracked.md")),
        row("untracked", "docs/designs/untracked.md", fake),
        row("ignored", "docs/designs/ignored.md", fake),
        row("local", "notebooks_local/x.md", fake),
    ]
    built = _build(repo, rows, commit)
    assert [d.source_id for d in built.documents] == ["tracked"]
    assert _codes(built) == [
        ("ignored", "not_tracked"),
        ("local", "denylisted"),
        ("untracked", "not_tracked"),
    ]
    text = _all_text(built)
    assert "UNTRACKED" not in text and "IGNORED" not in text and "LOCAL" not in text


# --- [A2] the denylist wins even inside allowlisted roots ---------------------

_DENIED = [
    "docs/handoff/h.md",
    "CLAUDE.md",
    ".claude/skills/x.md",
    "docs/archive/a.md",
    ".env",
    "docs/designs/CLAUDE.md",
    "docs/designs/agents.MD",
    "docs/designs/handoff.md",
    "docs/designs/sub/.env.md",
    "docs/OpenBBPlatform/.claude/skills/s.md",
    "docs/OpenBBPlatform/.agents/a.md",
    "docs/Specs/x/.codex/c.md",
    "docs/Specs/x/rules/r.md",
    "docs/Specs/x/context/c.md",
    "docs/designs/.dev-cycle/d.md",
    "docs/designs/.worktrees/w.md",
    "docs/designs/.notebook_state/n.md",
    "docs/designs/notebooks_local/n.md",
    "docs/Specs/HANDOFF.md",
    "notebooks/portfolio/01.ipynb",
]


def test_denylist_beats_allowlist(repo):
    for rel in _DENIED:
        repo.write(rel, "# Injected\n\nDENIED_BODY\n")
    repo.write("docs/designs/ok.md", "# Ok\n\nfine\n")
    commit = repo.commit()
    rows = [row(f"d{i}", rel, repo.blob(rel)) for i, rel in enumerate(_DENIED)]
    rows = [
        (
            r | {"kind": "example_notebook", "notebook_role": "analytics"}
            if r["path"].endswith(".ipynb")
            else r
        )
        for r in rows
    ]
    rows.append(row("ok", "docs/designs/ok.md", repo.blob("docs/designs/ok.md")))
    built = _build(repo, rows, commit)
    assert [d.source_id for d in built.documents] == ["ok"]
    assert {e.code for e in built.exclusions} == {"denylisted"}
    assert len(built.exclusions) == len(_DENIED)
    assert "DENIED_BODY" not in _all_text(built)
    for rel in _DENIED:
        assert corpus.path_code(rel) == "denylisted", rel


def test_paths_outside_allowlist_rejected(repo):
    for rel in (
        "docs/other/x.md",
        "docs/examples/nested/x.md",
        "specs/gh-1-x/tasks.md",
        "docs/designs/x.txt",
    ):
        assert corpus.path_code(rel) == "not_allowlisted", rel
    for rel in (
        "docs/designs/a.md",
        "docs/OpenBBPlatform/b/c.md",
        "docs/Specs/gh-1/spec.md",
        "specs/gh-1338-hfp-x/plan.md",
        "docs/examples/n.ipynb",
        "docs/examples/README.md",
    ):
        assert corpus.path_code(rel) is None, rel


@pytest.mark.parametrize(
    "path",
    [
        "C:/docs/designs/x.md",
        "c:docs/designs/x.md",
        "docs/designs/../../CLAUDE.md",
        "docs/designs/./x.md",
        "docs\\designs\\x.md",
        "/docs/designs/x.md",
        "//host/share/docs/designs/x.md",
        "~/docs/designs/x.md",
        "docs//designs/x.md",
        "docs/designs/x.md\x00",
        "docs/designs/x.md:stream",
        "",
    ],
)
def test_path_shapes_rejected(path):
    assert corpus.path_code(path) == "path_shape"


def test_symlink_and_gitlink_entries_rejected(repo):
    repo.write("docs/designs/real.md", "# Real\n\nr\n")
    repo.write("secret.txt", "SYMLINK_TARGET_BODY\n")
    repo.commit()
    repo.index_entry("120000", "docs/designs/link.md", "../../secret.txt")
    repo.index_entry("160000", "docs/designs/sub.md", repo.git("rev-parse", "HEAD"))
    repo.git("commit", "-q", "-m", "links")
    commit = repo.git("rev-parse", "HEAD")
    rows = [
        row("link", "docs/designs/link.md", repo.blob("docs/designs/link.md")),
        row("sub", "docs/designs/sub.md", repo.blob("docs/designs/sub.md")),
    ]
    built = _build(repo, rows, commit)
    assert built.documents == ()
    assert _codes(built) == [("link", "symlink"), ("sub", "gitlink")]


# --- [A2] notebooks: markdown cell source only --------------------------------


def _notebook():
    leak = " ".join(SENTINELS.values())
    return {
        "metadata": {"kernelspec": {"name": leak}, "note": leak},
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {
                "cell_type": "markdown",
                "id": "m1",
                "metadata": {"tags": [leak]},
                "attachments": {"image.png": {"text/plain": leak}},
                "source": ["# Notebook\n", "\n", "markdown kept\n"],
            },
            {
                "cell_type": "code",
                "id": "c1",
                "metadata": {"secret": leak},
                "execution_count": None,
                "source": f"print('{leak}')",
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": [leak]},
                    {
                        "output_type": "execute_result",
                        "data": {"text/plain": leak},
                        "metadata": {},
                    },
                ],
            },
            {"cell_type": "raw", "metadata": {}, "source": leak},
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": "## Second\n\nalso kept",
            },
        ],
    }


def test_notebook_outputs_attachments_code_never_read(repo):
    repo.write("docs/examples/nb.ipynb", json.dumps(_notebook(), indent=1))
    commit = repo.commit()
    md = corpus.notebook_markdown(json.dumps(_notebook()))
    assert "markdown kept" in md and "also kept" in md
    assert scan_text(md) == []
    built = _build(
        repo,
        [
            row(
                "nb",
                "docs/examples/nb.ipynb",
                repo.blob("docs/examples/nb.ipynb"),
                kind="example_notebook",
                notebook_role="analytics",
            )
        ],
        commit,
    )
    assert built.exclusions == ()
    nb = built.documents[0]
    assert [s.anchor for s in nb.sections] == ["notebook", "second"]
    assert nb.notebook_role == "analytics"
    assert scan_text(_all_text(built)) == []


def test_invalid_notebook_rejected(repo):
    repo.write("docs/examples/bad.ipynb", "{not json")
    commit = repo.commit()
    rows = [
        row(
            "bad",
            "docs/examples/bad.ipynb",
            repo.blob("docs/examples/bad.ipynb"),
            kind="example_notebook",
            notebook_role="template",
        )
    ]
    assert _codes(_build(repo, rows, commit)) == [("bad", "notebook_invalid")]


# --- [A2] private paths and secret shapes are dropped by section --------------

_PRIVATE = """## Clean

public text

## Windows Path

see C:\\Users\\someone\\docs\\x.md

## Secret

api_key=abcdef123456

## Home

/home/alice/project/file

## Sentinel

owner Sentinel Q. Owner
"""


def test_private_path_and_secret_shaped_sections_dropped(repo, write_register, capsys):
    repo.write("docs/designs/p.md", _PRIVATE)
    commit = repo.commit()
    rows = [row("p", "docs/designs/p.md", repo.blob("docs/designs/p.md"))]
    built = _build(repo, rows, commit)
    assert [s.anchor for s in built.documents[0].sections] == ["clean"]
    assert sorted((e.anchor, e.code) for e in built.exclusions) == [
        ("home", "private_path_excluded"),
        ("secret", "secret_shape_excluded"),
        ("sentinel", "secret_shape_excluded"),
        ("windows-path", "private_path_excluded"),
    ]
    path = write_register(register_doc(commit, rows))
    assert (
        register.main(["--check", "--register", str(path), "--repo", str(repo.root)])
        == 1
    )
    out = capsys.readouterr().out
    assert "excluded_section id=p#windows-path code=private_path_excluded" in out
    for leak in ("someone", "abcdef", "alice", "Sentinel Q", "Users"):
        assert leak not in out
    assert scan_text(out) == []


def test_check_clean_register_reports_counts_only(repo, write_register, capsys):
    repo.write("docs/designs/a.md", "# A\n\nalpha\n")
    repo.write("specs/gh-9-x/plan.md", "# Plan\n\nbeta\n")
    commit = repo.commit()
    rows = [
        row("a", "docs/designs/a.md", repo.blob("docs/designs/a.md")),
        row(
            "plan",
            "specs/gh-9-x/plan.md",
            repo.blob("specs/gh-9-x/plan.md"),
            kind="implementation_plan",
            authority="repo_plan",
            status="implemented",
            status_evidence="pr:9",
        ),
    ]
    path = write_register(register_doc(commit, rows))
    assert (
        register.main(["--check", "--register", str(path), "--repo", str(repo.root)])
        == 0
    )
    out = capsys.readouterr().out
    assert "status=implemented authority=repo_plan n=1" in out
    assert "status=unknown authority=repo_design n=1" in out
    assert "result=ok" in out
    assert "alpha" not in out and "beta" not in out


def test_check_rejects_invalid_register_without_echoing_values(write_register, capsys):
    doc = register_doc(
        "a" * 40, [row("x", "docs/designs/x.md", "b" * 40, status="api_key=hunter22")]
    )
    path = write_register(doc)
    assert register.main(["--check", "--register", str(path)]) == 2
    out = capsys.readouterr().out
    assert "register_error" in out
    assert "hunter22" not in out
