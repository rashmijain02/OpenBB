---
description: Start or resume development in rashmijain02/OpenBB (routes to Dev Strategy v4)
argument-hint: "[#issue] [what you want to do]"
---

# /openbb-dev-cycle

Arguments: $ARGUMENTS

The development cycle is **Dev Strategy v4** (`docs/dev-strategy.md`). You are in Claude Code,
which runs **Phase 2 (execute)** and the **tricky-bug / refactor route**. Copilot CLI runs
Phase 1 (`openbb-spec`, `openbb-issues`) and Phase 3 (`openbb-ship`).

1. Identify the issue. If there is none, help the user write one and create it only after they
   agree (`gh issue create --repo rashmijain02/OpenBB`, then add it to
   [Project 1](https://github.com/users/rashmijain02/projects/1/views/1)). No issue, no work.
2. Decide the situation:
   - `specs/gh-<NN>-<slug>/` exists with an approved spec, plan and tasks: run the
     `openbb-execute` skill for that issue.
   - It is a tricky bug or refactor with no spec: run `openbb-execute` in route mode.
   - There is no spec and it is a feature: stop and tell the user to run Phase 1 in Copilot CLI:
     `copilot --agent openbb-orchestrator`, then "Use openbb-spec for #<NN>".
   - A `handoff.md` already exists: stop and tell the user to ship from Copilot CLI:
     "Use openbb-ship for #<NN>".
3. Never push, open a PR or merge from here (D6). Phase 3 does that, asking each time.
