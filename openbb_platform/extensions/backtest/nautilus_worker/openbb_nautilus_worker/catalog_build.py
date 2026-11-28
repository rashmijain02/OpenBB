"""Worker op ``build_catalog``: admitted neutral dataset -> Nautilus catalog.

Imports ``nautilus_trader`` lazily inside :func:`nautilus_writer` only. The
request carries only an opaque ``dataset_id``; locations come from
``OPENBB_NAUTILUS_DATA_ROOT`` (decision L8: outside the repo), with datasets
under ``datasets/<id>`` and catalogs under ``catalogs/<id>``. Every file and
content hash is verified (:func:`dataset.admit_dataset`) before anything is
written. The response holds hashes and counts, never paths.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import dataset as ds
from .describe import PRECISION_MODULE
from .protocol import ErrorCode, ProtocolError, canonical_json

DATA_ROOT_ENV = "OPENBB_NAUTILUS_DATA_ROOT"
VENUE = "SIM"
BAR_SPEC = "1-DAY-LAST-EXTERNAL"

Writer = Callable[[Path, ds.Manifest, list[dict[str, Any]]], str]


class BuildCatalogRequest(BaseModel):
    """``build_catalog`` body: the dataset id and nothing else."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: str = Field(pattern=r"^[0-9a-f]{64}$")


def scaled_to_str(scaled: int, places: int) -> str:
    """Render a scaled integer with exactly ``places`` decimals (``2000, 2 -> 20.00``)."""
    return str(Decimal(scaled).scaleb(-places))


def bar_type_str(symbol: str) -> str:
    """Bar type string for ``symbol`` on the simulated venue."""
    return f"{symbol}.{VENUE}-{BAR_SPEC}"


def tree_sha256(root: Path) -> str:
    """Digest over every file under ``root``: sorted relative path + file sha256."""
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProtocolError(ErrorCode.SCHEMA, "catalog contains a link")
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append([path.relative_to(root).as_posix(), digest])
    return hashlib.sha256(canonical_json(entries)).hexdigest()


def runtime_fixed_precision() -> int:
    """``FIXED_PRECISION`` of the installed nautilus_trader."""
    return int(importlib.import_module(PRECISION_MODULE).FIXED_PRECISION)


def nautilus_writer(  # pylint: disable=too-many-locals
    catalog_dir: Path, manifest: ds.Manifest, bars: list[dict[str, Any]]
) -> str:  # pragma: no cover - needs nautilus_trader (worker venv, LIVE T02-L)
    """Write ``Equity`` instruments and daily bars to a ``ParquetDataCatalog``."""
    # pylint: disable=import-outside-toplevel,import-error
    import nautilus_trader
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    catalog = ParquetDataCatalog(str(catalog_dir))
    for inst in manifest.instruments:
        places = inst.price_precision
        equity = Equity(
            instrument_id=InstrumentId.from_str(f"{inst.symbol}.{VENUE}"),
            raw_symbol=Symbol(inst.symbol),
            currency=USD,
            price_precision=places,
            price_increment=Price.from_str(scaled_to_str(1, places)),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )
        catalog.write_data([equity])
        bar_type = BarType.from_str(bar_type_str(inst.symbol))

        def price(value: int, places: int = places) -> Any:
            return Price.from_str(scaled_to_str(value, places))

        catalog.write_data(
            [
                Bar(
                    bar_type,
                    price(row["open"]),
                    price(row["high"]),
                    price(row["low"]),
                    price(row["close"]),
                    Quantity.from_int(row["volume"]),
                    row["ts_event"],
                    row["ts_init"],
                )
                for row in bars
                if row["symbol"] == inst.symbol
            ]
        )
    return str(nautilus_trader.__version__)


def _data_root(env: Mapping[str, str]) -> Path:
    raw = env.get(DATA_ROOT_ENV)
    if not raw or not Path(raw).is_absolute():
        raise ProtocolError(ErrorCode.CONFIG, f"{DATA_ROOT_ENV} must be absolute")
    return Path(raw)


def build_catalog(
    body: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    writer: Writer | None = None,
    fixed_precision: int | None = None,
) -> dict[str, Any]:
    """Admit the dataset, build its catalog atomically and report its hash."""
    try:
        req = BuildCatalogRequest.model_validate(body)
    except ValidationError as exc:
        raise ProtocolError(ErrorCode.SCHEMA, "bad build_catalog request") from exc
    root = _data_root(os.environ if env is None else env)
    if fixed_precision is None:
        fixed_precision = runtime_fixed_precision()
    manifest = ds.admit_dataset(root / "datasets", req.dataset_id, fixed_precision)
    bars = pq.read_table(root / "datasets" / req.dataset_id / ds.BARS_FILE)

    catalogs = root / "catalogs"
    catalogs.mkdir(parents=True, exist_ok=True)
    tmp = catalogs / f".{req.dataset_id}.tmp"
    dest = catalogs / req.dataset_id
    ds.discard_dir(tmp)
    tmp.mkdir()
    try:
        version = (writer or nautilus_writer)(tmp, manifest, bars.to_pylist())
        catalog_sha = tree_sha256(tmp)
        files = sum(1 for p in tmp.rglob("*") if p.is_file())
        if not files:
            raise ProtocolError(ErrorCode.PROCESS, "catalog writer wrote no files")
        ds.replace_dir(tmp, dest)
    finally:
        ds.discard_dir(tmp)
    return {
        "dataset_id": req.dataset_id,
        "catalog_sha256": catalog_sha,
        "nautilus_version": version,
        "instrument_count": len(manifest.instruments),
        "bar_count": bars.num_rows,
        "file_count": files,
        "action_basis": manifest.action_basis,
    }
