"""Collect runtime facts for ``describe``. Imports nautilus_trader lazily."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from collections.abc import Callable
from importlib import metadata
from typing import Any

from .protocol import DescribeFacts, ErrorCode, LicenseFile, ProtocolError

# Attribute names read from the installed release (seam-contract test pins these).
PRECISION_MODULE = "nautilus_trader.model.objects"
PRECISION_ATTRS = ("HIGH_PRECISION", "FIXED_PRECISION")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wheel_tag(dist: metadata.Distribution) -> str:
    text = dist.read_text("WHEEL") or ""
    tags = [
        ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("Tag:")
    ]
    if not tags:
        raise ProtocolError(
            ErrorCode.MODULE_ORIGIN, "installed wheel has no Tag metadata"
        )
    return tags[0]


def _wheel_sha256(dist: metadata.Distribution) -> str | None:
    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    try:
        h = json.loads(raw).get("archive_info", {}).get("hash", "")
    except ValueError:
        return None
    algo, _, digest = h.partition("=")
    return digest if algo == "sha256" and len(digest) == 64 else None


def _license_files(dist: metadata.Distribution) -> list[LicenseFile]:
    out = []
    for f in dist.files or []:
        name = f.name.upper()
        if f.parent.name.endswith(".dist-info") and (
            name.startswith("LICENSE") or name.startswith("COPYING")
        ):
            out.append(LicenseFile(name=f.name, sha256=_sha256(f.read_binary())))
    return sorted(out, key=lambda x: (x.name, x.sha256))


def _inside_prefix(path: str) -> bool:
    real, prefix = os.path.realpath(path), os.path.realpath(sys.prefix)
    return os.path.commonpath([real, prefix]) == prefix


def collect_facts(
    _body: dict[str, Any] | None = None,
    import_module: Callable[[str], Any] = importlib.import_module,
    distribution: Callable[[str], metadata.Distribution] = metadata.distribution,
) -> dict[str, Any]:
    """Return ``DescribeFacts`` as a dict, or raise ``ProtocolError``."""
    try:
        nt = import_module("nautilus_trader")
        objects = import_module(PRECISION_MODULE)
        dist = distribution("nautilus_trader")
    except (ImportError, metadata.PackageNotFoundError) as exc:
        raise ProtocolError(
            ErrorCode.MODULE_ORIGIN, "nautilus_trader is not importable"
        ) from exc
    try:
        high, fixed = (getattr(objects, a) for a in PRECISION_ATTRS)
    except AttributeError as exc:
        raise ProtocolError(
            ErrorCode.ABI, "precision constants not found in installed release"
        ) from exc
    wheel_tag = _wheel_tag(dist)
    vi = sys.version_info
    facts = DescribeFacts(
        nautilus_version=str(getattr(nt, "__version__", dist.version)),
        python_version=f"{vi.major}.{vi.minor}.{vi.micro}",
        python_tag=f"cp{vi.major}{vi.minor}",
        wheel_tag=wheel_tag,
        platform_tag=wheel_tag.rsplit("-", 1)[-1],
        high_precision=bool(high),
        fixed_precision=int(fixed),
        module_origin_in_prefix=_inside_prefix(nt.__file__),
        wheel_sha256=_wheel_sha256(dist),
        license_files=_license_files(dist),
    )
    return facts.model_dump(mode="json")
