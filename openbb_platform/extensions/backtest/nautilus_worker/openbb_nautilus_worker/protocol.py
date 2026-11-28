"""Signed stdio JSON-lines protocol between the OpenBB facade and the worker.

Pure module: importable WITHOUT nautilus_trader (the facade imports it). One JSON
object per line, at most ``MAX_FRAME_BYTES``. The first stdin frame is a key
frame carrying a per-spawn 32-byte key (never argv/env). Every later frame
carries ``mac = HMAC-SHA256(key, canonical_json(frame without mac))`` and a
strictly increasing ``seq``. Error codes equal ``FailedLayer`` string values
(#1338) by decision L5; this module cannot import ``openbb_agents``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024
KEY_BYTES = 32
KNOWN_OPS = ("describe", "shutdown")


class ErrorCode(str, Enum):
    """Worker error codes; each value equals a ``FailedLayer`` value."""

    PROCESS = "process"
    MODULE_ORIGIN = "module_origin"
    ABI = "abi"
    CONFIG = "config"
    AUTH = "auth"
    SCHEMA = "schema"
    EGRESS = "egress"


class ProtocolError(Exception):
    """A protocol or worker failure carrying a ``FailedLayer``-valued code."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_FROZEN = ConfigDict(extra="forbid", frozen=True)


class KeyFrame(BaseModel):
    """First stdin frame: delivers the per-spawn signing key (hex)."""

    model_config = _FROZEN
    v: Literal[1]
    hello: Literal[True]
    key: str = Field(pattern=r"^[0-9a-f]{64}$")


class Request(BaseModel):
    """Signed request frame."""

    model_config = _FROZEN
    v: Literal[1]
    seq: int = Field(ge=1)
    op: str
    body: dict[str, Any]
    mac: str = Field(pattern=r"^[0-9a-f]{64}$")


class ErrorBody(BaseModel):
    """Error payload of a failed response."""

    model_config = _FROZEN
    code: str
    message: str


class Response(BaseModel):
    """Signed response frame."""

    model_config = _FROZEN
    v: Literal[1]
    seq: int = Field(ge=0)
    ok: bool
    body: dict[str, Any] | None = None
    error: ErrorBody | None = None
    mac: str = Field(pattern=r"^[0-9a-f]{64}$")


class LicenseFile(BaseModel):
    """Name and sha256 of a licence file from the installed dist-info."""

    model_config = _FROZEN
    name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DescribeFacts(BaseModel):
    """Facts a worker reports about its own runtime. No paths, no secrets."""

    model_config = _FROZEN
    nautilus_version: str
    python_version: str
    python_tag: str
    wheel_tag: str
    platform_tag: str
    high_precision: bool
    fixed_precision: int
    module_origin_in_prefix: bool
    wheel_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_files: list[LicenseFile]


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes used for signing."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _mac(key: bytes, envelope: dict[str, Any]) -> str:
    unsigned = {k: v for k, v in envelope.items() if k != "mac"}
    return hmac.new(key, canonical_json(unsigned), hashlib.sha256).hexdigest()


def encode_frame(model: BaseModel) -> bytes:
    """Serialize a frame to one newline-terminated line, enforcing the size cap."""
    line = json.dumps(
        model.model_dump(mode="json", exclude_none=True), separators=(",", ":")
    ).encode()
    if len(line) + 1 > MAX_FRAME_BYTES:
        raise ProtocolError(ErrorCode.SCHEMA, "frame exceeds size limit")
    return line + b"\n"


def encode_key_frame(key: bytes) -> bytes:
    """Build the first stdin frame for ``key``."""
    if len(key) != KEY_BYTES:
        raise ProtocolError(ErrorCode.CONFIG, "key must be 32 bytes")
    return encode_frame(KeyFrame(v=1, hello=True, key=key.hex()))


def sign_request(key: bytes, seq: int, op: str, body: dict[str, Any]) -> Request:
    """Build a signed request."""
    env: dict[str, Any] = {"v": PROTOCOL_VERSION, "seq": seq, "op": op, "body": body}
    return Request.model_validate({**env, "mac": _mac(key, env)})


