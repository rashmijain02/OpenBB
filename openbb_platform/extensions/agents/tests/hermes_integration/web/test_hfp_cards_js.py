"""Run the HFP card JS tests (``hfp_cards.test.cjs``) under ``node --test`` (#1342)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("hfp_cards.test.cjs")


def test_hfp_cards_js_suite():
    """Every ``node:test`` case in the card suite passes."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed: the HFP card JS suite cannot run")
    result = subprocess.run(  # noqa: S603
        [node, "--test", "--test-reporter=tap", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    failed = [line for line in output.splitlines() if line.startswith("not ok")]
    assert result.returncode == 0 and not failed, "\n".join(failed) or output[-2000:]
    passed = [line for line in output.splitlines() if line.startswith("ok ")]
    assert len(passed) >= 18, output[-2000:]
