"""Ordered target and universe admission for guarded price warming (#1344).

Runs before any database or FMP access. The first failing layer wins and is
reported with #1338's :class:`FailedLayer` vocabulary plus stable finding codes;
no exception text, secret, URL or symbol ever appears in a finding.

Order:

1. ``PROCESS`` / ``ABI`` -- the running interpreter belongs to the map's pinned
   venv; ``pyvenv.cfg`` matches the running minor and the profile's python pin.
2. ``MODULE_ORIGIN`` -- ``portfolio_utils``, ``openbb_fmp_cached`` and
   ``openbb_agents`` resolve under the approved source root; that checkout's
   HEAD equals ``source_sha`` and is clean.
3. ``CONFIG`` -- no ``FMP_CACHE_TEST_MODE``; auto-create stays off; the target is
   a safe identifier; DB-related environment is identical before and after the
   warmer import (its module-level ``load_dotenv(override=True)``).
4. ``DATABASE`` -- the old copy is never a target; target class policy
   (disposable pattern / attested production); target equals the profile pin;
   the settings resolve to the target (``db_category == "expected"``). Execute
   mode then probes ``SELECT DATABASE()`` on the warmer's own connection path.
5. Universe -- a private ticker-only manifest (expiry, digest, limits, symbol
   shape, CUSIPs, ``SKIP_SYMBOLS``, loud empty). The admitted symbols are passed
   to the warmer as ``symbols=`` so the portfolio-table selector never runs.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import platform
import re
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from portfolio_utils.fmp_sync.budget import ACCOUNT_LABEL_PATTERN

logger = logging.getLogger(__name__)

OLD_COPY_DB = "openbb_fmp_cache"
LIVE_DB = "openbb_fmp_cache_test"
PROTECTED_DATABASES = frozenset({OLD_COPY_DB, LIVE_DB})
DISPOSABLE_PATTERN = re.compile(r"^obb_disposable_[a-z0-9]{8,32}$")
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
GLOBAL_SYMBOL_CAP = 500
WARMER_MODULE = "portfolio_utils.fetch_position_history"
ORIGIN_MODULES = ("portfolio_utils", "openbb_fmp_cached", "openbb_agents")
_DB_ENV_PREFIXES = ("DB_", "MYSQL_", "FMP_CACHE_")
# Transport and state keys a warmer import or .env must not change either.
# FMP_API_KEY / FMP_CACHED_API_KEY are compared by presence + SHA-256 only (see
# _db_env); FMP_CACHED_API_KEY escapes the FMP_CACHE_ prefix, so it is listed.
_DRIFT_KEYS = frozenset(
    {
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "FMP_API_KEY",
        "FMP_CACHED_API_KEY",
        "FMP_SYNC_STATE_ROOT",
    }
)
# Transport-trust and state-location keys a ``.env`` may never newly supply
# (the FMP keys are excluded: a ``.env`` may legitimately provide them).
_TRANSPORT_KEYS = _DRIFT_KEYS - {"FMP_API_KEY", "FMP_CACHED_API_KEY"}
_AUTO_CREATE = "FMP_CACHE_AUTO_CREATE_DB"
EXIT_ADMITTED = 0
EXIT_POLICY = 40
EXIT_INFRA = 30
_MYSQL_DOWN = frozenset({2002, 2003, 2006, 2013, 2055})

TargetClass = Literal["disposable", "production"]
Mode = Literal["dry_run", "execute"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeploymentMap(_Strict):
    """Private deployment map (outside git). Paths are host-local, never logged."""

    schema_version: Literal[1]
    source_root: str
    source_sha: str = Field(min_length=7)
    interpreter: str  # venv directory
    target: str
    target_class: TargetClass
    profile_path: str
    settings_path: str | None = None
    ops_attest_ref: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_path: str | None = None
    legacy_selector: bool = False
    state_root: str | None = None
    # Consumed by later tasks (budget, render); validated here so the map is one schema.
    limits: dict[str, int] | None = None
    account_label: str | None = Field(default=None, pattern=ACCOUNT_LABEL_PATTERN)
    hermes_timezone: str | None = None
    # Python minor of the sync process itself (e.g. "3.12"); separate from the
    # Hermes runtime pin in the profile. When set, admission checks the sync
    # interpreter against it instead of the profile pin.
    sync_python: str | None = Field(default=None, pattern=r"^\d+\.\d+$")
    # Transport allowlist for the budget guard (FMP host names, loopback MySQL port).
    fmp_hosts: list[str] | None = None
    mysql_port: int | None = Field(default=None, gt=0, lt=65536)
    # Readiness / audit policy (#1345); validated by ``readiness.ReadinessPolicy``.
    readiness: dict[str, Any] | None = None
    # Backup/binlog/disk paths for ops observability (#1345); private, never logged.
    # Validated by ``ops_observe.OpsPolicy``.
    ops: dict[str, Any] | None = None


class UniverseManifest(_Strict):
    """Private ticker-only universe manifest."""

    schema_version: Literal[1]
    manifest_id: str = Field(min_length=1, max_length=128)
    source: str
    accepted_at: AwareDatetime
    expires_at: AwareDatetime
    symbol_limit: int = Field(gt=0)
    symbols: list[str]
    benchmarks: list[str] = Field(default_factory=list)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Admission:
    """Result of :func:`admit`. Carries codes and counts only."""

    admitted: bool
    code: str
    failed_layer: str | None = None
    findings: tuple[str, ...] = ()
    target: str | None = None
    target_class: str | None = None
    db_category: str | None = None
    manifest_id: str | None = None
    manifest_sha256: str | None = None
    symbols: tuple[str, ...] | None = ()
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """Business exit code: 0 admitted, 30 infra, 40 policy/config block."""
        if self.admitted:
            return EXIT_ADMITTED
        return EXIT_INFRA if self.code == "FAILED_INFRA" else EXIT_POLICY


class _Blocked(Exception):
    def __init__(self, code: str, layer: str | None, *findings: str):
        super().__init__(code)
        self.code = code
        self.layer = layer
        self.findings = findings
        self.category: str | None = None


def load_map(path: Path) -> DeploymentMap:
    """Load a deployment map; raises ``ValueError`` (never echoing contents)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return DeploymentMap.model_validate(data)
    except (OSError, ValueError, ValidationError) as exc:
        raise ValueError("deployment map unreadable or invalid") from exc


