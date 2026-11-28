"""Canonical hashing for reviewed strategies (#1356 T01). Pure; no nautilus_trader.

``code_sha256`` hashes the strategy's source files with CRLF folded to LF, so a
Windows checkout and a Linux checkout hash the same. ``params_sha256`` hashes
the *validated and normalised* parameters, so key order, ``1.0``, ``"1"`` and
``Decimal("1.00")`` are one value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..protocol import ErrorCode
from .errors import ReviewedError


def sha256_hex(data: bytes) -> str:
    """Return the hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no spaces, ASCII, no NaN."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def digest(obj: Any) -> str:
    """Hex sha256 of the canonical JSON of ``obj``."""
    return sha256_hex(canonical_json(obj))


def normalise_newlines(data: bytes) -> bytes:
    """Fold CRLF to LF (the only newline normalisation applied)."""
    return data.replace(b"\r\n", b"\n")


def file_sha256(root: Path, rel: str) -> str:
    """Hash one package-relative file under ``root`` after LF normalisation."""
    path = Path(root) / rel
    if path.is_symlink() or not path.is_file():
        raise ReviewedError(
            ErrorCode.MODULE_ORIGIN,
            "strategy_code_drift",
            f"reviewed file {rel!r} is missing or not a regular file",
        )
    try:
        resolved = path.resolve()
        resolved.relative_to(Path(root).resolve())
    except (OSError, ValueError) as exc:
        raise ReviewedError(
            ErrorCode.MODULE_ORIGIN, "strategy_code_drift", f"{rel!r} escapes the root"
        ) from exc
    return sha256_hex(normalise_newlines(resolved.read_bytes()))


def code_sha256(root: Path, files: Sequence[str]) -> str:
    """Hash ``[[path, file_sha256], ...]`` in the reviewed file order."""
    return digest([[rel, file_sha256(root, rel)] for rel in files])


def plain(value: Any) -> Any:
    """Normalise a value to canonical JSON-able form.

    Floats go through ``str`` (so ``1.0`` is ``"1"``); Decimals become plain
    strings without trailing zeros; mappings and sequences recurse.
    """
    if isinstance(value, float):
        value = Decimal(str(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite number")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def params_digest(strategy_id: str, version: str, normalised: Mapping[str, Any]) -> str:
    """Hash of ``{id, version, params}`` for already-normalised parameters."""
    return digest({"id": strategy_id, "version": version, "params": normalised})
