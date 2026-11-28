"""Stage-1 export: fmp_cached rows -> content-addressed neutral dataset (#1355 T02).

Never imports ``nautilus_trader``. Reads the cache through the injectable
``execute`` seam of :class:`~openbb_backtest.data.bundle.FmpCachedReader` (live
MySQL only when no executor is given), aligns rows to the ``exchange_calendars``
sessions used by the bundle layer, and writes ``bars.parquet``,
``actions.parquet`` and ``manifest.json`` atomically under
``<out_root>/<dataset_id>``. Stage 2 (the Nautilus ``ParquetDataCatalog``) runs
in the worker (``build_catalog`` op).

Action basis (lead decisions L6/L7):

- ``raw_plus_actions``: ``adjustment_type='unadjusted'`` prices plus explicit
  split/dividend events; no factor is ever applied to prices.
- ``split_adjusted_source``: ``adjustment_type='splits_only'`` prices with split
  events dropped (applying them would adjust twice); P15 verification only.
- ``back_adjusted`` is rejected (dividend back-adjustment is not a traded price).

The cache stores one series per ``adjustment_type`` and
``FmpCachedReader.equity_historical`` does not filter on it (#1385), so this
module selects the column itself and fails closed on mixed or double-adjusted
input. Output is counts and hashes only, never rows.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
from openbb_nautilus_worker import dataset as ds
from openbb_nautilus_worker.dataset import DatasetError
from openbb_nautilus_worker.protocol import ErrorCode, canonical_json

from openbb_backtest.data.bundle import FmpCachedReader
from openbb_backtest.data.calendars import get_calendar, sessions_in_range

Execute = Callable[..., Any]

DATA_ROOT_ENV = "OPENBB_NAUTILUS_DATA_ROOT"
BASIS_ADJUSTMENT = {
    "raw_plus_actions": "unadjusted",
    "split_adjusted_source": "splits_only",
}
_PRICE_COLS = ("open", "high", "low", "close")
# |ln ratio| below this cannot be told apart from an ordinary overnight gap.
SPLIT_AMBIGUOUS_LOG = 0.2
_SYMBOL_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")

# Selects adjustment_type / is_filled / is_valid so the basis can be checked
# (FmpCachedReader.equity_historical drops them, #1385).
EQUITY_SQL = (
    "SELECT symbol, date, open, high, low, close, volume, adjustment_type, "
    "is_filled, is_valid FROM equity_historical WHERE symbol IN ({placeholders}) "
    "AND date BETWEEN %s AND %s AND interval_type = '1d' ORDER BY symbol, date"
)


@dataclass(frozen=True)
class ExportResult:
    """Outcome of an export: the content address, its directory and manifest."""

    dataset_id: str
    path: Path
    manifest: ds.Manifest


def _fail(code: ErrorCode, reason: str, message: str) -> DatasetError:
    return DatasetError(code, reason, message)


class _RecordingExecute:
    """Wraps an executor and keeps the (query, params) of every call."""

    def __init__(self, execute: Execute):
        self._execute = execute
        self.calls: list[tuple[str, tuple]] = []

    def __call__(self, query: str, params: tuple = ()) -> list[dict]:
        self.calls.append((query, tuple(params)))
        return list(self._execute(query, params) or [])

    def fingerprint(self) -> str:
        """Digest of every query and its parameters (values are symbols/dates)."""
        calls = [[q, [str(p) for p in params]] for q, params in self.calls]
        return ds.sha256_hex(canonical_json(calls))


def _live_execute() -> Execute:
    """Return the reader's default executor (live fmp_cached MySQL)."""
    return FmpCachedReader()._execute  # pylint: disable=protected-access


