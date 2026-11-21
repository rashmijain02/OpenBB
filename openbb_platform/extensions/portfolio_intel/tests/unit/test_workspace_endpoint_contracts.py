"""Hermetic endpoint contract tests for every Workspace widget (#1266, plan Step 3).

The 61 widget endpoints are called with their manifest defaults inside a
subprocess (``_workspace_endpoint_probe.py``) that starts with a scrubbed
environment and HOME/USERPROFILE/APPDATA pointing at a temp dir. Every
import-time path (OpenBB settings and credentials, home databases) binds to
that temp dir, dotenv loading is disabled, and every DNS lookup and real
socket connect (loopback included) is refused, so no provider, network,
credential file, or operator database is reached. Known response violations
are recorded in ``fixtures/workspace_contract_debt.json`` under
``responses.*`` with the repair issue that removes them (shrink-only).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from openbb_portfolio_intel.widget_backend.contracts import (
    collect_response_issues,
    compare_with_baseline,
    load_debt_baseline,
)

UNIT = Path(__file__).resolve().parent
PROBE = UNIT / "_workspace_endpoint_probe.py"
BACKEND = UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
DEBT = UNIT / "fixtures" / "workspace_contract_debt.json"
WIDGETS: dict[str, Any] = json.loads(
    (BACKEND / "widgets.json").read_text(encoding="utf-8")
)
APPS: list[dict[str, Any]] = json.loads(
    (BACKEND / "apps.json").read_text(encoding="utf-8")
)
SCRUB_PREFIXES = ("PI_", "DB_", "FMP", "OPENBB", "MYSQL", "FRED", "POLYGON")
SCRUB_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "_PROXY")


def _hermetic_env(home: Path) -> dict[str, str]:
    """Return a scrubbed environment whose home and app-data dirs are temp."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(SCRUB_PREFIXES)
        and not any(marker in name.upper() for marker in SCRUB_MARKERS)
    }
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[name] = str(home)
    env["PI_WIDGET_BACKEND_AUTH_MODE"] = "loopback-dev"
    # Demo data is explicit (#1269): probe the labelled stub fallback.
    env["PI_DEMO_MODE"] = "fallback"
    # Fresh-install paper engine: sqlite with no database file yet.
    env["PI_PAPER_ENGINE"] = "sqlite"
    env["PI_PAPER_DB"] = str(home / "paper.db")
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    return env


def _run_probe(mode: str, home: Path) -> Any:
    """Run the probe subprocess and return its JSON result."""
    output = home / f"{mode}.json"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter + in-repo probe
        [sys.executable, str(PROBE), mode, str(output)],
        cwd=home,
        env=_hermetic_env(home),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    # Never echo probe stdout/stderr: it could contain response content.
    # Bind only the exit code so assertion rewriting cannot print the output.
    returncode = completed.returncode
    del completed
    assert returncode == 0, f"probe {mode} exited {returncode}"
    return json.loads(output.read_text(encoding="utf-8"))


class _Responses(dict):
    """Endpoint results whose repr never echoes response bodies into logs."""

    def __repr__(self) -> str:
        return f"<{len(self)} endpoint responses>"


@pytest.fixture(scope="module", name="responses")
def _responses_fixture(tmp_path_factory: pytest.TempPathFactory) -> _Responses:
    """Call every widget endpoint once inside the hermetic subprocess."""
    raw = _run_probe("probe", tmp_path_factory.mktemp("home"))
    return _Responses({key: tuple(value) for key, value in raw.items()})


def test_probe_isolation_guards_hold(tmp_path: Path) -> None:
    """Loopback (sync and async), DNS, home, OpenBB settings, dotenv are isolated."""
    checks = _run_probe("selftest", tmp_path)
    assert checks == {name: True for name in checks}
    assert len(checks) == 6
    assert repr(_Responses(a=(200, "secret body", None, None))) == (
        "<1 endpoint responses>"
    )