def manifest_digest(symbols: Sequence[str], benchmarks: Sequence[str] = ()) -> str:
    """SHA-256 over the canonical sorted symbol and benchmark lists."""
    canonical = json.dumps(
        {"benchmarks": sorted(set(benchmarks)), "symbols": sorted(set(symbols))},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_hermes() -> SimpleNamespace:
    """Lazy import of #1338's hermes_integration (D9). Raises ``ImportError``."""
    # pylint: disable=import-outside-toplevel
    from openbb_agents.hermes_integration import models, profile, provenance

    return SimpleNamespace(
        FailedLayer=models.FailedLayer,
        provenance=provenance,
        load_profile=profile.load_profile,
    )


def _db_env(env: Mapping[str, str]) -> dict[str, str]:
    snap = {
        k: v
        for k, v in env.items()
        if k.upper().startswith(_DB_ENV_PREFIXES) or k.upper() in _DRIFT_KEYS
    }
    # The warmer's import does setdefault(FMP_CACHE_AUTO_CREATE_DB, "false").
    if snap.get(_AUTO_CREATE, "false").lower() == "false":
        snap.pop(_AUTO_CREATE, None)
    # Presence + SHA-256 only: the snapshot never holds a credential value.
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in snap.items()}


def _within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).resolve().relative_to(
            Path(os.path.abspath(root)).resolve()
        )
    except ValueError:
        return False
    return True


def _default_module_origin(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin)


def _default_dotenv_path() -> Path | None:
    spec = importlib.util.find_spec("portfolio_utils")
    if spec is None or not spec.origin:
        return None
    # Mirrors fetch_position_history.PROJECT_ROOT / ".env".
    return Path(spec.origin).resolve().parent.parent / ".env"


def _default_connect(target: str) -> Any:
    warmer = importlib.import_module(WARMER_MODULE)
    return warmer._connect(target)  # pylint: disable=protected-access


# ------------------------------------------------------------------ layers


