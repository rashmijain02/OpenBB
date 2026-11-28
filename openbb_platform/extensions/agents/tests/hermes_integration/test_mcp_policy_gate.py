"""The hermes-finance policy gate at the MCP call_tool seam (#1339 T01).

The gate is opt-in (``--policy-profile hermes-finance``). Without the flag the
server is unchanged. With it, a denied call fails before the tool body runs,
over a real stdio round trip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openbb_agents import mcp_server
from openbb_agents.hermes_integration.policy_probe import child_pythonpath

from .conftest import SENTINELS

# Snapshot of the default (ungated) tool list, taken on portfolio @ 75f442402.
_DEFAULT_TOOLS = [
    {
        "name": "get_positions",
        "description": (
            "Return all current positions from the sanitized portfolio basket."
        ),
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_sector_exposure",
        "description": "Aggregate portfolio market value by GICS sector.",
        "schema": {"type": "object", "properties": {}},
    },
]

_CLAIMS = {
    "approved": True,
    "principal": "operator",
    "capabilities": ["private_portfolio_read"],
}


def test_default_profile_tool_list_unchanged():
    """collect_tools() descriptors match the pre-gate snapshot exactly."""
    descriptors = [
        {key: value for key, value in tool.items() if key != "fn"}
        for tool in mcp_server.collect_tools()
    ]
    assert descriptors == _DEFAULT_TOOLS


def test_main_without_flags_serves_ungated(monkeypatch):
    """No flags means no gate: _serve gets no policy profile."""
    seen = {}

    async def fake_serve(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    mcp_server.main([])
    assert seen.get("policy_profile") is None


def test_main_passes_profile_and_principal(monkeypatch):
    """The flags reach _serve unchanged."""
    seen = {}

    async def fake_serve(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    mcp_server.main(
        ["--policy-profile", "hermes-finance", "--principal", "hermes_runtime"]
    )
    assert seen == {"policy_profile": "hermes-finance", "principal": "hermes_runtime"}


@pytest.mark.parametrize(
    "argv",
    [["--policy-profile", "hermes-financ"], ["--policy-profle", "hermes-finance"]],
)
def test_main_rejects_misspelled_policy_flags(monkeypatch, argv):
    """A typo must stop the server, never start it ungated."""

    async def fake_serve(**_kwargs):
        raise AssertionError("server must not start")

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    with pytest.raises(SystemExit) as excinfo:
        mcp_server.main(argv)
    assert excinfo.value.code == 2


def test_main_rejects_principal_without_policy_profile(monkeypatch, capsys):
    """--principal alone would serve ungated; it must be a usage error."""

    async def fake_serve(**_kwargs):
        raise AssertionError("server must not start")

    monkeypatch.setattr(mcp_server, "_serve", fake_serve)
    with pytest.raises(SystemExit) as excinfo:
        mcp_server.main(["--principal", "hermes_runtime"])
    assert excinfo.value.code == 2
    assert "--principal requires --policy-profile" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_stdio_default_server_child_never_loads_hermes_integration(tmp_path):
    """The real default stdio child has no hermes_integration module loaded."""
    marker = tmp_path / "modules.txt"
    script = f"""
import sys
from pathlib import Path
from openbb_agents.tools import portfolio_tools

def _record(*_args, **_kwargs):
    loaded = sorted(m for m in sys.modules if m.startswith("openbb_agents.hermes_integration"))
    Path({str(marker)!r}).write_text(repr(loaded), encoding="utf-8")
    raise RuntimeError("probe")

portfolio_tools._default_fetch = _record
portfolio_tools._default_profile = _record
from openbb_agents.mcp_server import main
main(sys.argv[1:])
"""
    await _call_all(script, [], tmp_path / "server.err", arguments={})
    assert marker.read_text(encoding="utf-8") == "[]"


def test_default_mode_does_not_import_policy_module():
    """The default server path never loads the hermes policy code."""
    code = (
        "import sys, openbb_agents.mcp_server; "
        "print(any(m.startswith('openbb_agents.hermes_integration') "
        "for m in sys.modules))"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv, current interpreter
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": child_pythonpath(os.getenv("PYTHONPATH"))},
        timeout=60,
    )
    assert out.stdout.strip() == "False"


def _probe_script(marker: Path) -> str:
    """Server whose tool bodies record that they ran, then raise."""
    return f"""
import sys
from pathlib import Path
from openbb_agents.tools import portfolio_tools

def _ran(*_args, **_kwargs):
    Path({str(marker)!r}).write_text("tool body ran", encoding="utf-8")
    raise RuntimeError({SENTINELS["account"]!r})

