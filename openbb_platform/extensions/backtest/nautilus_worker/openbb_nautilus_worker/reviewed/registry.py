"""Reviewed-strategy allowlist, pinned hashes and run binding (#1356 T01).

The only way to resolve a strategy is a dictionary lookup in :data:`ALLOWLIST`
by ``(id, version)``. No entry points, no ``importlib`` on strings and no class
objects from requests (a test walks this file's AST to keep it so).

Review rule: :data:`REVIEW_LEDGER` is append-only. A record for an existing
``(id, version)`` can never change; any change to a reviewed file needs a new
version with a new record (:func:`check_ledger`). A drifted file or schema is
never fixed by editing a hash alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ValidationError

from ..protocol import ErrorCode
from . import buy_and_hold, target_weight_rebalance
from .errors import ReviewedError
from .hashing import code_sha256, digest, params_digest, plain
from .spec import (
    ID_PATTERN,
    SEMVER_PATTERN,
    ExecutionAssumptions,
    StrategySpec,
    parse_execution,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_ID = re.compile(ID_PATTERN)
_SEMVER = re.compile(SEMVER_PATTERN)


@dataclass(frozen=True)
class Pin:
    """Reviewed hashes of one ``(id, version)``."""

    strategy_id: str
    version: str
    code_sha256: str
    param_schema_sha256: str
    spec_sha256: str


# Append-only. Never edit a record; add a new version with a new record.
REVIEW_LEDGER: tuple[Pin, ...] = (
    Pin(
        "buy_and_hold",
        "1.0.0",
        "d11ec2d5bc48cf04bf33b85c6b0cd6ecabae13118409dd0450c144202e0028d1",
        "2154e944794a16b4465e64b0798fa95c932eae6839f587c550c4ddd725dddc66",
        "c08541e7d1398d15482f1f190c08e0b732f253ddc41536817d9f2c4cb30b260c",
    ),
    Pin(
        "target_weight_rebalance",
        "1.0.0",
        "2e52e63b2b2e62a88a29dc96e737eb23a525d5f5dcf21cae3c48a633347f9f6e",
        "611597da61879e314df15f3441e17d59c66bf04417f98ff499786b5fc98a3a3e",
        "7d07d0ea95933afcfed00284d58acca2a59c8ef3b3ae0c76decfed29ed4f14ed",
    ),
)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_ledger(ledger: tuple[Pin, ...]) -> None:
    """Enforce the review rule on a ledger (raises :class:`ReviewedError`)."""
    seen: set[tuple[str, str]] = set()
    latest: dict[str, tuple[int, ...]] = {}
    for pin in ledger:
        key = (pin.strategy_id, pin.version)
        if key in seen:
            raise ReviewedError(
                ErrorCode.SCHEMA,
                "pin_changed_without_version_bump",
                f"{pin.strategy_id}@{pin.version} is already pinned; "
                "a changed reviewed file needs a new version",
            )
        seen.add(key)
        number = _version_key(pin.version)
        if pin.strategy_id in latest and number <= latest[pin.strategy_id]:
            raise ReviewedError(
                ErrorCode.SCHEMA,
                "pin_version_not_increasing",
                f"{pin.strategy_id}@{pin.version} must be newer than earlier pins",
            )
        latest[pin.strategy_id] = number


@dataclass(frozen=True)
class Entry:
    """A reviewed strategy as defined by the code under review."""

    spec: StrategySpec
    params_model: type[BaseModel]


_DEFINITIONS = {
    (module.STRATEGY_ID, module.VERSION): Entry(
        module.build_spec(), module.PARAMS_MODEL
    )
    for module in (buy_and_hold, target_weight_rebalance)
}
_UNIVERSE: dict[tuple[str, str], Callable[[Any], tuple[str, ...]]] = {
    (buy_and_hold.STRATEGY_ID, buy_and_hold.VERSION): buy_and_hold.universe,
    (
        target_weight_rebalance.STRATEGY_ID,
        target_weight_rebalance.VERSION,
    ): target_weight_rebalance.universe,
}

check_ledger(REVIEW_LEDGER)
_PINS: dict[tuple[str, str], Pin] = {
    (pin.strategy_id, pin.version): pin for pin in REVIEW_LEDGER
}
ALLOWLIST: Mapping[tuple[str, str], Entry] = MappingProxyType(
    {key: _DEFINITIONS[key] for key in _PINS}
)


def pin_for(strategy_id: str, version: str) -> Pin:
    """Return the reviewed pin of ``(id, version)``."""
    return _PINS[(strategy_id, version)]


def _lookup(strategy_id: Any, version: Any) -> tuple[str, str]:
    if not isinstance(strategy_id, str) or not _ID.fullmatch(strategy_id):
        raise ReviewedError(
            ErrorCode.SCHEMA, "bad_strategy_id", "not a reviewed strategy id"
        )
    versions = sorted(
        (ver for sid, ver in ALLOWLIST if sid == strategy_id), key=_version_key
    )
    if not versions:
        raise ReviewedError(
            ErrorCode.SCHEMA, "unknown_strategy", "strategy is not reviewed"
        )
    if version is None:
        if len(versions) != 1:
            raise ReviewedError(
                ErrorCode.SCHEMA, "version_required", "several versions are reviewed"
            )
        return strategy_id, versions[0]
    if (
        not isinstance(version, str)
        or not _SEMVER.fullmatch(version)
        or (strategy_id, version) not in ALLOWLIST
    ):
        raise ReviewedError(
            ErrorCode.SCHEMA, "unknown_version", "version is not reviewed"
        )
    return strategy_id, version


@dataclass(frozen=True)
class Verified:
    """Hashes recomputed from the local sources, equal to the pins."""

    strategy_id: str
    version: str
    code_sha256: str
    spec_sha256: str
    param_schema_sha256: str
    entry: Entry


def verify(
    strategy_id: Any, version: Any = None, *, root: Path | None = None
) -> Verified:
    """Recompute and compare every pinned hash against the local copy."""
    sid, ver = _lookup(strategy_id, version)
    entry, pin = ALLOWLIST[(sid, ver)], pin_for(sid, ver)
    code = code_sha256(
        root if root is not None else PACKAGE_ROOT, entry.spec.code_files
    )
    if code != pin.code_sha256:
        raise ReviewedError(
            ErrorCode.MODULE_ORIGIN,
            "strategy_code_drift",
            f"{sid}@{ver} sources differ from the reviewed pin",
        )
    schema = digest(entry.params_model.model_json_schema())
    if schema != pin.param_schema_sha256 or schema != entry.spec.param_schema_sha256:
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "param_schema_drift",
            f"{sid}@{ver} parameter schema differs from the reviewed pin",
        )
    if entry.spec.spec_sha256 != pin.spec_sha256:
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "strategy_spec_drift",
            f"{sid}@{ver} spec differs from the reviewed pin",
        )
    return Verified(sid, ver, code, pin.spec_sha256, schema, entry)


def _validate_params(entry: Entry, raw: Any) -> dict[str, Any]:
    try:
        model = entry.params_model.model_validate(raw)
    except ValidationError as exc:
        fields = sorted(
            {".".join(map(str, e["loc"])) or "params" for e in exc.errors()}
        )
        raise ReviewedError(
            ErrorCode.SCHEMA, "bad_params", "invalid fields: " + ", ".join(fields)
        ) from exc
    return plain(model.model_dump(mode="python"))


@dataclass(frozen=True)
class Binding:
    """A verified strategy, normalised params and execution for one run."""

    strategy_id: str
    version: str
    code_sha256: str
    spec_sha256: str
    param_schema_sha256: str
    params: dict[str, Any]
    params_sha256: str
    execution: ExecutionAssumptions
    symbols: tuple[str, ...]

    @property
    def execution_sha256(self) -> str:
        """Hash of the execution assumptions."""
        return self.execution.execution_sha256

    def request_fields(self) -> dict[str, Any]:
        """Return the ``run`` request v2 fields for this binding."""
        return {
            "strategy_ref": {
                "id": self.strategy_id,
                "version": self.version,
                "code_sha256": self.code_sha256,
                "spec_sha256": self.spec_sha256,
            },
            "params": dict(self.params),
            "params_sha256": self.params_sha256,
            "execution": self.execution.canonical(),
        }


def _bind(verified: Verified, params: Any, execution: ExecutionAssumptions) -> Binding:
    entry = verified.entry
    normalised = _validate_params(entry, params)
    entry.spec.check_execution(execution)
    universe = _UNIVERSE[(verified.strategy_id, verified.version)](
        entry.params_model.model_validate(normalised)
    )
    return Binding(
        strategy_id=verified.strategy_id,
        version=verified.version,
        code_sha256=verified.code_sha256,
        spec_sha256=verified.spec_sha256,
        param_schema_sha256=verified.param_schema_sha256,
        params=normalised,
        params_sha256=params_digest(verified.strategy_id, verified.version, normalised),
        execution=execution,
        symbols=universe,
    )


def resolve(
    strategy_id: Any,
    version: Any,
    params: Any,
    execution: Any,
    *,
    root: Path | None = None,
) -> Binding:
    """Facade side: verify, validate params and execution, bind."""
    verified = verify(strategy_id, version, root=root)
    return _bind(verified, params, parse_execution(execution))


def resolve_request(req: Any, *, root: Path | None = None) -> Binding:
    """Worker side: re-resolve a v2 request against the worker's own copy."""
    ref = req.strategy_ref
    verified = verify(ref.id, ref.version, root=root)
    if ref.code_sha256 != verified.code_sha256:
        raise ReviewedError(
            ErrorCode.MODULE_ORIGIN,
            "strategy_code_drift",
            "caller and worker disagree on the reviewed code",
        )
    if ref.spec_sha256 != verified.spec_sha256:
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "strategy_spec_drift",
            "caller and worker disagree on the reviewed spec",
        )
    binding = _bind(verified, req.params, req.execution)
    if binding.params_sha256 != req.params_sha256:
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "params_sha_mismatch",
            "params do not hash to the declared params_sha256",
        )
    return binding


def check_no_corporate_actions(manifest: Any) -> None:
    """Reject a window with splits, dividends or any corporate-action rows."""
    source, content = manifest.source, manifest.content
    if source.split_events or source.dividend_events or content.actions_rows:
        raise ReviewedError(
            ErrorCode.SCHEMA,
            "corporate_actions_present",
            "corporate actions in the window are not supported by this review",
        )


def run_binding(
    binding: Binding, dataset_id: str, engine_version: str
) -> dict[str, Any]:
    """Return the bound tuple: spec, code, params, execution, dataset, engine."""
    body = {
        "strategy_id": binding.strategy_id,
        "version": binding.version,
        "spec_sha256": binding.spec_sha256,
        "code_sha256": binding.code_sha256,
        "param_schema_sha256": binding.param_schema_sha256,
        "params_sha256": binding.params_sha256,
        "execution_sha256": binding.execution_sha256,
        "dataset_id": dataset_id,
        "engine_version": engine_version,
    }
    return {**body, "binding_sha256": digest(body)}
