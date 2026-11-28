"""Worker-side dataset admission and ``build_catalog`` op (#1355 T02).

Pure tests: datasets are built here with :mod:`openbb_nautilus_worker.dataset`
helpers (no facade import), the catalog writer is a fake. The real
``ParquetDataCatalog`` round trip is ``requires_nautilus`` (worker venv, T02-L).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from openbb_nautilus_worker import (
    catalog_build as cb,
    dataset as ds,
    protocol,
)
from openbb_nautilus_worker.dataset import DatasetError
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError

# 2024-11-29 is a half-day (13:00 New York = 18:00 UTC); 2024-12-02 a full day.
TS = [1732903200 * 10**9, 1733173200 * 10**9]


def _bars(close0: int = 20300) -> pa.Table:
    return pa.table(
        {
            "symbol": ["AAA", "AAA"],
            "session": [date(2024, 11, 29), date(2024, 12, 2)],
            "ts_event": TS,
            "ts_init": TS,
            "open": [20130, 10160],
            "high": [20340, 10220],
            "low": [20110, 10120],
            "close": [close0, 10175],
            "volume": [400000, 2100000],
        },
        schema=ds.BARS_SCHEMA,
    )


def _actions() -> pa.Table:
    return pa.table(
        {
            "symbol": ["AAA"],
            "ex_date": [date(2024, 12, 2)],
            "kind": ["split"],
            "value": ["2"],
        },
        schema=ds.ACTIONS_SCHEMA,
    )


def _make_dataset(root: Path, *, precision: int = 2, label: str = "synthetic") -> str:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / ".build"
    tmp.mkdir()
    bars, actions = _bars(), _actions()
    files = {
        ds.BARS_FILE: ds.write_table(bars, tmp / ds.BARS_FILE),
        ds.ACTIONS_FILE: ds.write_table(actions, tmp / ds.ACTIONS_FILE),
    }
    sessions = [date(2024, 11, 29), date(2024, 12, 2)]
    manifest = ds.Manifest(
        symbols=["AAA"],
        start="2024-11-29",
        end="2024-12-02",
        calendar=ds.CalendarFacts(
            code="XNYS",
            exchange_calendars_version="4.13.2",
            sessions_count=2,
            sessions_sha256=ds.sessions_digest(sessions),
        ),
        action_basis="raw_plus_actions",
        max_precision=9,
        instruments=[
            ds.InstrumentFacts(symbol="AAA", price_precision=precision, bar_count=2)
        ],
        source=ds.SourceFacts(
            label=label,
            query_sha256="0" * 64,
            adjustment_type="unadjusted",
            rows_read=2,
            rows_used=2,
            filled_rows_dropped=0,
            invalid_rows_dropped=0,
            other_adjustment_rows_ignored=0,
            split_events=1,
            dividend_events=0,
            split_events_dropped=0,
        ),
        content=ds.ContentFacts(
            bars_sha256=ds.table_digest(bars),
            bars_rows=2,
            actions_sha256=ds.table_digest(actions),
            actions_rows=1,
        ),
        files=files,
        writer={"pyarrow": pa.__version__},
    )
    ds_id = ds.dataset_id(manifest)
    (tmp / ds.MANIFEST_NAME).write_bytes(ds.manifest_bytes(manifest))
    tmp.rename(root / ds_id)
    return ds_id


def _rewrite_manifest(path: Path, **changes) -> None:
    man = json.loads((path / ds.MANIFEST_NAME).read_text())
    for dotted, value in changes.items():
        node = man
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    (path / ds.MANIFEST_NAME).write_text(json.dumps(man))


def _reason(fn, *args, **kw) -> DatasetError:
    with pytest.raises(DatasetError) as info:
        fn(*args, **kw)
    return info.value


# --- admission -------------------------------------------------------------------


def test_admit_accepts_valid_dataset(tmp_path):
    """Check: admit accepts valid dataset."""
    ds_id = _make_dataset(tmp_path)
    man = ds.admit_dataset(tmp_path, ds_id, fixed_precision=9)
    assert man.instruments[0].price_precision == 2
    assert ds.dataset_id(man) == ds_id


def test_rejects_file_hash_mismatch(tmp_path):
    """Check: rejects file hash mismatch."""
    ds_id = _make_dataset(tmp_path)
    actions = tmp_path / ds_id / ds.ACTIONS_FILE
    data = bytearray(actions.read_bytes())
    data[len(data) // 2] ^= 0x01
    actions.write_bytes(bytes(data))
    err = _reason(ds.admit_dataset, tmp_path, ds_id, 9)
    assert (err.reason, err.code) == ("file_hash_mismatch", ErrorCode.SCHEMA)


def test_rejects_rewritten_table_even_with_updated_file_hash(tmp_path):
    """Files/writer are outside the id, so the content digest must catch edits."""
    ds_id = _make_dataset(tmp_path)
    path = tmp_path / ds_id
    digest = ds.write_table(_bars(close0=99999), path / ds.BARS_FILE)
    man = json.loads((path / ds.MANIFEST_NAME).read_text())
    man["files"][ds.BARS_FILE] = digest
    (path / ds.MANIFEST_NAME).write_text(json.dumps(man))
    err = _reason(ds.admit_dataset, tmp_path, ds_id, 9)
    assert err.reason == "content_digest_mismatch"


def test_rejects_manifest_identity_edit(tmp_path):
    """Check: rejects manifest identity edit."""
    ds_id = _make_dataset(tmp_path)
    _rewrite_manifest(tmp_path / ds_id, source__label="edited")
    assert _reason(ds.admit_dataset, tmp_path, ds_id, 9).reason == "dataset_id_mismatch"


@pytest.mark.parametrize(
    "bad", ["../x", "A" * 64, "0" * 63, "C:/abs", "\\\\host\\share", "0" * 64]
)
def test_rejects_bad_or_unknown_dataset_id(tmp_path, bad):
    """Check: rejects bad or unknown dataset id."""
    _make_dataset(tmp_path)
    err = _reason(ds.admit_dataset, tmp_path, bad, 9)
    assert err.reason in {"bad_dataset_id", "unknown_dataset"}
    assert err.code == ErrorCode.SCHEMA


def test_rejects_precision_beyond_worker(tmp_path):
    """Check: rejects precision beyond worker."""
    ds_id = _make_dataset(tmp_path, precision=2)
    err = _reason(ds.admit_dataset, tmp_path, ds_id, 1)
    assert (err.reason, err.code) == ("precision_beyond_worker", ErrorCode.ABI)


def test_scaled_to_str_keeps_declared_places():
    """Check: scaled to str keeps declared places."""
    assert cb.scaled_to_str(20300, 2) == "203.00"
    assert cb.scaled_to_str(101234, 4) == "10.1234"
    assert cb.scaled_to_str(1, 3) == "0.001"
    assert cb.bar_type_str("AAA") == "AAA.SIM-1-DAY-LAST-EXTERNAL"


# --- build_catalog op ---------------------------------------------------------------


class _FakeWriter:
    def __init__(self):
        self.calls = 0

    def __call__(self, catalog_dir: Path, manifest, bars):
        self.calls += 1
        out = catalog_dir / "data" / "bar" / "part-0.json"
        out.parent.mkdir(parents=True)
        out.write_bytes(
            protocol.canonical_json(
                {
                    "instruments": [i.symbol for i in manifest.instruments],
                    "bars": [[b["symbol"], b["ts_event"], b["close"]] for b in bars],
                }
            )
        )
        return "fake-1.231.0"


def _env(tmp_path: Path) -> dict[str, str]:
    return {cb.DATA_ROOT_ENV: str(tmp_path)}


def test_build_catalog_records_stable_catalog_hash(tmp_path):
    """Check: build catalog records stable catalog hash."""
    ds_id = _make_dataset(tmp_path / "datasets")
    writer = _FakeWriter()
    first = cb.build_catalog(
        {"dataset_id": ds_id}, env=_env(tmp_path), writer=writer, fixed_precision=9
    )
    second = cb.build_catalog(
        {"dataset_id": ds_id}, env=_env(tmp_path), writer=writer, fixed_precision=9
    )
    assert first == second
    assert first["catalog_sha256"] == cb.tree_sha256(tmp_path / "catalogs" / ds_id)
    assert (first["bar_count"], first["instrument_count"]) == (2, 1)
    assert first["nautilus_version"] == "fake-1.231.0"
    assert str(tmp_path) not in json.dumps(first)
    assert not list((tmp_path / "catalogs").glob(".*.tmp"))


def test_catalog_hash_changes_with_content(tmp_path):
    """Check: catalog hash changes with content."""
    ds_id = _make_dataset(tmp_path / "datasets")
    before = cb.build_catalog(
        {"dataset_id": ds_id},
        env=_env(tmp_path),
        writer=_FakeWriter(),
        fixed_precision=9,
    )
    (tmp_path / "catalogs" / ds_id / "extra.bin").write_bytes(b"x")
    assert cb.tree_sha256(tmp_path / "catalogs" / ds_id) != before["catalog_sha256"]


def test_build_catalog_verifies_before_writing(tmp_path):
    """Check: build catalog verifies before writing."""
    ds_id = _make_dataset(tmp_path / "datasets")
    bars = tmp_path / "datasets" / ds_id / ds.BARS_FILE
    bars.write_bytes(bars.read_bytes() + b"\0")
    writer = _FakeWriter()
    with pytest.raises(DatasetError) as info:
        cb.build_catalog(
            {"dataset_id": ds_id}, env=_env(tmp_path), writer=writer, fixed_precision=9
        )
    assert info.value.reason == "file_hash_mismatch"
    assert writer.calls == 0
    assert not (tmp_path / "catalogs" / ds_id).exists()


@pytest.mark.parametrize(
    "body",
    [{}, {"dataset_id": "../../etc"}, {"dataset_id": "0" * 64, "path": "C:/x"}],
)
def test_build_catalog_request_schema(tmp_path, body):
    """Check: build catalog request schema."""
    with pytest.raises(ProtocolError) as info:
        cb.build_catalog(
            body, env=_env(tmp_path), writer=_FakeWriter(), fixed_precision=9
        )
    assert info.value.code == ErrorCode.SCHEMA


def test_build_catalog_requires_absolute_data_root(tmp_path):
    """Check: build catalog requires absolute data root."""
    for env in ({}, {cb.DATA_ROOT_ENV: "relative/dir"}):
        with pytest.raises(ProtocolError) as info:
            cb.build_catalog(
                {"dataset_id": "0" * 64},
                env=env,
                writer=_FakeWriter(),
                fixed_precision=9,
            )
        assert info.value.code == ErrorCode.CONFIG


def test_build_catalog_is_a_known_signed_op():
    """Check: build catalog is a known signed op."""
    key = b"k" * 32
    req = protocol.sign_request(key, 1, "build_catalog", {"dataset_id": "0" * 64})
    raw = json.loads(protocol.encode_frame(req))
    assert protocol.verify_request(key, raw, 1).op == "build_catalog"


@pytest.mark.requires_nautilus
def test_worker_catalog_build_round_trip(tmp_path):
    """Bars read back from ParquetDataCatalog equal the neutral values; hash stable."""
    # pylint: disable=import-outside-toplevel,import-error
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    ds_id = _make_dataset(tmp_path / "datasets")
    first = cb.build_catalog({"dataset_id": ds_id}, env=_env(tmp_path))
    second = cb.build_catalog({"dataset_id": ds_id}, env=_env(tmp_path))
    assert first["catalog_sha256"] == second["catalog_sha256"]
    catalog = ParquetDataCatalog(str(tmp_path / "catalogs" / ds_id))
    bars = catalog.bars()
    expected = pq.read_table(tmp_path / "datasets" / ds_id / ds.BARS_FILE).to_pylist()
    assert [(str(b.close), b.ts_event) for b in bars] == [
        (cb.scaled_to_str(r["close"], 2), r["ts_event"]) for r in expected
    ]


# --- placing a dataset dir (#1355 CODE-5) ------------------------------------------


def _tmp_copy(root: Path, ds_id: str) -> Path:
    tmp = root / ".incoming.tmp"
    tmp.mkdir()
    for name in (ds.MANIFEST_NAME, *ds.DATA_FILES):
        (tmp / name).write_bytes((root / ds_id / name).read_bytes())
    return tmp


def test_place_keeps_existing_dataset_that_admits(tmp_path):
    """An existing dest with the same id is kept, never rmtree'd."""
    ds_id = _make_dataset(tmp_path)
    sentinel = tmp_path / ds_id / "kept.marker"
    sentinel.write_bytes(b"original")
    tmp = _tmp_copy(tmp_path, ds_id)
    ds.place_dataset_dir(tmp, tmp_path / ds_id, ds_id)
    assert sentinel.read_bytes() == b"original"
    assert not tmp.exists()
    ds.admit_dataset(tmp_path, ds_id, 9)


