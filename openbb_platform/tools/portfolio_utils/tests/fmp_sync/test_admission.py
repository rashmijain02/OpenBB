"""Target and universe admission before any DB/FMP access (#1344-T01).

Every collaborator that would touch the host (interpreter, module origins, git,
the warmer import, the MySQL session) is injected; nothing here connects.
"""

from __future__ import annotations

import json
import logging
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from openbb_agents.hermes_integration.models import FailedLayer
from openbb_agents.hermes_integration.provenance import GitFacts
from portfolio_utils.fmp_sync import admission
from portfolio_utils.fmp_sync.admission import admit, load_map, manifest_digest

from .conftest import DISPOSABLE_DB, FIXTURES_1338

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 40
ATTEST = "b" * 64


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)

    def fetchone(self):
        return (self.conn.session_db,)

    def close(self):
        pass


class FakeConn:
    """Stands in for the warmer's own ``_connect`` path; records every statement."""

    def __init__(self, session_db):
        self.session_db = session_db
        self.sql: list[str] = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def world(tmp_path, synthetic_settings, monkeypatch):
    """A synthetic, fully admissible deployment; overrides make it inadmissible."""
    version = platform.python_version()
    minor = ".".join(version.split(".")[:2])
    venv = tmp_path / "venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"home = x\nversion = {version}\n", encoding="utf-8"
    )
    src = tmp_path / "src"
    src.mkdir()

    def make(
        *,
        target=DISPOSABLE_DB,
        target_class="disposable",
        profile_db=None,
        settings_db=None,
        symbols=("AAA", "BBB"),
        benchmarks=("SPY",),
        digest=None,
        symbol_limit=10,
        expires=NOW + timedelta(days=7),
        accepted=NOW - timedelta(days=1),
        ops_attest_ref=None,
        manifest=True,
        **extra,
    ):
        profile = yaml.safe_load(
            (FIXTURES_1338 / "profiles" / "synthetic-ok.yaml").read_text(
                encoding="utf-8"
            )
        )
        profile["database"]["expected"] = profile_db or target
        profile["python"] = {
            "requires": ">=3.10,<3.15",
            "supported": minor,
            "venv_env": "X",
        }
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
        settings = synthetic_settings(settings_db or target)
        data = {
            "schema_version": 1,
            "source_root": str(src),
            "source_sha": SHA,
            "interpreter": str(venv),
            "target": target,
            "target_class": target_class,
            "profile_path": str(profile_path),
            "settings_path": str(settings),
            "ops_attest_ref": ops_attest_ref,
        }
        if manifest:
            m = {
                "schema_version": 1,
                "manifest_id": "synthetic-1",
                "source": "test",
                "accepted_at": accepted.isoformat(),
                "expires_at": expires.isoformat(),
                "symbol_limit": symbol_limit,
                "symbols": list(symbols),
                "benchmarks": list(benchmarks),
                "sha256": digest or manifest_digest(symbols, benchmarks),
            }
            mpath = tmp_path / "manifest.json"
            mpath.write_text(json.dumps(m), encoding="utf-8")
            data["manifest_path"] = str(mpath)
        data.update(extra)
        map_path = tmp_path / "map.json"
        map_path.write_text(json.dumps(data), encoding="utf-8")
        return load_map(map_path)

    kwargs = {
        "executable": str(venv / "Scripts" / "python.exe"),
        "module_origin_fn": lambda name: src / name / "__init__.py",
        "git_facts_fn": lambda d: GitFacts(
            sha=SHA, remote="github.com/x/y", dirty=False
        ),
        "import_warmer_fn": lambda: None,
        "dotenv_path": tmp_path / "absent.env",
        "now": NOW,
    }
    return make, kwargs


def _admit(world, mode="dry_run", requested_class="disposable", **overrides):
    make, kwargs = world
    map_kwargs = overrides.pop("map", {})
    kwargs = {**kwargs, **overrides}
    return admit(
        make(**map_kwargs), mode=mode, requested_class=requested_class, **kwargs
    )


