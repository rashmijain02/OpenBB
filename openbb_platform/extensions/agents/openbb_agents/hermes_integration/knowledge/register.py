"""Reviewed register of public knowledge sources and its ``--check`` CLI (#1378-T01).

The register (``public_sources.json``) is the only thing that decides which
repository documents may reach Hermes as public reference text, and the only
source of each document's status, authority and supersession links. Document
prose ("Status: implemented") is never parsed for status.

Each row pins a path to the git blob that was reviewed (``blob_sha``) at the
register's ``reviewed_commit``. :mod:`.corpus` reads content only through
``git cat-file`` of that pinned blob, so working-tree edits, untracked and
ignored files cannot enter.

``python -m openbb_agents.hermes_integration.knowledge.register --check`` validates
the committed register against the repository and prints identifiers, codes and
counts only (never document text). Exit 0 clean, 1 on any exclusion, scan hit
or HEAD drift, 2 on an invalid register, 3 on usage errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import corpus

DEFAULT_REGISTER = Path(__file__).with_name("public_sources.json")
# A pattern, not a notebook path: rows are classified, never opened, here.
_NOTEBOOK_PATH = re.compile(r"\.ipynb$")

Status = Literal["implemented", "proposed", "historical", "superseded", "unknown"]
Kind = Literal[
    "requirement_spec",
    "implementation_plan",
    "design",
    "platform_doc",
    "example_notebook",
    "tax_source_pointer",
]
Authority = Literal[
    "official_primary",
    "repo_requirement",
    "repo_plan",
    "repo_design",
    "repo_reference",
    "historical",
]
NotebookRole = Literal["analytics", "explanation", "setup_only", "template"]

SourceId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$", max_length=128)]
GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Anchor = Annotated[str, Field(pattern=r"^[\w-]+$", max_length=200)]
Evidence = Annotated[
    str,
    Field(pattern=r"^(?:pr:[1-9][0-9]*|issue:[1-9][0-9]*|commit:[0-9a-f]{40}|none)$"),
]


class _Strict(BaseModel):
    """Unknown fields are errors and nothing is coerced."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Effective(_Strict):
    """When a source applies (all optional)."""

    tax_year: int | None = Field(default=None, ge=1900, le=2100)
    provider_version: str | None = Field(default=None, pattern=r"^[\w.+-]{1,64}$")
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PublicSource(_Strict):
    """One reviewed, revision-pinned public source."""

    source_id: SourceId
    path: str = Field(min_length=1, max_length=512)
    blob_sha: GitSha
    kind: Kind
    authority: Authority
    status: Status
    status_evidence: Evidence
    supersedes: tuple[SourceId, ...] = ()
    superseded_by: tuple[SourceId, ...] = ()
    effective: Effective | None = None
    privacy_class: Literal["public_reference"]
    model_context: Literal["allowed"]
    sections: tuple[Anchor, ...] | None = None
    section_status: dict[Anchor, Status] = Field(default_factory=dict)
    notebook_role: NotebookRole | None = None
    content: Literal["full", "pointer_only"] = "full"
    pointer_id: str | None = Field(default=None, pattern=r"^T[0-9]{2}$")

    @model_validator(mode="after")
    def _consistent(self) -> PublicSource:
        if self.section_status and self.sections is not None:
            unknown = set(self.section_status) - set(self.sections)
            if unknown:
                raise ValueError("section_status anchors must be listed in sections")
        statuses = {self.status, *self.section_status.values()}
        if "implemented" in statuses and self.status_evidence == "none":
            raise ValueError("implemented requires status_evidence")
        if (self.status == "superseded") != bool(self.superseded_by):
            raise ValueError("status superseded requires superseded_by and vice versa")
        if self.source_id in self.supersedes or self.source_id in self.superseded_by:
            raise ValueError("a source cannot supersede itself (cycle)")
        notebook = self.kind == "example_notebook"
        if notebook != (self.notebook_role is not None):
            raise ValueError(
                "notebook_role is required for, and only for, example_notebook"
            )
        if notebook != bool(_NOTEBOOK_PATH.search(self.path)):
            raise ValueError(
                "example_notebook rows must be notebook paths (notebook_role)"
            )
        pointer = self.kind == "tax_source_pointer"
        shape = (self.content == "pointer_only", self.pointer_id is not None)
        if pointer != all(shape) or any(shape) != all(shape):
            raise ValueError(
                "tax_source_pointer requires content pointer_only and pointer_id"
            )
        if pointer != (self.authority == "official_primary"):
            raise ValueError(
                "official_primary is the authority of tax_source_pointer rows only"
            )
        if pointer and (self.sections is None or len(self.sections) != 1):
            raise ValueError("a pointer row names exactly one section")
        return self


