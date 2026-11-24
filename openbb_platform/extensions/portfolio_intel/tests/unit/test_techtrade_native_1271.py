"""TechTrade Desk native Workspace behavior (#1271, plan Step 7).

Three parts:

1. **Native contracts.** Segment Movers and Simulated P&L are Plotly figures
   (``raw=true`` returns the rows); the Scan Table returns an array of rows
   with ``columnsDefs`` and a symbol click-through to the ticker group. No
   ``dataKey`` wrappers remain, so the #1271 contract debt is empty.
2. **Read-only and paper boundaries.** No TechTrade widget (nor the paper
   ticket) can place, write or cancel an order, whatever parameters it is
   sent. The execution endpoints refuse every request that lacks one of
   their explicit gates, without reaching an order seam.
3. **Privacy follow-ups.** ``/tt/execute/paper-status`` withholds the paper
   account id (``account_display``).

Every store is a synthetic SQLite snapshot under ``tmp_path``; no home
directory, MySQL or brokerage data is read.
"""

# ruff: noqa: D103

from __future__ import annotations

import importlib
import json
import os
import re
import types
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend import widgets_endpoints
from openbb_portfolio_intel.widget_backend._shared import account_display
from openbb_portfolio_intel.widget_backend.contracts import collect_response_issues
from openbb_portfolio_intel.widget_backend.main import app
from openbb_techtrade.snapshot.registry import DEFAULT_DATASET_REGISTRY
from openbb_techtrade.snapshot.store import SnapshotStatus, SqliteSnapshotStore

_UNIT = Path(__file__).resolve().parent
_BACKEND = _UNIT.parents[1] / "openbb_portfolio_intel" / "widget_backend"
_WIDGETS: dict[str, Any] = json.loads(
    (_BACKEND / "widgets.json").read_text(encoding="utf-8")
)
_APPS: list[dict[str, Any]] = json.loads(
    (_BACKEND / "apps.json").read_text(encoding="utf-8")
)
_DEBT = _UNIT / "fixtures" / "workspace_contract_debt.json"
_VIEWER = (
    _UNIT.parents[3]
    / "extensions"
    / "portfolio"
    / "assets"
    / "local_viewer"
    / "index.html"
)
_CLIENT = TestClient(app, raise_server_exceptions=False)
_STORE_PATH = (
    "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store"
)

SESSION = date(2026, 9, 11)
SEGMENT = "Information Technology"
DISCLAIMER = "EOD planning snapshot — not a live/intraday quote"
TT_WIDGETS = sorted(w for w in _WIDGETS if w.startswith("tt_"))
_TECHTRADE_APP = next(a for a in _APPS if a["id"] == "custom-techtrade-desk")
_PLACED = {p["i"] for tab in _TECHTRADE_APP["tabs"].values() for p in tab["layout"]}


# ---------------------------------------------------------------------------
# Synthetic snapshot store
# ---------------------------------------------------------------------------


def _seed(
    store: SqliteSnapshotStore,
    dataset: str,
    rows: list[dict],
    *,
    segment: str = SEGMENT,
) -> None:
    key = f"segment={segment.casefold()}"
    payload = {
        "rows": rows,
        "segment": segment,
        "as_of_session": SESSION.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": [],
        "excluded_symbols": [],
        "survivorship": "not-applicable",
        "universe_membership": [],
    }
    run_id = f"{dataset.replace('.', '-')}-{segment.replace(' ', '-')}"
    store.stage(
        dataset,
        key,
        SESSION,
        run_id,
        payload,
        status=SnapshotStatus.OK,
        row_count=len(rows),
        engine_version="test",
        payload_schema_version="1",
    )
    definition = DEFAULT_DATASET_REGISTRY.require(dataset)
    assert store.validate(
        dataset, key, SESSION, run_id, lambda row: definition.validator(row, None)
    ).ok
    assert store.promote(dataset, key, SESSION, run_id)


