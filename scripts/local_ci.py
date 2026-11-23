"""Run this repository's GitHub Actions pull-request checks locally (#1275).

GitHub Actions is unavailable, so the owner approved a local run of the same
checks as the merge gate. This CLI reads ``.github/workflows/*.yml``, decides
which workflows and jobs a pull request from ``--head`` into ``--base`` would
trigger (``on.pull_request`` branches, types, paths, paths-ignore and job
``if:``), and runs a local equivalent of every triggered job it knows how to
replay, against an LF checkout of the exact commit under test.

Usage::

    python scripts/local_ci.py --base origin/portfolio --list
    python scripts/local_ci.py --base origin/portfolio --jobs closes,pr-description \
        --pr-body-file body.md
    python scripts/local_ci.py --merged-with origin/feat/other --include-worktree

Every job reports PASS, FAIL, SKIPPED (not triggered) or NOT-REPRODUCIBLE
(with the reason). The exit code is 1 when any reproducible job fails.

Safety: job subprocesses get a scrubbed environment (no provider, database,
token or proxy variables; HOME points at a temp dir), servers bind only to
127.0.0.1 on a free port, output is redacted before it is printed, and no
job reads ``.env`` or operator databases.
"""

# One self-contained operator CLI (job selection + one runner per job), like
# tier_calls.py; splitting it would only add import plumbing.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
import base64
import contextlib
import fnmatch
import hashlib
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PASS = "PASS"  # noqa: S105 - a job status, not a password
FAIL = "FAIL"
SKIPPED = "SKIPPED"
NOT_REPRODUCIBLE = "NOT-REPRODUCIBLE"

SCRUB_PREFIXES = ("PI_", "DB_", "FMP", "OPENBB", "MYSQL", "FRED", "POLYGON", "GH_")
SCRUB_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "_PROXY")
DROP_VARS = ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME", "CONDA_PREFIX")
PR_DEFAULT_TYPES = ("opened", "synchronize", "reopened")
LINT_TYPE_STUBS = (
    "types-pytz",
    "types-requests",
    "types-termcolor",
    "types-tabulate",
    "types-PyYAML",
    "types-setuptools",
    "types-six",
)
BIN = "Scripts" if os.name == "nt" else "bin"
EXE = ".exe" if os.name == "nt" else ""


class LocalCiError(RuntimeError):
    """A local CI precondition failed (bad ref, merge conflict, git error)."""


@dataclass
class Result:
    """Outcome of one job."""

    key: str
    status: str
    detail: str = ""
    seconds: float = 0.0


# ---------------------------------------------------------------------------
# Secrets and environment
# ---------------------------------------------------------------------------


def _secret_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(SCRUB_PREFIXES) or any(m in upper for m in SCRUB_MARKERS)


def redact(text: str) -> str:
    """Replace the value of every credential-like environment variable."""
    for name, value in os.environ.items():
        if _secret_name(name) and len(value) >= 6:
            text = text.replace(value, "***")
    return re.sub(r"(?i)(authorization: *bearer +)\S+", r"\1***", text)