def check_basis(basis: str, adjustment: str | None) -> str:
    """Validate the basis/adjustment pair; return the source adjustment_type."""
    if basis == "back_adjusted":
        raise _fail(
            ErrorCode.SCHEMA,
            "back_adjusted_rejected",
            "dividend back-adjusted prices are not traded prices",
        )
    if basis not in BASIS_ADJUSTMENT:
        raise _fail(ErrorCode.SCHEMA, "unknown_action_basis", repr(basis))
    expected = BASIS_ADJUSTMENT[basis]
    adjustment = adjustment or expected
    if adjustment == expected:
        return adjustment
    if basis == "raw_plus_actions":
        raise _fail(
            ErrorCode.SCHEMA,
            "double_adjustment",
            f"raw_plus_actions applies split events; source must be 'unadjusted', "
            f"not {adjustment!r}",
        )
    raise _fail(
        ErrorCode.SCHEMA,
        "basis_adjustment_mismatch",
        f"split_adjusted_source needs 'splits_only' rows, not {adjustment!r}",
    )


def _decimal(value: Any, what: str) -> Decimal:
    if value is None:
        raise _fail(ErrorCode.SCHEMA, "missing_price", f"{what} is null")
    try:
        dec = Decimal(str(value))
    except InvalidOperation as exc:
        raise _fail(ErrorCode.SCHEMA, "bad_price", f"{what} not numeric") from exc
    if not dec.is_finite():
        raise _fail(ErrorCode.SCHEMA, "bad_price", f"{what} not finite")
    return dec


def _decimals(dec: Decimal) -> int:
    exponent = dec.normalize().as_tuple().exponent
    return max(0, -int(exponent))


def _as_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _ensure_outside_repo(root: Path) -> Path:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise _fail(
                ErrorCode.CONFIG,
                "out_root_in_repo",
                "dataset root must be outside any git checkout",
            )
    return resolved


@dataclass
class _Counts:
    rows_read: int = 0
    rows_used: int = 0
    filled: int = 0
    invalid: int = 0
    other_adjustment: int = 0


def _select_rows(  # pylint: disable=too-many-locals,too-many-branches
    rows: list[dict],
    symbols: list[str],
    sessions: list[date],
    adjustment: str,
    counts: _Counts,
) -> dict[str, dict[date, dict]]:
    """Pick one series per symbol and check it against the calendar sessions."""
    session_set = set(sessions)
    if rows and all("adjustment_type" not in r for r in rows):
        raise _fail(ErrorCode.SCHEMA, "unknown_adjustment", "rows lack adjustment")
    by_symbol: dict[str, dict[date, dict]] = {s: {} for s in symbols}
    other_dates: dict[str, set[date]] = {s: set() for s in symbols}
    other_types: dict[str, set[str]] = {s: set() for s in symbols}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym not in by_symbol:
            continue
        if row.get("is_valid") is not None and not row.get("is_valid"):
            counts.invalid += 1
            continue
        day = _as_date(row.get("date"))
        if row.get("adjustment_type") != adjustment:
            other_dates[sym].add(day)
            other_types[sym].add(str(row.get("adjustment_type")))
            counts.other_adjustment += 1
            continue
        if row.get("is_filled"):
            if day in session_set:
                raise _fail(
                    ErrorCode.SCHEMA,
                    "filled_session",
                    f"{sym} {day} is a gap-filled row on a trading session",
                )
            counts.filled += 1
            continue
        if day in by_symbol[sym]:
            raise _fail(ErrorCode.SCHEMA, "duplicate_row", f"{sym} {day}")
        by_symbol[sym][day] = row
    for sym in symbols:
        chosen = by_symbol[sym]
        if not chosen:
            if other_dates[sym] and adjustment == "unadjusted":
                raise _fail(
                    ErrorCode.CONFIG,
                    "unadjusted_rows_absent",
                    f"{sym} has only {sorted(other_types[sym])} rows; using them with "
                    "split events would adjust twice (fmp_cached gap, #1385)",
                )
            if other_dates[sym]:
                raise _fail(
                    ErrorCode.CONFIG,
                    "adjustment_rows_absent",
                    f"{sym} has no {adjustment!r} rows",
                )
            raise _fail(ErrorCode.SCHEMA, "missing_symbol", f"{sym} has no rows")
        mixed = sorted((other_dates[sym] & session_set) - set(chosen))
        if mixed:
            raise _fail(
                ErrorCode.SCHEMA,
                "mixed_adjustment_basis",
                f"{sym} mixes {adjustment!r} with {sorted(other_types[sym])} "
                f"rows (first {mixed[0]})",
            )
        extra = sorted(set(chosen) - session_set)
        if extra:
            raise _fail(
                ErrorCode.SCHEMA, "extra_session", f"{sym} {extra[0]} not a session"
            )
        missing = sorted(session_set - set(chosen))
        if missing:
            raise _fail(
                ErrorCode.SCHEMA, "missing_session", f"{sym} lacks {missing[0]}"
            )
        counts.rows_used += len(chosen)
    return by_symbol


