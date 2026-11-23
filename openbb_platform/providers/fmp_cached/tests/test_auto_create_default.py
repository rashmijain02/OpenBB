"""One default for FMP_CACHE_AUTO_CREATE_DB across both init paths (#1293).

``cache_schema.should_auto_create()`` and ``database.init_database()`` must
reach the same decision for every value of the variable. Hermetic: the
decision is observed through ``DatabaseConfig``, which ``init_database``
constructs only when it is going to create the database; it is replaced
with a stub that raises, so no connection is ever attempted.
"""

from __future__ import annotations

import pytest
from openbb_fmp_cached.utils import cache_schema, database


class _WouldCreate(Exception):
    """Raised by the stub when init_database decides to auto-create."""


def _init_database_decides_to_create(monkeypatch) -> bool:
    def _stub():
        raise _WouldCreate

    monkeypatch.setattr(database, "DatabaseConfig", _stub)
    try:
        database.init_database()
    except _WouldCreate:
        return True
    return False


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("true", True), ("TRUE", True), ("false", False), ("", False)],
)
def test_both_init_paths_agree(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("FMP_CACHE_AUTO_CREATE_DB", raising=False)
    else:
        monkeypatch.setenv("FMP_CACHE_AUTO_CREATE_DB", value)

    assert cache_schema.should_auto_create() is expected
    assert _init_database_decides_to_create(monkeypatch) is expected


def test_default_is_defined_once():
    assert database.AUTO_CREATE_DB_DEFAULT is False
    assert database.AUTO_CREATE_DB_ENV == "FMP_CACHE_AUTO_CREATE_DB"


def test_explicit_argument_still_overrides_environment(monkeypatch):
    monkeypatch.setenv("FMP_CACHE_AUTO_CREATE_DB", "true")
    monkeypatch.setattr(database, "DatabaseConfig", lambda: pytest.fail("created"))

    assert database.init_database(auto_create=False) is True
