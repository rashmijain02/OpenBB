"""Story widgets that are not placed on any app tab (#1274 lead decision).

Some story steps exercise widgets that exist only in the Workspace widget
gallery: no app tab places them, so a workspace run can never see them on a
dashboard. In workspace mode those steps are verified through the backend
and reported as ``GALLERY-ONLY (API-verified)``, neither OK nor FAIL. A
placed widget that is not seen is still a FAIL.
"""

from __future__ import annotations

import httpx
import pytest
from openbb_browser_test_harness.drivers.workspace_driver import api_verify_step
from openbb_browser_test_harness.report import summarize
from openbb_browser_test_harness.selectors import (
    GALLERY_ONLY,
    GALLERY_ONLY_WIDGETS,
    placed_widget_ids,
    selector_for_endpoint,
)
from openbb_browser_test_harness.steps import ActionKind, Persona, Step, StepResult
from openbb_browser_test_harness.stories import STORIES


def _story_widget_ids() -> set[str]:
    out = set()
    for story in STORIES.values():
        for step in story.steps:
            selector = selector_for_endpoint(step.endpoint) if step.endpoint else None
            if selector is not None:
                out.add(selector.widget_id)
    return out


def test_every_story_widget_is_placed_or_gallery_only() -> None:
    """Each story widget is on an app tab, or listed as gallery-only."""
    placed = placed_widget_ids()
    missing = sorted(_story_widget_ids() - placed - GALLERY_ONLY_WIDGETS)
    assert not missing, f"place these in apps.json or list them gallery-only: {missing}"


def test_gallery_only_list_has_no_placed_or_stale_widget() -> None:
    """A placed widget must be judged in the browser, never gallery-only."""
    assert not GALLERY_ONLY_WIDGETS & placed_widget_ids()
    assert _story_widget_ids() >= GALLERY_ONLY_WIDGETS


def _step(endpoint: str, expected: int = 200) -> Step:
    return Step(
        id="T.gallery",
        story="portfolio",
        notebook_ref="n/a",
        persona=Persona.ANALYST,
        tab_id="n/a",
        action=ActionKind.OBSERVE,
        human_title="t",
        human_description="d",
        human_expected="e",
        endpoint=endpoint,
        params={"symbol": "AAPL"},
        expected_status=expected,
    )


def _client(status: int, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=[{"note": "x"}])

    return httpx.AsyncClient(
        base_url="http://127.0.0.1:6120", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_api_verify_passes_on_expected_status() -> None:
    """A gallery step passes when the backend answers the expected status."""
    seen: list[httpx.Request] = []
    async with _client(200, seen) as client:
        ok, observed, error = await api_verify_step(
            client, _step("pi/equity/insider-trading")
        )
    assert ok and observed == 200 and error is None
    assert seen[0].url.path == "/pi/equity/insider-trading"
    assert seen[0].url.params["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_api_verify_fails_on_unexpected_status() -> None:
    """Any other status fails the step (never gallery-only)."""
    seen: list[httpx.Request] = []
    async with _client(500, seen) as client:
        ok, observed, error = await api_verify_step(
            client, _step("pi/equity/insider-trading")
        )
    assert not ok and observed == 500 and error and "expected_status=200" in error


def test_summary_counts_gallery_only_apart_from_ok_and_fail() -> None:
    """Reports count GALLERY-ONLY apart from OK and FAIL."""
    results = [
        StepResult("a", True, 1, None, {}),
        StepResult("b", False, 1, None, {}, error="widget_not_visible"),
        StepResult("c", True, 1, None, {}, status=GALLERY_ONLY),
        StepResult("d", False, 1, None, {}, error="gallery_api", status=None),
    ]
    assert summarize(results) == {"ok": 1, "fail": 2, "gallery_only": 1}
    assert results[2].verdict == GALLERY_ONLY
    assert results[0].verdict == "OK" and results[1].verdict == "FAIL"


def test_is_gallery_only_only_for_listed_unplaced_widgets() -> None:
    """Placed widgets stay browser-judged; listed unplaced ones are gallery-only."""
    from openbb_browser_test_harness.selectors import is_gallery_only  # noqa: PLC0415

    assert is_gallery_only("pi_charting")
    assert is_gallery_only("tt_execute_paper_status")
    assert not is_gallery_only("pi_xray_sector")
    assert not is_gallery_only("tt_segment_movers")
