"""``run`` request admission (#1355 T03, acceptance A2).

Pure module (no nautilus_trader): the facade imports :func:`screen_request`
to fail fast and the worker runs the full :func:`admit_run` authoritatively,
so both sides run the same checks. Error codes follow decision L5: broker
venue / endpoint / credential => ``egress``; raw path, unknown id or wrong
hash => ``schema``; precision => ``abi``. Messages name the check and the
offending *field*, never the offending value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import dataset as ds
from .protocol import ErrorCode
from .reviewed import (
    params as reviewed_params,
    registry,
)
from .reviewed.spec import ExecutionAssumptions, StrategyRef

MAX_DEADLINE_SECONDS = 3600
DEFAULT_DEADLINE_SECONDS = 600
STANDARD_FIXED_PRECISION = ds.STANDARD_FIXED_PRECISION
HIGH_FIXED_PRECISION = 16

_ENDPOINT_KEY = re.compile(
    r"url|uri|endpoint|host|port|socket|address|gateway|proxy|server|domain|dns",
    re.I,
)
_CREDENTIAL_KEY = re.compile(
    r"api_?key|apikey|secret|token|password|passwd|passphrase|credential|account|"
    r"user_?name|login|private_?key|mnemonic|wallet|cookie|session|auth|signature",
    re.I,
)
_LIVE_KEY = re.compile(
    r"trading_?node|exec(ution)?_clients|data_clients|live|broker|instrument_provider",
    re.I,
)
_URL_VALUE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.I)
_HOST_PORT_VALUE = re.compile(r"^[\w.\-]+:\d{1,5}$")
_IP_VALUE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_PATH_VALUE = re.compile(r"(^[A-Za-z]:)|(^[\\/~])|[\\/]|(^|[\\/])\.\.")


class RunRequest(BaseModel):
    """``run`` body. Simulated venue, netting OMS, cash account, zero fees."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    # v1 alias (the #1355 probe and LIVE commands) XOR the reviewed v2 set.
    strategy: Literal["buy_and_hold"] | None = None
    strategy_ref: StrategyRef | None = None
    params: dict[str, Any] | None = None
    params_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    execution: ExecutionAssumptions | None = None
    venue: Literal["SIM"] = "SIM"
    oms_type: Literal["NETTING"] = "NETTING"
    account_type: Literal["CASH"] = "CASH"
    currency: Literal["USD"] = "USD"
    fees: Literal["zero"] = "zero"
    starting_cash: str = Field(
        default="10000.00", pattern=r"^[0-9]{1,12}(\.[0-9]{1,2})?$"
    )
    precision_mode: Literal["standard", "high"] = "standard"
    deadline_seconds: int = Field(
        default=DEFAULT_DEADLINE_SECONDS, ge=1, le=MAX_DEADLINE_SECONDS
    )

    @model_validator(mode="after")
    def _one_form(self) -> RunRequest:
        v2 = (self.strategy_ref, self.params, self.params_sha256, self.execution)
        if self.strategy is not None:
            if any(item is not None for item in v2):
                raise ValueError("strategy alias excludes the strategy_ref fields")
        else:
            if any(item is None for item in v2):
                raise ValueError("strategy or the full strategy_ref set is required")
            if "fees" in self.model_fields_set:
                raise ValueError("fees come from execution")
        return self


_ALLOWED_KEYS = frozenset(RunRequest.model_fields)
# Nested names of the reviewed v2 objects are declared fields, not credentials
# (``execution.account`` is the CASH account type). Values are still screened.
_NESTED_ROOTS = frozenset({"strategy_ref", "execution", "params"})
_NESTED_KEYS = (
    frozenset(StrategyRef.model_fields)
    | frozenset(ExecutionAssumptions.model_fields)
    | frozenset(reviewed_params.BuyAndHoldParams.model_fields)
    | frozenset(reviewed_params.TargetWeightRebalanceParams.model_fields)
)


@dataclass(frozen=True)
class Admitted:
    """An admitted run: request, verified manifest, directory and bars.

    bars is parsed from the verified bytes and is never re-read from disk.
    """

    request: RunRequest
    manifest: ds.Manifest
    dataset_dir: Path
    bars: pa.Table
    binding: registry.Binding | None = None


def _reject(code: ErrorCode, reason: str, message: str) -> ds.DatasetError:
    return ds.DatasetError(code, reason, message)