def _check_process(dmap, profile, layers, prov, executable: str) -> None:
    venv = Path(dmap.interpreter)
    if not _within(Path(executable), venv):
        raise _Blocked(
            "BLOCKED_PROCESS", layers.PROCESS.value, "INTERPRETER_NOT_PINNED"
        )
    recorded = prov.read_pyvenv_version(venv)
    if recorded is None:
        raise _Blocked("BLOCKED_ABI", layers.ABI.value, "PYVENV_UNREADABLE")
    running = platform.python_version()
    if recorded.split(".")[:2] != running.split(".")[:2]:
        raise _Blocked("BLOCKED_ABI", layers.ABI.value, "PYVENV_RUNNING_MISMATCH")
    if dmap.sync_python:
        if ".".join(running.split(".")[:2]) != dmap.sync_python:
            raise _Blocked("BLOCKED_ABI", layers.ABI.value, "SYNC_PYTHON_MISMATCH")
        return
    if not prov.python_matches(
        recorded, profile.python.requires, profile.python.supported
    ):
        raise _Blocked("BLOCKED_ABI", layers.ABI.value, "PYTHON_PIN_MISMATCH")


def _check_origins(dmap, layers, module_origin_fn, git_facts_fn) -> None:
    root = Path(dmap.source_root)
    for name in ORIGIN_MODULES:
        origin = module_origin_fn(name)
        if origin is None or not _within(Path(origin), root):
            raise _Blocked(
                "BLOCKED_MODULE_ORIGIN",
                layers.MODULE_ORIGIN.value,
                f"MODULE_OUTSIDE_SOURCE_ROOT:{name}",
            )
    facts = git_facts_fn(root)
    if not facts.sha or not facts.sha.lower().startswith(dmap.source_sha.lower()):
        raise _Blocked(
            "BLOCKED_MODULE_ORIGIN", layers.MODULE_ORIGIN.value, "SOURCE_SHA_MISMATCH"
        )
    if facts.dirty is not False:
        raise _Blocked(
            "BLOCKED_MODULE_ORIGIN", layers.MODULE_ORIGIN.value, "SOURCE_DIRTY"
        )


def _check_flags(env: Mapping[str, str], config: str) -> None:
    if env.get("FMP_CACHE_TEST_MODE", "false").strip().lower() not in (
        "",
        "false",
        "0",
    ):
        raise _Blocked("BLOCKED_CONFIG", config, "TEST_MODE_ENV")
    if env.get(_AUTO_CREATE, "false").strip().lower() != "false":
        raise _Blocked("BLOCKED_CONFIG", config, "AUTO_CREATE_DB_ENABLED")


def _overridden(before: Mapping[str, str], after: Mapping[str, str]) -> bool:
    """Drift = a key present before whose hash changed or vanished (an override).

    Keys that only appear afterwards were supplied by ``.env`` (the cron child
    starts from a stripped environment); the resolved target is enforced
    separately by the database layer.
    """
    return any(after.get(k) != v for k, v in before.items())


def _newly_transport(before: Mapping[str, str], env: Mapping[str, str]) -> bool:
    """Report a transport-trust or state-location key absent before but present now."""
    return any(k.upper() in _TRANSPORT_KEYS and k not in before for k in env)


def _check_config(  # pylint: disable=too-many-arguments
    dmap, layers, env, *, before, dotenv_path, import_warmer_fn
) -> None:
    config = layers.CONFIG.value
    _check_flags(env, config)
    if dotenv_path is not None and Path(dotenv_path).is_file():
        from dotenv import dotenv_values  # pylint: disable=import-outside-toplevel

        loaded = {k: v or "" for k, v in dotenv_values(dotenv_path).items()}
        # Keys the .env only supplies are allowed; the unsafe flags are judged on
        # the merged view and the resolved target is checked after loading.
        _check_flags({**env, **loaded}, config)
        # Compare only keys both sides hold: the .env need not repeat every key the
        # cron child already carries (e.g. FMP_SYNC_STATE_ROOT).
        if any(k in before and before[k] != v for k, v in _db_env(loaded).items()):
            raise _Blocked("BLOCKED_CONFIG", config, "DOTENV_DRIFT")
        if _newly_transport(before, loaded):
            raise _Blocked("BLOCKED_CONFIG", config, "DOTENV_TRANSPORT_KEY")
    try:
        import_warmer_fn()
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        raise _Blocked(
            "BLOCKED_MODULE_ORIGIN", layers.MODULE_ORIGIN.value, "WARMER_IMPORT_FAILED"
        ) from exc
    if _overridden(before, _db_env(env)):
        raise _Blocked("BLOCKED_CONFIG", config, "DOTENV_DRIFT")
    if _newly_transport(before, env):
        raise _Blocked("BLOCKED_CONFIG", config, "DOTENV_TRANSPORT_KEY")
    _check_flags(env, config)
    # pylint: disable-next=import-outside-toplevel
    from openbb_fmp_cached.utils.database import safe_identifier

    try:
        safe_identifier(dmap.target)
    except ValueError as exc:
        raise _Blocked("BLOCKED_CONFIG", config, "INVALID_TARGET_IDENTIFIER") from exc


