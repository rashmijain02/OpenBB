"""Playwright workspace driver (B6, #1728).

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5.2

Two attach mechanisms (P0-1 fix from spec review):

- **persistent-context (default)** — ``chromium.launch_persistent_context`` against
  ``~/.openbb_browser_test_harness/chrome_profile/``. First-run opens a browser
  for the user to log in to pro.openbb.co; auth persists across runs via cookies.
- **cdp-attach** — user launches Chrome with ``--remote-debugging-port=9222``;
  driver calls ``chromium.connect_over_cdp("http://127.0.0.1:9222")``. Driver does
  not manage the browser lifecycle.

**Screenshot policy (P1-4):** ``page.screenshot()`` only — never OS-level capture.
Browser chrome (tab title, URL bar, taskbar) is outside the frame by construction.
Each screenshot's SHA-256 is recorded in ``StepResult.screenshot_sha256`` for
future baseline-diff (P2-10).

**Import guard:** Playwright is an optional dependency (extras=[workspace]). If
someone imports this module without playwright installed, they get a clear
``ImportError`` rather than a mysterious NameError at runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..redact import assert_screenshot_clean
from ..selectors import (
    GALLERY_ONLY,
    RENDERED_WIDGETS_JS,
    RenderedWidget,
    WidgetSelector,
    is_gallery_only,
    judge_rendered,
    load_widget_tabs,
    match_rendered,
    selector_for_endpoint,
)
from ..steps import ActionKind, Step, StepResult

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright


#: Checkout root (``src/openbb_browser_test_harness/drivers`` -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[6]


class WorkspaceDriverError(RuntimeError):
    """Raised on setup or mode-selection failures."""


def _default_profile_dir() -> Path:
    """Chrome profile lives under ~/.openbb_browser_test_harness/chrome_profile/.

    Matches the ``portfolio_export`` chrome profile pattern from CLAUDE.md so
    users have a single conceptual location for browser state.
    """
    return Path.home() / ".openbb_browser_test_harness" / "chrome_profile"


def _is_local_workspace_url(url: str) -> bool:
    """Return whether *url* is the exact supported self-hosted base URL."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "http"
        and parsed.netloc == "127.0.0.1:1420"
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_authenticated_workspace_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "http"
        and parsed.netloc == "127.0.0.1:1420"
        and (parsed.path == "/app" or parsed.path.startswith("/app/"))
    )