_MOVERS = [
    {"symbol": "NVDA", "segment": SEGMENT, "pct_change": 4.2, "rank": 1},
    {"symbol": "MSFT", "segment": SEGMENT, "pct_change": -1.5, "rank": 2},
]
_ENERGY_MOVERS = [
    {"symbol": "XOM", "segment": "Energy", "pct_change": -2.75, "rank": 1},
]
# The shape ``openbb_techtrade.snapshots.models.plan_to_row`` materializes.
_SCAN_ROW = {
    "symbol": "NVDA",
    "segment": SEGMENT,
    "as_of": SESSION.isoformat(),
    "direction": "long",
    "score": 0.91,
    "rank_in_segment": 1,
    "action": "buy",
    "conviction": "high",
    "entry_price": 100.0,
    "stop_price": 95.0,
    "target_price": 110.0,
    "stop_distance_pct": 5.0,
    "target_distance_pct": 10.0,
    "risk_reward": 2.0,
    "atr": 2.5,
    "position_size": 10.0,
    "risk_per_share": 5.0,
    "risk_pct_of_notional": 0.05,
    "time_stop_bars": 10,
    "reasoning": "trend and momentum agree",
    "top_factors": ["trend", "momentum"],
    "order_count": 3,
    "filled": False,
}
# The shape ``snapshot.adapters._planned_trajectories`` materializes.
_SIMULATE = [
    {
        "symbol": "NVDA",
        "segment": SEGMENT,
        "day": day,
        "timestamp": f"2026-09-{14 + day:02d}T20:00:00+00:00",
        "price": price,
        "pnl": pnl,
        "source": "simulated_fill",
    }
    for day, price, pnl in ((0, 100.0, -1.0), (1, 104.0, 39.0), (2, 110.0, 99.0))
]


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[SqliteSnapshotStore]:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    _seed(store, "techtrade.movers", _MOVERS)
    _seed(store, "techtrade.movers", _ENERGY_MOVERS, segment="Energy")
    _seed(store, "techtrade.scan", [_SCAN_ROW])
    _seed(store, "techtrade.simulate", _SIMULATE)
    with patch(_STORE_PATH, return_value=store):
        yield store
    store.close()


@pytest.fixture
def empty_store(tmp_path: Path) -> Iterator[SqliteSnapshotStore]:
    store = SqliteSnapshotStore(tmp_path / "empty.db")
    with patch(_STORE_PATH, return_value=store):
        yield store
    store.close()


@pytest.fixture
def completed_empty(tmp_path: Path) -> Iterator[SqliteSnapshotStore]:
    """Snapshots exist for the segment, but the run produced no rows."""
    store = SqliteSnapshotStore(tmp_path / "completed-empty.db")
    for dataset in ("techtrade.movers", "techtrade.scan", "techtrade.simulate"):
        _seed(store, dataset, [])
    with patch(_STORE_PATH, return_value=store):
        yield store
    store.close()


def _issues(widget_id: str, response: Any) -> list[str]:
    return [
        issue.code
        for issue in collect_response_issues(
            widget_id, _WIDGETS[widget_id], response.status_code, response.text
        )
    ]


def _annotation_text(figure: dict) -> str:
    return " ".join(a.get("text", "") for a in figure["layout"].get("annotations", []))


# ---------------------------------------------------------------------------
# 1. Native contracts
# ---------------------------------------------------------------------------


def test_no_1271_contract_debt_remains() -> None:
    """The five #1271 entries are cleared; nothing else is recorded."""
    issues = json.loads(_DEBT.read_text(encoding="utf-8"))["issues"]
    assert [entry for entry in issues if entry["tracking"] == "#1271"] == []


@pytest.mark.parametrize("widget_id", ["tt_segment_movers", "tt_scan_table"])
def test_no_top_level_data_key_wrapper(widget_id: str) -> None:
    """``dataKey`` is not a widget-level key in the Workspace schema."""
    widget = _WIDGETS[widget_id]
    assert "dataKey" not in widget
    assert "dataKey" not in (widget.get("data") or {})


