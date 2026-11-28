"""Field-level evidence projections and a sentinel scanner (#1339 T03).

Hermes never sees a raw artifact. It sees an :class:`EvidenceProjection`:
opaque run and artifact IDs, a capability status, finding codes,
``[[metric:run:artifact:field]]`` references and bucketed aggregates. Exact
amounts, quantities, account identities and names cannot be represented in
the model, so they cannot cross.

Every projection request goes through a :class:`~.access.PolicyGate` as
``evidence_projection_read`` on ``evidence.projection``. A field outside the
grant, or a request that combines a weight, a ticker and a date (enough to
re-identify a holding), fails closed with :class:`ProjectionDenied`.

The module also carries the sentinel scanner used by real-path checks::

    ... | python -m openbb_agents.hermes_integration.projection --scan-stdin

It reports labels only (never the matched text) and exits 1 on any hit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .access import (
    EVIDENCE_PROJECTION_FIELDS,
    AccessRequest,
    PolicyGate,
)

# Synthetic private-shaped sentinels shared by tests and real-path probes.
SENTINELS: Mapping[str, str] = {
    "account": "ZZ-000000001",
    "amount": "$4,242,424.42",
    "name": "Sentinel Q. Owner",
}
SENTINEL_MARKER = "SENTINEL"

# Requesting one field from each class re-identifies a holding.
REIDENTIFYING_CLASSES: tuple[frozenset[str], ...] = (
    frozenset({"weight", "weight_pct", "weight_bucket", "allocation_pct"}),
    frozenset({"ticker", "symbol", "cusip", "isin", "security_id"}),
    frozenset({"as_of", "date", "trade_date", "settle_date", "timestamp"}),
)

PCT_BUCKETS = ("0-5%", "5-10%", "10-25%", "25-50%", "50-100%")
COUNT_BUCKETS = ("0", "1-9", "10-99", "100-999", "1000+")
Bucket = Literal[
    "0-5%",
    "5-10%",
    "10-25%",
    "25-50%",
    "50-100%",
    "0",
    "1-9",
    "10-99",
    "100-999",
    "1000+",
    "out_of_range",
]

_OPAQUE = r"[a-z]{3}_[0-9a-f]{16}"
_FIELD = r"[a-z][a-z0-9_]{0,63}"
OPAQUE_ID_RE = re.compile(rf"^{_OPAQUE}$")
FIELD_RE = re.compile(rf"^{_FIELD}$")
METRIC_REF_RE = re.compile(rf"^\[\[metric:{_OPAQUE}:{_OPAQUE}:{_FIELD}\]\]$")
FINDING_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

OPERATION = "evidence_projection_read"
SCOPE = "evidence.projection"


class ProjectionDenied(Exception):
    """A projection request failed closed; ``reason`` is a fixed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EvidenceProjection(BaseModel):
    """What Hermes may see about one evidence artifact (no raw values)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str | None = None
    artifact_id: str | None = None
    capability_status: Literal["granted", "denied", "unavailable"] | None = None
    finding_codes: tuple[str, ...] = ()
    metric_refs: tuple[str, ...] = ()
    aggregate_buckets: dict[str, Bucket] = Field(default_factory=dict)
    as_of: dt.date | None = None

    @field_validator("run_id", "artifact_id")
    @classmethod
    def _opaque(cls, value: str | None) -> str | None:
        if value is not None and not OPAQUE_ID_RE.match(value):
            raise ValueError("ids must be opaque")
        return value

    @field_validator("finding_codes")
    @classmethod
    def _codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not FINDING_CODE_RE.match(code) for code in value):
            raise ValueError("finding codes must be fixed codes")
        return value

    @field_validator("metric_refs")
    @classmethod
    def _refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not METRIC_REF_RE.match(ref) for ref in value):
            raise ValueError("metric refs must be [[metric:run:artifact:field]]")
        return value

    @field_validator("aggregate_buckets")
    @classmethod
    def _bucket_names(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not FIELD_RE.match(name) for name in value):
            raise ValueError("aggregate names must be field names")
        return value


def opaque_id(prefix: str, raw: object) -> str:
    """Return a stable opaque ID (``prefix_`` + 16 hex) for a raw identifier."""
    digest = hashlib.sha256(f"{prefix}\x00{raw}".encode()).hexdigest()
    return f"{prefix}_{digest[:16]}"


def bucket(value: object) -> str:
    """Map a number to a coarse bucket; fractions in [0, 1] are percentages."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "out_of_range"
    if value < 0:
        return "out_of_range"
    if isinstance(value, float) and value <= 1:
        for upper, label in zip((0.05, 0.10, 0.25, 0.50, 1.0), PCT_BUCKETS):
            if value <= upper:
                return label
    if value == 0:
        return "0"
    for upper, label in zip((9, 99, 999), COUNT_BUCKETS[1:4]):
        if value <= upper:
            return label
    return COUNT_BUCKETS[-1]


