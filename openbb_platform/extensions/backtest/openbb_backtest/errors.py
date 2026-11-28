"""Backtest error hierarchy (component 09.1).

Every error the ``obb.backtest.*`` surface raises subclasses OpenBB's
:class:`~openbb_core.app.model.abstract.error.OpenBBError`, so callers can catch
backtest failures with the same ``except OpenBBError`` they already use across
the platform, while the more specific subclasses carry actionable context:

- :class:`BacktestError` — the package root error (catch-all).
- :class:`OptionalDependencyError` — a lazily-imported heavy dependency (zipline,
  numba, …) is missing; the message includes a ready-to-run ``pip install`` hint.
- :class:`EngineSelectionError` — an unknown ``engine=`` was requested; the
  message lists the valid choices.

See ``docs/designs/backtest-design/09-api-surface.md`` §2.
"""

from __future__ import annotations

from collections.abc import Sequence

from openbb_core.app.model.abstract.error import OpenBBError


class BacktestError(OpenBBError):
    """Base class for all errors raised by the backtest extension."""


class OptionalDependencyError(BacktestError):
    """A required optional dependency is not installed.

    Parameters
    ----------
    dependency
        The distribution name that is missing (e.g. ``"zipline-reloaded"``).
    feature
        Optional human-readable description of the capability that needs it,
        woven into the message (e.g. ``"the event-driven engine"``).
    extra
        Optional ``openbb-backtest`` extras group that installs the dependency;
        when given, the hint points at ``pip install 'openbb-backtest[extra]'``
        instead of the bare distribution.
    """

    def __init__(
        self,
        dependency: str,
        *,
        feature: str | None = None,
        extra: str | None = None,
    ) -> None:
        self.dependency = dependency
        self.feature = feature
        self.extra = extra
        target = f"openbb-backtest[{extra}]" if extra else dependency
        what = f" for {feature}" if feature else ""
        message = (
            f"Optional dependency '{dependency}' is required{what} but is not "
            f"installed. Install it with: pip install '{target}'"
        )
        super().__init__(message)


class EngineSelectionError(BacktestError):
    """An unknown or unsupported engine name was requested.

    Parameters
    ----------
    requested
        The engine name the caller asked for.
    available
        The valid engine names, listed in the message to guide the caller.
    """

    def __init__(self, requested: str, *, available: Sequence[str]) -> None:
        self.requested = requested
        self.available = list(available)
        choices = ", ".join(self.available)
        super().__init__(
            f"Unknown engine '{requested}'. Choose one of: {choices}."
        )


class _BackendError(BacktestError):
    """Shared shape of the backend errors (#1356): a message plus context.

    ``reason`` names the specific check (for a worker or reviewed-loader
    rejection it is the worker's own ``reason``) and ``code`` is the failed
    layer (a ``FailedLayer`` value such as ``schema`` or ``module_origin``).
    Both are ``None`` when the facade itself rejected the request.
    """

    def __init__(
        self, message: str, *, reason: str | None = None, code: str | None = None
    ) -> None:
        self.reason = reason
        self.code = code
        super().__init__(message)


class BackendSelectionError(_BackendError):
    """An unknown backend, or a backend/engine combination that cannot run."""


class BackendUnavailableError(_BackendError):
    """The selected backend cannot run here (not configured, not qualified, failed).

    The legacy engine is never used as a fallback.
    """


class UnsupportedSemanticsError(_BackendError):
    """The request needs semantics the selected backend does not implement.

    Raised for an unreviewed or plugin strategy on ``nautilus``, a reviewed-only
    strategy on ``legacy``, unsupported execution assumptions, and the commands
    that do not route to ``nautilus`` yet (HFP-P17).
    """
