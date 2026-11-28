"""The real-path replay probe runs end to end on synthetic data (#1341 T01)."""

# pylint: disable=protected-access

import json
from pathlib import Path

import pytest
from openbb_agents.hermes_integration import replay_probe


def test_duplicate_delivery_has_one_outcome_per_operation(capsys):
    """Duplicate delivery has one outcome per operation."""
    assert (
        replay_probe.main(["--scenario", "duplicate-delivery", "--format", "json"]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["run_bound"] is True
    by_name = {op["operation"]: op for op in report["operations"]}
    assert set(by_name) == {
        "story_run_create",
        "story_job_submit",
        "story_artifact_table",
        "story_paper_prepare",
    }
    for op in by_name.values():
        assert (op["deliveries"], op["outcomes"]) == (2, 1), op
    assert by_name["story_job_submit"]["replay_of_set"] is True
    # The report carries no filesystem path.
    assert "gh1341-probe" not in json.dumps(report)


def test_probe_refuses_a_store_outside_its_directory(tmp_path, monkeypatch):
    """Probe refuses a store outside its directory."""
    root = (tmp_path / "probe").resolve()
    root.mkdir()
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", str(tmp_path / "elsewhere.sqlite"))
    monkeypatch.setenv("OPENBB_STORY_ARTIFACT_ROOT", str(root / "a"))
    monkeypatch.setenv("OPENBB_STORY_PAPER_ROOT", str(root / "p"))
    with pytest.raises(replay_probe.ProbeRefused):
        replay_probe._ensure_contained(root)


def test_probe_restores_the_environment(monkeypatch):
    """Probe restores the environment."""
    monkeypatch.setenv("OPENBB_STORY_RUN_STORE", "sentinel-store")
    with replay_probe._sandbox() as root:
        assert Path(replay_probe.os.environ["OPENBB_STORY_RUN_STORE"]).parent == root
    assert replay_probe.os.environ["OPENBB_STORY_RUN_STORE"] == "sentinel-store"


def test_unknown_scenario_is_a_usage_error():
    """Unknown scenario is a usage error."""
    assert replay_probe.main(["--scenario", "nope"]) == 3
