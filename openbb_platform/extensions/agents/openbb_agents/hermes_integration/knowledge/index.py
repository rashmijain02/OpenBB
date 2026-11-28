"""Bounded exact retrieval over the admitted public corpus (#1378-T02).

An in-memory SQLite FTS5 index plus an exact identifier table, built from a
:class:`~.corpus.Corpus`. Nothing is persisted. :meth:`KnowledgeIndex.search`
runs three stages and the first non-empty one wins:

1. ``identifier``: a query token is a known identifier (``PF-15``, ``T01``,
   ``documents.search``) that a section *defines* (heading or definition
   line), or the whole query equals a heading;
2. ``phrase``: FTS5 phrase of every query token;
3. ``all_terms``: FTS5 conjunction of every token, ranked by ``bm25``.

Every token is double-quoted before ``MATCH``, so model text cannot inject
FTS5 operators: there is no OR, NOT, NEAR, column filter, prefix or fuzzy
matching, and no embeddings. Payloads are capped (5 hits, 800 characters per
excerpt, 4000 characters in total) and every excerpt is marked untrusted.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._text import clean_text
from .corpus import Corpus, path_code

ANSWER_CONTRACT_VERSION = 1
MAX_HITS = 5
MAX_EXCERPT = 800
MAX_PAYLOAD = 4000
MAX_QUERY = 256
MAX_TOKENS = 12
MAX_SECTION_TEXT = 3000

STATUSES = ("implemented", "proposed", "historical", "superseded", "unknown")
STATUS_FILTERS = frozenset({"any", *STATUSES})
AUTHORITY_ORDER = (
    "official_primary",
    "repo_requirement",
    "repo_plan",
    "repo_design",
    "repo_reference",
    "historical",
)
RESULTS = frozenset({"evidence", "no_evidence", "ambiguous", "unknown_cite"})
MATCHES = frozenset({"identifier", "phrase", "all_terms", "cite"})
FLAGS = frozenset(
    {
        "INSTRUCTION_LIKE_TEXT",
        "HEAD_DRIFT",
        "SUPERSEDED",
        "SUCCESSOR",
        "POINTER_ONLY",
        "TRUNCATED",
    }
)
HIT_FIELDS = frozenset(
    {
        "cite",
        "path",
        "section",
        "revision",
        "authority",
        "status",
        "superseded_by",
        "match",
        "flags",
        "excerpt",
    }
)
PAYLOAD_FIELDS = frozenset(
    {"answer_contract_version", "result", "query", "scope", "hits"}
)

CITE_RE = re.compile(
    r"\[\[doc:(?P<source_id>[a-z0-9][a-z0-9_.-]*)@(?P<blob>[0-9a-f]{12})"
    r"#(?P<anchor>[\w-]+)\]\]"
)
_TOKEN = re.compile(r"[^\W_](?:[\w.-]*[^\W_])?")
_IDENT = re.compile(
    r"(?<![\w.-])(?:[A-Z][A-Z0-9]*-[A-Z]*[0-9]+[A-Za-z0-9]*|T[0-9]{2}"
    r"|[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)(?![\w-])"
)
_DEFINITION = re.compile(r"^\s*(?:\|\s*|[-*]\s+)?(?:\*\*|`)?(?P<ident>[^\s|*`:]+)")
_INSTRUCTION = re.compile(
    r"(?im)(?:^\s*(?:system|assistant|developer|user)\s*:"
    r"|\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions"
    r"|\"(?:tool_call|tool_calls|function_call|tool_name)\"\s*:"
    r"|\b(?:pip|npm|uv)\s+install\b|\bcurl\s+\S"
    r"|\b(?:change|switch|set|use)\s+(?:the\s+)?"
    r"(?:policy|profile|model|route|principal|provider|endpoint|base[ _]?url"
    r"|api[ _]?key)\b"
    r"|\b(?:call|invoke|execute|run)\s+(?:the\s+)?`?[a-z][a-z0-9]*(?:_[a-z0-9]+)+)"
)
_LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)")
# Detection-only fold of common Cyrillic/Greek look-alikes of Latin letters;
# NFKC already folds full-width and compatibility forms. The folded text is
# only matched, never returned.
_CONFUSABLES = str.maketrans(
    {
        "\u0430": "a",
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0456": "i",
        "\u0458": "j",
        "\u0455": "s",
        "\u04bb": "h",
        "\u0501": "d",
        "\u03b1": "a",
        "\u03b9": "i",
        "\u03bd": "v",
        "\u03bf": "o",
        "\u0406": "I",
        "\u0410": "A",
        "\u0415": "E",
        "\u041e": "O",
        "\u0420": "P",
        "\u0421": "C",
    }
)


class QueryRejected(ValueError):
    """A query or argument outside the fixed bounds (fixed ``code`` only)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def instruction_like(text: str) -> bool:
    """Return True when ``text`` reads like an instruction to the model.

    Heuristic: the folded text (NFKC plus look-alike letters) is matched
    against :data:`_INSTRUCTION`, and a markdown link whose target is a
    denylisted path (``notebooks_local/``, ``.env*``, agent instructions)
    also counts. The flag only labels untrusted data; safety rests on the
    server-side gate and the argument-free tools.
    """
    folded = unicodedata.normalize("NFKC", text).translate(_CONFUSABLES)
    if _INSTRUCTION.search(folded):
        return True
    for target in _LINK_TARGET.findall(folded):
        path = re.split(r"[#?]", target, maxsplit=1)[0]
        while path.startswith(("./", "../")):
            path = path.split("/", 1)[1]
        if path and path_code(path) == "denylisted":
            return True
    return False


