"""Worker entrypoint: ``python -I -m openbb_nautilus_worker`` (stdio, no listener)."""

import sys

from . import describe, protocol


def serve(stdin, stdout) -> int:
    """Serve signed frames until shutdown, EOF or an authentication failure."""
    try:
        session = protocol.Session.from_key_line(
            stdin.readline(protocol.MAX_FRAME_BYTES + 2)
        )
    except protocol.ProtocolError:
        return 3
    handlers: dict[str, protocol.Handler] = {
        "describe": describe.collect_facts,
        "shutdown": lambda _body: {},
    }
    while True:
        line = stdin.readline(protocol.MAX_FRAME_BYTES + 2)
        if not line:
            return 0
        out, stop = session.handle(line, handlers)
        stdout.write(out)
        stdout.flush()
        if stop:
            return 0


def main() -> int:
    """Run the worker on the process's binary stdio."""
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
