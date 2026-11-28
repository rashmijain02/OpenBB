"""Test helper: hold the fmp_sync target lock until killed or a release file appears.

Usage: hold_lock.py <state_root> <database> <ready_file> <release_file>
Never touches a database or the network.
"""

import os
import sys
import time
from pathlib import Path

from portfolio_utils.fmp_sync.locking import target_lock


def main() -> int:
    root, database, ready, release = sys.argv[1:5]
    with target_lock(database, root=Path(root), entrypoint="test_holder"):
        # The pid of *this* interpreter (a venv launcher may sit in between).
        Path(ready).write_text(str(os.getpid()), encoding="utf-8")
        deadline = time.monotonic() + 120
        while not Path(release).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
