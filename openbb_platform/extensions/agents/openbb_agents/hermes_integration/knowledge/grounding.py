"""Deterministic answer-contract validator for source-grounded synthesis (#1378-T02).

Synthesis is Hermes's own turn; OpenBB only supplies evidence payloads and
this validator. :func:`check_answer` grades an answer against the payloads of
the same turn and returns codes from the closed :data:`CODES` vocabulary.

Required answer shape (``answer_contract_version`` 1): every claim carries a
cite key returned in this turn, preceded by an inline ``(status, authority)``
label that matches the cited hit; a superseded source is cited only together
with its successor. When no payload has evidence (``no_evidence`` or
``ambiguous``) the answer is the literal ``[[abstain:<result>]]`` plus the
searched scope, and asserts nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .index import AUTHORITY_ORDER, CITE_RE, STATUSES

CODES = frozenset(
    {
        "ok",
        "uncited_claim",
        "unknown_cite",
        "status_mislabel",
        "superseded_without_successor",
        "authority_missing",
        "abstain_required",
        "abstain_ok",
    }
)
_ORDER = (
    "abstain_required",
    "uncited_claim",
    "unknown_cite",
    "status_mislabel",
    "superseded_without_successor",
    "authority_missing",
)
_ABSTAIN = re.compile(r"\[\[abstain:(no_evidence|ambiguous)\]\]")
_ANY_CITE = re.compile(r"\[\[doc:[^\]]*\]\]")
_LABEL = re.compile(
    r"\((?P<status>"
    + "|".join(STATUSES)
    + r")\s*,\s*(?P<authority>"
    + "|".join(AUTHORITY_ORDER)
    + r")\)"
)
_CLAIMS_DONE = re.compile(
    r"(?i)(?<!not )\b(?:is|are|was|were|now|already)\s+(?:already\s+|now\s+)?"
    r"(?:implemented|available|shipped|live|merged|in use|done)\b"
)
_CLAIMS_PLANNED = re.compile(
    r"(?i)\b(?:planned|proposed|not\s+(?:yet\s+)?implemented|future work)\b"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass(frozen=True)
class GroundingVerdict:
    """Fixed codes only; ``ok`` when every code is ``ok`` or ``abstain_ok``."""

    codes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True when the answer satisfies the contract."""
        return set(self.codes) <= {"ok", "abstain_ok"}


def _claims(answer: str) -> list[str]:
    claims: list[str] = []
    for raw in answer.replace("\r", "\n").split("\n"):
        line = _BULLET.sub("", raw).strip()
        claims.extend(p.strip() for p in _SENTENCE.split(line) if p.strip())
    return [c for c in claims if re.search(r"[A-Za-z0-9]", _ANY_CITE.sub("", c))]


def _prose_mislabel(text: str, status: Any) -> bool:
    prose = _LABEL.sub("", text)
    if status != "implemented" and _CLAIMS_DONE.search(prose):
        return True
    return status == "implemented" and bool(_CLAIMS_PLANNED.search(prose))


def _segment_codes(
    segment: str, cite: str, hit: Mapping[str, Any] | None, claim_cites: set[str]
) -> set[str]:
    if hit is None:
        return {"unknown_cite"}
    codes: set[str] = set()
    labels = list(_LABEL.finditer(segment))
    if not labels or labels[-1].group("authority") != hit.get("authority"):
        codes.add("authority_missing")
    status = hit.get("status")
    if labels and labels[-1].group("status") != status:
        codes.add("status_mislabel")
    if _prose_mislabel(segment, status):
        codes.add("status_mislabel")
    successors = set(hit.get("superseded_by") or ())
    superseded = status == "superseded" or bool(successors)
    if superseded and not successors & (claim_cites - {cite}):
        codes.add("superseded_without_successor")
    return codes


def check_answer(
    answer: str, payloads: Iterable[Mapping[str, Any]]
) -> GroundingVerdict:
    """Grade ``answer`` against this turn's tool ``payloads``."""
    payloads = list(payloads)
    hits: dict[str, Mapping[str, Any]] = {}
    for payload in payloads:
        for hit in payload.get("hits") or ():
            if isinstance(hit, Mapping) and isinstance(hit.get("cite"), str):
                hits[hit["cite"]] = hit
    results = {p.get("result") for p in payloads}
    text = answer if isinstance(answer, str) else ""
    markers = set(_ABSTAIN.findall(text))
    body = _ABSTAIN.sub("", text)
    cites_present = bool(_ANY_CITE.search(body))

    if "evidence" not in results:
        expected = results & {"no_evidence", "ambiguous"}
        if markers and markers <= expected and not cites_present:
            return GroundingVerdict(("abstain_ok",))
        return GroundingVerdict(("abstain_required",))
    if markers and not cites_present:
        return GroundingVerdict(("abstain_ok",))

    claims = _claims(body)
    if not claims:
        return GroundingVerdict(("abstain_required",))
    codes: set[str] = set()
    for claim in claims:
        found = list(_ANY_CITE.finditer(claim))
        if not found:
            codes.add("uncited_claim")
            continue
        claim_cites = {m.group(0) for m in found}
        start = 0
        last_hit: Mapping[str, Any] | None = None
        for match in found:
            cite = match.group(0)
            segment = claim[start : match.start()]
            start = match.end()
            hit = hits.get(cite) if CITE_RE.fullmatch(cite) else None
            codes |= _segment_codes(segment, cite, hit, claim_cites)
            last_hit = hit
        # Prose after the final cite is still a claim about that source.
        if last_hit is not None and _prose_mislabel(
            claim[start:], last_hit.get("status")
        ):
            codes.add("status_mislabel")
    ordered = tuple(c for c in _ORDER if c in codes)
    return GroundingVerdict(ordered or ("ok",))
