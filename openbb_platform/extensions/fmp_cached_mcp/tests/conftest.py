"""Shared fixtures for openbb_fmp_cached_mcp tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Import the fmp_cached provider from this checkout, not whichever checkout the
# shared venv's editable install points at (its prune allowlist is under test).
_PROVIDER = Path(__file__).resolve().parents[3] / "providers" / "fmp_cached"
if _PROVIDER.is_dir() and str(_PROVIDER) not in sys.path:
    sys.path.insert(0, str(_PROVIDER))

HOSTED = Path(__file__).parent / "fixtures" / "hosted"
SNAPSHOT = "2026-11-24"


def load_hosted(name: str):
    return json.loads((HOSTED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def hosted_inventory() -> dict:
    return load_hosted(f"inventory-{SNAPSHOT}.json")


@pytest.fixture(scope="session")
def hosted_paths() -> dict:
    return load_hosted(f"paths-{SNAPSHOT}.json")


@pytest.fixture(scope="session")
def hosted_errors() -> list[dict]:
    return load_hosted(f"errors-{SNAPSHOT}.json")["cases"]
