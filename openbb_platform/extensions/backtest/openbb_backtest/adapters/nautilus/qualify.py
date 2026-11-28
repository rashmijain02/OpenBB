"""``python -m openbb_backtest.adapters.nautilus.qualify``: turn worker facts into pass/fail."""

from __future__ import annotations

import argparse
import json
import os
import sys

from openbb_nautilus_worker.protocol import DescribeFacts, ErrorCode, ProtocolError
from pydantic import BaseModel, ConfigDict

from .client import WorkerClient, worker_command
from .pin import NautilusPin, load_pin

# Evaluation order mirrors FailedLayer ordering (module_origin before abi before config).
_LAYER_ORDER = ["module_origin", "abi", "config"]


class Check(BaseModel):
    """One qualification check."""

    model_config = ConfigDict(frozen=True)
    check: str
    layer: str
    ok: bool
    expected: str
    actual: str


class QualifyReport(BaseModel):
    """Qualification result for one runtime. Facts only: no paths, no secrets."""

    model_config = ConfigDict(frozen=True)
    runtime: str
    passed: bool
    failed_layer: str | None = None
    message: str | None = None
    nautilus_version: str | None = None
    python_version: str | None = None
    abi_tag: str | None = None
    wheel_tag: str | None = None
    high_precision: bool | None = None
    fixed_precision: int | None = None
    license_sha256: list[str] = []
    wheel_hash_evidence: str | None = None
    checks: list[Check] = []


def evaluate(pin: NautilusPin, runtime: str, facts: DescribeFacts) -> list[Check]:
    """Compare reported facts with the pin; one ``Check`` per assertion."""
    rt = pin.runtimes[runtime]
    expected_abi = f"{pin.python_tag}-{rt.platform_tag}"
    actual_abi = f"{facts.python_tag}-{facts.platform_tag}"
    wheel_ok = facts.wheel_sha256 is None or facts.wheel_sha256 == rt.wheel_sha256
    precision = (rt.high_precision, rt.fixed_precision)
    origin_ok = facts.module_origin_in_prefix
    return [
        Check(
            check="version",
            layer="module_origin",
            ok=facts.nautilus_version == pin.version,
            expected=pin.version,
            actual=facts.nautilus_version,
        ),
        Check(
            check="wheel_sha256",
            layer="module_origin",
            ok=wheel_ok,
            expected=rt.wheel_sha256,
            actual=facts.wheel_sha256 or "absent",
        ),
        Check(
            check="module_origin",
            layer="module_origin",
            ok=origin_ok,
            expected="inside worker prefix",
            actual="inside" if origin_ok else "outside",
        ),
        Check(
            check="python_minor",
            layer="abi",
            ok=facts.python_version.startswith(pin.python_minor + "."),
            expected=pin.python_minor,
            actual=facts.python_version,
        ),
        Check(
            check="abi_tag",
            layer="abi",
            ok=actual_abi == expected_abi,
            expected=expected_abi,
            actual=actual_abi,
        ),
        Check(
            check="precision",
            layer="abi",
            ok=(facts.high_precision, facts.fixed_precision) == precision,
            expected=f"high={precision[0]} fixed={precision[1]}",
            actual=f"high={facts.high_precision} fixed={facts.fixed_precision}",
        ),
    ]


def _failed_report(runtime: str, code: ErrorCode, message: str) -> QualifyReport:
    return QualifyReport(
        runtime=runtime, passed=False, failed_layer=code.value, message=message
    )


def qualify_runtime(
    pin: NautilusPin,
    runtime: str,
    command: list[str],
    *,
    timeout: float = 60.0,
    env=None,
) -> QualifyReport:
    """Spawn the worker, run ``describe`` and judge the facts against the pin."""
    try:
        with WorkerClient(command, timeout=timeout, env=env) as client:
            facts = client.describe()
    except ProtocolError as exc:
        return _failed_report(runtime, exc.code, exc.message)
    checks = evaluate(pin, runtime, facts)
    failed = [c for c in checks if not c.ok]
    layer = min((c.layer for c in failed), key=_LAYER_ORDER.index) if failed else None
    return QualifyReport(
        runtime=runtime,
        passed=not failed,
        failed_layer=layer,
        nautilus_version=facts.nautilus_version,
        python_version=facts.python_version,
        abi_tag=f"{facts.python_tag}-{facts.platform_tag}",
        wheel_tag=facts.wheel_tag,
        high_precision=facts.high_precision,
        fixed_precision=facts.fixed_precision,
        license_sha256=sorted({f.sha256 for f in facts.license_files}),
        wheel_hash_evidence="absent" if facts.wheel_sha256 is None else "verified",
        checks=checks,
    )


def _text(rep: QualifyReport) -> str:
    head = f"{rep.runtime}: {'PASS' if rep.passed else 'FAIL'}"
    if rep.failed_layer:
        head += f" (failed_layer={rep.failed_layer})"
    lines = [head]
    if rep.nautilus_version:
        lines.append(
            f"nautilus_trader {rep.nautilus_version} / {rep.abi_tag} / "
            f"HIGH_PRECISION={str(rep.high_precision).lower()} / FIXED_PRECISION={rep.fixed_precision}"
        )
    lines += [
        f"  {'ok ' if c.ok else 'BAD'} {c.check}: expected {c.expected}, got {c.actual}"
        for c in rep.checks
    ]
    if rep.message:
        lines.append(f"  {rep.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Exit 0 on pass, 2 on any qualification failure."""
    ap = argparse.ArgumentParser(prog="qualify", description=__doc__)
    ap.add_argument("--runtime", choices=["native", "docker"], required=True)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument(
        "--worker-command-json",
        help="JSON list overriding the spawn command (tests / fake worker)",
    )
    args = ap.parse_args(argv)
    pin = load_pin()
    try:
        command = (
            json.loads(args.worker_command_json)
            if args.worker_command_json
            else worker_command(args.runtime, os.environ, pin)
        )
        report = qualify_runtime(pin, args.runtime, command, timeout=args.timeout)
    except ProtocolError as exc:
        report = _failed_report(args.runtime, exc.code, exc.message)
    sys.stdout.write(
        (report.model_dump_json(indent=2) if args.format == "json" else _text(report))
        + "\n"
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
