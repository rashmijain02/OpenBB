"""Pinned-blob corpus reader for the public-knowledge register (#1378-T01).

Admission is *allowlist AND NOT denylist*, and the denylist always wins.
Content is read only with ``git cat-file blob <blob_sha>`` after
``git ls-tree`` proves that ``path`` held exactly that regular-file blob at the
register's ``reviewed_commit``. The working tree is never opened, so untracked,
ignored (``notebooks_local/``) and uncommitted text cannot enter.

Notebooks contribute the ``source`` of markdown cells only: outputs,
attachments, metadata, code and raw cells are never read into text.

Every admitted section is scanned with :func:`~..projection.scan_text` and a
user-path pattern; a hit drops the section with a fixed code. Results carry
source IDs, anchors and codes; only :class:`Section.text` holds document text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..projection import scan_text

if TYPE_CHECKING:
    from .register import PublicSource, Register

EXCLUSION_CODES = frozenset(
    {
        "path_shape",
        "denylisted",
        "not_allowlisted",
        "not_tracked",
        "symlink",
        "gitlink",
        "blob_mismatch",
        "blob_missing",
        "undecodable",
        "notebook_invalid",
        "section_missing",
        "pointer_missing",
        "no_text",
        "private_path_excluded",
        "secret_shape_excluded",
    }
)

# --- path eligibility ---------------------------------------------------------

_ALLOW = tuple(
    re.compile(p)
    for p in (
        r"^docs/Specs/[^/]+(?:/[^/]+)*\.md$",
        r"^specs/gh-[0-9]+-[a-z0-9-]+/plan\.md$",
        r"^docs/designs/[^/]+(?:/[^/]+)*\.md$",
        r"^docs/OpenBBPlatform/[^/]+(?:/[^/]+)*\.md$",
        r"^docs/examples/[^/]+\.(?:md|ipynb)$",
    )
)
# Compared case-insensitively against every path segment.
_DENY_SEGMENTS = frozenset(
    {
        "notebooks_local",
        ".notebook_state",
        ".worktrees",
        ".dev-cycle",
        ".claude",
        ".agents",
        ".codex",
        "rules",
        "context",
    }
)
_DENY_PREFIXES = (
    "notebooks/",
    "docs/handoff/",
    "docs/archive/",
    "docs/prompts/",
    "docs/superpowers/",
    ".github/skills/",
)
_DENY_NAMES = frozenset({"claude.md", "agents.md", "gemini.md", "handoff.md"})
_BAD_CHARS = re.compile(r"[\\:\x00-\x1f\x7f]")


def path_code(path: str) -> str | None:
    """Return why ``path`` is ineligible (``None`` when it may be read)."""
    if not path or path.startswith(("/", "~")) or _BAD_CHARS.search(path):
        return "path_shape"
    segments = path.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return "path_shape"
    folded = path.casefold()
    names = folded.split("/")
    if (
        any(seg in _DENY_SEGMENTS for seg in names)
        or folded.startswith(_DENY_PREFIXES)
        or names[-1] in _DENY_NAMES
        or ".env" in names[-1]
    ):
        return "denylisted"
    if not any(rx.match(path) for rx in _ALLOW):
        return "not_allowlisted"
    return None


# --- hardened read-only git ---------------------------------------------------


def _git(repo: Path, *args: str) -> bytes | None:
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "--literal-pathspecs",
                "-c",
                "core.fsmonitor=false",  # never run a repo-configured fsmonitor hook
                "-C",
                str(repo),
                *args,
            ],
            check=True,
            capture_output=True,
            timeout=60,
            env={
                **os.environ,
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def repo_root(start: Path) -> Path | None:
    """Return the work-tree root containing ``start`` (``None`` outside git)."""
    out = _git(start, "rev-parse", "--show-toplevel")
    if not out:
        return None
    return Path(out.decode("utf-8").strip())


def _tree_entry(repo: Path, rev: str, path: str) -> tuple[str, str, str] | None:
    """``(mode, type, sha)`` of exactly ``path`` at ``rev``, or ``None``."""
    out = _git(repo, "ls-tree", "-z", "--full-tree", rev, "--", path)
    if not out:
        return None
    for record in out.split(b"\x00"):
        meta, sep, name = record.partition(b"\t")
        if sep and name.decode("utf-8", "replace") == path:
            mode, kind, sha = meta.decode("ascii").split()
            return mode, kind, sha
    return None


# --- markdown sections --------------------------------------------------------

PREAMBLE = "_preamble"
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")


@dataclass(frozen=True)
class Section:
    """One heading-delimited section; ``text`` is the only document text."""

    anchor: str
    level: int
    title: str
    text: str
    sha256: str
    status: str = "unknown"


def slugify(title: str) -> str:
    """GitHub-style heading slug (without the duplicate suffix)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-") or "section"


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    fence: str | None = None
    for i, line in enumerate(lines):
        fence_match = _FENCE.match(line)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= len(fence)
            ):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            continue
        atx = _ATX.match(line)
        if atx:
            found.append((i, len(atx.group(1)), (atx.group(2) or "").strip()))
            continue
        setext = _SETEXT.match(lines[i + 1]) if i + 1 < len(lines) else None
        starts_paragraph = (
            i == 0 or not lines[i - 1].strip() or (found and found[-1][0] == i - 1)
        )
        if (
            setext
            and line.strip()
            and starts_paragraph
            and not line.lstrip().startswith((">", "|", "-", "*"))
        ):
            found.append((i, 1 if setext.group(1)[0] == "=" else 2, line.strip()))
    return found