def test_admits_synthetic_disposable(world):
    result = _admit(world)
    assert result.admitted, result
    assert result.code == "ADMITTED" and result.exit_code == 0
    assert result.symbols == ("AAA", "BBB", "SPY")
    assert result.db_category == "expected"
    assert result.manifest_id == "synthetic-1"
    assert result.counts == {"requested": 3, "skipped": 0, "admitted": 3}


@pytest.mark.parametrize(
    ("name", "finding"),
    [
        ("openbb_fmp_cache_test", "TARGET_PROTECTED_IN_DISPOSABLE"),
        ("OPENBB_FMP_CACHE_TEST", "TARGET_PROTECTED_IN_DISPOSABLE"),
        ("openbb_fmp_cache", "TARGET_OLD_COPY"),
    ],
)
def test_blocks_live_and_old_names_in_disposable_mode(world, name, finding):
    result = _admit(world, map={"target": name})
    assert not result.admitted
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert result.code == "BLOCKED_DATABASE" and result.exit_code == 40
    assert finding in result.findings


def test_blocks_non_disposable_pattern(world):
    result = _admit(world, map={"target": "scratch_db"})
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert "TARGET_NOT_DISPOSABLE" in result.findings


def test_old_copy_blocked_even_as_attested_production(world):
    result = _admit(
        world,
        requested_class="production",
        map={
            "target": "openbb_fmp_cache",
            "target_class": "production",
            "ops_attest_ref": ATTEST,
        },
    )
    assert result.code == "BLOCKED_DATABASE"
    assert "TARGET_OLD_COPY" in result.findings


@pytest.mark.parametrize("value", ["true", "TRUE"])
def test_blocks_test_mode_env(world, value):
    result = _admit(world, env={"FMP_CACHE_TEST_MODE": value})
    assert result.failed_layer == FailedLayer.CONFIG.value
    assert "TEST_MODE_ENV" in result.findings


def test_blocks_auto_create_db(world):
    result = _admit(world, env={"FMP_CACHE_AUTO_CREATE_DB": "true"})
    assert result.failed_layer == FailedLayer.CONFIG.value
    assert "AUTO_CREATE_DB_ENABLED" in result.findings


def test_blocks_dotenv_drift(world):
    """Importing the warmer must not change DB env (its load_dotenv(override=True))."""
    env = {"DB_NAME": DISPOSABLE_DB}

    def _import_that_overrides():
        env["DB_NAME"] = "openbb_fmp_cache_test"

    result = _admit(world, env=env, import_warmer_fn=_import_that_overrides)
    assert result.failed_layer == FailedLayer.CONFIG.value
    assert "DOTENV_DRIFT" in result.findings
    assert "openbb_fmp_cache_test" not in json.dumps(result.findings)


def test_blocks_dotenv_file_that_would_override(world, tmp_path):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text("DB_NAME=openbb_fmp_cache_test\n", encoding="utf-8")
    imported: list[bool] = []
    result = _admit(
        world,
        env={"DB_NAME": DISPOSABLE_DB},
        dotenv_path=dotenv,
        import_warmer_fn=lambda: imported.append(True),
    )
    assert "DOTENV_DRIFT" in result.findings
    assert imported == [], "a drifting .env must block before the warmer is imported"


def test_warmer_autocreate_setdefault_is_not_drift(world):
    env: dict[str, str] = {}
    result = _admit(
        world,
        env=env,
        import_warmer_fn=lambda: env.setdefault("FMP_CACHE_AUTO_CREATE_DB", "false"),
    )
    assert result.admitted, result


def test_blocks_profile_mismatch(world):
    result = _admit(world, map={"profile_db": "obb_disposable_ffffffff"})
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert "PROFILE_TARGET_MISMATCH" in result.findings


def test_blocks_settings_resolving_elsewhere(world):
    """Default-resolving helpers would hit another DB: the #1338 category must be expected."""
    result = _admit(world, map={"settings_db": "openbb_fmp_cache"})
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert result.db_category == "legacy_default"
    assert "RESOLVED_DATABASE_LEGACY_DEFAULT" in result.findings


