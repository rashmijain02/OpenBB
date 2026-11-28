"""Content-addressed neutral dataset: manifest schema, digests and admission.

Pure module (no nautilus_trader): the facade uses it to write a dataset and the
worker uses it to admit one, so both sides run the same checks (#1355 T02).

A dataset directory holds ``bars.parquet``, ``actions.parquet`` and
``manifest.json``. ``dataset_id`` is the sha256 of the canonical manifest
*identity* (everything except ``files`` and ``writer``), so the id depends on
the content, not on the Parquet writer's bytes. Admission recomputes every
file hash, every content digest and the id itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .protocol import ErrorCode, ProtocolError, canonical_json

SCHEMA_VERSION = 1
TRANSFORM_VERSION = "neutral-1"
DATASET_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_NAME = "manifest.json"
BARS_FILE = "bars.parquet"
ACTIONS_FILE = "actions.parquet"
DATA_FILES = (BARS_FILE, ACTIONS_FILE)
# Source column scale: equity_historical prices are DECIMAL(15,6).
SOURCE_PRICE_DECIMALS = 6
# Standard (64-bit) Nautilus precision: 9 decimals, |price| <= ~9.22e9.
STANDARD_FIXED_PRECISION = 9
STANDARD_PRICE_MAX = 9_223_372_036

ActionBasis = Literal["raw_plus_actions", "split_adjusted_source"]

BARS_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("session", pa.date32()),
        ("ts_event", pa.int64()),
        ("ts_init", pa.int64()),
        ("open", pa.int64()),
        ("high", pa.int64()),
        ("low", pa.int64()),
        ("close", pa.int64()),
        ("volume", pa.int64()),
    ]
)
ACTIONS_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("ex_date", pa.date32()),
        ("kind", pa.string()),
        ("value", pa.string()),
    ]
)


class DatasetError(ProtocolError):
    """A rejected export or dataset; ``reason`` names the specific check."""

    def __init__(self, code: ErrorCode, reason: str, message: str):
        super().__init__(code, f"{reason}: {message}")
        self.reason = reason


_FROZEN = ConfigDict(extra="forbid", frozen=True)
_SHA = Field(pattern=r"^[0-9a-f]{64}$")


class CalendarFacts(BaseModel):
    """Calendar identity: code, library version and a digest of the sessions."""

    model_config = _FROZEN
    code: str
    exchange_calendars_version: str
    sessions_count: int = Field(ge=1)
    sessions_sha256: str = _SHA
    close_time_basis: Literal["session_close_utc"] = "session_close_utc"


class InstrumentFacts(BaseModel):
    """Per-instrument precision and coverage."""

    model_config = _FROZEN
    symbol: str = Field(pattern=r"^[A-Z0-9.\-]{1,16}$")
    price_precision: int = Field(ge=0, le=16)
    size_precision: Literal[0] = 0
    bar_count: int = Field(ge=1)


class SourceFacts(BaseModel):
    """Source provenance: label, query fingerprint and row counts (never rows)."""

    model_config = _FROZEN
    label: str
    query_sha256: str = _SHA
    adjustment_type: str
    rows_read: int = Field(ge=0)
    rows_used: int = Field(ge=0)
    filled_rows_dropped: int = Field(ge=0)
    invalid_rows_dropped: int = Field(ge=0)
    other_adjustment_rows_ignored: int = Field(ge=0)
    split_events: int = Field(ge=0)
    dividend_events: int = Field(ge=0)
    split_events_dropped: int = Field(ge=0)


class ContentFacts(BaseModel):
    """Writer-independent digests of the table contents."""

    model_config = _FROZEN
    bars_sha256: str = _SHA
    bars_rows: int = Field(ge=1)
    actions_sha256: str = _SHA
    actions_rows: int = Field(ge=0)


class Manifest(BaseModel):
    """``manifest.json`` of a neutral dataset."""

    model_config = _FROZEN
    schema_version: Literal[1] = 1
    transform_version: str = TRANSFORM_VERSION
    symbols: list[str]
    start: str
    end: str
    currency: Literal["USD"] = "USD"
    venue: Literal["SIM"] = "SIM"
    calendar: CalendarFacts
    action_basis: ActionBasis
    split_events_applied_to_prices: Literal[False] = False
    max_precision: int = Field(ge=0, le=16)
    instruments: list[InstrumentFacts]
    source: SourceFacts
    content: ContentFacts
    # Excluded from the dataset id (writer-dependent bytes).
    files: dict[str, str]
    writer: dict[str, str]


def sha256_hex(data: bytes) -> str:
    """Return the hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sessions_digest(sessions: list[date]) -> str:
    """Digest of an ordered list of session dates."""
    return sha256_hex("\n".join(d.isoformat() for d in sessions).encode("ascii"))


