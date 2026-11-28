"""Versioned paused cron wrapper rendering (#1344-T03)."""

from __future__ import annotations

import ast
import json
from datetime import date

import pytest
from portfolio_utils.fmp_sync import locking, render

MAP = {
    "schema_version": 1,
    "source_root": "SRC",
    "source_sha": "a" * 40,
    "interpreter": "VENV",
    "target": "obb_disposable_abcdef12",
    "target_class": "disposable",
    "profile_path": "profile.json",
    "limits": {
        "per_run": 5,
        "per_minute": 5,
        "per_day": 50,
        "bytes_per_day": 1000000,
    },
    "hermes_timezone": "America/Los_Angeles",
    "sync_python": "3.12",
}


@pytest.fixture
def rig(tmp_path):
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(
        f"home = {tmp_path / 'base'}\nversion_info = 3.12.15\n", encoding="utf-8"
    )
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "python.exe").write_text("x", encoding="utf-8")
    (venv / "Scripts").mkdir()
    (venv / "Scripts" / "python.exe").write_text("x", encoding="utf-8")
    data = dict(MAP, source_root=str(tmp_path / "src"), interpreter=str(venv))
    map_path = tmp_path / "map.json"

    def write(**over):
        map_path.write_text(json.dumps({**data, **over}), encoding="utf-8")
        return map_path

    write()
    return {
        "map": map_path,
        "write": write,
        "home": tmp_path / "hermes",
        "tmp": tmp_path,
    }


def _plan(rig):
    return render.plan(rig["map"], rig["home"])


def test_render_plan_is_default_and_writes_nothing(rig, capsys):
    result = _plan(rig)
    assert result.status == "NEW"
    assert not rig["home"].exists()
    argv = ["plan", "--map", str(rig["map"]), "--hermes-home", str(rig["home"])]
    assert render.main(argv) == 0
    assert not rig["home"].exists()
    assert "hermes cron create" in capsys.readouterr().out


def test_render_idempotent_unchanged(rig):
    first = _plan(rig)
    render.apply_files(rig["map"], rig["home"])
    again = _plan(rig)
    assert again.status == "UNCHANGED" and again.content_sha256 == first.content_sha256


def test_drift_blocks(rig):
    render.apply_files(rig["map"], rig["home"])
    script = rig["home"] / "scripts" / render.WRAPPER_NAME
    script.write_text(script.read_text("utf-8") + "# edited\n", encoding="utf-8")
    assert _plan(rig).status == "DRIFT"
    with pytest.raises(render.RenderError):
        render.apply_files(rig["map"], rig["home"])
    assert "# edited" in script.read_text("utf-8")  # never overwritten


def test_wrapper_has_no_params_or_paths_from_cron(rig):
    text = render.render_wrapper(rig["map"])
    tree = ast.parse(text)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "argv" not in attrs and "parse_args" not in attrs
    assert "getenv" not in attrs
    del names
    consts = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not any(c.strip().lower().startswith("hermes") for c in consts)
    assert "register" not in text.lower()


def test_registration_text_is_paused_local(rig):
    cmd = _plan(rig).command
    assert "UNVERIFIED" in cmd and "OPS-ATTEST" in cmd
    for flag in ("no-agent", "paused", "deliver-local", "schedule", "script"):
        assert f"<UNVERIFIED:{flag}>" in cmd  # placeholders, never real flags
    assert "paused" in cmd.lower()
    assert "30 15 * * 1-5" in cmd
    assert "--register" not in cmd
    assert "HERMES_TIMEZONE" in cmd and "America/Los_Angeles" in cmd


def test_requires_hermes_timezone_los_angeles(rig):
    rig["write"](hermes_timezone="UTC")
    with pytest.raises(render.RenderError, match="HERMES_TIMEZONE"):
        _plan(rig)
    rig["write"](hermes_timezone=None)
    with pytest.raises(render.RenderError, match="HERMES_TIMEZONE"):
        _plan(rig)


def test_schedule_1530_pt_is_1830_et_through_dst():
    fires = render.fire_instants("30 15 * * 1-5", date(2027, 3, 1), date(2027, 3, 31))
    fires += render.fire_instants(
        "30 15 * * 1-5", date(2027, 11, 1), date(2027, 11, 30)
    )
    assert fires
    assert render.dst_check("30 15 * * 1-5") == []
    for eastern in render.to_new_york(fires):
        assert (eastern.hour, eastern.minute) == (18, 30) and eastern.weekday() < 5
    assert render.dst_check("30 14 * * 1-5") != []  # a wrong schedule is flagged


def test_render_refuses_register_and_non_plan_modes(rig):
    base = ["--map", str(rig["map"]), "--hermes-home", str(rig["home"])]
    for argv in (
        ["plan", "--register", *base],
        ["register", *base],
        ["create", *base],
        ["plan", "--mode", "register", *base],
    ):
        with pytest.raises(SystemExit) as exc:
            render.main(argv)
        assert exc.value.code == 2
    assert not rig["home"].exists()
    assert not list(rig["tmp"].rglob("jobs.json"))


def test_state_root_must_match_manual_default(rig):
    rig["write"](state_root=str(rig["tmp"] / "elsewhere"))
    with pytest.raises(render.RenderError, match="state root"):
        _plan(rig)
    rig["write"](state_root=str(locking.default_state_root()))
    _plan(rig)


def test_child_python_is_the_venv_python(rig):
    """The wrapper runs the venv's own python (never the pyvenv.cfg base)."""
    result = _plan(rig)
    venv = rig["tmp"] / "venv"
    assert result.child_python == str(venv / "Scripts" / "python.exe")
    assert result.sync_python == "3.12"
    text = render.render_wrapper(rig["map"])
    assert json.dumps(result.child_python) in text
    assert "base" not in result.child_python
    (venv / "Scripts" / "python.exe").unlink()
    with pytest.raises(render.RenderError, match="venv python"):
        _plan(rig)
