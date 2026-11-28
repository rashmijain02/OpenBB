"""Principal and operation-scoped access capabilities with default deny (#1339).

A request is allowed only when an explicit :class:`Capability` grants the
same principal, operation and scope and covers every requested field.
Unknown principals, operations, scopes or fields are denied; there are no
wildcards, no prefix matching and no partial allows.

The principal is bound by whoever launches the server (for example the
``--principal`` flag of ``openbb_agents.mcp_server``). Tool arguments come
from the model, so they are never consulted: a model-supplied "approved"
claim cannot change a decision.

This module has no side effects on import and depends only on pydantic, the
standard library and the ``AccessClass`` vocabulary of ``openbb_mcp_server``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, get_args

from openbb_mcp_server.models.capability import AccessClass
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

PRINCIPALS: frozenset[str] = frozenset(
    {"hermes_runtime", "hermes_scheduler", "webui_display", "operator"}
)
HOUSEHOLD_OPERATIONS: frozenset[str] = frozenset(
    {"household_read", "household_display", "evidence_projection_read"}
)
OPERATIONS: frozenset[str] = frozenset(get_args(AccessClass)) | HOUSEHOLD_OPERATIONS
KNOWN_SCOPES: frozenset[str] = frozenset(
    {
        "portfolio.positions",
        "portfolio.sector_exposure",
        "household.summary",
        "evidence.projection",
    }
)

# Fields an evidence projection may carry (#1339 T03). Each is opaque,
# coded or bucketed by ``projection.project``; raw values have no field.
EVIDENCE_PROJECTION_FIELDS: frozenset[str] = frozenset(
    {
        "run_id",
        "artifact_id",
        "capability_status",
        "finding_codes",
        "metric_refs",
        "aggregate_buckets",
        "as_of",
    }
)

Reason = Literal[
    "granted",
    "unknown_principal",
    "unknown_operation",
    "unknown_scope",
    "no_fields",
    "no_grant",
    "field_not_granted",
]


class Capability(BaseModel):
    """One explicit grant: principal x operation x scope x field set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal: str
    operation: str
    scope: str
    fields: frozenset[str]

    @field_validator("principal")
    @classmethod
    def _known_principal(cls, value: str) -> str:
        if value not in PRINCIPALS:
            raise ValueError("unknown principal")
        return value

    @field_validator("operation")
    @classmethod
    def _known_operation(cls, value: str) -> str:
        if value not in OPERATIONS:
            raise ValueError("unknown operation")
        return value

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        if value not in KNOWN_SCOPES:
            raise ValueError("unknown scope (wildcards are not scopes)")
        return value

    @field_validator("fields")
    @classmethod
    def _explicit_fields(cls, value: frozenset[str]) -> frozenset[str]:
        if not value:
            raise ValueError("a grant must name at least one field")
        if any(not name or "*" in name for name in value):
            raise ValueError("field names must be explicit (no wildcards)")
        return value


class AccessRequest(BaseModel):
    """What a caller asks for. Extra claims (e.g. ``approved``) are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal: str
    operation: str
    scope: str
    fields: frozenset[str]


@dataclass(frozen=True)
class Decision:
    """Outcome of a policy check; ``reason`` is a fixed code, never free text."""

    allowed: bool
    reason: Reason


@dataclass(frozen=True)
class PolicyGate:
    """Immutable set of grants; :meth:`decide` denies unless a grant matches."""

    grants: frozenset[Capability]

    def decide(self, request: AccessRequest) -> Decision:
        """Return the decision for ``request`` (default deny)."""
        if request.principal not in PRINCIPALS:
            return Decision(False, "unknown_principal")
        if request.operation not in OPERATIONS:
            return Decision(False, "unknown_operation")
        if request.scope not in KNOWN_SCOPES:
            return Decision(False, "unknown_scope")
        if not request.fields:
            return Decision(False, "no_fields")
        candidates = [
            grant
            for grant in self.grants
            if grant.principal == request.principal
            and grant.operation == request.operation
            and grant.scope == request.scope
        ]
        if not candidates:
            return Decision(False, "no_grant")
        if any(request.fields <= grant.fields for grant in candidates):
            return Decision(True, "granted")
        return Decision(False, "field_not_granted")


@dataclass(frozen=True)
class ToolBinding:
    """The operation, scope and output fields an MCP tool exercises."""

    operation: str
    scope: str
    fields: frozenset[str]


TOOL_BINDINGS: Mapping[str, ToolBinding] = MappingProxyType(
    {
        "get_positions": ToolBinding(
            operation="private_portfolio_read",
            scope="portfolio.positions",
            fields=frozenset(
                {
                    "symbol",
                    "shares",
                    "cost_basis",
                    "current_value",
                    "unrealized_gain_pct",
                    "weight_pct",
                }
            ),
        ),
        "get_sector_exposure": ToolBinding(
            operation="private_portfolio_read",
            scope="portfolio.sector_exposure",
            fields=frozenset({"sector", "market_value", "weight_pct"}),
        ),
    }
)

# hermes-finance: no principal may read the private portfolio or household
# records. Display and evidence projections are field-allowlisted.
HERMES_FINANCE_POLICY = PolicyGate(
    grants=frozenset(
        {
            Capability(
                principal="webui_display",
                operation="household_display",
                scope="household.summary",
                fields=frozenset({"display_label", "as_of"}),
            ),
            Capability(
                principal="hermes_runtime",
                operation="evidence_projection_read",
                scope="evidence.projection",
                fields=EVIDENCE_PROJECTION_FIELDS,
            ),
        }
    )
)

POLICY_PROFILES: Mapping[str, PolicyGate] = MappingProxyType(
    {"hermes-finance": HERMES_FINANCE_POLICY}
)


@dataclass(frozen=True)
class ToolGate:
    """Policy gate bound to one server-side principal, applied per tool call."""

    policy: PolicyGate
    principal: str | None

    def decide_tool(self, name: str, arguments: Mapping[str, Any]) -> Decision:
        """Decide a tool call. ``arguments`` are model-supplied and ignored."""
        del arguments  # never consulted: model claims cannot grant access
        binding = TOOL_BINDINGS.get(name)
        if binding is None:
            decision = Decision(False, "unknown_operation")
        else:
            decision = self.policy.decide(
                AccessRequest(
                    principal=self.principal or "",
                    operation=binding.operation,
                    scope=binding.scope,
                    fields=binding.fields,
                )
            )
        logger.log(
            logging.INFO if decision.allowed else logging.WARNING,
            "policy_decision principal=%s tool=%s operation=%s allowed=%s reason=%s",
            self.principal if self.principal in PRINCIPALS else "<unknown>",
            name if binding is not None else "<unbound>",
            binding.operation if binding is not None else "<none>",
            str(decision.allowed).lower(),
            decision.reason,
        )
        return decision

    def denial_payload(self, name: str, decision: Decision) -> str:
        """Structural JSON error for a denied call (no argument values)."""
        tool = name if name in TOOL_BINDINGS else "?"
        return json.dumps(
            {"error": "capability_denied", "tool": tool, "reason": decision.reason}
        )


def build_tool_gate(profile: str, principal: str | None) -> ToolGate:
    """Return the gate for a named policy profile; unknown profiles raise."""
    policy = POLICY_PROFILES.get(profile)
    if policy is None:
        raise ValueError("unknown policy profile")
    return ToolGate(policy=policy, principal=principal)
