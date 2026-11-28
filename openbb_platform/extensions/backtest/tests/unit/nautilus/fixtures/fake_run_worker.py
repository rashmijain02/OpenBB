"""The real worker entrypoint with a fake engine seam and standard precision.

Usage: fake_run_worker.py [--idle-seconds N]
Runs ``openbb_nautilus_worker.__main__.main`` unchanged (guards, env scrub,
admission, heavy-job lock, deadlines) except that the engine fills the
strategy's order at the first close and ``FIXED_PRECISION`` is 9, because
nautilus_trader is not installed outside the worker venv. Never imports it.
"""

import os
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(
    0, os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", "nautilus_worker"))
)

# pylint: disable=wrong-import-position
from openbb_nautilus_worker import (  # noqa: E402
    __main__ as worker_main,
    runs,
)


def fill_at_first_close(spec: runs.RunSpec) -> runs.EngineResult:
    """Fill the whole order at the first session's close with zero commission."""
    return runs.EngineResult(
        name="fake-fill-at-close",
        version="0",
        fills=[
            runs.Fill(
                session=spec.sessions[0],
                quantity=spec.order.quantity,
                price=spec.closes[0],
                commission=Decimal(0),
            )
        ],
    )


if __name__ == "__main__":
    raise SystemExit(
        worker_main.main(sys.argv[1:], engine=fill_at_first_close, fixed_precision=9)
    )
