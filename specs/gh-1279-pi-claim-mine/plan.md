# Implementation Plan: List My Claims and Heartbeat Urgency

**Branch**: No branch created by Phase 1 | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)
**Input**: `specs/gh-1279-pi-claim-mine/spec.md`
**Parent Issue**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)
**Status**: Draft, pending G1. Recommendations are provisional; no execution is authorized.

## Summary

Add a read-only `cmd_mine()` command and `--mine` dispatch to the existing script.
Reuse identity, project pagination, trusted heartbeat selection, age calculation, and
threshold constants. Extend the existing offline tests, not the architecture.

## Technical Context

**Language/Version**: Existing Python script; use Python 3.12+ in `.venv_portfolio`.
**Primary Dependencies**: Standard library, existing gh wrappers; pytest for tests.
**Storage**: Existing Project 1 items and issue comments, read only; no new persistence.
**Testing**: `openbb_platform/tests/test_pi_claim.py`, using `_load_module()`,
`_project_item()`, monkeypatch, capsys, and local functions.
**Target Platform**: Existing cross-platform maintenance CLI; commands use PowerShell.
**Project Type**: Repository maintenance CLI.
**Performance Goals**: No new SLA; resolve identity once and fetch comments only for
In Progress issues. Reuse existing project pagination.
**Constraints**: Zero GitHub writes; no network in tests, new dependencies, private-data
fixtures, protocol changes, or unrelated refactoring.
**Scale/Scope**: One Project 1 scan, two production/test files, two user stories.

## Constitution Check

| Principle | Before research | After design |
| --- | --- | --- |
| Fork independence | Pass: origin and gh default verified | Pass: existing repo-scoped helpers |
| Issue first / board record | Pass: parent on Project 1 | Pass: no child issues or local tracker; user defers issue creation |
| Test first / real-path verification | Pass: red-green strategy | Conditional: scenario specified; `/verify` availability must be resolved before G2 |
| Providers | Pass: none needed | Pass: no provider calls; `fmp_cached`-first rule unchanged |
| Privacy | Pass: no brokerage data needed | Pass: synthetic fixtures and repo-relative evidence |
| Integration flow | Pass: planning only | Pass: no branch/commit/push/merge |

Constitution Last Amended and latest cited `CLAUDE.md` change are both 2026-11-20.
Re-check after G1 edits. The headless override permits planning against pending
recommendations; it neither grants G1 approval nor waives G2 verification.

## Project Structure

### Documentation (this feature)

```text
specs\gh-1279-pi-claim-mine\
  spec.md
  plan.md
  research.md
  data-model.md
  quickstart.md
  contracts\cli.md
  checklists\requirements.md
  tasks.md
  analysis.md
```

### Source Code (repository root)

```text
scripts\pi_claim.py                        # Planned implementation and usage text
openbb_platform\tests\test_pi_claim.py      # Planned offline regression tests
```

**Structure Decision**: Extend existing files in place. Add `cmd_mine()` alongside
`cmd_list_stale()` without refactoring the latter or changing shared trust rules.

## Design and Control Flow

1. Add `--mine` to the current parser, usage text, and help/no-arguments guard.
2. Before dispatch or GitHub access, reject conflicting `--mine` arguments with
   `p.error()` (exit 2). Detect a supplied `--note`, including an empty value. Preserve
   `--help` precedence and behavior without `--mine`.
3. Resolve `whoami()` once, scan `_project_items()`, and follow the existing `Status`
   field-name check for `In Progress`. Skip content without issue numbers.
4. Call `latest_heartbeat(str(number))` for eligible-status issues. Skip absent markers
   or exact owner mismatches. Do not filter by action or assignee (Q1).
5. Compute `_age(hb)`. Compare timedeltas using `STALE_HOURS` first, then
   `HEARTBEAT_INTERVAL_MIN`, with strict `>` comparisons. Display signed whole minutes
   using existing floor division and the exact labels in the contract.
6. Print matching rows in traversal order with issue number/title (60-character title
   limit). Print an explicit no-claims line when empty. Return 0 for successful listings.
7. Preserve visible helper failures; do not convert lookup failures to empty success.
   Existing inspection helpers propagate `RuntimeError`, producing a visible nonzero
   CLI failure. Do not add a broad catch or silent fallback.
8. No mutation helper is reachable from this command. No auto-heartbeat on inspection.

## Test Strategy

All additions belong to `openbb_platform/tests/test_pi_claim.py`. Each behavior slice
starts with a failing test, followed by the smallest implementation and a targeted
rerun. The user's explicit network-free requirement overrides generic live-provider
test guidance for this maintenance CLI.