def test_production_requires_attest_ref(world):
    prod = {"target": "openbb_fmp_cache_test", "target_class": "production"}
    no_flag = _admit(world, map={**prod, "ops_attest_ref": ATTEST})
    assert no_flag.code == "BLOCKED_POLICY" and no_flag.exit_code == 40
    assert "TARGET_CLASS_MISMATCH" in no_flag.findings

    no_ref = _admit(world, requested_class="production", map=prod)
    assert no_ref.code == "BLOCKED_POLICY"
    assert "OPS_ATTEST_MISSING" in no_ref.findings

    ok = _admit(
        world, requested_class="production", map={**prod, "ops_attest_ref": ATTEST}
    )
    assert ok.admitted, ok
    assert ok.target_class == "production"


def test_select_database_mismatch_blocks_before_write(world):
    conn = FakeConn("openbb_fmp_cache_test")
    result = _admit(world, mode="execute", connect_fn=lambda: conn)
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert "SESSION_DATABASE_MISMATCH" in result.findings
    assert conn.sql == ["SELECT DATABASE()"], "only the identity probe may run"
    assert conn.closed

    good = FakeConn(DISPOSABLE_DB.upper())
    assert _admit(world, mode="execute", connect_fn=lambda: good).admitted
    assert good.sql == ["SELECT DATABASE()"]


def test_session_probe_failure_is_generic(world):
    def _raise():
        raise RuntimeError("password=SYNTHETIC-PASSWORD-SENTINEL host=10.0.0.1")

    result = _admit(world, mode="execute", connect_fn=_raise)
    assert "SESSION_CHECK_FAILED" in result.findings
    assert "SENTINEL" not in repr(result)


def test_dry_run_never_probes_session(world):
    def _never():
        raise AssertionError("dry-run must not connect")

    assert _admit(world, connect_fn=_never).admitted


def test_blocks_wrong_interpreter(world, tmp_path):
    result = _admit(world, executable=str(tmp_path / "other" / "python.exe"))
    assert result.failed_layer == FailedLayer.PROCESS.value
    assert "INTERPRETER_NOT_PINNED" in result.findings


def test_blocks_abi_mismatch(world, tmp_path):
    (tmp_path / "venv" / "pyvenv.cfg").write_text("version = 3.9.1\n", encoding="utf-8")
    result = _admit(world)
    assert result.failed_layer == FailedLayer.ABI.value


@pytest.mark.parametrize(
    ("override", "finding"),
    [
        (
            {
                "git_facts_fn": lambda d: GitFacts(
                    sha="c" * 40, remote=None, dirty=False
                )
            },
            "SOURCE_SHA_MISMATCH",
        ),
        (
            {"git_facts_fn": lambda d: GitFacts(sha=SHA, remote=None, dirty=True)},
            "SOURCE_DIRTY",
        ),
        (
            {"module_origin_fn": lambda name: Path("/elsewhere") / name},
            "MODULE_OUTSIDE_SOURCE_ROOT",
        ),
    ],
)
def test_blocks_module_origin(world, override, finding):
    result = _admit(world, **override)
    assert result.failed_layer == FailedLayer.MODULE_ORIGIN.value
    assert any(f.startswith(finding) for f in result.findings)


def test_hermes_integration_unavailable_is_module_origin(world, monkeypatch):
    def _missing():
        raise ImportError("no openbb_agents")

    monkeypatch.setattr(admission, "_load_hermes", _missing)
    result = _admit(world)
    assert result.code == "BLOCKED_MODULE_ORIGIN"
    assert result.failed_layer == "module_origin"


# ---------------------------------------------------------------- universe


def test_blocks_expired_manifest(world):
    result = _admit(world, map={"expires": NOW - timedelta(seconds=1)})
    assert result.code == "BLOCKED_UNIVERSE" and "MANIFEST_EXPIRED" in result.findings


def test_blocks_digest_mismatch(world):
    result = _admit(world, map={"digest": "0" * 64})
    assert "MANIFEST_DIGEST_MISMATCH" in result.findings


def test_digest_covers_benchmarks(world):
    result = _admit(world, map={"digest": manifest_digest(("AAA", "BBB"), ())})
    assert "MANIFEST_DIGEST_MISMATCH" in result.findings


