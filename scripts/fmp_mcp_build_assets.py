"""Build ``openbb_fmp_cached_mcp/assets/{tools,endpoint_map}.json`` from recorded fixtures (#1299).

The served ``tools/list`` is the recorded hosted inventory, verbatim. The
endpoint map joins the recorded REST path per endpoint, the hosted defaults
discovered for required parameters, the required-parameter list parsed from
each tool description, and the owner-approved retention class.

Run after re-recording with ``scripts/fmp_mcp_record.py``; the contract tests
fail until the assets match the fixtures again.
"""

# ruff: noqa: T201, D102, D103, PLW2901  (operator CLI)
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "openbb_platform/extensions/fmp_cached_mcp"
HOSTED = PKG / "tests/fixtures/hosted"
ASSETS = PKG / "openbb_fmp_cached_mcp/assets"
RETENTION = REPO / "specs/gh-1298-fmp-cached-mcp-parity/retention-classes.json"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--date", default="2026-11-24")
    a = p.parse_args()
    inv = json.loads((HOSTED / f"inventory-{a.date}.json").read_text("utf-8"))
    paths = json.loads((HOSTED / f"paths-{a.date}.json").read_text("utf-8"))
    retention = json.loads(RETENTION.read_text("utf-8"))

    emap: dict[str, dict[str, dict]] = {}
    for tool in inv["tools"]:
        enum = tool["inputSchema"]["properties"]["endpoint"]["enum"]
        required: dict[str, list[str]] = {}
        for line in tool["description"].splitlines():
            m = re.match(r"^- ([^\s:(]+)(?: \(([^)]*)\))?: ", line)
            if m and m.group(1) in enum:
                required[m.group(1)] = [
                    x.strip().rstrip("*")
                    for x in (m.group(2) or "").split(",")
                    if x.strip()
                ]
        eps: dict[str, dict] = {}
        for ep in enum:
            key = f"{tool['name']}/{ep}"
            rec = paths[key]
            spec = {
                "path": rec["path"],
                "required": required.get(ep, []),
                "retention": retention[key],
            }
            if rec.get("defaults"):
                spec["defaults"] = rec["defaults"]
                spec["defaults_verified"] = rec["how"] == "rest-json-equal"
            eps[ep] = spec
        emap[tool["name"]] = eps

    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "tools.json").write_text(
        json.dumps(inv["tools"], indent=1, ensure_ascii=False) + "\n", "utf-8"
    )
    (ASSETS / "endpoint_map.json").write_text(
        json.dumps(emap, indent=1, ensure_ascii=False) + "\n", "utf-8"
    )
    print(f"tools={len(inv['tools'])} endpoints={sum(len(v) for v in emap.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
