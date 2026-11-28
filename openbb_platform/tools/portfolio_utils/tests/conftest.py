"""Shared test setup for portfolio_utils (#1344).

``run_position_history_warm`` now takes the per-target fmp-sync lock. Keep every
test's lock/state files under ``tmp_path`` instead of the operator's real
``%LOCALAPPDATA%\OpenBB\fmp-sync`` root.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_fmp_sync_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("FMP_SYNC_STATE_ROOT", str(tmp_path / "fmp-sync-state"))