portfolio_tools._default_fetch = _ran
portfolio_tools._default_profile = _ran
from openbb_agents.mcp_server import main
main(sys.argv[1:])
"""


async def _call_all(
    script: str, flags: list[str], errlog: Path, arguments: dict | None = None
) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = child_pythonpath(env.get("PYTHONPATH"))
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", script, *flags],
        env=env,
    )
    results = {}
    with errlog.open("w", encoding="utf-8") as err, anyio.fail_after(60):
        async with (
            stdio_client(parameters, errlog=err) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            assert {t.name for t in listed.tools} == {
                "get_positions",
                "get_sector_exposure",
            }
            for tool in ("get_positions", "get_sector_exposure"):
                results[tool] = await session.call_tool(
                    tool, dict(_CLAIMS if arguments is None else arguments)
                )
    return results


@pytest.mark.asyncio
async def test_stdio_gate_denies_get_positions_before_tool_body(tmp_path):
    """Gated server refuses both private tools; the tool body never runs."""
    marker = tmp_path / "ran.txt"
    errlog = tmp_path / "server.err"
    results = await _call_all(
        _probe_script(marker),
        ["--policy-profile", "hermes-finance", "--principal", "hermes_runtime"],
        errlog,
    )
    for tool, result in results.items():
        assert result.isError is True
        payload = json.loads(result.content[0].text)
        assert payload == {
            "error": "capability_denied",
            "tool": tool,
            "reason": "no_grant",
        }
    assert not marker.exists(), "tool body ran behind the gate"
    audit = [
        line
        for line in errlog.read_text(encoding="utf-8").splitlines()
        if "policy_decision" in line
    ]
    assert len(audit) == 2
    assert all("allowed=false reason=no_grant" in line for line in audit)
    text = errlog.read_text(encoding="utf-8")
    assert not any(value in text for value in SENTINELS.values())
    assert "approved" not in text


@pytest.mark.asyncio
async def test_stdio_gate_without_principal_denies(tmp_path):
    """A gated server launched without --principal refuses every tool."""
    marker = tmp_path / "ran.txt"
    results = await _call_all(
        _probe_script(marker),
        ["--policy-profile", "hermes-finance"],
        tmp_path / "server.err",
    )
    for result in results.values():
        assert result.isError is True
        assert json.loads(result.content[0].text)["reason"] == "unknown_principal"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_stdio_default_profile_still_runs_tool_body(tmp_path):
    """Control: without the gate the same probe body runs (marker written)."""
    marker = tmp_path / "ran.txt"
    results = await _call_all(
        _probe_script(marker), [], tmp_path / "server.err", arguments={}
    )
    assert marker.exists(), "probe did not detect tool execution"
    for tool, result in results.items():
        assert result.isError is True
        assert json.loads(result.content[0].text) == {
            "error": "tool_failed",
            "tool": tool,
        }


def test_policy_probe_synthetic_denies_both_tools(capsys):
    """Real-path probe: both private tools refused, nothing leaked."""
    from openbb_agents.hermes_integration import policy_probe

    assert policy_probe.main(["--synthetic"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["result"] == "denied"
    assert {c["error"] for c in summary["calls"].values()} == {"capability_denied"}


def test_policy_probe_requires_synthetic_flag():
    """The probe only runs in the synthetic environment."""
    from openbb_agents.hermes_integration import policy_probe

    assert policy_probe.main([]) == 3


def test_policy_probe_flags_an_allowed_call():
    """The probe's verdict fails when a call succeeds or a claim leaks."""
    from openbb_agents.hermes_integration import policy_probe

    denied = json.dumps({"error": "capability_denied", "reason": "no_grant"})
    audit = "policy_decision a\npolicy_decision b\n"
    allowed = {
        "get_positions": {"isError": False, "text": "[]"},
        "get_sector_exposure": {"isError": True, "text": denied},
    }
    assert policy_probe._evaluate(allowed, audit)[0] is False
    both = {tool: {"isError": True, "text": denied} for tool in allowed}
    assert policy_probe._evaluate(both, audit)[0] is True
    assert policy_probe._evaluate(both, audit + "approved")[0] is False


def test_policy_probe_child_pythonpath_is_absolute_package_root(tmp_path, monkeypatch):
    """The child server imports this checkout's package, not a relative one."""
    import openbb_agents
    from openbb_agents.hermes_integration import policy_probe

    root = Path(openbb_agents.__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", "relative-entry")
    env = policy_probe._synthetic_env(tmp_path)
    first = env["PYTHONPATH"].split(os.pathsep)[0]
    assert Path(first).is_absolute()
    assert Path(first) == root
    assert env["PYTHONPATH"].split(os.pathsep)[1:] == ["relative-entry"]


def test_policy_probe_passes_with_relative_pythonpath(monkeypatch, capsys):
    """Regression: a relative PYTHONPATH must not break the child (cwd=temp)."""
    import openbb_agents
    from openbb_agents.hermes_integration import policy_probe

    root = Path(openbb_agents.__file__).resolve().parents[1]
    monkeypatch.chdir(root)
    monkeypatch.setenv("PYTHONPATH", ".")
    assert policy_probe.main(["--synthetic"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "denied"
