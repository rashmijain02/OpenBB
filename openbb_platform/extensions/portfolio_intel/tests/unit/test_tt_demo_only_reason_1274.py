"""TechTrade empty-snapshot messages name ``PI_DEMO_MODE=only`` (#1274).

In the browser re-run with ``PI_DEMO_MODE=only`` the TechTrade tables said
"No EOD snapshot available ... run the post-close snapshot job" although the
real reason is that demo-only mode never reads the operator snapshot store.
Each empty-snapshot body must say so; ``fallback`` keeps the old wording.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

_client = TestClient(app)
DEMO_ONLY = "PI_DEMO_MODE=only"

URLS = (
    "/tt/scan/table",
    "/tt/position/order-legs?symbol=AAPL",
    "/tt/validation/verdict?symbol=AAPL",
    "/tt/tuning/report?symbol=AAPL",
    "/tt/audit/journal?symbol=AAPL",
    "/tt/position/signal-card?symbol=AAPL",
    "/tt/position/plan-card?symbol=AAPL",
    "/tt/scan/export",
)


def _body_text(url: str) -> str:
    response = _client.get(url)
    assert response.status_code == 200, url
    body = response.json()
    if isinstance(body, str):
        return body
    return " ".join(str(row.get("note") or "") for row in body)


@pytest.mark.parametrize("url", URLS)
def test_demo_only_empty_snapshot_message_names_demo_mode(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-snapshot body says the store is not read in demo-only mode."""
    monkeypatch.setenv("PI_DEMO_MODE", "only")
    text = _body_text(url)
    assert "No EOD snapshot available" in text
    assert DEMO_ONLY in text


@pytest.mark.parametrize("url", URLS[:2])
def test_fallback_empty_snapshot_message_is_unchanged(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside demo-only mode the message keeps pointing at the snapshot job."""
    monkeypatch.setenv("PI_DEMO_MODE", "fallback")
    monkeypatch.setattr(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        lambda: _Empty(),
    )
    text = _body_text(url)
    assert "post-close snapshot job" in text
    assert DEMO_ONLY not in text


class _Empty:
    def get_live(self, _dataset: str, _key: str) -> None:
        return None

    def get_live_many(self, _dataset: str, _keys: list[str]) -> dict:
        return {}
