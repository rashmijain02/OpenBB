"""MCP chart tools return rows, never Plotly figures (#1272).

Since #1268 the Terminal chart endpoints return a Plotly figure by default
and their rows only with ``raw=true``. Workspace's agent contract says agents
read chart rows (``raw=true``); the cloned MCP tools must do the same, and
their rows carry the #1269 provenance columns.
"""

import inspect
import os

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
os.environ.setdefault("PI_DEMO_MODE", "fallback")

from openbb_mcp_server.adapters.portfolio_intel import (  # noqa: E402
    compose_portfolio_intel_app,
)
from openbb_mcp_server.app.app import create_mcp_server  # noqa: E402
from openbb_mcp_server.models.settings import MCPSettings  # noqa: E402
from openbb_mcp_server.service.exposure_policy import ExposurePolicy  # noqa: E402
from openbb_portfolio_intel.providers.retrofit import _TIER_CALLS  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import (  # noqa: E402
    app as intelligence_app,
)

# Every Plotly chart widget endpoint the portfolio-read profile admits: all
# 14 chart widgets, including the two TechTrade charts made Plotly in #1271.
EXPECTED_CHART_PATHS = {
    "/pi/attribution",
    "/pi/equity/charting",
    "/pi/equity/financials",
    "/pi/equity/price-history",
    "/pi/equity/price-target-history",
    "/pi/equity/revenue-business-line",
    "/pi/equity/revenue-geography",
    "/pi/equity/stock-ownership",
    "/pi/paper/performance",
    "/pi/risk/vol",
    "/pi/xray/country",
    "/pi/xray/sector",
    "/tt/position/simulate",
    "/tt/scan/segment-movers",
}
DEMO_PARAMS = {"account_id": "demo", "symbol": "AAPL"}


@pytest.fixture(autouse=True)
def _empty_snapshot_store(tmp_path, monkeypatch):
    """TechTrade charts read an empty synthetic store, never a home database."""
    # pylint: disable=import-outside-toplevel
    from openbb_portfolio_intel.widget_backend import widgets_endpoints
    from openbb_techtrade.snapshot.store import SqliteSnapshotStore

    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    monkeypatch.setattr(widgets_endpoints, "_get_snapshot_store", lambda: store)
    yield
    store.close()


@pytest.fixture(autouse=True)
def _no_provider_tiers():
    """Serve the labelled stub so no provider or network is reached."""
    saved = dict(_TIER_CALLS)
    _TIER_CALLS.clear()
    try:
        yield
    finally:
        _TIER_CALLS.clear()
        _TIER_CALLS.update(saved)


def _compose() -> FastAPI:
    return compose_portfolio_intel_app(
        FastAPI(),
        intelligence_app,
        MCPSettings(api_prefix="/api/v1", capability_profile="portfolio-read"),
        ExposurePolicy.load(),
    )


def _chart_paths(app: FastAPI) -> set[str]:
    return {
        route.path
        for route in app.router.routes
        if isinstance(route, APIRoute)
        and route.path.startswith(("/pi/", "/tt/"))
        and "raw" in inspect.signature(route.endpoint).parameters
    }


def _params(path: str, app: FastAPI) -> dict[str, str]:
    route = next(
        r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path
    )
    names = inspect.signature(route.endpoint).parameters
    return {k: v for k, v in DEMO_PARAMS.items() if k in names}


def test_cloned_chart_tools_are_the_expected_set():
    assert _chart_paths(_compose()) == EXPECTED_CHART_PATHS


@pytest.mark.parametrize("raw", [None, "false", "0"])
def test_chart_tools_always_return_rows_with_provenance(raw):
    """Fails if any MCP chart tool is fetched without ``raw=true``."""
    composed = _compose()
    client = TestClient(composed)
    for path in sorted(EXPECTED_CHART_PATHS):
        params = _params(path, composed)
        if raw is not None:
            params["raw"] = raw
        response = client.get(path, params=params)
        assert response.status_code == 200, path
        body = response.json()
        assert isinstance(body, list), f"{path} returned a figure, not rows"
        assert body and all("data_state" in row for row in body), path


def test_source_backend_still_serves_figures():
    """The rewrite is MCP-only; Workspace widgets keep their Plotly figure."""
    client = TestClient(intelligence_app)
    body = client.get("/pi/xray/country", params={"account_id": "demo"}).json()
    assert isinstance(body, dict) and "layout" in body


def test_chart_tool_descriptions_say_they_return_rows():
    schema = _compose().openapi()
    for path in EXPECTED_CHART_PATHS:
        description = schema["paths"][path]["get"].get("description", "")
        assert "raw=true" in description and "data_state" in description, path


@pytest.mark.asyncio
async def test_mcp_chart_tool_call_returns_rows():
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(settings, _compose(), auth=("synthetic-user", "x" * 32))
    result = str(await mcp.call_tool("intelligence_pi_xray_country", DEMO_PARAMS))
    assert "data_state" in result
    assert "layout" not in result


@pytest.mark.asyncio
async def test_middleware_replaces_raw_once_and_keeps_other_params():
    """The forwarded query has exactly one ``raw=true`` and the caller's other args."""
    from urllib.parse import parse_qsl  # pylint: disable=import-outside-toplevel

    from openbb_mcp_server.adapters.portfolio_intel import (  # pylint: disable=import-outside-toplevel
        ChartRowsMiddleware,
    )

    seen: dict = {}

    async def downstream(scope, receive, send):  # noqa: ANN001
        seen["query"] = scope["query_string"]

    middleware = ChartRowsMiddleware(downstream, frozenset({"/pi/xray/country"}))
    scope = {
        "type": "http",
        "path": "/pi/xray/country",
        "query_string": b"account_id=demo&raw=false&raw=0&note=a%26b",
    }
    await middleware(scope, None, None)
    pairs = parse_qsl(seen["query"].decode("latin-1"))
    assert pairs == [("account_id", "demo"), ("note", "a&b"), ("raw", "true")]

    other = {"type": "http", "path": "/pi/news", "query_string": b"raw=false"}
    await middleware(other, None, None)
    assert seen["query"] == b"raw=false"


@pytest.mark.parametrize("path", ["/tt/scan/segment-movers", "/tt/position/simulate"])
def test_techtrade_chart_tools_are_forced_to_rows(path):
    """#1271: the TechTrade Plotly charts are rows through MCP, raw=false or not."""
    composed = _compose()
    client = TestClient(composed)
    params = {**_params(path, composed), "raw": "false"}
    body = client.get(path, params=params).json()
    assert isinstance(body, list), f"{path} returned a figure, not rows"
    assert [row["data_state"] for row in body] == ["unavailable"]
    assert isinstance(
        TestClient(intelligence_app).get(path, params=_params(path, composed)).json(),
        dict,
    ), "the Workspace route keeps its Plotly figure"