def test_techtrade_desk_places_twelve_widgets_on_six_tabs() -> None:
    assert len(_TECHTRADE_APP["tabs"]) == 6
    placements = [p for t in _TECHTRADE_APP["tabs"].values() for p in t["layout"]]
    assert len(placements) == 12


def test_segment_movers_is_a_plotly_bar_of_row_values(seeded) -> None:
    response = _CLIENT.get("/tt/scan/segment-movers")
    assert response.status_code == 200
    figure = response.json()
    assert _issues("tt_segment_movers", response) == []
    assert "title" not in figure["layout"]
    (trace,) = figure["data"]
    assert trace["type"] == "bar"
    # Strongest mover per segment, unscaled: NVDA +4.2 beats MSFT -1.5.
    pairs = dict(zip(trace["x"], trace["y"]))
    assert pairs == {SEGMENT: 4.2, "Energy": -2.75}
    assert dict(zip(trace["x"], trace["text"])) == {SEGMENT: "NVDA", "Energy": "XOM"}
    meta = figure["layout"]["meta"]
    assert meta["source"] == "eod-snapshot"
    assert meta["asOf"] == SESSION.isoformat()
    assert meta["state"] == "partial"  # 2 of 11 segments materialized
    assert DISCLAIMER in _annotation_text(figure)
    assert response.headers["x-pi-data-state"] == "partial"


def test_segment_movers_raw_rows_keep_values_and_state(seeded) -> None:
    rows = _CLIENT.get("/tt/scan/segment-movers?raw=true").json()
    by_segment = {row["segment"]: row for row in rows}
    assert by_segment[SEGMENT]["symbol"] == "NVDA"
    assert by_segment[SEGMENT]["change_pct"] == 4.2
    assert by_segment[SEGMENT]["bucket"] == "gainer"
    assert by_segment["Energy"]["bucket"] == "loser"
    for row in rows:
        assert row["data_state"] == "partial"
        assert row["data_source"] == "eod-snapshot"
        assert row["disclaimer"] == DISCLAIMER


def test_simulate_is_a_plotly_line_of_marked_pnl(seeded) -> None:
    response = _CLIENT.get("/tt/position/simulate?symbol=NVDA")
    assert response.status_code == 200
    figure = response.json()
    assert _issues("tt_simulate_result", response) == []
    assert "title" not in figure["layout"]
    (trace,) = figure["data"]
    assert trace["type"] == "scatter"
    assert trace["x"] == [0, 1, 2]
    assert trace["y"] == [-1.0, 39.0, 99.0]
    assert figure["layout"]["meta"]["source"] == "eod-snapshot"
    assert DISCLAIMER in _annotation_text(figure)


def test_simulate_raw_rows_are_the_snapshot_rows(seeded) -> None:
    rows = _CLIENT.get("/tt/position/simulate?symbol=NVDA&raw=true").json()
    assert [row["pnl"] for row in rows] == [-1.0, 39.0, 99.0]
    assert all(row["data_source"] == "eod-snapshot" for row in rows)


@pytest.mark.parametrize(
    ("widget_id", "url"),
    [
        ("tt_segment_movers", "/tt/scan/segment-movers"),
        ("tt_simulate_result", "/tt/position/simulate?symbol=NVDA"),
    ],
)
def test_chart_without_snapshot_is_an_unavailable_figure(
    empty_store, widget_id: str, url: str
) -> None:
    response = _CLIENT.get(url)
    figure = response.json()
    assert figure["data"] == []
    assert figure["layout"]["meta"]["state"] == "unavailable"
    assert "no eod snapshot" in _annotation_text(figure).lower()
    assert _issues(widget_id, response) == []
    raw = _CLIENT.get(url + ("&" if "?" in url else "?") + "raw=true").json()
    assert [row["data_state"] for row in raw] == ["unavailable"]


