"""Shared text cleaning for the public-knowledge corpus and index (#1378).

Kept import-free of the rest of the package so ``corpus`` and ``index`` can both
use it without a cycle.
"""

from __future__ import annotations

import re

_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(text: str) -> str:
    """Strip HTML comments, zero-width/bidi and control characters."""
    text = _HTML_COMMENT.sub("", text)
    text = _INVISIBLE.sub("", text)
    return _CONTROL.sub("", text)
