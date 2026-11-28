"""The real worker entrypoint with the event-replay fake engine (#1355, #1356).

Usage: fake_run_worker.py [--noisy] [--idle-seconds N]
Runs ``openbb_nautilus_worker.__main__.main`` unchanged (guards, env scrub,
admission, heavy-job lock, deadlines, reviewed host, independent ledger)
except that the engine seam is ``nautilus_worker/tests/fake_engine.replay``
(fills at the event price, books like the engine, no settlement or staging)
and ``FIXED_PRECISION`` is 9, because nautilus_trader is not installed outside
the worker venv. Never imports it.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", "nautilus_worker"))
sys.path.insert(0, _WORKER)
sys.path.insert(0, os.path.join(_WORKER, "tests"))

# pylint: disable=wrong-import-position
import fake_engine  # noqa: E402
from openbb_nautilus_worker import (  # noqa: E402
    __main__ as worker_main,
    runs,
)


def noisy_replay(spec: runs.RunSpec) -> runs.EngineResult:
    """Like :func:`fake_engine.replay`, but writes junk to stdout and fd 1.

    Stands in for native/Rust/pyarrow code that prints: the protocol stream
    must survive it (#1355 CODE-2).
    """
    print("engine says hello on sys.stdout")  # noqa: T201
    sys.stdout.flush()
    os.write(1, b"native junk on fd 1\n{not json\n")
    return fake_engine.replay(spec)


ENGINES = {"--noisy": noisy_replay}


if __name__ == "__main__":
    args = sys.argv[1:]
    engine = fake_engine.replay
    for flag, fn in ENGINES.items():
        if flag in args:
            args.remove(flag)
            engine = fn
    raise SystemExit(worker_main.main(args, engine=engine, fixed_precision=9))
