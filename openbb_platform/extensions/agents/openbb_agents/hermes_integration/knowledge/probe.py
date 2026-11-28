r"""Real-path probe for the gated public-knowledge tools (#1378-T02).

``--synthetic``  builds a synthetic public corpus in a temporary git repo,
                 starts the real gated stdio server (``hermes-finance``,
                 ``hermes_runtime``) with a temporary HOME and a closed
                 loopback DB port, and replays a scripted coordinator: a hit,
                 a wrong-revision near match, proposed-vs-implemented, an
                 absent answer and a private-tool denial. Each scripted
                 answer is graded with :func:`grounding.check_answer`.
``--synthetic --adversarial`` runs :mod:`.adversarial` instead: injected
                 instructions, private-path and notebook-output exclusion,
                 an obedient coordinator that must be denied every action,
                 and abstention on excluded evidence (#1378-T03).
``--register``   asks fixed public questions against the committed register.
``--grade-stdin`` grades owner-pasted answers (L6): one ``<question_id>\\t<answer>``
                 line per answer, cite keys and abstain markers only.

Output is identifiers, codes and counts only (no excerpts, no document
text). Exit 0 when every check passes, 1 on a failed check, 3 on usage.
No network, no services, no model calls.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..egress_guard import egress_guard
from . import adversarial, grounding
from ._stdio import _EGRESS, _env, _flags, _git

SYNTHETIC_DOCS = {
    "docs/Specs/gh-1-probe/spec.md": (
        "# Probe spec\n\n## Requirements\n\n| ID | Requirement |\n|---|---|\n"
        "| PQ-01 | Every answer cites a pinned section. |\n"
    ),
    "docs/designs/cap_v1.md": "# Cap v1\n\n## Excerpt cap\n\nThe excerpt cap is 600.\n",
    "docs/designs/cap_v2.md": "# Cap v2\n\n## Excerpt cap\n\nThe excerpt cap is 800.\n",
    "specs/gh-2-probe/plan.md": (
        "# Probe plan\n\n## Operations\n\n### reports.render\n\n"
        "The reports.render operation formats a public summary.\n"
    ),
}

# Fixed public questions for --register / --grade-stdin.
REGISTER_QUESTIONS = {
    "answerable": "PF-15",
    "proposed_vs_implemented": "documents.search",
    "absent": "zebra quokka platypus",
}


def _blob(root: Path, rel: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "rev-parse", f"HEAD:{rel}"],  # noqa: S607
        check=True,
        capture_output=True,
        timeout=60,
    )
    return out.stdout.decode("ascii").strip()


def build_synthetic_repo(root: Path) -> Path:
    """Create the synthetic corpus repo under ``root``; return its register."""
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for rel, text in SYNTHETIC_DOCS.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "synthetic")
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        timeout=60,
    )
    base = {"privacy_class": "public_reference", "model_context": "allowed"}
    paths = list(SYNTHETIC_DOCS)

    def row(source_id: str, idx: int, **extra: Any) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "path": paths[idx],
            "blob_sha": _blob(root, paths[idx]),
            "kind": "design",
            "authority": "repo_design",
            "status": "proposed",
            "status_evidence": "none",
            **base,
            **extra,
        }

    rows = [
        row("probe.spec", 0, kind="requirement_spec", authority="repo_requirement"),
        row("probe.cap.v1", 1, status="superseded", superseded_by=["probe.cap.v2"]),
        row("probe.cap.v2", 2, supersedes=["probe.cap.v1"]),
        row("probe.plan", 3, kind="implementation_plan", authority="repo_plan"),
    ]
    doc = {
        "schema_version": 1,
        "reviewed_commit": out.stdout.decode("ascii").strip(),
        "sources": rows,
    }
    register_path = root / "probe_register.json"
    register_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return register_path


Call = tuple[str, str, dict[str, Any]]


async def _session(flags: list[str], home: Path, calls: list[Call]) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "openbb_agents.mcp_server", *flags],
        env=_env(home),
        cwd=str(home),
    )
    out: dict[str, Any] = {}
    errlog = home / "server.err"
    with errlog.open("w", encoding="utf-8") as err, anyio.fail_after(180):
        async with (
            stdio_client(params, errlog=err) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            for key, name, args in calls:
                result = await session.call_tool(name, args)
                block = result.content[0] if result.content else None
                text = getattr(block, "text", "")
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = {}
                out[key] = (bool(result.isError), payload)
    return out


def _cite(payload: dict, source_id: str) -> str:
    for hit in payload.get("hits") or ():
        if f"doc:{source_id}@" in hit.get("cite", ""):
            return hit["cite"]
    return "[[doc:missing@000000000000#missing]]"


def _synthetic_checks(out: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return ``(check_id, expected, got)`` for the scripted coordinator."""
    hit = out["hit"][1]
    cap = out["cap"][1]
    ops = out["ops"][1]
    absent = out["absent"][1]
    spec = _cite(hit, "probe.spec")
    v1, v2 = _cite(cap, "probe.cap.v1"), _cite(cap, "probe.cap.v2")
    plan = _cite(ops, "probe.plan")
    wrong = re.sub(r"@[0-9a-f]{12}", "@" + "0" * 12, v2)

    def grade(answer: str, payload: dict) -> str:
        return ",".join(grounding.check_answer(answer, [payload]).codes)

    private_err, private = out["private"]
    return [
        ("hit_result", "evidence", hit.get("result", "-")),
        ("hit_match", "identifier", (hit.get("hits") or [{}])[0].get("match", "-")),
        (
            "hit_grounded",
            "ok",
            grade(f"Cites (proposed, repo_requirement) {spec}.", hit),
        ),
        (
            "revision_successor",
            "probe.cap.v2",
            "probe.cap.v2" if v2 in str(cap) else "-",
        ),
        (
            "revision_superseded_alone",
            "superseded_without_successor",
            grade(f"The cap is 600 (superseded, repo_design) {v1}.", cap),
        ),
        (
            "revision_wrong_blob",
            "unknown_cite",
            grade(f"The cap is 800 (proposed, repo_design) {wrong}.", cap),
        ),
        (
            "status_mislabel",
            "status_mislabel",
            grade(f"reports.render is implemented (proposed, repo_plan) {plan}.", ops),
        ),
        (
            "status_labelled",
            "ok",
            grade(f"reports.render is proposed (proposed, repo_plan) {plan}.", ops),
        ),
        ("absent_result", "no_evidence", absent.get("result", "-")),
        (
            "absent_abstain",
            "abstain_ok",
            grade("[[abstain:no_evidence]] searched the probe register", absent),
        ),
        ("absent_assert", "abstain_required", grade("Harvest in December.", absent)),
        (
            "private_denied",
            "capability_denied",
            private.get("error", "-") if private_err else "allowed",
        ),
    ]


