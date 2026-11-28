"""Argument validation reproduces the hosted zod error texts (#1299)."""

from __future__ import annotations

import pytest
from openbb_fmp_cached_mcp.validation import validate_arguments

from .conftest import SNAPSHOT, load_hosted

CASES = [
    c
    for c in load_hosted(f"errors-{SNAPSHOT}.json")["cases"]
    if c["label"] not in ("unknown_tool", "fmp_missing_param", "fmp_unknown_symbol")
]


@pytest.mark.parametrize("case", CASES, ids=[c["label"] for c in CASES])
def test_validation_matches_hosted(case):
    result = case["response"]["result"]
    cleaned, error = validate_arguments(case["tool"], case["arguments"])
    if result.get("isError"):
        assert error == result["content"][0]["text"]
        assert cleaned is None
    else:
        assert error is None
        assert "bogus" not in cleaned  # zod strips unknown keys silently


def test_valid_arguments_pass_through_in_order():
    cleaned, error = validate_arguments(
        "chart", {"symbol": "AAPL", "endpoint": "intraday-1-min", "extended": True}
    )
    assert error is None
    assert cleaned == {"symbol": "AAPL", "endpoint": "intraday-1-min", "extended": True}


def test_array_item_type_error_has_index_path():
    _, error = validate_arguments(
        "quote", {"endpoint": "batch-quote", "symbols": ["AAPL", 3]}
    )
    assert '"path": [\n      "symbols",\n      1\n    ]' in error
    assert "Expected string, received number" in error


def test_enum_given_wrong_type():
    _, error = validate_arguments("quote", {"endpoint": 5})
    assert '"code": "invalid_type"' in error
    assert "received number" in error
