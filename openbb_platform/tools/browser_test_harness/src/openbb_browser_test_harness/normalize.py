"""Normalize observation times in harness fixtures (#1269).

Backend-local widget state carries the real UTC time it was read: the
``data_as_of`` row column, the chart ``layout.meta.asOf`` and the Markdown
``as of <time>.`` clause. Fixtures must stay deterministic, so the recorder
and the drift check replace exactly those timestamps with a token. Nothing
else is touched, so a changed shape, value or data state still drifts.
"""

from __future__ import annotations

import re
from typing import Any

OBSERVED_AT = "<observed-at>"
_TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
_TIMESTAMP_RE = re.compile(rf"^{_TIMESTAMP}$")
_AS_OF_CLAUSE_RE = re.compile(rf"(as of ){_TIMESTAMP}(\.)")
_KEYS = frozenset({"data_as_of", "asOf"})


def normalize_observed_at(value: Any) -> Any:
    """Return a copy of ``value`` with observation timestamps tokenized."""
    if isinstance(value, dict):
        return {
            key: (
                OBSERVED_AT
                if key in _KEYS and isinstance(item, str) and _TIMESTAMP_RE.match(item)
                else normalize_observed_at(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_observed_at(item) for item in value]
    if isinstance(value, str):
        return _AS_OF_CLAUSE_RE.sub(rf"\g<1>{OBSERVED_AT}\g<2>", value)
    return value
