"""Render the ``openbb-hfp`` WebUI extension bundle and print its tree pin (#1342).

Usage: ``python -m openbb_agents.hermes_integration.web.bundle --out DIR --port N``.
``DIR`` must be empty or absent and outside every git work tree; WebUI serves it via
``HERMES_WEBUI_EXTENSION_DIR`` with ``HERMES_WEBUI_EXTENSION_MANIFEST=manifest.json``.
The printed ``tree_sha256`` is the profile's ``web.extension_tree_sha256`` pin.
Exit 0 rendered, 2 refused, 3 usage.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from ..skills_admission import tree_sha256
from .security import EXTENSION_ID

ASSET_DIR = Path(__file__).resolve().parent / "extension"
ASSETS = ("hfp.js", "hfp.css")
MANIFEST = "manifest.json"


def inside_git_tree(path: Path) -> bool:
    """Return True when ``path`` or a parent holds ``.git`` (repo or worktree)."""
    current = Path(path).resolve()
    return any((c / ".git").exists() for c in (current, *current.parents))


def render_manifest(port: int) -> str:
    """Render the manifest with the sidecar origin bound to ``127.0.0.1:<port>``."""
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("port must be an integer in 1024-65535")
    data = json.loads((ASSET_DIR / "manifest.template.json").read_text("utf-8"))
    (ext,) = data["extensions"]
    if ext["id"] != EXTENSION_ID:
        raise ValueError("manifest template id drifted")
    ext["sidecar"]["origin"] = f"http://127.0.0.1:{port}"
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def render_bundle(out_dir: Path, port: int) -> str:
    """Write the bundle into ``out_dir`` and return its ``tree_sha256``."""
    manifest = render_manifest(port)
    out = Path(out_dir)
    if inside_git_tree(out):
        raise ValueError("bundle dir is inside a git work tree")
    if out.exists() and any(out.iterdir()):
        raise ValueError("bundle dir is not empty")
    out.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(ASSET_DIR / name, out / name)
    (out / MANIFEST).write_bytes(manifest.encode("utf-8"))
    return tree_sha256(out)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="hfp_bundle", description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    try:
        sha = render_bundle(args.out, args.port)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"bundle refused: {exc}\n")
        return 2
    payload = {"extension_id": EXTENSION_ID, "files": len(ASSETS) + 1}
    payload["tree_sha256"] = sha
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
