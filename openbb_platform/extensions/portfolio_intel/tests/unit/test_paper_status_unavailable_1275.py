"""Paper-status widget reports an unreachable paper engine explicitly (#1275, #1269).

When the paper engine cannot be reached (MySQL down, driver error), the
``tt_execute_paper_status`` markdown widget must answer 200 with the
``unavailable`` data state and a fixed reason, never a 500, and must not echo
the driver's error text (it can carry host or user names). Synthetic errors
only; no database is contacted.
"""

# pylint: disable=wrong-import-position  # auth mode must be set before the app import

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402
from openbb_techtrade.execution import paper_engine  # noqa: E402

_CLIENT = TestClient(app, raise_server_exceptions=False)
_URL = "/tt/execute/paper-status/markdown"
_LEAK = "db-host-sentinel.invalid"


class _BrokenEngine:
    """Engine whose reads fail like a dropped MySQL connection."""

    def is_initialized(self) -> bool:
        """Is initialized."""
        raise ConnectionError(f"synthetic: lost connection to {_LEAK}")

    def close(self) -> None:
        """Nothing to release."""


def _unreachable(**_kwargs: Any) -> Any:
    raise OSError(f"synthetic: can't connect to MySQL server on {_LEAK}")


@pytest.mark.parametrize(
    "factory", [_unreachable, lambda **_kw: _BrokenEngine()], ids=["init", "read"]
)
def test_unreachable_paper_engine_is_unavailable_not_500(monkeypatch, factory) -> None:
    """Unreachable paper engine is unavailable not 500."""
    monkeypatch.setenv("PI_PAPER_ENGINE", "mysql")
    monkeypatch.setattr(paper_engine, "get_default_engine", factory)

    response = _CLIENT.get(_URL)

    assert response.status_code == 200
    assert response.headers["x-pi-data-state"] == "unavailable"
    assert "**Data state:** Unavailable" in response.text
    assert "paper engine is unreachable" in response.text
    assert _LEAK not in response.text
    assert _LEAK not in " ".join(response.headers.values())
