"""Test helper: try the fmp_sync target lock once; print busy/acquired.

Usage: try_lock.py <state_root> <database>
Exit 75 when busy, 0 when acquired (and released). Never touches a database.
"""

import sys
from pathlib import Path

from portfolio_utils.fmp_sync.locking import LockBusy, target_lock


def main() -> int:
    root, database = sys.argv[1:3]
    try:
        with target_lock(database, root=Path(root), entrypoint="test_try"):
            print("acquired")
            return 0
    except LockBusy:
        print("busy")
        return 75


if __name__ == "__main__":
    sys.exit(main())
