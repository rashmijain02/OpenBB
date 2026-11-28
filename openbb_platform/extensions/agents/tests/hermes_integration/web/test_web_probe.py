"""``web_probe --scenario security`` real-path CLI (#1342 T01)."""

from __future__ import annotations

import json

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
