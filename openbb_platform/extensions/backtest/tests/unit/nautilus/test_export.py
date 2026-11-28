"""Stage-1 export tests (#1355 T02): synthetic DictCursor rows, never MySQL.

Fixture ``fixtures/synthetic_bundle`` (hand-made, no real market data): XNYS
sessions 2024-11-25..2024-12-03; Thanksgiving 2024-11-28 is a holiday (a
gap-filled AAA row sits on it) and 2024-11-29 is a 13:00 New York half-day;
AAA splits 2-for-1 ex 2024-12-02 (unadjusted prices halve), BBB pays 0.25 ex
2024-11-27, CCC has 4-decimal prices.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from openbb_backtest.adapters.nautilus import export as ex
from openbb_nautilus_worker import dataset as ds
from openbb_nautilus_worker.dataset import DatasetError

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "synthetic_bundle"
SYMBOLS = ["AAA", "BBB", "CCC"]
START, END = "2024-11-25", "2024-12-03"
SESSIONS = [
    "2024-11-25",
    "2024-11-26",
    "2024-11-27",
    "2024-11-29",
    "2024-12-02",
    "2024-12-03",
]


def _ns(text: str) -> int:
    return (
        int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())
        * 10**9
    )


def _snapshot(tmp_path: Path, mutate=None, name: str = "snap") -> Path:
    tables = {
        t: json.loads((SNAPSHOT / f"{t}.json").read_text())
        for t in ("equity_historical", "calendar_splits", "calendar_dividend")
    }
    if mutate:
        mutate(tables)
    out = tmp_path / name
    out.mkdir(parents=True)
    for t, rows in tables.items():
        (out / f"{t}.json").write_text(json.dumps(rows))
    return out


def _export(tmp_path, mutate=None, *, root="out", basis="raw_plus_actions", **kw):
    snap = _snapshot(tmp_path, mutate, name=f"snap-{root}")
    out = tmp_path / root
    out.mkdir(parents=True, exist_ok=True)
    return ex.export_dataset(
        kw.pop("symbols", SYMBOLS),
        kw.pop("start", START),
        kw.pop("end", END),
        basis=basis,
        out_root=out,
        execute=ex.snapshot_executor(snap),
        **kw,
    )


def _reason(tmp_path, mutate=None, **kw) -> DatasetError:
    with pytest.raises(DatasetError) as info:
        _export(tmp_path, mutate, **kw)
    return info.value


def _rows(tables, sym=None, day=None):
    return [
        r
        for r in tables["equity_historical"]
        if (sym is None or r["symbol"] == sym) and (day is None or r["date"] == day)
    ]


def _relabel(sym, days, label):
    def mutate(tables):
        for r in _rows(tables, sym):
            if r["date"] in days:
                r["adjustment_type"] = label

    return mutate


def _halve_before_split(label):
    """Make AAA a split-adjusted series (pre-split prices / 2) labelled ``label``."""

    def mutate(tables):
        for r in tables["equity_historical"]:
            r["adjustment_type"] = label
            if r["symbol"] == "AAA" and r["date"] < "2024-12-02":
                for c in ("open", "high", "low", "close"):
                    r[c] = str(Decimal(r[c]) / 2)

    return mutate


# --- seam contract ---------------------------------------------------------


def test_snapshot_rows_match_the_export_query_columns():
    """The DictCursor fixture carries every column EQUITY_SQL selects (seam contract)."""
    selected = ex.EQUITY_SQL.split("SELECT ", 1)[1].split(" FROM ", 1)[0]
    cols = {c.strip() for c in selected.split(",")}
    rows = json.loads((SNAPSHOT / "equity_historical.json").read_text())
    for row in rows:
        assert cols <= set(row), cols - set(row)
    assert "adjustment_type" in cols and "is_filled" in cols


# --- A1: reproducible, recorded ---------------------------------------------


def test_export_is_byte_reproducible(tmp_path):
    """Check: export is byte reproducible."""
    a = _export(tmp_path, root="a")
    b = _export(tmp_path, root="b")
    assert a.dataset_id == b.dataset_id
    assert a.path.name == a.dataset_id
    for name in (*ds.DATA_FILES, ds.MANIFEST_NAME):
        assert (a.path / name).read_bytes() == (b.path / name).read_bytes(), name
    # Admission on the facade side accepts what the export wrote.
    assert ds.admit_dataset(tmp_path / "a", a.dataset_id, 9) == a.manifest


def test_manifest_records_calendar_version_and_sessions_digest(tmp_path):
    """Check: manifest records calendar version and sessions digest."""
    res = _export(tmp_path)
    man = json.loads((res.path / ds.MANIFEST_NAME).read_text())
    cal = man["calendar"]
    assert cal["code"] == "XNYS"
    assert cal["exchange_calendars_version"] == metadata.version("exchange_calendars")
    assert cal["sessions_count"] == 6
    assert cal["sessions_sha256"] == ds.sha256_hex("\n".join(SESSIONS).encode())
    assert man["action_basis"] == "raw_plus_actions"
    assert {i["symbol"]: i["price_precision"] for i in man["instruments"]} == {
        "AAA": 2,
        "BBB": 2,
        "CCC": 4,
    }
    for name, digest in man["files"].items():
        assert ds.sha256_hex((res.path / name).read_bytes()) == digest
    src = man["source"]
    assert (src["rows_read"], src["rows_used"], src["filled_rows_dropped"]) == (
        20,
        18,
        2,
    )
    assert (
        src["split_events"],
        src["dividend_events"],
        src["split_events_dropped"],
    ) == (1, 1, 0)
    assert len(src["query_sha256"]) == 64
    assert man["writer"]["pyarrow"]


def test_bars_are_unadjusted_scaled_ints_and_actions_explicit(tmp_path):
    """Check: bars are unadjusted scaled ints and actions explicit."""
    res = _export(tmp_path)
    bars = pq.read_table(res.path / ds.BARS_FILE).to_pylist()
    close = {(b["symbol"], b["session"].isoformat()): b["close"] for b in bars}
    # No factor applied: AAA keeps 203.00 before and 101.75 on the split ex-date.
    assert close[("AAA", "2024-11-29")] == 20300
    assert close[("AAA", "2024-12-02")] == 10175
    assert close[("CCC", "2024-11-25")] == 101234
    assert [b["session"].isoformat() for b in bars if b["symbol"] == "BBB"] == SESSIONS
    actions = pq.read_table(res.path / ds.ACTIONS_FILE).to_pylist()
    assert [(a["symbol"], a["ex_date"], a["kind"], a["value"]) for a in actions] == [
        ("AAA", date(2024, 12, 2), "split", "2"),
        ("BBB", date(2024, 11, 27), "dividend", "0.25"),
    ]


def test_half_day_close_timestamp_is_1300_new_york_in_utc(tmp_path):
    """Check: half day close timestamp is 1300 new york in utc."""
    bars = pq.read_table(_export(tmp_path).path / ds.BARS_FILE).to_pylist()
    ts = {b["session"].isoformat(): (b["ts_event"], b["ts_init"]) for b in bars}
    assert ts["2024-11-29"] == (_ns("2024-11-29T18:00:00"),) * 2  # 13:00 EST
    assert ts["2024-11-27"] == (_ns("2024-11-27T21:00:00"),) * 2  # 16:00 EST


def test_dst_transition_close_utc(tmp_path):
    """Check: dst transition close utc."""

    def mutate(tables):
        rows = []
        for day in ("2024-11-01", "2024-11-04"):
            rows.append({**_rows(tables, "BBB", "2024-11-25")[0], "date": day})
        tables["equity_historical"] = rows
        tables["calendar_dividend"] = []
        tables["calendar_splits"] = []

    res = _export(
        tmp_path, mutate, symbols=["BBB"], start="2024-11-01", end="2024-11-04"
    )
    bars = pq.read_table(res.path / ds.BARS_FILE).to_pylist()
    assert [b["ts_event"] for b in bars] == [
        _ns("2024-11-01T20:00:00"),  # 16:00 EDT
        _ns("2024-11-04T21:00:00"),  # 16:00 EST
    ]


# --- A1/A2: calendar alignment ----------------------------------------------


def test_rejects_missing_or_extra_sessions(tmp_path):
    """Check: rejects missing or extra sessions."""

    def drop(tables):
        tables["equity_historical"].remove(_rows(tables, "BBB", "2024-11-29")[0])

    assert _reason(tmp_path / "m", drop).reason == "missing_session"

    def extra(tables):
        _rows(tables, "AAA", "2024-11-28")[0]["is_filled"] = 0

    assert _reason(tmp_path / "e", extra).reason == "extra_session"

    def filled(tables):
        _rows(tables, "CCC", "2024-11-26")[0]["is_filled"] = 1

    assert _reason(tmp_path / "f", filled).reason == "filled_session"


# --- A1/A2: action basis -------------------------------------------------------


def test_rejects_double_adjustment(tmp_path):
    """Check: rejects double adjustment."""
    # Cache holds only splits_only rows: raw_plus_actions would split them twice.
    err = _reason(tmp_path / "a", _relabel("AAA", SESSIONS, "splits_only"))
    assert (err.reason, err.code.value) == ("unadjusted_rows_absent", "config")
    # Declaring a split-adjusted source for raw_plus_actions.
    err = _reason(tmp_path / "b", adjustment="splits_only")
    assert (err.reason, err.code.value) == ("double_adjustment", "schema")
    # Rows labelled 'unadjusted' but already split-adjusted (no jump at the split).
    err = _reason(tmp_path / "c", _halve_before_split("unadjusted"))
    assert err.reason == "double_adjustment"
    # Mixed adjustment_type values inside one series.
    err = _reason(tmp_path / "d", _relabel("AAA", SESSIONS[4:], "splits_only"))
    assert err.reason == "mixed_adjustment_basis"


def test_rejects_unlabelled_rows_as_mixed(tmp_path):
    """Check: rejects unlabelled rows as mixed."""
    err = _reason(tmp_path, _relabel("CCC", ["2024-11-27"], None))
    assert err.reason == "mixed_adjustment_basis"


def test_back_adjusted_basis_is_rejected(tmp_path):
    """Check: back adjusted basis is rejected."""
    assert _reason(tmp_path, basis="back_adjusted").reason == "back_adjusted_rejected"


def test_parallel_complete_series_is_ignored_not_mixed(tmp_path):
    """Check: parallel complete series is ignored not mixed."""

    def add_parallel(tables):
        copies = [
            {**r, "adjustment_type": "splits_only"}
            for r in tables["equity_historical"]
            if not r["is_filled"]
        ]
        tables["equity_historical"].extend(copies)

    base = _export(tmp_path, root="base")
    res = _export(tmp_path, add_parallel, root="par")
    assert res.manifest.source.other_adjustment_rows_ignored == 18
    assert res.manifest.content == base.manifest.content


def test_split_adjusted_fallback_drops_split_events(tmp_path):
    """Check: split adjusted fallback drops split events."""
    res = _export(
        tmp_path, _halve_before_split("splits_only"), basis="split_adjusted_source"
    )
    assert res.manifest.action_basis == "split_adjusted_source"
    assert res.manifest.source.adjustment_type == "splits_only"
    assert res.manifest.source.split_events_dropped == 1
    actions = pq.read_table(res.path / ds.ACTIONS_FILE).to_pylist()
    assert [a["kind"] for a in actions] == ["dividend"]
    bars = pq.read_table(res.path / ds.BARS_FILE).to_pylist()
    close = {(b["symbol"], b["session"].isoformat()): b["close"] for b in bars}
    assert res.manifest.instruments[0].price_precision == 3  # 201.25 / 2 = 100.625
    assert close[("AAA", "2024-11-29")] == 101500  # 203.00 / 2, not divided again


def test_split_adjusted_fallback_rejects_unadjusted_prices(tmp_path):
    """Check: split adjusted fallback rejects unadjusted prices."""

    def relabel_all(tables):
        for r in tables["equity_historical"]:
            r["adjustment_type"] = "splits_only"

    err = _reason(tmp_path, relabel_all, basis="split_adjusted_source")
    assert err.reason == "basis_adjustment_mismatch"


# --- A2: precision -----------------------------------------------------------


def test_rejects_precision_beyond_source_or_worker(tmp_path):
    """Check: rejects precision beyond source or worker."""

    def seven(tables):
        _rows(tables, "CCC", "2024-11-27")[0]["close"] = "10.2500001"

    err = _reason(tmp_path / "s", seven)
    assert (err.reason, err.code.value) == ("precision_beyond_source", "abi")
    err = _reason(tmp_path / "w", max_precision=3)  # CCC needs 4 decimals
    assert (err.reason, err.code.value) == ("precision_beyond_worker", "abi")

    def huge(tables):
        _rows(tables, "BBB", "2024-11-27")[0]["high"] = "9300000000.00"

    err = _reason(tmp_path / "h", huge)
    assert (err.reason, err.code.value) == ("price_out_of_range", "abi")


def test_admission_rejects_precision_above_worker(tmp_path):
    """Check: admission rejects precision above worker."""
    res = _export(tmp_path)
    with pytest.raises(DatasetError) as info:
        ds.admit_dataset(res.path.parent, res.dataset_id, fixed_precision=3)
    assert (info.value.reason, info.value.code.value) == (
        "precision_beyond_worker",
        "abi",
    )


# --- mutation guard against a vacuous hash ------------------------------------


def _set_close(t):
    _rows(t, "BBB", "2024-11-26")[0].update(close="50.41")


def _set_volume(t):
    _rows(t, "CCC", "2024-12-03")[0].update(volume=315001)


def _set_dividend(t):
    t["calendar_dividend"][0].update(data_json=json.dumps({"amount": 0.26}))


def _set_split(t):
    t["calendar_splits"][0].update(
        data_json=json.dumps({"numerator": 3, "denominator": 1})
    )


@pytest.mark.parametrize(
    ("mutate", "kw"),
    [
        (_set_close, {}),
        (_set_volume, {}),
        (_set_dividend, {}),
        (_set_split, {}),
        (None, {"end": "2024-12-02"}),
        (None, {"symbols": ["AAA", "BBB"]}),
        (None, {"source_label": "other"}),
    ],
    ids=["price", "volume", "dividend", "split", "window", "symbols", "label"],
)
def test_dataset_id_changes_when_any_input_changes(tmp_path, mutate, kw):
    """Any single input change (rows, events, window, symbols, provenance) moves the id."""
    base = _export(tmp_path, root="base").dataset_id
    changed = _export(tmp_path, mutate, root="changed", **kw).dataset_id
    assert changed != base


# --- output location, CLI ------------------------------------------------------


def test_out_root_inside_repo_rejected(tmp_path):
    """Check: out root inside repo rejected."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(DatasetError) as info:
        ex.export_dataset(
            SYMBOLS,
            START,
            END,
            basis="raw_plus_actions",
            out_root=repo / "data",
            execute=ex.snapshot_executor(SNAPSHOT),
        )
    assert info.value.reason == "out_root_in_repo"


