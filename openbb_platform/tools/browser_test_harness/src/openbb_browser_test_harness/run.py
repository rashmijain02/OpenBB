"""CLI entrypoint — ``python -m openbb_browser_test_harness.run --story portfolio``.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .drivers import (
    _WORKSPACE_AVAILABLE,
    HarnessSetupError,
    StandaloneDriver,
    WorkspaceDriver,
)
from .report import summarize, write_report_json, write_report_md
from .steps import Step, StepResult
from .stories import STORIES

#: Workspace app whose tabs hold each story's widgets (``apps.json`` names).
STORY_APPS: dict[str, str] = {
    "portfolio": "Portfolio Intelligence - Terminal",
    "techtrade": "Techtrade Trading Desk",
}


def workspace_driver_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """Return the ``WorkspaceDriver`` keyword arguments the CLI flags set (#1274).

    Unset flags are left out so the driver defaults apply.
    """
    kwargs: dict[str, object] = {
        "mode": args.workspace_mode,
        "app_name": args.app_name or STORY_APPS.get(args.story),
    }
    if args.workspace_url:
        kwargs["workspace_url"] = args.workspace_url
    if args.backend_url:
        kwargs["backend_url"] = args.backend_url
    if args.headless is not None:
        kwargs["headless"] = args.headless
    if args.profile_dir is not None:
        kwargs["profile_dir"] = args.profile_dir
    if args.dashboard:
        kwargs["dashboard_name"] = args.dashboard
    if args.managed_credentials is not None:
        kwargs["managed_credentials_path"] = args.managed_credentials
    return kwargs


async def _run_story(  # pylint: disable=too-many-locals
    story_id: str,
    mode: str,
    out_dir: Path,
    capture_guide_screenshots: bool,
    driver_kwargs: dict[str, object] | None = None,
) -> int:
    story = STORIES[story_id]
    steps_by_id: dict[str, Step] = {s.id: s for s in story.steps}

    driver: object
    if mode == "standalone":
        # Extended step_timeout for endpoints that hit live fmp_cached
        # (e.g. pi/equity/analyst-forecasts).
        driver = StandaloneDriver(step_timeout_s=30.0)
    elif mode == "workspace":
        if not _WORKSPACE_AVAILABLE:
            print(
                "workspace mode requires playwright. Install with:\n"
                "  pip install -e "
                "openbb_platform/tools/browser_test_harness/[workspace]\n"
                "  python -m playwright install chromium",
                file=sys.stderr,
            )
            return 2
        assert WorkspaceDriver is not None
        # If --capture-guide-screenshots is set, save PNGs into the guides/
        # tree so B5's manual guide auto-populates them.
        screenshots_dir: Path | None = None
        if capture_guide_screenshots:
            screenshots_dir = (
                Path(__file__).resolve().parents[2]
                / "guides"
                / "screenshots"
                / story_id
            )
        driver = WorkspaceDriver(
            screenshots_dir=screenshots_dir,
            **(driver_kwargs or {}),  # type: ignore[arg-type]
        )
    else:
        print(f"Unknown mode {mode!r}", file=sys.stderr)
        return 2

    try:
        await driver.setup()  # type: ignore[attr-defined]
    except HarnessSetupError as exc:
        print(f"Harness setup failed: {exc}", file=sys.stderr)
        return 3

    results: list[StepResult] = []
    try:
        for step in story.steps:
            result = await driver.run_step(step)  # type: ignore[attr-defined]
            status = result.verdict
            print(f"  [{status}] {step.id} - {result.duration_ms}ms")
            results.append(result)
    finally:
        await driver.teardown()  # type: ignore[attr-defined]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_report_md(out_dir / "report.md", story, results, steps_by_id)
    write_report_json(out_dir / "report.json", story, results, steps_by_id)

    counts = summarize(results)
    failed = counts["fail"]
    print(
        f"\n{len(results)} steps: {counts['ok']} OK, {failed} FAIL, "
        f"{counts['gallery_only']} GALLERY-ONLY (API-verified)"
    )
    print(f"Reports written to {out_dir.resolve()}")

    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="openbb-browser-harness",
        description="Run the browser test harness against the portfolio or techtrade Workspace app.",
    )
    parser.add_argument(
        "--story",
        choices=list(STORIES.keys()),
        required=True,
        help="Which story to run.",
    )
    parser.add_argument(
        "--mode",
        choices=["standalone", "workspace"],
        default="standalone",
        help="standalone = HTTP-only (default, CI-friendly); workspace = Playwright.",
    )
    parser.add_argument(
        "--workspace-mode",
        choices=["persistent-context", "cdp-attach"],
        default="persistent-context",
        help="How Playwright attaches to Chrome (workspace mode only).",
    )
    parser.add_argument(
        "--capture-guide-screenshots",
        action="store_true",
        help=(
            "In workspace mode, save screenshots to guides/screenshots/<story>/ "
            "so the B5 manual-guide generator can embed them."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".dev-cycle/browser-harness-report"),
        help="Where to write report.md and report.json.",
    )
    parser.add_argument(
        "--workspace-url",
        default=None,
        help="Workspace base URL (workspace mode; default: the driver default).",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help=(
            "Attach to this running widget backend instead of spawning one "
            "(workspace mode)."
        ),
    )
    headless = parser.add_mutually_exclusive_group()
    headless.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=None,
        help="Run Chromium headless (workspace mode).",
    )
    headless.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="Run Chromium visibly (workspace mode; the driver default).",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=None,
        help=(
            "Persistent Chromium profile directory (workspace mode). It holds a "
            "logged-in session: keep it outside the repository (default "
            "~/.openbb_browser_test_harness/chrome_profile)."
        ),
    )
    parser.add_argument(
        "--app-name",
        default=None,
        help=(
            "Workspace app whose tabs hold the story's widgets (default: the "
            "story's app from apps.json)."
        ),
    )
    parser.add_argument(
        "--dashboard",
        default=None,
        help="Visible name of the Workspace dashboard to open after login.",
    )
    parser.add_argument(
        "--managed-credentials",
        type=Path,
        default=None,
        help=(
            "Self-hosted Workspace managed credential file (default: "
            "third_party/workspace/backend-api/backend/"
            "workspace-admin-credentials.secrets under the current directory)."
        ),
    )
    return parser


def main() -> int:
    """Parse the CLI and run one story."""
    args = build_parser().parse_args()
    return asyncio.run(
        _run_story(
            args.story,
            args.mode,
            args.out,
            args.capture_guide_screenshots,
            workspace_driver_kwargs(args),
        )
    )


if __name__ == "__main__":
    sys.exit(main())