def _require_local_workspace_origin(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.netloc != "127.0.0.1:1420":
        raise WorkspaceDriverError(
            "Managed login refused because the live page left the exact "
            "self-hosted Workspace origin."
        )


def _default_managed_credentials_path() -> Path:
    return (
        Path.cwd()
        / "third_party"
        / "workspace"
        / "backend-api"
        / "backend"
        / "workspace-admin-credentials.secrets"
    )


def _read_managed_credentials(path: Path) -> tuple[str, str]:
    """Read the ignored setup-managed credential file without logging values."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkspaceDriverError(
            "Unable to read the managed credential file for local Workspace."
        ) from exc
    email = payload.get("Email") if isinstance(payload, dict) else None
    password = payload.get("Password") if isinstance(payload, dict) else None
    if (
        not isinstance(email, str)
        or not email
        or not isinstance(password, str)
        or not password
    ):
        raise WorkspaceDriverError(
            "The managed credential file for local Workspace has an invalid shape."
        )
    return email, password


def _pick_random_port() -> int:
    """Ask the kernel for a free ephemeral 127.0.0.1 port.

    Uses the classic ``bind((127.0.0.1, 0))`` trick so concurrent workspace
    runs never collide with each other, and never collide with a manual
    ``openbb.sh api`` session on the fixed port 8000. See #1789.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class WorkspaceDriver:
    """Playwright driver for the OpenBB Workspace UI at pro.openbb.co.

    Usage::

        driver = WorkspaceDriver(mode="persistent-context")
        await driver.setup()   # prompts user for first-run login if needed
        for step in story.steps:
            result = await driver.run_step(step)
        await driver.teardown()
    """

    mode: str = "persistent-context"  # or "cdp-attach"
    workspace_url: str = "https://pro.openbb.co"
    cdp_endpoint: str = "http://127.0.0.1:9222"
    profile_dir: Path = field(default_factory=_default_profile_dir)
    screenshots_dir: Path | None = None  # if None, screenshots aren't saved
    headless: bool = False  # persistent-context defaults to visible for login
    ignore_local_self_hosted_https_errors: bool = False
    managed_credentials_path: Path = field(
        default_factory=_default_managed_credentials_path
    )
    login_timeout_ms: float = 30_000
    #: Workspace app (``apps.json`` name) whose tabs the driver opens to find
    #: a step's widget (#1274). ``None`` checks only the current page.
    app_name: str | None = None
    #: Dashboard (its visible name) to open after login (#1274). ``None``
    #: leaves the landing page as is.
    dashboard_name: str | None = None
    #: How long a step waits for its widget to render (seconds, #1274).
    widget_settle_s: float = 15.0
    #: Browser viewport (#1274 re-run): Workspace mounts only on-screen cards,
    #: and Playwright's 1280x720 default leaves most of a tab unmounted. Each
    #: widget is also scrolled into view before it is judged.
    viewport: dict[str, int] | None = field(
        default_factory=lambda: {"width": 1600, "height": 1200}
    )

    #: If None, spawn a fresh uvicorn on a random ephemeral 127.0.0.1 port
    #: (#1789). If set, attach to an existing backend.
    backend_url: str | None = None
    #: Timeout for the backend readiness probe (seconds).
    backend_readiness_timeout_s: float = 60.0
    #: Timeout for each step (currently informational, mirrors standalone).
    step_timeout_s: float = 10.0

    # Populated in setup()
    _playwright: Playwright | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _page: Page | None = field(default=None, init=False, repr=False)
    _owns_context: bool = field(default=False, init=False, repr=False)
    #: True iff setup() spawned the backend (so teardown() must kill it).
    _spawn_backend: bool = field(default=False, init=False, repr=False)
    _backend_proc: asyncio.subprocess.Process | None = field(
        default=None, init=False, repr=False
    )
    _resolved_backend_url: str | None = field(default=None, init=False, repr=False)
    login_performed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Record spawn-vs-attach mode at construction (#1789)."""
        if self.ignore_local_self_hosted_https_errors and not _is_local_workspace_url(
            self.workspace_url
        ):
            raise WorkspaceDriverError(
                "Development TLS bypass is permitted only for the exact "
                "self-hosted Workspace URL."
            )
        self._spawn_backend = self.backend_url is None
        self._resolved_backend_url = self.backend_url
        # A profile holds a logged-in session; it must never be committable
        # (#1274 review PRIVACY-2).
        repo = _REPO_ROOT.resolve()
        profile = Path(self.profile_dir).expanduser().resolve()
        if profile == repo or repo in profile.parents:
            raise WorkspaceDriverError(
                "The browser profile must live outside the repository "
                "(default ~/.openbb_browser_test_harness/chrome_profile)."
            )

    async def _spawn_widget_backend(self) -> str:
        """Spawn uvicorn on a random ephemeral port; return the base URL.

        Polls ``/widgets.json`` for up to ``backend_readiness_timeout_s``.
        """
        import httpx  # local import: httpx is a runtime dep of the harness

        port = _pick_random_port()
        base_url = f"http://127.0.0.1:{port}"
        child_env = os.environ.copy()
        child_env.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")
        self._backend_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "openbb_portfolio_intel.widget_backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        deadline = time.monotonic() + self.backend_readiness_timeout_s
        async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
            while time.monotonic() < deadline:
                if self._backend_proc.returncode is not None:
                    raise WorkspaceDriverError(
                        f"widget_backend exited with code "
                        f"{self._backend_proc.returncode} during setup."
                    )
                try:
                    resp = await client.get("/widgets.json")
                    if resp.status_code == 200:
                        return base_url
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    pass
                await asyncio.sleep(0.2)
        raise WorkspaceDriverError(
            f"widget_backend did not become ready in "
            f"{self.backend_readiness_timeout_s}s (port={port})"
        )

    async def setup(self) -> None:
        """Attach to Chromium via the chosen mechanism.

        For persistent-context mode: opens a browser window; on first run the
        user must log in to Workspace, then rerun. Cookies persist for future
        runs.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkspaceDriverError(
                "Playwright not installed. Install harness with the workspace "
                "extra: `pip install -e "
                "openbb_platform/tools/browser_test_harness/[workspace]` "
                "and then `playwright install chromium`."
            ) from exc

        self._playwright = await async_playwright().start()

        # Resolve backend_url — spawn a fresh uvicorn on a random port if the
        # caller did not provide one (#1789). Attach mode otherwise.
        if self._spawn_backend:
            self._resolved_backend_url = await self._spawn_widget_backend()

        if self.mode == "persistent-context":
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                ignore_https_errors=self.ignore_local_self_hosted_https_errors,
            )
            self._owns_context = True
        elif self.mode == "cdp-attach":
            browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_endpoint
            )
            if not browser.contexts:
                raise WorkspaceDriverError(
                    "CDP attach: no browser contexts found. Ensure Chrome is "
                    f"running with --remote-debugging-port at {self.cdp_endpoint}."
                )
            self._context = browser.contexts[0]
            self._owns_context = False
        else:
            raise WorkspaceDriverError(
                f"Unknown mode {self.mode!r} — use 'persistent-context' or 'cdp-attach'."
            )

        # Open a page and navigate to Workspace, appending backend_url so the
        # Workspace UI knows where to send widget requests (#1789).
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        if self.viewport:
            await self._page.set_viewport_size(self.viewport)
        target_url = self.workspace_url
        if self._resolved_backend_url:
            sep = "&" if "?" in target_url else "?"
            target_url = f"{target_url}{sep}backend_url={self._resolved_backend_url}"
        await self._page.goto(target_url, wait_until="load")
        if _is_local_workspace_url(self.workspace_url):
            _require_local_workspace_origin(self._page.url)
            await self._ensure_local_login()
        # Wait for the widget grid selector, or fall through after 5s — the
        # grid may not exist on every route (e.g. login redirect page).
        with contextlib.suppress(Exception):
            await self._page.wait_for_selector(
                '[data-testid="widget-grid"]', timeout=5000
            )
        if self.dashboard_name:
            await self._open_dashboard(self.dashboard_name)

    async def _open_dashboard(self, name: str) -> None:
        """Close a start-up dialog, then open the named dashboard (#1274)."""
        assert self._page is not None
        dialog = self._page.get_by_role("dialog")
        # A missing or already-closed dialog is fine.
        with contextlib.suppress(Exception):
            if await dialog.count():
                await dialog.get_by_role("button", name="Close").click()
        link = self._page.get_by_text(name, exact=True).first
        try:
            await link.click(timeout=self.login_timeout_ms)
        except Exception as exc:
            raise WorkspaceDriverError(
                f"Workspace dashboard {name!r} was not found."
            ) from exc
        await self._page.wait_for_selector(
            "[data-widget-id]", timeout=self.login_timeout_ms
        )

    async def _ensure_local_login(self) -> None:
        """Log into local Workspace only when the persisted profile needs it."""
        assert self._page is not None
        _require_local_workspace_origin(self._page.url)
        if _is_authenticated_workspace_url(self._page.url):
            self.login_performed = False
            return

        email_input = self._page.get_by_label("Email", exact=True)
        login_ready = asyncio.create_task(
            email_input.wait_for(state="attached", timeout=0)
        )
        authenticated = asyncio.create_task(
            self._page.wait_for_url(
                lambda url: _is_authenticated_workspace_url(str(url)),
                timeout=0,
            )
        )
        done, pending = await asyncio.wait(
            {login_ready, authenticated},
            timeout=self.login_timeout_ms / 1000,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            raise WorkspaceDriverError(
                "Local Workspace did not reach a login or authenticated route."
            )
        _require_local_workspace_origin(self._page.url)
        if _is_authenticated_workspace_url(self._page.url):
            self.login_performed = False
            return
        if await email_input.count() == 0:
            raise WorkspaceDriverError(
                "Local Workspace did not expose the expected login form."
            )

        _require_local_workspace_origin(self._page.url)
        email, password = _read_managed_credentials(self.managed_credentials_path)
        _require_local_workspace_origin(self._page.url)
        await email_input.fill(email)
        _require_local_workspace_origin(self._page.url)
        await self._page.get_by_label("Password", exact=True).fill(password)
        await self._page.get_by_role("button", name="Login", exact=True).click()
        try:
            await self._page.wait_for_url(
                lambda url: _is_authenticated_workspace_url(str(url)),
                timeout=self.login_timeout_ms,
            )
        except Exception as exc:
            raise WorkspaceDriverError(
                "Local Workspace managed login did not complete."
            ) from exc
        _require_local_workspace_origin(self._page.url)
        if not _is_authenticated_workspace_url(self._page.url):
            raise WorkspaceDriverError(
                "Local Workspace managed login reached an unexpected route."
            )
        self.login_performed = True

    async def teardown(self) -> None:
        """Close the page/context if we own them; otherwise leave them alive.

        In cdp-attach mode the user's browser keeps running.
        """
        if self._context is not None and self._owns_context:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        if self._playwright is not None:
            await self._playwright.stop()
        # Terminate the spawned uvicorn if we own it (#1789).
        if self._spawn_backend and self._backend_proc is not None:
            if self._backend_proc.returncode is None:
                try:
                    self._backend_proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self._backend_proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._backend_proc.kill()
                    await self._backend_proc.wait()
        self._backend_proc = None
        self._context = None
        self._page = None
        self._playwright = None
        self._owns_context = False

    async def run_step(self, step: Step) -> StepResult:
        """Execute one step against the live Workspace UI.

        Screenshots the page, computes SHA-256, redacts the path, then
        (for steps with an endpoint) finds the backend widget on the page
        (#1274): it opens the ``app_name`` tab that holds the widget, reads
        the rendered grid items (``selectors.RENDERED_WIDGETS_JS``) and maps
        the backend id to one by the ``widget-<id>`` card class, a legacy
        ``data-widget-id``, or the exact title.

        - ``widget_visible``: a matched item with a non-zero box.
        - ``not_blank``: type-appropriate body content (a mounted plot for a
          chart, a grid for a table, body text for markdown/metric).

        A step whose endpoint backs a widget fails when the widget is unseen
        or blank, whatever its action (:func:`step_verdict`). Steps with no
        widget (chrome / navigation) carry ``"n/a"`` observations.
        """
        if self._page is None:
            return StepResult(
                step_id=step.id,
                ok=False,
                duration_ms=0,
                screenshot_path=None,
                observations={},
                error="workspace_not_setup",
            )

        start = time.monotonic()

        # Find the step's widget first (opening its tab), so the screenshot
        # shows what was judged (#1274).
        selector: WidgetSelector | None = None
        if step.endpoint:
            selector = selector_for_endpoint(step.endpoint)
        rendered: RenderedWidget | None = None
        matched_by = "n/a"
        tab: str | None = None
        gallery = selector is not None and is_gallery_only(selector.widget_id)
        if selector is not None and not gallery:
            tab = await self._open_widget_tab(selector)
            rendered, matched_by = await self._await_widget(selector)

        # Screenshot capture — page.screenshot() only, no OS-level grab.
        screenshot_path: str | None = None
        screenshot_sha: str | None = None
        if self.screenshots_dir is not None:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            out = self.screenshots_dir / step.resolved_screenshot_name
            # PII guard on the OUTPUT PATH before we let Playwright write it.
            assert_screenshot_clean(out)
            png_bytes = await self._page.screenshot(
                path=str(out),
                type="png",
                full_page=False,  # viewport only per P1-4 (page-scoped)
            )
            screenshot_path = str(out)
            screenshot_sha = hashlib.sha256(png_bytes).hexdigest()
        else:
            # No output dir — capture bytes to compute SHA but don't save.
            png_bytes = await self._page.screenshot(
                type="png",
                full_page=False,
            )
            screenshot_sha = hashlib.sha256(png_bytes).hexdigest()

        widget_visible: object = "n/a"
        not_blank: object = "n/a"
        if selector is not None and not gallery:
            widget_visible, not_blank = judge_rendered(selector, rendered)

        duration_ms = int((time.monotonic() - start) * 1000)

        observations: dict[str, object] = {
            "widget_visible": widget_visible,
            "not_blank": not_blank,
            "screenshot_bytes": len(png_bytes),
        }
        if selector is not None:
            observations["widget_id"] = selector.widget_id
            observations["widget_type"] = selector.widget_type
            observations["matched_by"] = matched_by
            observations["tab"] = tab or "current"
        if step.action == ActionKind.NAVIGATE:
            observations["current_url"] = self._page.url

        status: str | None = None
        if gallery:
            # No app tab places this widget (#1274 lead decision): verify the
            # story step through the backend; never claim it was seen.
            ok, observed, error = await self._api_verify(step)
            observations["gallery_only"] = True
            observations["api_status_code"] = observed
            status = GALLERY_ONLY if ok else None
        else:
            ok, error = step_verdict(selector, widget_visible, not_blank)

        return StepResult(
            step_id=step.id,
            ok=ok,
            duration_ms=duration_ms,
            screenshot_path=screenshot_path,
            observations=observations,
            error=error,
            screenshot_sha256=screenshot_sha,
            status=status,
        )

    async def _api_verify(self, step: Step) -> tuple[bool, int | None, str | None]:
        """Call the step's endpoint on the widget backend (gallery-only steps)."""
        import httpx  # pylint: disable=import-outside-toplevel

        if not self._resolved_backend_url:
            return False, None, "gallery_only_api: no backend URL"
        async with httpx.AsyncClient(
            base_url=self._resolved_backend_url, timeout=self.step_timeout_s * 3
        ) as client:
            return await api_verify_step(client, step)

    async def _rendered_widgets(self) -> list[RenderedWidget]:
        """Read one record per rendered grid item from the live DOM."""
        assert self._page is not None
        try:
            records = await self._page.evaluate(RENDERED_WIDGETS_JS)
        except Exception:  # noqa: BLE001 — a failed read is "nothing rendered"
            return []
        return [RenderedWidget.from_record(r) for r in records or []]

    async def _open_widget_tab(self, selector: WidgetSelector) -> str | None:
        """Open the ``app_name`` tab that holds the widget; return its name.

        Best effort: when no app is configured, the widget is not in the
        app's layout, or the tab button is absent, the current page is
        judged as is (an unseen widget then fails the step).
        """
        assert self._page is not None
        if not self.app_name:
            return None
        tab = load_widget_tabs().get(self.app_name, {}).get(selector.widget_id)
        if not tab:
            return None
        button = self._page.get_by_role("button", name=tab, exact=True).first
        try:
            if await button.count():
                await button.click()
        except Exception:  # noqa: BLE001 — judged on the current page
            return tab
        return tab

    async def _await_widget(
        self, selector: WidgetSelector
    ) -> tuple[RenderedWidget | None, str]:
        """Find, scroll into view and poll the widget until it renders content.

        Workspace mounts a card only when its grid item is on screen, so an
        unmatched widget is searched for by scrolling every not-yet-mounted
        grid item into view once (#1274 re-run). A matched widget is scrolled
        into view before it is judged. A widget still unmatched after the
        scan stays unseen, which fails the step.
        """
        assert self._page is not None
        deadline = time.monotonic() + self.widget_settle_s
        scanned = False
        scrolled: set[str] = set()
        while True:
            items = await self._rendered_widgets()
            item, how = match_rendered(selector, items)
            if item is None and not scanned:
                scanned = True
                item, how = await self._scan_for_widget(selector, items, scrolled)
            if item is not None and item.uid not in scrolled:
                await self._scroll_into_view(item.uid)
                scrolled.add(item.uid)
                item, how = match_rendered(selector, await self._rendered_widgets())
            visible, not_blank = judge_rendered(selector, item)
            if (visible and not_blank) or time.monotonic() >= deadline:
                return item, how
            await asyncio.sleep(0.5)

    async def _scroll_into_view(self, uid: str) -> None:
        """Scroll one grid item on screen so Workspace mounts its card."""
        assert self._page is not None
        safe = uid.replace('"', r"\"")
        with contextlib.suppress(Exception):
            await self._page.locator(
                f'[data-widget-id="{safe}"]'
            ).first.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.3)

    async def _scan_for_widget(
        self,
        selector: WidgetSelector,
        items: list[RenderedWidget],
        scrolled: set[str],
    ) -> tuple[RenderedWidget | None, str]:
        """Scroll each unmounted grid item into view until the widget matches."""
        for pending in items:
            if pending.widget_ids or pending.title or pending.uid in scrolled:
                continue
            await self._scroll_into_view(pending.uid)
            scrolled.add(pending.uid)
            item, how = match_rendered(selector, await self._rendered_widgets())
            if item is not None:
                return item, how
        return None, "none"


async def api_verify_step(
    client: Any, step: Step
) -> tuple[bool, int | None, str | None]:
    """Return ``(ok, status_code, error)`` for one step called on the backend.

    Passes when the endpoint answers the step's ``expected_status``. The body
    is not echoed (it can hold widget data); only the status is reported.
    """
    path = step.endpoint or ""
    path = path if path.startswith("/") else f"/{path}"
    try:
        response = await client.get(path, params=step.params)
    except Exception as exc:  # noqa: BLE001 - any transport failure fails the step
        return False, None, f"gallery_only_api: {type(exc).__name__}"
    if response.status_code != step.expected_status:
        return (
            False,
            response.status_code,
            (
                f"gallery_only_api: expected_status={step.expected_status} "
                f"got_status={response.status_code}"
            ),
        )
    return True, response.status_code, None


def step_verdict(
    selector: WidgetSelector | None, widget_visible: object, not_blank: object
) -> tuple[bool, str | None]:
    """Return ``(ok, error)`` for a workspace step (#1274).

    A step whose endpoint backs a widget passes only when that widget is
    seen on the page and is not blank, whatever the step's action: an
    unseen widget is a FAIL, never an OK. Steps without a widget (chrome,
    navigation, non-widget endpoints) carry no widget verdict.
    """
    if selector is None:
        return True, None
    if widget_visible is not True:
        return False, (
            f"widget_not_visible: widget={selector.widget_id} "
            f"title={selector.name!r}"
        )
    if not_blank is not True:
        return False, (
            f"widget_blank: widget={selector.widget_id} type={selector.widget_type}"
        )
    return True, None
