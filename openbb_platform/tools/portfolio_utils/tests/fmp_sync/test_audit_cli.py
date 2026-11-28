"""``audit`` CLI: dry-run evaluation and read-only audit (#1345-T01).

The dry run goes through the real CLI and the real XNYS calendar with a socket
counter; the read-only audit uses the synthetic admission world plus the SQLite
stand-in (or a refused connection). Nothing reaches MySQL.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pymysql
import pytest
from portfolio_utils.fmp_sync import __main__ as cli
from portfolio_utils.fmp_sync import readiness, sessions

from .conftest import DISPOSABLE_DB
from .fixtures import sql_fixture as sf
from .test_admission import world  # noqa: F401  (fixture)
from .test_readiness import CLOSURES_2026_2027, FIXTURE

NOW_ISO = "2026-11-27T15:30:00-08:00"
NOW = datetime(2026, 11, 27, 15, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
SENTINEL = 987654


@pytest.fixture(name="sockets")
def _sockets(monkeypatch):
    made: list[int] = []
    real_init = socket.socket.__init__

    def counting_init(self, *args, **kwargs):
        made.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "__init__", counting_init)
    return made


def _map(tmp_path: Path, **extra) -> Path:
    data = {
        "schema_version": 1,
        "source_root": str(tmp_path / "src"),
        "source_sha": "0" * 40,
        "interpreter": str(tmp_path / "venv"),
        "target": DISPOSABLE_DB,
        "target_class": "disposable",
        "profile_path": str(tmp_path / "profile.yaml"),
        **extra,
    }
    path = tmp_path / "map-disposable.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_audit_dry_run_zero_sockets_unvalidated(tmp_path, sockets, capsys):
    code = cli.main(
        ["audit", "--dry-run", "--map", str(_map(tmp_path)), "--now", NOW_ISO]
    )
    line = json.loads(capsys.readouterr().out.strip())
    assert code == 0 and line["exit"] == 0 and line["outcome"] == "OK"
    assert line["target_session"] == "2026-11-27"
    assert line["data_status"] == "UNVALIDATED"
    assert "DRY_RUN_NO_DB" in line["findings"]
    assert line["states"]["NOT_EVALUATED"] >= 5
    assert sockets == []
    assert not (Path(os.environ["FMP_SYNC_STATE_ROOT"]) / "runs").exists()


def test_audit_naive_now_rejected(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(
            [
                "audit",
                "--dry-run",
                "--map",
                str(_map(tmp_path)),
                "--now",
                "2026-11-27T15:30",
            ]
        )


def test_audit_dry_run_dst_and_thanksgiving(tmp_path, capsys):
    for now, expected in (
        ("2026-11-26T15:30:00-08:00", "2026-11-25"),  # Thanksgiving
        ("2027-03-15T15:30:00-07:00", "2027-03-15"),  # after spring-forward
        ("2027-11-08T15:30:00-08:00", "2027-11-08"),  # after fall-back
        ("2027-01-01T15:30:00-08:00", "2026-12-31"),  # New Year (Friday)
    ):
        assert (
            cli.main(["audit", "--dry-run", "--map", str(_map(tmp_path)), "--now", now])
            == 0
        )
        assert json.loads(capsys.readouterr().out)["target_session"] == expected


def _read_only(world, conn_fn, **map_extra):  # noqa: F811
    make, admit_kwargs = world
    dmap = make(**map_extra)
    return readiness.run_audit(
        dmap,
        mode="read_only",
        now=NOW,
        calendar=sessions.SyntheticCalendar.from_json(FIXTURE),
        admit_kwargs=admit_kwargs,
        connect_fn=conn_fn,
    )


def test_audit_read_only_mysql_unavailable_exit_30(world):  # noqa: F811
    def refused():
        raise pymysql.err.OperationalError(2003, "synthetic")

    out = _read_only(world, refused)
    line = json.loads(out.to_line())
    assert (line["outcome"], line["exit"], line["data_status"]) == (
        "FAILED_INFRA",
        30,
        "UNKNOWN",
    )
    assert "MYSQL_UNAVAILABLE" in line["findings"]


def test_audit_read_only_validated_and_receipt(world):  # noqa: F811
    conn = sf.build(
        DISPOSABLE_DB,
        prices=[sf.row(s, NOW.date()) for s in ("AAA", "BBB", "SPY")],
        holidays=CLOSURES_2026_2027,
    )
    out = _read_only(world, lambda: conn)
    assert (out.outcome, out.exit_code, out.data_status) == ("OK", 0, "VALIDATED")
    assert conn.writes() == [] and conn.sql[0] == "SET SESSION TRANSACTION READ ONLY"
    run = Path(os.environ["FMP_SYNC_STATE_ROOT"]) / "runs" / f"{out.run_id}.json"
    assert json.loads(run.read_text("utf-8"))["data_status"] == "VALIDATED"
    lock_dir = Path(os.environ["FMP_SYNC_STATE_ROOT"]) / "locks"
    assert not lock_dir.exists() or not any(lock_dir.iterdir())


def test_private_counts_absent_from_stdout_status(world, monkeypatch):  # noqa: F811
    conn = sf.build(
        DISPOSABLE_DB,
        prices=[sf.row(s, NOW.date()) for s in ("AAA", "BBB", "SPY")],
        holidays=CLOSURES_2026_2027,
        private={"Portfolio_Positions": 3},
    )
    conn.db.execute("CREATE TABLE Account_Owner (id INTEGER)")
    conn.db.execute("CREATE TABLE ESPP_Plan (id INTEGER)")
    real_run = readiness.ReadOnlySession.run

    def sentinel_run(self, query_id, params=(), n_in=0):
        rows = real_run(self, query_id, params, n_in)
        return [{"c": SENTINEL}] if query_id.startswith("private_count:") else rows

    monkeypatch.setattr(readiness.ReadOnlySession, "run", sentinel_run)
    out = _read_only(world, lambda: conn, readiness={"private_counts": True})
    assert str(SENTINEL) not in out.to_line()
    run = Path(os.environ["FMP_SYNC_STATE_ROOT"]) / "runs" / f"{out.run_id}.json"
    payload = json.loads(run.read_text("utf-8"))
    assert payload["private_counts"]["Portfolio_Positions"] == SENTINEL
    assert str(SENTINEL) not in json.dumps(payload["checks"])


def test_audit_read_only_admission_block_is_policy(world):  # noqa: F811
    out = _read_only(
        world, lambda: pytest.fail("must not connect"), target_class="production"
    )
    assert out.exit_code == 40 and out.outcome.startswith("BLOCKED")


def test_audit_read_only_bad_readiness_policy_blocks(world):  # noqa: F811
    out = _read_only(
        world, lambda: pytest.fail("must not connect"), readiness={"bogus": 1}
    )
    assert (out.outcome, out.exit_code) == ("BLOCKED_CONFIG", 40)


def test_audit_dry_run_integrity_fundamentals_not_evaluated(tmp_path, sockets, capsys):
    code = cli.main(
        [
            "audit",
            "--dry-run",
            "--map",
            str(_map(tmp_path)),
            "--now",
            NOW_ISO,
            "--checks",
            "integrity,fundamentals",
        ]
    )
    line = json.loads(capsys.readouterr().out.strip())
    assert code == 0 and line["data_status"] == "UNVALIDATED"
    assert {"DRY_RUN_NO_DB", "SOURCE_NOT_ADMITTED"} <= set(line["findings"])
    assert line["states"]["NOT_EVALUATED"] >= 9
    assert sockets == []


def test_audit_unknown_checks_group_rejected(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["audit", "--dry-run", "--map", str(_map(tmp_path)), "--checks", "bogus"]
        )
    assert exc.value.code == 2
