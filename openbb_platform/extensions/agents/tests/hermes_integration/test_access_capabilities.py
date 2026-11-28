"""Default-deny tests for the Hermes finance access capabilities (#1339 T01).

A request is allowed only when an explicit grant matches the principal, the
operation, the scope and every requested field. Everything else is refused.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import get_args

import pytest
from openbb_agents.hermes_integration import access
from openbb_agents.hermes_integration.access import (
    OPERATIONS,
    PRINCIPALS,
    AccessRequest,
    Capability,
    PolicyGate,
    build_tool_gate,
)
from openbb_mcp_server.models.capability import AccessClass

from .conftest import SENTINELS

_GRANT = Capability(
    principal="webui_display",
    operation="household_display",
    scope="household.summary",
    fields=frozenset({"display_label", "as_of"}),
)


def _request(**overrides) -> AccessRequest:
    values = {
        "principal": "webui_display",
        "operation": "household_display",
        "scope": "household.summary",
        "fields": frozenset({"display_label"}),
    }
    values.update(overrides)
    return AccessRequest(**values)


def test_vocabulary_reuses_access_class_and_adds_household_operations():
    """Operations are the AccessClass values plus the three household ones."""
    expected = set(get_args(AccessClass)) | {
        "household_read",
        "household_display",
        "evidence_projection_read",
    }
    assert set(OPERATIONS) == expected
    assert set(PRINCIPALS) == {
        "hermes_runtime",
        "hermes_scheduler",
        "webui_display",
        "operator",
    }


def test_exact_grant_allows():
    """Positive control: the matching grant is the only way to be allowed."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(_request())
    assert decision.allowed is True
    assert decision.reason == "granted"


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
@pytest.mark.parametrize("principal", sorted(PRINCIPALS))
def test_empty_grant_set_denies_everything(principal, operation):
    """With no grants, no principal can perform any operation."""
    gate = PolicyGate(grants=frozenset())
    decision = gate.decide(
        _request(principal=principal, operation=operation, scope="household.summary")
    )
    assert decision.allowed is False
    assert decision.reason == "no_grant"


@pytest.mark.parametrize(
    "principal", ["intruder", "", "Webui_Display", " webui_display", "operator\x00"]
)
def test_unknown_principal_denied(principal):
    """Unknown or near-miss principal names never match a grant."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(principal=principal)
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_principal"


@pytest.mark.parametrize("operation", ["household_write", "", "HOUSEHOLD_DISPLAY"])
def test_unknown_operation_denied(operation):
    """Unknown operations are refused before grants are consulted."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(operation=operation)
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_operation"


@pytest.mark.parametrize("scope", ["household", "household.summary.raw", "*", ""])
def test_unknown_scope_denied(scope):
    """Scopes match exactly; a parent, child or wildcard scope is unknown."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(_request(scope=scope))
    assert decision.allowed is False
    assert decision.reason == "unknown_scope"


def test_known_scope_without_grant_denied():
    """A known scope that the principal holds no grant for is refused."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(scope="evidence.projection", operation="evidence_projection_read")
    )
    assert decision.allowed is False
    assert decision.reason == "no_grant"


def test_field_outside_grant_denied():
    """One extra field fails the whole request; there is no partial allow."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(fields=frozenset({"display_label", "account_number"}))
    )
    assert decision.allowed is False
    assert decision.reason == "field_not_granted"


def test_empty_field_request_denied():
    """A request that names no fields is refused rather than treated as 'all'."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(fields=frozenset())
    )
    assert decision.allowed is False
    assert decision.reason == "no_fields"


