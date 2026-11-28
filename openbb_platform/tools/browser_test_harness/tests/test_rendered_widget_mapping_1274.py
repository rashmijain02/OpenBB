"""Self-hosted Workspace widget mapping (#1274).

Self-hosted Workspace sets ``data-widget-id`` to a per-instance UUID, so the
old ``[data-widget-id="<backend id>"]`` selector matched nothing and every
workspace step reported ``widget_visible=False`` while still printing OK.
These pure-Python tests (no Playwright) run the mapping on a synthetic DOM
captured from the pinned Workspace markup
(``fixtures/workspace_dom_selfhosted.html``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openbb_browser_test_harness.drivers.workspace_driver import step_verdict
from openbb_browser_test_harness.run import (
    STORY_APPS,
    build_parser,
    workspace_driver_kwargs,
)
from openbb_browser_test_harness.selectors import (
    RENDERED_WIDGETS_JS,
    RenderedWidget,
    container_selector,
    judge_rendered,
    load_endpoint_to_widget_selector,
    load_widget_tabs,
    match_rendered,
    parse_rendered_widgets,
    selector_for_endpoint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "workspace_dom_selfhosted.html"


@pytest.fixture(scope="module", name="rendered")
def _rendered() -> list[RenderedWidget]:
    return parse_rendered_widgets(FIXTURE.read_text(encoding="utf-8"))


def _sel(endpoint: str):
    selector = selector_for_endpoint(endpoint)
    assert selector is not None
    return selector


def test_fixture_has_uuid_grid_items_only(rendered: list[RenderedWidget]) -> None:
    """The old id selector cannot match: every data-widget-id is a UUID."""
    assert len(rendered) == 5
    backend_ids = set(load_endpoint_to_widget_selector().values())
    for item in rendered:
        assert len(item.uid) == 36 and item.uid.count("-") == 4
        assert container_selector(item.uid) not in {s.container for s in backend_ids}


def test_chart_with_plot_is_matched_by_card_class_and_not_blank(
    rendered: list[RenderedWidget],
) -> None:
    """A rendered chart maps by its card class and has a mounted plot."""
    selector = _sel("pi/xray/sector")
    item, how = match_rendered(selector, rendered)
    assert how == "card-class" and item is not None
    assert item.uid.startswith("3f0c9a52")
    assert judge_rendered(selector, item) == (True, True)
    assert step_verdict(selector, True, True) == (True, None)


def test_blank_chart_frame_is_visible_but_blank_and_fails(
    rendered: list[RenderedWidget],
) -> None:
    """A ``data: []`` chart shows a frame (navbar icons) but no plot: FAIL."""
    selector = _sel("tt/scan/segment-movers")
    item, how = match_rendered(selector, rendered)
    assert how == "card-class"
    visible, not_blank = judge_rendered(selector, item)
    assert (visible, not_blank) == (True, False)
    ok, error = step_verdict(selector, visible, not_blank)
    assert not ok and error and error.startswith("widget_blank")


def test_spinning_table_is_blank(rendered: list[RenderedWidget]) -> None:
    """Navbar params are not table content; no grid in the body means blank."""
    selector = _sel("pi/equity/analyst-forecasts")
    item, _how = match_rendered(selector, rendered)
    assert judge_rendered(selector, item) == (True, False)


def test_title_fallback_matches_exact_normalized_name(
    rendered: list[RenderedWidget],
) -> None:
    """Without the card class the exact (whitespace-normalised) title maps."""
    selector = _sel("pi/equity/key-stats")
    item, how = match_rendered(selector, rendered)
    assert how == "title" and item is not None
    assert judge_rendered(selector, item) == (True, True)


def test_zero_box_widget_is_not_visible(rendered: list[RenderedWidget]) -> None:
    """A widget on a hidden tab (zero box) is not visible."""
    selector = _sel("pi/context/provenance")
    item, how = match_rendered(selector, rendered)
    assert how == "card-class"
    assert judge_rendered(selector, item) == (False, False)


def test_absent_widget_is_unseen_and_fails_for_every_action(
    rendered: list[RenderedWidget],
) -> None:
    """An unseen widget is a FAIL, never an OK (was OK for non-ASSERT steps)."""
    selector = _sel("pi/health/providers")
    item, how = match_rendered(selector, rendered)
    assert (item, how) == (None, "none")
    visible, not_blank = judge_rendered(selector, item)
    ok, error = step_verdict(selector, visible, not_blank)
    assert not ok and error and error.startswith("widget_not_visible")


def test_steps_without_a_widget_have_no_widget_verdict() -> None:
    """Chrome and navigation steps carry no widget verdict."""
    assert step_verdict(None, "n/a", "n/a") == (True, None)


def test_legacy_backend_id_attribute_still_matches() -> None:
    """Hosted builds that put the backend id in data-widget-id still map."""
    selector = _sel("pi/xray/sector")
    item, how = match_rendered(
        selector, [RenderedWidget(uid="pi_xray_sector", width=10, height=10)]
    )
    assert how == "data-widget-id" and item is not None


def test_live_dom_reader_uses_the_same_markers() -> None:
    """The browser-side reader keys on the markers the parser models."""
    for marker in (
        "[data-widget-id]",
        "widget-",
        "._left-navbar p.font-semibold",
        '[id^="widget-content-"]',
        ".js-plotly-plot",
        "svg.main-svg",
        ".ag-root",
    ):
        assert marker in RENDERED_WIDGETS_JS, marker


def test_record_round_trip() -> None:
    """A browser record becomes a RenderedWidget unchanged."""
    record = {
        "uid": "u",
        "widget_ids": ["pi_x"],
        "title": "T",
        "width": 1.5,
        "height": 2,
        "body_text": 3,
        "plots": 1,
        "tables": 0,
    }
    item = RenderedWidget.from_record(record)
    assert item.widget_ids == ("pi_x",) and item.width == 1.5 and item.plots == 1


def test_widget_tabs_cover_story_apps() -> None:
    """Every story app has a widget -> tab map from apps.json."""
    tabs = load_widget_tabs()
    for app in STORY_APPS.values():
        assert tabs.get(app), app
    assert tabs["Techtrade Trading Desk"]["tt_segment_movers"].startswith("T1")


def test_cli_flags_reach_the_workspace_driver(tmp_path: Path) -> None:
    """The workspace CLI flags become WorkspaceDriver arguments."""
    args = build_parser().parse_args(
        [
            "--story",
            "techtrade",
            "--mode",
            "workspace",
            "--workspace-url",
            "http://127.0.0.1:1420",
            "--backend-url",
            "http://127.0.0.1:6120",
            "--headless",
            "--profile-dir",
            str(tmp_path),
            "--dashboard",
            "Techtrade Trading Desk",
            "--managed-credentials",
            str(tmp_path / "creds.secrets"),
        ]
    )
    kwargs = workspace_driver_kwargs(args)
    assert kwargs == {
        "mode": "persistent-context",
        "app_name": "Techtrade Trading Desk",
        "workspace_url": "http://127.0.0.1:1420",
        "backend_url": "http://127.0.0.1:6120",
        "headless": True,
        "profile_dir": tmp_path,
        "dashboard_name": "Techtrade Trading Desk",
        "managed_credentials_path": tmp_path / "creds.secrets",
    }


def test_cli_headed_and_defaults() -> None:
    """--headed sets headless off; unset flags keep the driver defaults."""
    headed = build_parser().parse_args(["--story", "portfolio", "--headed"])
    assert workspace_driver_kwargs(headed)["headless"] is False
    default = build_parser().parse_args(["--story", "portfolio"])
    kwargs = workspace_driver_kwargs(default)
    assert "headless" not in kwargs and "backend_url" not in kwargs
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--story", "portfolio", "--headless", "--headed"])


def test_profile_dir_inside_the_repository_is_refused(tmp_path: Path) -> None:
    """A logged-in browser profile must never live in the checkout (PRIVACY-2)."""
    from openbb_browser_test_harness.drivers.workspace_driver import (  # noqa: PLC0415
        WorkspaceDriver,
        WorkspaceDriverError,
    )

    repo = Path(__file__).resolve().parents[4]
    with pytest.raises(WorkspaceDriverError, match="outside the repository"):
        WorkspaceDriver(profile_dir=repo / ".dev-cycle" / "tmp" / "chrome_profile")
    assert (
        WorkspaceDriver(profile_dir=tmp_path / "profile").profile_dir.name == "profile"
    )


class _LazyGridPage:
    """Fake page whose grid items mount only after they are scrolled into view.

    Self-hosted Workspace (re-run evidence, 1280x720) mounts the card of an
    off-screen grid item only when it scrolls on screen; until then the item
    has no ``widget-<id>`` class, title or body.
    """

    def __init__(self, cards: dict[str, tuple[str, str]]) -> None:
        self.cards = cards  # uid -> (backend id, title)
        self.mounted: set[str] = set()
        self.scrolled: list[str] = []
        self.viewport: dict | None = None

    async def evaluate(self, _source: str) -> list[dict]:
        out = []
        for uid, (wid, title) in self.cards.items():
            live = uid in self.mounted
            out.append(
                {
                    "uid": uid,
                    "widget_ids": [wid] if live else [],
                    "title": title if live else "",
                    "width": 600,
                    "height": 300,
                    "body_text": 40 if live else 0,
                    "plots": 1 if live else 0,
                    "tables": 1 if live else 0,
                }
            )
        return out

    def locator(self, selector: str) -> _LazyGridPage._Loc:
        return _LazyGridPage._Loc(self, selector)

    class _Loc:
        def __init__(self, page: _LazyGridPage, selector: str) -> None:
            self.page, self.selector = page, selector

        @property
        def first(self) -> _LazyGridPage._Loc:
            return self

        async def scroll_into_view_if_needed(self, **_kwargs: object) -> None:
            uid = self.selector.split('"')[1]
            self.page.scrolled.append(uid)
            self.page.mounted.add(uid)


def _lazy_driver(page: _LazyGridPage, tmp_path: Path):
    from openbb_browser_test_harness.drivers.workspace_driver import (  # noqa: PLC0415
        WorkspaceDriver,
    )

    driver = WorkspaceDriver(profile_dir=tmp_path / "p", widget_settle_s=0.0)
    driver._page = page  # pylint: disable=protected-access
    return driver


@pytest.mark.asyncio
async def test_off_screen_widget_is_scrolled_into_view_and_judged(
    tmp_path: Path,
) -> None:
    """An unmounted grid item is scrolled on screen, then matched and judged."""
    page = _LazyGridPage(
        {
            "u-1": ("pi_symbol_context", "Symbol Context Bar"),
            "u-2": ("pi_xray_sector", "X-Ray - Sector Weights"),
        }
    )
    driver = _lazy_driver(page, tmp_path)
    selector = _sel("pi/xray/sector")
    item, how = await driver._await_widget(selector)  # pylint: disable=protected-access
    assert how == "card-class" and item is not None and item.uid == "u-2"
    assert "u-2" in page.scrolled
    assert judge_rendered(selector, item) == (True, True)


@pytest.mark.asyncio
async def test_widget_absent_after_scrolling_every_item_still_fails(
    tmp_path: Path,
) -> None:
    """Scrolling never turns an absent widget into an OK."""
    page = _LazyGridPage({"u-1": ("pi_symbol_context", "Symbol Context Bar")})
    driver = _lazy_driver(page, tmp_path)
    selector = _sel("pi/xray/sector")
    item, how = await driver._await_widget(selector)  # pylint: disable=protected-access
    assert (item, how) == (None, "none")
    assert step_verdict(selector, *judge_rendered(selector, item))[0] is False


def test_driver_default_viewport_is_large() -> None:
    """The default viewport mounts more cards than Playwright's 1280x720."""
    from openbb_browser_test_harness.drivers.workspace_driver import (  # noqa: PLC0415
        WorkspaceDriver,
    )

    viewport = WorkspaceDriver().viewport
    assert viewport and viewport["width"] >= 1600 and viewport["height"] >= 1200


class _HeaderOnlyPage(_LazyGridPage):
    """Cards show their header off screen but mount the body only on screen."""

    async def evaluate(self, source: str) -> list[dict]:
        out = await super().evaluate(source)
        for record in out:
            wid, title = self.cards[record["uid"]]
            record["widget_ids"], record["title"] = [wid], title
        return out


@pytest.mark.asyncio
async def test_matched_widget_is_scrolled_into_view_before_judging(
    tmp_path: Path,
) -> None:
    """A matched card whose body is not mounted is scrolled on screen first."""
    page = _HeaderOnlyPage({"u-9": ("tt_segment_movers", "Techtrade - Segment Movers")})
    driver = _lazy_driver(page, tmp_path)
    selector = _sel("tt/scan/segment-movers")
    item, how = await driver._await_widget(selector)  # pylint: disable=protected-access
    assert how == "card-class" and page.scrolled == ["u-9"]
    assert judge_rendered(selector, item) == (True, True)
