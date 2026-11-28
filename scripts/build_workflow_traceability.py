"""Generate or verify tutorial traceability for shipped workflows (#1340-T02).

``python scripts/build_workflow_traceability.py``          write the files
``python scripts/build_workflow_traceability.py --check``  exit 1 if any differs

Reads workflow JSON and story manifest JSON only: no live server, no notebook.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "openbb_platform" / "extensions" / "agents"))
sys.path.insert(0, str(REPO_ROOT / "openbb_platform" / "extensions" / "mcp_server"))

# pylint: disable=wrong-import-position
from openbb_agents.notebook_guide.traceability import (  # noqa: E402
    TRACE_DIR,
    WORKFLOW_STORY_MAP,
    render_traceability,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check every traceability file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify, write nothing")
    parser.add_argument("--trace-dir", type=Path, default=TRACE_DIR)
    args = parser.parse_args(argv)
    stale: list[str] = []
    for workflow_id in sorted(WORKFLOW_STORY_MAP):
        expected = render_traceability(workflow_id)
        path = args.trace_dir / f"{workflow_id}.json"
        if args.check:
            actual = (
                path.read_bytes().decode("utf-8").replace("\r\n", "\n")
                if path.is_file()
                else None
            )
            if actual != expected:
                stale.append(path.name)
        else:
            args.trace_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected.encode("utf-8"))
            sys.stdout.write(f"wrote {path.name}\n")
    if stale:
        sys.stderr.write(f"traceability out of date: {', '.join(stale)}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