def test_hermetic_env_scrubs_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credential, provider, and proxy variables never reach the probe."""
    for name in ("FRED_API_KEY", "HTTPS_PROXY", "DB_PASSWORD", "PI_PAPER_DB"):
        monkeypatch.setenv(name, "x")
    env = _hermetic_env(Path("home"))
    assert "FRED_API_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert "DB_PASSWORD" not in env
    assert env["PI_PAPER_DB"] == str(Path("home") / "paper.db")


def _new_and_resolved(
    widget_id: str, status: int, body: str
) -> tuple[list[Any], list[Any]]:
    issues = collect_response_issues(widget_id, WIDGETS[widget_id], status, body)
    prefix = f"responses.{widget_id}"
    baseline = {
        key: value
        for key, value in load_debt_baseline(DEBT, prefix=prefix).items()
        if key[1] == prefix or key[1].startswith(f"{prefix}.")
    }
    return compare_with_baseline(issues, baseline)


@pytest.mark.parametrize("widget_id", sorted(WIDGETS))
def test_endpoint_response_matches_widget_contract(
    widget_id: str, responses: _Responses
) -> None:
    """Every endpoint returns its type's shape, or the gap is recorded debt."""
    status, body, _state, _source = responses[widget_id]
    new, resolved = _new_and_resolved(widget_id, status, body)
    assert not new, f"new response contract violations: {new}"
    assert not resolved, f"fixed response debt still in baseline, remove it: {resolved}"


def _body_state(widget: dict[str, Any], body: str) -> tuple[str, str] | None:
    """Return ``(state, source)`` as the response body states it (#1269)."""
    payload = json.loads(body)
    kind = widget["type"]
    if kind == "chart" and isinstance(payload, dict) and "layout" in payload:
        meta = payload["layout"]["meta"]
        return meta["state"], meta["source"]
    if kind == "table" and isinstance(payload, list) and payload:
        return payload[0]["data_state"], payload[0]["data_source"]
    if kind == "metric":
        value = payload[-1]["value"]
        return value.split(":", 1)[0].lower(), ""
    if kind == "markdown":
        match = re.search(r"\*\*Data state:\*\* (\w+).*?Source: `([^`]*)`", payload)
        return (match.group(1).lower(), match.group(2)) if match else None
    return None


@pytest.mark.parametrize("widget_id", sorted(WIDGETS))
def test_provenance_headers_match_the_body(
    widget_id: str, responses: _Responses
) -> None:
    """``X-PI-Data-State``/``-Source`` equal the state the body states (#1269)."""
    status, body, state, source = responses[widget_id]
    assert status == 200
    stated = _body_state(WIDGETS[widget_id], body)
    if stated is None:  # #1271 shape-debt envelope: headers still carry state
        assert state is not None and source is not None
        return
    assert state == stated[0]
    if stated[1]:
        assert source == stated[1]


def test_every_placed_widget_has_an_endpoint_contract_test() -> None:
    """App placements reference only widgets covered by the test above."""
    placed = {
        placement["i"]
        for app_def in APPS
        for tab in app_def["tabs"].values()
        for placement in tab["layout"]
    }
    assert placed <= set(WIDGETS)


def test_response_checker_rejects_wrong_shapes() -> None:
    """Each response rule fires on a synthetic violation."""
    table = {"type": "table", "data": {"table": {"columnsDefs": [{"field": "a"}]}}}
    cases = [
        ({"type": "chart"}, 200, "[]", "response.shape.chart"),
        ({"type": "chart"}, 200, '{"data": []}', "response.state.chart"),
        (table, 200, '{"a": 1}', "response.shape.table"),
        (table, 200, "[]", "response.empty"),
        (table, 200, '[{"b": 1}]', "response.table.column_missing"),
        ({"type": "markdown"}, 200, '""', "response.shape.markdown"),
        ({"type": "metric"}, 200, '{"value": 1}', "response.shape.metric"),
        ({"type": "table"}, 200, '[{"a": NaN}]', "response.json"),
        ({"type": "table"}, 500, "", "response.status"),
    ]
    for widget, status, body, code in cases:
        codes = {i.code for i in collect_response_issues("w", widget, status, body)}
        assert code in codes, (widget, body, codes)
    live = '{"data": [], "layout": {"meta": {"state": "live", "source": "x"}}}'
    assert not collect_response_issues("w", {"type": "chart"}, 200, live)
    row = '{"a": 1, "data_state": "demo", "data_source": "stub", "data_as_of": "u"}'
    assert not collect_response_issues("w", table, 200, f"[{row}]")
    keyed = {"type": "table", "data": {"dataKey": "rows"}}
    assert not collect_response_issues("w", keyed, 200, f'{{"rows": [{row}]}}')
    assert collect_response_issues("w", keyed, 200, '{"rows": {"a": 1}}')
    card = '{"label": "Data State", "value": "Demo: synthetic"}'
    assert not collect_response_issues("w", {"type": "metric"}, 200, card)