def _run_synthetic() -> tuple[list[tuple[str, str, str]], int]:
    with tempfile.TemporaryDirectory(prefix="hfp-knowledge-probe-") as tmp:
        home = Path(tmp)
        register_path = build_synthetic_repo(home / "repo")
        calls: list[Call] = [
            ("hit", "knowledge_search", {"query": "PQ-01"}),
            ("cap", "knowledge_search", {"query": "excerpt cap"}),
            ("ops", "knowledge_search", {"query": "reports.render"}),
            ("absent", "knowledge_search", {"query": "capital gains"}),
            ("private", "get_positions", {"approved": True}),
        ]
        with egress_guard(refuse_live_ports=True) as attempts:
            out = anyio.run(_session, _flags(register_path), home, calls)
        errtext = (home / "server.err").read_text(encoding="utf-8")
    egress = len(attempts) + sum(int(n) for n in _EGRESS.findall(errtext))
    if not _EGRESS.search(errtext):
        egress += 1  # the server must report its own egress count
    return _synthetic_checks(out), egress


def _run_register() -> tuple[dict[str, dict], int]:
    with tempfile.TemporaryDirectory(prefix="hfp-knowledge-probe-") as tmp:
        home = Path(tmp)
        calls: list[Call] = [
            (qid, "knowledge_search", {"query": q})
            for qid, q in REGISTER_QUESTIONS.items()
        ]
        with egress_guard(refuse_live_ports=True) as attempts:
            out = anyio.run(_session, _flags(None), home, calls)
        errtext = (home / "server.err").read_text(encoding="utf-8")
    egress = len(attempts) + sum(int(n) for n in _EGRESS.findall(errtext))
    if not _EGRESS.search(errtext):
        egress += 1
    return {k: v[1] for k, v in out.items()}, egress


