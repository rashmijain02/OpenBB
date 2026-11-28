"""Reviewed strategy metadata and execution assumptions (#1356 T01).

Pure pydantic: ``extra="forbid"`` and frozen everywhere. ``spec_sha256`` is the
hash of the spec *without* parameters; the run binds the tuple (spec, code,
params, execution, dataset, engine version) in :mod:`registry`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..protocol import ErrorCode
from .errors import ReviewedError
from .hashing import digest, plain

_FROZEN = ConfigDict(extra="forbid", frozen=True)
SHA256 = r"^[0-9a-f]{64}$"
ID_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
CODE_FILE_PATTERN = r"^[a-z0-9_]+(/[a-z0-9_]+)*\.py$"
MAX_TAKER_BPS = Decimal(100)
# Every file the strategy host imports (transitively) executes in a reviewed run,
# so every strategy fingerprints all of them, not only the files it names itself.
HOST_CODE_FILES = (
    "reviewed/spec.py",
    "reviewed/params.py",
    "reviewed/hashing.py",
    "reviewed/errors.py",
    "reviewed/sizing.py",
    "reviewed/staging.py",
    "reviewed/booking.py",
    "reviewed/host.py",
    "reviewed/buy_and_hold.py",
    "reviewed/target_weight_rebalance.py",
)

# Assumption names a spec declares support for, and a run selects one of each.
ASSUMPTION_FIELDS = (
    "decision",
    "fill_timing",
    "sizing",
    "staging",
    "account",
    "settlement",
    "cash_model",
    "fees",
    "booking",
    "marks",
    "corporate_actions",
)


class ExecutionAssumptions(BaseModel):
    """One run's execution semantics. Anything not listed is rejected."""

    model_config = _FROZEN
    decision: Literal["session_close"] = "session_close"
    fill_timing: Literal["next_open", "same_close"] = "next_open"
    sizing: Literal["whole_share_floor_v1"] = "whole_share_floor_v1"
    staging: Literal["sell_then_buy_v1"] = "sell_then_buy_v1"
    account: Literal["CASH"] = "CASH"
    borrowing: Literal[False] = False
    short: Literal[False] = False
    settlement: Literal["T+1", "T+2"] = "T+1"
    cash_model: Literal["settled_cash_only"] = "settled_cash_only"
    fees: Literal["zero", "taker_bps"] = "zero"
    taker_bps: Decimal | None = Field(default=None, allow_inf_nan=False)
    booking: Literal["nautilus_f64_half_away_cents_v1"] = (
        "nautilus_f64_half_away_cents_v1"
    )
    marks: Literal["exact_decimal_half_even_cents_v1"] = (
        "exact_decimal_half_even_cents_v1"
    )
    corporate_actions: Literal["reject_if_present_in_window"] = (
        "reject_if_present_in_window"
    )

    @model_validator(mode="after")
    def _fee_consistent(self) -> ExecutionAssumptions:
        if self.fees == "zero" and self.taker_bps is not None:
            raise ValueError("taker_bps is only valid with fees='taker_bps'")
        if self.fees == "taker_bps" and (
            self.taker_bps is None or not 0 < self.taker_bps <= MAX_TAKER_BPS
        ):
            raise ValueError("taker_bps must be in (0, 100]")
        return self

    def canonical(self) -> dict[str, Any]:
        """Normalised wire form: every field explicit, numbers as plain strings."""
        return plain(self.model_dump(mode="python"))

    @property
    def execution_sha256(self) -> str:
        """Hash of every assumption (defaults expanded)."""
        return digest(self.canonical())


def parse_execution(raw: Any) -> ExecutionAssumptions:
    """Validate an execution mapping; any unsupported value is ``schema``."""
    if isinstance(raw, ExecutionAssumptions):
        return raw
    try:
        return ExecutionAssumptions.model_validate({} if raw is None else raw)
    except ValidationError as exc:
        fields = sorted(
            {".".join(map(str, e["loc"])) or "execution" for e in exc.errors()}
        )
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "unsupported_execution",
            "unsupported or invalid fields: " + ", ".join(fields),
        ) from exc


class SupportedAssumptions(BaseModel):
    """The values a reviewed strategy supports for each assumption."""

    model_config = _FROZEN
    decision: tuple[str, ...]
    fill_timing: tuple[str, ...]
    sizing: tuple[str, ...]
    staging: tuple[str, ...]
    account: tuple[str, ...]
    settlement: tuple[str, ...]
    cash_model: tuple[str, ...]
    fees: tuple[str, ...]
    booking: tuple[str, ...]
    marks: tuple[str, ...]
    corporate_actions: tuple[str, ...]


class StrategySpec(BaseModel):
    """Reviewed strategy metadata. Params are never part of the spec."""

    model_config = _FROZEN
    strategy_id: str = Field(pattern=ID_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    code_files: Annotated[
        tuple[Annotated[str, Field(pattern=CODE_FILE_PATTERN)], ...],
        Field(min_length=1),
    ]
    param_schema_sha256: str = Field(pattern=SHA256)
    supported: SupportedAssumptions

    @property
    def spec_sha256(self) -> str:
        """Hash of the spec (id, version, files, schema hash, supported set)."""
        return digest(self.model_dump(mode="json"))

    def check_execution(self, execution: ExecutionAssumptions) -> None:
        """Reject an assumption this spec was not reviewed for."""
        for name in ASSUMPTION_FIELDS:
            if getattr(execution, name) not in getattr(self.supported, name):
                raise ReviewedError(
                    ErrorCode.SCHEMA,
                    "unsupported_execution",
                    f"{self.strategy_id}@{self.version} does not support this {name}",
                )


class StrategyRef(BaseModel):
    """Wire reference to a reviewed strategy (request v2)."""

    model_config = _FROZEN
    id: str = Field(pattern=ID_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    code_sha256: str = Field(pattern=SHA256)
    spec_sha256: str = Field(pattern=SHA256)
