"""Reviewed strategy metadata, allowlist and drift rejection (#1356 T01).

Acceptance A1 (hashes bind code, params, timing, sizing and output to the run)
and A2 (unreviewed or drifted strategy => rejected, no silent fallback).
Expected hashes are recomputed here with ``hashlib`` over the real source files
and compared with the pins; the shipped receipts below are the reviewed
literals for the 1.0.0 versions (changing a reviewed file means a new version
plus a new receipt, never an in-place re-pin).
"""

# ruff: noqa: D103

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.metadata
import json
import shutil
from decimal import Decimal
from pathlib import Path

import fake_engine
import pytest
from openbb_nautilus_worker import (
    admission as adm,
    dataset as ds,
    runs,
)
from openbb_nautilus_worker.catalog_build import DATA_ROOT_ENV
from openbb_nautilus_worker.protocol import ErrorCode, ProtocolError
from openbb_nautilus_worker.reviewed import (
    hashing,
    registry,
    spec as spec_mod,
)
from openbb_nautilus_worker.reviewed.errors import ReviewedError

PKG = Path(registry.__file__).resolve().parents[1]
BAH, TWR = "buy_and_hold", "target_weight_rebalance"
RECEIPTS: dict[tuple[str, str], dict[str, str]] = {
    (BAH, "1.0.0"): {
        "code_sha256": "902955c7e28f4135e98ea453e6abc7baf836e76175f7329e6fdbe913cf136575",
        "param_schema_sha256": "2154e944794a16b4465e64b0798fa95c932eae6839f587c550c4ddd725dddc66",
        "spec_sha256": "fb5ad1e5dd9877cf88eae922b4f626e6ceb5e4283d0d73d1afb9c836b36c0184",
    },
    (TWR, "1.0.0"): {
        "code_sha256": "902955c7e28f4135e98ea453e6abc7baf836e76175f7329e6fdbe913cf136575",
        "param_schema_sha256": "611597da61879e314df15f3441e17d59c66bf04417f98ff499786b5fc98a3a3e",
        "spec_sha256": "9eef1f20509a63e2a617678b826efc0465eb160544f9fe18aab7705af1a0de4f",
    },
}


def _independent_code_hash(root: Path, files) -> str:
    rows = []
    for rel in files:
        data = (root / rel).read_bytes().replace(b"\r\n", b"\n")
        rows.append([rel, hashlib.sha256(data).hexdigest()])
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(blob).hexdigest()


def _copy_pkg(tmp_path: Path, crlf: bool = False) -> Path:
    dst = tmp_path / "pkg"
    shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__"))
    if crlf:
        for path in dst.rglob("*.py"):
            # Normalise first: a Windows checkout with core.autocrlf is already CRLF.
            lf = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(lf.replace(b"\n", b"\r\n"))
    return dst


def _reason(exc: pytest.ExceptionInfo[ReviewedError]) -> tuple[str, str]:
    return exc.value.code.value, exc.value.reason


PARAMS = {
    BAH: {"symbols": ["BHX"]},
    TWR: {"weights": {"AAA": "0.5", "BBB": "0.5"}, "rebalance_every_sessions": 2},
}


def test_receipts_match_ledger():
    assert RECEIPTS, "receipts must be filled"
    for (sid, ver), want in RECEIPTS.items():
        pin = registry.pin_for(sid, ver)
        assert {
            "code_sha256": pin.code_sha256,
            "param_schema_sha256": pin.param_schema_sha256,
            "spec_sha256": pin.spec_sha256,
        } == want


def test_only_two_strategies_reviewed():
    assert set(registry.ALLOWLIST) == {(BAH, "1.0.0"), (TWR, "1.0.0")}


def test_pinned_code_hashes_match_sources():
    for (sid, ver), entry in registry.ALLOWLIST.items():
        want = _independent_code_hash(PKG, entry.spec.code_files)
        assert registry.pin_for(sid, ver).code_sha256 == want
        assert registry.verify(sid, ver).code_sha256 == want


