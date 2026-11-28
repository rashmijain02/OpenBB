"""Rejections raised by the reviewed-strategy loader (#1356 T01)."""

from __future__ import annotations

from ..protocol import ErrorCode, ProtocolError


class ReviewedError(ProtocolError):
    """A rejected reviewed-strategy request; ``reason`` names the check.

    Code drift is ``module_origin``; parameter, spec or semantics mismatch is
    ``schema`` (decision L5: no new error codes).
    """

    def __init__(self, code: ErrorCode, reason: str, message: str):
        super().__init__(code, f"{reason}: {message}")
        self.reason = reason
