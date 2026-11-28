"""Canonical JSON and tool-input-schema digests.

One definition shared by the tutorial catalog generator, the workflow
manifests and the registry, so a reviewed schema pin means the same bytes
everywhere. Pure: no I/O, no server import.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json_sha256(obj: Any) -> str:
    """Return the SHA-256 of ``obj`` as sorted, compact, UTF-8 JSON."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tool_input_schema_sha256(parameters: Mapping[str, Any] | None) -> str:
    """Return the pin for a tool's input schema (``None`` hashes as ``{}``)."""
    return canonical_json_sha256(parameters or {})
