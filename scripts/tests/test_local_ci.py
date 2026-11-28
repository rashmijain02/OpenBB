"""Unit tests for ``scripts/local_ci.py`` (#1275 local CI-equivalent gate).

Fake workflow YAML and throwaway git repositories only: nothing here reads the
real workflows, installs packages, or touches the network.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import local_ci  # noqa: E402  pylint: disable=wrong-import-position

# ---------------------------------------------------------------------------
# Workflow and path-filter selection
# ---------------------------------------------------------------------------

FAKE_WORKFLOWS = {
    "lint.yml": """
        name: Lint
        on:
          pull_request:
            types: [opened, synchronize, edited]
        jobs:
          code:
            name: Code Linting
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
    "mcp.yml": """
        name: MCP
        on:
          pull_request:
            branches:
              - portfolio
            paths:
              - "openbb_platform/**"
              - "third_party/workspace"
        jobs:
          replay:
            name: Replay (Python ${{ matrix.python-version }})
            runs-on: ubuntu-latest
            strategy:
              matrix:
                python-version: ["3.12", "3.13"]
            steps: [{run: "true"}]
        """,
    "ignore.yml": """
        on:
          pull_request:
            paths-ignore:
              - "docs/**"
        jobs:
          any:
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
    "negate.yml": """
        on:
          pull_request:
            paths:
              - "src/**"
              - "!src/**/*.md"
        jobs:
          src:
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
    "dispatch.yml": """
        on:
          workflow_dispatch:
        jobs:
          manual:
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
    "harness.yml": """
        on:
          pull_request:
            branches: [portfolio, develop]
          workflow_dispatch:
        jobs:
          standalone:
            if: github.event_name == 'pull_request' || github.event.inputs.mode == 'standalone'
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
          workspace:
            if: github.event_name == 'workflow_dispatch' && github.event.inputs.mode == 'workspace'
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
    "closed-only.yml": """
        on:
          pull_request:
            types: [labeled]
        jobs:
          label:
            runs-on: ubuntu-latest
            steps: [{run: "true"}]
        """,
}


@pytest.fixture(name="workflows")
def _workflows(tmp_path: Path) -> list:
    """Write the fake workflow files and load them."""
    for name, body in FAKE_WORKFLOWS.items():
        (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return local_ci.load_workflows(tmp_path)


def _triggered(workflows: list, base: str, changed: list[str]) -> dict[str, bool]:
    return {
        sel.key: sel.triggered
        for sel in local_ci.select_jobs(workflows, base_branch=base, changed=changed)
    }


def test_on_key_parsed_even_though_yaml_reads_it_as_true(workflows: list) -> None:
    """PyYAML turns ``on:`` into ``True``; the loader must still see triggers."""
    lint = next(wf for wf in workflows if wf.stem == "lint")
    assert "pull_request" in lint.triggers


def test_path_filter_and_branch_filter_select_jobs(workflows: list) -> None:
    """Jobs run only when base branch and changed paths match the filters."""
    got = _triggered(workflows, "portfolio", ["openbb_platform/x/a.py"])
    assert got["lint:code"] is True
    assert got["mcp:replay[3.12]"] is True
    assert got["mcp:replay[3.13]"] is True
    assert got["ignore:any"] is True
    assert got["negate:src"] is False
    assert got["dispatch:manual"] is False
    assert got["harness:standalone"] is True
    assert got["harness:workspace"] is False
    assert got["closed-only:label"] is False


def test_paths_not_matching_skip_the_workflow(workflows: list) -> None:
    """A docs-only change skips path-filtered and paths-ignore workflows."""
    got = _triggered(workflows, "portfolio", ["docs/readme.md"])
    assert got["mcp:replay[3.12]"] is False
    assert got["ignore:any"] is False
    assert got["lint:code"] is True


def test_branch_filter_rejects_other_base(workflows: list) -> None:
    """``branches: [portfolio]`` does not run for a PR into develop."""
    got = _triggered(workflows, "develop", ["openbb_platform/x/a.py"])
    assert got["mcp:replay[3.12]"] is False
    assert got["harness:standalone"] is True


def test_submodule_path_and_negation(workflows: list) -> None:
    """An exact submodule path matches; a later ``!`` pattern excludes."""
    got = _triggered(workflows, "portfolio", ["third_party/workspace"])
    assert got["mcp:replay[3.12]"] is True
    got = _triggered(workflows, "main", ["src/pkg/doc.md", "src/pkg/a.py"])
    assert got["negate:src"] is True


def test_selection_reason_explains_skip(workflows: list) -> None:
    """A skipped job says why."""
    sel = {
        s.key: s
        for s in local_ci.select_jobs(
            workflows, base_branch="portfolio", changed=["docs/a.md"]
        )
    }
    assert "paths" in sel["mcp:replay[3.12]"].reason
    assert "workflow_dispatch" in sel["dispatch:manual"].reason or (
        "pull_request" in sel["dispatch:manual"].reason
    )


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("openbb_platform/**", "openbb_platform/a/b/c.py", True),
        ("scripts/*.py", "scripts/a.py", True),
        ("scripts/*.py", "scripts/tests/a.py", False),
        ("**.md", "docs/x/readme.md", True),
        ("third_party/workspace", "third_party/workspace", True),
        ("third_party/workspace", "third_party/workspace2", False),
        ("desktop/**", "desktopx/a", False),
        ("feat/pi-*", "feat/pi-release", True),
        ("[ab]x", "bx", True),
        # ``**/`` also matches zero directories (#1274 review CODE-1).
        ("src/**/*.md", "src/README.md", True),
        ("src/**/*.md", "src/a/b/README.md", True),
        ("src/**/*.md", "srcx/README.md", False),
        ("**/README.md", "README.md", True),
        ("**/README.md", "docs/README.md", True),
        ("**/README.md", "docs/xREADME.md", False),
    ],
)
def test_github_glob(pattern: str, path: str, expected: bool) -> None:
    """GitHub filter globs: ``*`` stops at ``/``, ``**`` crosses it."""
    assert local_ci.github_glob_match(pattern, path) is expected