def _check_database(  # pylint: disable=too-many-arguments
    dmap, profile, layers, env, *, requested_class, prov
) -> str:
    database = layers.DATABASE.value
    target = dmap.target.lower()
    if target == OLD_COPY_DB:
        raise _Blocked("BLOCKED_DATABASE", database, "TARGET_OLD_COPY")
    if requested_class != dmap.target_class:
        raise _Blocked("BLOCKED_POLICY", layers.CONFIG.value, "TARGET_CLASS_MISMATCH")
    if dmap.target_class == "disposable":
        if target in PROTECTED_DATABASES:
            raise _Blocked(
                "BLOCKED_DATABASE", database, "TARGET_PROTECTED_IN_DISPOSABLE"
            )
        if not DISPOSABLE_PATTERN.match(target):
            raise _Blocked("BLOCKED_DATABASE", database, "TARGET_NOT_DISPOSABLE")
    elif not dmap.ops_attest_ref:
        raise _Blocked("BLOCKED_POLICY", layers.CONFIG.value, "OPS_ATTEST_MISSING")
    if profile.database.expected.lower() != target:
        raise _Blocked("BLOCKED_DATABASE", database, "PROFILE_TARGET_MISMATCH")
    settings = (
        Path(dmap.settings_path) if dmap.settings_path else prov.default_settings_path()
    )
    resolved = prov.resolve_fmp_cached_database(settings, env)
    category = prov.db_category(resolved.database.lower(), target)
    if category != "expected":
        exc = _Blocked(
            "BLOCKED_DATABASE", database, f"RESOLVED_DATABASE_{category.upper()}"
        )
        exc.category = category
        raise exc
    return category


def _check_disk(dmap: DeploymentMap, layers, disk_usage_fn) -> None:
    """Execute admission only: a measurably CRITICAL data volume blocks (reads stay allowed)."""
    if not dmap.ops:
        return
    # pylint: disable-next=import-outside-toplevel
    from portfolio_utils.fmp_sync import ops_observe

    try:
        policy = ops_observe.OpsPolicy(**dmap.ops)
    except ValueError as exc:
        raise _Blocked(
            "BLOCKED_CONFIG", layers.CONFIG.value, "OPS_CONFIG_INVALID"
        ) from exc
    if ops_observe.data_volume_critical(
        policy, *([disk_usage_fn] if disk_usage_fn else [])
    ):
        raise _Blocked("BLOCKED_POLICY", layers.CONFIG.value, "DISK_CRITICAL")


def _probe_session(target: str, layers, connect_fn) -> None:
    database = layers.DATABASE.value
    conn = None
    try:
        conn = connect_fn()
        cursor = conn.cursor()
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
        cursor.close()
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], int) and args[0] in _MYSQL_DOWN:
            raise _Blocked("FAILED_INFRA", database, "MYSQL_UNAVAILABLE") from exc
        raise _Blocked("BLOCKED_DATABASE", database, "SESSION_CHECK_FAILED") from exc
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    session = row[0] if row else None
    if not isinstance(session, str) or session.lower() != target.lower():
        raise _Blocked("BLOCKED_DATABASE", database, "SESSION_DATABASE_MISMATCH")