def _register_checks(payloads: dict[str, dict]) -> list[tuple[str, str, str]]:
    answerable = payloads["answerable"]
    ops = payloads["proposed_vs_implemented"]
    top = (ops.get("hits") or [{}])[0]
    return [
        ("answerable_result", "evidence", answerable.get("result", "-")),
        ("pvi_result", "evidence", ops.get("result", "-")),
        ("pvi_status", "proposed", top.get("status", "-")),
        ("absent_result", "no_evidence", payloads["absent"].get("result", "-")),
    ]


def _emit(checks: list[tuple[str, str, str]], egress: int) -> int:
    failed = 0
    for check_id, expected, got in checks:
        ok = got == expected
        failed += not ok
        sys.stdout.write(
            f"check id={check_id} expected={expected} got={got} ok={str(ok).lower()}\n"
        )
    sys.stdout.write(f"checks={len(checks)} failed={failed} egress={egress}\n")
    return 0 if failed == 0 and egress == 0 else 1


def _hit_lines(payloads: dict[str, dict]) -> None:
    for qid, payload in payloads.items():
        sys.stdout.write(
            f"question id={qid} result={payload.get('result')} "
            f"hits={len(payload.get('hits') or ())}\n"
        )
        for hit in payload.get("hits") or ():
            sys.stdout.write(
                f"hit question={qid} cite={hit['cite']} status={hit['status']} "
                f"authority={hit['authority']} match={hit['match']}\n"
            )


def _grade_stdin(payloads: dict[str, dict]) -> int:
    graded = failed = 0
    for line in sys.stdin.read().splitlines():
        qid, sep, answer = line.partition("\t")
        if not sep or qid not in payloads:
            sys.stdout.write("grade id=? verdict=unknown_question\n")
            failed += 1
            continue
        verdict = grounding.check_answer(answer, [payloads[qid]])
        graded += 1
        failed += not verdict.ok
        sys.stdout.write(f"grade id={qid} verdict={','.join(verdict.codes)}\n")
    sys.stdout.write(f"graded={graded} failed={failed}\n")
    return 0 if graded and not failed else 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: one of ``--synthetic`` [``--adversarial``], ``--register``, ``--grade-stdin``."""
    parser = argparse.ArgumentParser(prog="knowledge.probe")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--synthetic", action="store_true")
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--grade-stdin", action="store_true")
    parser.add_argument("--adversarial", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    if args.adversarial and not args.synthetic:
        sys.stderr.write("knowledge.probe: --adversarial requires --synthetic\n")
        return 3
    if args.adversarial:
        return adversarial.emit(*adversarial.run_adversarial())
    if args.synthetic:
        checks, egress = _run_synthetic()
        return _emit(checks, egress)
    if args.register or args.grade_stdin:
        payloads, egress = _run_register()
        if args.grade_stdin:
            return _grade_stdin(payloads) or (1 if egress else 0)
        _hit_lines(payloads)
        return _emit(_register_checks(payloads), egress)
    sys.stderr.write("knowledge.probe: --synthetic, --register or --grade-stdin\n")
    return 3


if __name__ == "__main__":
    sys.exit(main())
