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

Names that reach Hermes come from closed vocabularies (:data:`FINDING_CODES`,
:data:`AGGREGATE_NAMES`, :data:`METRIC_NAMES`). A producer-supplied code or
name outside them (``TOP_HOLDING_NVDA``, an aggregate named after a ticker, a
digit-bearing code) is dropped and flagged by the boolean ``unvetted_dropped`` (never a count: a
producer keying by ticker would make it the exact holding count), never
passed. Opaque IDs are keyed HMAC-SHA256 digests; the key file is named by
:data:`PROJECTION_KEY_ENV` and must live outside any git work tree. Without a
usable key, :func:`project` fails closed (``projection_key_unconfigured``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import math
import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
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
COUNT_AGGREGATES: frozenset[str] = frozenset({"position_count", "sector_count"})
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

# Closed vocabularies: the only finding codes and names that may reach Hermes.
# Producer-supplied codes or names outside them are dropped and counted.
FINDING_CODES: frozenset[str] = frozenset(
    {
        "CAPABILITY_DENIED",
        "CAPABILITY_UNAVAILABLE",
        "CASH_HIGH",
        "CASH_LOW",
        "CONCENTRATION_HIGH",
        "CONCENTRATION_MODERATE",
        "DATA_INCOMPLETE",
        "DATA_STALE",
        "DIVERSIFICATION_LOW",
        "DRAWDOWN_HIGH",
        "SECTOR_CONCENTRATION_HIGH",
        "VOLATILITY_HIGH",
    }
)
AGGREGATE_NAMES: frozenset[str] = frozenset(
    {
        "cash_share",
        "equity_share",
        "fixed_income_share",
        "position_count",
        "sector_count",
        "top_weight",
        "total_value",
    }
)
METRIC_NAMES: frozenset[str] = frozenset(
    {
        "beta",
        "cash_share",
        "market_value",
        "max_drawdown",
        "position_count",
        "realized_gain",
        "sharpe_ratio",
        "top_weight",
        "total_value",
        "unrealized_gain",
        "volatility",
    }
)

_OPAQUE = r"[a-z]{3}_[0-9a-f]{16}"
_NAME = r"[a-z]+(?:_[a-z]+)*"
OPAQUE_ID_RE = re.compile(rf"^{_OPAQUE}$")
NAME_RE = re.compile(rf"^{_NAME}$")
METRIC_REF_RE = re.compile(rf"^\[\[metric:{_OPAQUE}:{_OPAQUE}:(?P<name>{_NAME})\]\]$")
FINDING_CODE_RE = re.compile(r"^[A-Z]+(?:_[A-Z]+)*$")
# A name segment from this class names a security, so it never crosses.
_SYMBOL_WORDS = frozenset({"ticker", "symbol", "cusip", "isin", "sedol", "figi"})

PROJECTION_KEY_ENV = "HFP_PROJECTION_ID_KEY"
MIN_KEY_BYTES = 32

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
    unvetted_dropped: bool = False

    @field_validator("run_id", "artifact_id")
    @classmethod
    def _opaque(cls, value: str | None) -> str | None:
        if value is not None and not OPAQUE_ID_RE.match(value):
            raise ValueError("ids must be opaque")
        return value

    @field_validator("finding_codes")
    @classmethod
    def _codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not vetted_code(code) for code in value):
            raise ValueError("finding codes must come from FINDING_CODES")
        return value

    @field_validator("metric_refs")
    @classmethod
    def _refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            match = METRIC_REF_RE.match(ref)
            if not match or not vetted_name(match.group("name"), METRIC_NAMES):
                raise ValueError("metric refs must be [[metric:run:artifact:name]]")
        return value

    @field_validator("aggregate_buckets")
    @classmethod
    def _bucket_names(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not vetted_name(name, AGGREGATE_NAMES) for name in value):
            raise ValueError("aggregate names must come from AGGREGATE_NAMES")
        return value


def vetted_code(code: object) -> bool:
    """Return True for a finding code in :data:`FINDING_CODES` with no digits."""
    return (
        isinstance(code, str)
        and code in FINDING_CODES
        and bool(FINDING_CODE_RE.match(code))
        and not _SYMBOL_WORDS.intersection(code.lower().split("_"))
    )


def vetted_name(name: object, vocabulary: frozenset[str]) -> bool:
    """Return True for a name in ``vocabulary`` with no digits or symbol words."""
    return (
        isinstance(name, str)
        and name in vocabulary
        and bool(NAME_RE.match(name))
        and not _SYMBOL_WORDS.intersection(name.split("_"))
    )


def _in_git_work_tree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.parents)


