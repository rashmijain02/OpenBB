"""Render the versioned, paused price-warming cron wrapper (#1344-T03).

Modes are deliberately minimal:

- ``plan`` (default, writes nothing): report NEW/UNCHANGED/UPDATE/DRIFT for the
  wrapper and PRINT the paused ``hermes cron create`` command text.
- ``apply-files``: write only the wrapper script into
  ``<hermes-home>/scripts``. Refused on DRIFT (an edited file is never
  overwritten).

This module never runs Hermes, never edits ``jobs.json`` and has no register
mode: ``--register`` and any other command are rejected by the parser.

The ``hermes cron create`` flags are UNVERIFIED placeholders. OPS-ATTEST (g)
requires the owner's ``hermes cron create --help`` output from the installed
version before the command can be bound and run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from portfolio_utils.fmp_sync import locking
from portfolio_utils.fmp_sync.admission import DeploymentMap, load_map

WRAPPER_VERSION = 3
WRAPPER_NAME = "fmp_cache_prices.py"
JOB_NAME = "fmp-cache-prices"
SCHEDULE = "30 15 * * 1-5"
HERMES_TZ = "America/Los_Angeles"
MARKET_TZ = "America/New_York"
MARKET_TIME = (18, 30)  # Eastern wall-clock the schedule must land on
RUN_MODE = "execute"
# Deadline story (one place): the dispatcher in the child ends itself at
# locking.DEFAULT_DEADLINE_S (900 s, CANCELLED_DEADLINE). The wrapper's own
# deadline is WRAPPER_MARGIN_S later; at that point it touches the cancel file
# and waits WRAPPER_GRACE_S for a CANCELLED outcome, then kills the job. The
# worst case (deadline + grace) stays under Hermes' 3600 s script timeout.
WRAPPER_MARGIN_S = 120.0
WRAPPER_DEADLINE_S = locking.DEFAULT_DEADLINE_S + WRAPPER_MARGIN_S
WRAPPER_GRACE_S = 30.0
HERMES_SCRIPT_TIMEOUT_S = 3600.0
TEMPLATE = Path(__file__).resolve().parent / "templates" / "fmp_cache_prices.py.tmpl"
_ZERO = "0" * 64
# Windows/DST-sensitive instants: the days around both 2027 US transitions.
DST_WINDOWS = (
    (date(2027, 3, 8), date(2027, 3, 22)),
    (date(2027, 11, 1), date(2027, 11, 15)),
)


class RenderError(ValueError):
    """Render refused (config, drift or unsupported schedule). Text carries no paths."""


@dataclass(frozen=True)
class PlanResult:
    """What a plan found; ``command`` is text to print, never to run."""

    status: str  # NEW | UNCHANGED | UPDATE | DRIFT
    content_sha256: str
    command: str
    child_python: str
    sync_python: str


# ------------------------------------------------------------------ schedule


def _field_values(spec: str, low: int, high: int) -> set[int]:
    if spec == "*":
        return set(range(low, high + 1))
    if "-" in spec:
        first, last = spec.split("-", 1)
        return set(range(int(first), int(last) + 1))
    return {int(spec)}


def fire_instants(schedule: str, start: date, end: date) -> list[datetime]:
    """Fire instants (aware, Hermes zone) for ``M H * * D[-D]`` between dates inclusive."""
    parts = schedule.split()
    if len(parts) != 5 or parts[2] != "*" or parts[3] != "*":
        raise RenderError("unsupported schedule form")
    minute, hour = int(parts[0]), int(parts[1])
    days = _field_values(parts[4], 0, 7)
    zone = ZoneInfo(HERMES_TZ)
    fires: list[datetime] = []
    day = start
    while day <= end:
        cron_day = day.isoweekday() % 7  # cron: 0/7 = Sunday, 1 = Monday
        if cron_day in days:
            fires.append(
                datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            )
        day += timedelta(days=1)
    return fires


def to_new_york(fires: list[datetime]) -> list[datetime]:
    """Convert fire instants to America/New_York."""
    zone = ZoneInfo(MARKET_TZ)
    return [moment.astimezone(zone) for moment in fires]


def dst_check(schedule: str) -> list[str]:
    """Return problems: fire instants around both 2027 DST transitions must be 18:30 ET."""
    problems: list[str] = []
    for start, end in DST_WINDOWS:
        for eastern in to_new_york(fire_instants(schedule, start, end)):
            if (eastern.hour, eastern.minute) != MARKET_TIME or eastern.weekday() > 4:
                problems.append(f"DST_MISMATCH:{eastern.date().isoformat()}")
    return problems


# ------------------------------------------------------------------ inputs


def effective_state_root(map_path: Path) -> Path:
    """State root the wrapper uses; must equal the manual default."""
    dmap = _load(map_path)
    default = Path(os.path.abspath(locking.default_state_root()))
    if dmap.state_root and Path(os.path.abspath(dmap.state_root)) != default:
        raise RenderError("state root differs from the manual default")
    return default


def _load(map_path: Path) -> DeploymentMap:
    try:
        return load_map(Path(map_path))
    except ValueError as exc:
        raise RenderError("deployment map unreadable or invalid") from exc


def _cfg(venv: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = (venv / "pyvenv.cfg").read_text("utf-8")
    except OSError as exc:
        raise RenderError("interpreter venv has no pyvenv.cfg") from exc
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    return values


def resolve_child_python(venv: Path) -> tuple[str, str]:
    """Return (venv python, ``major.minor`` from ``pyvenv.cfg``).

    The wrapper runs the venv's own python so ``sys.executable`` stays inside
    the pinned venv (admission requires it). On Windows that is the venv
    launcher, which starts the base python as a second process; the wrapper's
    job object (KILL_ON_JOB_CLOSE) contains both, so killing the wrapper kills
    the pair and releases the lock.
    """
    venv = Path(venv)
    cfg = _cfg(venv)
    version = cfg.get("version_info") or cfg.get("version") or ""
    minor = ".".join(version.split(".")[:2])
    for rel in (("Scripts", "python.exe"), ("bin", "python3"), ("bin", "python")):
        candidate = venv.joinpath(*rel)
        if candidate.is_file():
            return str(candidate), minor
    raise RenderError("venv python not found")


def render_wrapper(map_path: Path) -> str:
    """Return the final wrapper text (LF) with its embedded self hash."""
    dmap = _load(map_path)
    if dmap.hermes_timezone != HERMES_TZ:
        raise RenderError(f"map must set HERMES_TIMEZONE to {HERMES_TZ}")
    problems = dst_check(SCHEDULE)
    if problems:
        raise RenderError("schedule does not land on the market time through DST")
    if not 0 < WRAPPER_GRACE_S < WRAPPER_MARGIN_S:
        raise RenderError("grace period must be positive and below the deadline margin")
    if WRAPPER_DEADLINE_S + WRAPPER_GRACE_S >= HERMES_SCRIPT_TIMEOUT_S:
        raise RenderError("wrapper deadline plus grace reaches the Hermes timeout")
    root = effective_state_root(map_path)
    child, minor = resolve_child_python(Path(dmap.interpreter))
    sync_python = dmap.sync_python or minor
    if not sync_python or (minor and sync_python != minor):
        raise RenderError("sync python version unknown or inconsistent with the venv")
    source = Path(dmap.source_root)
    tokens = {
        "VERSION": str(WRAPPER_VERSION),
        "SELF_SHA256": _ZERO,
        "MAP_PATH": json.dumps(str(Path(map_path).resolve())),
        "MAP_SHA256": json.dumps(
            hashlib.sha256(Path(map_path).read_bytes()).hexdigest()
        ),
        "STATE_ROOT": json.dumps(str(root)),
        "CHILD_PYTHON": json.dumps(child),
        "CHILD_SHA256": json.dumps(
            hashlib.sha256(Path(child).read_bytes()).hexdigest()
        ),
        "TARGET_CLASS": json.dumps(dmap.target_class),
        "DEADLINE_S": repr(float(WRAPPER_DEADLINE_S)),
        "GRACE_S": repr(float(WRAPPER_GRACE_S)),
        "SOURCE_PATHS": json.dumps(
            [
                str(source / "openbb_platform" / "tools" / "portfolio_utils"),
                str(source / "openbb_platform" / "extensions" / "agents"),
            ]
        ),
        "MODE": json.dumps(RUN_MODE),
    }
    text = TEMPLATE.read_text("utf-8").replace("\r\n", "\n")
    for key, value in tokens.items():
        text = text.replace(f"@@{key}@@", value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text.replace(f'SELF_SHA256 = "{_ZERO}"', f'SELF_SHA256 = "{digest}"', 1)


def verify_self_hash(text: str) -> bool:
    """Return True when ``text`` is an untampered rendered wrapper."""
    data = text.replace("\r\n", "\n")
    marker = 'SELF_SHA256 = "'
    index = data.find(marker)
    if index < 0:
        return False
    start = index + len(marker)
    embedded = data[start : start + 64]
    blanked = data[:start] + _ZERO + data[start + 64 :]
    return hashlib.sha256(blanked.encode("utf-8")).hexdigest() == embedded


def _command() -> str:
    return "\n".join(
        [
            "# UNVERIFIED: every hermes cron create flag below is a PLACEHOLDER.",
            "# Bind them from the owner's `hermes cron create --help` output",
            "# (OPS-ATTEST g, installed Hermes version) before running anything.",
            "# This job must be created PAUSED with local-only delivery and no agent.",
            f"# The gateway must run with HERMES_TIMEZONE={HERMES_TZ}.",
            f'hermes cron create <UNVERIFIED:schedule> "{SCHEDULE}" '
            f"<UNVERIFIED:name> {JOB_NAME} "
            f"<UNVERIFIED:script> {WRAPPER_NAME} "
            "<UNVERIFIED:no-agent> <UNVERIFIED:paused> <UNVERIFIED:deliver-local>",
            "# Afterwards `hermes cron list` must show the job paused (live step).",
        ]
    )


def plan(map_path: Path, hermes_home: Path) -> PlanResult:
    """Compare the rendered wrapper with the installed one; write nothing."""
    text = render_wrapper(map_path)
    dmap = _load(map_path)
    child, minor = resolve_child_python(Path(dmap.interpreter))
    target = Path(hermes_home) / "scripts" / WRAPPER_NAME
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not target.exists():
        status = "NEW"
    else:
        existing = target.read_bytes().decode("utf-8", errors="replace")
        if existing.replace("\r\n", "\n") == text:
            status = "UNCHANGED"
        elif verify_self_hash(existing):
            status = "UPDATE"
        else:
            status = "DRIFT"
    return PlanResult(status, digest, _command(), child, dmap.sync_python or minor)


def apply_files(map_path: Path, hermes_home: Path) -> PlanResult:
    """Write only the wrapper script; never register or touch ``jobs.json``."""
    result = plan(map_path, hermes_home)
    if result.status == "DRIFT":
        raise RenderError("installed wrapper was edited; refusing to overwrite")
    if result.status != "UNCHANGED":
        target = Path(hermes_home) / "scripts" / WRAPPER_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_bytes(render_wrapper(map_path).encode("utf-8"))
        os.replace(tmp, target)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m portfolio_utils.fmp_sync.render")
    sub = parser.add_subparsers(dest="command")
    for name in ("plan", "apply-files"):
        item = sub.add_parser(name)
        item.add_argument("--map", required=True, type=Path)
        item.add_argument("--hermes-home", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry; ``plan`` is the default and only prints."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0].startswith("--") and args[0] not in ("-h", "--help"):
        args = ["plan", *args]
    parsed = _parser().parse_args(args)
    if parsed.command is None:
        _parser().error("a command is required (plan or apply-files)")
    try:
        if parsed.command == "apply-files":
            result = apply_files(parsed.map, parsed.hermes_home)
        else:
            result = plan(parsed.map, parsed.hermes_home)
    except RenderError as exc:
        print(f"render refused: {exc}")  # noqa: T201
        return 40
    print(  # noqa: T201
        json.dumps(
            {
                "status": result.status,
                "sha256": result.content_sha256,
                "sync_python": result.sync_python,
                "applied": parsed.command == "apply-files",
            },
            sort_keys=True,
        )
    )
    print(result.command)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