def is_reidentifying(fields: Iterable[str]) -> bool:
    """Return True when ``fields`` touch every re-identifying class at once."""
    requested = set(fields)
    return all(requested & cls for cls in REIDENTIFYING_CLASSES)


def project(
    artifact: Mapping[str, Any],
    *,
    gate: PolicyGate,
    principal: str,
    fields: Iterable[str],
) -> EvidenceProjection:
    """Project ``artifact`` onto the requested, granted fields.

    Raises :class:`ProjectionDenied` when the request combines re-identifying
    fields or the gate refuses it. Raw values never reach the result: IDs are
    hashed, findings are kept only when they are fixed codes, metrics become
    references and aggregates become buckets.
    """
    requested = frozenset(fields)
    if is_reidentifying(requested):
        raise ProjectionDenied("reidentifying_combination")
    decision = gate.decide(
        AccessRequest(
            principal=principal, operation=OPERATION, scope=SCOPE, fields=requested
        )
    )
    if not decision.allowed:
        raise ProjectionDenied(decision.reason)
    if not requested <= EVIDENCE_PROJECTION_FIELDS:
        raise ProjectionDenied("field_not_projectable")

    run = opaque_id("run", artifact.get("run_id"))
    art = opaque_id("art", artifact.get("artifact_id"))
    values: dict[str, Any] = {}
    if "run_id" in requested:
        values["run_id"] = run
    if "artifact_id" in requested:
        values["artifact_id"] = art
    if "capability_status" in requested:
        status = artifact.get("capability_status")
        values["capability_status"] = (
            status if status in ("granted", "denied", "unavailable") else "unavailable"
        )
    if "finding_codes" in requested:
        values["finding_codes"] = tuple(
            code
            for code in artifact.get("findings") or ()
            if isinstance(code, str) and FINDING_CODE_RE.match(code)
        )
    if "metric_refs" in requested:
        values["metric_refs"] = tuple(
            f"[[metric:{run}:{art}:{name}]]"
            for name in sorted(artifact.get("metrics") or {})
            if isinstance(name, str) and FIELD_RE.match(name)
        )
    if "aggregate_buckets" in requested:
        values["aggregate_buckets"] = {
            name: bucket(value)
            for name, value in sorted((artifact.get("aggregates") or {}).items())
            if isinstance(name, str) and FIELD_RE.match(name)
        }
    if "as_of" in requested:
        values["as_of"] = _as_date(artifact.get("as_of"))
    return EvidenceProjection(**values)


def _as_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# --- sentinel scanner ------------------------------------------------------------

_ALLOWED_SECRET_VALUES = frozenset({"present", "absent", "null"})
# A key is secret-shaped when one of its ``_``/``.``/``-`` segments is one of
# these words, so ``api_key`` and ``DB_PASSWORD`` match but ``max_tokens`` and
# ``completion_tokens`` (usage counters) do not.
_SECRET_WORDS = frozenset({"key", "apikey", "token", "secret", "password"})
_SECRET_KV_RE = re.compile(r"""(?ix)
    ["']?(?P<key>[a-z0-9_.-]*(?:key|token|secret|password)[a-z0-9_.-]*)["']?
    \s*[:=]\s*
    (?P<value>"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}\]]+)
    """)


def scan_text(text: str) -> list[str]:
    """Return sorted hit labels for ``text`` (labels only, never the match)."""
    hits: set[str] = set()
    for label, value in SENTINELS.items():
        if value in text:
            hits.add(f"sentinel:{label}")
    if SENTINEL_MARKER in text:
        hits.add("marker:SENTINEL")
    for match in _SECRET_KV_RE.finditer(text):
        segments = re.split(r"[_.-]", match.group("key").lower())
        if not _SECRET_WORDS.intersection(segments):
            continue
        value = match.group("value").strip("\"'").strip().lower()
        if value not in _ALLOWED_SECRET_VALUES:
            key = re.sub(r"[^a-z0-9_.-]", "", match.group("key").lower())[:64]
            hits.add(f"secret_value:{key}")
    return sorted(hits)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--scan-stdin`` scans stdin; exit 0 clean, 1 on a hit, 3 usage."""
    parser = argparse.ArgumentParser(prog="projection")
    parser.add_argument("--scan-stdin", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 3
    if not args.scan_stdin:
        sys.stderr.write("projection: --scan-stdin is required\n")
        return 3
    hits = scan_text(sys.stdin.read())
    for label in hits:
        sys.stdout.write(f"scan_hit label={label}\n")
    sys.stdout.write(f"scan_result hits={len(hits)}\n")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
