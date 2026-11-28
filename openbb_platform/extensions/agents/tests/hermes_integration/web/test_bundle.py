"""``openbb-hfp`` extension bundle and its tree-hash pin (#1342 T01)."""

from __future__ import annotations

import json

import pytest
from openbb_agents.hermes_integration import skills_admission
from openbb_agents.hermes_integration.web import bundle


def test_render_bundle_manifest_contract(tmp_path):
    out = tmp_path / "bundle"
    sha = bundle.render_bundle(out, port=8799)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    (ext,) = manifest["extensions"]
    assert ext["id"] == "openbb-hfp"
    assert ext["permissions"]["network_external"] is False
    assert ext["sidecar"] == {
        "type": "loopback",
        "origin": "http://127.0.0.1:8799",
        "health_path": "/health",
        "proxy_auth": "token-v1",
    }
    for asset in ext["scripts"] + ext["stylesheets"]:
        assert (out / asset).is_file(), asset
    assert sha == skills_admission.tree_sha256(out)
    assert len(sha) == 64


def test_tree_hash_is_stable_and_port_sensitive(tmp_path):
    a = bundle.render_bundle(tmp_path / "a", port=8799)
    b = bundle.render_bundle(tmp_path / "b", port=8799)
    c = bundle.render_bundle(tmp_path / "c", port=8800)
    assert a == b != c


@pytest.mark.parametrize("port", [0, 80, 1023, 65536, -1])
def test_render_rejects_bad_port(tmp_path, port):
    with pytest.raises(ValueError, match="port"):
        bundle.render_bundle(tmp_path / "x", port=port)


def test_render_refuses_git_tree_and_non_empty_dir(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="git"):
        bundle.render_bundle(repo / "nested" / "bundle", port=8799)
    full = tmp_path / "full"
    full.mkdir()
    (full / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        bundle.render_bundle(full, port=8799)
    assert bundle.inside_git_tree(repo / "nested")
    assert not bundle.inside_git_tree(tmp_path / "elsewhere")


def test_cli_prints_tree_sha(tmp_path, capsys):
    out = tmp_path / "bundle"
    assert bundle.main(["--out", str(out), "--port", "8799"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["tree_sha256"] == skills_admission.tree_sha256(out)
    assert printed["extension_id"] == "openbb-hfp"
    assert bundle.main(["--out", str(out), "--port", "8799"]) == 2  # non-empty now