def test_blocks_over_symbol_limit(world):
    result = _admit(world, map={"symbol_limit": 2})
    assert "OVER_SYMBOL_LIMIT" in result.findings


def test_blocks_over_global_cap(world, monkeypatch):
    monkeypatch.setattr(admission, "GLOBAL_SYMBOL_CAP", 2)
    result = _admit(world)
    assert "OVER_GLOBAL_CAP" in result.findings


@pytest.mark.parametrize(
    ("symbol", "finding"),
    [
        ("09261F598", "CUSIP_SYMBOL"),
        ("aapl", "INVALID_SYMBOL"),
        ("TOO_LONG_SYMBOL", "INVALID_SYMBOL"),
    ],
)
def test_blocks_bad_symbols(world, symbol, finding):
    result = _admit(world, map={"symbols": ("AAA", symbol)})
    assert result.code == "BLOCKED_UNIVERSE"
    assert finding in result.findings


def test_skip_symbols_applied_and_counted(world):
    result = _admit(world, map={"symbols": ("AAA", "NSAV"), "benchmarks": ()})
    assert result.admitted
    assert result.symbols == ("AAA",)
    assert result.counts == {"requested": 2, "skipped": 1, "admitted": 1}


def test_blocks_empty_universe_loudly(world, caplog):
    with caplog.at_level(logging.WARNING, logger="portfolio_utils.fmp_sync.admission"):
        result = _admit(world, map={"symbols": ("NSAV",), "benchmarks": ()})
    assert result.code == "BLOCKED_EMPTY_UNIVERSE" and result.exit_code == 40
    assert [r for r in caplog.records if "empty universe" in r.getMessage()]


def test_manifest_required_unless_legacy_selector(world):
    missing = _admit(world, map={"manifest": False})
    assert "MANIFEST_MISSING" in missing.findings
    legacy = _admit(world, map={"manifest": False, "legacy_selector": True})
    assert legacy.admitted and legacy.symbols is None
    assert "LEGACY_SELECTOR_OPT_IN" in legacy.findings