def _walk(obj: Any, prefix: str = ""):
    """Yield ``(dotted_key, value)`` for every key and leaf in ``obj``."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, str(key), value
            yield from _walk(value, path)
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            yield f"{prefix}[{i}]", str(i), value
            yield from _walk(value, f"{prefix}[{i}]")


def _screen_keys_and_values(body: dict[str, Any]) -> None:
    for path, key, value in _walk(body):
        root = path.split(".")[0].split("[")[0]
        known = ("." not in path and "[" not in path and key in _ALLOWED_KEYS) or (
            root in _NESTED_ROOTS
            and (
                key in _NESTED_KEYS
                or (path.startswith("params.weights.") and path.count(".") == 2)
            )
        )
        if not known:
            if _LIVE_KEY.search(key):
                raise _reject(ErrorCode.EGRESS, "live_config", f"field {path!r}")
            if _ENDPOINT_KEY.search(key):
                raise _reject(ErrorCode.EGRESS, "endpoint_field", f"field {path!r}")
            if _CREDENTIAL_KEY.search(key):
                raise _reject(ErrorCode.EGRESS, "credential_field", f"field {path!r}")
        if isinstance(value, str) and (
            _URL_VALUE.match(value)
            or _HOST_PORT_VALUE.match(value)
            or _IP_VALUE.match(value)
        ):
            raise _reject(ErrorCode.EGRESS, "endpoint_value", f"field {path!r}")
    venue = body.get("venue", "SIM")
    if venue != "SIM":
        raise _reject(ErrorCode.EGRESS, "venue", "only the simulated venue SIM")


def screen_request(body: Any) -> RunRequest:
    """Pure, filesystem-free checks shared by the client and the worker."""
    if not isinstance(body, dict):
        raise _reject(ErrorCode.SCHEMA, "bad_request", "body must be an object")
    _screen_keys_and_values(body)
    raw_id = body.get("dataset_id")
    if isinstance(raw_id, str) and _PATH_VALUE.search(raw_id):
        raise _reject(ErrorCode.SCHEMA, "raw_path", "dataset_id must be an opaque id")
    try:
        return RunRequest.model_validate(body)
    except ValidationError as exc:
        fields = sorted(
            {".".join(map(str, e["loc"])) or "request" for e in exc.errors()}
        )
        raise _reject(
            ErrorCode.SCHEMA, "bad_request", "invalid fields: " + ", ".join(fields)
        ) from exc


def check_precision_mode(req: RunRequest, fixed_precision: int) -> None:
    """Reject a requested precision mode that differs from the worker build."""
    expected = (
        HIGH_FIXED_PRECISION
        if req.precision_mode == "high"
        else STANDARD_FIXED_PRECISION
    )
    if fixed_precision != expected:
        raise _reject(
            ErrorCode.ABI,
            "precision_mode_mismatch",
            f"requested {req.precision_mode}; worker FIXED_PRECISION={fixed_precision}",
        )


def admit_run(req: RunRequest, datasets_root: Path, fixed_precision: int) -> Admitted:
    """Authoritative worker-side admission of a screened request."""
    check_precision_mode(req, fixed_precision)
    binding = registry.resolve_request(req) if req.strategy_ref is not None else None
    root = Path(datasets_root)
    path = ds.resolve_dataset_dir(root, req.dataset_id)
    if path.resolve().parent != root.resolve():
        raise _reject(ErrorCode.SCHEMA, "link_rejected", "dataset escapes the root")
    admitted = ds.load_dataset(root, req.dataset_id, fixed_precision)
    manifest = admitted.manifest
    one_symbol = req.strategy == "buy_and_hold" or (
        binding is not None and binding.strategy_id == "buy_and_hold"
    )
    if one_symbol and len(manifest.instruments) != 1:
        raise _reject(
            ErrorCode.SCHEMA, "bad_request", "buy_and_hold needs exactly one symbol"
        )
    if binding is not None:
        registry.check_no_corporate_actions(manifest)
        if not set(binding.symbols) <= set(manifest.symbols):
            raise _reject(
                ErrorCode.SCHEMA,
                "universe_not_in_dataset",
                "strategy symbols are not all in the dataset",
            )
    return Admitted(
        request=req,
        manifest=manifest,
        dataset_dir=path,
        bars=admitted.bars,
        binding=binding,
    )