def hermetic_env(home: Path, **extra: str) -> dict[str, str]:
    """Return a scrubbed environment whose home directories are ``home``."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not _secret_name(name) and name.upper() not in DROP_VARS
    }
    for name in ("HOME", "USERPROFILE"):
        env[name] = str(home)
    env["PYTHONUTF8"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.update(extra)
    return env


def free_port() -> int:
    """Return a free TCP port on 127.0.0.1."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str, check: bool = True) -> str:
    """Run git in ``repo`` and return stripped stdout."""
    completed = subprocess.run(  # noqa: S603
        ["git", "-c", "core.autocrlf=false", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode != 0:
        raise LocalCiError(f"git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    """Return every path changed on ``head`` since its merge base with ``base``."""
    out = git(repo, "diff", "--name-only", "--no-renames", f"{base}...{head}")
    return [line for line in out.splitlines() if line]


def lint_diff_filter(paths: list[str]) -> list[str]:
    """Apply the workflow's grep pipeline to a list of changed paths."""
    pattern = re.compile(r"^(openbb_platform|cli)/.*\.py$")
    excluded = (
        "openbb_platform/core/openbb/package",
        "openbb_platform/tools/",
        "integration",
        "tests",
    )
    return [p for p in paths if pattern.search(p) and not any(e in p for e in excluded)]


def compute_diff_files(repo: Path, base: str, head: str) -> list[str]:
    """Return General Code Linting's ``diff_files`` for ``base...head``."""
    out = git(repo, "diff", "--diff-filter=d", "--name-only", f"{base}...{head}")
    return lint_diff_filter([line for line in out.splitlines() if line])


def _remove_worktree(repo: Path, path: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(path), check=False)
    shutil.rmtree(path, ignore_errors=True)
    git(repo, "worktree", "prune", check=False)


@contextlib.contextmanager
def checkout(repo: Path, commit: str, dest: Path) -> Iterator[Path]:
    """Check ``commit`` out (LF, detached) at ``dest``; remove it afterwards."""
    git(repo, "worktree", "add", "--detach", str(dest), commit)
    try:
        yield dest
    finally:
        _remove_worktree(repo, dest)


def _commit_tree(repo: Path, tree: str, parents: list[str], message: str) -> str:
    args = ["-c", "user.name=local-ci", "-c", "user.email=local-ci@localhost.invalid"]
    args += ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args, "-m", message)


def merge_commit(repo: Path, head: str, other: str) -> str:
    """Return an unreferenced merge commit of ``head`` and ``other``."""
    head_sha = git(repo, "rev-parse", "--verify", f"{head}^{{commit}}")
    other_sha = git(repo, "rev-parse", "--verify", f"{other}^{{commit}}")
    completed = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "merge-tree",
            "--write-tree",
            "--name-only",
            head_sha,
            other_sha,
        ],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        conflicts = ", ".join(lines[1:6]) or completed.stderr.strip()
        raise LocalCiError(f"merge conflict with {other}: {conflicts}")
    return _commit_tree(repo, lines[0], [head_sha, other_sha], f"local-ci: {other}")


@contextlib.contextmanager
def merged_snapshot(repo: Path, head: str, other: str) -> Iterator[tuple[str, Path]]:
    """Yield ``(commit, path)`` of ``head`` merged with ``other`` in a temp worktree."""
    commit = merge_commit(repo, head, other)
    parent = Path(tempfile.mkdtemp(prefix="local-ci-merge-"))
    try:
        with checkout(repo, commit, parent / "merged") as path:
            yield commit, path
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def snapshot_worktree(repo: Path) -> str:
    """Return an unreferenced commit of the working tree (tracked + untracked)."""
    index = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index")
    )
    with tempfile.TemporaryDirectory(prefix="local-ci-index-") as tmp:
        temp_index = Path(tmp) / "index"
        if index.exists():
            shutil.copyfile(index, temp_index)
        env = {**os.environ, "GIT_INDEX_FILE": str(temp_index)}
        for args in (["add", "-A"], ["write-tree"]):
            completed = subprocess.run(  # noqa: S603
                ["git", *args],  # noqa: S607
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise LocalCiError(f"git {args[0]}: {completed.stderr.strip()}")
        tree = completed.stdout.strip()
    head = git(repo, "rev-parse", "HEAD")
    return _commit_tree(repo, tree, [head], "local-ci: working tree snapshot")


# ---------------------------------------------------------------------------
# Workflow parsing and job selection
# ---------------------------------------------------------------------------


@dataclass
class Workflow:
    """One parsed workflow file."""

    stem: str
    name: str
    triggers: dict[str, Any]
    jobs: dict[str, Any]
    env: dict[str, Any] = field(default_factory=dict)


@dataclass
class Selected:
    """One (matrix-expanded) job and whether a pull request triggers it."""

    workflow: Workflow
    job_id: str
    matrix: dict[str, str]
    name: str
    triggered: bool
    reason: str

    @property
    def key(self) -> str:
        """Return ``stem:job`` plus ``[matrix values]`` when expanded."""
        suffix = f"[{','.join(self.matrix.values())}]" if self.matrix else ""
        return f"{self.workflow.stem}:{self.job_id}{suffix}"


def _normalize_triggers(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {raw: {}}
    if isinstance(raw, list):
        return {str(event): {} for event in raw}
    if isinstance(raw, dict):
        return {str(k): (v or {}) for k, v in raw.items()}
    return {}


def load_workflows(workflow_dir: Path) -> list[Workflow]:
    """Parse every ``*.yml`` / ``*.yaml`` workflow in ``workflow_dir``."""
    workflows = []
    for path in sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # YAML 1.1 reads the bare key ``on`` as boolean True.
        raw = doc.get("on", doc.get(True))
        workflows.append(
            Workflow(
                stem=path.stem,
                name=str(doc.get("name") or path.stem),
                triggers=_normalize_triggers(raw),
                jobs=doc.get("jobs") or {},
                env=doc.get("env") or {},
            )
        )
    return workflows


def _glob_regex(pattern: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char in "?+" and out:
            out[-1] = f"(?:{out[-1]}){char}"
        elif char == "[":
            end = pattern.find("]", i + 1)
            out.append(pattern[i : end + 1] if end > i else re.escape(char))
            i = end if end > i else i
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


def github_glob_match(pattern: str, path: str) -> bool:
    """Match a GitHub Actions filter glob (``*`` stops at ``/``; ``**`` crosses)."""
    return re.fullmatch(_glob_regex(pattern), path) is not None


def _filter_hits(patterns: list[str], path: str) -> bool:
    hit = False
    for pattern in patterns:
        if pattern.startswith("!"):
            if github_glob_match(pattern[1:], path):
                hit = False
        elif github_glob_match(pattern, path):
            hit = True
    return hit


def pull_request_skip_reason(
    workflow: Workflow, base_branch: str, changed: list[str], action: str
) -> str | None:
    """Return why a pull request would not trigger ``workflow`` (None = runs)."""
    if "pull_request" not in workflow.triggers:
        events = ", ".join(workflow.triggers) or "none"
        return f"no pull_request trigger (on: {events})"
    config = workflow.triggers["pull_request"] or {}
    types = config.get("types") or PR_DEFAULT_TYPES
    if action not in types:
        return f"pull_request types {list(types)} exclude {action}"
    branches = [str(b) for b in config.get("branches") or []]
    if branches and not _filter_hits(branches, base_branch):
        return f"base {base_branch} not in branches {branches}"
    ignored = [str(b) for b in config.get("branches-ignore") or []]
    if ignored and _filter_hits(ignored, base_branch):
        return f"base {base_branch} in branches-ignore"
    paths = [str(p) for p in config.get("paths") or []]
    if paths and not any(_filter_hits(paths, p) for p in changed):
        return "no changed file matches paths filter"
    ignore = [str(p) for p in config.get("paths-ignore") or []]
    if ignore and all(_filter_hits(ignore, p) for p in changed):
        return "every changed file matches paths-ignore"
    return None


_ATOM = re.compile(r"^(!)?\s*([\w.\-]+)\s*(?:(==|!=)\s*'([^']*)')?$")


def evaluate_if(expr: Any, context: dict[str, str]) -> bool | None:
    """Evaluate a simple job ``if:`` (``==``/``!=``, ``&&``, ``||``); None = unknown."""
    if expr is None:
        return True
    if isinstance(expr, bool):
        return expr
    text = str(expr).strip()
    text = text.removeprefix("${{").removesuffix("}}").strip()
    if "(" in text and not re.fullmatch(r"[^()]*\(\)[^()]*", text):
        return None
    functions = {"always()": "true", "success()": "true", "failure()": ""}
    functions["cancelled()"] = ""
    disjuncts = []
    for part in text.split("||"):
        values = []
        for raw_atom in part.split("&&"):
            atom = raw_atom.strip()
            if atom in functions:
                values.append(bool(functions[atom]))
                continue
            match = _ATOM.match(atom)
            if not match:
                return None
            negate, name, op, literal = match.groups()
            value = context.get(name, "")
            truth = (
                bool(value)
                if op is None
                else (value.lower() == literal.lower()) == (op == "==")
            )
            values.append(not truth if negate else truth)
        disjuncts.append(all(values))
    return any(disjuncts)


def _expand_matrix(job: dict[str, Any]) -> list[dict[str, str]]:
    matrix = ((job.get("strategy") or {}).get("matrix")) or {}
    axes = {
        k: [str(v) for v in values]
        for k, values in matrix.items()
        if k not in ("include", "exclude") and isinstance(values, list)
    }
    if not axes:
        return [{}]
    return [dict(zip(axes, combo)) for combo in itertools.product(*axes.values())]


def select_jobs(
    workflows: list[Workflow],
    *,
    base_branch: str,
    changed: list[str],
    head_branch: str = "",
    action: str = "synchronize",
) -> list[Selected]:
    """Return every job of every workflow with its pull-request trigger verdict."""
    context = {
        "github.event_name": "pull_request",
        "github.base_ref": base_branch,
        "github.head_ref": head_branch,
    }
    selected = []
    for workflow in workflows:
        skip = pull_request_skip_reason(workflow, base_branch, changed, action)
        for job_id, raw_job in workflow.jobs.items():
            job = raw_job or {}
            verdict = evaluate_if(job.get("if"), context)
            reason = skip or ""
            if skip is None and verdict is False:
                reason = f"job if: {job.get('if')} is false for pull_request"
            elif skip is None and verdict is None:
                reason = "job if: not evaluable locally; assumed to run"
            for matrix in _expand_matrix(job):
                name = str(job.get("name") or job_id)
                for axis, value in matrix.items():
                    name = re.sub(
                        r"\$\{\{\s*matrix\." + re.escape(axis) + r"\s*}}", value, name
                    )
                triggered = skip is None and verdict is not False
                selected.append(
                    Selected(workflow, job_id, matrix, name, triggered, reason)
                )
    return selected


def filter_jobs(selected: list[Selected], patterns: list[str]) -> list[Selected]:
    """Keep jobs whose key, ``stem:job``, stem or job id matches a pattern."""
    if not patterns:
        return selected

    def hit(sel: Selected, pattern: str) -> bool:
        names = (
            sel.key,
            f"{sel.workflow.stem}:{sel.job_id}",
            sel.workflow.stem,
            sel.job_id,
        )
        return pattern in names or fnmatch.fnmatchcase(sel.key, pattern)

    return [s for s in selected if any(hit(s, p) for p in patterns)]


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def find_bash() -> str:
    """Return Git Bash on Windows (never WSL's ``bash.exe``), else ``bash``."""
    override = os.environ.get("LOCAL_CI_BASH")
    if override:
        return override
    if os.name == "nt":
        exec_path = Path(git(Path.cwd(), "--exec-path"))
        for root in exec_path.parents:
            candidate = root / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    return shutil.which("bash") or "bash"


def run_cmd(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 3600,
) -> tuple[int, str]:
    """Run ``argv``; return ``(returncode, redacted combined output)``."""
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, redact(f"{argv[0]}: {exc}")
    return completed.returncode, redact(completed.stdout + completed.stderr)


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def uv_python(version: str) -> str | None:
    """Return an interpreter for ``version`` via ``uv python find`` (or None)."""
    uv = shutil.which("uv")
    if not uv:
        return None
    code, out = run_cmd([uv, "python", "find", version], cwd=Path.cwd(), timeout=60)
    path = out.strip().splitlines()[-1] if out.strip() else ""
    return path if code == 0 and Path(path).is_file() else None


def venv_tool(venv: Path, tool: str) -> str:
    """Return the path of a console script inside ``venv``."""
    return str(venv / BIN / f"{tool}{EXE}")


# ---------------------------------------------------------------------------
# Job context and step runner
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Everything a job runner needs."""

    repo: Path
    tree: Path
    work: Path
    cache: Path
    base: str
    head: str
    base_branch: str
    head_branch: str
    pr_body: str | None
    venvs: dict[str, Path] = field(default_factory=dict)

    @property
    def home(self) -> Path:
        """Return the temp HOME every job runs with."""
        path = self.work / "home"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def env(self, **extra: str) -> dict[str, str]:
        """Return the hermetic job environment."""
        return hermetic_env(self.home, PIP_CACHE_DIR=str(self.cache / "pip"), **extra)


@dataclass
class Step:
    """One command of a job; ``expect_fail`` inverts the verdict."""

    name: str
    argv: list[str]
    cwd: Path
    env: dict[str, str] | None = None
    expect_fail: bool = False


def run_steps(ctx: Context, key: str, steps: list[Step]) -> Result:
    """Run steps in order, stopping at the first failure (like ``bash -e``)."""
    log = ctx.work / "logs" / (re.sub(r"[^\w.-]+", "_", key) + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        for step in steps:
            code, out = run_cmd(step.argv, cwd=step.cwd, env=step.env or ctx.env())
            handle.write(f"## {step.name} (exit {code})\n{out}\n")
            failed = (code == 0) if step.expect_fail else (code != 0)
            if failed:
                return Result(
                    key, FAIL, f"step '{step.name}' exit {code}\n{_tail(out)}"
                )
    return Result(key, PASS, f"{len(steps)} steps; log {log.name}")


def ensure_venv(
    ctx: Context, label: str, version: str, packages: list[str], cwd: Path
) -> Path | str:
    """Create (or reuse) a cached venv; return its path or a NOT-REPRODUCIBLE reason."""
    key = "\n".join([label, version, *packages])
    # Short directory names: Windows MAX_PATH breaks deep site-packages paths.
    venv = ctx.cache / "v" / hashlib.sha256(key.encode()).hexdigest()[:10]
    stamp = venv / ".local-ci-ready"
    if stamp.exists():
        return venv
    python = uv_python(version)
    if python is None:
        return f"Python {version} not found (install with: uv python install {version})"
    shutil.rmtree(venv, ignore_errors=True)
    # ``-m venv`` runs from the cache dir so no checkout module shadows the stdlib.
    for argv, where in (
        ([python, "-m", "venv", str(venv)], ctx.cache),
        ([venv_tool(venv, "python"), "-m", "pip", "install", *packages], cwd),
    ):
        code, out = run_cmd(argv, cwd=where, env=ctx.env())
        if code != 0:
            raise LocalCiError(f"venv {label}: {_tail(out, 10)}")
    stamp.write_text(key, encoding="utf-8")
    return venv


# ---------------------------------------------------------------------------
# Job runners
# ---------------------------------------------------------------------------


def run_closes_syntax(tree: Path, head_branch: str, body: str | None) -> Result:
    """Replay ``portfolio-intel-closes-syntax`` with the PR body as data."""
    key = "closes-syntax"
    if not re.match(r"(?i)^(feat/pi-|feature/pi-|pi/)", head_branch):
        return Result(key, PASS, f"head '{head_branch}' out of scope; check skipped")
    if body is None:
        return Result(key, NOT_REPRODUCIBLE, "needs the PR body: pass --pr-body-file")
    bash = find_bash()
    script = (
        "set -euo pipefail\n"
        "source .github/scripts/closes-syntax-check.sh\n"
        "printf '%s' \"$PR_BODY\" | check_closes_syntax\n"
    )
    env = {**hermetic_env(tree), "PR_BODY": body}
    code, out = run_cmd([bash, "-c", script], cwd=tree, env=env, timeout=120)
    if code != 0:
        return Result(key, FAIL, _tail(out))
    code, out = run_cmd(
        [bash, ".github/scripts/test-closes-syntax.sh"], cwd=tree, env=env, timeout=300
    )
    if code != 0:
        return Result(key, FAIL, "self-test failed\n" + _tail(out))
    return Result(key, PASS, "Closes clause valid; self-test passed")


def run_pr_description(body: str | None) -> Result:
    """Replay ``pr_description``: the body must have non-whitespace content."""
    key = "pr-description"
    if body is None:
        return Result(key, NOT_REPRODUCIBLE, "needs the PR body: pass --pr-body-file")
    if not body.strip():
        return Result(key, FAIL, "PR description is empty")
    return Result(key, PASS, "PR description present")


def _code_linting(ctx: Context, sel: Selected) -> Result:
    diff_files = compute_diff_files(ctx.repo, ctx.base, ctx.head)
    packages = ["./openbb_platform/extensions/devtools", *LINT_TYPE_STUBS]
    devtools = (
        ctx.tree / "openbb_platform/extensions/devtools/pyproject.toml"
    ).read_bytes()
    label = "lint-" + hashlib.sha256(devtools).hexdigest()[:8]
    venv = ensure_venv(ctx, label, "3.10", packages, ctx.tree)
    if isinstance(venv, str):
        return Result(sel.key, NOT_REPRODUCIBLE, venv)
    tool = _bind(venv_tool, venv)
    skip_file = (ctx.tree / ".codespell.skip").read_text(encoding="utf-8")
    skip = skip_file.replace("\n", ",").removesuffix(",")
    contract = "scripts/tests/test_general_linting_workflow.py"
    steps = [
        Step(
            "lint contract", [tool("python"), "-m", "pytest", contract, "-q"], ctx.tree
        ),
        Step(
            "lint contract ruff",
            [tool("ruff"), "check", "--no-fix", contract],
            ctx.tree,
        ),
        Step(
            "codespell",
            [
                tool("codespell"),
                "--ignore-words=.codespell.ignore",
                f"--skip={skip}",
                "--quiet-level=2",
            ],
            ctx.tree,
        ),
    ]
    if diff_files:
        mypy_flags = [
            "--ignore-missing-imports",
            "--scripts-are-modules",
            "--check-untyped-defs",
        ]
        steps += [
            Step("black", [tool("black"), "--diff", "--check", *diff_files], ctx.tree),
            Step(
                "mypy",
                [tool("mypy"), *diff_files, *mypy_flags, "--platform", "linux"],
                ctx.tree,
            ),
            Step("pylint", [tool("pylint"), *diff_files], ctx.tree),
            Step("ruff", [tool("ruff"), "check", *diff_files], ctx.tree),
        ]
    result = run_steps(ctx, sel.key, steps)
    note = f"diff_files={len(diff_files)}"
    depth = git(ctx.repo, "rev-list", "--count", f"{ctx.base}...{ctx.head}")
    if depth.isdigit() and int(depth) > 20:
        note += f"; CI caveat: {depth} commits on both sides exceed fetch-depth 20"
    result.detail = f"{note}; {result.detail}"
    return result


def _bind(func: Callable[[Path, str], str], venv: Path) -> Callable[[str], str]:
    """Bind ``venv`` as the first argument of ``func``."""
    return lambda name: func(venv, name)


def _markdown_lint(ctx: Context, sel: Selected) -> Result:
    docker = shutil.which("docker")
    if not docker or run_cmd([docker, "info"], cwd=ctx.tree, timeout=60)[0] != 0:
        return Result(sel.key, NOT_REPRODUCIBLE, "docker daemon not available")
    job = sel.workflow.jobs[sel.job_id]
    step = next(
        s for s in job["steps"] if str(s.get("uses", "")).startswith("docker://")
    )
    image = step["uses"].removeprefix("docker://")
    args = str((step.get("with") or {}).get("args", "")).split()
    mount = f"{ctx.tree}:/github/workspace"
    argv = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        mount,
        "-w",
        "/github/workspace",
    ]
    return run_steps(
        ctx,
        sel.key,
        [
            Step("pull", [docker, "pull", image], ctx.tree),
            Step("lint", [*argv, image, *args], ctx.tree),
        ],
    )


class _UniqueKeyLoader(yaml.SafeLoader):  # pylint: disable=too-many-ancestors
    """SafeLoader that rejects duplicate keys and tolerates custom tags."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in keys:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        keys.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)
_UniqueKeyLoader.add_multi_constructor("!", lambda _loader, _suffix, _node: None)


def validate_json_yaml(
    tree: Path, files: list[str], yaml_exclude: str, json_exclude: str
) -> list[str]:
    """Return one error line per invalid JSON or YAML file."""
    errors = []
    for rel in files:
        suffix = Path(rel).suffix.lower()
        try:
            text = (tree / rel).read_text(encoding="utf-8")
            if suffix == ".json" and not (
                json_exclude and re.search(json_exclude, rel)
            ):
                json.loads(text, parse_constant=_reject_constant)
            elif suffix in (".yml", ".yaml") and not (
                yaml_exclude and re.search(yaml_exclude, rel)
            ):
                documents = list(
                    yaml.load_all(text, Loader=_UniqueKeyLoader)  # noqa: S506
                )
                if len(documents) > 1:
                    raise ValueError("multiple YAML documents")
        except (ValueError, UnicodeDecodeError, yaml.YAMLError, OSError) as exc:
            errors.append(f"{rel}: {str(exc).splitlines()[0]}")
    return errors


def _reject_constant(name: str) -> Any:
    raise ValueError(f"invalid JSON constant {name}")


def _json_yaml(ctx: Context, sel: Selected) -> Result:
    job = sel.workflow.jobs[sel.job_id]
    step = next(
        s for s in job["steps"] if "json-yaml-validate" in str(s.get("uses", ""))
    )
    with_ = step.get("with") or {}
    files = [
        f
        for f in git(ctx.tree, "ls-files").splitlines()
        if Path(f).suffix.lower() in (".json", ".yml", ".yaml")
        and (ctx.tree / f).is_file()
    ]
    errors = validate_json_yaml(
        ctx.tree,
        files,
        str(with_.get("yaml_exclude_regex", "")),
        str(with_.get("json_exclude_regex", "")),
    )
    detail = (
        f"{len(files)} files checked (approximation of {step['uses'].split('@')[0]})"
    )
    if errors:
        return Result(sel.key, FAIL, detail + "\n" + "\n".join(errors[:25]))
    return Result(sel.key, PASS, detail)


def _bash_script_job(script: str) -> Callable[[Context, Selected], Result]:
    def runner(ctx: Context, sel: Selected) -> Result:
        return run_steps(ctx, sel.key, [Step(script, [find_bash(), script], ctx.tree)])

    return runner


def _lock_check(ctx: Context, sel: Selected) -> Result:
    uv_version = str(sel.workflow.env.get("UV_VERSION", ""))
    if not uv_version:
        return Result(sel.key, NOT_REPRODUCIBLE, "workflow env UV_VERSION missing")
    venv = ensure_venv(ctx, "uv", "3.13", [f"uv=={uv_version}"], ctx.tree)
    if isinstance(venv, str):
        return Result(sel.key, NOT_REPRODUCIBLE, venv)
    env = ctx.env(PATH=f"{venv / BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    argv = [venv_tool(venv, "python"), "scripts/lock_mcp_envs.py", "--check"]
    return run_steps(ctx, sel.key, [Step("lock check", argv, ctx.tree, env)])


def _pwsh() -> str | None:
    return shutil.which("pwsh")


def _reject_314(ctx: Context, sel: Selected) -> Result:
    python, pwsh = uv_python("3.14"), _pwsh()
    if not python or not pwsh:
        return Result(
            sel.key, NOT_REPRODUCIBLE, "needs uv-managed Python 3.14 and pwsh"
        )
    argv = [
        pwsh,
        "-NoProfile",
        "-File",
        "scripts/test_portfolio_mcp.ps1",
        "-Profile",
        "portfolio-read",
    ]
    argv += [
        "-Mode",
        "package",
        "-PythonExecutable",
        python,
        "-RepositoryRoot",
        str(ctx.tree),
    ]
    code, out = run_cmd(argv, cwd=ctx.tree, env=ctx.env(), timeout=600)
    if code == 0:
        return Result(
            sel.key, FAIL, "unsupported interpreter replay unexpectedly succeeded"
        )
    if "Unsupported Python 3.14" not in out or ">=3.10,<3.14" not in out:
        return Result(sel.key, FAIL, "diagnostic not explicit\n" + _tail(out))
    return Result(sel.key, PASS, "3.14 rejected with explicit diagnostic")


REPLAY_WHEELS = (
    "openbb_platform/core",
    "openbb_platform/extensions/platform_api",
    "openbb_platform/extensions/mcp_server",
    "openbb_platform/extensions/equity",
    "openbb_platform/extensions/portfolio",
    "openbb_platform/extensions/portfolio_intel",
    "openbb_platform/extensions/techtrade",
    "openbb_platform/extensions/backtest",
    "openbb_platform/extensions/regime",
    "openbb_platform/providers/fmp",
    "openbb_platform/providers/fmp_cached",
    "openbb_platform/providers/yfinance",
)


def _replay_profile(ctx: Context, sel: Selected) -> Result:
    version = sel.matrix.get("python-version", "3.12")
    python, pwsh = uv_python(version), _pwsh()
    if not python or not pwsh:
        return Result(
            sel.key, NOT_REPRODUCIBLE, f"needs uv-managed Python {version} and pwsh"
        )
    root = ctx.work / f"replay-{version}"
    wheels, venv = root / "wheels", root / "venv"
    py = venv_tool(venv, "python")
    tree = ctx.tree
    steps = [
        Step(
            "wheels",
            [
                python,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheels),
                *REPLAY_WHEELS,
            ],
            tree,
        ),
        Step("venv", [python, "-m", "venv", str(venv)], tree),
        Step("pip upgrade", [py, "-m", "pip", "install", "--upgrade", "pip"], tree),
    ]
    result = run_steps(ctx, sel.key, steps)
    if result.status != PASS:
        return result
    regular = [
        str(w)
        for w in wheels.glob("*.whl")
        if not w.name.startswith(("openbb_portfolio_intel-", "openbb_techtrade-"))
    ]
    paired = [
        str(next(wheels.glob(f"{n}-*.whl")))
        for n in ("openbb_techtrade", "openbb_portfolio_intel")
    ]
    package = [
        pwsh,
        "-NoProfile",
        "-File",
        "scripts/test_portfolio_mcp.ps1",
        "-Profile",
        "portfolio-read",
    ]
    package += [
        "-Mode",
        "package",
        "-PythonExecutable",
        py,
        "-RepositoryRoot",
        str(tree),
    ]
    absent = "import importlib.util; assert importlib.util.find_spec('openbb_financialtoolkit') is None"
    steps = [
        Step("install regular", [py, "-m", "pip", "install", *regular], tree),
        Step(
            "install techtrade",
            [py, "-m", "pip", "install", "--no-deps", paired[0]],
            tree,
        ),
        Step(
            "install portfolio_intel",
            [py, "-m", "pip", "install", "--no-deps", paired[1]],
            tree,
        ),
        Step(
            "extras",
            [py, "-m", "pip", "install", "openpyxl", "pandas-ta-classic"],
            tree,
        ),
        Step("pip check", [py, "-m", "pip", "check"], tree),
        Step(
            "test deps",
            [py, "-m", "pip", "install", "pytest", "pytest-asyncio", "pytest-mock"],
            tree,
        ),
        Step("build", [py, "-c", "import openbb; openbb.build()"], tree),
        Step("package mode", package, tree),
        Step("optional absent", [py, "-c", absent], tree),
    ]
    result = run_steps(ctx, sel.key, steps)
    if result.status != PASS:
        return result
    result = _replay_http(ctx, sel, venv, pwsh)
    if result.status != PASS:
        return result
    tests = [
        "openbb_platform/extensions/mcp_server/tests/integration/test_profile_protocol.py",
        "openbb_platform/extensions/mcp_server/tests/service/test_runtime_profiles.py",
    ]
    ft = "openbb_platform/extensions/financialtoolkit"
    steps = [
        Step("profile protocol", [py, "-m", "pytest", *tests, "-q"], tree),
        Step(
            "ft wheel",
            [python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), ft],
            tree,
        ),
    ]
    result = run_steps(ctx, sel.key, steps)
    if result.status != PASS:
        return result
    ft_wheel = str(next(wheels.glob("openbb_financialtoolkit-*.whl")))
    steps = [
        Step("ft install", [py, "-m", "pip", "install", ft_wheel], tree),
        Step("ft build", [py, "-c", "import openbb; openbb.build()"], tree),
        Step(
            "ft package mode",
            [*package, "-OptionalAnalytics", "openbb-financialtoolkit"],
            tree,
        ),
        Step(
            "ft tests",
            [
                py,
                "-m",
                "pytest",
                "openbb_platform/extensions/mcp_server/tests/app/test_analytics_profiles.py",
                "-q",
            ],
            tree,
        ),
    ]
    return run_steps(ctx, sel.key, steps)


def _http_answers(url: str) -> bool:
    """Return True when ``url`` gives any HTTP response (like ``curl --silent``)."""
    try:
        with urllib.request.urlopen(url, timeout=2):  # noqa: S310 - loopback URL
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def _replay_http(ctx: Context, sel: Selected, venv: Path, pwsh: str) -> Result:
    port = free_port()
    secret = "x" * 32
    env = ctx.env(
        OPENBB_MCP_RUNTIME_PROFILE="portfolio-read",
        OPENBB_MCP_CAPABILITY_PROFILE="portfolio-read",
        OPENBB_MCP_INSTALLATION_KIND="portfolio_venv",
        OPENBB_MCP_APP_TARGET="openbb_platform/extensions/portfolio/launch.py",
        OPENBB_MCP_ENABLE_TOOL_DISCOVERY="true",
        OPENBB_MCP_ENABLE_INTELLIGENCE_ADAPTER="true",
        OPENBB_MCP_SERVER_AUTH=json.dumps(["replay-user", secret]),
        PI_WIDGET_BACKEND_TOKEN="runtime-replay-token",  # noqa: S106
    )
    log = (ctx.work / "logs" / "openbb-mcp.log").open("w", encoding="utf-8")
    argv = [
        venv_tool(venv, "openbb-mcp"),
        "--app",
        "openbb_platform/extensions/portfolio/launch.py",
    ]
    argv += [
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--transport",
        "streamable-http",
        "--tool-discovery",
    ]
    # The server must outlive this block's polling; it is killed in ``finally``.
    server = subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
        argv, cwd=ctx.tree, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        for _ in range(60):
            if server.poll() is not None:
                return Result(sel.key, FAIL, "openbb-mcp exited before listening")
            if _http_answers(url):
                break
            time.sleep(1)
        token = base64.b64encode(f"replay-user:{secret}".encode()).decode()
        step = Step(
            "protocol",
            [
                pwsh,
                "-NoProfile",
                "-File",
                "./scripts/test_portfolio_mcp.ps1",
                "-Profile",
                "portfolio-read",
                "-Mode",
                "protocol",
                "-Uri",
                url,
                "-Authorization",
                f"Bearer {token}",
                "-TimeoutSeconds",
                "60",
            ],
            ctx.tree,
            env,
        )
        return run_steps(ctx, sel.key, [step])
    finally:
        server.kill()
        server.wait(timeout=30)
        log.close()


def _harness_venv(ctx: Context) -> Path | str:
    if "harness" in ctx.venvs:
        return ctx.venvs["harness"]
    python = uv_python("3.12")
    if python is None:
        return "Python 3.12 not found"
    venv = ctx.work / "harness-venv"
    py = venv_tool(venv, "python")
    editable = [
        "openbb_platform/core",
        "openbb_platform/extensions/backtest",
        "openbb_platform/extensions/portfolio_intel",
        "openbb_platform/tools/portfolio_snapshot_importer",
        "openbb_platform/tools/browser_test_harness/[test]",
    ]
    steps = [
        Step("venv", [python, "-m", "venv", str(venv)], ctx.tree),
        Step("pip upgrade", [py, "-m", "pip", "install", "--upgrade", "pip"], ctx.tree),
    ]
    steps += [
        Step(f"install {e}", [py, "-m", "pip", "install", "-e", e], ctx.tree)
        for e in editable
    ]
    result = run_steps(ctx, "harness-venv", steps)
    if result.status != PASS:
        raise LocalCiError("harness venv: " + result.detail)
    ctx.venvs["harness"] = venv
    return venv


def _harness_env(ctx: Context, name: str, **extra: str) -> dict[str, str]:
    db = str(ctx.work / f"pi-paper-{name}.db")
    return ctx.env(
        PI_WIDGET_BACKEND_AUTH_MODE="",
        PI_WIDGET_BACKEND_TOKEN="",
        PI_PAPER_ENGINE="sqlite",
        PI_PAPER_DB=db,
        **extra,
    )


def _standalone_harness(ctx: Context, sel: Selected) -> Result:
    venv = _harness_venv(ctx)
    if isinstance(venv, str):
        return Result(sel.key, NOT_REPRODUCIBLE, venv)
    story = sel.matrix.get("story", "portfolio")
    py = venv_tool(venv, "python")
    harness = ctx.tree / "openbb_platform/tools/browser_test_harness"
    run = [
        py,
        "-m",
        "openbb_browser_test_harness.run",
        "--story",
        story,
        "--mode",
        "standalone",
        "--out",
        f".dev-cycle/browser-harness-report-{story}",
    ]
    return run_steps(
        ctx,
        sel.key,
        [
            Step(
                "unit tests",
                [py, "-m", "pytest", "tests/", "-v", "--tb=short"],
                harness,
                _harness_env(ctx, "unit"),
            ),
            Step(f"{story} story", run, ctx.tree, _harness_env(ctx, "story")),
        ],
    )


def _fixture_drift(ctx: Context, sel: Selected) -> Result:
    venv = _harness_venv(ctx)
    if isinstance(venv, str):
        return Result(sel.key, NOT_REPRODUCIBLE, venv)
    harness = ctx.tree / "openbb_platform/tools/browser_test_harness"
    argv = [
        venv_tool(venv, "python"),
        "-m",
        "pytest",
        "tests/test_fixtures_are_current.py",
        "-v",
        "--tb=short",
    ]
    env = _harness_env(ctx, "fixtures", BROWSER_HARNESS_LIVE="1")
    return run_steps(ctx, sel.key, [Step("fixture drift", argv, harness, env)])


def _step_run(sel: Selected, step_name: str) -> str:
    """Return the ``run:`` text of the named step of the selected job."""
    for step in sel.workflow.jobs[sel.job_id].get("steps") or []:
        if step.get("name") == step_name:
            return str(step.get("run", ""))
    raise LocalCiError(f"{sel.key}: workflow has no step named {step_name!r}")


def _evidence_tests(head: Path) -> list[str]:
    """Mirror the workflow's 'Verify head evidence' test discovery."""
    policy_path = "openbb_platform/extensions/mcp_server/openbb_mcp_server/assets"
    policy = json.loads(
        (head / policy_path / "capability_policy.json").read_text(encoding="utf-8")
    )
    tests = {
        "openbb_platform/extensions/mcp_server/tests/service/test_coverage_diff.py",
        "openbb_platform/extensions/mcp_server/tests/app/test_prompt_dependencies.py",
    }
    for family in policy["traceability"]["work_families"].values():
        for evidence in family["source_evidence"]:
            if not (
                "/tests/" in f"/{evidence}"
                or evidence.startswith("tests/")
                or evidence.endswith("/tests")
            ):
                continue
            source = head / evidence
            files = [source] if source.is_file() else sorted(source.rglob("*"))
            for path in files:
                rel = path.relative_to(head).as_posix()
                if path.is_file() and _collectable_test(path, rel):
                    tests.add(rel)
    return sorted(tests)


def _collectable_test(path: Path, rel: str) -> bool:
    is_test_name = path.name.startswith("test_") or path.name.endswith("_test.py")
    in_tests = "/tests/" in f"/{rel}" or rel.startswith("tests/")
    return path.suffix == ".py" and is_test_name and in_tests


def _compare_inventories(ctx: Context, sel: Selected) -> Result:
    if ctx.base_branch != "portfolio":
        return Result(sel.key, FAIL, f"expected base portfolio, got {ctx.base_branch}")
    python = uv_python("3.12")
    if python is None:
        return Result(sel.key, NOT_REPRODUCIBLE, "Python 3.12 not found")
    editable = re.findall(
        r'-e "\$GITHUB_WORKSPACE/\$source/([^"]+)"',
        _step_run(sel, "Create isolated metadata environments"),
    )
    with checkout(ctx.repo, ctx.base, ctx.work / "base") as base_tree:
        trees = {"base": base_tree, "head": ctx.tree}
        for source, tree in trees.items():
            venv = ctx.work / f"{source}-venv"
            py = venv_tool(venv, "python")
            installs = [arg for path in editable for arg in ("-e", str(tree / path))]
            steps = [
                Step(f"{source} venv", [python, "-m", "venv", str(venv)], tree),
                Step(
                    f"{source} pip",
                    [py, "-m", "pip", "install", "--upgrade", "pip"],
                    tree,
                ),
                Step(
                    f"{source} editable", [py, "-m", "pip", "install", *installs], tree
                ),
                Step(
                    f"{source} pi_install",
                    [py, str(tree / "scripts/pi_install.py")],
                    tree,
                ),
                Step(
                    f"{source} fmp_trading",
                    [
                        py,
                        "-m",
                        "pip",
                        "install",
                        "-e",
                        str(tree / "openbb_platform/extensions/fmp_trading")
                        + "[agent]",
                    ],
                    tree,
                ),
                Step(
                    f"{source} test deps",
                    [
                        py,
                        "-m",
                        "pip",
                        "install",
                        "pytest",
                        "pytest-asyncio",
                        "pytest-mock",
                    ],
                    tree,
                ),
                Step(
                    f"{source} build", [py, "-c", "import openbb; openbb.build()"], tree
                ),
            ]
            result = run_steps(ctx, sel.key, steps)
            if result.status != PASS:
                return result
        head_py = venv_tool(ctx.work / "head-venv", "python")
        base_py = venv_tool(ctx.work / "base-venv", "python")
        tests = [str(ctx.tree / t) for t in _evidence_tests(ctx.tree)]
        steps = [
            Step("head evidence", [head_py, "-m", "pytest", *tests, "-q"], ctx.tree)
        ]
        for profile in ("portfolio-read", "portfolio-ops"):
            base_out = ctx.work / "base-inventories" / profile
            head_out = ctx.work / "head-inventories" / profile
            steps.append(
                Step(
                    f"base {profile}",
                    [
                        base_py,
                        str(base_tree / "scripts/audit_mcp_capabilities.py"),
                        "--profile",
                        profile,
                        "--output-dir",
                        str(base_out),
                        "--metadata-only",
                    ],
                    base_tree,
                )
            )
            steps.append(
                Step(
                    f"head {profile}",
                    [
                        head_py,
                        str(ctx.tree / "scripts/audit_mcp_capabilities.py"),
                        "--profile",
                        profile,
                        "--output-dir",
                        str(head_out),
                        "--metadata-only",
                        "--comparison-sha",
                        ctx.base,
                        "--base-ref",
                        ctx.base_branch,
                        "--require-lineage",
                        "--comparison-inventory",
                        str(base_out / "inventory.json"),
                        "--comparison-repository",
                        str(base_tree),
                        "--tests-verified",
                    ],
                    ctx.tree,
                )
            )
        return run_steps(ctx, sel.key, steps)


def _workspace_contract(ctx: Context, sel: Selected) -> Result:
    sub = "third_party/workspace"
    entry = git(ctx.repo, "ls-tree", ctx.head, sub).split()
    common = Path(
        git(ctx.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    modules = common / "modules" / sub
    python = uv_python("3.13")
    if len(entry) < 3 or not modules.is_dir() or python is None:
        return Result(
            sel.key,
            NOT_REPRODUCIBLE,
            "needs the initialized workspace submodule and Python 3.13",
        )
    target = ctx.tree / sub
    shutil.rmtree(target, ignore_errors=True)
    code, out = run_cmd(
        [
            "git",
            f"--git-dir={modules}",
            "-c",
            "core.autocrlf=false",
            "worktree",
            "add",
            "--detach",
            str(target),
            entry[2],
        ],
        cwd=ctx.repo,
    )  # noqa: S607
    if code != 0:
        return Result(
            sel.key, NOT_REPRODUCIBLE, "submodule commit unavailable: " + _tail(out, 3)
        )
    try:
        backend = target / "backend-api" / "backend"
        venv = ctx.work / "poetry-venv"
        env = ctx.env(POETRY_VIRTUALENVS_PATH=str(ctx.cache / "poetry-venvs"))
        poetry = venv_tool(venv, "poetry")
        tests = [
            "tests/test_workspace_mcp_surface_parity.py",
            "tests/test_workspace_mcp_bridge.py",
            "tests/test_workspace_mcp_resources.py",
        ]
        return run_steps(
            ctx,
            sel.key,
            [
                Step("venv", [python, "-m", "venv", str(venv)], backend, env),
                Step(
                    "poetry",
                    [venv_tool(venv, "python"), "-m", "pip", "install", "poetry"],
                    backend,
                    env,
                ),
                Step(
                    "poetry install",
                    [poetry, "install", "--with", "dev", "--no-root"],
                    backend,
                    env,
                ),
                Step(
                    "parity tests",
                    [poetry, "run", "python", "-m", "pytest", *tests, "-q"],
                    backend,
                    env,
                ),
            ],
        )
    finally:
        run_cmd(
            [
                "git",
                f"--git-dir={modules}",
                "worktree",
                "remove",
                "--force",
                str(target),
            ],
            cwd=ctx.repo,
        )  # noqa: S607
        run_cmd(
            ["git", f"--git-dir={modules}", "worktree", "prune"], cwd=ctx.repo
        )  # noqa: S607


RUNNERS: dict[tuple[str, str], Callable[[Context, Selected], Result]] = {
    ("portfolio-mcp-coverage", "compare-portfolio-inventories"): _compare_inventories,
    ("portfolio-mcp-coverage", "verify-workspace-contract"): _workspace_contract,
    ("general-linting", "code-linting"): _code_linting,
    ("general-linting", "markdown-link-check"): _markdown_lint,
    ("general-linting", "json-yaml-validate"): _json_yaml,
    ("portfolio-intel-closes-syntax", "check-closes-syntax"): lambda ctx, sel: _rekey(
        run_closes_syntax(ctx.tree, ctx.head_branch, ctx.pr_body), sel
    ),
    ("pr_description", "pr-description"): lambda ctx, sel: _rekey(
        run_pr_description(ctx.pr_body), sel
    ),
    ("portfolio-intel-auto-close-tests", "fixtures"): _bash_script_job(
        ".github/scripts/test-auto-close-cited-issues.sh"
    ),
    ("dual-mcp-lock", "lock-check"): _lock_check,
    ("portfolio-mcp-coverage", "reject-unsupported-interpreter"): _reject_314,
    ("portfolio-mcp-coverage", "replay-portfolio-profile"): _replay_profile,
    ("browser-test-harness", "standalone-harness"): _standalone_harness,
    ("browser-test-harness", "fixture-drift-check"): _fixture_drift,
}


def _rekey(result: Result, sel: Selected) -> Result:
    result.key = sel.key
    return result


def _not_reproducible_reason(sel: Selected) -> str:
    job = sel.workflow.jobs.get(sel.job_id) or {}
    uses = sorted(
        {
            str(s.get("uses", "")).split("@", maxsplit=1)[0]
            for s in job.get("steps") or []
            if s.get("uses")
        }
    )
    runs_on = job.get("runs-on", "?")
    return f"no local runner (runs-on {runs_on}; uses {', '.join(uses) or 'none'})"


def run_job(ctx: Context, sel: Selected) -> Result:
    """Run one selected job and time it."""
    if not sel.triggered:
        return Result(sel.key, SKIPPED, sel.reason)
    runner = RUNNERS.get((sel.workflow.stem, sel.job_id))
    if runner is None:
        return Result(sel.key, NOT_REPRODUCIBLE, _not_reproducible_reason(sel))
    start = time.monotonic()
    try:
        result = runner(ctx, sel)
    except LocalCiError as exc:
        result = Result(sel.key, FAIL, redact(str(exc)))
    result.seconds = time.monotonic() - start
    return result


def exit_code(results: list[Result]) -> int:
    """Return 1 when any reproducible job failed, else 0."""
    return 1 if any(r.status == FAIL for r in results) else 0


def render_table(results: list[Result]) -> str:
    """Return a fixed-width PASS/FAIL table (first detail line per job)."""
    width = max([len(r.key) for r in results] + [3])
    lines = [f"{'JOB':<{width}}  {'STATUS':<16}  {'TIME':>7}  DETAIL"]
    for r in results:
        first = (r.detail.splitlines() or [""])[0][:110]
        lines.append(f"{r.key:<{width}}  {r.status:<16}  {r.seconds:>6.0f}s  {first}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--base", default="origin/portfolio", help="base ref (default origin/portfolio)"
    )
    parser.add_argument(
        "--base-branch", help="branch name for filters (default: --base without remote)"
    )
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--head-branch", help="head branch name (default: current branch)"
    )
    parser.add_argument(
        "--include-worktree", action="store_true", help="test uncommitted changes too"
    )
    parser.add_argument("--merged-with", help="test head merged with this ref")
    parser.add_argument("--pr-body-file", type=Path)
    parser.add_argument(
        "--jobs", action="append", default=[], help="comma-separated job keys/globs"
    )
    parser.add_argument(
        "--list", action="store_true", help="only show the job selection"
    )
    parser.add_argument(
        "--cache-dir", type=Path, help="default <repo>/.dev-cycle/local-ci"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pylint: disable=too-many-locals
    """Select, run and report the pull-request jobs."""
    args = _parse_args(argv)
    repo = Path(git(args.repo, "rev-parse", "--show-toplevel"))
    base = git(repo, "rev-parse", "--verify", f"{args.base}^{{commit}}")
    base_branch = args.base_branch or re.sub(r"^(refs/remotes/)?[^/]+/", "", args.base)
    head_branch = args.head_branch or git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = (
        snapshot_worktree(repo)
        if args.include_worktree
        else git(repo, "rev-parse", "--verify", args.head)
    )
    body = args.pr_body_file.read_text(encoding="utf-8") if args.pr_body_file else None
    patterns = [p.strip() for group in args.jobs for p in group.split(",") if p.strip()]
    cache = (args.cache_dir or repo / ".dev-cycle" / "local-ci").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="local-ci-"))
    try:
        with contextlib.ExitStack() as stack:
            if args.merged_with:
                head, tree = stack.enter_context(
                    merged_snapshot(repo, head, args.merged_with)
                )
            else:
                tree = stack.enter_context(checkout(repo, head, work / "head"))
            changed = changed_paths(repo, base, head)
            workflows = load_workflows(tree / ".github" / "workflows")
            selected = filter_jobs(
                select_jobs(
                    workflows,
                    base_branch=base_branch,
                    changed=changed,
                    head_branch=head_branch,
                ),
                patterns,
            )
            sys.stdout.write(
                f"base {base_branch} {base[:10]}  head {head_branch} {head[:10]}  changed {len(changed)}\n"
            )
            if args.list:
                for sel in selected:
                    sys.stdout.write(
                        f"{'RUN ' if sel.triggered else 'skip'}  {sel.key}  {sel.reason}\n"
                    )
                return 0
            ctx = Context(
                repo, tree, work, cache, base, head, base_branch, head_branch, body
            )
            results = []
            for sel in selected:
                sys.stdout.write(f"-> {sel.key}\n")
                sys.stdout.flush()
                results.append(run_job(ctx, sel))
            report = [r.__dict__ for r in results]
            (cache / "last-report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            sys.stdout.write(render_table(results) + "\n")
            for r in results:
                if r.status == FAIL:
                    sys.stdout.write(f"\n--- {r.key} ---\n{r.detail}\n")
            return exit_code(results)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
