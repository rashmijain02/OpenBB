"""Fake worker speaking the signed stdio protocol with canned ``describe`` facts.

Usage: fake_worker.py FACTS_JSON [--bad-mac] [--error CODE]
Never imports nautilus_trader.
"""

import json
import os
import pathlib
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER_ROOT = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "..", "nautilus_worker")
)
sys.path.insert(0, _WORKER_ROOT)

from openbb_nautilus_worker import (
    protocol,
)  # noqa: E402  # pylint: disable=wrong-import-position


def main() -> int:
    """Serve describe/shutdown with canned facts."""
    facts = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    bad_mac = "--bad-mac" in sys.argv
    forced_error = (
        sys.argv[sys.argv.index("--error") + 1] if "--error" in sys.argv else None
    )

    def describe(_body):
        if forced_error:
            raise protocol.ProtocolError(
                protocol.ErrorCode(forced_error), "canned failure"
            )
        return facts

    session = protocol.Session.from_key_line(sys.stdin.buffer.readline())
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return 0
        out, stop = session.handle(
            line, {"describe": describe, "shutdown": lambda _b: {}}
        )
        if bad_mac:
            frame = json.loads(out)
            frame["mac"] = "0" * 64
            out = (json.dumps(frame) + "\n").encode()
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
        if stop:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