- Use `_load_module()` for one production module identity and `_project_item()` for
  existing GraphQL shape. Synthetic users: `agent-a`, `agent-b`.
- Filtering tests patch identity/project/heartbeat/age seams as needed. Cover ownership,
  statuses, missing content/status, missing heartbeat, and release/done markers (Q1).
- Trust tests patch `gh_json` with ordered synthetic REST comments containing `id`,
  `body`, and `author_association`; leave `latest_heartbeat()` and its parser real.
  Prove newer trusted owners win and untrusted/malformed markers cannot spoof ownership.
- `test_mine_main_read_only_paginated` patches `gh` for identity and `gh_json` for
  GraphQL pages and REST comments, sets `sys.argv` to `["pi_claim.py", "--mine"]`,
  and runs real `main()`, `cmd_mine()`, `_project_items()`, `latest_heartbeat()`, and
  `_age()`. Freeze `module.datetime` with a subclass returning a fixed aware UTC time.
  Put an eligible owned claim on the second page and assert its row and cursor traversal.
- Transport fakes allow only expected reads (GraphQL `query`, never `mutation`;
  REST GET user/comments), and fail on unexpected operations. Patch mutation helpers
  with failing sentinels too. Do not mock `cmd_mine()` in the real-path smoke test.
- Fixed-age cases: 0, 5m, 10m, 10m1s, 11m, 120m, 120m1s, 121m, and -1m.
  Assert each issue's row-local age and exact label, not global substring presence.
- Inject `RuntimeError` from identity/project/comment reads and require it to surface,
  never as no-claims output. Empty cases assert return 0 and a clear message.
- CLI conflicts patch `sys.argv` and all read/write seams with failing sentinels;
  expect `SystemExit(2)` and usage diagnostics, including for `--note ""`.
- Reverse-verify load-bearing tests in Phase 2: locally remove the owner condition,
  mutate each strict threshold comparator, or insert a mutation call; the corresponding
  test must fail. Restore changes and rerun before final checks. Never commit mutations.

### Phase 2 Commands (not executed during this documentation-only phase)

```powershell
& .\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\tests\test_pi_claim.py -k mine -q
& .\.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\tests\test_pi_claim.py -q
& .\.venv_portfolio\Scripts\python.exe -m black --check scripts\pi_claim.py openbb_platform\tests\test_pi_claim.py
& .\.venv_portfolio\Scripts\python.exe -m ruff check scripts\pi_claim.py openbb_platform\tests\test_pi_claim.py
```

### Required `/verify` Scenario and Availability

Requested invocation for the Phase 2 agent, once its `/verify` harness is available:

```text
/verify Drive pi_claim.main() with argv ["pi_claim.py", "--mine"] against synthetic
two-page project and trusted/untrusted comment fixtures; exercise all urgency labels
and empty/error cases, fail on every GitHub write, and capture the actual command
and output in .dev-cycle/verify-gh-1279.log without network access.
```

This is a scenario request, not a claim that a runnable `/verify` command exists here.
No `/verify` command/skill definition was found in the repository command locations
inspected; `scripts/verify_mcp_runtime.py` is unrelated. Phase 2 must supply the documented
harness or obtain an approved equivalent before G2. The offline smoke test defines
the real-path driver; passing pytest alone does not waive the separate verification gate.

## Provider Use and Private Data

No financial data provider is needed. Do not add any provider call; the general
`fmp_cached`-first policy remains unchanged. Read only existing issue/project metadata
and trusted heartbeat fields. Do not read exports, credentials, browser profiles,
or notebook output. Save only synthetic fixtures and repo-relative evidence.

## Phase 1 Friction and G1 Decisions

- Confirm Q1/Q2 recommendations before execution.
- Canonical `.venv_portfolio\Scripts\python.exe` is absent in this temporary checkout.
  No global substitute or installation was used; tests and claim CLI startup checks
  were not run. Restore the canonical environment before Phase 2.
- This gh build rejects `--repo` on `repo set-default --view`. The flagged invocation
  failed; the supported read-only form confirmed the correct default. Issue reads
  explicitly target the fork.
- A bundled command containing read-only `git branch --show-current` was denied before
  execution. Setup succeeded when retried without it; no branch operation was performed.
- `latest_heartbeat()` currently reads at most the first 100 issue comments. Reuse its
  existing semantics; extending comment pagination is outside this pilot's scope.
- Record process friction on the parent issue in a later authorized coordination step.
  This run preserves it here and makes no GitHub mutations.

## Complexity Tracking

No implementation complexity exceptions. The G2 harness risk remains open, not passed.
