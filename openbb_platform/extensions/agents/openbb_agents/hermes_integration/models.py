"""Report contracts for the Hermes finance runtime preflight (#1338)."""

from __future__ import annotations

from enum import Enum, IntEnum

from pydantic import BaseModel, ConfigDict, Field


class HealthLevel(IntEnum):
    """Ladder of health levels; each level implies the lower ones."""

    CONFIGURED = 1
    AUTHENTICATED = 2
    ADMITTED = 3
    CALLABLE = 4
    QUALIFIED = 5


class FailedLayer(str, Enum):
    """Layer that blocked admission, in evaluation order."""

    PROCESS = "process"
    MODULE_ORIGIN = "module_origin"
    ABI = "abi"
    CONFIG = "config"
    AUTH = "auth"
    ROUTE = "route"
    BACKEND = "backend"
    DATABASE = "database"
    SCHEMA = "schema"
    SKILLS = "skills"
    EGRESS = "egress"


class Presence(str, Enum):
    """Whether a secret-shaped field is set. The value itself is never kept."""

    PRESENT = "present"
    ABSENT = "absent"


class ComponentReport(BaseModel):
    """Metadata-only facts about one component. Holds no secret values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    level: HealthLevel | None = None
    failed_layer: FailedLayer | None = None
    detail: str = ""
    sha: str | None = None
    observed_sha: str | None = None
    remote: str | None = None
    dirty: bool | None = None
    license_sha256: str | None = None
    origin: str | None = None
    observed_python: str | None = None
    observed_database: str | None = None
    presence: dict[str, Presence] = Field(default_factory=dict)


class PreflightReport(BaseModel):
    """Aggregate preflight result. Exit 0 only when ``qualified``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    components: list[ComponentReport]
    failed_layers: list[FailedLayer]
    failed_layer: FailedLayer | None
    qualified: bool
