"""Legacy numbers are bit-identical to origin/portfolio's code (#1357, D6).

``fixtures/legacy_golden_1357.json`` was captured by running
``legacy_scenarios_1357.capture`` against origin/portfolio (f7ce26ccc), before
#1357 routed sweep / validate / tearsheet / reconcile to the nautilus backend.
The legacy default must reproduce every float exactly (``float.hex``) and
carry no experiment summary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import legacy_scenarios_1357 as scenarios

GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_golden_1357.json").read_text("utf-8")
)
KEYS = sorted(k for k in GOLDEN if not k.startswith("_"))


@pytest.fixture(scope="module", name="captured")
def captured_fixture():
    return scenarios.capture()


def test_golden_was_captured_from_origin_portfolio():
    assert GOLDEN["_source"].startswith("origin/portfolio")
    assert KEYS == [
        "reconcile",
        "sweep",
        "tearsheet_auto",
        "tearsheet_event",
        "validate_cpcv",
        "validate_wfo",
    ]


@pytest.mark.parametrize("key", KEYS)
def test_legacy_numbers_unchanged(captured, key):
    got = dict(captured[key])
    want = dict(GOLDEN[key])
    # Fields added by #1357 are additive; legacy leaves them at their defaults.
    for extra, default in (
        ("experiment", None),
        ("diagnostic_only", False),
        ("modeled_differences", []),
    ):
        if extra in got and extra not in want:
            assert got.pop(extra) == default, extra
    assert got == want
