"""Report contracts for the Hermes finance runtime preflight (#1338)."""

from __future__ import annotations

from enum import Enum, IntEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


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


class EdgeStatus(str, Enum):
    """Outcome class of one handshake edge."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"


class EdgeReport(BaseModel):
    """Highest health level reached on one edge, with the failed layer if any."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: EdgeStatus
    level: HealthLevel | None = None
    failed_layer: FailedLayer | None = None
    detail: str = ""
    presence: dict[str, Presence] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def callable(self) -> bool:  # noqa: A003
        """True only when the edge answered a real call."""
        return self.level is not None and self.level >= HealthLevel.CALLABLE


class PreflightReport(BaseModel):
    """Aggregate preflight result. Exit 0 only when ``qualified``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    components: list[ComponentReport]
    edges: list[EdgeReport] = Field(default_factory=list)
    failed_layers: list[FailedLayer]
    failed_layer: FailedLayer | None
    qualified: bool
