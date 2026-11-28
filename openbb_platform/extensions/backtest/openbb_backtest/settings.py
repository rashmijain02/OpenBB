"""Runtime settings for the backtest extension.

Database access reuses the fmp_cached ``DatabaseConfig`` (component 03); no new
secrets are introduced here. API credentials continue to resolve from
``~/.openbb_platform/user_settings.json`` / environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestSettings(BaseSettings):
    """Environment-configurable backtest defaults (prefix ``OPENBB_BACKTEST_``)."""

    model_config = SettingsConfigDict(env_prefix="OPENBB_BACKTEST_", extra="ignore")

    default_calendar: str = "XNYS"
    default_engine: str = "auto"
    default_provider: str = "fmp_cached"
    reconcile_tolerance: float = 1e-6
    seed: int = 0
    export_dir: str = "Analysis/exports"
    bundle_root: str = ".openbb_backtest/bundles"
    # #1356: ``legacy`` until the HFP-P18 cutover; ``nautilus`` only on request.
    default_backend: str = "legacy"
    # Worker runtime for ``backend="nautilus"`` (``native`` or ``docker``, see
    # ``nautilus_worker/pin.yaml``). Unset means the backend is unavailable.
    nautilus_runtime: str | None = None
    nautilus_timeout_seconds: float = 120.0
    # #1357 experiment bounds, checked at plan time before any spawn.
    runs_root: str = ".openbb_backtest"
    experiment_max_configs: int = 64
    experiment_max_cells: int = 512
    experiment_max_attempts: int = 2


DEFAULT_SETTINGS = BacktestSettings()
