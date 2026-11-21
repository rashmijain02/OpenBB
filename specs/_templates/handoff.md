# Handoff: <short title>

<!-- Copy to specs/gh-<NN>-<slug>/handoff.md at the end of Phase 2 (openbb-execute).
     openbb-ship (Phase 3) reads it. Keep it factual; paste command output, not assurances. -->

| Field | Value |
|---|---|
| Parent issue | #<NN> (<title>) |
| Sub-issues | #<NN> (<title>), … |
| Branch | `feat/pi-<topic>-gh-<NN>` |
| Base | `portfolio` @ `<merge-base sha>` |
| HEAD | `<sha>` |
| Worktree | `.worktrees/<name>` |
| Executor model | `<exact Claude model id>` |

## Tasks

| Task (from tasks.md) | Status | Commit |
|---|---|---|
| T001 … | done | `<sha>` |

## Evidence

- **Tests:** `<command>` → `<N passed, 0 failed>`
- **Verify harness:** `<command>`; log at `.dev-cycle/verify-<NN>.log` (key output pasted below)
- **Lint/format:** `black --check`, `ruff` → clean
- **Claude review gate:** `/code-review` → <result>; `/security-review` → <result>

```text
<key verify output>
```

## Review findings

| Severity | Finding | Location | Action (applied / deferred #NN) |
|---|---|---|---|

## Open questions for the owner

- …

## Not done / follow-ups

- … (each with an issue number)