def _cell(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def table_digest(table: pa.Table) -> str:
    """Writer-independent digest of an Arrow table: schema + rows, canonical JSON."""
    header = [[f.name, str(f.type)] for f in table.schema]
    rows = [[_cell(v) for v in row.values()] for row in table.to_pylist()]
    return sha256_hex(canonical_json({"schema": header, "rows": rows}))


def identity(manifest: Manifest) -> dict[str, Any]:
    """Return the part of the manifest the dataset id is computed over."""
    return manifest.model_dump(mode="json", exclude={"files", "writer"})


def dataset_id(manifest: Manifest) -> str:
    """Content address of a dataset: sha256 of its canonical manifest identity."""
    return sha256_hex(canonical_json(identity(manifest)))


def manifest_bytes(manifest: Manifest) -> bytes:
    """Serialize ``manifest.json`` canonically, so it is byte-reproducible."""
    return canonical_json(manifest.model_dump(mode="json")) + b"\n"


def write_table(table: pa.Table, path: Path) -> str:
    """Write ``table`` deterministically and return the file sha256."""
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=False,
        store_schema=False,
    )
    return sha256_hex(path.read_bytes())


def discard_dir(path: Path) -> None:
    """Remove a temporary directory if it exists."""
    if path.exists():
        shutil.rmtree(path)


def replace_dir(tmp: Path, dest: Path) -> None:
    """Move a fully written ``tmp`` directory into place at ``dest``."""
    discard_dir(dest)
    tmp.rename(dest)


def _reject(code: ErrorCode, reason: str, message: str) -> DatasetError:
    return DatasetError(code, reason, message)


def resolve_dataset_dir(root: Path, ds_id: str) -> Path:
    """Map a 64-hex ``ds_id`` to its directory under ``root``; reject anything else."""
    if not isinstance(ds_id, str) or not DATASET_ID_RE.fullmatch(ds_id):
        raise _reject(ErrorCode.SCHEMA, "bad_dataset_id", "dataset id must be 64 hex")
    path = root / ds_id
    if not path.is_dir():
        raise _reject(ErrorCode.SCHEMA, "unknown_dataset", "dataset not found")
    if path.is_symlink() or os.path.isjunction(path):
        raise _reject(ErrorCode.SCHEMA, "link_rejected", "dataset dir is a link")
    return path


def check_precision(manifest: Manifest, fixed_precision: int) -> None:
    """Reject instruments whose declared precision exceeds the worker's."""
    for inst in manifest.instruments:
        if inst.price_precision > min(fixed_precision, manifest.max_precision):
            raise _reject(
                ErrorCode.ABI,
                "precision_beyond_worker",
                f"{inst.symbol} declares {inst.price_precision} decimals; "
                f"worker supports {fixed_precision}",
            )


def admit_dataset(root: Path, ds_id: str, fixed_precision: int) -> Manifest:
    """Verify a dataset end to end and return its manifest.

    Checks: id shape and location, no links, manifest schema, id == digest of the
    manifest identity, every file's sha256, every table's content digest, and
    declared precision against ``fixed_precision``.
    """
    path = resolve_dataset_dir(root, ds_id)
    for name in (MANIFEST_NAME, *DATA_FILES):
        file = path / name
        if not file.is_file() or file.is_symlink():
            raise _reject(ErrorCode.SCHEMA, "missing_file", f"{name} missing")
    try:
        manifest = Manifest.model_validate(
            json.loads((path / MANIFEST_NAME).read_bytes())
        )
    except (ValueError, ValidationError) as exc:
        raise _reject(ErrorCode.SCHEMA, "bad_manifest", "manifest invalid") from exc
    if dataset_id(manifest) != ds_id:
        raise _reject(ErrorCode.SCHEMA, "dataset_id_mismatch", "id != manifest")
    if sorted(manifest.files) != sorted(DATA_FILES):
        raise _reject(ErrorCode.SCHEMA, "bad_manifest", "unexpected file list")
    for name in DATA_FILES:
        if sha256_hex((path / name).read_bytes()) != manifest.files[name]:
            raise _reject(ErrorCode.SCHEMA, "file_hash_mismatch", f"{name} hash")
    bars = pq.read_table(path / BARS_FILE)
    actions = pq.read_table(path / ACTIONS_FILE)
    if not bars.schema.equals(BARS_SCHEMA) or not actions.schema.equals(ACTIONS_SCHEMA):
        raise _reject(ErrorCode.SCHEMA, "bad_schema", "table schema differs")
    if (
        table_digest(bars) != manifest.content.bars_sha256
        or table_digest(actions) != manifest.content.actions_sha256
    ):
        raise _reject(ErrorCode.SCHEMA, "content_digest_mismatch", "content digest")
    check_precision(manifest, fixed_precision)
    return manifest