def load_projection_key() -> bytes:
    """Read the per-deployment ID key from the file named by the env var.

    Raises :class:`ProjectionDenied` (``projection_key_unconfigured``) when the
    variable is unset, the path is relative or unreadable, or the key is shorter
    than :data:`MIN_KEY_BYTES`; ``projection_key_in_repo`` when the file sits in
    a git work tree. There is no unkeyed fallback.
    """
    raw = os.environ.get(PROJECTION_KEY_ENV, "").strip()
    if not raw:
        raise ProjectionDenied("projection_key_unconfigured")
    path = Path(raw)
    if not path.is_absolute():
        raise ProjectionDenied("projection_key_unconfigured")
    try:
        resolved = path.resolve(strict=True)
        key = resolved.read_bytes().strip()
    except OSError as exc:
        raise ProjectionDenied("projection_key_unconfigured") from exc
    if _in_git_work_tree(resolved):
        raise ProjectionDenied("projection_key_in_repo")
    if len(key) < MIN_KEY_BYTES:
        raise ProjectionDenied("projection_key_unconfigured")
    return key


def opaque_id(prefix: str, raw: object, key: bytes) -> str:
    """Return a keyed opaque ID (``prefix_`` + 16 hex of HMAC-SHA256)."""
    if len(key) < MIN_KEY_BYTES:
        raise ProjectionDenied("projection_key_unconfigured")
    digest = hmac.new(key, f"{prefix}\x00{raw}".encode(), hashlib.sha256)
    return f"{prefix}_{digest.hexdigest()[:16]}"


def bucket(value: object, *, count: bool = False) -> str:
    """Map a number to a coarse bucket; fractions in [0, 1] are percentages.

    NaN, infinities, negatives and non-numbers are ``out_of_range``. With
    ``count=True`` (names in :data:`COUNT_AGGREGATES`) the value must be a whole
    number, even when passed as an integral float, and always uses the count
    buckets; a fractional count is ``out_of_range``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "out_of_range"
    if isinstance(value, float) and not math.isfinite(value):
        return "out_of_range"
    if value < 0:
        return "out_of_range"
    if count and value != int(value):
        return "out_of_range"
    if not count and isinstance(value, float) and value <= 1:
        for upper, label in zip((0.05, 0.10, 0.25, 0.50, 1.0), PCT_BUCKETS):
            if value <= upper:
                return label
    if value == 0:
        return "0"
    for upper, label in zip((9, 99, 999), COUNT_BUCKETS[1:4]):
        if value <= upper:
            return label
    return COUNT_BUCKETS[-1]


def _touches(name: str, cls: frozenset[str]) -> bool:
    return name in cls or bool(cls.intersection(name.lower().split("_")))


def is_reidentifying(fields: Iterable[str]) -> bool:
    """Return True when ``fields`` touch every re-identifying class at once.

    A name touches a class when it is a member or one of its ``_`` segments is
    (``top_weight`` touches the weight class).
    """
    names = [name for name in fields if isinstance(name, str)]
    return all(
        any(_touches(name, cls) for name in names) for cls in REIDENTIFYING_CLASSES
    )


def _vetted(items: Iterable[object], ok: Any) -> tuple[list[str], int]:
    kept: set[str] = set()
    dropped = 0
    for item in items:
        if ok(item):
            kept.add(str(item))
        else:
            dropped += 1
    return sorted(kept), dropped


def project(
    artifact: Mapping[str, Any],
    *,
    gate: PolicyGate,
    principal: str,
    fields: Iterable[str],
) -> EvidenceProjection:
    """Project ``artifact`` onto the requested, granted fields.

    Raises :class:`ProjectionDenied` when the request (or the names it would
    emit) combines re-identifying classes, the gate refuses it, or no ID key is
    configured. Raw values never reach the result: IDs are keyed HMACs,
    finding codes and metric / aggregate names come only from the closed
    vocabularies (anything else is dropped and flagged by
    ``unvetted_dropped``), metrics become references and aggregates buckets.
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
    key = load_projection_key()

    run = opaque_id("run", artifact.get("run_id"), key)
    art = opaque_id("art", artifact.get("artifact_id"), key)
    values: dict[str, Any] = {}
    dropped = 0
    emitted: set[str] = set(requested)
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
        codes, n = _vetted(artifact.get("findings") or (), vetted_code)
        values["finding_codes"] = tuple(codes)
        emitted.update(code.lower() for code in codes)
        dropped += n
    if "metric_refs" in requested:
        names, n = _vetted(
            artifact.get("metrics") or {}, lambda m: vetted_name(m, METRIC_NAMES)
        )
        values["metric_refs"] = tuple(f"[[metric:{run}:{art}:{m}]]" for m in names)
        emitted.update(names)
        dropped += n
    if "aggregate_buckets" in requested:
        aggregates = artifact.get("aggregates") or {}
        names, n = _vetted(aggregates, lambda a: vetted_name(a, AGGREGATE_NAMES))
        values["aggregate_buckets"] = {
            a: bucket(aggregates[a], count=a in COUNT_AGGREGATES) for a in names
        }
        emitted.update(names)
        dropped += n
    if "as_of" in requested:
        values["as_of"] = _as_date(artifact.get("as_of"))
    if is_reidentifying(emitted):
        raise ProjectionDenied("reidentifying_combination")
    values["unvetted_dropped"] = dropped > 0
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