def _local_imports(path: Path) -> set[str]:
    """Return reviewed-package modules a source file imports (relative imports)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module)
            else:
                found.update(a.name for a in node.names)
    return found


def test_every_strategy_fingerprints_all_files_the_host_imports():
    reviewed = PKG / "reviewed"
    closure, todo = {"host"}, ["host"]
    while todo:
        for mod in _local_imports(reviewed / f"{todo.pop()}.py"):
            if mod not in closure:
                closure.add(mod)
                todo.append(mod)
    want = {f"reviewed/{m}.py" for m in closure}
    assert "reviewed/target_weight_rebalance.py" in want
    for (sid, ver), entry in registry.ALLOWLIST.items():
        assert want <= set(entry.spec.code_files), (
            sid,
            ver,
            sorted(want - set(entry.spec.code_files)),
        )


def test_code_hash_lf_normalised(tmp_path):
    crlf = _copy_pkg(tmp_path, crlf=True)
    assert (crlf / "reviewed" / "spec.py").read_bytes().count(b"\r\n") > 10
    for sid, ver in registry.ALLOWLIST:
        assert registry.verify(sid, ver, root=crlf).code_sha256 == (
            registry.pin_for(sid, ver).code_sha256
        )


def test_params_hash_canonical():
    base = registry.resolve(TWR, "1.0.0", PARAMS[TWR], None)
    variants = [
        {"rebalance_every_sessions": 2, "weights": {"BBB": "0.50", "AAA": "0.5"}},
        {
            "weights": {"AAA": 0.5, "BBB": Decimal("0.500")},
            "rebalance_every_sessions": 2,
        },
        {"weights": {"AAA": "5E-1", "BBB": "0.5"}, "rebalance_every_sessions": 2},
    ]
    for raw in variants:
        got = registry.resolve(TWR, "1.0.0", raw, None)
        assert got.params_sha256 == base.params_sha256
        assert got.params == base.params
    one = registry.resolve(
        TWR, "1.0.0", {"weights": {"AAA": 1.0}, "rebalance_every_sessions": 1}, None
    )
    for w in ("1", Decimal("1.00"), "1.000"):
        other = registry.resolve(
            TWR, "1.0.0", {"weights": {"AAA": w}, "rebalance_every_sessions": 1}, None
        )
        assert other.params_sha256 == one.params_sha256
    changed = registry.resolve(
        TWR, "1.0.0", {**PARAMS[TWR], "rebalance_every_sessions": 3}, None
    )
    assert changed.params_sha256 != base.params_sha256
    # id and version are part of the hashed object
    assert hashing.params_digest("a", "1.0.0", {}) != hashing.params_digest(
        "b", "1.0.0", {}
    )
    assert hashing.params_digest("a", "1.0.0", {}) != hashing.params_digest(
        "a", "1.0.1", {}
    )


def test_execution_hash_expands_defaults_and_binds_timing():
    a = registry.resolve(BAH, "1.0.0", PARAMS[BAH], None)
    b = registry.resolve(BAH, "1.0.0", PARAMS[BAH], {"fill_timing": "next_open"})
    assert a.execution_sha256 == b.execution_sha256
    c = registry.resolve(BAH, "1.0.0", PARAMS[BAH], {"fill_timing": "same_close"})
    assert c.execution_sha256 != a.execution_sha256
    d = registry.resolve(BAH, "1.0.0", PARAMS[BAH], {"settlement": "T+2"})
    e = registry.resolve(
        BAH, "1.0.0", PARAMS[BAH], {"fees": "taker_bps", "taker_bps": "10.0"}
    )
    f = registry.resolve(
        BAH, "1.0.0", PARAMS[BAH], {"fees": "taker_bps", "taker_bps": "10"}
    )
    assert len({a.execution_sha256, c.execution_sha256, d.execution_sha256}) == 3
    assert e.execution_sha256 == f.execution_sha256 != a.execution_sha256


def test_spec_hash_changes_with_each_assumption():
    base = registry.ALLOWLIST[(BAH, "1.0.0")].spec
    seen = {base.spec_sha256}
    for name in ("fill_timing", "sizing", "settlement", "booking", "fees"):
        supported = base.supported.model_copy(
            update={name: (*getattr(base.supported, name), "extra_value")}
        )
        mutated = base.model_copy(update={"supported": supported})
        assert mutated.spec_sha256 not in seen, name
        seen.add(mutated.spec_sha256)
    bumped = base.model_copy(update={"version": "1.0.1"})
    files = base.model_copy(update={"code_files": (*base.code_files, "reviewed/x.py")})
    assert {bumped.spec_sha256, files.spec_sha256}.isdisjoint(seen)


def test_param_schema_hash_pinned():
    for (sid, ver), entry in registry.ALLOWLIST.items():
        schema = entry.params_model.model_json_schema()
        blob = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
        want = hashlib.sha256(blob).hexdigest()
        assert registry.pin_for(sid, ver).param_schema_sha256 == want
        assert entry.spec.param_schema_sha256 == want


def test_one_byte_code_change_rejected_module_origin(tmp_path):
    root = _copy_pkg(tmp_path)
    target = root / "reviewed" / "params.py"
    target.write_bytes(target.read_bytes() + b" ")
    for sid, ver in registry.ALLOWLIST:
        with pytest.raises(ReviewedError) as info:
            registry.verify(sid, ver, root=root)
        assert _reason(info) == ("module_origin", "strategy_code_drift")
    # an untouched copy is fine, so the failure above is the byte, not the copy
    clean = _copy_pkg(tmp_path / "clean")
    assert registry.verify(BAH, "1.0.0", root=clean).code_sha256


def test_missing_reviewed_file_rejected(tmp_path):
    root = _copy_pkg(tmp_path)
    (root / "reviewed" / "hashing.py").unlink()
    with pytest.raises(ReviewedError) as info:
        registry.verify(BAH, "1.0.0", root=root)
    assert _reason(info) == ("module_origin", "strategy_code_drift")


def test_params_sha_mismatch_rejected_schema():
    binding = registry.resolve(BAH, "1.0.0", PARAMS[BAH], None)
    fields = binding.request_fields()
    fields["params"] = {"symbols": ["OTHER"]}  # params changed, hash kept
    with pytest.raises(ReviewedError) as info:
        registry.resolve_request(adm.screen_request({"dataset_id": "0" * 64, **fields}))
    assert _reason(info) == ("schema", "params_sha_mismatch")


def test_stale_peer_code_hash_rejected_module_origin():
    fields = registry.resolve(BAH, "1.0.0", PARAMS[BAH], None).request_fields()
    fields["strategy_ref"] = {**fields["strategy_ref"], "code_sha256": "ab" * 32}
    with pytest.raises(ReviewedError) as info:
        registry.resolve_request(adm.screen_request({"dataset_id": "0" * 64, **fields}))
    assert _reason(info) == ("module_origin", "strategy_code_drift")


def test_spec_sha_mismatch_rejected_schema():
    fields = registry.resolve(BAH, "1.0.0", PARAMS[BAH], None).request_fields()
    fields["strategy_ref"] = {**fields["strategy_ref"], "spec_sha256": "cd" * 32}
    with pytest.raises(ReviewedError) as info:
        registry.resolve_request(adm.screen_request({"dataset_id": "0" * 64, **fields}))
    assert _reason(info) == ("schema", "strategy_spec_drift")


@pytest.mark.parametrize(
    "sid, params",
    [
        (TWR, {"weights": {"AAA": "0.6", "BBB": "0.6"}, "rebalance_every_sessions": 2}),
        (TWR, {"weights": {"AAA": "-0.1"}, "rebalance_every_sessions": 2}),
        (TWR, {"weights": {"AAA": "1.5"}, "rebalance_every_sessions": 2}),
        (TWR, {"weights": {}, "rebalance_every_sessions": 2}),
        (TWR, {"weights": {"AAA": "NaN"}, "rebalance_every_sessions": 2}),
        (TWR, {"weights": {"AAA": "0.5"}, "rebalance_every_sessions": 0}),
        (TWR, {"weights": {"AAA": "0.5"}, "rebalance_every_sessions": 253}),
        (TWR, {"weights": {"AAA": "0.5"}, "rebalance_every_sessions": 2.5}),
        (TWR, {"weights": {"AAA": "0.5"}, "rebalance_every_sessions": 2, "x": 1}),
        (TWR, {"weights": {"aaa": "0.5"}, "rebalance_every_sessions": 2}),
        (BAH, {"symbols": []}),
        (BAH, {"symbols": ["AAA", "AAA"]}),
        (BAH, {"symbols": [f"S{i}" for i in range(51)]}),
        (BAH, {"symbols": ["../x"]}),
        (BAH, {"symbols": ["AAA"], "weights": {}}),
    ],
)
def test_out_of_bounds_params_rejected(sid, params):
    with pytest.raises(ReviewedError) as info:
        registry.resolve(sid, "1.0.0", params, None)
    assert _reason(info) == ("schema", "bad_params")


def test_bounds_edges_accepted():
    registry.resolve(
        TWR,
        "1.0.0",
        {"weights": {"AAA": "0.5", "BBB": "0.5"}, "rebalance_every_sessions": 252},
        None,
    )
    registry.resolve(BAH, "1.0.0", {"symbols": [f"S{i}" for i in range(50)]}, None)
    registry.resolve(
        TWR, "1.0.0", {"weights": {"AAA": "0"}, "rebalance_every_sessions": 1}, None
    )


def test_unknown_id_or_version_rejected():
    with pytest.raises(ReviewedError) as info:
        registry.resolve("momentum_12_1", "1.0.0", {}, None)
    assert _reason(info) == ("schema", "unknown_strategy")
    with pytest.raises(ReviewedError) as info:
        registry.resolve(BAH, "9.9.9", PARAMS[BAH], None)
    assert _reason(info) == ("schema", "unknown_version")
    with pytest.raises(ReviewedError) as info:
        registry.resolve(BAH, "1.0", PARAMS[BAH], None)
    assert _reason(info) == ("schema", "unknown_version")
    # a single-version strategy resolves without a version and records it
    assert registry.resolve(BAH, None, PARAMS[BAH], None).version == "1.0.0"


@pytest.mark.parametrize(
    "sid",
    [
        "pkg.module:Class",
        "openbb_backtest.strategies.momentum",
        "a:b",
        "../buy_and_hold",
        "C:\\x\\buy_and_hold",
        "/etc/passwd",
        "Buy_And_Hold",
        "buy-and-hold",
        "",
        "x" * 49,
    ],
)
def test_dotted_path_colon_and_filesystem_ids_rejected(sid):
    with pytest.raises(ReviewedError) as info:
        registry.resolve(sid, "1.0.0", {}, None)
    assert _reason(info) == ("schema", "bad_strategy_id")


def test_entry_points_never_consulted(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("entry points consulted")

    monkeypatch.setattr(importlib.metadata, "entry_points", boom)
    monkeypatch.setattr(importlib, "import_module", boom)
    got = registry.resolve(BAH, "1.0.0", PARAMS[BAH], None)
    assert got.strategy_id == BAH
    # an entry-point-style plugin cannot shadow a reviewed id: the id is
    # looked up in the frozen table only, and unknown ids are rejected
    with pytest.raises(ReviewedError):
        registry.resolve("techtrade_confluence", "1.0.0", {}, None)


def test_registry_has_no_dynamic_import_machinery():
    tree = ast.parse(Path(registry.__file__).read_text(encoding="utf-8"))
    banned = {"importlib", "pkgutil", "runpy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not banned & {a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned
        if isinstance(node, ast.Name):
            assert node.id not in {"__import__", "eval", "exec"}
    assert isinstance(registry.ALLOWLIST, type(registry.ALLOWLIST))
    with pytest.raises(TypeError):
        registry.ALLOWLIST[("x", "1.0.0")] = None  # type: ignore[index]


@pytest.mark.parametrize(
    "execution",
    [
        {"settlement": "T+0"},
        {"settlement": "T+3"},
        {"account": "MARGIN"},
        {"borrowing": True},
        {"short": True},
        {"cash_model": "unsettled_ok"},
        {"fill_timing": "next_close"},
        {"fees": "maker_bps"},
        {"fees": "taker_bps"},
        {"fees": "taker_bps", "taker_bps": "101"},
        {"fees": "taker_bps", "taker_bps": "0"},
        {"fees": "zero", "taker_bps": "5"},
        {"booking": "decimal_half_even"},
        {"corporate_actions": "apply"},
        {"leverage": "2"},
    ],
)
def test_unsupported_settlement_rejected(execution):
    with pytest.raises(ReviewedError) as info:
        registry.resolve(BAH, "1.0.0", PARAMS[BAH], execution)
    assert _reason(info) == ("schema", "unsupported_execution")


def test_spec_that_does_not_support_an_assumption_rejects_it():
    entry = registry.ALLOWLIST[(BAH, "1.0.0")]
    narrow = entry.spec.model_copy(
        update={
            "supported": entry.spec.supported.model_copy(
                update={"settlement": ("T+1",)}
            )
        }
    )
    with pytest.raises(ReviewedError) as info:
        narrow.check_execution(spec_mod.parse_execution({"settlement": "T+2"}))
    assert _reason(info) == ("schema", "unsupported_execution")


def _manifest(tmp_path, make_dataset):
    root = tmp_path / "datasets"
    ds_id = make_dataset(root)
    return ds_id, ds.load_dataset(root, ds_id, 9).manifest


def test_corporate_actions_in_window_rejected(tmp_path, make_dataset):
    _, manifest = _manifest(tmp_path, make_dataset)
    registry.check_no_corporate_actions(manifest)  # oracle has none
    for update in ({"split_events": 1}, {"dividend_events": 2}):
        bad = manifest.model_copy(
            update={"source": manifest.source.model_copy(update=update)}
        )
        with pytest.raises(ReviewedError) as info:
            registry.check_no_corporate_actions(bad)
        assert _reason(info) == ("schema", "corporate_actions_present")
    rows = manifest.model_copy(
        update={"content": manifest.content.model_copy(update={"actions_rows": 1})}
    )
    with pytest.raises(ReviewedError):
        registry.check_no_corporate_actions(rows)


def _pin(version="1.0.0", code="a" * 64, schema="b" * 64, spec="c" * 64):
    return registry.Pin(BAH, version, code, schema, spec)


def test_hash_only_bump_without_version_change_rejected():
    ok = (_pin(),)
    registry.check_ledger(ok)
    bumped = (_pin(), _pin(code="d" * 64))
    with pytest.raises(ReviewedError) as info:
        registry.check_ledger(bumped)
    assert _reason(info) == ("schema", "pin_changed_without_version_bump")
    with pytest.raises(ReviewedError) as info:
        registry.check_ledger((_pin(), _pin()))
    assert _reason(info) == ("schema", "pin_changed_without_version_bump")
    # a version bump is the sanctioned path
    registry.check_ledger((_pin(), _pin("1.0.1", code="d" * 64)))
    # versions only move forward
    with pytest.raises(ReviewedError) as info:
        registry.check_ledger((_pin("1.0.1"), _pin("1.0.0", code="d" * 64)))
    assert _reason(info) == ("schema", "pin_version_not_increasing")
    registry.check_ledger(registry.REVIEW_LEDGER)


def test_edited_pin_is_caught_as_drift(monkeypatch):
    pin = registry.pin_for(BAH, "1.0.0")
    forged = registry.Pin(
        BAH, "1.0.0", "e" * 64, pin.param_schema_sha256, pin.spec_sha256
    )
    monkeypatch.setattr(
        registry, "_PINS", {**registry._PINS, (BAH, "1.0.0"): forged}  # noqa: SLF001
    )
    with pytest.raises(ReviewedError) as info:
        registry.verify(BAH, "1.0.0")
    assert _reason(info) == ("module_origin", "strategy_code_drift")
    schema_forged = registry.Pin(
        BAH, "1.0.0", pin.code_sha256, "f" * 64, pin.spec_sha256
    )
    monkeypatch.setattr(
        registry,
        "_PINS",
        {**registry._PINS, (BAH, "1.0.0"): schema_forged},  # noqa: SLF001
    )
    with pytest.raises(ReviewedError) as info:
        registry.verify(BAH, "1.0.0")
    assert _reason(info) == ("schema", "param_schema_drift")


# --- request v2 admission and run ---------------------------------------------


def _v2(ds_id, sid=BAH, params=None, execution=None, **extra):
    fields = registry.resolve(
        sid, "1.0.0", params or PARAMS[BAH], execution
    ).request_fields()
    return {"dataset_id": ds_id, **fields, **extra}


def test_screen_accepts_v2_nested_names_but_not_credentials():
    body = _v2("0" * 64, TWR, PARAMS[TWR])
    req = adm.screen_request(body)
    assert req.strategy is None and req.strategy_ref.id == TWR
    # nested names that look like credentials/endpoints are still rejected
    bad = _v2("0" * 64, TWR, PARAMS[TWR])
    bad["params"] = {**bad["params"], "api_key": "x"}
    with pytest.raises(ProtocolError) as info:
        adm.screen_request(bad)
    assert info.value.code is ErrorCode.EGRESS
    url = _v2("0" * 64)
    url["params"] = {"symbols": ["http://evil.example"]}
    with pytest.raises(ProtocolError) as info:
        adm.screen_request(url)
    assert info.value.code is ErrorCode.EGRESS


def test_alias_and_v2_are_mutually_exclusive():
    body = _v2("0" * 64, strategy="buy_and_hold")
    with pytest.raises(ProtocolError) as info:
        adm.screen_request(body)
    assert info.value.code is ErrorCode.SCHEMA
    partial = _v2("0" * 64)
    del partial["params_sha256"]
    with pytest.raises(ProtocolError):
        adm.screen_request(partial)
    with pytest.raises(ProtocolError):
        adm.screen_request({"dataset_id": "0" * 64})
    explicit_fees = _v2("0" * 64, fees="zero")
    with pytest.raises(ProtocolError):
        adm.screen_request(explicit_fees)


def test_v1_alias_still_admitted(tmp_path, make_dataset):
    ds_id, _ = _manifest(tmp_path, make_dataset)
    admitted = adm.admit_run(
        adm.screen_request({"dataset_id": ds_id, "strategy": "buy_and_hold"}),
        tmp_path / "datasets",
        9,
    )
    assert admitted.binding is None


def test_admit_v2_binds_and_rechecks_locally(tmp_path, make_dataset):
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    sym = manifest.symbols[0]
    body = _v2(ds_id, params={"symbols": [sym]})
    admitted = adm.admit_run(adm.screen_request(body), tmp_path / "datasets", 9)
    assert admitted.binding.strategy_id == BAH
    assert admitted.binding.params == {"symbols": [sym]}


def test_admit_v2_rejects_symbol_outside_dataset(tmp_path, make_dataset):
    ds_id, _ = _manifest(tmp_path, make_dataset)
    body = _v2(ds_id, params={"symbols": ["ZZZ"]})
    with pytest.raises(ProtocolError) as info:
        adm.admit_run(adm.screen_request(body), tmp_path / "datasets", 9)
    assert info.value.code is ErrorCode.SCHEMA


def test_admit_v2_drifted_worker_copy_rejected(tmp_path, make_dataset, monkeypatch):
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    body = _v2(ds_id, params={"symbols": [manifest.symbols[0]]})
    root = _copy_pkg(tmp_path)
    (root / "reviewed" / "spec.py").write_bytes(
        (root / "reviewed" / "spec.py").read_bytes() + b"\n# drift\n"
    )
    monkeypatch.setattr(registry, "PACKAGE_ROOT", root)
    with pytest.raises(ReviewedError) as info:
        adm.admit_run(adm.screen_request(body), tmp_path / "datasets", 9)
    assert _reason(info) == ("module_origin", "strategy_code_drift")


def _fill(spec):
    res = fake_engine.replay(spec)
    return runs.EngineResult("fake", "9.9", res.fills, res.final_cash, res.denied)


def test_run_v2_buy_and_hold_reports_full_binding(tmp_path, make_dataset, oracle):
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    env = {DATA_ROOT_ENV: str(tmp_path)}
    body = {
        **_v2(
            ds_id,
            params={"symbols": [manifest.symbols[0]]},
            execution={"fill_timing": "same_close"},
        ),
        "starting_cash": oracle["initial_cash"],
    }
    rep = runs.run(body, env=env, engine=_fill, fixed_precision=9)
    assert rep["strategy"] == BAH and rep["cash"] == oracle["expected"]["cash"]
    binding = rep["binding"]
    pin = registry.pin_for(BAH, "1.0.0")
    assert binding["code_sha256"] == pin.code_sha256
    assert binding["spec_sha256"] == pin.spec_sha256
    assert binding["dataset_id"] == ds_id
    assert binding["engine_version"] == "9.9"
    assert len(binding["params_sha256"]) == len(binding["execution_sha256"]) == 64
    assert binding["binding_sha256"] == hashing.digest(
        {k: v for k, v in binding.items() if k != "binding_sha256"}
    )
    # every component feeds the binding hash
    other = registry.run_binding(
        registry.resolve(
            BAH,
            "1.0.0",
            {"symbols": [manifest.symbols[0]]},
            {"fill_timing": "next_open"},
        ),
        ds_id,
        "9.9",
    )
    assert other["binding_sha256"] != binding["binding_sha256"]


@pytest.mark.parametrize(
    "execution",
    [{}, {"fill_timing": "next_open"}, {"fees": "taker_bps", "taker_bps": "10"}],
)
def test_run_v2_reviewed_execution_is_executable(tmp_path, make_dataset, execution):
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    env = {DATA_ROOT_ENV: str(tmp_path)}
    body = _v2(ds_id, params={"symbols": [manifest.symbols[0]]}, execution=execution)
    rep = runs.run(body, env=env, engine=_fill, fixed_precision=9)
    assert (
        rep["binding"]["execution_sha256"]
        == registry.run_binding(
            registry.resolve(
                BAH, "1.0.0", {"symbols": [manifest.symbols[0]]}, execution
            ),
            ds_id,
            "9.9",
        )["execution_sha256"]
    )


def test_run_v2_rebalance_is_executable(tmp_path, make_dataset):
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    env = {DATA_ROOT_ENV: str(tmp_path)}
    sym = manifest.symbols[0]
    params = {"weights": {sym: "0.5"}, "rebalance_every_sessions": 2}
    body = _v2(ds_id, TWR, params, {"fill_timing": "same_close"})
    rep = runs.run(body, env=env, engine=_fill, fixed_precision=9)
    assert rep["strategy"] == TWR and rep["positions"][sym] > 0


def test_run_v2_unexecutable_semantics_fail_closed(tmp_path, make_dataset, monkeypatch):
    """The executable guard is still wired: a dropped capability is ``config``."""
    ds_id, manifest = _manifest(tmp_path, make_dataset)
    env = {DATA_ROOT_ENV: str(tmp_path)}
    monkeypatch.setitem(runs.EXECUTABLE, "fees", ("zero",))
    body = _v2(
        ds_id,
        params={"symbols": [manifest.symbols[0]]},
        execution={"fees": "taker_bps", "taker_bps": "10"},
    )
    with pytest.raises(ProtocolError) as info:
        runs.run(body, env=env, engine=_fill, fixed_precision=9)
    assert info.value.code is ErrorCode.CONFIG


def test_admit_run_wires_corporate_action_check():
    tree = ast.parse(Path(adm.__file__).read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "admit_run"
    )
    called = {
        c.func.attr
        for c in ast.walk(fn)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
    }
    assert {"check_no_corporate_actions", "resolve_request"} <= called