@pytest.mark.parametrize(
    ("widget_id", "url"),
    [
        ("tt_segment_movers", "/tt/scan/segment-movers"),
        ("tt_simulate_result", "/tt/position/simulate?symbol=NVDA"),
        ("tt_scan_table", "/tt/scan/table"),
    ],
)
def test_completed_empty_snapshot_is_unavailable_not_missing(
    completed_empty, widget_id: str, url: str
) -> None:
    """A finished run with no rows is not data, and is not 'no snapshot'."""
    response = _CLIENT.get(url)
    assert _issues(widget_id, response) == []
    assert response.headers["x-pi-data-state"] == "unavailable"
    text = response.text.lower()
    assert "completed with no" in text
    assert "no eod snapshot available" not in text


def test_scan_table_returns_rows_with_declared_columns(seeded) -> None:
    response = _CLIENT.get("/tt/scan/table")
    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list) and rows
    assert _issues("tt_scan_table", response) == []
    columns = _WIDGETS["tt_scan_table"]["data"]["table"]["columnsDefs"]
    fields = [column["field"] for column in columns]
    assert fields[0] == "symbol"
    assert set(fields) <= set(rows[0])
    assert rows[0]["symbol"] == "NVDA"
    assert rows[0]["entry_price"] == 100.0
    assert rows[0]["data_source"] == "eod-snapshot"


def test_scan_table_without_snapshot_is_one_unavailable_row(empty_store) -> None:
    response = _CLIENT.get("/tt/scan/table")
    rows = response.json()
    assert [row["data_state"] for row in rows] == ["unavailable"]
    assert "no eod snapshot" in rows[0]["note"].lower()
    assert _issues("tt_scan_table", response) == []


def _glossary_summaries() -> set[str]:
    return set(re.findall(r'summary: "([^"]+)"', _VIEWER.read_text(encoding="utf-8")))


def test_scan_table_columns_carry_curated_header_tooltips() -> None:
    """Numeric plan columns explain themselves with a viewer glossary summary."""
    columns = {
        column["field"]: column
        for column in _WIDGETS["tt_scan_table"]["data"]["table"]["columnsDefs"]
    }
    summaries = _glossary_summaries()
    for field in ("score", "entry_price", "stop_price", "target_price", "risk_reward"):
        assert columns[field]["headerTooltip"] in summaries, field
    for field in ("data_source", "data_as_of"):
        assert columns[field]["hide"] is True


def test_scan_table_symbol_click_drives_the_ticker_group() -> None:
    """A symbol click updates Group 1 (pinned Workspace ``useCellOnClickHandler``).

    For a ``ticker`` group the handler fires only when ``groupBy.paramName``
    equals the clicking widget's own ticker-typed param, so the table carries a
    hidden ``symbol`` ticker param (``show: false``, as the app-builder
    layout-grid spec requires for a click-driven param).
    """
    widget = _WIDGETS["tt_scan_table"]
    symbol_column = widget["data"]["table"]["columnsDefs"][0]
    assert symbol_column["renderFn"] == "cellOnClick"
    assert symbol_column["renderFnParams"] == {
        "actionType": "groupBy",
        "groupBy": {"paramName": "symbol"},
    }
    params = {p["paramName"]: p for p in widget["params"]}
    assert params["symbol"]["type"] == "ticker"
    assert params["symbol"]["show"] is False
    group = next(g for g in _TECHTRADE_APP["groups"] if g["type"] == "ticker")
    assert "tt_scan_table" in group["widgetIds"]


# ---------------------------------------------------------------------------
# 2. Read-only and paper boundaries
# ---------------------------------------------------------------------------