def test_place_refuses_existing_dir_that_does_not_admit(tmp_path):
    """A corrupt dest is a DatasetError and is left for the owner (not deleted)."""
    ds_id = _make_dataset(tmp_path)
    tmp = _tmp_copy(tmp_path, ds_id)
    bars = tmp_path / ds_id / ds.BARS_FILE
    bars.write_bytes(bars.read_bytes() + b"\0")
    err = _reason(ds.place_dataset_dir, tmp, tmp_path / ds_id, ds_id)
    assert (err.reason, err.code) == ("dataset_dir_conflict", ErrorCode.SCHEMA)
    assert bars.exists()


def test_place_moves_new_dataset_into_place(tmp_path):
    """A fresh id is renamed into place."""
    ds_id = _make_dataset(tmp_path)
    tmp = _tmp_copy(tmp_path, ds_id)
    other = tmp_path / "other"
    other.mkdir()
    ds.place_dataset_dir(tmp, other / ds_id, ds_id)
    ds.admit_dataset(other, ds_id, 9)


def test_replace_dir_os_error_is_dataset_error(tmp_path, monkeypatch):
    """A locked dest (PermissionError on Windows) surfaces as a DatasetError."""
    (tmp_path / "dest").mkdir()
    (tmp_path / "tmp").mkdir()

    def locked(_path):
        raise PermissionError("file in use")

    monkeypatch.setattr(ds.shutil, "rmtree", locked)
    err = _reason(ds.replace_dir, tmp_path / "tmp", tmp_path / "dest")
    assert (err.reason, err.code) == ("replace_failed", ErrorCode.PROCESS)