def _instrument_prices(
    sym: str, rows: dict[date, dict], max_precision: int
) -> tuple[int, dict[date, dict[str, Decimal]], dict[date, int]]:
    """Validate prices/volumes of one symbol; return precision and values."""
    prices: dict[date, dict[str, Decimal]] = {}
    volumes: dict[date, int] = {}
    places = 2
    for day, row in rows.items():
        ohlc = {c: _decimal(row.get(c), f"{sym} {day} {c}") for c in _PRICE_COLS}
        for col, dec in ohlc.items():
            if dec <= 0:
                raise _fail(ErrorCode.SCHEMA, "non_positive_price", f"{sym} {col}")
            if dec > ds.STANDARD_PRICE_MAX:
                raise _fail(ErrorCode.ABI, "price_out_of_range", f"{sym} {col}")
            decimals = _decimals(dec)
            if decimals > ds.SOURCE_PRICE_DECIMALS:
                raise _fail(
                    ErrorCode.ABI,
                    "precision_beyond_source",
                    f"{sym} {day} {col} has {decimals} decimals; source scale is "
                    f"{ds.SOURCE_PRICE_DECIMALS}",
                )
            places = max(places, decimals)
        if ohlc["high"] < max(ohlc["open"], ohlc["close"], ohlc["low"]) or ohlc[
            "low"
        ] > min(ohlc["open"], ohlc["close"]):
            raise _fail(ErrorCode.SCHEMA, "ohlc_inconsistent", f"{sym} {day}")
        vol = _decimal(row.get("volume"), f"{sym} {day} volume")
        if vol < 0 or vol != vol.to_integral_value():
            raise _fail(ErrorCode.SCHEMA, "bad_volume", f"{sym} {day}")
        prices[day] = ohlc
        volumes[day] = int(vol)
    if places > max_precision:
        raise _fail(
            ErrorCode.ABI,
            "precision_beyond_worker",
            f"{sym} needs {places} decimals; worker supports {max_precision}",
        )
    return places, prices, volumes


def _event_frames(
    reader: FmpCachedReader, symbols: list[str], sessions: list[date]
) -> tuple[list[tuple[str, date, float]], list[tuple[str, date, float]]]:
    """Return in-range (symbol, ex_date, value) splits and dividends."""
    first, last = sessions[0], sessions[-1]
    session_set = set(sessions)
    out: list[list[tuple[str, date, float]]] = []
    for frame, col in (
        (reader.splits(symbols), "ratio"),
        (reader.dividends(symbols), "amount"),
    ):
        events = []
        for sym, ex, value in zip(frame["symbol"], frame["ex_date"], frame[col]):
            day = _as_date(ex)
            if not first <= day <= last:
                continue
            if day not in session_set:
                raise _fail(
                    ErrorCode.SCHEMA,
                    "action_not_on_session",
                    f"{sym} {col} ex-date {day} is not a session",
                )
            if not value or float(value) <= 0:
                raise _fail(ErrorCode.SCHEMA, "bad_action", f"{sym} {col} {day}")
            events.append((str(sym).upper(), day, float(value)))
        out.append(sorted(events))
    return out[0], out[1]


