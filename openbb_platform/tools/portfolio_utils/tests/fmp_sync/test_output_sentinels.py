"""Secret-bearing failures never reach stdout/stderr or any persisted file (#1344-T02, D6)."""

from __future__ import annotations

import logging
import os
import sys
from functools import partial
from pathlib import Path

import requests
from portfolio_utils.fmp_sync.__main__ import main
from portfolio_utils.fmp_sync.dispatcher import run_prices

from .test_admission import world  # noqa: F401  (fixture)
from .test_budget import FMP_URL
from .test_dispatcher import LIMITS, _state, harness  # noqa: F401  (fixture)

KEY = "sk-SENTINEL-9f3a7c21"


def _leaky_fetch(symbol, **_kwargs):
    print(f"api key {KEY} for {symbol}")
    print(KEY, file=sys.stderr)
    os.write(1, KEY.encode())
    os.write(2, KEY.encode())
    logging.getLogger().error("root %s", KEY)
    logging.getLogger("provider.child").error("child %s", KEY)
    resp = requests.get(FMP_URL, params={"apikey": KEY, "symbol": symbol})
    raise RuntimeError(f"upstream failed {KEY} {resp.url}")


def _all_state_text() -> str:
    parts = []
    for path in Path(_state()).rglob("*"):
        if path.is_file():
            parts.append(path.read_bytes().decode("utf-8", "replace"))
    return "\n".join(parts)


def test_secret_never_leaves_the_dispatcher(harness, capfd):  # noqa: F811
    def leaky_holiday(start, end, database):
        print(KEY)

    def leaky_readiness(symbols, database=None):
        raise RuntimeError(f"cannot read {KEY}")

    out = harness.run(
        fetch_one_fn=_leaky_fetch,
        api_key_resolver=lambda: KEY,
        holiday_fn=leaky_holiday,
        readiness_fn=leaky_readiness,
    )
    captured = capfd.readouterr()
    assert out.counts.failed == 3 and out.exit_code == 30
    assert KEY not in captured.out and KEY not in captured.err
    assert captured.out == "" and captured.err == ""
    assert KEY not in out.model_dump_json() and KEY not in out.to_line()
    assert KEY not in _all_state_text()
    assert _all_state_text(), "the run file was written"


def test_main_prints_one_counts_only_line(harness, capfd, tmp_path):  # noqa: F811
    harness.dmap_make(limits=LIMITS, account_label="acct")  # writes <tmp>/map.json
    map_path = tmp_path / "map.json"
    runner = partial(
        run_prices,
        fetch_one_fn=_leaky_fetch,
        api_key_resolver=lambda: KEY,
        inner_send=harness.inner_send,
        clock=harness.mono,
        now_fn=harness.wall,
        holiday_fn=lambda *a: None,
        readiness_fn=lambda *a: {},
        admit_kwargs=harness.admit_kwargs,
    )
    code = main(["prices", "--execute", "--map", str(map_path)], runner=runner)
    text = capfd.readouterr().out
    assert code == 30
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1 and len(lines[0]) <= 512
    assert KEY not in text and "AAA" not in text and "SPY" not in text
