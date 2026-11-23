"""Workspace agent capabilities agree with the native widget inventory (#1272).

Plan Step 8 / review checkpoint C: the widget, app and agent capability
inventories agree, and no model-driven mutation path is exposed.

- The agent inventory registered on the widget backend is exactly the
  widgets in ``fixtures/native_workspace_matrix.json`` (same ids, types and
  endpoints), so nothing is advertised that does not exist.
- Every chart widget is read with ``raw=true``.
- The agent denies exactly the widgets the MCP exposure policy denies
  (paper order ticket, one-click backtest), and nothing else.
- ``/agents.json`` on the real backend advertises widget access and only
  implemented features; ``/query`` turns a selection into one read-only
  ``get_widget_data`` call and refuses action widgets.
- Real endpoints (hermetic subprocess, network refused, sentinel
  credentials in the environment): every readable widget answers 200 with
  agent-readable data whose provenance the agent can state, and no
  credential reaches the agent's model context.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio import copilot  # noqa: E402
from openbb_portfolio_intel.widget_backend.agent_policy import (  # noqa: E402
    AGENT_DENIED_WIDGETS,
    build_agent_capabilities,
)
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

UNIT = Path(__file__).resolve().parent
MATRIX = json.loads(
    (UNIT / "fixtures" / "native_workspace_matrix.json").read_text(encoding="utf-8")
)
MATRIX_WIDGETS: dict[str, dict[str, Any]] = {w["id"]: w for w in MATRIX["widgets"]}
PROBE = UNIT / "_workspace_endpoint_probe.py"
SENTINEL = "SENTINEL-CREDENTIAL-1272"


def test_agent_inventory_matches_native_workspace_matrix():
    caps = build_agent_capabilities()
    assert set(caps) == set(MATRIX_WIDGETS)
    for widget_id, cap in caps.items():
        row = MATRIX_WIDGETS[widget_id]
        assert cap.kind == row["type"], widget_id
        assert cap.endpoint == row["endpoint"], widget_id
        assert row["endpointRegistered"] is True, widget_id


def test_backend_registers_the_inventory_for_the_agent():
    caps = getattr(app.state, copilot.CAPABILITIES_STATE)
    assert caps == build_agent_capabilities()


def test_every_chart_widget_is_read_with_raw_true():
    caps = build_agent_capabilities()
    charts = [k for k, w in MATRIX_WIDGETS.items() if w["type"] == "chart"]
    assert len(charts) == MATRIX["summary"]["types"]["chart"]
    for widget_id in charts:
        defaults = {p["name"]: p["default"] for p in MATRIX_WIDGETS[widget_id]["parameters"]}
        assert caps[widget_id].input_args(defaults)["raw"] is True, widget_id
    for widget_id, row in MATRIX_WIDGETS.items():
        if row["type"] != "chart":
            assert "raw" not in caps[widget_id].input_args({}), widget_id


def test_agent_denials_are_the_paper_and_job_action_widgets():
    caps = build_agent_capabilities()
    denied = {k for k, c in caps.items() if not c.readable}
    assert denied == {"pi_paper_ticket", "pi_backtest_button"}
    assert denied == set(AGENT_DENIED_WIDGETS)


def test_agent_denials_match_the_mcp_exposure_policy():
    """Widgets MCP refuses to expose are exactly the ones the agent refuses."""
    exposure = pytest.importorskip("openbb_mcp_server.service.exposure_policy")
    policy = exposure.ExposurePolicy.load()
    mcp_denied = {
        widget_id
        for widget_id, row in MATRIX_WIDGETS.items()
        if policy.classify_path("GET", "/" + row["endpoint"]).disposition
        == "restricted"
    }
    caps = build_agent_capabilities()
    assert {k for k, c in caps.items() if not c.readable} == mcp_denied


def test_agents_json_on_backend_advertises_only_implemented_features():
    body = TestClient(app).get("/agents.json").json()
    features = body[copilot.COPILOT_ID]["features"]
    assert features["widget-dashboard-select"] is True
    enabled = {name for name, value in features.items() if value}
    assert enabled == set(copilot.IMPLEMENTED_FEATURES)


def _sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", ""
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            events.append((name, json.loads(data)))
    return events


def _selected(widget_id: str, **params: Any) -> dict[str, Any]:
    return {
        "uuid": str(uuid4()),
        "origin": "portfolio-intel",
        "widget_id": widget_id,
        "name": widget_id,
        "description": "selected",
        "params": [
            {"name": k, "type": "text", "description": k, "current_value": v}
            for k, v in params.items()
        ],
    }


def test_query_turns_a_selection_into_one_read_only_widget_call(monkeypatch):
    async def no_model(_messages):  # noqa: ANN001
        raise AssertionError("no model call before widget data arrives")
        yield  # pragma: no cover

    monkeypatch.setattr(copilot, "_proxy_deltas", no_model)
    body = {
        "messages": [{"role": "human", "content": "Explain these"}],
        "widgets": {
            "primary": [
                _selected("pi_charting", symbol="AAPL", window="6M"),
                _selected("pi_alerts_panel", account_id="demo"),
                _selected(
                    "pi_paper_ticket",
                    account_id="demo",
                    symbol="AAPL",
                    side="buy",
                    quantity="100",
                    confirm="true",
                ),
            ]
        },
    }
    response = TestClient(app).post("/query", json=body)
    assert response.status_code == 200
    events = _sse(response.text)
    calls = [data for name, data in events if name == "copilotFunctionCall"]
    assert len(calls) == 1 and calls[0]["function"] == "get_widget_data"
    sources = calls[0]["input_arguments"]["data_sources"]
    assert [s["id"] for s in sources] == ["pi_charting", "pi_alerts_panel"]
    assert sources[0]["input_args"] == {"symbol": "AAPL", "window": "6M", "raw": True}
    refusal = "".join(d["delta"] for n, d in events if n == "copilotMessageChunk")
    assert "pi_paper_ticket" in refusal


# ---------------------------------------------------------------------------
# Real endpoints, hermetic subprocess
# ---------------------------------------------------------------------------
SCRUB_PREFIXES = ("PI_", "DB_", "FMP", "OPENBB", "MYSQL", "FRED", "POLYGON", "COPILOT")
SCRUB_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "_PROXY")


def _hermetic_env(home: Path) -> dict[str, str]:
    """Same isolation as ``test_workspace_endpoint_contracts._hermetic_env``."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(SCRUB_PREFIXES)
        and not any(marker in name.upper() for marker in SCRUB_MARKERS)
    }
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[name] = str(home)
    env["PI_WIDGET_BACKEND_AUTH_MODE"] = "loopback-dev"
    env["PI_DEMO_MODE"] = "fallback"
    env["PI_PAPER_ENGINE"] = "sqlite"
    env["PI_PAPER_DB"] = str(home / "paper.db")
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    # Sentinel credentials: none may reach widget data or the agent context.
    for name in ("FMP_API_KEY", "OPENBB_PAT", "COPILOT_PROXY_API_KEY", "DB_PASSWORD"):
        env[name] = SENTINEL
    env["SENTINEL"] = SENTINEL
    return env


