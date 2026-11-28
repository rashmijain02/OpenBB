"""CLI store selection (#1300) and plan_limited aliases (B7)."""

from __future__ import annotations

import pytest

from openbb_fmp_cached_mcp import __main__ as cli
from openbb_fmp_cached_mcp.endpoint_map import PLAN_LIMITED_ALIASES, load_endpoint_map
from openbb_fmp_cached_mcp.service import StoreBackedUpstream
from openbb_fmp_cached_mcp.store import StoreUnavailable
from openbb_fmp_cached_mcp.upstream import FmpRestUpstream


def test_sqlite_store_is_created(tmp_path):
    up, rest = cli.build_upstream("k" * 32, f"sqlite:{tmp_path / 's.db'}")
    assert isinstance(up, StoreBackedUpstream) and isinstance(rest, FmpRestUpstream)
    assert (tmp_path / "s.db").exists()


def test_none_store_is_live_only():
    up, rest = cli.build_upstream("k" * 32, "none")
    assert up is rest


class _DownMySql:
    dialect = "mysql"

    def __init__(self):
        raise StoreUnavailable("OperationalError")


def test_auto_store_falls_back_to_live_when_mysql_is_down(monkeypatch, caplog):
    monkeypatch.setattr(cli, "MySqlDatabase", _DownMySql)
    up, rest = cli.build_upstream("k" * 32, "auto")
    assert up is rest
    assert any("store unavailable" in r.getMessage() for r in caplog.records)


def test_mysql_store_refuses_to_start_when_down(monkeypatch):
    monkeypatch.setattr(cli, "MySqlDatabase", _DownMySql)
    with pytest.raises(cli.StoreSetupError):
        cli.build_upstream("k" * 32, "mysql")


def test_plan_limited_aliases_name_real_endpoints_and_registry_entries():
    plan_limited = pytest.importorskip("openbb_fmp_cached.utils.plan_limited")
    emap = load_endpoint_map()
    for key, model in PLAN_LIMITED_ALIASES.items():
        tool, ep = key.split("/", 1)
        assert ep in emap[tool], key
        assert plan_limited.is_plan_limited(model), model


def test_unopenable_sqlite_path_is_a_clean_setup_error(tmp_path):
    with pytest.raises(cli.StoreSetupError):
        cli.build_upstream("k" * 32, f"sqlite:{tmp_path / 'missing' / 'dir' / 'x.db'}")


class _CreateDenied:
    """MySQL reachable, but the user lacks CREATE (error 1142)."""

    dialect = "mysql"

    def execute(self, sql, params=()):
        from openbb_fmp_cached_mcp.store import (  # pylint: disable=C0415
            StoreDataError,
        )

        raise StoreDataError("OperationalError 1142")

    def query(self, sql, params=()):
        return []


def test_auto_store_goes_live_when_mysql_refuses_create(monkeypatch, caplog):
    monkeypatch.setattr(cli, "MySqlDatabase", _CreateDenied)
    up, rest = cli.build_upstream("k" * 32, "auto")
    assert up is rest
    assert any("store unavailable" in r.getMessage() for r in caplog.records)


def test_mysql_store_exits_cleanly_when_mysql_refuses_create(monkeypatch):
    monkeypatch.setattr(cli, "MySqlDatabase", _CreateDenied)
    with pytest.raises(cli.StoreSetupError):
        cli.build_upstream("k" * 32, "mysql")


def test_store_is_opened_before_the_http_client(monkeypatch):
    built = []
    monkeypatch.setattr(cli, "FmpRestUpstream", lambda key: built.append(key))
    monkeypatch.setattr(cli, "MySqlDatabase", _CreateDenied)
    with pytest.raises(cli.StoreSetupError):
        cli.build_upstream("k" * 32, "mysql")
    assert built == [], "no client is created when the store cannot be opened"


@pytest.mark.parametrize("spec", ["sqlite:", "sqlite:   ", "bogus", ""])
def test_invalid_store_specs_are_rejected(spec):
    assert cli.valid_store_spec(spec) is False


@pytest.mark.parametrize("spec", ["auto", "mysql", "none", "sqlite:data/store.db"])
def test_valid_store_specs_are_accepted(spec):
    assert cli.valid_store_spec(spec) is True


def test_unsafe_bind_is_refused_before_the_store_is_opened(monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "load_fmp_key", lambda: "k" * 32)
    monkeypatch.setattr(cli, "build_upstream", lambda *a: opened.append(a))
    monkeypatch.delenv("FMP_CACHED_MCP_TOKEN", raising=False)
    assert (
        cli.main(["--transport", "http", "--host", "0.0.0.0", "--store", "none"]) == 2
    )
    assert opened == []