def _check_split_jumps(
    basis: str,
    splits: list[tuple[str, date, float]],
    prices: dict[str, dict[date, dict[str, Decimal]]],
    sessions: list[date],
) -> tuple[int, int]:
    """Fail closed when the price series disagrees with the declared basis.

    At a split ex-date an unadjusted series jumps by about the split ratio
    (prior close / ex-date open); a split-adjusted series does not. A
    ``raw_plus_actions`` series without the jump is already adjusted, so
    applying the split event would adjust it twice.

    Splits that cannot be judged are counted, never rejected: a ratio with
    ``|ln r| < 0.2`` (indistinguishable from an overnight gap) and a split on
    the first session (no prior close). Returns ``(ambiguous, at_window_start)``.
    """
    ambiguous = at_start = 0
    for sym, day, ratio in splits:
        idx = sessions.index(day)
        if idx == 0:
            at_start += 1
            continue
        if abs(math.log(ratio)) < SPLIT_AMBIGUOUS_LOG:
            ambiguous += 1
            continue
        prev_close = float(prices[sym][sessions[idx - 1]]["close"])
        ex_open = float(prices[sym][day]["open"])
        jump = math.log(prev_close / ex_open)
        looks_raw = abs(jump - math.log(ratio)) < abs(jump)
        if basis == "raw_plus_actions" and not looks_raw:
            raise _fail(
                ErrorCode.SCHEMA,
                "double_adjustment",
                f"{sym} shows no price jump at its {ratio:g} split on {day}; the "
                "'unadjusted' rows are already split-adjusted",
            )
        if basis == "split_adjusted_source" and looks_raw:
            raise _fail(
                ErrorCode.SCHEMA,
                "basis_adjustment_mismatch",
                f"{sym} jumps at its {ratio:g} split on {day}; 'splits_only' rows "
                "are not split-adjusted",
            )
    return ambiguous, at_start


def _scaled(dec: Decimal, places: int) -> int:
    return int(dec.scaleb(places))


def _event_value(value: float) -> str:
    return format(Decimal(repr(value)).normalize(), "f")


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    out = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not out:
        raise _fail(ErrorCode.CONFIG, "no_symbols", "at least one symbol is required")
    for sym in out:
        if len(sym) > 16 or not set(sym) <= _SYMBOL_OK:
            raise _fail(ErrorCode.CONFIG, "bad_symbol", repr(sym))
    return out


def _write_atomic(
    out_root: Path,
    bars: pa.Table,
    actions: pa.Table,
    build_manifest: Callable[[dict[str, str]], ds.Manifest],
) -> ExportResult:
    # pylint: disable=import-outside-toplevel
    from openbb_core.app.paths import safe_join

    tmp = out_root / f".export-{os.getpid()}.tmp"
    ds.discard_dir(tmp)
    tmp.mkdir(parents=True)
    try:
        files = {
            ds.BARS_FILE: ds.write_table(bars, tmp / ds.BARS_FILE),
            ds.ACTIONS_FILE: ds.write_table(actions, tmp / ds.ACTIONS_FILE),
        }
        manifest = build_manifest(files)
        ds_id = ds.dataset_id(manifest)
        (tmp / ds.MANIFEST_NAME).write_bytes(ds.manifest_bytes(manifest))
        dest = safe_join(out_root, ds_id)
        ds.place_dataset_dir(tmp, dest, ds_id)
    finally:
        ds.discard_dir(tmp)
    return ExportResult(dataset_id=ds_id, path=dest, manifest=manifest)


