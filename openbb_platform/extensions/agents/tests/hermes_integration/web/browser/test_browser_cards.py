"""Tier B (#1342 T02): approve through the plan card in the real pinned WebUI.

The real sidecar runs with a :class:`StoryBackend` over temp stores
(``synthetic_stack``). The page shows a plan marker, the extension mounts the plan
card, the owner double-clicks Approve, and the plan's one run is started and run
in-process; the run card then reads ``succeeded``. Counts come from SQLite rows
and the browser's own request log, never from handler counters. A page on
another loopback port still cannot approve.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import threading

import pytest

pytest.importorskip("openbb_portfolio_intel")

from openbb_agents.hermes_integration.web.journey import (  # noqa: E402
    WORKFLOW_ID,
    synthetic_stack,
)
from openbb_agents.hermes_integration.web.web_journey import (  # noqa: E402
    PINNED_SHELL_ASSETS,
)

from .test_browser_origin import _attacker, _login  # noqa: E402


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    with synthetic_stack(tmp_path_factory.mktemp("hfp-cards")) as built:
        yield built


@pytest.fixture(scope="module")
def sidecar_backend(journey):
    return journey.backend


# The fresh temp profile opens the WebUI onboarding dialog; it would cover the card.
_SHOW = """(marker) => { document.getElementById('onboardingOverlay')?.remove();
  const d = document.createElement('div');
  d.setAttribute('data-hfp-scan', '1'); d.textContent = marker;
  document.body.appendChild(d); return !!window.HfpCards; }"""

_ATTACK = """<!doctype html><meta charset="utf-8"><script>
window.attempt = fetch("{url}", {{method: "POST", credentials: "include",
  headers: {{"Content-Type": "application/json"}}, body: {body}}})
  .then(r => r.status, () => "blocked");
</script>"""


def _consent(page):
    status = page.evaluate(
        """async () => (await fetch('/api/extensions/sidecar-proxy-consent', {method: 'POST',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({id: 'openbb-hfp', approved: true})})).status"""
    )
    assert status == 200


def test_browser_cards(browser_context, stack, journey):  # noqa: PLR0915
    requests: list[tuple[str, str]] = []
    browser_context.on("request", lambda r: requests.append((r.method, r.url)))
    page = browser_context.new_page()
    _login(page, stack)
    _consent(page)
    page.reload()

    plan = journey.story.post(
        "/api/v1/story/plans", json={"workflow_id": WORKFLOW_ID}
    ).json()
    plan_id = plan["plan_id"]
    assert page.evaluate(_SHOW, f"[[hfp:plan:{plan_id}]]") is True
    button = page.locator(f'[data-hfp-plan="{plan_id}"] .hfp-approve')
    button.wait_for(timeout=15000)
    button.dblclick()
    page.locator(f'[data-hfp-plan="{plan_id}"] [data-hfp-code="approved"]').wait_for(
        timeout=15000
    )
    approve_url = f"/api/extensions/openbb-hfp/sidecar/plans/{plan_id}/approve"
    posts = [u for m, u in requests if m == "POST" and u.endswith(approve_url)]
    assert len(posts) == 1, posts
    rows = journey.rows(
        journey.store,
        "SELECT state, approved_at FROM story_plans WHERE plan_id = ?",
        plan_id,
    )
    assert len(rows) == 1 and rows[0][0] == "approved" and rows[0][1]

    # Start is the agent's MCP call, never a sidecar route; twice -> one run.
    starts = [
        journey.story.post(f"/api/v1/story/plans/{plan_id}/start", json={})
        for _ in range(2)
    ]
    assert [s.status_code for s in starts] == [202, 202]
    run_id = starts[0].json()["run_id"]
    assert starts[1].json()["run_id"] == run_id
    assert starts[0].json()["marker"] == f"[[hfp:run:{run_id}]]"
    # Playwright's sync API owns this thread's event loop; the worker's own
    # asyncio.run needs a thread without one (as in the real worker process).
    ran: list[object] = []
    worker = threading.Thread(target=lambda: ran.append(journey.worker.run_once()))
    worker.start()
    worker.join(timeout=120)
    assert ran and ran[0]
    # No run marker is injected: the approved plan card polled its plan until
    # the start named the run, then mounted the run card (production path).
    page.locator(
        f'[data-hfp-plan="{plan_id}"] [data-hfp-run="{run_id}"]'
        '[data-hfp-outcome="succeeded"]'
    ).wait_for(timeout=30000)
    run_gets = [
        u for m, u in requests if m == "GET" and u.endswith(f"/sidecar/runs/{run_id}")
    ]
    assert run_gets, "the run card polled the run"
    # Reload: the plan card now shows its run, read from the same stores.
    page.reload()
    page.evaluate(_SHOW, f"[[hfp:plan:{plan_id}]]")
    page.locator(
        f'[data-hfp-plan="{plan_id}"] [data-hfp-run="{run_id}"]'
        '[data-hfp-outcome="succeeded"]'
    ).wait_for(timeout=20000)

    assert journey.rows(journey.store, "SELECT run_id FROM story_runs") == [(run_id,)]
    jobs = journey.rows(journey.jobs_db, "SELECT status FROM job_run")
    assert jobs == [("succeeded",)]
    assert journey.provider_calls == [] and journey.egress == []

    # A page on another loopback port: the approval proxy refuses it.
    approvals_before = journey.rows(
        journey.store, "SELECT approved_at FROM story_plans WHERE plan_id = ?", plan_id
    )
    body = json.dumps({"plan_sha256": plan["plan_sha256"], "approval_nonce": "n" * 64})
    with _attacker(
        _ATTACK.format(url=stack.webui + approve_url, body=json.dumps(body))
    ) as url:
        evil = browser_context.new_page()
        evil.goto(url)
        attempt = evil.evaluate("window.attempt")
    assert attempt in ("blocked", 403), attempt
    assert (
        journey.rows(
            journey.store,
            "SELECT approved_at FROM story_plans WHERE plan_id = ?",
            plan_id,
        )
        == approvals_before
    )
    assert not [u for m, u in requests if "/api/chat/start" in u]
    assert [u for u in stack.aborted if u not in PINNED_SHELL_ASSETS] == []
