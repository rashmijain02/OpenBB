"""``story_run_cancel`` gets no grant from the hermes-finance gate (#1341 T02).

The gate binds only the tools it knows (``TOOL_BINDINGS``); every other tool
name is denied as an unknown operation, for every principal. Adding the run
cancel tool to the reviewed server policy therefore opens nothing here.
"""

import pytest
from openbb_agents.hermes_integration import access
from openbb_agents.hermes_integration.access import PRINCIPALS, build_tool_gate


def test_run_cancel_has_no_tool_binding():
    """No binding means no grant can ever match it."""
    assert "story_run_cancel" not in access.TOOL_BINDINGS
    assert "story_job_cancel" not in access.TOOL_BINDINGS


@pytest.mark.parametrize("principal", sorted(PRINCIPALS))
def test_run_cancel_is_denied_by_default_for_every_principal(principal):
    """Model-supplied claims cannot turn the denial into an allow."""
    gate = build_tool_gate("hermes-finance", principal=principal)
    claims = {"approved": True, "principal": "operator", "run_id": "synthetic"}
    for args in ({}, claims):
        decision = gate.decide_tool("story_run_cancel", args)
        assert decision.allowed is False
        assert decision.reason == "unknown_operation"
