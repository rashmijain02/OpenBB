"""Tier B (#1342 T03): reload and network-offline mid-run in the real pinned WebUI.

Drives :func:`web_journey.drive_reconnect` against the module's real stack: the
job is held queued while the page reloads (the run card comes back from the
extension's own storage, with no marker on the page) and while the network is
offline (the card reads ``sidecar_unreachable``, then reconnects). Once the
worker is released the card reads ``succeeded``. Counts come from SQLite and the
browser's request log: one approval POST, zero ``/api/chat/start``, one run, one
job.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest

pytest.importorskip("openbb_portfolio_intel")

from openbb_agents.hermes_integration.web import web_journey  # noqa: E402
from openbb_agents.hermes_integration.web.journey import (  # noqa: E402
    WORKFLOW_ID,
    synthetic_stack,
)


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    with synthetic_stack(tmp_path_factory.mktemp("hfp-reconnect")) as built:
        yield built


@pytest.fixture(scope="module")
def sidecar_backend(journey):
    return journey.backend


def test_browser_reconnect(browser_context, stack, journey):
    webui = web_journey.WebUi(stack.webui, stack.password, stack.src, stack.aborted)
    report = web_journey.drive_reconnect(browser_context, webui, journey, WORKFLOW_ID)
    assert report["steps"] == list(web_journey.EXPECTED_STEPS), report
    assert report["error"] is None
    assert report["approve_posts"] == 1 and report["chat_starts"] == 0
    assert (report["runs"], report["jobs"]) == (1, 1)
    assert report["ok"], report
