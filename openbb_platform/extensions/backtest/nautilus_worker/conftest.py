"""Pytest config: make ``openbb_nautilus_worker`` importable from the source tree."""

import importlib.util
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