def _check_universe(
    dmap, now: datetime
) -> tuple[UniverseManifest, tuple[str, ...], dict]:
    if not dmap.manifest_path:
        raise _Blocked("BLOCKED_UNIVERSE", None, "MANIFEST_MISSING")
    try:
        manifest = UniverseManifest.model_validate(
            json.loads(Path(dmap.manifest_path).read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise _Blocked("BLOCKED_UNIVERSE", None, "MANIFEST_INVALID") from exc
    if now < manifest.accepted_at:
        raise _Blocked("BLOCKED_UNIVERSE", None, "MANIFEST_NOT_YET_ACCEPTED")
    if now >= manifest.expires_at:
        raise _Blocked("BLOCKED_UNIVERSE", None, "MANIFEST_EXPIRED")
    if manifest_digest(manifest.symbols, manifest.benchmarks) != manifest.sha256:
        raise _Blocked("BLOCKED_UNIVERSE", None, "MANIFEST_DIGEST_MISMATCH")
    candidates = list(dict.fromkeys([*manifest.symbols, *manifest.benchmarks]))
    if len(candidates) > manifest.symbol_limit:
        raise _Blocked("BLOCKED_UNIVERSE", None, "OVER_SYMBOL_LIMIT")
    if len(candidates) > GLOBAL_SYMBOL_CAP:
        raise _Blocked("BLOCKED_UNIVERSE", None, "OVER_GLOBAL_CAP")
    warmer = importlib.import_module(WARMER_MODULE)
    for symbol in candidates:
        if warmer._is_cusip(symbol):  # pylint: disable=protected-access
            raise _Blocked("BLOCKED_UNIVERSE", None, "CUSIP_SYMBOL")
        if not SYMBOL_PATTERN.match(symbol):
            raise _Blocked("BLOCKED_UNIVERSE", None, "INVALID_SYMBOL")
    admitted = tuple(s for s in candidates if s not in warmer.SKIP_SYMBOLS)
    counts = {
        "requested": len(candidates),
        "skipped": len(candidates) - len(admitted),
        "admitted": len(admitted),
    }
    if not admitted:
        logger.warning(
            "fmp_sync admission: empty universe after filtering %d manifest symbols",
            len(candidates),
        )
        raise _Blocked("BLOCKED_EMPTY_UNIVERSE", None, "EMPTY_UNIVERSE")
    return manifest, admitted, counts


# ------------------------------------------------------------------ entry


def admit(  # pylint: disable=too-many-arguments,too-many-locals
    dmap: DeploymentMap,
    *,
    mode: Mode,
    requested_class: TargetClass = "disposable",
    env: MutableMapping[str, str] | None = None,
    executable: str | None = None,
    module_origin_fn: Callable[[str], Path | None] | None = None,
    git_facts_fn: Callable[[Path], Any] | None = None,
    import_warmer_fn: Callable[[], Any] | None = None,
    connect_fn: Callable[[], Any] | None = None,
    dotenv_path: Path | None = None,
    now: datetime | None = None,
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> Admission:
    """Run every admission layer in order; the first failure wins."""
    env = os.environ if env is None else env
    before = _db_env(env)
    target, target_class = dmap.target.lower(), dmap.target_class
    try:
        hermes = _load_hermes()
    except ImportError:
        return Admission(
            False,
            "BLOCKED_MODULE_ORIGIN",
            "module_origin",
            ("HERMES_INTEGRATION_UNAVAILABLE",),
            target=target,
            target_class=target_class,
        )
    layers = hermes.FailedLayer
    prov = hermes.provenance
    category: str | None = None
    try:
        try:
            profile = hermes.load_profile(Path(dmap.profile_path))
        except (OSError, ValueError) as exc:
            raise _Blocked(
                "BLOCKED_CONFIG", layers.CONFIG.value, "PROFILE_UNREADABLE"
            ) from exc
        _check_process(dmap, profile, layers, prov, executable or sys.executable)
        _check_origins(
            dmap,
            layers,
            module_origin_fn or _default_module_origin,
            git_facts_fn or prov.git_facts,
        )
        _check_config(
            dmap,
            layers,
            env,
            before=before,
            dotenv_path=(
                dotenv_path if dotenv_path is not None else _default_dotenv_path()
            ),
            import_warmer_fn=(
                import_warmer_fn or (lambda: importlib.import_module(WARMER_MODULE))
            ),
        )
        category = _check_database(
            dmap, profile, layers, env, requested_class=requested_class, prov=prov
        )
        if mode == "execute":
            _check_disk(dmap, layers, disk_usage_fn)
            _probe_session(
                dmap.target,
                layers,
                connect_fn or (lambda: _default_connect(dmap.target)),
            )
        if dmap.legacy_selector:
            return Admission(
                True,
                "ADMITTED",
                None,
                ("LEGACY_SELECTOR_OPT_IN",),
                db_category=category,
                symbols=None,
                target=target,
                target_class=target_class,
            )
        manifest, symbols, counts = _check_universe(
            dmap, now or datetime.now(timezone.utc)
        )
    except _Blocked as blocked:
        return Admission(
            False,
            blocked.code,
            blocked.layer,
            blocked.findings,
            db_category=blocked.category or category,
            target=target,
            target_class=target_class,
        )
    return Admission(
        True,
        "ADMITTED",
        None,
        (),
        db_category=category,
        manifest_id=manifest.manifest_id,
        manifest_sha256=manifest.sha256,
        symbols=symbols,
        counts=counts,
        target=target,
        target_class=target_class,
    )