@pytest.mark.parametrize(
    ("patterns", "path", "expected"),
    [
        (["src/**", "!src/**/*.md"], "src/README.md", False),
        (["src/**", "!src/**/*.md"], "src/a/README.md", False),
        (["src/**", "!src/**/*.md"], "src/a.py", True),
        (["**", "!**/README.md"], "README.md", False),
        (["**", "!**/README.md", "README.md"], "README.md", True),
    ],
)
def test_filter_negation_with_zero_directory_globstar(
    patterns: list[str], path: str, expected: bool
) -> None:
    """A ``!`` pattern with ``**/`` excludes files at depth zero too."""
    assert local_ci._filter_hits(patterns, path) is expected  # noqa: SLF001


def test_markdown_lint_mounts_the_tree_read_only(tmp_path: Path) -> None:
    """The markdown-lint container sees the tree read-only, with no network."""
    argv = local_ci.markdown_lint_docker_argv("docker", tmp_path)
    mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-v"]
    assert mounts == [f"{tmp_path}:/github/workspace:ro"]
    assert argv[argv.index("--network") + 1] == "none"


def test_jobs_option_filters_by_key_glob(workflows: list) -> None:
    """``--jobs`` patterns match full keys, workflow stems or job ids."""
    selected = local_ci.select_jobs(
        workflows, base_branch="portfolio", changed=["openbb_platform/a.py"]
    )
    keys = [s.key for s in local_ci.filter_jobs(selected, ["mcp:replay[3.13]"])]
    assert keys == ["mcp:replay[3.13]"]
    keys = [s.key for s in local_ci.filter_jobs(selected, ["mcp"])]
    assert keys == ["mcp:replay[3.12]", "mcp:replay[3.13]"]
    keys = [s.key for s in local_ci.filter_jobs(selected, ["code"])]
    assert keys == ["lint:code"]


