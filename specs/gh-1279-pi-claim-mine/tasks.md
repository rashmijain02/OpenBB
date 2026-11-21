# Tasks: List My Claims and Heartbeat Urgency

**Input**: `specs/gh-1279-pi-claim-mine/` design documents.
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/cli.md`.
**Parent**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)
**Tests**: Required, offline monkeypatch style. Each behavior task is a test-first
red-green-refactor slice, not permission to implement before observing failure.
**Organization**: Five US1 tasks, two US2 tasks, one cross-cutting validation task: **8 total** (T002 merged into T001 at G1).
**Status**: Plan only, not a local work tracker. G1 approved by the owner on 2026-11-20 with trims.

## Format: `[ID] [P?] [Story] Description`

No tasks are marked `[P]`: all implementation slices share the same two files.
Story labels map to `spec.md`. Paths are repository-relative.

## Phase 1: Setup (Shared Infrastructure)

No project scaffolding or dependency changes are needed. Before execution, G1 must be
approved, the normal issue/branch relay authorized, and the canonical venv restored.
These are external entry conditions, not additional implementation tasks.

## Phase 2: Foundational (Blocking Prerequisites)

Reuse `_load_module()` and `_project_item()` in the existing test module. Add fixture
helpers only when a story test needs them. No new foundational subsystem or model.

## Phase 3: User Story 1 - See Only My Current Claims (Priority: P1) (#1280)

**Goal**: One read-only command lists only attributable In Progress claims and clearly
distinguishes empty output from a failed lookup.
**Independent Test**: Synthetic mixed-status/owner items, trusted comment histories,
and two GraphQL pages exercise real command behavior without network.

### Test-First Implementation Slices

- [x] T001 [US1] Write failing `test_mine_filters_status_and_owner` in `openbb_platform\tests\test_pi_claim.py`, including missing content/status/number, absent marker, another owner, and latest release/done markers with In Progress status; then add minimal `cmd_mine()` filtering in `scripts\pi_claim.py` using existing helpers. Canonical constraints: `data-model.md` `ProjectItem.content.number`, `ProjectItem.fieldValues.nodes`, `CurrentIdentity.login`, `TrustedMarker.owner`, `TrustedMarker.action`. Test one identity resolution per invocation. In the same red step, also write `test_mine_uses_latest_trusted_heartbeat` in `openbb_platform\tests\test_pi_claim.py` using ordered synthetic comment dictionaries through patched `gh_json`, not a patched parser Cover ownership changing to another trusted user, untrusted impersonation, and malformed timestamp skipping. Canonical constraint: `data-model.md` `TrustedMarker.hb` and `TrustedMarker.owner`. Covers FR-002. and make `cmd_mine()` delegate marker selection to the real `latest_heartbeat()`. (T002 merged here at G1 so every task starts red.) Covers FR-002.
- [x] T003 [US1] Write failing `test_mine_empty_is_explicit` and `test_mine_lookup_failures_surface` in `openbb_platform\tests\test_pi_claim.py`; then finish empty-result output and preserve visible identity/project/comment failures in `scripts\pi_claim.py`, with no broad catch or no-claims fallback. Include empty project, only other owners, and no trusted markers. Covers FR-006.
- [x] T004 [US1] Write failing `test_mine_main_read_only_paginated` in `openbb_platform\tests\test_pi_claim.py` with fixed UTC time, real `main()`/pagination/parser/age helpers, synthetic user/comments/project responses, an owned item on page two, read-only transport allowlists and mutation sentinels; then wire `--mine` dispatch and update the no-arguments guard in `scripts\pi_claim.py`. Assert cursor traversal, eligible output and return 0; never patch `cmd_mine()`. Covers FR-001, FR-003, FR-007.
- [x] T005 [US1] Write failing `test_mine_rejects_conflicting_arguments` in `openbb_platform\tests\test_pi_claim.py` for positionals, action, `--note` including empty string, `--list-stale`, and `--status`; then add `--mine`-specific usage validation in `scripts\pi_claim.py`. Require exit 2, diagnostics, and no reads/writes; allow help precedence. Covers FR-008.
- [x] T006 [US1] Write failing `test_mine_rows_include_issue_and_title_in_project_order` and `test_mine_help_and_legacy_dispatch` in `openbb_platform\tests\test_pi_claim.py`; then finish row identity/title formatting and module usage text in `scripts\pi_claim.py` while preserving non-`--mine` help, status, stale-list and transition dispatch. Canonical constraints: `data-model.md` `DisplayRow.number` and `DisplayRow.title`. Covers FR-001, FR-004, FR-009.

**Checkpoint**: US1 is a useful read-only ownership listing. Run its tests independently
before adding urgency classification.

## Phase 4: User Story 2 - Identify Overdue Heartbeats (Priority: P2) (#1281)

**Goal**: Each owned row shows age and exactly one correct urgency flag.
**Independent Test**: Fixed-age owned items around both thresholds produce row-local
expected output; no other ownership scenario is needed to validate urgency.

### Test-First Implementation Slices

- [x] T007 [US2] Write failing `test_mine_flags_use_exact_thresholds` in `openbb_platform\tests\test_pi_claim.py` at 0m, 5m, 10m, 10m1s, 11m, 120m, 120m1s and 121m; then add strict unrounded comparisons using existing constants in `scripts\pi_claim.py`. Extend `test_mine_main_read_only_paginated` with rows covering all three flags. Canonical constraint: `data-model.md` `DisplayRow.urgency`. Covers FR-005, FR-007.
- [x] T008 [US2] Write failing `test_mine_displays_signed_whole_minute_ages` in `openbb_platform\tests\test_pi_claim.py` for just-over boundaries and a future marker; then finish age formatting in `scripts\pi_claim.py` using existing signed floor-division semantics without influencing classification. Assert each row's label as well as age. Canonical constraint: `data-model.md` `DisplayRow.age`. Covers FR-004, FR-005.

**Checkpoint**: US1 and US2 pass together, including exact boundaries and write guards.

## Phase 5: Polish & Cross-Cutting Concerns

- [x] T009 Final gates (trimmed at G1, 2026-11-20): run the focused and full `openbb_platform\tests\test_pi_claim.py` module and the Black/Ruff commands in `specs\gh-1279-pi-claim-mine\quickstart.md`; then run the real path once, read-only, against the live board: `python scripts\pi_claim.py --mine` with the main checkout's `.venv_portfolio`. Capture the command and output in `.dev-cycle\verify-gh-1279.log` for the handoff. The temporary-mutation step was dropped at G1.

## Dependencies & Execution Order

Actual task prerequisites (additional sequencing is for avoiding shared-file conflicts):

| Task | Requires | Reason |
| --- | --- | --- |
| T001 | G1/execution entry conditions | First handler slice |
| T002 | T001 | Exercise handler's real marker selection |
| T003 | T001 | Complete listing result/error behavior |
| T004 | T001 | Wire handler through real CLI and read-only pagination |
| T005 | T004 | Validate new CLI mode conflicts |
| T006 | T004 | Complete CLI display/help/compatibility contract |
| T007 | T004 | Add urgency and extend real-path scenario |
| T008 | T007 | Verify formatted age cannot alter urgency |
| T009 | T001, T003, T005, T006, T008 | All behavior slices ready for final verification |

Recommended order: T001, T003 through T009. Story progression: US1 (MVP) -> US2 -> final gates.
US2 depends on US1's listing foundation; its urgency behavior remains independently
testable with a minimal owned-item fixture.

## Parallel Examples

US1: do not edit the handler and the shared test file from simultaneous tasks. After
implementation, read-only documentation inspection may overlap a focused test run.
US2: same restriction; boundary tests and age tests share code and must land sequentially.
No parallel agent dispatch is required or authorized by this plan.

## Implementation Strategy

Deliver US1 first as the minimal ownership listing, validate it, then add US2 urgency
without changing eligibility. Each slice writes tests, observes red, implements green,
and refactors only if needed. Reuse fixtures/helpers; no live network calls. Final
quality/verification must complete before G2. Nothing in this task plan authorizes
issue creation, branching, committing, pushing, or continuing past G1 in this run.
