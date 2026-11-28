"""Generate or verify the public-knowledge register (#1378, Q1 allowlist).

``python scripts/build_public_sources_register.py --commit <rev>``
    write ``public_sources.json`` pinned to ``<rev>`` (a reviewed re-pin)
``python scripts/build_public_sources_register.py --check``
    regenerate at the committed register's ``reviewed_commit``; exit 1 if it differs

Reads only tracked blobs with hardened read-only git (``rev-parse``,
``ls-tree``, ``cat-file``); never opens the working tree, so untracked and
ignored files cannot enter. Output is deterministic for a given commit.
Statuses come from recorded evidence (merge PRs, the bundle's commit);
everything else is ``unknown``. Sections whose text hits the content scan are
left out of a row's ``sections`` allowlist. Prints identifiers and counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "openbb_platform" / "extensions" / "agents"))

# pylint: disable=wrong-import-position
from openbb_agents.hermes_integration.knowledge import (  # noqa: E402
    corpus,
    register,
)

BUNDLE = "docs/Specs/gh-1312-hermes-financial-planning"
# The commit that landed the gh-1312 bundle (status evidence for its rows).
BUNDLE_COMMIT = "ea3546edd16df6b2efe072f68608f0faad99e7b7"
ROOTS = (BUNDLE, "specs", "docs/designs", "docs/OpenBBPlatform", "docs/examples")
# HFP plans merged into portfolio -> merge PR number (reviewed).
MERGED_PLANS = {"1338": 1388, "1340": 1390, "1341": 1393, "1344": 1391, "1345": 1394}
NOTEBOOK_ROLES = {
    "COMMUNITY_EXAMPLE_TEMPLATE": "template",
    "googleColab": "setup_only",
    "copperToGoldRatio": "analytics",
    "impliedEarningsMove": "analytics",
    "usdLiquidityIndex": "analytics",
    "financialStatements": "explanation",
    "findSymbols": "explanation",
    "loadHistoricalPriceData": "explanation",
    "openbbPlatformAsLLMTools": "explanation",
    "openbb_vs_langchain": "explanation",
    "platform_standardization": "explanation",
}
BUNDLE_KIND = {
    "spec.md": ("requirement_spec", "repo_requirement"),
    "plan.md": ("design", "repo_design"),
    "research.md": ("design", "repo_reference"),
    "recommendations.md": ("design", "repo_reference"),
    "github-plan/plan.md": ("implementation_plan", "repo_plan"),
    "github-plan/coverage.md": ("implementation_plan", "repo_reference"),
    "github-plan/github-preview.md": ("implementation_plan", "repo_reference"),
}
TAX_SECTION = "8-official-tax-source-register"
TAX_YEARS = {"T06": 2025, "T11": 2025}
_PUBLIC = {"privacy_class": "public_reference", "model_context": "allowed"}


class RegisterBuildError(RuntimeError):
    """A git read failed or the tree lacks a required source."""


def _git(repo: Path, *args: str) -> bytes:
    out = corpus.git_read(repo, *args)
    if out is None:
        raise RegisterBuildError(f"git {args[0]} failed")
    return out


def _tree(repo: Path, commit: str) -> dict[str, str]:
    out = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *ROOTS)
    entries: dict[str, str] = {}
    for record in out.split(b"\x00"):
        meta, sep, name = record.partition(b"\t")
        if not sep:
            continue
        mode, kind, sha = meta.decode("ascii").split()
        if mode == "100644" and kind == "blob":
            entries[name.decode("utf-8")] = sha
    return entries


def _source_id(path: str) -> str:
    stem = path.removesuffix(".md").removesuffix(".ipynb")
    for prefix, short in (
        (f"{BUNDLE}/", "hfp.gh1312."),
        ("docs/designs/", "designs."),
        ("docs/OpenBBPlatform/", "platform."),
        ("docs/examples/", "examples."),
    ):
        if stem.startswith(prefix):
            stem = short + stem[len(prefix) :]
    if stem.startswith("specs/gh-"):
        stem = "hfp.plan.gh" + stem.split("-")[1]
    return stem.lower().replace("/", ".").replace(" ", "-")


def _unknown(kind: str, authority: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "authority": authority,
        "status": "unknown",
        "status_evidence": "none",
    }


def _classify(path: str) -> dict[str, Any] | None:
    meta: dict[str, Any]
    if path.startswith(f"{BUNDLE}/"):
        rel = path[len(BUNDLE) + 1 :]
        if rel not in BUNDLE_KIND:
            return None
        kind, authority = BUNDLE_KIND[rel]
        meta = {
            "kind": kind,
            "authority": authority,
            "status": "proposed",
            "status_evidence": f"commit:{BUNDLE_COMMIT}",
        }
    elif path.startswith("specs/gh-"):
        num = path.split("-")[1]
        if num not in MERGED_PLANS or not path.endswith("/plan.md"):
            return None
        meta = {
            "kind": "implementation_plan",
            "authority": "repo_plan",
            "status": "implemented",
            "status_evidence": f"pr:{MERGED_PLANS[num]}",
        }
    elif path.startswith("docs/designs/"):
        meta = _unknown("design", "repo_design")
    elif path.startswith("docs/OpenBBPlatform/"):
        meta = _unknown("platform_doc", "repo_reference")
    elif path.startswith("docs/examples/") and path.endswith(".ipynb"):
        name = path.rsplit("/", 1)[1].removesuffix(".ipynb")
        meta = _unknown("example_notebook", "repo_reference")
        meta["notebook_role"] = NOTEBOOK_ROLES[name]
    elif path.startswith("docs/examples/"):
        meta = _unknown("platform_doc", "repo_reference")
    else:
        return None
    return meta


def _clean_sections(repo: Path, path: str, blob: str) -> list[str] | None:
    raw = _git(repo, "cat-file", "blob", blob).decode("utf-8")
    text = corpus.notebook_markdown(raw) if path.endswith(".ipynb") else raw
    sections = corpus.split_sections(text)
    if not any(corpus.section_code(s.text) for s in sections):
        return None
    return [s.anchor for s in sections if not corpus.section_code(s.text)]


def build(repo: Path, commit: str) -> dict[str, Any]:
    """Return the register document pinned to ``commit``."""
    sha = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    reviewed = sha.decode("ascii").strip()
    rows: list[dict[str, Any]] = []
    for path, blob in sorted(_tree(repo, reviewed).items()):
        meta = _classify(path)
        if meta is None or corpus.path_code(path) is not None:
            continue
        notebook_role = meta.pop("notebook_role", None)
        row: dict[str, Any] = {
            "source_id": _source_id(path),
            "path": path,
            "blob_sha": blob,
            **meta,
        }
        if notebook_role is not None:
            row["notebook_role"] = notebook_role
        row |= _PUBLIC
        keep = _clean_sections(repo, path, blob)
        if keep is not None:
            row["sections"] = keep
        rows.append(row)
    research = next((r for r in rows if r["path"] == f"{BUNDLE}/research.md"), None)
    if research is None:
        raise RegisterBuildError("research.md missing at commit")
    for n in range(1, 13):
        pid = f"T{n:02d}"
        tax: dict[str, Any] = {
            "source_id": f"tax.{pid.lower()}",
            "path": research["path"],
            "blob_sha": research["blob_sha"],
            "kind": "tax_source_pointer",
            "authority": "official_primary",
            "status": "unknown",
            "status_evidence": "none",
            **_PUBLIC,
            "sections": [TAX_SECTION],
            "content": "pointer_only",
            "pointer_id": pid,
        }
        if pid in TAX_YEARS:
            tax["effective"] = {"tax_year": TAX_YEARS[pid]}
        rows.append(tax)
    return {"schema_version": 1, "reviewed_commit": reviewed, "sources": rows}


def render(repo: Path, commit: str) -> str:
    """Return the register text (LF, trailing newline) pinned to ``commit``."""
    doc = build(repo, commit)
    register.Register.model_validate_json(json.dumps(doc))  # never emit invalid
    return json.dumps(doc, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write (``--commit``) or verify (``--check``) the register."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--commit", help="revision to pin (writes the register)")
    mode.add_argument("--check", action="store_true", help="verify, write nothing")
    parser.add_argument("--output", type=Path, default=register.DEFAULT_REGISTER)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.check:
            current = args.output.read_bytes().decode("utf-8").replace("\r\n", "\n")
            commit = json.loads(current)["reviewed_commit"]
            expected = render(args.repo, commit)
            same = current == expected
            sys.stdout.write(
                f"commit={commit[:12]} result={'ok' if same else 'stale'}\n"
            )
            return 0 if same else 1
        text = render(args.repo, args.commit)
    except (RegisterBuildError, OSError, KeyError, ValueError) as exc:
        sys.stdout.write(f"register_build_error type={type(exc).__name__}\n")
        return 2
    args.output.write_text(text, encoding="utf-8", newline="\n")
    rows = json.loads(text)["sources"]
    narrowed = sum(
        1 for r in rows if "sections" in r and r.get("content") != "pointer_only"
    )
    sys.stdout.write(f"rows={len(rows)} narrowed={narrowed}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
