"""Render FMP REST responses exactly as the hosted FMP MCP server does (#1299).

The hosted server is a Node service: it parses the REST body and re-serialises
it with ``JSON.stringify`` (compact, insertion order, JavaScript number
formatting). Empty results for an identifier lookup become a ``not_found``
envelope, 402 responses become an ``ACCESS DENIED`` message, other HTTP errors
become ``Bad request for tool ...``. Non-JSON bodies (the 10-K xlsx) are decoded
as UTF-8 with replacement characters and emitted as a JSON string.

Every rule here is pinned by a recorded fixture under ``tests/fixtures/hosted``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: Arguments the hosted server names in its ``not_found`` envelope, observed
#: for symbol, cik and name. ``symbols`` / ``query`` / ``formType`` lookups
#: return a plain ``[]`` instead.
NOT_FOUND_IDENTIFIERS = ("symbol", "cik", "name")

PRICING_URL = "https://financialmodelingprep.com/developer/docs/pricing"
MAX_SAFE_INTEGER = 2**53 - 1
_ARRAY_INDEX = re.compile(r"^(0|[1-9][0-9]*)$")
_MAX_ARRAY_INDEX = 2**32 - 2


def _reject_constant(name: str) -> Any:
    """``JSON.parse`` rejects ``NaN`` / ``Infinity``; so do we."""
    raise ValueError(f"non-JSON literal {name}")


def _is_array_index(key: str) -> bool:
    return bool(_ARRAY_INDEX.match(key)) and int(key) <= _MAX_ARRAY_INDEX


def _js_key_order(obj: dict) -> list[tuple[str, Any]]:
    """JS property order: array-index keys ascending, then insertion order."""
    items = [(str(k), v) for k, v in obj.items()]
    index = sorted(
        (kv for kv in items if _is_array_index(kv[0])), key=lambda kv: int(kv[0])
    )
    return index + [kv for kv in items if not _is_array_index(kv[0])]


@dataclass(frozen=True)
class Rendered:
    """Text for ``content[0]`` and the ``isError`` flag of a tool result."""

    text: str
    is_error: bool


def js_number(value: float | int) -> str:
    """Format a number like JavaScript's ``Number.prototype.toString``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) <= MAX_SAFE_INTEGER:
            return str(value)
        value = float(value)  # JSON.parse reads every number as a double
    if not math.isfinite(value):
        return "null"  # JSON.stringify(NaN) === "null"
    if value == 0:
        return "0"
    dec = Decimal(repr(value)).normalize()
    sign, digit_tuple, exp = dec.as_tuple()
    digits = "".join(map(str, digit_tuple))
    k = len(digits)
    if not isinstance(exp, int):  # finite values always have an int exponent
        return "null"
    n = exp + k  # value = 0.digits * 10**n
    prefix = "-" if sign else ""
    if k <= n <= 21:
        return prefix + digits + "0" * (n - k)
    if 0 < n <= 21:
        return prefix + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return prefix + "0." + "0" * (-n) + digits
    e = n - 1
    mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
    return f"{prefix}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"


_LONE_SURROGATE = re.compile("[\\ud800-\\udfff]")


def _js_string(text: str) -> str:
    """``JSON.stringify`` of a string; lone UTF-16 surrogates are escaped as in JS."""
    out = json.dumps(text, ensure_ascii=False)
    if _LONE_SURROGATE.search(out):
        out = _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", out)
    return out


def js_dumps(obj: Any) -> str:
    """``JSON.stringify(obj)``: compact, insertion order, JS numbers."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, (int, float)):
        return js_number(obj)
    if isinstance(obj, str):
        return _js_string(obj)
    if isinstance(obj, dict):
        return (
            "{"
            + ",".join(f"{_js_string(k)}:{js_dumps(v)}" for k, v in _js_key_order(obj))
            + "}"
        )
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(js_dumps(v) for v in obj) + "]"
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def _js_str(value: Any) -> str:
    """``String(value)`` in JavaScript."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return js_number(value)
    if isinstance(value, list):
        return ",".join(_js_str(v) for v in value)
    return str(value)


def _not_found(arguments: dict[str, Any]) -> str | None:
    provided = [
        f'{k}="{_js_str(arguments[k])}"'
        for k in arguments
        if k in NOT_FOUND_IDENTIFIERS
    ]
    if not provided:
        return None
    endpoint = arguments.get("endpoint", "")
    joined = ", ".join(provided)
    return js_dumps(
        {
            "status": "not_found",
            "endpoint": endpoint,
            "provided": joined,
            "message": (
                f"No data returned for {endpoint} with {joined}. The identifier may "
                "not exist, or may have no data for this endpoint. Use the 'search' "
                "tool to verify the symbol/cik/name."
            ),
        }
    )


def _error_message(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        for key in ("Error Message", "error", "message"):
            if isinstance(parsed.get(key), str):
                return parsed[key]
    return text


def _access_denied(tool: str, message: str) -> str:
    plan = message.split(" ", 1)[0] if message else "current"
    return (
        f'ACCESS DENIED: A parameter you passed to this tool ("{tool}") requires a '
        f"higher plan. The user is currently on the {plan} plan. Please inform the "
        f"user they need to upgrade their FMP subscription at {PRICING_URL} to use "
        "this filter. Do not retry this tool with the same parameter value; the "
        "user may retry with values their plan allows."
    )


def render_response(
    *, tool: str, arguments: dict[str, Any], path: str, status: int, body: bytes
) -> Rendered:
    """Turn one FMP REST response into the hosted tool-result text."""
    if status == 200:
        try:
            parsed = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError):
            return Rendered(_js_string(body.decode("utf-8", "replace")), False)
        if parsed == []:
            envelope = _not_found(arguments)
            if envelope is not None:
                return Rendered(envelope, False)
        return Rendered(js_dumps(parsed), False)
    message = _error_message(body)
    if status == 402:
        return Rendered(_access_denied(tool, message), True)
    return Rendered(f'Bad request for tool "{tool}" (endpoint {path}): {message}', True)