class _OrderSeams:
    """Replace every order-placing seam with a recorder that refuses.

    The seams sit *below* the gates (``ExecutionGateway`` and the endpoint
    checks run unpatched): the paper/live broker adapters, both paper engines
    and the CSV/XLSX batch sink.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        targets = [
            ("openbb_techtrade.execution.order_sink", "PaperOrderSink", "write_batch"),
            ("openbb_techtrade.execution.paper_engine", "SqlitePaperEngine", "submit_batch"),
            ("openbb_techtrade.execution.paper_engine", "SqlitePaperEngine", "record_fill"),
            ("openbb_techtrade.execution.paper_engine", "SqlitePaperEngine", "cancel_order"),
            ("openbb_techtrade.execution.broker_backends", "PaperBrokerAdapter", "submit_batch"),
            ("openbb_techtrade.execution.broker_backends", "PaperBrokerAdapter", "cancel_order"),
            ("openbb_techtrade.execution.broker_backends", "LiveBrokerAdapter", "submit_batch"),
            ("openbb_techtrade.execution.broker_backends", "LiveBrokerAdapter", "cancel_order"),
            ("openbb_techtrade.execution.mysql_paper_engine", "MysqlPaperEngine", "submit_batch"),
            ("openbb_techtrade.execution.mysql_paper_engine", "MysqlPaperEngine", "record_fill"),
            ("openbb_techtrade.execution.mysql_paper_engine", "MysqlPaperEngine", "cancel_order"),
        ]  # fmt: skip
        for module_name, class_name, method in targets:
            cls = getattr(importlib.import_module(module_name), class_name)
            monkeypatch.setattr(cls, method, self._refuse(f"{class_name}.{method}"))

    def _refuse(self, name: str) -> Any:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(f"order seam reached: {name}")

        return refuse


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Paper/execution state under ``tmp_path`` only; execution env allowed."""
    root = tmp_path / "sandbox"
    root.mkdir()
    home = root / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("PI_PAPER_DB", str(root / "paper.db"))
    monkeypatch.setenv("PI_T5_EXECUTE_OUTPUT_DIR", str(root / "t5_out"))
    monkeypatch.setenv("PI_T5_EXECUTION_AUDIT_DB", str(root / "audit" / "audit.db"))
    monkeypatch.setenv("PI_T5_BROKER_MODE", "paper")
    monkeypatch.setenv("PI_PAPER_ENGINE", "sqlite")
    monkeypatch.delenv("PI_ALLOW_T5_LIVE", raising=False)
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    with patch(_STORE_PATH, return_value=store):
        yield root
    store.close()