class Register(_Strict):
    """The reviewed allowlist register."""

    schema_version: Literal[1]
    reviewed_commit: GitSha
    sources: tuple[PublicSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _links(self) -> Register:
        ids = [s.source_id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source_id")
        full_paths = [s.path for s in self.sources if s.content == "full"]
        if len(full_paths) != len(set(full_paths)):
            raise ValueError("duplicate path among full-content rows")
        by_id = {s.source_id: s for s in self.sources}
        for src in self.sources:
            for other in (*src.supersedes, *src.superseded_by):
                if other not in by_id:
                    raise ValueError(
                        f"unresolved supersession link from {src.source_id}"
                    )
            for newer in src.superseded_by:
                if src.source_id not in by_id[newer].supersedes:
                    raise ValueError("supersession links must be symmetric")
            for older in src.supersedes:
                if src.source_id not in by_id[older].superseded_by:
                    raise ValueError("supersession links must be symmetric")
        _acyclic({s.source_id: s.supersedes for s in self.sources})
        return self

    def source(self, source_id: str) -> PublicSource:
        """Return the row with ``source_id`` (KeyError when absent)."""
        for src in self.sources:
            if src.source_id == source_id:
                return src
        raise KeyError(source_id)


def _acyclic(edges: dict[str, tuple[str, ...]]) -> None:
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        state[node] = 1
        for nxt in edges.get(node, ()):
            if state.get(nxt) == 1:
                raise ValueError("supersession cycle")
            if nxt not in state:
                visit(nxt)
        state[node] = 2

    for node in edges:
        if node not in state:
            visit(node)


def load_register(path: Path) -> Register:
    """Parse and validate a register file (strict JSON)."""
    return Register.model_validate_json(Path(path).read_bytes())


@dataclass(frozen=True)
class CheckReport:
    """``--check`` outcome: identifiers, codes and counts only."""

    ok: bool
    lines: tuple[str, ...]


def check(reg: Register, repo: Path) -> CheckReport:
    """Build the corpus and summarise it without any document text."""
    built = corpus.build_corpus(reg, repo)
    lines = [
        f"register sources={len(reg.sources)} reviewed_commit={reg.reviewed_commit[:12]}"
    ]
    by_status = Counter((d.status, d.authority) for d in built.documents)
    lines += [
        f"status={s} authority={a} n={n}" for (s, a), n in sorted(by_status.items())
    ]
    by_kind = Counter(d.kind for d in built.documents)
    lines += [f"kind={k} n={n}" for k, n in sorted(by_kind.items())]
    sections = sum(len(d.sections) for d in built.documents)
    lines.append(f"admitted documents={len(built.documents)} sections={sections}")
    codes = Counter(e.code for e in built.exclusions)
    lines += [f"excluded code={c} n={n}" for c, n in sorted(codes.items())]
    for exc in built.exclusions:
        if exc.anchor is None:
            lines.append(f"excluded_source id={exc.source_id} code={exc.code}")
        else:
            lines.append(
                f"excluded_section id={exc.source_id}#{exc.anchor} code={exc.code}"
            )
    drift = [d.source_id for d in built.documents if d.head_drift]
    lines.append(f"flag=revision_drift n={len(drift)}")
    lines += [f"drift id={sid}" for sid in drift]
    ok = not built.exclusions and not drift and bool(built.documents)
    if not built.documents:
        lines.append("loud_empty admitted=0")
    lines.append(f"result={'ok' if ok else 'fail'}")
    return CheckReport(ok=ok, lines=tuple(lines))


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: ``--check [--register PATH] [--repo PATH]``."""
    parser = argparse.ArgumentParser(prog="knowledge.register")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    parser.add_argument("--repo", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    if not args.check:
        sys.stderr.write("knowledge.register: --check is required\n")
        return 3
    try:
        reg = load_register(args.register)
    except OSError:
        _out("register_error code=unreadable")
        return 2
    except ValidationError as exc:
        for err in exc.errors(
            include_input=False, include_url=False, include_context=False
        ):
            loc = ".".join(str(part) for part in err["loc"])[:120]
            _out(f"register_error loc={loc or '-'} type={err['type']}")
        return 2
    repo = (
        args.repo if args.repo is not None else corpus.repo_root(args.register.parent)
    )
    if repo is None:
        _out("register_error code=repo_not_found")
        return 2
    report = check(reg, repo)
    for line in report.lines:
        _out(line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