def test_map_rejects_unknown_fields(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"schema_version": 1, "bogus": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_map(path)


def test_sync_python_pin_is_separate_from_hermes_pin(world):
    """The sync process is checked against the map's own pin, not the Hermes profile pin."""
    minor = ".".join(platform.python_version().split(".")[:2])
    ok = _admit(world, map={"sync_python": minor})
    assert ok.admitted, ok
    wrong = "2.7"
    result = _admit(world, map={"sync_python": wrong})
    assert result.failed_layer == FailedLayer.ABI.value
    assert "SYNC_PYTHON_MISMATCH" in result.findings


def test_sync_python_replaces_profile_python_check(world):
    """A profile pin the sync interpreter does not satisfy no longer blocks it."""
    make, kwargs = world
    minor = ".".join(platform.python_version().split(".")[:2])
    dmap = make(sync_python=minor)
    profile = yaml.safe_load(Path(dmap.profile_path).read_text(encoding="utf-8"))
    profile["python"]["supported"] = "2.7"  # Hermes runtime pin differs
    Path(dmap.profile_path).write_text(yaml.safe_dump(profile), encoding="utf-8")
    assert admit(dmap, mode="dry_run", **kwargs).admitted
    legacy = make()
    profile["python"]["supported"] = "2.7"
    Path(legacy.profile_path).write_text(yaml.safe_dump(profile), encoding="utf-8")
    blocked = admit(legacy, mode="dry_run", **kwargs)
    assert "PYTHON_PIN_MISMATCH" in blocked.findings


# ---------------------------------------------- .env supplies keys vs overrides


def _dotenv_loader(env, dotenv):
    """Mimic the warmer's ``load_dotenv(override=True)`` on the injected env."""

    def _load():
        from dotenv import dotenv_values  # pylint: disable=import-outside-toplevel

        env.update({k: v or "" for k, v in dotenv_values(dotenv).items()})

    return _load


def _no_settings(tmp_path):
    return {"settings_path": str(tmp_path / "absent-settings.json")}


def test_dotenv_supplying_absent_keys_is_not_drift(world, tmp_path):
    """Stripped cron env + .env supplying DB_*/FMP_API_KEY: reaches the DB identity check."""
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text(
        f"DB_HOST=127.0.0.1\nDB_NAME={DISPOSABLE_DB}\nDB_USER=u\n"
        "DB_PASSWORD=SYNTHETIC-SENTINEL\nFMP_API_KEY=SYNTHETIC-KEY\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    conn = FakeConn(DISPOSABLE_DB)
    result = _admit(
        world,
        mode="execute",
        env=env,
        dotenv_path=dotenv,
        import_warmer_fn=_dotenv_loader(env, dotenv),
        connect_fn=lambda: conn,
        map=_no_settings(tmp_path),
    )
    assert result.admitted, result
    assert conn.sql == ["SELECT DATABASE()"]
    assert "SENTINEL" not in repr(result)


def test_dotenv_overriding_present_key_is_drift(world, tmp_path):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text("DB_NAME=openbb_fmp_cache_test\n", encoding="utf-8")
    env = {"DB_NAME": DISPOSABLE_DB}
    result = _admit(
        world,
        env=env,
        dotenv_path=dotenv,
        import_warmer_fn=_dotenv_loader(env, dotenv),
    )
    assert "DOTENV_DRIFT" in result.findings


def test_dotenv_equal_to_present_value_is_not_drift(world, tmp_path):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text(f"DB_NAME={DISPOSABLE_DB}\n", encoding="utf-8")
    env = {"DB_NAME": DISPOSABLE_DB}
    result = _admit(
        world,
        env=env,
        dotenv_path=dotenv,
        import_warmer_fn=_dotenv_loader(env, dotenv),
        map=_no_settings(tmp_path),
    )
    assert result.admitted, result


def test_dotenv_supplied_old_copy_is_blocked_by_target_check(world, tmp_path):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text("DB_HOST=127.0.0.1\nDB_NAME=openbb_fmp_cache\n", encoding="utf-8")
    env: dict[str, str] = {}
    result = _admit(
        world,
        env=env,
        dotenv_path=dotenv,
        import_warmer_fn=_dotenv_loader(env, dotenv),
        map=_no_settings(tmp_path),
    )
    assert "DOTENV_DRIFT" not in result.findings
    assert result.failed_layer == FailedLayer.DATABASE.value
    assert "RESOLVED_DATABASE_LEGACY_DEFAULT" in result.findings


@pytest.mark.parametrize(
    "line,finding",
    [
        ("FMP_CACHE_AUTO_CREATE_DB=true", "AUTO_CREATE_DB_ENABLED"),
        ("FMP_CACHE_TEST_MODE=true", "TEST_MODE_ENV"),
    ],
)
def test_dotenv_supplied_unsafe_flags_still_block(world, tmp_path, line, finding):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text(line + "\n", encoding="utf-8")
    env: dict[str, str] = {}
    result = _admit(
        world,
        env=env,
        dotenv_path=dotenv,
        import_warmer_fn=_dotenv_loader(env, dotenv),
    )
    assert finding in result.findings


def test_dotenv_unsafe_flag_blocks_before_the_warmer_import(world, tmp_path):
    dotenv = tmp_path / "warmer.env"
    dotenv.write_text("FMP_CACHE_AUTO_CREATE_DB=true\n", encoding="utf-8")
    imported: list[bool] = []
    result = _admit(
        world,
        env={},
        dotenv_path=dotenv,
        import_warmer_fn=lambda: imported.append(True),
    )
    assert "AUTO_CREATE_DB_ENABLED" in result.findings
    assert imported == []


def test_import_that_sets_unsafe_flag_blocks(world):
    env: dict[str, str] = {}
    result = _admit(
        world,
        env=env,
        import_warmer_fn=lambda: env.update({"FMP_CACHE_TEST_MODE": "true"}),
    )
    assert "TEST_MODE_ENV" in result.findings


def test_import_that_removes_a_present_key_is_drift(world):
    env = {"DB_NAME": DISPOSABLE_DB}
    result = _admit(world, env=env, import_warmer_fn=lambda: env.pop("DB_NAME"))
    assert "DOTENV_DRIFT" in result.findings