def query_tokens(query: str) -> list[str]:
    """Normalise ``query`` into at most :data:`MAX_TOKENS` literal tokens."""
    if not isinstance(query, str) or len(query) > MAX_QUERY:
        raise QueryRejected("query_too_long")
    tokens = _TOKEN.findall(clean_text(query))
    if not tokens:
        raise QueryRejected("empty_query")
    if len(tokens) > MAX_TOKENS:
        raise QueryRejected("too_many_tokens")
    return tokens


def _quoted(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def phrase_expr(tokens: Sequence[str]) -> str:
    """FTS5 expression for the phrase of ``tokens`` (one quoted string)."""
    return _quoted(" ".join(tokens))


def all_terms_expr(tokens: Sequence[str]) -> str:
    """FTS5 expression requiring every token (implicit AND, each quoted)."""
    return " ".join(_quoted(t) for t in tokens)


def make_cite(source_id: str, blob_sha: str, anchor: str) -> str:
    """Return the revision-pinned cite key for one section."""
    return f"[[doc:{source_id}@{blob_sha[:12]}#{anchor}]]"


@dataclass(frozen=True)
class Entry:  # pylint: disable=too-many-instance-attributes
    """One indexed section with register metadata."""

    cite: str
    source_id: str
    path: str
    anchor: str
    title: str
    blob_sha: str
    head_drift: bool
    kind: str
    authority: str
    status: str
    superseded_by: tuple[str, ...]
    pointer_only: bool
    text: str
    identifiers: frozenset[str] = field(default_factory=frozenset)


def _defined_identifiers(title: str, text: str) -> frozenset[str]:
    found = {m.group(0).casefold() for m in _IDENT.finditer(title)}
    for line in text.split("\n")[1:]:
        head = _DEFINITION.match(line)
        if head and _IDENT.fullmatch(head.group("ident").rstrip(".,;")):
            found.add(head.group("ident").rstrip(".,;").casefold())
    return frozenset(found)


def _authority_rank(authority: str) -> int:
    return AUTHORITY_ORDER.index(authority) if authority in AUTHORITY_ORDER else 99


class KnowledgeIndex:
    """In-memory exact index; build with :meth:`from_corpus`."""

    def __init__(self, entries: Iterable[Entry]) -> None:
        self._entries = tuple(entries)
        self._by_cite = {e.cite: e for e in self._entries}
        self._by_source: dict[str, list[Entry]] = {}
        for entry in self._entries:
            self._by_source.setdefault(entry.source_id, []).append(entry)
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.execute(
            "CREATE VIRTUAL TABLE fts USING fts5(body, tokenize='unicode61')"
        )
        self._db.executemany(
            "INSERT INTO fts(rowid, body) VALUES (?, ?)",
            [(i, f"{e.title}\n{e.text}") for i, e in enumerate(self._entries)],
        )
        self._db.commit()

    @classmethod
    def from_corpus(cls, built: Corpus) -> KnowledgeIndex:
        """Index every admitted section of ``built``."""
        entries = []
        for doc in built.documents:
            for sec in doc.sections:
                text = clean_text(sec.text)
                entries.append(
                    Entry(
                        cite=make_cite(doc.source_id, doc.blob_sha, sec.anchor),
                        source_id=doc.source_id,
                        path=doc.path,
                        anchor=sec.anchor,
                        title=clean_text(sec.title),
                        blob_sha=doc.blob_sha,
                        head_drift=doc.head_drift,
                        kind=doc.kind,
                        authority=doc.authority,
                        status=sec.status,
                        superseded_by=doc.superseded_by,
                        pointer_only=doc.kind == "tax_source_pointer",
                        text=text,
                        identifiers=_defined_identifiers(sec.title, text),
                    )
                )
        return cls(entries)

    def __len__(self) -> int:
        """Return the number of indexed sections."""
        return len(self._entries)

    @property
    def cites(self) -> frozenset[str]:
        """Every cite key the index holds."""
        return frozenset(self._by_cite)

    # --- stages ---------------------------------------------------------------

    def _identifier_stage(self, tokens: Sequence[str]) -> list[Entry]:
        wanted = {t.casefold() for t in tokens if _IDENT.fullmatch(t)}
        whole = " ".join(tokens).casefold()
        scored = []
        for entry in self._entries:
            in_title = {i for i in wanted if i in entry.identifiers}
            title_hit = bool(entry.title) and (
                " ".join(_TOKEN.findall(entry.title)).casefold() == whole
            )
            if not in_title and not title_hit:
                continue
            heading = sum(1 for i in in_title if i in entry.title.casefold()) + (
                2 if title_hit else 0
            )
            scored.append((-len(in_title) - heading, entry))
        scored.sort(key=lambda item: (item[0], *self._tie(item[1])))
        return [entry for _, entry in scored]

    def _fts_stage(self, expr: str) -> list[Entry]:
        rows = self._db.execute(
            "SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts)",
            (expr,),
        ).fetchall()
        ranked = [(round(score, 6), self._entries[rowid]) for rowid, score in rows]
        ranked.sort(key=lambda item: (item[0], *self._tie(item[1])))
        return [entry for _, entry in ranked]

    @staticmethod
    def _tie(entry: Entry) -> tuple[int, int, str]:
        superseded = int(entry.status == "superseded" or bool(entry.superseded_by))
        return superseded, _authority_rank(entry.authority), entry.cite

    def _successor(self, entry: Entry) -> Entry | None:
        for newer in entry.superseded_by:
            candidates = self._by_source.get(newer, [])
            same = [c for c in candidates if c.anchor == entry.anchor]
            if same or candidates:
                return (same or candidates)[0]
        return None

    # --- public API -------------------------------------------------------------

    def search(
        self, query: str, limit: int = MAX_HITS, status: str = "any"
    ) -> dict[str, Any]:
        """Return a bounded evidence payload for ``query``."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise QueryRejected("bad_limit")
        if status not in STATUS_FILTERS:
            raise QueryRejected("bad_status")
        tokens = query_tokens(query)
        limit = max(1, min(limit, MAX_HITS))

        def keep(entry: Entry) -> bool:
            return status in ("any", entry.status)

        def narrow(entries: list[Entry]) -> list[Entry]:
            return [e for e in _most_specific(entries) if keep(e)]

        match, found = "identifier", narrow(self._identifier_stage(tokens))
        if not found:
            match = "phrase"
            found = narrow(self._fts_stage(phrase_expr(tokens)))
        if not found and len(tokens) > 1:
            match = "all_terms"
            found = narrow(self._fts_stage(all_terms_expr(tokens)))
        selected: list[tuple[Entry, str]] = []
        for entry in found:
            if len(selected) >= limit:
                break
            if any(e.cite == entry.cite for e, _ in selected):
                continue
            if entry.superseded_by:
                successor = self._successor(entry)
                if successor is None or len(selected) + 2 > limit:
                    continue  # never return a superseded hit alone
                if not any(e.cite == successor.cite for e, _ in selected):
                    selected.append((successor, "SUCCESSOR"))
            selected.append((entry, ""))
        hits = [self._hit(entry, match, tokens, extra) for entry, extra in selected]
        result = "no_evidence" if not hits else self._result(selected)
        return _bounded(
            {
                "answer_contract_version": ANSWER_CONTRACT_VERSION,
                "result": result,
                "query": " ".join(tokens),
                "scope": {"status": status, "sources": len(self._by_source)},
                "hits": hits,
            }
        )

    def get_section(self, cite: str) -> dict[str, Any]:
        """Return one indexed section by its exact cite key."""
        entry = self._by_cite.get(cite) if isinstance(cite, str) else None
        if entry is None:
            return {
                "answer_contract_version": ANSWER_CONTRACT_VERSION,
                "result": "unknown_cite",
                "hits": [],
            }
        hit = self._hit(entry, "cite", (), "", budget=MAX_SECTION_TEXT)
        return _bounded(
            {
                "answer_contract_version": ANSWER_CONTRACT_VERSION,
                "result": "evidence",
                "hits": [hit],
            }
        )

    @staticmethod
    def _result(selected: Sequence[tuple[Entry, str]]) -> str:
        current = [e for e, _ in selected if not e.superseded_by]
        if not current:
            return "no_evidence"
        best = min(_authority_rank(e.authority) for e in current)
        top = {e.status for e in current if _authority_rank(e.authority) == best}
        return "ambiguous" if len(top) > 1 else "evidence"

    def _hit(
        self,
        entry: Entry,
        match: str,
        tokens: Sequence[str],
        extra: str,
        budget: int = MAX_EXCERPT,
    ) -> dict[str, Any]:
        text, truncated = _excerpt(entry.text, tokens, budget)
        flags = set()
        if extra:
            flags.add(extra)
        if instruction_like(entry.text):
            flags.add("INSTRUCTION_LIKE_TEXT")
        if entry.head_drift:
            flags.add("HEAD_DRIFT")
        if entry.superseded_by or entry.status == "superseded":
            flags.add("SUPERSEDED")
        if entry.pointer_only:
            flags.add("POINTER_ONLY")
        if truncated:
            flags.add("TRUNCATED")
        superseded_by = [s.cite for s in (self._successor(entry),) if s is not None]
        return {
            "cite": entry.cite,
            "path": entry.path,
            "section": {"anchor": entry.anchor, "title": entry.title[:120]},
            "revision": {"blob_sha": entry.blob_sha, "head_drift": entry.head_drift},
            "authority": entry.authority,
            "status": entry.status,
            "superseded_by": superseded_by,
            "match": match,
            "flags": sorted(flags),
            "excerpt": {"untrusted": True, "text": text},
        }


_CANDIDATES = 50


def _most_specific(entries: list[Entry]) -> list[Entry]:
    """Keep ranked order but drop a section whose sub-section also matched.

    A section runs to the next equal-or-higher heading, so a parent's text
    contains its children's. Citing the narrowest matching section keeps
    status overrides (``section_status``) and evidence exact.
    """
    top = entries[:_CANDIDATES]
    return [
        e
        for e in top
        if not any(
            o is not e
            and o.source_id == e.source_id
            and len(o.text) < len(e.text)
            and o.text in e.text
            for o in top
        )
    ]


def _excerpt(text: str, tokens: Sequence[str], budget: int) -> tuple[str, bool]:
    if len(text) <= budget:
        return text, False
    folded = text.casefold()
    positions = [folded.find(t.casefold()) for t in tokens]
    first = min((p for p in positions if p >= 0), default=0)
    start = max(0, min(first - budget // 4, len(text) - budget))
    return text[start : start + budget], True


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def _bounded(payload: dict[str, Any]) -> dict[str, Any]:
    """Shrink excerpts (then drop trailing hits) until within the payload cap."""
    hits = payload["hits"]
    while _size(payload) > MAX_PAYLOAD and hits:
        longest = max(hits, key=lambda h: len(h["excerpt"]["text"]))
        current = longest["excerpt"]["text"]
        if len(current) > 120:
            over = _size(payload) - MAX_PAYLOAD
            cut = max(len(current) - over - 1, 120)
            longest["excerpt"]["text"] = current[:cut]
            if "TRUNCATED" not in longest["flags"]:
                longest["flags"] = sorted({*longest["flags"], "TRUNCATED"})
        else:
            hits.pop()
    if not hits and payload["result"] == "evidence":
        payload["result"] = "no_evidence"
    return payload
