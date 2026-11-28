"""Per-strategy parameter models with bounds (#1356 T01). Strict; no extras."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_SYMBOLS = 50
MAX_REBALANCE_SESSIONS = 252

Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9.\-]{1,16}$")]


def _float_via_str(value: object) -> object:
    """Floats become Decimals through ``str`` (``0.1`` stays ``0.1``)."""
    return Decimal(str(value)) if isinstance(value, float) else value


Weight = Annotated[
    Decimal,
    BeforeValidator(_float_via_str),
    Field(ge=0, le=1, allow_inf_nan=False),
]


class BuyAndHoldParams(BaseModel):
    """``buy_and_hold``: 1 to 50 distinct symbols."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    symbols: Annotated[tuple[Symbol, ...], Field(min_length=1, max_length=MAX_SYMBOLS)]

    @field_validator("symbols")
    @classmethod
    def _distinct(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("symbols must be distinct")
        return value


class TargetWeightRebalanceParams(BaseModel):
    """Long-only, unlevered target weights re-applied every N sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    weights: Annotated[
        dict[Symbol, Weight], Field(min_length=1, max_length=MAX_SYMBOLS)
    ]
    rebalance_every_sessions: Annotated[
        int, Field(ge=1, le=MAX_REBALANCE_SESSIONS, strict=True)
    ]

    @model_validator(mode="after")
    def _unlevered(self) -> TargetWeightRebalanceParams:
        if sum(self.weights.values(), Decimal(0)) > 1:
            raise ValueError("weights must sum to at most 1")
        return self