def test_cli_snapshot_prints_hashes_and_rejects_mixed_basis(tmp_path, capsys):
    """Check: cli snapshot prints hashes and rejects mixed basis."""
    argv = [
        "--symbols",
        "AAA,BBB,CCC",
        "--start",
        START,
        "--end",
        END,
        "--basis",
        "raw_plus_actions",
        "--out-root",
        str(tmp_path / "o"),
        "--snapshot-dir",
        str(SNAPSHOT),
    ]
    assert ex.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and len(out["dataset_id"]) == 64
    assert str(tmp_path) not in json.dumps(out)
    mixed = _snapshot(tmp_path, _relabel("AAA", SESSIONS[4:], "splits_only"), "mixed")
    argv[-1] = str(mixed)
    assert ex.main(argv) == 2
    err = json.loads(capsys.readouterr().out)
    assert (err["ok"], err["reason"], err["code"]) == (
        False,
        "mixed_adjustment_basis",
        "schema",
    )


# --- independent buy-and-hold oracle --------------------------------------------


def test_buy_and_hold_oracle_matches_exported_closes(tmp_path):
    """Hand-computed oracle (not golden/fixtures/buy_and_hold.json), checked on export."""
    oracle = json.loads((FIXTURES / "buy_and_hold_oracle.json").read_text())
    rows = [
        {
            "symbol": oracle["symbol"],
            "date": d,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1000,
            "interval_type": "1d",
            "adjustment_type": "unadjusted",
            "is_filled": 0,
            "is_valid": 1,
        }
        for d, c in zip(oracle["sessions"], oracle["closes"])
    ]

    def mutate(tables):
        tables["equity_historical"] = rows
        tables["calendar_splits"] = []
        tables["calendar_dividend"] = []

    res = _export(
        tmp_path,
        mutate,
        symbols=[oracle["symbol"]],
        start=oracle["sessions"][0],
        end=oracle["sessions"][-1],
    )
    bars = pq.read_table(res.path / ds.BARS_FILE).to_pylist()
    places = res.manifest.instruments[0].price_precision
    closes_cents = [b["close"] * 100 // 10**places for b in bars]
    cash_cents = round(Decimal(oracle["initial_cash"]) * 100)
    qty = cash_cents // closes_cents[0]
    cash_left = cash_cents - qty * closes_cents[0]
    equity = [Decimal(cash_left + qty * c) / 100 for c in closes_cents]
    assert qty == oracle["expected"]["quantity"]
    assert Decimal(cash_left) / 100 == Decimal(oracle["expected"]["cash"])
    assert [str(e.quantize(Decimal("0.01"))) for e in equity] == oracle["expected"][
        "equity"
    ]


# --- split-ratio ambiguity and dividend basis (#1355 fix part 2) -------------


def _small_split_with_gap(t):
    """AAA: a 21/20 (=1.05) split whose raw series gaps UP 4% overnight."""
    t["calendar_splits"][0].update(
        data_json=json.dumps({"numerator": 21, "denominator": 20})
    )
    for r in _rows(t, "AAA"):
        if r["date"] >= "2024-12-02":
            for c in ("open", "high", "low", "close"):
                r[c] = str((Decimal(r[c]) * Decimal("2.08")).quantize(Decimal("0.01")))


def test_small_split_ratio_is_ambiguous_not_a_basis_verdict(tmp_path):
    """A 1.05 split vs a 4% overnight gap: raw data must not be rejected."""
    res = _export(tmp_path, _small_split_with_gap)
    src = res.manifest.source
    assert (src.split_ratio_ambiguous, src.split_at_window_start) == (1, 0)
    assert ("AAA", date(2024, 12, 2), "split", "1.05") in [
        tuple(r.values())
        for r in pq.read_table(res.path / "actions.parquet").to_pylist()
    ]


def test_split_on_first_session_is_recorded_as_ambiguous(tmp_path):
    """No prior session in the window: no verdict, but the manifest says so."""
    res = _export(tmp_path, start="2024-12-02")
    src = res.manifest.source
    assert (src.split_ratio_ambiguous, src.split_at_window_start) == (0, 1)


def _flat_prices(first_close, second_open):
    days = [date(2024, 12, 2), date(2024, 12, 3)]
    row = {"open": Decimal(second_open), "close": Decimal(second_open)}
    return {
        "AAA": {
            days[0]: {"open": Decimal(first_close), "close": Decimal(first_close)},
            days[1]: row,
        }
    }, days


@pytest.mark.parametrize(
    ("ratio", "expect"),
    [(math.exp(0.19), "ambiguous"), (math.exp(0.21), "double_adjustment")],
    ids=["below-threshold", "above-threshold"],
)
def test_split_ratio_threshold_is_ln_0_2(ratio, expect):
    """|ln r| < 0.2 is ambiguous; above it a flat series is a double adjustment."""
    prices, days = _flat_prices("100", "100")
    args = ("raw_plus_actions", [("AAA", days[1], ratio)], prices, days)
    if expect == "ambiguous":
        assert ex._check_split_jumps(*args) == (
            1,
            0,
        )  # pylint: disable=protected-access
    else:
        with pytest.raises(DatasetError) as info:
            ex._check_split_jumps(*args)  # pylint: disable=protected-access
        assert info.value.reason == "double_adjustment"


def test_dividend_basis_is_recorded_and_moves_the_id(tmp_path):
    """Dividends are passed through unverified (#1385); the manifest says so."""
    res = _export(tmp_path)
    assert res.manifest.dividend_basis == "passthrough_unverified"
    man = json.loads((res.path / ds.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert man["dividend_basis"] == "passthrough_unverified"
    assert "dividend_basis" in ds.identity(res.manifest)


def test_summary_reports_dividend_basis(tmp_path):
    """The CLI summary carries the dividend basis next to the action basis."""
    out = ex.summary(_export(tmp_path))
    assert out["dividend_basis"] == "passthrough_unverified"
