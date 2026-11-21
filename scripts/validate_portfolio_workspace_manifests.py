"""Validate the Portfolio Intelligence OpenBB Workspace manifests (#1266).

Operator / CI command. Checks the checked-in ``widgets.json`` and
``apps.json`` against the pinned Workspace schema rules and the backend's
registered routes, then compares the result with the recorded shrink-only
debt baseline.

Usage::

    python scripts/validate_portfolio_workspace_manifests.py
    python scripts/validate_portfolio_workspace_manifests.py --strict

Exit codes: 0 = no issues beyond recorded debt (``--strict``: no issues at
all); 1 = new violations or stale baseline entries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

# pylint: disable=wrong-import-position
from openbb_portfolio_intel.widget_backend import contracts  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXTENSION = REPO / "openbb_platform" / "extensions" / "portfolio_intel"
BACKEND = EXTENSION / "openbb_portfolio_intel" / "widget_backend"
DEFAULT_BASELINE = (
    EXTENSION / "tests" / "unit" / "fixtures" / "workspace_contract_debt.json"
)


def main(argv: list[str] | None = None) -> int:
    """Run the validation and print a compact report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--strict", action="store_true", help="fail on recorded debt as well"
    )
    args = parser.parse_args(argv)

    widgets = json.loads((BACKEND / "widgets.json").read_text(encoding="utf-8"))
    apps = json.loads((BACKEND / "apps.json").read_text(encoding="utf-8"))
    routes = {getattr(route, "path", "") for route in app.routes}
    issues = contracts.collect_manifest_issues(widgets, apps, routes=routes)
    sys.stdout.write(
        f"{len(widgets)} widgets, {len(apps)} apps, {len(issues)} issues" + "\n"
    )
    if args.strict:
        for issue in issues:
            sys.stdout.write(f"ISSUE {issue.code} {issue.path}: {issue.message}" + "\n")
        return 1 if issues else 0

    baseline = {
        **contracts.load_debt_baseline(args.baseline, prefix="widgets."),
        **contracts.load_debt_baseline(args.baseline, prefix="apps."),
    }
    new, resolved = contracts.compare_with_baseline(issues, baseline)
    for issue in new:
        sys.stdout.write(f"NEW {issue.code} {issue.path}: {issue.message}" + "\n")
    for code, path in resolved:
        sys.stdout.write(f"RESOLVED (remove from baseline) {code} {path}" + "\n")
    sys.stdout.write(f"recorded debt: {len(baseline) - len(resolved)}" + "\n")
    return 1 if new or resolved else 0


if __name__ == "__main__":
    sys.exit(main())
