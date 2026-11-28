"""Admission of read-only skills and quarantine of skill proposals (#1339-T02).

Hermes loads skills from every search root, in this pinned precedence
(``agent/skill_utils.py`` @ 710fa8a): trusted project > local
(``$HERMES_HOME/skills``) > ``skills.create_dir`` > ``skills.external_dirs``.
``create_dir`` is itself a search root, so a "quarantine" inside any root is not
a quarantine. The finance profile therefore admits only hash-pinned skills in
the local tier, requires every other root and every skill writer to be off, and
writes proposals only to a quarantine outside all roots.

A same-user deny ACL makes the admitted tree tamper-evident, not immutable: the
owner can rewrite the DACL (plan decision O6). The hash pin is what detects it.

Reports carry reason codes and manifest-relative skill names only, never
absolute paths or file content. Nothing here imports or runs Hermes.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .hermes_config import SkillFacts

TIER_PROJECT, TIER_LOCAL, TIER_CREATE_DIR, TIER_EXTERNAL = range(4)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_PROBE_PREFIX = ".hfp-write-probe-"


class ProposalRejected(ValueError):
    """A proposal was refused; ``reason`` is a code, never a path."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class SkillAdmission(BaseModel):
    """Admission verdict; ``reasons`` holds codes, never paths or content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blocked: bool
    reasons: list[str]
    admitted: list[str] = Field(default_factory=list)


def _raise(error: OSError) -> None:
    raise error


def is_link(path: Path) -> bool:
    """Return True for a symlink, an NTFS junction or any other reparse point."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def tree_sha256(directory: Path) -> str:
    """Hash a skill tree: sorted relative paths plus each file's sha256.

    Symlinks are hashed by their target string and never followed. An unreadable
    entry raises ``OSError``; it is never skipped silently.
    """
    digest = hashlib.sha256()
    entries: list[tuple[str, bytes]] = []
    root = Path(directory)
    for current, dirs, files in os.walk(root, onerror=_raise, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(current, name)
            rel = path.relative_to(root).as_posix()
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                entries.append((rel, b"L" + os.readlink(path).encode()))
            elif stat.S_ISREG(mode):
                entries.append((rel, b"F" + hashlib.sha256(path.read_bytes()).digest()))
            elif not stat.S_ISDIR(mode):
                entries.append((rel, b"O"))
    for rel, value in sorted(entries):
        digest.update(rel.encode("utf-8") + b"\0" + value + b"\n")
    return digest.hexdigest()


def _resolve(entry: str, hermes_home: Path) -> Path:
    """Resolve a config path like Hermes: ``~``/``${VAR}``, relative to HERMES_HOME."""
    path = Path(os.path.expandvars(os.path.expanduser(entry)))
    if not path.is_absolute():
        path = hermes_home / path
    return path.resolve()


def overlaps(a: Path, b: Path) -> bool:
    """Return True when ``a`` and ``b`` are one directory or one contains the other."""
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


def search_roots(hermes_home: Path, facts: SkillFacts) -> list[tuple[int, Path]]:
    """Recompute the pinned ``get_skill_search_roots`` order (project tier excluded).

    Unlike upstream, roots are listed even when they do not exist yet, since a
    root created later is loaded without notice.
    """
    home = Path(hermes_home).resolve()
    local = (home / "skills").resolve()
    roots: list[tuple[int, Path]] = [(TIER_LOCAL, local)]
    if facts.create_dir:
        create = _resolve(facts.create_dir, home)
        if create != local:  # upstream treats create_dir == local dir as unset
            roots.append((TIER_CREATE_DIR, create))
    for entry in facts.external_dirs:
        roots.append((TIER_EXTERNAL, _resolve(entry, home)))
    seen: set[Path] = set()
    unique = []
    for tier, path in roots:
        if path not in seen:
            seen.add(path)
            unique.append((tier, path))
    return unique


def _config_reasons(facts: SkillFacts, hermes_home: Path) -> list[str]:
    reasons: list[str] = []
    if facts.project_discovery is not False:
        reasons.append("project_discovery_enabled")
    if facts.external_dirs:
        reasons.append("external_dirs_set")
    roots = search_roots(hermes_home, facts)
    for tier, create in roots:
        if tier != TIER_CREATE_DIR:
            continue
        others = [path for t, path in roots if t != TIER_CREATE_DIR]
        if any(overlaps(create, other) for other in others):
            reasons.append("create_dir_inside_search_root")
        else:
            reasons.append("create_dir_set")  # an unpinned search root
    if facts.curator_enabled is not False:
        reasons.append("curator_enabled")
    if facts.background_review_enabled is not False:
        reasons.append("background_review_enabled")
    if facts.inline_shell is not False:
        reasons.append("inline_shell_enabled")
    # Disabled toolsets are subtracted last at tool granularity upstream, and the
    # pinned ``skills`` toolset is the one that names ``skill_manage``.
    if "skills" not in facts.disabled_toolsets:
        reasons.append("skill_manage_enabled")
    return reasons


def _frontmatter_name(text: str) -> str | None:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return str(name).strip().lower() if name else None


def _skill_names(skill_dir: Path) -> set[str]:
    names = {skill_dir.name.lower()}
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if text and not skill_md.is_symlink():
        name = _frontmatter_name(text)
        if name:
            names.add(name)
    return names


def _manifest_dirs(admitted: Mapping[str, str], skills_root: Path) -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for rel in admitted:
        parts = PurePosixPath(rel).parts
        if not parts or rel.startswith("/") or ".." in parts or ":" in rel:
            continue
        dirs[rel] = skills_root.joinpath(*parts)
    return dirs


def admitted_names(admitted: Mapping[str, str], skills_root: Path) -> set[str]:
    """Lower-cased directory and frontmatter names of every admitted skill."""
    names: set[str] = set()
    for rel, path in _manifest_dirs(admitted, Path(skills_root)).items():
        names |= _skill_names(path) if path.is_dir() else {PurePosixPath(rel).name}
    return {name.lower() for name in names}


def _dir_writable(directory: Path) -> bool:
    """Real write probe: create and remove one scratch file.

    ``tempfile.mkstemp`` is not used: on Windows it retries a denied create
    thousands of times.
    """
    name = Path(directory, _PROBE_PREFIX + secrets.token_hex(8))
    try:
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    os.close(fd)
    with contextlib.suppress(OSError):
        os.remove(name)
    return True


def _file_writable(path: Path) -> bool:
    """Open for read-write without writing; denied ACL or mode bits refuse it."""
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


def _tree_reasons(admitted: Mapping[str, str], skills_root: Path) -> list[str]:
    reasons: list[str] = []
    dirs = _manifest_dirs(admitted, skills_root)
    if len(dirs) != len(admitted):
        reasons.append("invalid_manifest_entry")
    for rel, path in sorted(dirs.items()):
        if not path.is_dir() or is_link(path):
            reasons.append(f"missing:{rel}")
        else:
            try:
                observed = tree_sha256(path)
            except OSError:
                reasons.append(f"unreadable:{rel}")
                continue
            if observed != admitted[rel]:
                reasons.append(f"drift:{rel}")
    admitted_dirs = [path.resolve() for path in dirs.values()]
    unadmitted = symlink = dir_writable = file_writable = False
    try:
        for current, subdirs, files in os.walk(
            skills_root, onerror=_raise, followlinks=False
        ):
            here = Path(current)
            links = [d for d in subdirs if is_link(Path(current, d))]
            symlink = symlink or bool(links)
            subdirs[:] = [d for d in subdirs if d not in links]  # never descend
            if not dir_writable and _dir_writable(here):
                dir_writable = True
            for name in files:
                path = here / name
                if is_link(path):
                    symlink = True
                    continue
                resolved = path.resolve()
                if not any(d in resolved.parents for d in admitted_dirs):
                    unadmitted = True
                if not file_writable and _file_writable(path):
                    file_writable = True
    except OSError:
        # A directory that cannot be listed could hide unadmitted content.
        reasons.append("unreadable_tree")
    if unadmitted:
        reasons.append("unadmitted_content")
    if symlink:
        # Symlinks, NTFS junctions and other reparse points all redirect a path.
        reasons.append("symlink_junction_or_reparse_point_in_tree")
    if dir_writable:
        reasons.append("admitted_dir_writable")
    if file_writable:
        reasons.append("admitted_file_writable")
    return reasons


def _quarantine_reasons(
    quarantine: Path, roots: list[tuple[int, Path]], names: set[str]
) -> list[str]:
    reasons: list[str] = []
    if any(overlaps(quarantine, root) for _tier, root in roots):
        reasons.append("quarantine_inside_search_root")
    if quarantine.is_dir():
        shadowed: set[str] = set()
        for skill_md in quarantine.rglob("SKILL.md"):
            shadowed |= _skill_names(skill_md.parent) & names
        reasons.extend(f"proposal_shadows_admitted:{n}" for n in sorted(shadowed))
    return reasons


def evaluate_skills(
    facts: SkillFacts,
    admitted: Mapping[str, str],
    skills_root: Path,
    *,
    quarantine: Path | None = None,
) -> SkillAdmission:
    """Admit the local skill tier only when it is pinned, read-only and alone.

    ``skills_root`` is ``$HERMES_HOME/skills``; ``admitted`` maps manifest-relative
    skill directories (POSIX form) to :func:`tree_sha256` pins.
    """
    skills_root = Path(skills_root)
    hermes_home = skills_root.parent
    reasons = _config_reasons(facts, hermes_home)
    if skills_root.is_dir():
        reasons += _tree_reasons(admitted, skills_root)
    else:
        reasons.append("skills_root_missing")
    if quarantine is not None:
        reasons += _quarantine_reasons(
            Path(quarantine).resolve(),
            search_roots(hermes_home, facts),
            admitted_names(admitted, skills_root),
        )
    return SkillAdmission(
        blocked=bool(reasons), reasons=reasons, admitted=sorted(admitted)
    )


def write_proposal(
    quarantine: Path,
    name: str,
    content: str,
    *,
    facts: SkillFacts,
    skills_root: Path,
    admitted: Mapping[str, str],
) -> Path:
    """Write ``<quarantine>/<name>/SKILL.md``; the only proposal writer.

    Refuses invalid names, a quarantine inside any search root, names that shadow
    an admitted skill (directory or frontmatter, case-insensitive) and overwrites.
    The proposal directory is re-checked for a link after the exclusive create and
    before any content is written; a directory swapped for a link in that window is
    refused and the empty file removed. A swap after that re-check, between it and
    the write, remains a residual race that Windows offers no handle-based way to close.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ProposalRejected("invalid_name")
    skills_root = Path(skills_root)
    quarantine = Path(quarantine).resolve()
    roots = search_roots(skills_root.parent, facts)
    if any(overlaps(quarantine, root) for _tier, root in roots):
        raise ProposalRejected("quarantine_inside_search_root")
    proposed = {name.lower()}
    front = _frontmatter_name(content)
    if front:
        proposed.add(front)
    if proposed & admitted_names(admitted, skills_root):
        raise ProposalRejected("shadows_admitted")
    proposal_dir = quarantine / name
    target = proposal_dir / "SKILL.md"
    # ``quarantine`` is resolved, so its ancestors hold no link; the proposal
    # directory and file must not be a symlink, junction or reparse point either.
    if any(is_link(path) for path in (proposal_dir, target)):
        raise ProposalRejected("link_in_proposal_path")
    proposal_dir.mkdir(parents=True, exist_ok=True)
    if is_link(proposal_dir) or proposal_dir.resolve() != proposal_dir:
        raise ProposalRejected("link_in_proposal_path")
    try:
        with target.open("x", encoding="utf-8", newline="") as handle:
            # Re-check after the create: a directory swapped for a link between
            # the checks above and the open would have redirected the file.
            if is_link(proposal_dir) or proposal_dir.resolve() != proposal_dir:
                escaped = True
            else:
                escaped = False
                handle.write(content)
    except FileExistsError as exc:
        raise ProposalRejected("proposal_exists") from exc
    if escaped:
        target.unlink(missing_ok=True)  # remove only the file this call created
        raise ProposalRejected("link_in_proposal_path")
    return target
