# Validation Guide: List My Claims

**Parent**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)
**Status**: Future Phase 2 commands, not results from this Phase 1 run.

## Prerequisites

G1 approval and the normal Phase 2 relay must occur first. Restore canonical
`.venv_portfolio\Scripts\python.exe` and its existing pytest/Black/Ruff tools.
Do not substitute global Python or modify a shared environment during this pilot.
No credentials or network access are needed for automated scenarios.

## Focused Red-Green and Regression Checks

From the repository root, after writing the planned tests and implementation:

```powershell
& .\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\tests\test_pi_claim.py -k mine -q
& .\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\tests\test_pi_claim.py -q
& .\.venv_portfolio\Scripts\python.exe -m black --check scripts\pi_claim.py openbb_platform\tests\test_pi_claim.py
& .\.venv_portfolio\Scripts\python.exe -m ruff check scripts\pi_claim.py openbb_platform\tests\test_pi_claim.py
```

Expected: new tests first fail for missing behavior, then all focused and existing
tests pass; formatting/lint pass. Reverse-verification mutations described in `plan.md`
must fail the corresponding tests and be restored before final checks.

## Real-Path Offline Scenario

```powershell
& .\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\tests\test_pi_claim.py -k test_mine_main_read_only_paginated -q
```

Expected: real `main()` dispatch, identity resolution, two project pages, trusted-marker
selection, frozen-time ages, eligible rows with all three labels, and return 0. Read-only
transport fakes reject unexpected calls; mutation sentinels are never called. Related
tests cover empty/error output, exact thresholds, and argument conflicts.

The required `/verify` request/capture path are in `plan.md`. Its harness is not defined
in this checkout; resolve availability before G2 rather than calling this pytest run
a completed `/verify` gate.

## Optional Runtime Inspection After Execution

With authorized runtime access and authenticated gh:

```powershell
& .\.venv_portfolio\Scripts\python.exe scripts\pi_claim.py --mine
```

Expected output follows [the CLI contract](contracts\cli.md). This runtime read is not
part of the offline suite and was not performed in Phase 1. Do not paste personal
identity or sensitive project content into public evidence.
