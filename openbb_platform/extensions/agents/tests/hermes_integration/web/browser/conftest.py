"""Tier B fixtures (#1342): the real pinned WebUI, the real HFP sidecar and system Edge.

Everything runs on 127.0.0.1 with temp state. The WebUI source is exported from the
pinned fork commit with ``git archive`` into a temp dir, so the fork checkout is only
read. HOME, USERPROFILE, LOCALAPPDATA and HERMES_HOME point into the temp dir, so no
real Hermes home or WebUI state is touched. Edge is the installed system browser
(``channel="msedge"``); no browser is downloaded. Every non-loopback request is
aborted and counted. A missing prerequisite skips with its reason, never a pass.
"""

from __future__ import annotations

import io
import os
import secrets
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from openbb_agents.hermes_integration.web import bundle
from openbb_agents.hermes_integration.web.sidecar import LoopbackSidecar

WEBUI_PIN = "22d984026c305dfbadd09f29482be6cefe0f028b"


def pytest_collection_modifyitems(items):
    for item in items:
        if "browser" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.requires_browser)


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fork_dir() -> Path:
    """The pinned fork checkout: ``HFP_WEBUI_DIR``, else the profile's ``HFP_HERMES_WEBUI_DIR``."""
    raw = os.environ.get("HFP_WEBUI_DIR") or os.environ.get("HFP_HERMES_WEBUI_DIR")
    if not raw:
        pytest.skip("HFP_WEBUI_DIR unset: the pinned hermes-webui checkout is required")
    return Path(raw)


@pytest.fixture(scope="module")
def playwright_sync():
    try:
        from playwright.sync_api import sync_playwright  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        pytest.skip(f"playwright not installed in this interpreter: {exc}")
    with sync_playwright() as pw:
        yield pw


def _export_webui(dest: Path) -> None:
    fork = _fork_dir()
    if not (fork / ".git").exists():
        pytest.skip(f"pinned WebUI fork not available (set HFP_WEBUI_DIR): {fork.name}")
    result = subprocess.run(
        ["git", "-C", str(fork), "archive", "--format=tar", WEBUI_PIN],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"WebUI pin {WEBUI_PIN[:7]} not in the fork checkout")
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        tar.extractall(dest, filter="data")


def _wait_health(url: str, proc: subprocess.Popen, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


@dataclass
class Stack:
    """The running loopback stack for one module."""

    webui: str
    password: str
    sidecar: LoopbackSidecar
    state_dir: Path
    log_path: Path
    src: Path
    aborted: list[str] = field(default_factory=list)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if os.name != "nt" and not os.environ.get("HFP_BROWSER_ANY_OS"):
        pytest.skip("tier B is qualified on the Windows host with system Edge")
    root = tmp_path_factory.mktemp("hfp-tier-b")
    src = root / "webui"
    _export_webui(src)
    home = root / "home"
    state = root / "webui-state"
    for path in (home, state, root / "agent-empty", root / "localappdata"):
        path.mkdir()
    token_file = state / "sidecar-auth" / "openbb-hfp.token"
    with LoopbackSidecar(principal="tier-b", token_file=token_file) as sidecar:
        ext_dir = root / "bundle"
        bundle.render_bundle(ext_dir, port=sidecar.port)
        port = _free_port()
        password = secrets.token_urlsafe(18)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("HERMES_", "HFP_")) and k not in {"PYTHONPATH"}
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
                "HERMES_WEBUI_EXTENSION_DIR": str(ext_dir),
                "HERMES_WEBUI_EXTENSION_MANIFEST": "manifest.json",
                "PYTHONDONTWRITEBYTECODE": "1",
                "NO_PROXY": "*",
            }
        )
        python = os.environ.get("HFP_WEBUI_PYTHON") or sys.executable
        log_path = root / "webui.log"
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                [python, str(src / "server.py")],
                cwd=src,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                url = f"http://127.0.0.1:{port}"
                if not _wait_health(url, proc):
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                    pytest.fail(f"pinned WebUI did not become healthy:\n{tail}")
                yield Stack(url, password, sidecar, state, log_path, src)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


@pytest.fixture
def browser_context(playwright_sync, stack):
    try:
        browser = playwright_sync.chromium.launch(
            channel="msedge",
            headless=True,
            args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
        )
    except Exception as exc:  # pylint: disable=broad-except
        pytest.skip(f"system Edge could not be launched by playwright: {type(exc).__name__}")
    context = browser.new_context()

    def guard(route):
        url = route.request.url
        if url.startswith(("http://127.0.0.1:", "about:", "data:", "blob:")):
            route.continue_()
        else:
            stack.aborted.append(url.split("?", 1)[0][:120])
            route.abort()

    context.route("**/*", guard)
    try:
        yield context
    finally:
        context.close()
        browser.close()
