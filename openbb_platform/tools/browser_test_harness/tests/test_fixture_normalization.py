"""Observed-at normalization for harness fixtures (#1269).

Backend-local state carries a real UTC observation time (``data_as_of``,
``layout.meta.asOf``, the Markdown ``as of`` clause). The recorder and the
drift check normalize only those positions, so fixtures stay deterministic
while any shape or state change still shows up as drift.
"""

from __future__ import annotations

import ast
import inspect

from openbb_browser_test_harness import snapshot
from openbb_browser_test_harness.drivers import standalone_driver
from openbb_browser_test_harness.normalize import OBSERVED_AT, normalize_observed_at

_TS = "2026-11-21T19:00:00+00:00"


def test_only_observation_times_are_normalized() -> None:
    """``data_as_of``, ``meta.asOf`` and the Markdown clause; nothing else."""
    body = {
        "rows": [
            {"time": _TS, "data_state": "live", "data_as_of": _TS},
            {"data_state": "stale", "data_as_of": "2026-09-11"},
            {"data_state": "cached", "data_as_of": "unknown"},
        ],
        "layout": {"meta": {"state": "live", "asOf": _TS}},
        "text": f"**Data state:** Live - x. Source: `request`; as of {_TS}.",
    }
    out = normalize_observed_at(body)
    assert out["rows"][0] == {
        "time": _TS,
        "data_state": "live",
        "data_as_of": OBSERVED_AT,
    }
    assert out["rows"][1]["data_as_of"] == "2026-09-11"
    assert out["rows"][2]["data_as_of"] == "unknown"
    assert out["layout"]["meta"]["asOf"] == OBSERVED_AT
    assert out["text"].endswith(f"as of {OBSERVED_AT}.")
    assert body["rows"][0]["data_as_of"] == _TS, "input is not mutated"


def test_state_and_shape_changes_still_drift() -> None:
    """Normalization cannot hide a changed state, value or key."""
    base = [{"value": 1, "data_state": "live", "data_as_of": _TS}]
    later = [{"value": 1, "data_state": "live", "data_as_of": "2026-11-22T01:02:03Z"}]
    assert normalize_observed_at(base) == normalize_observed_at(later)
    for changed in (
        [{"value": 1, "data_state": "demo", "data_as_of": _TS}],
        [{"value": 2, "data_state": "live", "data_as_of": _TS}],
        [{"value": 1, "extra": 0, "data_state": "live", "data_as_of": _TS}],
    ):
        assert normalize_observed_at(base) != normalize_observed_at(changed)


def _calls(module: object, name: str) -> int:
    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def test_recorder_normalizes_what_it_writes() -> None:
    """The fixture recorder writes normalized bodies."""
    assert _calls(snapshot, "normalize_observed_at") >= 1


def test_standalone_driver_selects_demo_fallback_explicitly() -> None:
    """The harness backend is configured with ``PI_DEMO_MODE=fallback``."""
    tree = ast.parse(inspect.getsource(standalone_driver))
    assigned = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Subscript)
        and isinstance(node.targets[0].slice, ast.Constant)
        and node.targets[0].slice.value == "PI_DEMO_MODE"
        and isinstance(node.value, ast.Constant)
    ]
    assert assigned == ["fallback"]