@pytest.fixture(scope="module", name="agent_reads")
def _agent_reads(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    home = tmp_path_factory.mktemp("agent-home")
    output = home / "agent.json"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter + in-repo probe
        [sys.executable, str(PROBE), "agent", str(output)],
        cwd=home,
        env=_hermetic_env(home),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    returncode = completed.returncode
    del completed
    assert returncode == 0, f"agent probe exited {returncode}"
    return json.loads(output.read_text(encoding="utf-8"))


def test_every_readable_widget_answers_the_agent(agent_reads):
    caps = build_agent_capabilities()
    readable = {k for k, c in caps.items() if c.readable}
    assert set(agent_reads) == readable
    failing = {k: v["status"] for k, v in agent_reads.items() if v["status"] != 200}
    assert not failing


def test_chart_reads_return_rows_not_figures(agent_reads):
    caps = build_agent_capabilities()
    plotly = {
        k
        for k, row in MATRIX_WIDGETS.items()
        if row["type"] == "chart" and (row["chart"] or {}).get("plotly")
    }
    assert plotly
    for widget_id in plotly:
        assert caps[widget_id].readable
        assert agent_reads[widget_id]["shape"] == "rows", widget_id


def test_agent_can_state_provenance_for_every_widget(agent_reads):
    """Every readable widget body carries a data state (#1271 cleared the debt)."""
    states = {"live", "cached", "demo", "stale", "partial", "unavailable"}
    unknown = {k for k, v in agent_reads.items() if v["state"] not in states}
    assert not unknown


def test_no_credential_reaches_widget_data_or_agent_context(agent_reads):
    leaked = {
        k for k, v in agent_reads.items() if v["body_leak"] or v["context_leak"]
    }
    assert not leaked


# ---------------------------------------------------------------------------
# Review fixes (#1272 round 2)
# ---------------------------------------------------------------------------
def test_backend_registers_its_connector_origin():
    from openbb_portfolio_intel.widget_backend.agent_policy import (  # pylint: disable=import-outside-toplevel
        agent_widget_origins,
    )

    assert getattr(app.state, copilot.ORIGINS_STATE) == frozenset({"portfolio-intel"})
    assert agent_widget_origins() == frozenset({"portfolio-intel"})


def test_origins_can_be_configured(monkeypatch):
    from openbb_portfolio_intel.widget_backend.agent_policy import (  # pylint: disable=import-outside-toplevel
        agent_widget_origins,
    )

    monkeypatch.setenv("PI_AGENT_WIDGET_ORIGINS", " My PI , other ")
    assert agent_widget_origins() == frozenset({"my pi", "other"})


def test_query_refuses_widgets_from_another_backend(monkeypatch):
    async def no_model(_messages):  # noqa: ANN001
        raise AssertionError("no model call before widget data arrives")
        yield  # pragma: no cover

    monkeypatch.setattr(copilot, "_proxy_deltas", no_model)
    foreign = _selected("pi_alerts_panel", account_id="demo")
    foreign["origin"] = "Some Other Backend"
    body = {
        "messages": [{"role": "human", "content": "Explain"}],
        "widgets": {"primary": [foreign, _selected("pi_news_ribbon", account_id="demo")]},
    }
    events = _sse(TestClient(app).post("/query", json=body).text)
    calls = [data for name, data in events if name == "copilotFunctionCall"]
    assert [s["id"] for s in calls[0]["input_arguments"]["data_sources"]] == [
        "pi_news_ribbon"
    ]


def test_allowlist_is_exactly_the_read_only_action_like_widgets():
    from openbb_portfolio.agent_capabilities import (  # pylint: disable=import-outside-toplevel
        action_markers,
    )
    from openbb_portfolio_intel.widget_backend.agent_policy import (  # pylint: disable=import-outside-toplevel
        AGENT_READ_ALLOWLIST,
        MANIFEST,
    )

    widgets = json.loads(MANIFEST.read_text(encoding="utf-8"))
    action_like = {k for k, w in widgets.items() if action_markers(w)}
    assert action_like == set(AGENT_READ_ALLOWLIST) | set(AGENT_DENIED_WIDGETS)


def test_a_new_action_like_widget_is_denied_by_default(tmp_path):
    """SECURITY-2: adding an action widget to the manifest never makes it readable."""
    from openbb_portfolio_intel.widget_backend.agent_policy import (  # pylint: disable=import-outside-toplevel
        MANIFEST,
    )

    widgets = json.loads(MANIFEST.read_text(encoding="utf-8"))
    widgets["tt_execute_submit"] = {
        "name": "Submit Paper Batch",
        "type": "markdown",
        "endpoint": "tt/execute/submit",
        "category": "Techtrade",
        "params": [{"paramName": "confirm", "value": "false", "type": "text"}],
    }
    widgets["pi_paper_rebalance"] = {
        "name": "Rebalance",
        "type": "table",
        "endpoint": "pi/paper/rebalance",
        "category": "Portfolio Intelligence",
    }
    manifest = tmp_path / "widgets.json"
    manifest.write_text(json.dumps(widgets), encoding="utf-8")
    caps = build_agent_capabilities(manifest)
    assert not caps["tt_execute_submit"].readable
    assert not caps["pi_paper_rebalance"].readable
    assert caps["pi_paper_blotter"].readable
