# Feature Specification: List My Claims and Heartbeat Urgency

**Feature Branch**: Not created; Phase 1 headless pilot stops at G1.

**Feature Directory**: `specs/gh-1279-pi-claim-mine`

**Created**: 2026-11-20

**Status**: Approved by the owner at G1 (2026-11-20, with trims recorded in tasks.md)

**Parent Issue**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)

**Input**: Add `pi_claim.py --mine` to list Project 1 In Progress items whose latest
trusted heartbeat owner equals the authenticated user, show heartbeat ages, and flag
`ok` (at most 10 minutes), `DUE` (over 10 minutes), or `STALE` (over 2 hours).
Keep the command read-only, with offline tests in the existing test module.

## Clarifications

### Session 2026-11-20

Headless clarification: no owner answers were requested or received. The following
recommendations are assumptions, not accepted decisions.

- **Q1: Should an In Progress item still be listed when its latest trusted marker names
  me but records `release` or `done`?** Recommended answer: **Yes, follow status and owner**
  (confirmed by the owner at G1, 2026-11-20). Why it matters: adding an active-action filter
  would hide inconsistent project state and narrow the issue's explicit eligibility rule.
  Reflected in FR-002 and Edge Cases.
- **Q2: What should happen when `--mine` is combined with another mode or transition
  arguments?** Recommended answer: **Reject with a usage error**
  (confirmed by the owner at G1, 2026-11-20). Why it matters: a single unambiguous mode prevents
  accidental mutation or silently ignoring a requested transition. `--help` may still
  display help without accessing GitHub. Reflected in FR-008.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See only my current claims (Priority: P1)

As an agent or owner, I want one read-only command that lists my In Progress claims,
so I do not have to inspect issues one at a time or confuse another agent's work with mine.

**Why this priority**: Correct ownership and project-status filtering are the essential
value; heartbeat urgency is useful only for the correct set of claims.

**Independent Test**: Run `--mine` against controlled project items and trusted comment
history for two synthetic users. Verify only the current user's eligible issues appear,
including an eligible item on a later project page, and that no writes occur.

**Acceptance Scenarios**:

1. **Given** In Progress items owned by the current user and another user, plus Todo and
   Done items owned by the current user, **When** I run `--mine`, **Then** only the current
   user's In Progress items appear, with issue numbers and titles.
2. **Given** an older trusted marker owned by me and a newer trusted marker owned by another
   user, **When** I list my claims, **Then** that issue is absent.
3. **Given** an untrusted or malformed newer marker and a valid earlier trusted marker,
   **When** I list my claims, **Then** ownership follows the valid trusted marker, not the
   invalid newer one.
4. **Given** no eligible claims, including an empty project or no attributable heartbeat,
   **When** I run `--mine`, **Then** I receive a clear "no In Progress claims" message and
   successful completion, not a blank listing.
5. **Given** an authentication or project/comment lookup failure, **When** I run `--mine`,
   **Then** the failure is visible and the command does not claim there are no claims.

### User Story 2 - Identify overdue heartbeats (Priority: P2)

As an agent or owner viewing my claims, I want each heartbeat's age and urgency clearly
labelled so I can tell which claims need attention without calculating timestamps.

**Why this priority**: Distinguishes normal claims from missed heartbeats and abandoned work.

**Independent Test**: At a fixed observation time, list owned claims aged below, exactly
at, and just beyond each threshold; assert each displayed age and urgency.

**Acceptance Scenarios**:

1. **Given** eligible claims aged 5 minutes, 11 minutes, and 121 minutes, **When** I run
   `--mine`, **Then** they display `ok`, `DUE`, and `STALE`, respectively.
2. **Given** an age of exactly 10 minutes, **When** I list it, **Then** it is `ok`; at
   10 minutes 1 second it is `DUE`, even though the displayed whole-minute age is 10.
3. **Given** an age of exactly 2 hours, **When** I list it, **Then** it is `DUE`; at
   2 hours 1 second it is `STALE`, even though the displayed whole-minute age is 120.
