"""Pytest config: make ``openbb_nautilus_worker`` importable from the source tree."""

import datetime
import importlib.util
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def pytest_configure(config):
    """Register the marker for tests that need the real nautilus_trader wheel."""
    config.addinivalue_line(
        "markers",
        "requires_nautilus: needs nautilus_trader importable (worker venv only).",
    )


def pytest_collection_modifyitems(config, items):  # pylint: disable=unused-argument
    """Skip ``requires_nautilus`` tests unless nautilus_trader is importable."""
    if importlib.util.find_spec("nautilus_trader") is not None:
        return
    skip = pytest.mark.skip(reason="nautilus_trader not installed (worker venv only)")
    for item in items:
        if "requires_nautilus" in item.keywords:
            item.add_marker(skip)


ORACLE_PATH = os.path.join(
    os.path.dirname(_ROOT),
    "tests",
    "unit",
    "nautilus",
    "fixtures",
    "buy_and_hold_oracle.json",
)


@pytest.fixture(name="oracle")
def oracle_fixture():
    """Load the hand-computed buy-and-hold oracle (#1355), shared with facade tests."""
    with open(ORACLE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(name="make_dataset")
def make_dataset_fixture(oracle):
    """Build a content-addressed neutral dataset from the oracle under ``root``.

    Returns ``build(root, *, precision=2) -> dataset_id``. ``root`` is the
    ``datasets`` directory. Uses only :mod:`openbb_nautilus_worker.dataset`.
    """
    # pylint: disable=import-outside-toplevel
    from datetime import date
    from decimal import Decimal

    import pyarrow as pa
    from openbb_nautilus_worker import dataset as ds

    def build(root, *, precision=2):
        root.mkdir(parents=True, exist_ok=True)
        sessions = [date.fromisoformat(s) for s in oracle["sessions"]]
        scaled = [int(Decimal(c).scaleb(precision)) for c in oracle["closes"]]
        ts = [
            int(
                datetime.datetime(
                    d.year, d.month, d.day, 21, tzinfo=datetime.timezone.utc
                ).timestamp()
            )
            * 10**9
            for d in sessions
        ]
        n = len(sessions)
        bars = pa.table(
            {
                "symbol": [oracle["symbol"]] * n,
                "session": sessions,
                "ts_event": ts,
                "ts_init": ts,
                "open": scaled,
                "high": scaled,
                "low": scaled,
                "close": scaled,
                "volume": [1000] * n,
            },
            schema=ds.BARS_SCHEMA,
        )
        actions = pa.table(
            {"symbol": [], "ex_date": [], "kind": [], "value": []},
            schema=ds.ACTIONS_SCHEMA,
        )
        tmp = root / ".build"
        tmp.mkdir()
        files = {
            ds.BARS_FILE: ds.write_table(bars, tmp / ds.BARS_FILE),
            ds.ACTIONS_FILE: ds.write_table(actions, tmp / ds.ACTIONS_FILE),
        }
        manifest = ds.Manifest(
            symbols=[oracle["symbol"]],
            start=oracle["sessions"][0],
            end=oracle["sessions"][-1],
            calendar=ds.CalendarFacts(
                code="XNYS",
                exchange_calendars_version="4.13.2",
                sessions_count=n,
                sessions_sha256=ds.sessions_digest(sessions),
            ),
            action_basis="raw_plus_actions",
            max_precision=16,
            instruments=[
                ds.InstrumentFacts(
                    symbol=oracle["symbol"], price_precision=precision, bar_count=n
                )
            ],
            source=ds.SourceFacts(
                label="synthetic-oracle",
                query_sha256="0" * 64,
                adjustment_type="unadjusted",
                rows_read=n,
                rows_used=n,
                filled_rows_dropped=0,
                invalid_rows_dropped=0,
                other_adjustment_rows_ignored=0,
                split_events=0,
                dividend_events=0,
                split_events_dropped=0,
            ),
            content=ds.ContentFacts(
                bars_sha256=ds.table_digest(bars),
                bars_rows=n,
                actions_sha256=ds.table_digest(actions),
                actions_rows=0,
            ),
            files=files,
            writer={"pyarrow": pa.__version__},
        )
        ds_id = ds.dataset_id(manifest)
        (tmp / ds.MANIFEST_NAME).write_bytes(ds.manifest_bytes(manifest))
        tmp.rename(root / ds_id)
        return ds_id

    return build
