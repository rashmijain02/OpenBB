---
name: "openbb-spec"
description: "Phase 1 of Dev Strategy v4 for rashmijain02/OpenBB: turn an issue into an approved spec, plan and tasks with Spec Kit. Use when the user asks to specify, plan, or start a feature in Copilot CLI."
compatibility: "Requires Spec Kit (.specify/) and gh authenticated as rashmijain02"
metadata:
  author: "rashmijain02"
  strategy: "docs/dev-strategy.md"
---

# openbb-spec: specify and plan (Phase 1)

You run Phase 1 of the relay in `docs/dev-strategy.md`. You produce `spec.md`, `plan.md` and
`tasks.md` for one feature and stop at gate G1. You do not write production code, cut branches,
push, or open PRs.

Model (D1): best available for the task. Name the model explicitly on any dispatch; if none is suitable, stop.

## Preconditions (stop and report if any fails)

1. `git remote get-url origin` is `rashmijain02/OpenBB`, and `gh repo set-default --view` is
   `rashmijain02/OpenBB`.
2. There is a **parent issue** for the feature on the
   [Portfolio Intelligence Engine board](https://github.com/users/rashmijain02/projects/1/views/1).
   If there is none, draft its title and body, show them to the user, and create it only after
   they agree (`gh issue create --repo rashmijain02/OpenBB`, then
   `gh project item-add 1 --owner rashmijain02 --url <issue-url>`). No issue, no work.
3. `.specify/memory/constitution.md` exists and its "Last Amended" date is not older than the
   newest change to `CLAUDE.md` rules it cites. If it is stale, tell the user and suggest
   `/speckit-constitution`; do not continue on a stale constitution without their agreement.
4. Read `CLAUDE.md` (Fork independence, Workflow rules, Coordination, Testing Rules, provider rule,
   sensitive-data rules). They are binding inputs to the spec.

## Steps

Let `NN` be the parent issue number and `slug` 2–4 lowercase words joined by hyphens.

**Keep it proportionate.** Size the artifacts to the change. For a change of under about 200 lines
of code, keep `spec.md` to about 80 lines and skip `research.md`, `data-model.md`, `quickstart.md`
and `contracts/` unless they carry something the plan needs. If the change is one file and the
fix is obvious, stop and suggest the small-fix route instead.

**Headless runs.** If the owner cannot answer during the run, record each `/speckit-clarify`
question with your recommended answer as an assumption marked "(pending owner confirmation at G1)".

1. **Fix the folder.** `SPECIFY_FEATURE_DIRECTORY=specs/gh-NN-slug` (D2). Pass this value
   explicitly to `/speckit-specify` so it does not create a numbered folder. Spec Kit's `git`
   branching extension is intentionally not installed; do not install it and do not create a
   branch.
2. `/speckit-specify` with the issue's problem statement and acceptance criteria as input.
   Include the issue reference in the spec header as `#NN (title)`.
3. `/speckit-clarify`. Ask the user the questions it raises; record answers in the spec.
4. `/speckit-plan`. The plan must name: files to change, the test strategy (which failing tests
   come first, which fixtures), the **real-path check** (the exact command that runs the changed
   entry point for real, read-only where possible), provider use (`fmp_cached` first), and any
   private-data handling.
5. `/speckit-tasks`. Group tasks by user story. Each task is small enough for one red-green-refactor
   cycle, names its test, and **can start red**: do not split a value from the display that shows it,
   or put a behaviour in one task and its only observable effect in a later one.
6. `/speckit-analyze`, asking it also to flag tasks that cannot start with a failing test. Fix every
   inconsistency it reports, or list it for the user.
7. **Gate G1.** Show the user a short summary: the spec folder, user stories, task count, open
   risks. Ask for approval. Do not continue without it.
8. After approval, hand off to `openbb-issues` to create the sub-issues. Do not use
   `/speckit-implement`; Phase 2 (`openbb-execute` in Claude Code) replaces it.

## Committing the spec

The spec folder must be committed before Phase 2 (G1). Commit it on the Phase 2 branch when
Claude Code cuts it, or, if the user prefers, on a `docs/spec-<slug>-gh-NN` branch. Ask the user
which; never commit to `portfolio`, `portfolio_validations` or `develop` directly.

## Output to the user

```text
Phase 1 complete for #NN (<title>)
Spec: specs/gh-NN-slug/{spec,plan,tasks}.md
User stories: <n>  Tasks: <n>
Next: openbb-issues (creates <n> sub-issues), then in Claude Code:
  "Use openbb-execute for #NN"
```