def export_dataset(  # pylint: disable=too-many-arguments,too-many-locals
    symbols: Sequence[str],
    start: str | date,
    end: str | date,
    *,
    basis: str,
    out_root: str | Path,
    adjustment: str | None = None,
    execute: Execute | None = None,
    calendar: str = "XNYS",
    max_precision: int = ds.STANDARD_FIXED_PRECISION,
    source_label: str = "fmp_cached",
) -> ExportResult:
    """Export cache rows to a content-addressed neutral dataset; return its id."""
    adjustment = check_basis(basis, adjustment)
    syms = _normalize_symbols(symbols)
    root = _ensure_outside_repo(Path(out_root))
    sessions = [
        ts.date()
        for ts in sessions_in_range(pd.Timestamp(start), pd.Timestamp(end), calendar)
    ]
    if not sessions:
        raise _fail(ErrorCode.CONFIG, "no_sessions", f"no {calendar} sessions")

    recorder = _RecordingExecute(execute or _live_execute())
    reader = FmpCachedReader(execute=recorder)
    query = EQUITY_SQL.format(placeholders=", ".join(["%s"] * len(syms)))
    rows = recorder(query, (*syms, str(sessions[0]), str(sessions[-1])))
    counts = _Counts(rows_read=len(rows))
    chosen = _select_rows(rows, syms, sessions, adjustment, counts)

    places: dict[str, int] = {}
    prices: dict[str, dict[date, dict[str, Decimal]]] = {}
    volumes: dict[str, dict[date, int]] = {}
    for sym in syms:
        places[sym], prices[sym], volumes[sym] = _instrument_prices(
            sym, chosen[sym], max_precision
        )

    splits, dividends = _event_frames(reader, syms, sessions)
    ambiguous, at_start = _check_split_jumps(basis, splits, prices, sessions)
    emitted_splits = splits if basis == "raw_plus_actions" else []

    cal = get_calendar(calendar)
    closes = {d: int(cal.session_close(pd.Timestamp(d)).value) for d in sessions}
    bar_rows: dict[str, list] = {f.name: [] for f in ds.BARS_SCHEMA}
    for sym in syms:
        for day in sessions:
            bar_rows["symbol"].append(sym)
            bar_rows["session"].append(day)
            bar_rows["ts_event"].append(closes[day])
            bar_rows["ts_init"].append(closes[day])
            for col in _PRICE_COLS:
                bar_rows[col].append(_scaled(prices[sym][day][col], places[sym]))
            bar_rows["volume"].append(volumes[sym][day])
    bars = pa.table(bar_rows, schema=ds.BARS_SCHEMA)

    events = sorted(
        [(s, d, "dividend", _event_value(v)) for s, d, v in dividends]
        + [(s, d, "split", _event_value(v)) for s, d, v in emitted_splits]
    )
    actions = pa.table(
        {
            "symbol": [e[0] for e in events],
            "ex_date": [e[1] for e in events],
            "kind": [e[2] for e in events],
            "value": [e[3] for e in events],
        },
        schema=ds.ACTIONS_SCHEMA,
    )

    def build_manifest(files: dict[str, str]) -> ds.Manifest:
        return ds.Manifest(
            symbols=syms,
            start=sessions[0].isoformat(),
            end=sessions[-1].isoformat(),
            calendar=ds.CalendarFacts(
                code=calendar,
                exchange_calendars_version=metadata.version("exchange_calendars"),
                sessions_count=len(sessions),
                sessions_sha256=ds.sessions_digest(sessions),
            ),
            action_basis=basis,  # type: ignore[arg-type]
            max_precision=max_precision,
            instruments=[
                ds.InstrumentFacts(
                    symbol=s, price_precision=places[s], bar_count=len(sessions)
                )
                for s in syms
            ],
            source=ds.SourceFacts(
                label=source_label,
                query_sha256=recorder.fingerprint(),
                adjustment_type=adjustment,
                rows_read=counts.rows_read,
                rows_used=counts.rows_used,
                filled_rows_dropped=counts.filled,
                invalid_rows_dropped=counts.invalid,
                other_adjustment_rows_ignored=counts.other_adjustment,
                split_events=len(splits),
                dividend_events=len(dividends),
                split_events_dropped=len(splits) - len(emitted_splits),
                split_ratio_ambiguous=ambiguous,
                split_at_window_start=at_start,
            ),
            content=ds.ContentFacts(
                bars_sha256=ds.table_digest(bars),
                bars_rows=bars.num_rows,
                actions_sha256=ds.table_digest(actions),
                actions_rows=actions.num_rows,
            ),
            files=files,
            writer={"pyarrow": pa.__version__},
        )

    return _write_atomic(root, bars, actions, build_manifest)