def _normalise(lines: Iterable[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def split_sections(markdown: str) -> list[Section]:
    """Split Markdown into sections; each runs to the next equal-or-higher heading."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heads = _headings(lines)
    sections: list[Section] = []
    used: set[str] = {PREAMBLE}
    first = heads[0][0] if heads else len(lines)
    pre = _normalise(lines[:first])
    if pre:
        sections.append(
            Section(PREAMBLE, 0, "", pre, hashlib.sha256(pre.encode()).hexdigest())
        )
    for idx, (start, level, title) in enumerate(heads):
        end = next((h[0] for h in heads[idx + 1 :] if h[1] <= level), len(lines))
        base = slugify(title)
        anchor, n = base, 0
        while anchor in used:
            n += 1
            anchor = f"{base}-{n}"
        used.add(anchor)
        text = _normalise(lines[start:end])
        sections.append(
            Section(
                anchor, level, title, text, hashlib.sha256(text.encode()).hexdigest()
            )
        )
    return sections


def notebook_markdown(raw: str) -> str:
    """Join the ``source`` of markdown cells; nothing else is read into text."""
    doc = json.loads(raw)
    cells = doc.get("cells") if isinstance(doc, dict) else None
    if not isinstance(cells, list):
        raise ValueError("notebook has no cell list")
    parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source")
        if isinstance(source, list) and all(isinstance(s, str) for s in source):
            source = "".join(source)
        if isinstance(source, str):
            parts.append(source)
    return "\n\n".join(parts)


# --- content scans ------------------------------------------------------------

_USER_PATH = re.compile(
    r"(?i)(?:\b[a-z]:[\\/]+users[\\/]+[^\\/\s]+|/home/[^/\s]+/|/users/[^/\s]+/|\\\\[^\\\s]+\\)"
)


def section_code(text: str) -> str | None:
    """Return the fixed exclusion code for a section's text (``None`` when clean)."""
    if _USER_PATH.search(text):
        return "private_path_excluded"
    if scan_text(text):
        return "secret_shape_excluded"
    return None


# --- corpus -------------------------------------------------------------------


@dataclass(frozen=True)
class Exclusion:
    """A source or section that was not admitted, by ID and code only."""

    source_id: str
    anchor: str | None
    code: str


@dataclass(frozen=True)
class Document:
    """An admitted source; metadata comes from the register row only."""

    source_id: str
    path: str
    blob_sha: str
    kind: str
    authority: str
    status: str
    notebook_role: str | None
    superseded_by: tuple[str, ...]
    head_drift: bool
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Corpus:
    """Admitted documents and every exclusion."""

    documents: tuple[Document, ...]
    exclusions: tuple[Exclusion, ...]


def _read_pinned(
    repo: Path, reviewed: str, src: PublicSource
) -> tuple[str | None, str | None, bool]:
    """Return ``(text, code, head_drift)`` for ``src`` read from its pinned blob."""
    code = path_code(src.path)
    if code:
        return None, code, False
    entry = _tree_entry(repo, reviewed, src.path)
    if entry is None or entry[1] not in ("blob", "commit"):
        return None, "not_tracked", False
    mode, _kind, sha = entry
    if mode == "120000":
        return None, "symlink", False
    if mode == "160000":
        return None, "gitlink", False
    if mode not in ("100644", "100755") or sha != src.blob_sha:
        return None, "blob_mismatch", False
    head = _tree_entry(repo, "HEAD", src.path)
    drift = head is None or head[0] != mode or head[2] != src.blob_sha
    raw = _git(repo, "cat-file", "blob", src.blob_sha)
    if raw is None:
        return None, "blob_missing", drift
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "undecodable", drift
    if src.kind == "example_notebook":
        try:
            text = notebook_markdown(text)
        except ValueError:
            return None, "notebook_invalid", drift
    return text, None, drift


def _pointer_section(section: Section, pointer_id: str) -> Section | None:
    row = re.compile(rf"^\|\s*{re.escape(pointer_id)}\s*\|")
    rows = [line for line in section.text.split("\n") if row.match(line)]
    if not rows:
        return None
    text = "\n".join(rows)
    return Section(
        section.anchor,
        section.level,
        section.title,
        text,
        hashlib.sha256(text.encode()).hexdigest(),
    )


def _admit_sections(
    src: PublicSource, text: str, out: list[Exclusion]
) -> list[Section]:
    sections = split_sections(text)
    if src.sections is not None:
        present = {s.anchor for s in sections}
        out.extend(
            Exclusion(src.source_id, a, "section_missing")
            for a in src.sections
            if a not in present
        )
        wanted = set(src.sections)
        sections = [s for s in sections if s.anchor in wanted]
    if src.pointer_id is not None:
        pointer = _pointer_section(sections[0], src.pointer_id) if sections else None
        if pointer is None:
            if sections:
                out.append(Exclusion(src.source_id, None, "pointer_missing"))
            return []
        sections = [pointer]
    admitted: list[Section] = []
    for sec in sections:
        code = section_code(sec.text)
        if code:
            out.append(Exclusion(src.source_id, sec.anchor, code))
            continue
        status = src.section_status.get(sec.anchor, src.status)
        admitted.append(
            Section(sec.anchor, sec.level, sec.title, sec.text, sec.sha256, status)
        )
    return admitted


def build_corpus(reg: Register, repo: Path) -> Corpus:
    """Admit every eligible register row from its pinned blob."""
    documents: list[Document] = []
    exclusions: list[Exclusion] = []
    for src in reg.sources:
        text, code, drift = _read_pinned(Path(repo), reg.reviewed_commit, src)
        if text is None:
            exclusions.append(Exclusion(src.source_id, None, code or "blob_missing"))
            continue
        before = len(exclusions)
        sections = _admit_sections(src, text, exclusions)
        if not sections:
            if len(exclusions) == before:
                exclusions.append(Exclusion(src.source_id, None, "no_text"))
            continue
        documents.append(
            Document(
                source_id=src.source_id,
                path=src.path,
                blob_sha=src.blob_sha,
                kind=src.kind,
                authority=src.authority,
                status=src.status,
                notebook_role=src.notebook_role,
                superseded_by=src.superseded_by,
                head_drift=drift,
                sections=tuple(sections),
            )
        )
    return Corpus(documents=tuple(documents), exclusions=tuple(exclusions))