def _tree(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*")}


def _route_methods(path: str) -> set[str]:
    methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", None) == path:
            methods |= set(getattr(route, "methods", set()) or set())
    return methods


_READ_ONLY_WIDGETS = [*TT_WIDGETS, "pi_paper_ticket"]
# Parameters a confused or hostile caller could add to try to trigger a write.
_HOSTILE = {"verdict": "PASS", "confirm": "yes", "plan_id": "widget-demo"}


@pytest.mark.parametrize("widget_id", _READ_ONLY_WIDGETS)
def test_widget_endpoint_is_a_get_only_route(widget_id: str) -> None:
    path = "/" + _WIDGETS[widget_id]["endpoint"].lstrip("/")
    assert _route_methods(path) <= {"GET", "HEAD"}, path
    assert "GET" in _route_methods(path), path


@pytest.mark.parametrize("widget_id", _READ_ONLY_WIDGETS)
def test_widget_never_places_or_writes_an_order(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path, widget_id: str
) -> None:
    """Even with execution allowed and confirm/verdict sent, a widget is read-only."""
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    seams = _OrderSeams(monkeypatch)
    before = _tree(sandbox)
    widget = _WIDGETS[widget_id]
    params = {p["paramName"]: p["value"] for p in widget.get("params", [])}
    for extra in ({}, _HOSTILE, {"confirm": "true"}):
        response = _CLIENT.get(
            "/" + widget["endpoint"].lstrip("/"), params={**params, **extra}
        )
        assert response.status_code < 500, (extra, response.text[:200])
    assert seams.calls == []
    assert _tree(sandbox) == before, "a read-only widget created files"


def test_execute_bridge_reports_readiness_without_executing(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    seams = _OrderSeams(monkeypatch)
    ready = _CLIENT.get("/tt/execute/bridge?verdict=PASS").json()
    blocked = _CLIENT.get("/tt/execute/bridge?verdict=FAIL").json()
    assert "Execute Bridge: READY" in ready
    assert "confirm=yes" in ready  # the explicit confirmation stays required
    assert "BLOCKED" in blocked and "READY" not in blocked
    assert seams.calls == []


# (params, execution env allowed, status, the gate that must refuse it)
_DENIED = [
    pytest.param({}, False, 403, "t5_execute_not_allowed", id="execution-env-off"),
    pytest.param(
        {"verdict": "FAIL", "confirm": "yes"},
        True,
        400,
        "verdict_gate_blocked",
        id="verdict-fail",
    ),
    pytest.param(
        {"verdict": "PASS"}, True, 400, "explicit_confirm_required", id="no-confirm"
    ),
    pytest.param(
        {"confirm": "yes"}, True, 400, "verdict_gate_blocked", id="no-verdict"
    ),
]


@pytest.mark.parametrize(("params", "allowed", "status", "gate"), _DENIED)
def test_write_batch_denied_paths_never_reach_an_order_seam(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: Path,
    params: dict[str, str],
    allowed: bool,
    status: int,
    gate: str,
) -> None:
    if allowed:
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    else:
        monkeypatch.delenv("PI_ALLOW_T5_EXECUTE", raising=False)
    seams = _OrderSeams(monkeypatch)
    before = _tree(sandbox)
    response = _CLIENT.post("/tt/execute/write-batch", params=params)
    assert response.status_code == status
    # The endpoint's own gate refuses it, not a deeper defence.
    assert gate in response.json()["detail"]
    assert seams.calls == []
    assert _tree(sandbox) == before


def test_write_batch_with_every_gate_reaches_the_order_seam(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    """Control: the seam recorder does detect a real paper submission."""
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    seams = _OrderSeams(monkeypatch)
    _CLIENT.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
    assert seams.calls, "the gated write path must reach an order seam"


def test_cancel_without_execution_env_is_refused(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    monkeypatch.delenv("PI_ALLOW_T5_EXECUTE", raising=False)
    seams = _OrderSeams(monkeypatch)
    response = _CLIENT.post(
        "/tt/execute/cancel",
        params={"order_uuid": "00000000-0000-4000-8000-000000000000"},
    )
    assert 400 <= response.status_code < 500
    assert seams.calls == []


def _ticket(confirm: str) -> str:
    return _CLIENT.get(
        "/pi/paper/ticket",
        params={
            "account_id": "demo",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": "100",
            "confirm": confirm,
        },
    ).json()


def _claims_commit(body: str) -> bool:
    """True when the text says an order was committed/submitted/placed."""
    lowered = body.lower().replace("no order placed", "").replace("not_submitted", "")
    return bool(re.search(r"committed|submitted|order placed", lowered))


def test_paper_ticket_defaults_to_a_preview() -> None:
    params = {p["paramName"]: p for p in _WIDGETS["pi_paper_ticket"]["params"]}
    assert params["confirm"]["value"] == "false"
    preview = _ticket("false")
    assert "**Ticket state:** `preview`" in preview
    assert not _claims_commit(preview)


@pytest.mark.parametrize("confirm", ["true", "TRUE"])
def test_paper_ticket_never_claims_a_commit_it_did_not_make(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path, confirm: str
) -> None:
    """``confirm=true`` writes nothing, so the ticket must not claim a commit.

    It says exactly what happened (preview confirmed, no order placed) and
    names the only gated path that submits paper orders.
    """
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    seams = _OrderSeams(monkeypatch)
    before = _tree(sandbox)
    body = _ticket(confirm)
    assert seams.calls == [] and _tree(sandbox) == before  # nothing happened...
    assert not _claims_commit(body)  # ...so nothing is claimed
    assert "COMMITTED" not in body
    assert "**Ticket state:** `not_submitted`" in body
    assert "Preview confirmed. No order placed." in body
    assert "POST /tt/execute/write-batch" in body


def test_gated_write_batch_reports_the_commit_it_made(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    """Positive control: the real gated paper path reports its submission."""
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    response = _CLIENT.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
    assert response.status_code == 200
    body = response.json()
    assert len(body["order_ids"]) == 3
    assert body["batch_sha"]
    assert (sandbox / "paper.db").exists()  # the write really happened


# ---------------------------------------------------------------------------
# 3. Privacy: paper-status JSON withholds the paper account id
# ---------------------------------------------------------------------------

_ACCOUNT = "PAPER-ACCT-SENTINEL-7781"


def test_paper_status_json_withholds_the_engine_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openbb_techtrade.execution import paper_engine

    account = types.SimpleNamespace(
        account_id=_ACCOUNT, starting_cash=100000, cash=99000, realized_pl=0
    )
    engine = types.SimpleNamespace(
        is_initialized=lambda: True,
        get_account=lambda: account,
        get_positions=lambda: [],
        get_orders=lambda status=None: [],
        close=lambda: None,
    )
    monkeypatch.setenv("PI_PAPER_ENGINE", "mysql")
    monkeypatch.setattr(paper_engine, "get_default_engine", lambda **_k: engine)
    response = _CLIENT.get("/tt/execute/paper-status")
    assert response.status_code == 200
    assert _ACCOUNT not in response.text
    body = response.json()
    assert body["account"]["account_id"] == account_display(_ACCOUNT)
    assert body["account"]["cash"] == "99000"


def test_paper_status_json_still_names_the_demo_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openbb_techtrade.execution import paper_engine

    account = types.SimpleNamespace(
        account_id="demo", starting_cash=1, cash=1, realized_pl=0
    )
    engine = types.SimpleNamespace(
        is_initialized=lambda: True,
        get_account=lambda: account,
        get_positions=lambda: [],
        get_orders=lambda status=None: [],
        close=lambda: None,
    )
    monkeypatch.setenv("PI_PAPER_ENGINE", "mysql")
    monkeypatch.setattr(paper_engine, "get_default_engine", lambda **_k: engine)
    body = _CLIENT.get("/tt/execute/paper-status").json()
    assert body["account"]["account_id"] == account_display("demo")


def test_every_placed_techtrade_widget_is_in_the_manifest() -> None:
    assert set(TT_WIDGETS) >= _PLACED
    assert widgets_endpoints.app is app


# ---------------------------------------------------------------------------
# Review fixes: excluded symbols, write-batch echoes (#1271 code review)
# ---------------------------------------------------------------------------


def _seed_excluded(store: SqliteSnapshotStore, dataset: str, symbol: str) -> None:
    key = f"segment={SEGMENT.casefold()}"
    payload = {
        "rows": [],
        "segment": SEGMENT,
        "as_of_session": SESSION.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": [],
        "excluded_symbols": [symbol],
        "exclusion_reasons": {symbol: "halted"},
        "survivorship": "not-applicable",
    }
    store.stage(
        dataset,
        key,
        SESSION,
        "excluded",
        payload,
        row_count=0,
        engine_version="test",
        payload_schema_version="1",
    )
    definition = DEFAULT_DATASET_REGISTRY.require(dataset)
    assert store.validate(
        dataset, key, SESSION, "excluded", lambda row: definition.validator(row, None)
    ).ok
    assert store.promote(dataset, key, SESSION, "excluded")


def test_simulate_for_an_excluded_symbol_is_an_unavailable_figure(
    tmp_path: Path,
) -> None:
    """A halted/delisted symbol is explained, never a 500 (CODE-2)."""
    store = SqliteSnapshotStore(tmp_path / "excluded.db")
    _seed_excluded(store, "techtrade.simulate", "AAPL")
    with patch(_STORE_PATH, return_value=store):
        response = _CLIENT.get("/tt/position/simulate?symbol=AAPL")
        raw = _CLIENT.get("/tt/position/simulate?symbol=AAPL&raw=true")
    store.close()
    assert response.status_code == 200
    figure = response.json()
    assert figure["data"] == []
    assert figure["layout"]["meta"]["state"] == "unavailable"
    assert "excluded" in _annotation_text(figure).lower()
    assert "halted" in _annotation_text(figure).lower()
    assert _issues("tt_simulate_result", response) == []
    rows = raw.json()
    assert raw.status_code == 200
    assert [(r["symbol"], r["excluded"], r["data_state"]) for r in rows] == [
        ("AAPL", True, "unavailable")
    ]
    assert "halted" in rows[0]["note"]


def test_simulate_figure_skips_rows_without_day_or_pnl() -> None:
    """The builder plots only complete rows; no KeyError on partial rows."""
    from openbb_portfolio_intel.widget_backend.provenance import (
        DataState,
        Provenance,
    )
    from openbb_portfolio_intel.widget_backend.techtrade_charts import (
        simulate_figure,
    )
    from openbb_portfolio_intel.widget_backend.terminal_charts import ChartContext

    ctx = ChartContext(
        {"symbol": "NVDA"},
        Provenance(DataState.CACHED, "eod-snapshot", "snapshot", "2026-09-11"),
    )
    figure = simulate_figure(
        [{"symbol": "NVDA", "note": "partial"}, {**_SIMULATE[0]}], ctx
    )
    assert [t["y"] for t in figure["data"]] == [[-1.0]]
    empty = simulate_figure([{"symbol": "NVDA", "note": "partial"}], ctx)
    assert empty["data"] == [] and empty["layout"]["meta"]["state"] == "unavailable"


def test_write_batch_receipt_withholds_account_and_absolute_paths(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    """The receipt names files home-relative or by name, not the operator path."""
    monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
    response = _CLIENT.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
    assert response.status_code == 200  # positive control: the write happened
    body = response.json()
    assert len(body["order_ids"]) == 3
    assert body["account_id"] == account_display("paper")
    for field in ("csv_path", "xlsx_path"):
        shown = body[field]
        assert str(sandbox) not in shown and not Path(shown).is_absolute(), field
        written = list((sandbox / "t5_out").rglob(Path(shown).name))
        assert written, f"{field}: the file itself is still written"
    assert str(sandbox) not in response.text


def test_approve_plan_withholds_the_account_id_field(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    from decimal import Decimal

    from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket

    batch = OrderBatch(
        tickets=(OrderTicket("TSLA", "Buy", Decimal("2")),),
        plan_id="validated-plan",
        verdict_gate_pass=True,
    )

    async def approved_builder(_plan, _approval_id):
        return batch

    monkeypatch.setattr(
        app.state, "t5_plan_approval_builder", approved_builder, raising=False
    )
    response = _CLIENT.post(
        "/tt/execute/approve-plan",
        params={"approval_request_id": "00000000-0000-4000-8000-000000001271"},
        json={"symbol": "MSFT"},
    )
    assert response.status_code == 200
    assert response.json()["account_id"] == account_display("paper")


def test_agent_denial_reason_for_the_paper_ticket_is_truthful() -> None:
    """The ticket stays agent-denied, but its stated reason must be true.

    Since #1271 the ticket never places or commits an order, so a reason
    that says it does is a false claim shown to users and agents.
    """
    from openbb_portfolio_intel.widget_backend.agent_policy import (
        AGENT_DENIED_WIDGETS,
    )

    reason = AGENT_DENIED_WIDGETS["pi_paper_ticket"]
    assert not _claims_commit(reason.replace("places no order", "")), reason
    assert "places paper orders" not in reason
    assert "no order" in reason
