"""Browser journey driver of the HFP web slice (#1342 T03).

``--stack local`` (synthetic, loopback only): exports the pinned WebUI with
``git archive`` from ``HFP_WEBUI_DIR`` into a temp dir (the checkout is only read),
starts it with temp state and a generated password beside the real HFP sidecar
over temp stores (:func:`.journey.synthetic_stack`), and drives system Edge
headless through Playwright. Every non-loopback request is aborted and counted.
The journey: plan card -> Approve (double click) -> start twice -> the run card,
then, with the job held queued (the worker is not started yet), a page reload
and a network-offline spell. The card must come back to the same run from the
extension's own storage, ``/api/chat/start`` must never be requested, and once
the worker is released the card reads ``succeeded`` with one run and one job.

``--stack live`` never runs anything. It prints the owner's L6 steps and, without
``--owner-config``, refuses (exit 2). Real data is never touched here.

Exit codes: 0 ok, 1 mismatch, 2 live refused, 3 usage, 4 prerequisite missing
(never a pass).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WEBUI_PIN = "22d984026c305dfbadd09f29482be6cefe0f028b"
_WAIT_MS = 30000
# The only off-box requests the pinned WebUI shell (``static/index.html`` at
# WEBUI_PIN) makes: CDN assets, aborted by the guard and not counted as egress.
# Any other aborted URL, including one the shell or the extension adds later,
# fails the journey.
PINNED_SHELL_ASSETS = frozenset(
    {
        "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/components/prism-core.min.js",
        "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/plugins/autoloader/"
        "prism-autoloader.min.js",
        "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/themes/prism-tomorrow.min.css",
        "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js",
        "https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/"
        "xterm-addon-web-links.js",
        "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css",
        "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js",
    }
)
# The fresh temp profile opens the WebUI onboarding dialog; it would cover cards.
_SHOW = """(marker) => { document.getElementById('onboardingOverlay')?.remove();
  if (marker) { const d = document.createElement('div');
    d.setAttribute('data-hfp-scan', '1'); d.textContent = marker;
    document.body.appendChild(d); }
  return !!window.HfpCards; }"""
_LOGIN = """async (pw) => (await fetch('/api/auth/login', {method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({password: pw})})).status"""
_CONSENT = """async () => (await fetch('/api/extensions/sidecar-proxy-consent', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({id: 'openbb-hfp', approved: true})})).status"""
OWNER_STEPS = (
    "L6b (owner, real browser, after L2-L5 and #1341 T04), in <qual-home>:",
    "1. Start WebUI with the finance-web profile and the HFP sidecar (loopback).",
    "2. Select synthetic.basket_xray -> Preview (press Send) -> plan card.",
    "3. Approve (double-click) -> Start (press Send).",
    "4. Close the tab mid-run, reopen, log in: expect the same run_id and no new",
    "   chat turn in the WebUI run journal.",
    "5. Cross-origin attempt from a second loopback page: expect 403.",
    "6. run_receipts --run <id>: 1 run, 1 job, succeeded, tables present;",
    "   L5 scan of <qual-home> hits=0. Report exit codes and mismatched lines.",
)


class JourneyUnavailable(RuntimeError):
    """A prerequisite of the local journey is missing; never a pass."""


@dataclass
class WebUi:
    """The running pinned WebUI."""

    url: str
    password: str
    src: Path
    aborted: list[str] = field(default_factory=list)


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _export(fork: Path, dest: Path) -> None:
    if not (fork / ".git").exists():
        raise JourneyUnavailable("pinned WebUI checkout not found (HFP_WEBUI_DIR)")
    # Fixed argv (git, the operator's checkout path, a pinned sha); no shell.
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(fork), "archive", "--format=tar", WEBUI_PIN],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise JourneyUnavailable(f"WebUI pin {WEBUI_PIN[:7]} not in the checkout")
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        tar.extractall(dest, filter="data")


def _healthy(url: str, proc: subprocess.Popen, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            # ``url`` is always http://127.0.0.1:<ephemeral port>.
            health = url + "/health"
            with urllib.request.urlopen(health, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


@contextlib.contextmanager
def local_webui(root: Path, fork: Path, sidecar_port: int) -> Iterator[WebUi]:
    """Run the pinned WebUI on an ephemeral loopback port with temp state."""
    # pylint: disable=import-outside-toplevel
    from .bundle import render_bundle

    src, home, state = root / "webui", root / "home", root / "webui-state"
    _export(fork, src)
    for path in (home, state, root / "agent-empty", root / "localappdata"):
        path.mkdir()
    render_bundle(root / "bundle", port=sidecar_port)
    port, password = _free_port(), secrets.token_urlsafe(18)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("HERMES_", "HFP_", "OPENBB_")) and k != "PYTHONPATH"
    }
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(root / "localappdata"),
            "HERMES_HOME": str(home / "hermes"),
            "HERMES_WEBUI_HOST": "127.0.0.1",
            "HERMES_WEBUI_PORT": str(port),
            "HERMES_WEBUI_PASSWORD": password,
            "HERMES_WEBUI_STATE_DIR": str(state),
            "HERMES_WEBUI_AGENT_DIR": str(root / "agent-empty"),
            "HERMES_WEBUI_EXTENSION_DIR": str(root / "bundle"),
            "HERMES_WEBUI_EXTENSION_MANIFEST": "manifest.json",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "*",
        }
    )
    python = os.environ.get("HFP_WEBUI_PYTHON") or sys.executable
    with (root / "webui.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
            [python, str(src / "server.py")],
            cwd=src,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            if not _healthy(url, proc):
                raise JourneyUnavailable("pinned WebUI did not become healthy")
            yield WebUi(url, password, src)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@contextlib.contextmanager
def edge_context(webui: WebUi) -> Iterator[Any]:
    """System Edge (headless, no download) with every non-loopback request aborted."""
    try:
        # pylint: disable=import-outside-toplevel
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise JourneyUnavailable("playwright is not installed") from exc
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                channel="msedge",
                headless=True,
                args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
            )
        except Exception as exc:  # pylint: disable=broad-except
            raise JourneyUnavailable("system Edge could not be launched") from exc
        context = browser.new_context()

        def guard(route: Any) -> None:
            url = route.request.url
            if url.startswith(("http://127.0.0.1:", "about:", "data:", "blob:")):
                route.continue_()
            else:
                webui.aborted.append(url.split("?", 1)[0][:120])
                route.abort()

        context.route("**/*", guard)
        try:
            yield context
        finally:
            context.close()
            browser.close()


def _card(page: Any, run_id: str, extra: str = "", scope: str = "") -> None:
    selector = f'{scope}[data-hfp-run="{run_id}"]{extra}'
    page.locator(selector).first.wait_for(state="attached", timeout=_WAIT_MS)


def _steps(
    context: Any, webui: WebUi, journey: Any, workflow_id: str, facts: dict[str, Any]
) -> Iterator[str]:
    """Run the journey as named steps; each yields after its check held."""
    requests: list[tuple[str, str]] = facts["requests"]
    context.on("request", lambda r: requests.append((r.method, r.url)))
    page = context.new_page()
    page.goto(webui.url + "/login")
    facts["login"] = page.evaluate(_LOGIN, webui.password)
    page.goto(webui.url + "/")
    facts["consent"] = page.evaluate(_CONSENT)
    page.reload()
    yield "login_and_consent"
    plan = journey.story.post(
        "/api/v1/story/plans", json={"workflow_id": workflow_id}
    ).json()
    plan_id = facts["plan_id"] = plan["plan_id"]
    page.evaluate(_SHOW, f"[[hfp:plan:{plan_id}]]")
    button = page.locator(f'[data-hfp-plan="{plan_id}"] .hfp-approve')
    button.wait_for(timeout=_WAIT_MS)
    button.dblclick()
    page.locator(f'[data-hfp-plan="{plan_id}"] [data-hfp-code="approved"]').wait_for(
        timeout=_WAIT_MS
    )
    yield "approved"
    starts = [
        journey.story.post(f"/api/v1/story/plans/{plan_id}/start", json={})
        for _ in range(2)
    ]
    run_id = starts[0].json()["run_id"]
    facts["start_replay_of"] = starts[1].json().get("replay_of") == run_id
    facts["start_marker"] = starts[0].json().get("marker") == f"[[hfp:run:{run_id}]]"
    # No run marker is injected: the approved plan card polls its plan until the
    # start names the run, then mounts the run card itself (production path).
    _card(page, run_id, scope=f'[data-hfp-plan="{plan_id}"] ')
    yield "run_card"
    # Reload mid-run (the job is held queued): no marker is on the new page, so
    # the card can only come back from the extension's own storage.
    page.reload()
    page.evaluate(_SHOW, "")
    _card(page, run_id, scope=".hfp-resume ")
    yield "reload_resumed"
    # Network offline mid-run, then back: the card reconnects to the same run.
    context.set_offline(True)
    page.locator('.hfp-resume [data-hfp-code="sidecar_unreachable"]').wait_for(
        state="attached", timeout=_WAIT_MS
    )
    yield "offline_unreachable"
    context.set_offline(False)
    _card(page, run_id, scope=".hfp-resume ")  # a run card again, not an error
    yield "online_reconnected"
    # Release the held job. Playwright's sync API owns this thread's loop, so
    # the worker (which runs its own asyncio loop) gets a thread of its own.
    ran: list[object] = []
    worker = threading.Thread(target=lambda: ran.append(journey.worker.run_once()))
    worker.start()
    worker.join(timeout=180)
    facts["worker_ran"] = bool(ran and ran[0])
    _card(page, run_id, '[data-hfp-outcome="succeeded"]', scope=".hfp-resume ")
    yield "succeeded"


EXPECTED_STEPS = (
    "login_and_consent",
    "approved",
    "run_card",
    "reload_resumed",
    "offline_unreachable",
    "online_reconnected",
    "succeeded",
)


def drive_reconnect(
    context: Any, webui: WebUi, journey: Any, workflow_id: str
) -> dict[str, Any]:
    """Drive the reconnect journey; counts come from SQLite and the request log."""
    facts: dict[str, Any] = {"requests": []}
    done: list[str] = []
    error = None
    try:
        for step in _steps(context, webui, journey, workflow_id, facts):
            done.append(step)
    except Exception as exc:  # pylint: disable=broad-except
        error = type(exc).__name__
    requests = facts["requests"]
    approve = f"/sidecar/plans/{facts.get('plan_id')}/approve"
    report = {
        "stack": "local",
        "steps": done,
        "error": error,
        "login": facts.get("login"),
        "consent": facts.get("consent"),
        "approve_posts": sum(
            1 for m, u in requests if m == "POST" and u.endswith(approve)
        ),
        "start_replay_of": facts.get("start_replay_of", False),
        "start_marker": facts.get("start_marker", False),
        "worker_ran": facts.get("worker_ran", False),
        "chat_starts": sum(1 for _, u in requests if "/api/chat/start" in u),
        "runs": len(journey.rows(journey.store, "SELECT run_id FROM story_runs")),
        "jobs": len(journey.rows(journey.jobs_db, "SELECT run_id FROM job_run")),
        "provider_calls": len(journey.provider_calls),
        "aborted": [u for u in webui.aborted if u not in PINNED_SHELL_ASSETS],
    }
    report["ok"] = (
        tuple(done) == EXPECTED_STEPS
        and report["login"] == 200
        and report["consent"] == 200
        and report["approve_posts"] == 1
        and report["start_replay_of"] is True
        and report["start_marker"] is True
        and report["worker_ran"] is True
        and report["chat_starts"] == 0
        and report["runs"] == 1
        and report["jobs"] == 1
        and report["provider_calls"] == 0
        and not report["aborted"]
    )
    return report


def run_local(fork: Path) -> dict[str, Any]:
    """Build the synthetic loopback stack and drive the reconnect journey."""
    # pylint: disable=import-outside-toplevel
    from .journey import PRINCIPAL, WORKFLOW_ID, synthetic_stack
    from .sidecar import LoopbackSidecar

    with tempfile.TemporaryDirectory(
        prefix="hfp-web-journey-", ignore_cleanup_errors=True
    ) as tmp:
        root = Path(tmp)
        (root / "stores").mkdir()
        token_file = root / "webui-state" / "sidecar-auth" / "openbb-hfp.token"
        with synthetic_stack(root / "stores") as journey, LoopbackSidecar(
            principal=PRINCIPAL, token_file=token_file, backend=journey.backend
        ) as side, local_webui(root, fork, side.port) as webui, edge_context(
            webui
        ) as context:
            return drive_reconnect(context, webui, journey, WORKFLOW_ID)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="web_journey", description=__doc__)
    parser.add_argument("--stack", choices=["local", "live"], required=True)
    parser.add_argument("--browser", choices=["msedge"], default="msedge")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--webui-dir", help="pinned WebUI checkout (HFP_WEBUI_DIR)")
    parser.add_argument("--owner-config", help="live only: the owner's L6 config")
    parser.add_argument("--webui", help="live only: the owner's WebUI URL")
    parser.add_argument("--workflow", default="synthetic.basket_xray")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    if args.stack == "live":
        steps = "\n".join(OWNER_STEPS)
        if not args.owner_config or not Path(args.owner_config).is_file():
            sys.stdout.write(
                "refused: --stack live runs nothing without the owner's"
                f" --owner-config; the owner runs these steps:\n{steps}\n"
            )
            return 2
        sys.stdout.write(f"owner steps (nothing is run here):\n{steps}\n")
        return 0
    fork = args.webui_dir or os.environ.get("HFP_WEBUI_DIR")
    try:
        if not fork:
            raise JourneyUnavailable("HFP_WEBUI_DIR unset")
        report = run_local(Path(fork))
    except JourneyUnavailable as exc:
        sys.stdout.write(json.dumps({"stack": "local", "unavailable": str(exc)}) + "\n")
        return 4
    text = (
        json.dumps(report, indent=2)
        if args.format == "json"
        else "\n".join(f"{k}: {v}" for k, v in report.items())
    )
    sys.stdout.write(text + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
