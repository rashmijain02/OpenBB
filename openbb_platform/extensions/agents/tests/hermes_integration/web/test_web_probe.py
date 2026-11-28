"""``web_probe --scenario security`` real-path CLI (#1342 T01)."""

from __future__ import annotations

import json

import pytest
from openbb_agents.hermes_integration.web import web_probe


def test_web_probe_security_reports_every_rejection(capsys):
    assert web_probe.main(["--scenario", "security", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scenario"] == "security"
    assert report["ok"] is True
    assert report["approvals_written"] == 0
    assert report["rejected_reached_handler"] == 0
    assert report["cors_headers_seen"] == 0
    assert report["bind"] == "127.0.0.1"
    codes = {case["name"]: case["code"] for case in report["cases"]}
    for name, code in {
        "foreign_host": "host_rejected",
        "cross_site_origin": "origin_rejected",
        "referer": "origin_rejected",
        "same_site_fetch": "fetch_metadata_rejected",
        "form_post": "unsupported_media_type",
        "text_plain_post": "unsupported_media_type",
        "no_token": "token_mismatch",
        "wrong_token": "token_mismatch",
        "unprovisioned": "token_unprovisioned",
        "preflight": "method_not_allowed",
        "oversize": "body_too_large",
    }.items():
        assert codes[name] == code, name
    assert all(case["ok"] for case in report["cases"])


def test_web_probe_text_format_and_bad_scenario(capsys):
    assert web_probe.main(["--scenario", "security", "--format", "text"]) == 0
    out = capsys.readouterr().out
    assert "approvals_written: 0" in out
    assert "ok: True" in out
    assert web_probe.main(["--scenario", "nope"]) == 3


def test_web_probe_journey_real_path(capsys):
    """T02 real path: one approval row, one run, one job, outcome succeeded."""
    pytest.importorskip("openbb_portfolio_intel")
    assert web_probe.main(["--scenario", "journey", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["plan"] == "pending->started"
    assert report["approve_results"] == ["200:approved", "200:already_approved"]
    assert report["duplicates"] == {"approve": "2->1", "start": "2->1"}
    assert (report["runs"], report["jobs"], report["job_status"]) == (
        1,
        1,
        ["succeeded"],
    )
    assert report["outcome"] == "succeeded" and report["artifacts_sha_ok"]
    assert (report["provider_calls"], report["egress_refused"]) == (0, 0)


def test_web_probe_reconnect(capsys):
    """T03 real path: the sidecar restarts mid-run; the new one reads the same run."""
    pytest.importorskip("openbb_portfolio_intel")
    assert web_probe.main(["--scenario", "reconnect", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["restarts"] == 1 and len(report["run_ids"]) == 1
    assert report["outcome_before"] == "waiting_job"
    assert report["outcome_after"] == "succeeded"
    assert report["restart_replay_of"] is True
    assert (report["runs"], report["jobs"], report["job_status"]) == (
        1,
        1,
        ["succeeded"],
    )
    assert report["agent_modules"] == [] and report["provider_calls"] == 0


def test_web_journey_live_refuses_without_owner_config(capsys, tmp_path):
    """``--stack live`` runs nothing; without owner config it refuses (exit 2)."""
    from openbb_agents.hermes_integration.web import web_journey

    assert web_journey.main(["--stack", "live"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("refused:") and "L6b" in out
    missing = tmp_path / "absent.json"
    assert web_journey.main(["--stack", "live", "--owner-config", str(missing)]) == 2
    capsys.readouterr()
    config = tmp_path / "owner.json"
    config.write_text("{}", encoding="utf-8")
    assert web_journey.main(["--stack", "live", "--owner-config", str(config)]) == 0
    assert "nothing is run here" in capsys.readouterr().out
    assert web_journey.main(["--stack", "nope"]) == 3


def test_web_journey_local_without_webui_is_unavailable_not_pass(
    capsys, monkeypatch
):
    """A missing prerequisite exits 4 with a reason, never 0."""
    from openbb_agents.hermes_integration.web import web_journey

    monkeypatch.delenv("HFP_WEBUI_DIR", raising=False)
    assert web_journey.main(["--stack", "local"]) == 4
    assert json.loads(capsys.readouterr().out)["unavailable"] == "HFP_WEBUI_DIR unset"