# ---------------------------------------------------------------------------
# Temp git repository helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(repo: Path, rel: str, text: str = "x = 1\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture(name="repo")
def _repo(tmp_path: Path) -> Path:
    """Build a repo with ``base`` and a ``feat`` branch that diverged from it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "base")
    _write(repo, "openbb_platform/a/old.py")
    _write(repo, "openbb_platform/a/keep.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feat")
    for rel in (
        "openbb_platform/a/new.py",
        "openbb_platform/a/tests/test_new.py",
        "openbb_platform/a/latests.py",
        "openbb_platform/tools/tool.py",
        "openbb_platform/core/openbb/package/gen.py",
        "openbb_platform/a/integration_x.py",
        "cli/c.py",
        "scripts/s.py",
        "openbb_platform/a/readme.md",
    ):
        _write(repo, rel)
    _write(repo, "openbb_platform/a/keep.py", "x = 2\n")
    (repo / "openbb_platform/a/old.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat")
    _git(repo, "checkout", "-q", "base")
    _write(repo, "openbb_platform/base_only.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base advances")
    _git(repo, "checkout", "-q", "feat")
    return repo


def test_diff_files_matches_workflow_pipeline(repo: Path) -> None:
    """Three-dot diff, no deletions, py under openbb_platform|cli, exclusions."""
    files = local_ci.compute_diff_files(repo, "base", "feat")
    assert files == [
        "cli/c.py",
        "openbb_platform/a/keep.py",
        "openbb_platform/a/new.py",
    ]


def test_lint_filter_is_substring_grep_like_ci() -> None:
    """``grep -v tests`` drops any path containing ``tests`` (e.g. latests.py)."""
    assert local_ci.lint_diff_filter(
        ["openbb_platform/x/latests.py", "openbb_platform/x/ok.py", "scripts/s.py"]
    ) == ["openbb_platform/x/ok.py"]


def test_changed_paths_include_deletions_for_path_filters(repo: Path) -> None:
    """Path filters see every changed path, deletions included, base-only not."""
    changed = local_ci.changed_paths(repo, "base", "feat")
    assert "openbb_platform/a/old.py" in changed
    assert "scripts/s.py" in changed
    assert "openbb_platform/base_only.py" not in changed


def test_merged_snapshot_builds_temp_tree_and_cleans_up(repo: Path) -> None:
    """``--merged-with`` tests head+other in a detached worktree, then removes it."""
    refs_before = _git(repo, "for-each-ref")
    with local_ci.merged_snapshot(repo, "feat", "base") as (commit, path):
        assert (path / "openbb_platform/base_only.py").is_file()
        assert (path / "openbb_platform/a/new.py").is_file()
        assert _git(repo, "rev-parse", f"{commit}^1") == _git(repo, "rev-parse", "feat")
    assert not path.exists()
    assert _git(repo, "for-each-ref") == refs_before
    assert str(path) not in _git(repo, "worktree", "list")


def test_merged_snapshot_conflict_raises(repo: Path) -> None:
    """A conflicting merge is reported, not silently tested."""
    _git(repo, "checkout", "-q", "base")
    _write(repo, "openbb_platform/a/keep.py", "x = 3\n")
    _git(repo, "commit", "-q", "-am", "conflict")
    with (
        pytest.raises(local_ci.LocalCiError, match="conflict"),
        local_ci.merged_snapshot(repo, "feat", "base"),
    ):
        pass


# ---------------------------------------------------------------------------
# Closes-syntax and PR description
# ---------------------------------------------------------------------------

FAKE_CHECK = """\
check_closes_syntax() {
  local body
  body=$(cat)
  if printf '%s' "$body" | grep -qiE '^closes #[0-9]+$'; then
    return 0
  fi
  echo "::error title=Missing Closes clause::" >&2
  return 1
}
"""
FAKE_SELFTEST = "#!/usr/bin/env bash\necho 'PASS: 1/1'\nexit 0\n"


@pytest.fixture(name="tree")
def _tree(tmp_path: Path) -> Path:
    scripts = tmp_path / "tree" / ".github" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "closes-syntax-check.sh").write_bytes(FAKE_CHECK.encode())
    (scripts / "test-closes-syntax.sh").write_bytes(FAKE_SELFTEST.encode())
    return tmp_path / "tree"


def test_closes_syntax_valid_body_passes(tree: Path) -> None:
    """A well-formed body on an in-scope branch passes."""
    result = local_ci.run_closes_syntax(tree, "feat/pi-x-gh-1", "Closes #12\n")
    assert result.status == local_ci.PASS, result.detail


def test_closes_syntax_bad_body_fails(tree: Path) -> None:
    """A body without a Closes clause fails with the script's error."""
    result = local_ci.run_closes_syntax(tree, "feat/pi-x-gh-1", "no clause here")
    assert result.status == local_ci.FAIL
    assert "Missing Closes clause" in result.detail


def test_closes_syntax_out_of_scope_branch_passes_without_check(tree: Path) -> None:
    """Non portfolio-intel heads skip the check, as the workflow does."""
    result = local_ci.run_closes_syntax(tree, "fix/other", "no clause")
    assert result.status == local_ci.PASS
    assert "out of scope" in result.detail


def test_closes_syntax_scope_is_case_insensitive(tree: Path) -> None:
    """``shopt -s nocasematch``: FEAT/PI-* is in scope."""
    result = local_ci.run_closes_syntax(tree, "FEAT/PI-X", "no clause")
    assert result.status == local_ci.FAIL


def test_closes_syntax_without_body_is_not_reproducible(tree: Path) -> None:
    """No ``--pr-body-file`` means the job cannot be replayed."""
    result = local_ci.run_closes_syntax(tree, "feat/pi-x", None)
    assert result.status == local_ci.NOT_REPRODUCIBLE
    assert "--pr-body-file" in result.detail


