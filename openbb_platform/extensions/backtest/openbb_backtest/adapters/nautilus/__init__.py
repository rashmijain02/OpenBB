"""Facade for the isolated Nautilus worker (#1355). Never imports ``nautilus_trader``.

The pure protocol module lives in the separate ``nautilus_worker`` distribution;
when it is not installed, the source-tree sibling is put on ``sys.path``.
"""

import sys
from pathlib import Path

WORKER_SOURCE_DIR = Path(__file__).resolve().parents[3] / "nautilus_worker"

try:
    import openbb_nautilus_worker  # noqa: F401  # pylint: disable=unused-import
except ImportError:  # source-tree layout
    if WORKER_SOURCE_DIR.is_dir() and str(WORKER_SOURCE_DIR) not in sys.path:
        sys.path.append(str(WORKER_SOURCE_DIR))
