"""Metadata-only provenance: git facts, licence hash, pyvenv.cfg, fmp_cached database (#1338).

Only ``git`` is ever executed. Nothing here imports or runs Hermes, and no secret
value is kept: secret-shaped settings become :class:`Presence` flags.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from openbb_mcp_server.service.capability_provenance import normalize_import_origin

from .models import Presence

REPO_ROOT = Path(__file__).resolve().parents[5]

# Names read by ``openbb_fmp_cached.utils.database.DatabaseConfig._load_config``;
# a contract test pins them to that module's string constants.
SETTINGS_DB_KEYS = ("mysql_database", "db_database", "database_name")
SETTINGS_ANY_KEYS = (
    "mysql_host",
    "mysql_user",
    "mysql_password",
    "mysql_database",
    "db_host",
    "db_user",
    "db_password",
    "db_database",
    "database_host",
    "database_user",
    "database_password",
    "database_name",
)
ENV_VARS = ("FMP_CACHE_TEST_MODE", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
DEFAULT_DB = "openbb_fmp_cache"
TEST_DB = "openbb_fmp_cache_test"
_SECRET_KEY = re.compile(r"key|token|secret|password|passwd", re.IGNORECASE)


@dataclass(frozen=True)
class GitFacts:
    """Facts read from a checkout with ``git`` only."""

    sha: str | None
    remote: str | None
    dirty: bool | None


def _git(directory: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-c",
                "core.fsmonitor=false",  # never run a repo-configured fsmonitor hook
                "-C",
                str(directory),
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def normalize_remote(url: str | None) -> str | None:
    """Return ``host/owner/repo`` with scheme, userinfo and ``.git`` removed."""
    if not url:
        return None
    text = url.strip()
    scp = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", text)  # git@host:owner/repo
    if scp:
        text = f"{scp.group(1)}/{scp.group(2)}"
    text = re.sub(r"^[a-z+]+://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[^/@]*@", "", text)
    text = text.removesuffix(".git").rstrip("/")
    return text.lower()


def git_facts(directory: Path) -> GitFacts:
    """Read HEAD sha, normalized origin remote and dirty flag from a checkout."""
    sha = _git(directory, "rev-parse", "HEAD")
    remote = normalize_remote(_git(directory, "remote", "get-url", "origin"))
    status = _git(directory, "status", "--porcelain")
    return GitFacts(sha or None, remote, None if status is None else bool(status))


def license_sha256(directory: Path) -> str | None:
    """SHA-256 of the checkout's LICENSE file, if any."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        path = directory / name
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def origin_of(directory: Path) -> str:
    """Path-free origin label (``repo://``, ``external://<sha12>/name``)."""
    return normalize_import_origin(str(directory), repo_root=REPO_ROOT) or ""


def read_pyvenv_version(venv_dir: Path) -> str | None:
    """Return the interpreter version recorded in ``pyvenv.cfg``."""
    cfg = venv_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    values: dict[str, str] = {}
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    raw = values.get("version_info") or values.get("version")
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", raw or "")
    if not match:
        return None
    return ".".join(g for g in match.groups() if g is not None)


def python_matches(version: str, requires: str, supported: str) -> bool:
    """Return True when ``version`` satisfies ``requires`` and is on the supported minor."""
    from packaging.specifiers import SpecifierSet  # pylint: disable=C0415

    parts = version.split(".")
    in_range = version in SpecifierSet(requires)
    return in_range and ".".join(parts[:2]) == supported


@dataclass(frozen=True)
class DbResolution:
    """Which fmp_cached database the settings and environment resolve to."""

    database: str
    source: str
    presence: dict[str, Presence] = field(default_factory=dict)
    issues: tuple[str, ...] = ()


def default_settings_path() -> Path:
    """Return the file ``DatabaseConfig`` reads: ``~/.openbb_platform/user_settings.json``."""
    return Path.home() / ".openbb_platform" / "user_settings.json"


def load_credentials(
    settings_path: Path | None,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Return the ``credentials`` mapping, or ``{}`` plus a reason when unusable.

    ``DatabaseConfig`` falls back to environment variables on any settings error,
    so an unusable file is reported, never raised.
    """
    if settings_path is None or not Path(settings_path).is_file():
        return {}, ()
    try:
        loaded = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ("settings_unreadable",)
    if not isinstance(loaded, dict):
        return {}, ("settings_not_a_mapping",)
    raw = loaded.get("credentials", {})
    if not isinstance(raw, dict):
        return {}, ("credentials_not_a_mapping",)
    return raw, ()


def db_category(database: str, expected: str) -> str:
    """Render a database name as ``expected``, ``legacy_default`` or ``other``."""
    if database == expected:
        return "expected"
    return "legacy_default" if database == DEFAULT_DB else "other"


def _secret_presence(credentials: Mapping[str, object]) -> dict[str, Presence]:
    return {
        key: Presence.PRESENT if credentials[key] else Presence.ABSENT
        for key in sorted(credentials)
        if _SECRET_KEY.search(key)
    }


def resolve_fmp_cached_database(
    settings_path: Path | None, env: Mapping[str, str] | None = None
) -> DbResolution:
    """Mirror ``DatabaseConfig._load_config`` database selection, secrets as presence."""
    env = os.environ if env is None else env
    test_mode = env.get("FMP_CACHE_TEST_MODE", "false").lower() == "true"
    default = TEST_DB if test_mode else DEFAULT_DB
    credentials, issues = load_credentials(settings_path)
    presence = _secret_presence(credentials)
    if any(key in credentials for key in SETTINGS_ANY_KEYS):
        database = next(
            (str(credentials[k]) for k in SETTINGS_DB_KEYS if credentials.get(k)),
            None,
        )
        source = "settings" if database else "default"
        database = TEST_DB if test_mode else (database or default)
        return DbResolution(database, source, presence, issues)
    if any(env.get(var) for var in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")):
        database = TEST_DB if test_mode else env.get("DB_NAME", default)
        return DbResolution(database, "env", presence, issues)
    return DbResolution(default, "default", presence, issues)