def sign_response(
    key: bytes,
    seq: int,
    *,
    ok: bool,
    body: dict | None = None,
    error: ErrorBody | None = None,
) -> Response:
    """Build a signed response."""
    env: dict[str, Any] = {"v": PROTOCOL_VERSION, "seq": seq, "ok": ok}
    if body is not None:
        env["body"] = body
    if error is not None:
        env["error"] = error.model_dump()
    return Response.model_validate({**env, "mac": _mac(key, env)})


def decode_line(line: bytes) -> dict[str, Any]:
    """Parse one frame line into a dict, enforcing size and JSON-object shape."""
    if len(line) > MAX_FRAME_BYTES:
        raise ProtocolError(ErrorCode.SCHEMA, "frame exceeds size limit")
    try:
        obj = json.loads(line)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(ErrorCode.SCHEMA, "frame is not valid JSON") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(ErrorCode.SCHEMA, "frame is not a JSON object")
    return obj


def _check_mac(key: bytes, raw: dict[str, Any], mac: str) -> None:
    if not hmac.compare_digest(_mac(key, raw), mac):
        raise ProtocolError(ErrorCode.AUTH, "bad frame signature")


def verify_request(key: bytes, raw: dict[str, Any], expected_seq: int) -> Request:
    """Validate schema, signature and sequence of a request."""
    try:
        req = Request.model_validate(raw)
    except ValidationError as exc:
        raise ProtocolError(ErrorCode.SCHEMA, "request does not match schema") from exc
    _check_mac(key, raw, req.mac)
    if req.seq != expected_seq:
        raise ProtocolError(ErrorCode.AUTH, "unexpected sequence number")
    if req.op not in KNOWN_OPS:
        raise ProtocolError(ErrorCode.SCHEMA, "unknown op")
    return req


def verify_response(key: bytes, raw: dict[str, Any], expected_seq: int) -> Response:
    """Validate schema, signature and sequence of a response."""
    try:
        resp = Response.model_validate(raw)
    except ValidationError as exc:
        raise ProtocolError(ErrorCode.SCHEMA, "response does not match schema") from exc
    _check_mac(key, raw, resp.mac)
    if resp.seq != expected_seq:
        raise ProtocolError(ErrorCode.AUTH, "unexpected sequence number")
    return resp


Handler = Callable[[dict[str, Any]], dict[str, Any]]


class Session:
    """Server side of one spawn: holds the key and the expected sequence."""

    def __init__(self, key: bytes):
        self._key = key
        self._next_seq = 1

    @classmethod
    def from_key_line(cls, line: bytes) -> Session:
        """Build a session from the first stdin line; anything else is ``auth``."""
        try:
            frame = KeyFrame.model_validate(decode_line(line)) if line.strip() else None
        except (ProtocolError, ValidationError) as exc:
            raise ProtocolError(ErrorCode.AUTH, "missing or invalid key frame") from exc
        if frame is None:
            raise ProtocolError(ErrorCode.AUTH, "missing or invalid key frame")
        return cls(bytes.fromhex(frame.key))

    def _error(self, seq: int, code: ErrorCode, message: str) -> bytes:
        return encode_frame(
            sign_response(
                self._key,
                seq,
                ok=False,
                error=ErrorBody(code=code.value, message=message),
            )
        )

    def handle(self, line: bytes, handlers: dict[str, Handler]) -> tuple[bytes, bool]:
        """Process one request line; return ``(response_line, stop)``."""
        seq = self._next_seq
        try:
            raw = decode_line(line)
            req = verify_request(self._key, raw, seq)
        except ProtocolError as exc:
            return self._error(0, exc.code, exc.message), True
        self._next_seq += 1
        stop = req.op == "shutdown"
        handler = handlers.get(req.op)
        if handler is None:
            return self._error(seq, ErrorCode.SCHEMA, "op not supported"), stop
        try:
            body = handler(req.body)
        except ProtocolError as exc:
            return self._error(seq, exc.code, exc.message), stop
        except Exception:  # pylint: disable=broad-except
            return self._error(seq, ErrorCode.PROCESS, "worker handler failed"), stop
        return encode_frame(sign_response(self._key, seq, ok=True, body=body)), stop