4. **Given** overdue or stale claims, **When** I list them, **Then** the command reports
   their state without renewing, reclaiming, reassigning, or changing project status.

### Edge Cases

- Draft/non-issue items, absent content, and items without In Progress status are excluded.
- Missing, malformed, or untrusted heartbeat markers cannot establish ownership.
- Assignees do not override the latest trusted marker's owner.
- The latest trusted marker determines ownership even if its action is `release` or `done`
  while the project item still says In Progress; this exposes inconsistent state rather than
  inventing an additional active-action filter.
- Trust, timestamp parsing, and comment-history visibility follow existing claim semantics;
  this feature does not redesign the heartbeat protocol or extend comment pagination.
- Future-dated valid markers retain the existing signed age calculation and are `ok`;
  listing does not rewrite timestamps.
- Failure to retrieve required data is not an empty result.
- Combining `--mine` with a transition or another inspection mode must not execute a write.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Expose `--mine` as a documented standalone inspection mode.
- **FR-002**: Resolve the authenticated identity and include only Project 1 In Progress
  issue items whose latest trusted valid heartbeat owner equals that identity, using the
  existing ownership comparison and trusted-marker rules, not issue assignment.
- **FR-003**: Inspect all project item pages, skipping non-issues and ineligible statuses.
- **FR-004**: Show each matching issue's number, title, heartbeat age in whole minutes,
  and exactly one urgency label. Preserve project traversal order and use the existing
  listing convention of titles truncated to 60 characters.
- **FR-005**: Classify using the unrounded age: `STALE` when greater than 2 hours;
  otherwise `DUE` when greater than 10 minutes; otherwise `ok`. Whole-minute display
  truncation must not change threshold decisions.
- **FR-006**: Return success with a clear no-claims message when no eligible claims exist;
  unavailable identity or data must remain a visible failure rather than empty success.
- **FR-007**: Perform no GitHub writes, including comments, status changes, assignments,
  heartbeat renewal, or reclaim, on any `--mine` invocation.
- **FR-008**: Reject `--mine` combined with issue/action positionals, `--note`,
  `--list-stale`, or `--status` with a nonzero usage error before performing reads or writes.
  `--help` remains read-only and may take precedence.
- **FR-009**: Preserve existing command behavior when `--mine` is absent, including
  `--status`, `--list-stale`, transitions, and help/no-argument behavior.

### Key Entities

- **Project issue item**: Issue number and title, with the Project 1 Status used to
  determine whether the item is In Progress.
- **Trusted heartbeat**: Latest valid marker recognized by the existing collaborator
  trust rules, carrying owner, timestamp, and action.
- **Claim listing row**: Eligible issue identity, signed heartbeat age, and urgency label;
  an ephemeral view, not stored claim state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: One invocation shows all and only eligible claims in the supported project
  view; none of another user's claims or non-In Progress items appear.
- **SC-002**: All three urgency classes and both exact threshold boundaries are correct,
  including just-over-threshold cases before the next whole minute.
- **SC-003**: Listing causes zero changes to issues, project fields, assignments, or
  heartbeat records, regardless of displayed urgency.
- **SC-004**: Every successful empty listing is explicit, and every failed identity or
  data lookup is distinguishable from a successful empty result.
- **SC-005**: Existing claim commands retain their behavior when the new option is unused.

## Assumptions

- Existing GitHub authentication and access to Project 1 are available at runtime.
- The existing trusted-marker selection and exact owner equality are authoritative.
- Human-readable output is sufficient; JSON, sorting controls, automatic heartbeats,
  notifications, assignee fallback, and new persistence are out of scope.
- Headless Phase 1 may proceed on documented recommended answers; G1 owner approval,
  sub-issue creation, committing, and execution are not authorized by this run.
- Q1 and Q2 were confirmed by the owner at G1 (2026-11-20).
  All other clarification categories are covered by explicit requirements or existing
  command semantics; no performance SLA, localization, or new data source is introduced.
