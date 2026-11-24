"""Shared fixtures for openbb_fmp_cached_mcp tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