def test_grant_does_not_transfer_to_another_principal():
    """webui_display's grant gives hermes_runtime nothing."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(principal="hermes_runtime")
    )
    assert decision.allowed is False
    assert decision.reason == "no_grant"


def test_grant_does_not_transfer_to_another_operation():
    """A display grant is not a read grant on the same scope and fields."""
    decision = PolicyGate(grants=frozenset({_GRANT})).decide(
        _request(operation="household_read")
    )
    assert decision.allowed is False
    assert decision.reason == "no_grant"


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "*"},
        {"fields": frozenset({"*"})},
        {"scope": "household.*"},
        {"principal": "intruder"},
        {"operation": "household_write"},
        {"scope": "household.unknown"},
        {"fields": frozenset()},
    ],
)
def test_widening_grants_are_rejected_at_construction(overrides):
    """Wildcards, unknown names and empty field sets cannot be granted."""
    values = {
        "principal": "webui_display",
        "operation": "household_display",
        "scope": "household.summary",
        "fields": frozenset({"display_label"}),
        **overrides,
    }
    with pytest.raises(ValueError):
        Capability(**values)


def test_gate_grants_cannot_be_widened_after_construction():
    """The gate is frozen; adding grants needs a new gate built by the server."""
    gate = PolicyGate(grants=frozenset({_GRANT}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        gate.grants = frozenset({_GRANT, _GRANT})  # type: ignore[misc]
    assert not hasattr(gate.grants, "add")


def test_access_request_rejects_extra_claims():
    """An 'approved' or 'principal override' claim cannot ride on a request."""
    with pytest.raises(ValueError):
        AccessRequest(
            principal="hermes_runtime",
            operation="household_read",
            scope="household.summary",
            fields=frozenset({"display_label"}),
            approved=True,
        )


def test_hermes_runtime_cannot_household_read():
    """The hermes-finance profile gives the runtime no household read."""
    gate = access.HERMES_FINANCE_POLICY
    for fields in ({"display_label"}, {"account_number"}, {"as_of"}):
        decision = gate.decide(
            AccessRequest(
                principal="hermes_runtime",
                operation="household_read",
                scope="household.summary",
                fields=frozenset(fields),
            )
        )
        assert decision.allowed is False


def test_hermes_finance_profile_has_no_private_portfolio_grant():
    """No principal in the profile can read the private portfolio."""
    grants = access.HERMES_FINANCE_POLICY.grants
    assert grants, "profile must not be empty (positive control below)"
    assert all(g.operation != "private_portfolio_read" for g in grants)
    assert all(g.operation != "household_read" for g in grants)
    assert not any(g.principal == "hermes_scheduler" for g in grants)


def test_webui_display_can_read_allowlisted_field_only():
    """webui_display may display the allowlisted fields and nothing more."""
    gate = access.HERMES_FINANCE_POLICY

    def display(*fields: str):
        return gate.decide(
            AccessRequest(
                principal="webui_display",
                operation="household_display",
                scope="household.summary",
                fields=frozenset(fields),
            )
        )

    assert display("display_label").allowed is True
    assert display("display_label", "as_of").allowed is True
    denied = display("display_label", "account_number")
    assert denied.allowed is False
    assert denied.reason == "field_not_granted"


def test_model_claimed_approval_in_arguments_is_ignored():
    """Tool decisions depend on the server-bound principal, never arguments."""
    gate = build_tool_gate("hermes-finance", principal="hermes_runtime")
    claims = {
        "approved": True,
        "principal": "operator",
        "capabilities": ["private_portfolio_read"],
        "owner_approval": "granted",
    }
    decision = gate.decide_tool("get_positions", claims)
    assert decision.allowed is False
    assert decision.reason == "no_grant"
    assert gate.decide_tool("get_positions", {}) == decision


def test_tool_gate_without_principal_denies():
    """A gated server launched without a principal refuses every tool."""
    gate = build_tool_gate("hermes-finance", principal=None)
    for tool in ("get_positions", "get_sector_exposure"):
        decision = gate.decide_tool(tool, {})
        assert decision.allowed is False
        assert decision.reason == "unknown_principal"


def test_tool_gate_unbound_tool_denied():
    """A tool with no operation binding is an unknown operation."""
    gate = build_tool_gate("hermes-finance", principal="operator")
    decision = gate.decide_tool("transfer_funds", {})
    assert decision.allowed is False
    assert decision.reason == "unknown_operation"


def test_unknown_policy_profile_rejected():
    """Only named profiles exist; a typo never yields an ungated server."""
    with pytest.raises(ValueError):
        build_tool_gate("hermes-financ", principal="hermes_runtime")


def test_tool_bindings_cover_every_exposed_tool():
    """Seam contract: every MCP tool has an operation, scope and field set."""
    from openbb_agents.mcp_server import collect_tools

    names = {t["name"] for t in collect_tools()}
    assert names <= set(access.TOOL_BINDINGS)
    for binding in access.TOOL_BINDINGS.values():
        assert binding.operation in OPERATIONS
        assert binding.fields


def test_tool_binding_fields_match_tool_output():
    """Seam contract: the binding names exactly the keys the tool returns."""
    import pandas as pd
    from openbb_agents.tools import portfolio_tools

    frame = pd.DataFrame(
        [
            {
                "symbol": "SYNTH",
                "total_quantity": 2,
                "total_cost_basis": 10.0,
                "total_current_value": 12.0,
                "pct_return": 20.0,
                "portfolio_weight_pct": 100.0,
            }
        ]
    )
    positions = portfolio_tools.get_positions(_fetch=lambda: frame)
    sectors = portfolio_tools.get_sector_exposure(
        _fetch=lambda: frame,
        _profile=lambda symbol: {"symbol": symbol, "sector": "Synthetic"},
    )
    assert set(positions[0]) == access.TOOL_BINDINGS["get_positions"].fields
    assert set(sectors[0]) == access.TOOL_BINDINGS["get_sector_exposure"].fields


def test_audit_line_is_structural_only(caplog):
    """The audit line names the decision, never argument values."""
    gate = build_tool_gate("hermes-finance", principal="hermes_runtime")
    with caplog.at_level(logging.INFO, logger=access.__name__):
        gate.decide_tool("get_positions", {"note": SENTINELS["account"]})
        gate.decide_tool(SENTINELS["name"], {"x": SENTINELS["amount"]})
    lines = [r.getMessage() for r in caplog.records if r.name == access.__name__]
    assert len(lines) == 2
    assert all(line.startswith("policy_decision ") for line in lines)
    assert "tool=get_positions" in lines[0] and "reason=no_grant" in lines[0]
    assert "tool=<unbound>" in lines[1]
    joined = "\n".join(lines)
    assert not any(value in joined for value in SENTINELS.values())


def test_allow_decisions_are_audited_at_the_server_log_level(caplog):
    """The server logs at WARNING, so an allow must be WARNING to be audited."""
    binding = access.TOOL_BINDINGS["get_positions"]
    wide = access.PolicyGate(
        grants=frozenset(
            {
                access.Capability(
                    principal="hermes_runtime",
                    operation=binding.operation,
                    scope=binding.scope,
                    fields=binding.fields,
                )
            }
        )
    )
    gate = access.ToolGate(policy=wide, principal="hermes_runtime")
    with caplog.at_level(logging.WARNING, logger="openbb_agents.hermes_integration.access"):
        assert gate.decide_tool("get_positions", {}).allowed
    allows = [
        r
        for r in caplog.records
        if r.name == "openbb_agents.hermes_integration.access"
        and "allowed=true reason=granted" in r.getMessage()
    ]
    assert len(allows) == 1 and allows[0].levelno >= logging.WARNING


@pytest.mark.parametrize("module", ["access", "policy_probe"])
def test_t01_modules_avoid_forbidden_imports(module):
    """No hosted-fallback config, LiteLLM, ADK or Hermes imports (plan §2)."""
    import ast
    from pathlib import Path

    source = Path(access.__file__).with_name(f"{module}.py").read_text("utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("openbb_agents.config", "litellm", "google.adk", "hermes")
    assert not [m for m in imported if m.startswith(forbidden)]
