# Research: List My Claims and Heartbeat Urgency

**Date**: 2026-11-20
**Parent**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)
**Method**: Direct repository/issue inspection; no external research or agents needed.

| Decision | Rationale | Alternatives considered |
| --- | --- | --- |
| One command in existing script | Matches `cmd_list_stale()` with minimal scope | New service or shared listing abstraction is unnecessary |
| Reuse `_project_items()` | Already follows GraphQL cursors | Legacy snapshot omits new items; duplicate queries add maintenance |
| Reuse `latest_heartbeat()` | Enforces trusted associations and parseable timestamps | Assignee fallback or new parser changes ownership semantics |
| Exact owner equality with `whoami()` | Matches acceptance and current lifecycle comparisons | Normalization or assignment-based membership changes the contract |
| No active-action filter (Q1, pending G1) | Eligibility is status plus latest trusted owner | Excluding release/done hides inconsistent project state |
| Reject mixed arguments (Q2, pending G1) | Prevents ambiguous dispatch and mutation | Precedence silently ignores arguments |
| Compare timedelta before formatting | Correct at 10m1s and 120m1s | Rounded-minute comparisons delay warnings |
| Preserve signed ages and title/order conventions | Matches current listings | Clock correction, sorting and JSON are out of scope |
| Monkeypatch existing tests, no network | User constraint and local style | Live GitHub calls risk side effects and nondeterminism |

## Observed Contracts

- `whoami()` decodes `gh api user` and hard-fails on authentication errors.
- `_project_items()` returns content number/title and named status fields; it paginates
  all project item pages.
- `latest_heartbeat()` reverses the returned comment list, skipping untrusted authors
  and malformed timestamps; currently it fetches at most the first 100 comments.
- `_age()` returns an aware UTC timedelta. Existing display uses
  `int(age.total_seconds() // 60)` and can show negative ages.
- `HEARTBEAT_INTERVAL_MIN=10`, `STALE_HOURS=2`. The issue explicitly uses strict `>`
  for urgency. Exactly two hours is `DUE` here; existing reclaim-at-equality is unchanged.
- Existing tests use importlib `_load_module()`, `_project_item()`, monkeypatch/capsys,
  fake GraphQL pages, and direct command assertions.

## Remaining Decisions and Risks

No technology choice remains unresolved. Two behavioral recommendations await G1 under
the headless override. The canonical venv is absent and `/verify` is not defined in
the inspected repository command locations. See `plan.md`; do not fabricate results
or install unrelated tooling during specification.