def snapshot_executor(directory: str | Path) -> Execute:
    """Offline executor over a DictCursor-shaped JSON snapshot directory.

    Files: ``equity_historical.json``, ``calendar_splits.json``,
    ``calendar_dividend.json``. Prices become ``Decimal`` and dates ``date``,
    as pymysql returns them. Only the queries this module issues are served.
    """
    base = Path(directory)

    def load(name: str) -> list[dict]:
        return json.loads((base / f"{name}.json").read_text(encoding="utf-8"))

    def execute(query: str, params: tuple = ()) -> list[dict]:
        table = query.split(" FROM ", 1)[1].split(maxsplit=1)[0]
        if table == "equity_historical":
            *syms, lo, hi = params
            out = []
            for row in load(table):
                if row["symbol"] in syms and lo <= row["date"] <= hi:
                    if row.get("interval_type", "1d") != "1d":
                        continue
                    rec = dict(row)
                    rec["date"] = date.fromisoformat(row["date"])
                    for col in _PRICE_COLS:
                        if rec.get(col) is not None:
                            rec[col] = Decimal(str(rec[col]))
                    out.append(rec)
            return out
        if table in ("calendar_splits", "calendar_dividend"):
            return [
                {**r, "date": date.fromisoformat(r["date"])}
                for r in load(table)
                if r["symbol"] in params
            ]
        raise ValueError(f"snapshot has no table for query on {table!r}")

    return execute


def summary(result: ExportResult) -> dict[str, Any]:
    """Return counts and hashes for output; never rows or local paths."""
    man = result.manifest
    return {
        "ok": True,
        "dataset_id": result.dataset_id,
        "symbols": man.symbols,
        "action_basis": man.action_basis,
        "dividend_basis": man.dividend_basis,
        "calendar": man.calendar.model_dump(),
        "instruments": [i.model_dump() for i in man.instruments],
        "source": man.source.model_dump(),
        "content": man.content.model_dump(),
        "files": man.files,
        "writer": man.writer,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: export a dataset and print counts/hashes as JSON (exit 2 on reject)."""
    parser = argparse.ArgumentParser(prog="openbb_backtest.adapters.nautilus.export")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--adjustment", default=None)
    parser.add_argument("--calendar", default="XNYS")
    parser.add_argument(
        "--out-root", default=None, help=f"default: ${DATA_ROOT_ENV}/datasets"
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="offline replay of a DictCursor-shaped JSON snapshot (no database)",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args(argv)
    try:
        out_root = args.out_root
        if not out_root:
            data_root = os.environ.get(DATA_ROOT_ENV)
            if not data_root:
                raise _fail(ErrorCode.CONFIG, "no_out_root", f"{DATA_ROOT_ENV} unset")
            out_root = str(Path(data_root) / "datasets")
        Path(out_root).mkdir(parents=True, exist_ok=True)
        result = export_dataset(
            args.symbols.split(","),
            args.start,
            args.end,
            basis=args.basis,
            adjustment=args.adjustment,
            out_root=out_root,
            calendar=args.calendar,
            execute=snapshot_executor(args.snapshot_dir) if args.snapshot_dir else None,
            source_label="snapshot" if args.snapshot_dir else "fmp_cached",
        )
    except DatasetError as exc:
        err = {
            "ok": False,
            "code": exc.code.value,
            "reason": exc.reason,
            "message": exc.message,
        }
        sys.stdout.write(json.dumps(err) + "\n")
        return 2
    sys.stdout.write(json.dumps(summary(result), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
