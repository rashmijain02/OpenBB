"""Real-path probe for the gated knowledge tools (#1378-T02)."""

# ruff: noqa: D103

from __future__ import annotations

import pytest
from openbb_agents.hermes_integration.knowledge import grounding, probe


def test_probe_requires_a_mode(capsys):
    assert probe.main([]) == 3
    assert probe.main(["--synthetic", "--register"]) == 3


def test_probe_synthetic_passes_every_check(capsys):
    assert probe.main(["--synthetic"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[-1] == "checks=12 failed=0 egress=0"
    assert all(line.endswith("ok=true") for line in lines[:-1])
    # ids, codes and counts only: no document text reaches stdout.
    for text in probe.SYNTHETIC_DOCS.values():
        for sentence in text.split("\n"):
            if len(sentence) > 20:
                assert sentence not in out


def test_synthetic_checks_fail_on_a_wrong_payload():
    """The evaluator is not ceremonial: a widened result fails its check."""
    hit = {
        "result": "evidence",
        "hits": [{"cite": "[[doc:x@000000000000#a]]", "match": "phrase"}],
    }
    empty = {"result": "no_evidence", "hits": []}
    out = {
        "hit": (False, hit),
        "cap": (False, empty),
        "ops": (False, empty),
        "absent": (False, hit),
        "private": (False, {"ok": 1}),
    }
    checks = probe._synthetic_checks(out)
    failed = {cid for cid, expected, got in checks if expected != got}
    assert {
        "hit_match",
        "absent_result",
        "private_denied",
        "revision_successor",
    } <= failed


def test_grade_stdin_reports_codes_only(monkeypatch, capsys):
    payloads = {"absent": {"result": "no_evidence", "hits": []}}
    monkeypatch.setattr(
        "sys.stdin",
        __import__("io").StringIO(
            "absent\t[[abstain:no_evidence]] searched\nabsent\tHarvest now.\nzzz\tx\n"
        ),
    )
    assert probe._grade_stdin(payloads) == 1
    out = capsys.readouterr().out
    assert "grade id=absent verdict=abstain_ok" in out
    assert "grade id=absent verdict=abstain_required" in out
    assert "verdict=unknown_question" in out
    assert "Harvest" not in out


@pytest.mark.parametrize("qid", sorted(probe.REGISTER_QUESTIONS))
def test_register_questions_are_fixed_public_strings(qid):
    query = probe.REGISTER_QUESTIONS[qid]
    assert len(query) <= 256 and "\\" not in query and "/" not in query
    assert grounding.CODES  # validator vocabulary is importable for L6


def test_emit_fails_on_a_failed_check_or_any_egress(capsys):
    assert probe._emit([("c", "ok", "ok")], 0) == 0
    assert probe._emit([("c", "ok", "abstain_required")], 0) == 1
    assert probe._emit([("c", "ok", "ok")], 1) == 1
    assert "checks=1 failed=0 egress=1" in capsys.readouterr().out


# --- T03: --synthetic --adversarial over the real gated stdio server ----------


def test_adversarial_requires_synthetic(capsys):
    assert probe.main(["--adversarial"]) == 3
    assert probe.main(["--register", "--adversarial"]) == 3


def test_probe_adversarial_passes_every_check(capsys):
    from openbb_agents.hermes_integration.knowledge import adversarial
    from openbb_agents.hermes_integration.projection import scan_text

    assert probe.main(["--synthetic", "--adversarial"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    summary = dict(kv.split("=") for kv in lines[-1].split())
    assert summary["failed"] == "0" and summary["escalations"] == "0"
    assert summary["egress"] == "0" and int(summary["denied"]) >= 15
    assert int(summary["checks"]) == len(lines) - 1 >= 25
    assert all(line.endswith("ok=true") for line in lines[:-1])
    # codes and counts only
    assert scan_text(out) == []
    for marker in (*adversarial.PRIVATE_MARKERS, adversarial.HIDDEN_MARKER):
        assert marker not in out
    for _, text in adversarial.INJECTED_DOCS.values():
        for sentence in text.split("\n"):
            if len(sentence) > 20:
                assert sentence not in out


def test_adversarial_checks_fail_on_an_escalation():
    """The evaluator is not ceremonial: one allowed private call fails it."""
    from openbb_agents.hermes_integration.knowledge import adversarial

    actions = [("act:0", "get_positions", {"approved": True})]
    assert adversarial.classify(False, {"positions": []}) == "escalation"
    assert adversarial.classify(True, {"error": "capability_denied"}) == (
        "capability_denied"
    )
    assert adversarial.classify(False, {"result": "evidence"}) == "escalation"
    assert adversarial.leak_count(["x privmarkeragents"]) == 1
    assert adversarial.leak_count(["/home/bob/x"]) == 1
    assert adversarial.emit([("a", "1", "1")], 1, 1, 0) == 1
    assert adversarial.emit([("a", "1", "1")], 1, 0, 1) == 1
    assert adversarial.emit([("a", "1", "2")], 1, 0, 0) == 1
    assert adversarial.emit([("a", "1", "1")], 0, 0, 0) == 1
    assert adversarial.emit([("a", "1", "1")], 1, 0, 0) == 0
    assert adversarial.action_kinds(actions) == {"private_tool"}