def test_closes_syntax_body_is_data_not_shell(tree: Path) -> None:
    """Backticks and ``$(...)`` in the body are never executed."""
    marker = tree / "pwned"
    body = f"Closes #1\n$(touch '{marker.as_posix()}')\n`touch '{marker.as_posix()}'`\n"
    local_ci.run_closes_syntax(tree, "feat/pi-x", body)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("body", "status"),
    [("Summary\n", "PASS"), (" \n\t\n", "FAIL"), (None, "NOT-REPRODUCIBLE")],
)
def test_pr_description(body: str | None, status: str) -> None:
    """Whitespace-only bodies fail; a missing body cannot be checked."""
    assert local_ci.run_pr_description(body).status == status


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_exit_code_fails_only_on_reproducible_failures() -> None:
    """NOT-REPRODUCIBLE and SKIPPED never fail the gate; FAIL does."""
    ok = [
        local_ci.Result("a", local_ci.PASS),
        local_ci.Result("b", local_ci.SKIPPED),
        local_ci.Result("c", local_ci.NOT_REPRODUCIBLE, "docker"),
    ]
    assert local_ci.exit_code(ok) == 0
    assert local_ci.exit_code([*ok, local_ci.Result("d", local_ci.FAIL)]) == 1


def test_redact_hides_secret_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Output never echoes the value of a credential-like environment variable."""
    monkeypatch.setenv("FMP_API_KEY", "sekrit-value-123")
    text = local_ci.redact("token sekrit-value-123 leaked")
    assert "sekrit-value-123" not in text


def test_hermetic_env_scrubs_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Jobs never inherit provider, database or proxy credentials."""
    for name in ("FMP_API_KEY", "DB_PASSWORD", "HTTPS_PROXY", "OPENBB_TOKEN"):
        monkeypatch.setenv(name, "x")
    env = local_ci.hermetic_env(tmp_path)
    assert not {"FMP_API_KEY", "DB_PASSWORD", "HTTPS_PROXY", "OPENBB_TOKEN"} & set(env)
    assert env["HOME"] == str(tmp_path)
    assert env["USERPROFILE"] == str(tmp_path)


# ---------------------------------------------------------------------------
# Fidelity: Linux container jobs, inventory install order, submodule
# ---------------------------------------------------------------------------

HARNESS_JOB = """
on:
  pull_request:
    branches: [portfolio]
env:
  TOP: "1"
jobs:
  standalone:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        story: [portfolio, techtrade]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install widget_backend dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e openbb_platform/core
      - name: Run unit tests
        working-directory: openbb_platform/tools/browser_test_harness
        env:
          PI_PAPER_DB: "${{ runner.temp }}/pi-paper-unit.db"
        run: pytest tests/ -v --tb=short
      - name: Run ${{ matrix.story }} story (standalone mode)
        env:
          PI_WIDGET_BACKEND_TOKEN: ""
        run: python -m harness.run --story ${{ matrix.story }}
      - name: Upload report artifact
        if: always()
        uses: actions/upload-artifact@v4
"""


def _harness_selected(tmp_path: Path) -> list:
    (tmp_path / "harness.yml").write_text(
        textwrap.dedent(HARNESS_JOB), encoding="utf-8"
    )
    return local_ci.select_jobs(
        local_ci.load_workflows(tmp_path), base_branch="portfolio", changed=["x"]
    )


def test_container_plan_mirrors_workflow_steps(tmp_path: Path) -> None:
    """Image from setup-python; run steps verbatim; network only while installing."""
    sel = _harness_selected(tmp_path)[1]
    image, steps = local_ci.container_plan(sel)
    assert image == "python:3.12"
    assert [s.name for s in steps] == [
        "Install widget_backend dependencies",
        "Run unit tests",
        "Run techtrade story (standalone mode)",
    ]
    assert [s.network for s in steps] == [True, False, False]
    assert "pip install -e openbb_platform/core" in steps[0].script
    assert steps[1].workdir == "openbb_platform/tools/browser_test_harness"
    assert steps[1].env["PI_PAPER_DB"] == "/tmp/pi-paper-unit.db"  # noqa: S108
    assert steps[1].env["TOP"] == "1"
    assert steps[2].script.strip().endswith("--story techtrade")
    assert steps[2].env["PI_WIDGET_BACKEND_TOKEN"] == ""


