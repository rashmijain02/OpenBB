"""Typed loader for ``nautilus_worker/pin.yaml`` (metadata only)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import WORKER_SOURCE_DIR

DEFAULT_PIN_PATH = WORKER_SOURCE_DIR / "pin.yaml"
_FROZEN = ConfigDict(extra="forbid", frozen=True)
SHA256 = r"^[0-9a-f]{64}$"


class EnvNames(BaseModel):
    """Environment variable names that locate the worker (never paths)."""

    model_config = _FROZEN
    venv: str
    image: str


class RuntimePin(BaseModel):
    """One runtime (native venv or container) and its wheel evidence."""

    model_config = _FROZEN
    platform_tag: str
    wheel_filename: str
    wheel_sha256: str = Field(pattern=SHA256)
    precision_mode: Literal["standard", "high"]
    high_precision: bool
    fixed_precision: int = Field(ge=1)
    lock: str

    @model_validator(mode="after")
    def _precision_consistent(self) -> RuntimePin:
        if (self.precision_mode == "high") != self.high_precision:
            raise ValueError("precision_mode and high_precision disagree")
        return self


class NautilusPin(BaseModel):
    """The committed pin: release, wheel hashes per platform tag, precision, licence."""

    model_config = _FROZEN
    schema_version: Literal[1]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")  # stable releases only
    source_tag: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")  # commit the tag points at
    source_tag_object: str = Field(pattern=r"^[0-9a-f]{40}$")  # annotated tag object
    python_tag: str = Field(pattern=r"^cp\d{3,4}$")
    python_minor: str
    license_spdx: str
    license_file_sha256: str = Field(pattern=SHA256)
    selected_runtime: Literal["native", "docker"]
    env: EnvNames
    excluded_extras: list[str]
    runtimes: dict[str, RuntimePin]

    @model_validator(mode="after")
    def _wheels_match_pin(self) -> NautilusPin:
        if set(self.runtimes) != {"native", "docker"}:
            raise ValueError("runtimes must be exactly native and docker")
        for name, rt in self.runtimes.items():
            expected = f"nautilus_trader-{self.version}-{self.python_tag}-{self.python_tag}-{rt.platform_tag}.whl"
            if rt.wheel_filename != expected:
                raise ValueError(f"{name}: wheel_filename must be {expected}")
        return self


def load_pin(path: Path | None = None) -> NautilusPin:
    """Load and validate the pin; unknown keys or bad hashes raise ``ValidationError``."""
    raw = yaml.safe_load(Path(path or DEFAULT_PIN_PATH).read_text(encoding="utf-8"))
    return NautilusPin.model_validate(raw)
