"""An engine-backed workflow runs with notebooks and kernels absent (#1340-T03).

The audit hook cannot be removed once installed, so every guard-on case runs in
a subprocess; this pytest process never installs it. Data is synthetic only.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from openbb_agents.hermes_integration.workflow import workflow_manifest_sha256
from openbb_agents.hermes_integration.workflow_runner import (
    SYNTHETIC_WEIGHTS,
    run_workflow,
)
from openbb_mcp_server.utils.schema_digest import tool_input_schema_sha256
from openbb_portfolio_intel.analytics.basket_lookthrough import (
    concentration,
    construction_targets,
)

from .conftest import SHIPPED, load_fixture

AGENTS = Path(__file__).resolve().parents[3]
MCP_SERVER = AGENTS.parent / "mcp_server"
WORKFLOW = "synthetic.concentration_review"
DOCUMENT = SHIPPED / f"{WORKFLOW}.workflow.json"

# Runs the runner CLI with non-loopback sockets denied and reports which
# notebook-related modules ended up loaded.
LAUNCHER = textwrap.dedent("""
    import json, socket, sys
    LOOP = {"127.0.0.1", "::1", "localhost"}
    def _check(address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOP:
            raise AssertionError("network denied")
    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect = lambda s, a: (_check(a), _connect(s, a))[1]
    socket.socket.connect_ex = lambda s, a: (_check(a), _connect_ex(s, a))[1]
    from openbb_agents.hermes_integration.workflow_runner import main
    code = main(sys.argv[1:])
    bad = ("nbformat", "nbclient", "nbconvert", "jupyter_client", "jupyter_core",
           "ipykernel", "IPython", "papermill")
    loaded = sorted(
        name for name in sys.modules
        if name.split(".")[0] in bad or name.startswith("openbb_agents.notebook_guide")
    )
    sys.stderr.write("MODULES:" + json.dumps(loaded) + "\\n")
    sys.exit(code)
    """)

CLI_TAIL = (
    "--inputs",
    "synthetic",
    "--server",
    "portfolio-ops",
    "--forbid-notebooks",
    "--format",
    "json",
)


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONSTARTUP"}
    }
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        OPENBB_STORY_RUN_STORE=str(tmp_path / "runs.sqlite"),
        PYTHONPATH=os.pathsep.join([str(AGENTS), str(MCP_SERVER)]),
    )
    return env


def _run_cli(tmp_path: Path, *args: str):
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-c", LAUNCHER, *args],
        cwd=cwd,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _loaded_modules(process) -> list[str]:
    line = next(
        row for row in process.stderr.splitlines() if row.startswith("MODULES:")
    )
    return json.loads(line[len("MODULES:") :])


@pytest.fixture(scope="module")
def guarded_run(tmp_path_factory):
    """One guard-on CLI run shared by the assertions below."""
    tmp_path = tmp_path_factory.mktemp("guarded")
    return _run_cli(tmp_path, "--workflow", WORKFLOW, *CLI_TAIL)


def test_guard_blocks_ipynb_open_and_jupyter_import(tmp_path):
    """The guard refuses real notebook access and counts every refusal."""
    (tmp_path / "x.ipynb").write_text("{}", "utf-8")
    (tmp_path / "ok.txt").write_text("fine", "utf-8")
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "docs" / "examples").mkdir(parents=True)
    (tmp_path / "nbformat.py").write_text("VALUE = 1\n", "utf-8")
    script = textwrap.dedent(f"""
        import json, os, sys
        from pathlib import Path
        from openbb_agents.hermes_integration import notebook_guard
        notebook_guard.install()
        root = Path({str(tmp_path)!r})
        sys.path.insert(0, str(root))
        seen = {{}}
        def attempt(name, call):
            try:
                call()
                seen[name] = "allowed"
            except Exception as error:
                seen[name] = type(error).__name__
        attempt("ipynb", lambda: open(root / "x.ipynb", encoding="utf-8").read())
        attempt("plain", lambda: open(root / "ok.txt", encoding="utf-8").read())
        attempt("listdir", lambda: os.listdir(root / "notebooks"))
        attempt("scandir", lambda: list(os.scandir(root / "docs" / "examples")))
        attempt("jupyter", lambda: __import__("nbformat"))
        print(json.dumps({{"seen": seen, "stats": notebook_guard.stats()}}))
        """)
    process = subprocess.run(
        [sys.executable, "-c", script],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout.splitlines()[-1])
    assert report["seen"]["plain"] == "allowed"
    for blocked in ("ipynb", "listdir", "scandir"):
        assert report["seen"][blocked] == "NotebookAccessBlocked", report
    assert report["seen"]["jupyter"] == "NotebookImportBlocked", report
    assert report["stats"] == {"blocked_opens": 3, "blocked_imports": 1}


def test_synthetic_workflow_runs_with_notebook_guard(guarded_run):
    """Guard on, cwd elsewhere: the shared engine produces the notebook's numbers."""
    process = guarded_run
    assert process.returncode == 0, process.stderr[-2000:]
    report = json.loads(process.stdout)
    assert report["admitted"] is True
    assert {s["stage_id"]: s["status"] for s in report["stages"]} == {
        "concentration": "succeeded",
        "construction": "succeeded",
        "checkpoint": "succeeded",
    }
    digest = report["workflow_manifest_sha256"]
    assert report["manifest_version"] == f"workflow:{WORKFLOW}@{digest[:12]}"

    direct = concentration(dict(SYNTHETIC_WEIGHTS), kill_shot_drop=0.20)
    got = report["outputs"]["concentration"]
    assert got["hhi"] == pytest.approx(direct.hhi)
    assert got["top5"] == pytest.approx(direct.top5)
    assert got["largest"] == direct.largest
    built = construction_targets(dict(SYNTHETIC_WEIGHTS))
    out = report["outputs"]["construction"]
    assert out["refused"] is built.refused
    assert out["residual"] == pytest.approx(built.residual)
    assert {t["name"]: t["target"] for t in out["targets"]} == pytest.approx(
        {k: v["target"] for k, v in built.targets.items()}
    )
    for stage in report["stages"][:2]:
        oracle = hashlib.sha256(
            json.dumps(
                report["outputs"][stage["stage_id"]],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert stage["output_sha256"] == oracle
        assert stage["evidence_ids"]


def test_runner_reports_zero_blocked_notebook_accesses(guarded_run):
    """The guard was active, and the run never touched a notebook."""
    report = json.loads(guarded_run.stdout)
    assert report["notebook_guard"] == {"blocked_opens": 0, "blocked_imports": 0}


def test_no_notebook_modules_in_sys_modules_after_run(guarded_run):
    """No notebook or Jupyter module is even loaded by a workflow run."""
    assert _loaded_modules(guarded_run) == []


def test_drifted_workflow_cli_exits_2_and_runs_nothing(tmp_path):
    """A drifted pin is rejected before a run exists or any tool is called."""
    drifted = tmp_path / "drifted.workflow.json"
    document = json.loads(DOCUMENT.read_text("utf-8"))
    document["capabilities"]["platform:story_concentration"]["schema_sha256"] = "0" * 64
    drifted.write_text(json.dumps(document), "utf-8")
    process = _run_cli(tmp_path, "--workflow-file", str(drifted), *CLI_TAIL)
    assert process.returncode == 2, process.stderr[-2000:]
    report = json.loads(process.stdout)
    assert report["admitted"] is False
    assert {r["code"] for r in report["rejections"]} == {"schema_drift"}
    assert {s["status"] for s in report["stages"]} <= {"not_run"}
    assert report["run_id"] is None
    assert not (tmp_path / "runs.sqlite").exists()


class _Sentinel:
    """An invoker that records calls; ``fail_on`` makes one tool raise."""

    def __init__(self, digest: str | None = None, fail_on: str | None = None):
        self.calls: list[str] = []
        self.digest = digest
        self.fail_on = fail_on

    async def call(self, server: str, tool: str, arguments: dict) -> dict:
        self.calls.append(tool)
        if tool == self.fail_on:
            raise RuntimeError("tool failed")
        if tool == "story_run_create":
            return {
                "run_id": "r1",
                "state_version": 0,
                "manifest_version": "v",
                "workflow_manifest_sha256": self.digest,
            }
        if tool == "story_run_checkpoint":
            return {"state_version": arguments["expected_version"] + 1}
        return {"echo": tool}


def _live(document: dict) -> dict[str, str]:
    return {
        f"{p['server']}:{p['tool']}": p["schema_sha256"]
        for p in document["capabilities"].values()
    }


def test_drifted_workflow_runs_no_stage():
    """Rejected workflows never reach the invoker."""
    sentinel = _Sentinel()
    result = asyncio.run(
        run_workflow(
            load_fixture("drifted"),
            {"weights": dict(SYNTHETIC_WEIGHTS)},
            sentinel,
            live_tools=_live(json.loads(DOCUMENT.read_text("utf-8"))),
        )
    )
    assert result.admitted is False
    assert sentinel.calls == []
    assert result.run_id is None
    assert all(s.status == "not_run" for s in result.stages)


def test_stages_run_in_order_and_a_failure_stops_the_rest_without_retry():
    """No retry, no fallback: a failing stage ends the run; later stages not_run."""
    document = json.loads(DOCUMENT.read_text("utf-8"))
    live = _live(document)
    inputs = {"weights": dict(SYNTHETIC_WEIGHTS)}
    digest = workflow_manifest_sha256(document)
    ok = _Sentinel(digest)
    done = asyncio.run(run_workflow(document, inputs, ok, live_tools=live))
    assert ok.calls[0] == "story_run_create"
    assert [c for c in ok.calls if c != "story_run_checkpoint"][1:] == [
        "story_concentration",
        "story_construction_targets",
    ]
    assert [s.status for s in done.stages] == ["succeeded"] * 3

    broken = _Sentinel(digest, fail_on="story_construction_targets")
    failed = asyncio.run(run_workflow(document, inputs, broken, live_tools=live))
    assert [s.status for s in failed.stages] == ["succeeded", "failed", "not_run"]
    assert broken.calls.count("story_construction_targets") == 1  # no retry
    assert failed.admitted is True


def test_run_bound_to_a_different_digest_executes_no_stage():
    """If the registry's workflow is not the admitted one, nothing runs."""
    document = json.loads(DOCUMENT.read_text("utf-8"))
    sentinel = _Sentinel("f" * 64)
    result = asyncio.run(
        run_workflow(
            document,
            {"weights": dict(SYNTHETIC_WEIGHTS)},
            sentinel,
            live_tools=_live(document),
        )
    )
    assert result.error and result.error.startswith("run_create_failed")
    assert sentinel.calls == ["story_run_create"]
    assert all(s.status == "not_run" for s in result.stages)


def test_in_process_portfolio_ops_run_records_workflow_digest_in_registry():
    """Real in-process server (no guard, no mocks): same engine, digest-bound run."""
    # pylint: disable=import-outside-toplevel
    from fastmcp import Client
    from openbb_agents.hermes_integration.workflow_admit import build_server
    from openbb_agents.hermes_integration.workflow_runner import FastMcpInvoker

    document = json.loads(DOCUMENT.read_text("utf-8"))

    async def scenario():
        server = build_server("portfolio-ops")
        hashes = {
            f"platform:{t.name}": tool_input_schema_sha256(t.parameters)
            for t in await server.list_tools()
        }
        async with Client(server) as client:
            invoker = FastMcpInvoker(client)
            result = await run_workflow(
                document,
                {"weights": dict(SYNTHETIC_WEIGHTS)},
                invoker,
                live_tools=hashes,
            )
            record = await invoker.call(
                "platform", "story_run_get", {"run_id": result.run_id}
            )
        return result, record

    result, record = asyncio.run(scenario())
    assert result.admitted
    assert record["workflow_manifest_sha256"] == result.workflow_manifest_sha256
    assert record["stage_status"] == {
        "concentration": "succeeded",
        "construction": "succeeded",
        "checkpoint": "succeeded",
    }
    assert record["state_version"] == 3
    assert record["manifest_version"] == result.manifest_version


def test_unpinned_run_create_is_rejected_before_any_call():
    """Review finding 3: run bookkeeping tools are pinned, so drift is detected."""
    document = json.loads(DOCUMENT.read_text("utf-8"))
    assert "platform:story_run_create" in document["capabilities"]
    live = _live(document)
    del document["capabilities"]["platform:story_run_create"]
    sentinel = _Sentinel(workflow_manifest_sha256(document))
    result = asyncio.run(
        run_workflow(
            document, {"weights": dict(SYNTHETIC_WEIGHTS)}, sentinel, live_tools=live
        )
    )
    assert result.admitted is False
    assert {r.code for r in result.rejections} == {"capability_unresolved"}
    assert sentinel.calls == []


def test_drifted_run_create_schema_is_rejected():
    document = json.loads(DOCUMENT.read_text("utf-8"))
    live = _live(document)
    live["platform:story_run_create"] = "0" * 64
    sentinel = _Sentinel(workflow_manifest_sha256(document))
    result = asyncio.run(
        run_workflow(
            document, {"weights": dict(SYNTHETIC_WEIGHTS)}, sentinel, live_tools=live
        )
    )
    assert {r.code for r in result.rejections} == {"schema_drift"}
    assert sentinel.calls == []


def test_guard_normalises_windows_paths_and_blocks_chdir_and_launchers(tmp_path):
    """Review finding 7: trailing dots/spaces, NTFS streams, chdir, launchers."""
    (tmp_path / "x.ipynb").write_text("{}", "utf-8")
    (tmp_path / "notebooks").mkdir()
    script = textwrap.dedent(f"""
        import json, os, subprocess, sys
        from pathlib import Path
        from openbb_agents.hermes_integration import notebook_guard
        notebook_guard.install()
        root = Path({str(tmp_path)!r})
        seen = {{}}
        def attempt(name, call):
            try:
                call()
                seen[name] = "allowed"
            except Exception as error:
                seen[name] = type(error).__name__
        attempt("dot", lambda: open(str(root / "x.ipynb") + ".", "rb").close())
        attempt("space", lambda: open(str(root / "x.ipynb") + " ", "rb").close())
        attempt("stream", lambda: open(str(root / "x.ipynb") + "::$DATA", "rb").close())
        attempt("dirdot", lambda: os.listdir(str(root / "notebooks") + "."))
        attempt("chdir", lambda: os.chdir(root / "notebooks"))
        attempt("popen", lambda: subprocess.run(["jupyter-nosuch-1340", "--version"]))
        attempt("nb", lambda: subprocess.run("nbnosuch1340 --version", shell=True))
        attempt("system", lambda: os.system("jupyter-nosuch-1340 --version"))
        attempt("python", lambda: subprocess.run([sys.executable, "-c", "pass"]))
        print(json.dumps({{"seen": seen}}))
        """)
    process = subprocess.run(
        [sys.executable, "-c", script],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    seen = json.loads(process.stdout.splitlines()[-1])["seen"]
    assert seen.pop("python") == "allowed"
    assert seen == dict.fromkeys(seen, "NotebookAccessBlocked"), seen
    assert len(seen) == 8
