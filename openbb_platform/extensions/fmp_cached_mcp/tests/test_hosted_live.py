"""Live hosted-drift and parity checks (#1301, C4). Opt-in: ``pytest -m integration``.

They never update fixtures: a failure means the hosted server changed and the
fixtures must be re-recorded in a reviewed PR (README "Re-recording").
"""

from __future__ import annotations

import asyncio
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


def _is_plan_limited(alias: str) -> bool:
    try:
        from openbb_fmp_cached.utils.plan_limited import (  # pylint: disable=C0415
            is_plan_limited,
        )
    except ImportError:
        return False
    return is_plan_limited(PLAN_LIMITED_ALIASES[alias])


@pytest.mark.plan_limited  # skipped without --run-plan-limited (conftest)
@pytest.mark.parametrize(
    "alias",
    [
        pytest.param(
            a,
            marks=pytest.mark.skipif(
                _is_plan_limited(a),
                reason=(
                    f"FMP endpoint {a!r} maps to plan-limited model "
                    f"{PLAN_LIMITED_ALIASES[a]!r} (see plan_limited.py). Our current "
                    "key does not cover it; run `pytest -m plan_limited "
                    "--run-plan-limited` on a higher-tier key to exercise."
                ),
            ),
        )
        for a in sorted(PLAN_LIMITED_ALIASES)
    ],
)
def test_plan_limited_aliases_live(recorder, alias):
    """CLAUDE.md FMP-tier rule: live call for an endpoint our key may not cover."""
    _, hosted, _ = recorder
    tool, ep = alias.split("/", 1)
    res = hosted.call(tool, {"endpoint": ep})
    assert res.get("content"), alias
