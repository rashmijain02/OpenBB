"""A negative-cache hit raises a fresh exception (#1274 review CODE-2).

``providers.retrofit._cached_dispatch`` kept the failing tier's exception
for the negative TTL and re-raised that same object on every hit. Each
``raise`` appends frames to the shared ``__traceback__`` (and pins the
frames' locals), so the cached object grew without bound under refreshes.
A hit must raise a new exception of the same type and args, with no
traceback carried over from earlier raises.
"""

from __future__ import annotations

import traceback

import pytest
from openbb_portfolio_intel.providers import retrofit


class TierDown(ConnectionError):
    """A provider failure that is cached on the negative TTL."""


def _depth(exc: BaseException) -> int:
    return len(traceback.extract_tb(exc.__traceback__))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def dispatch(_tier: str, _family: str, **_kwargs: object) -> object:
        calls.append(1)
        raise TierDown("tier down", 503)

    monkeypatch.setattr(retrofit, "_dispatch", dispatch)
    monkeypatch.setenv("PI_PROVIDER_CACHE_TTL_S", "600")
    monkeypatch.setenv("PI_PROVIDER_CACHE_NEGATIVE_TTL_S", "600")
    retrofit.clear_provider_cache()
    yield calls
    retrofit.clear_provider_cache()


def _raise_once() -> BaseException:
    with pytest.raises(TierDown) as info:
        retrofit._cached_dispatch(  # pylint: disable=protected-access
            "pi/synthetic", "synthetic/family", "fmp_cached", symbol="SYN"
        )
    return info.value


def test_negative_cache_hits_raise_fresh_equal_exceptions(_isolated: list[int]) -> None:
    """Hits re-raise the same type and args but never the cached object."""
    first = _raise_once()
    hits = [_raise_once() for _ in range(5)]
    assert len(_isolated) == 1, "the failing tier is dialled once per negative TTL"
    for hit in hits:
        assert type(hit) is TierDown and hit.args == ("tier down", 503)
        assert hit is not first
    assert len({id(h) for h in hits}) == len(hits)


def test_negative_cache_hit_traceback_does_not_grow(_isolated: list[int]) -> None:
    """Every hit carries only its own raise, not every earlier one."""
    _raise_once()
    depths = [_depth(_raise_once()) for _ in range(6)]
    assert len(set(depths)) == 1, depths
