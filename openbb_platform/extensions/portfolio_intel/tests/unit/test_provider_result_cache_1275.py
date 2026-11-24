"""Short-TTL provider result cache and explicit-demo short-circuit (#1275, plan 11.4).

Exercises ``providers.retrofit.route_through_chain`` / ``with_chain`` with a
synthetic family registered on fake tiers that count their calls. No real
provider, network or database is used.
"""

# pylint: disable=unused-argument  # the clock fixture patches the cache clock

from __future__ import annotations

import threading
from typing import Any

import pytest
from openbb_portfolio_intel.providers import registry, retrofit
from openbb_portfolio_intel.widget_backend import provenance as pv

FAMILY = "synthetic/cache-test"
TIERS = ("fmp_cached", "fmp")
ROWS = [{"symbol": "SYN", "value": 1.0}]


class Tier:
    """A fake tier: answers ``rows`` or raises ``error``; counts calls."""

    def __init__(self, rows: Any = None, error: Exception | None = None) -> None:
        self.rows, self.error, self.calls = rows, error, 0
        self._lock = threading.Lock()

    def __call__(self, **_kwargs: Any) -> Any:
        """Call."""
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rows


class Clock:
    """Monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        """Call."""
        return self.now


@pytest.fixture(name="clock")
def _clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(retrofit, "_cache_clock", clock)
    return clock


@pytest.fixture(autouse=True)
def _isolated(monkeypatch) -> None:
    tiers = {**registry.TIER_REGISTRY, registry.track_key(FAMILY, "A"): TIERS}
    monkeypatch.setattr(retrofit, "TIER_REGISTRY", tiers)
    monkeypatch.setattr(retrofit, "_TIER_CALLS", {})
    monkeypatch.delenv("PI_DEMO_MODE", raising=False)
    for name in ("TTL_S", "NEGATIVE_TTL_S", "MAX_ENTRIES"):
        monkeypatch.delenv(f"PI_PROVIDER_CACHE_{name}", raising=False)
    retrofit.clear_provider_cache()


def _wire(primary: Tier, fallback: Tier | None = None) -> None:
    retrofit.register_tier_call(FAMILY, "fmp_cached", primary)
    retrofit.register_tier_call(
        FAMILY, "fmp", fallback or Tier(error=ConnectionError("down"))
    )


def _route(ledger: list | None = None, **kwargs: Any) -> Any:
    return retrofit.route_through_chain(
        endpoint="pi/synthetic",
        family=FAMILY,
        stub_fallback=lambda: [{"symbol": "STUB"}],
        record_tier_used=lambda _e, tier: (ledger if ledger is not None else []).append(
            tier
        ),
        **kwargs,
    )


def test_identical_call_is_served_from_cache_with_the_real_tier(clock) -> None:
    """Identical call is served from cache with the real tier."""
    primary = Tier(rows=ROWS)
    _wire(primary)
    ledger: list[str] = []

    first = _route(ledger, symbol="SYN")
    second = _route(ledger, symbol="SYN")

    assert first == second == ROWS
    assert primary.calls == 1
    assert ledger == ["fmp_cached", "fmp_cached"]


def test_params_are_normalized_and_part_of_the_key(clock) -> None:
    """Params are normalized and part of the key."""
    primary = Tier(rows=ROWS)
    _wire(primary)

    _route(symbol="SYN", window="3M")
    _route(window="3M", symbol="SYN")
    _route(symbol="OTHER", window="3M")

    assert primary.calls == 2


def test_entries_expire_after_the_configured_ttl(monkeypatch, clock) -> None:
    """Entries expire after the configured ttl."""
    monkeypatch.setenv("PI_PROVIDER_CACHE_TTL_S", "30")
    primary = Tier(rows=ROWS)
    _wire(primary)

    _route(symbol="SYN")
    clock.now += 29
    _route(symbol="SYN")
    clock.now += 2
    _route(symbol="SYN")

    assert primary.calls == 2


def test_default_ttl_is_sensible() -> None:
    """Default ttl is sensible."""
    assert 10 <= retrofit.provider_cache_ttl() <= 300
    assert 0 < retrofit.provider_cache_negative_ttl() <= retrofit.provider_cache_ttl()


def test_failures_are_cached_briefly(monkeypatch, clock) -> None:
    """Failures are cached briefly."""
    monkeypatch.setenv("PI_PROVIDER_CACHE_NEGATIVE_TTL_S", "5")
    primary = Tier(error=ConnectionError("synthetic connection refused"))
    fallback = Tier(error=ConnectionError("synthetic connection refused"))
    _wire(primary, fallback)
    ledger: list[str] = []

    assert _route(ledger, symbol="SYN") == [{"symbol": "STUB"}]
    assert _route(ledger, symbol="SYN") == [{"symbol": "STUB"}]
    assert (primary.calls, fallback.calls) == (1, 1)
    clock.now += 6
    _route(ledger, symbol="SYN")
    assert (primary.calls, fallback.calls) == (2, 2)
    assert ledger == ["stub", "stub", "stub"]


def test_empty_results_are_negative_cached(monkeypatch, clock) -> None:
    """Empty results are negative cached."""
    monkeypatch.setenv("PI_PROVIDER_CACHE_NEGATIVE_TTL_S", "5")
    primary = Tier(rows=[])
    fallback = Tier(rows=ROWS)
    _wire(primary, fallback)

    _route(symbol="SYN")
    _route(symbol="SYN")
    clock.now += 6
    _route(symbol="SYN")

    assert primary.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("403 Forbidden"),
        RuntimeError("401 Unauthorized: invalid API key"),
        type("HttpError", (Exception,), {"status_code": 403})("denied"),
    ],
    ids=["403", "401", "status_code"],
)
def test_auth_failures_are_never_cached(clock, error: Exception) -> None:
    """Auth failures are never cached."""
    primary = Tier(error=error)
    _wire(primary, Tier(rows=ROWS))

    _route(symbol="SYN")
    _route(symbol="SYN")

    assert primary.calls == 2


def test_cache_is_bounded(monkeypatch, clock) -> None:
    """Cache is bounded."""
    monkeypatch.setenv("PI_PROVIDER_CACHE_MAX_ENTRIES", "2")
    primary = Tier(rows=ROWS)
    _wire(primary)

    for symbol in ("A", "B", "C"):
        _route(symbol=symbol)
    assert retrofit.provider_cache_size() <= 2
    _route(symbol="A")  # evicted (least recently used): refetched

    assert primary.calls == 4


def test_ttl_zero_disables_the_cache(monkeypatch, clock) -> None:
    """Ttl zero disables the cache."""
    monkeypatch.setenv("PI_PROVIDER_CACHE_TTL_S", "0")
    primary = Tier(rows=ROWS)
    _wire(primary)

    _route(symbol="SYN")
    _route(symbol="SYN")

    assert primary.calls == 2
    assert retrofit.provider_cache_size() == 0


def test_cached_values_are_isolated_copies(clock) -> None:
    """Cached values are isolated copies."""
    _wire(Tier(rows=[{"symbol": "SYN", "value": 1.0}]))

    first = _route(symbol="SYN")
    first[0]["value"] = 999.0

    assert _route(symbol="SYN")[0]["value"] == 1.0


def test_concurrent_identical_calls_are_safe(clock) -> None:
    """Concurrent identical calls are safe."""
    primary = Tier(rows=ROWS)
    _wire(primary)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(_route(symbol="SYN"))
        except BaseException as exc:  # noqa: BLE001 - collected for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == [ROWS] * 16
    assert 1 <= primary.calls <= 16
    assert retrofit.provider_cache_size() == 1


def test_cache_hit_keeps_real_provenance(clock) -> None:
    """A cached fmp_cached answer is still reported as ``cached`` from fmp_cached."""
    _wire(Tier(rows=ROWS))
    records = []
    for _ in range(2):
        with pv.scope() as holder:
            retrofit.route_through_chain(
                endpoint="pi/synthetic",
                family=FAMILY,
                stub_fallback=lambda: [],
                record_tier_used=lambda _e, tier: pv.record_tier(tier),
                symbol="SYN",
            )
            records.append(pv.resolve(holder))
    assert [(r.state, r.source) for r in records] == [
        (pv.DataState.CACHED, "fmp_cached"),
        (pv.DataState.CACHED, "fmp_cached"),
    ]


# ---------------------------------------------------------------------------
# Explicit demo selection (synthetic holdings, provider analytics)
# ---------------------------------------------------------------------------


def _wrapped(primary: Tier, ledger: list[str]) -> Any:
    _wire(primary)

    @retrofit.with_chain(
        endpoint="pi/synthetic",
        family=FAMILY,
        record_tier_used=lambda _e, tier: ledger.append(tier),
        kwargs_from=lambda **kw: {"symbol": "SYN"},
    )
    def endpoint(account_id: str = "demo", basket_id: str = "") -> Any:
        return [{"book": account_id or basket_id}]

    return endpoint


@pytest.mark.parametrize("params", [{"account_id": "demo"}, {"basket_id": "demo"}])
def test_explicit_demo_book_keeps_provider_analytics_and_is_cache_bounded(
    clock, params
) -> None:
    """The demo book still gets provider analytics (#1269); repeats are cached.

    An explicit demo selection means synthetic holdings, not synthetic market
    data: a live tier answer for the demo book is served (and labelled) as
    provider data. Repeated identical requests cost one provider call per TTL.
    """
    primary, ledger = Tier(rows=ROWS), list[str]()
    endpoint = _wrapped(primary, ledger)

    for _ in range(3):
        assert endpoint(**params) == ROWS
    assert primary.calls == 1
    assert ledger == ["fmp_cached"] * 3


def test_non_demo_selection_still_uses_providers(clock) -> None:
    """Non demo selection still uses providers."""
    primary, ledger = Tier(rows=ROWS), list[str]()
    endpoint = _wrapped(primary, ledger)

    assert endpoint(account_id="Z00000001") == ROWS
    assert primary.calls == 1
    assert ledger == ["fmp_cached"]
