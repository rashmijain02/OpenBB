# Handoff: pi_claim --mine (pilot of Dev Strategy v4)

| Field | Value |
|---|---|
| Parent issue | #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats) |
| Sub-issues | #1280 (See Only My Current Claims), #1281 (Identify Overdue Heartbeats) |
| Branch | `feat/pi-claim-mine-gh-1279` |
| Base | `feat/dev-strategy-v4-gh-1277` @ `ae9ff6cb4` (stacked on PR #1278, which is stacked on #1276; see note) |
| HEAD (code) | `33765103a` |
| Worktree | outside the repo (pilot), not under `.worktrees/` |
| Executor model | Claude Opus 5.5 (main); reviewers Claude `sonnet` |

Base note: the pilot needs the Spec Kit scaffold and the new skills, which exist only on #1278's branch
until it merges. Normal features cut from `origin/portfolio`. When #1276 and #1278 merge, retarget this
PR to `portfolio`.

## Tasks

| Task (from tasks.md) | Status | Commit |
|---|---|---|
| T001 (incl. merged T002) ownership and trusted-marker filtering | done | `94fd54e9c` |
| T003 explicit empty result, visible failures | done | `94fd54e9c` |
| T004 `--mine` through `main()`, pagination, read-only transport | done | `94fd54e9c` |
| T005 reject `--mine` with other modes (exit 2, no gh calls) | done | `94fd54e9c` |
| T006 order, 60-char titles, help text, legacy dispatch | done | `94fd54e9c` |
| T007 ok / DUE / STALE at exact boundaries | done | `ecf4d56fe` |
| T008 signed whole-minute ages | done (passed on first run; see friction 5) | `ecf4d56fe` |
| T009 final gates and one real read-only run | done | `33765103a` (security fix) |

## Evidence

- **Tests:** `.venv_portfolio\Scripts\python.exe -m pytest -q -p no:cacheprovider openbb_platform/tests/test_pi_claim.py` → `13 passed` (baseline before the change: 2 passed). Every new test was seen failing before its implementation, except T008 (see friction 5); a temporary mutation (truncate instead of floor) made T008 fail, then the original was restored.
- **Format/lint:** `black --check` → clean for both files. `ruff check openbb_platform/tests/test_pi_claim.py` → all checks passed. `ruff check scripts/pi_claim.py` → 32 findings, all of kinds already present in the file before this change (D103 ×5, D401, PLR1714, PLW1510, S603, S607, T201 ×22); the only additions are 4 `T201` `print` calls, which is how this CLI reports results.
- **Real path (read-only, live board):** log `.dev-cycle/verify-gh-1279.log` (git-ignored):

```text
$ python scripts/pi_claim.py --mine
  #1277  age=32min (DUE)  [dev-env] Adopt Dev Strategy v4: Spec Kit + Copilot/Claude r
  #1279  age=2min (ok)  [dev-env] pi_claim: add --mine to list my claims and flag ov
  #1280  age=4min (ok)  [dev-env] See Only My Current Claims
  #1281  age=2min (ok)  [dev-env] Identify Overdue Heartbeats
exit=0

$ python scripts/pi_claim.py --mine --status 1279
usage error: --mine cannot be combined with --status
exit=2
```

  #1277 is correctly DUE: it is claimed but waiting for owner review, with no heartbeat sent while idle.
- **Claude review gate (D5):** code review per user story (Claude `sonnet`): US1 APPROVE, US2 APPROVE.
  Security review of the branch diff (Claude `sonnet`): PASS with one low finding, applied.

## Review findings

| Severity | Finding | Location | Action |
|---|---|---|---|
| should-fix | Heartbeat lookup reads only the first 100 comments (pre-existing, all modes) | `scripts/pi_claim.py` `latest_heartbeat()` | deferred #1282 (pi_claim: heartbeat lookup reads only the first 100 comments) |
| nit | Fixtures lighter than real GraphQL shapes (`content: {}`, `{}` field values, Status not first) | `openbb_platform/tests/test_pi_claim.py` | applied (`94fd54e9c`) |
| nit | `main()` catches only `RuntimeError` for `--mine` | `scripts/pi_claim.py` `main()` | no change: matches `--status`, `--list-stale` and transitions; other errors still exit nonzero |
| low (security) | Remote titles printed raw: terminal escape injection | `cmd_mine`, `cmd_list_stale` | applied (`33765103a`) with a test |

## Pilot friction (Dev Strategy v4) for the owner

1. **Python environment in worktrees.** `.venv_portfolio` exists only in the main checkout; the skills
   point at it relative to the current folder. Phase 1 reported it "absent". Fix: skills say "use the
   main checkout's `.venv_portfolio`".
2. **`/verify` is undefined.** No repository definition exists, and Copilot flagged it as a blocker.
   For this change, "verify" meant one real read-only run against the live board. Fix: define it in
   `openbb-execute` as "run the changed entry point for real and record the command and output".
3. **Spec size.** Phase 1 produced about 650 lines across 8 files for about 60 lines of code. Fix:
   `openbb-spec` asks for proportionate specs, or features this small use the small-fix route.
4. **Superpowers not loaded.** This Claude Code session started outside the repo, so
   `.claude/settings.json` did not apply and the plugin was absent. TDD and subagent review were
   followed directly. Fix: start Phase 2 sessions inside the repo (or worktree).
5. **Task split hid a red step.** T008 (age display) could not fail first because T007's green step
   needed the age in each row. Fix: Spec Kit tasks should not separate a display from the label shown
   with it; `openbb-spec` can ask `/speckit-analyze` to flag tasks that cannot start red.
6. **Per-task reviewer cost.** One reviewer per task (8) is heavy for a small change; this run used one
   per user story plus a security pass. Fix: `openbb-execute` reviews per user story, per task only for
   large stories.
7. **Headless clarify.** Copilot could not ask the owner during Phase 1; recording recommended answers
   as G1 assumptions worked well. Keep it.
8. **Base for pilots.** The new skills live only on #1278's branch, so the pilot is stacked three deep.
   Normal work cuts from `portfolio` once #1276 and #1278 merge.

## Open questions for the owner

- Apply friction fixes 1, 2, 3, 5 and 6 to the skills in #1278 before merging it?

## Not done / follow-ups

- #1282 (pi_claim: heartbeat lookup reads only the first 100 comments)
- Phase 3 (`openbb-ship`): independent Copilot review, push and PR, after the owner says yes.
