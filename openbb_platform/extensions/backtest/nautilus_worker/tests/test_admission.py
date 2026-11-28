"""``run`` request admission (#1355 T03, acceptance A2).

Datasets are built from the hand-computed oracle by the ``make_dataset``
fixture; every rejection is checked for its ``FailedLayer`` code (decision L5:
precision -> ``abi``, path/hash -> ``schema``, broker endpoint/credential ->
``egress``).
"""

# ruff: noqa: D103

from __future__ import annotations

import os
import shutil
import sys

import pytest
from openbb_nautilus_worker import (
    admission as adm,
    dataset as ds,
)
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError

SENTINEL = "SENTINEL-VALUE-7f3a"


def _body(ds_id: str, **over):
    body = {
        "dataset_id": ds_id,
        "strategy": "buy_and_hold",
        "starting_cash": "10000.00",
    }
    body.update(over)
    return body


def _admit(root, body, fixed_precision=9):
    req = adm.screen_request(body)
    return adm.admit_run(req, root, fixed_precision)


def _code(root, body, fixed_precision=9) -> tuple[str, str]:
    with pytest.raises(ProtocolError) as info:
        _admit(root, body, fixed_precision)
    return info.value.code.value, info.value.message


def test_admits_oracle_dataset(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    ds_id = make_dataset(root)
    admitted = _admit(root, _body(ds_id))
    assert admitted.request.venue == "SIM"
    assert admitted.manifest.symbols == ["BHX"]
    assert admitted.dataset_dir == root / ds_id


@pytest.mark.parametrize(
    "raw",
    [
        "C:\\data\\" + "a" * 56,
        "C:/data/" + "a" * 57,
        "/etc/" + "a" * 59,
        "\\\\server\\share\\" + "a" * 50,
        "..\\" + "a" * 61,
        "../" + "a" * 61,
        "a" * 32 + "/" + "a" * 31,
        "~/" + "a" * 62,
    ],
)
def test_rejects_absolute_dotdot_unc_drive_paths(tmp_path, make_dataset, raw):
    root = tmp_path / "datasets"
    make_dataset(root)
    code, message = _code(root, _body(raw))
    assert code == "schema"
    assert "raw_path" in message
    assert raw not in message


def test_rejects_symlink_or_junction_dataset_dir(tmp_path, make_dataset):
    real = tmp_path / "elsewhere"
    ds_id = make_dataset(real)
    root = tmp_path / "datasets"
    root.mkdir()
    link = root / ds_id
    if os.name == "nt":
        import _winapi  # pylint: disable=import-outside-toplevel

        _winapi.CreateJunction(str(real / ds_id), str(link))
    else:
        os.symlink(real / ds_id, link)
    code, message = _code(root, _body(ds_id))
    assert code == "schema" and "link_rejected" in message


def test_rejects_unknown_dataset_id(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    make_dataset(root)
    code, message = _code(root, _body("f" * 64))
    assert code == "schema" and "unknown_dataset" in message


def test_rejects_file_hash_mismatch(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    ds_id = make_dataset(root)
    bars = root / ds_id / ds.BARS_FILE
    data = bytearray(bars.read_bytes())
    data[len(data) // 2] ^= 0x01
    bars.write_bytes(bytes(data))
    code, message = _code(root, _body(ds_id))
    assert code == "schema" and "file_hash_mismatch" in message


def test_rejects_precision_mode_mismatch(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    ds_id = make_dataset(root)
    code, message = _code(root, _body(ds_id, precision_mode="high"), 9)
    assert code == "abi" and "precision_mode_mismatch" in message
    code, _ = _code(root, _body(ds_id, precision_mode="standard"), 16)
    assert code == "abi"


def test_rejects_dataset_precision_beyond_nine(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    ds_id = make_dataset(root, precision=10)
    code, message = _code(root, _body(ds_id), 9)
    assert code == "abi" and "precision_beyond_worker" in message
    shutil.rmtree(root)


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"venue": "IB"}, "venue"),
        ({"venue": "BINANCE"}, "venue"),
        ({"base_url": "https://api.example.invalid"}, "endpoint_field"),
        ({"endpoint": "wss://stream.example.invalid"}, "endpoint_field"),
        ({"host": "127.0.0.1"}, "endpoint_field"),
        ({"port": 7497}, "endpoint_field"),
        ({"api_key": SENTINEL}, "credential_field"),
        ({"apiSecret": SENTINEL}, "credential_field"),
        ({"token": SENTINEL}, "credential_field"),
        ({"account_id": SENTINEL}, "credential_field"),
        ({"password": SENTINEL}, "credential_field"),
        ({"trading_node": {"exec_clients": {}}}, "live_config"),
        ({"exec_clients": {"IB": {}}}, "live_config"),
        ({"strategy": "https://evil.example.invalid/x"}, "endpoint_value"),
        ({"strategy": "gateway.example.invalid:4001"}, "endpoint_value"),
        ({"starting_cash": "10.0.0.1"}, "endpoint_value"),
    ],
)
def test_request_schema_forbids_venue_endpoint_and_credentials(extra, reason):
    with pytest.raises(ProtocolError) as info:
        adm.screen_request(_body("a" * 64, **extra))
    assert info.value.code is ErrorCode.EGRESS
    assert reason in info.value.message
    assert SENTINEL not in info.value.message


def test_unknown_benign_field_and_bad_strategy_are_schema():
    for body in (
        _body("a" * 64, colour="blue"),
        _body("a" * 64, strategy="sma_cross"),
        _body("a" * 64, starting_cash="-5"),
        _body("a" * 64, deadline_seconds=10**6),
    ):
        with pytest.raises(ProtocolError) as info:
            adm.screen_request(body)
        assert info.value.code is ErrorCode.SCHEMA


def test_screen_is_pure_and_client_side_safe():
    """The facade imports admission; importing it must not pull nautilus."""
    assert "nautilus_trader" not in sys.modules
    req = adm.screen_request(_body("a" * 64))
    assert (req.venue, req.oms_type, req.account_type) == ("SIM", "NETTING", "CASH")