def test_container_plan_rejects_unknown_expressions(tmp_path: Path) -> None:
    """A ``${{ secrets.X }}`` the container cannot reproduce is refused."""
    text = HARNESS_JOB.replace("pytest tests/", "pytest ${{ secrets.TOKEN }}")
    (tmp_path / "harness.yml").write_text(textwrap.dedent(text), encoding="utf-8")
    sel = local_ci.select_jobs(
        local_ci.load_workflows(tmp_path), base_branch="portfolio", changed=["x"]
    )[0]
    with pytest.raises(local_ci.LocalCiError, match="secrets"):
        local_ci.container_plan(sel)


def test_docker_run_args_are_read_only_and_networkless_by_default() -> None:
    """The tree is mounted read-only; memory is capped; nothing else is mounted rw."""
    args = local_ci.docker_run_args("c1", "python:3.12", Path("T"), Path("P"))
    joined = " ".join(args)
    assert f"{Path('T')}:/src:ro" in joined
    assert "--memory" in args
    assert args[args.index("--network") + 1] == "none"
    assert args[-3:] == ["python:3.12", "sleep", "infinity"]


def test_host_readiness_timeout_is_not_reproducible() -> None:
    """On the Windows host a readiness-only failure is NOT-REPRODUCIBLE."""
    ready = local_ci.Result(
        "k", local_ci.FAIL, "Backend did not become ready in 10.0s (last error: x)"
    )
    assert local_ci.host_harness_verdict(ready).status == local_ci.NOT_REPRODUCIBLE
    other = local_ci.Result("k", local_ci.FAIL, "AssertionError: shape")
    assert local_ci.host_harness_verdict(other).status == local_ci.FAIL


METADATA_STEP = """\
set -euo pipefail
for source in base head; do
  environment="$RUNNER_TEMP/$source-venv"
  python -m venv "$environment"
  "$environment/bin/python" -m pip install --upgrade pip
  "$environment/bin/python" -m pip install \
    -e "$GITHUB_WORKSPACE/$source/openbb_platform/core" \
    -e "$GITHUB_WORKSPACE/$source/openbb_platform/extensions/agents"
  "$environment/bin/python" \
    "$GITHUB_WORKSPACE/$source/scripts/pi_install.py"
  "$environment/bin/python" -m pip install \
    -e "$GITHUB_WORKSPACE/$source/openbb_platform/extensions/fmp_trading[agent]"
  "$environment/bin/python" -c \
    "import openbb; openbb.build()"
done
"""


def test_metadata_env_commands_keep_workflow_order() -> None:
    """fmp_trading[agent] installs only after pi_install, exactly as scripted."""
    tree, venv = Path("TREE"), Path("VENV")
    py = local_ci.venv_tool(venv, "python")
    cmds = local_ci.metadata_env_commands(METADATA_STEP, tree, venv, "HOSTPY")
    assert cmds == [
        ["HOSTPY", "-m", "venv", str(venv)],
        [py, "-m", "pip", "install", "--upgrade", "pip"],
        [
            py,
            "-m",
            "pip",
            "install",
            "-e",
            str(tree / "openbb_platform/core"),
            "-e",
            str(tree / "openbb_platform/extensions/agents"),
        ],
        [py, str(tree / "scripts/pi_install.py")],
        [
            py,
            "-m",
            "pip",
            "install",
            "-e",
            str(tree / "openbb_platform/extensions/fmp_trading") + "[agent]",
        ],
        [py, "-c", "import openbb; openbb.build()"],
    ]


def test_populate_submodule_from_local_objects(tmp_path: Path) -> None:
    """The pinned submodule commit is checked out from local objects only."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _git(sub, "init", "-q", "-b", "main")
    _write(sub, "pinned.txt", "v1\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "v1")
    pinned = _git(sub, "rev-parse", "HEAD")
    _write(sub, "pinned.txt", "v2\n")
    _git(sub, "commit", "-q", "-am", "v2")
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(
        main,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(sub),
        "third_party/ws",
    )
    _git(main, "-C", "third_party/ws", "checkout", "-q", pinned)
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "pin")
    commit = _git(main, "rev-parse", "HEAD")
    modules = main / ".git" / "modules" / "third_party" / "ws"
    before = _git(main, "--git-dir", str(modules), "worktree", "list")
    tree = tmp_path / "tree"
    (tree / "third_party" / "ws").mkdir(parents=True)
    local_ci.populate_submodule(main, commit, "third_party/ws", tree)
    assert (tree / "third_party/ws/pinned.txt").read_text(encoding="utf-8") == "v1\n"
    assert _git(main, "--git-dir", str(modules), "worktree", "list") == before
