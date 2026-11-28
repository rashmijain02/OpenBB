"""Make ``trial_helpers`` importable under ``--import-mode=importlib`` (#1357)."""

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
