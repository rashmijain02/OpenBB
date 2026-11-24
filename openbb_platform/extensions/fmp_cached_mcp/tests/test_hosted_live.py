"""Live hosted-drift and parity checks (#1301, C4). Opt-in: ``pytest -m integration``.

They never update fixtures: a failure means the hosted server changed and the
fixtures must be re-recorded in a reviewed PR (README "Re-recording").
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

from openbb_fmp_cached_mcp.endpoint_map import PLAN_LIMITED_ALIASES
from openbb_fmp_cached_mcp.server import Scrubber, call_tool
from openbb_fmp_cached_mcp.upstream import FmpRestUpstream, load_fmp_key

from .conftest import SNAPSHOT, load_hosted

pytestmark = pytest.mark.integration

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


@pytest.fixture(scope="module")
def recorder():
    key = load_fmp_key()
    if not key:
        pytest.skip("no FMP key configured")
    sys.path.insert(0, str(SCRIPTS))
    import fmp_mcp_record as rec  # pylint: disable=import-outside-toplevel

    rec.KEY = key
    hosted = rec.Hosted()
    hosted.start()
    return rec, hosted, key


def test_hosted_tools_list_has_not_drifted(recorder):
    _, hosted, _ = recorder
    tools, cursor = [], None
    while True:
        res = hosted.post("tools/list", {"cursor": cursor} if cursor else {})["result"]
        tools += res["tools"]
        cursor = res.get("nextCursor")
        if not cursor:
            break
    assert tools == load_hosted(f"inventory-{SNAPSHOT}.json")["tools"]


LIVE_CALLS = [
    ("statements", {"endpoint": "income-statement", "symbol": "AAPL", "limit": 1}),
    ("company", {"endpoint": "profile-symbol", "symbol": "MSFT"}),
    (
        "chart",
        {
            "endpoint": "historical-price-eod-light",
            "symbol": "AAPL",
            "from_date": "2026-11-02",
            "to_date": "2026-11-06",
        },
    ),
    ("senate", {"endpoint": "senate-trading-by-name", "name": "Nobody Atall"}),
    ("quote", {"endpoint": "quote"}),
    ("quote", {"endpoint": "no-such"}),
]


@pytest.mark.parametrize(
    "tool, args", LIVE_CALLS, ids=[c[1]["endpoint"] for c in LIVE_CALLS]
)
def test_live_answer_equals_hosted(recorder, tool, args):
    rec, hosted, key = recorder

    async def ours():
        up = FmpRestUpstream(key)
        try:
            return await call_tool(up, Scrubber(key), tool, dict(args))
        finally:
            await up.aclose()

    mine = asyncio.run(ours())
    theirs = hosted.call(tool, dict(args))

    def mask(t: str) -> str:
        return re.sub(r"apikey=[^&\"]+", "apikey=<key>", rec.scrub(t))

    assert mask(mine.content[0].text) == mask(theirs["content"][0]["text"])
    assert bool(mine.isError) == bool(theirs.get("isError"))


@pytest.mark.plan_limited
@pytest.mark.parametrize("alias", sorted(PLAN_LIMITED_ALIASES))
def test_plan_limited_aliases_live(recorder, alias):
    """CLAUDE.md FMP-tier rule: gated unless --run-plan-limited on a higher plan."""
    plan_limited = pytest.importorskip("openbb_fmp_cached.utils.plan_limited")
    model = PLAN_LIMITED_ALIASES[alias]
    if plan_limited.is_plan_limited(model) and not os.environ.get("RUN_PLAN_LIMITED"):
        pytest.skip(
            f"FMP endpoint {alias} maps to plan-limited model {model!r} "
            "(see plan_limited.py); set RUN_PLAN_LIMITED=1 on a higher-tier key."
        )
    _, hosted, _ = recorder
    tool, ep = alias.split("/", 1)
    res = hosted.call(tool, {"endpoint": ep})
    assert res.get("content"), alias
