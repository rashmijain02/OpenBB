---
name: openbb-dev-cycle
description: Entry point for development in rashmijain02/OpenBB. Routes to Dev Strategy v4 (docs/dev-strategy.md) - Phase 1 specify/plan and Phase 3 ship in Copilot CLI, Phase 2 execute in Claude Code. Use when the user asks for the "dev cycle", to start or resume a feature, or is unsure which workflow applies.
---

# openbb-dev-cycle (router)

The development cycle for this repository is **Dev Strategy v4**: `docs/dev-strategy.md`
(approved 2026-11-20). This skill only decides where to go next. The earlier 10-phase cycle is
retired; its git history is the archive.

Tracking board: [Portfolio Intelligence Engine](https://github.com/users/rashmijain02/projects/1/views/1)
(Project 1, owner `rashmijain02`). No issue, no work.

## Where am I?

| Situation | Go to | Runs in |
|---|---|---|
| New feature, or anything needing design | `openbb-spec`, then `openbb-issues` | Copilot CLI |
| Spec approved (G1), sub-issues exist | `openbb-execute` | Claude Code |
| `specs/gh-<NN>-<slug>/handoff.md` exists (G2) | `openbb-ship` | Copilot CLI |
| Small fix: one file, an obvious bug | issue → `fix/<topic>-gh-<NN>` → failing test → `openbb-ship` | Copilot CLI |
| Tricky bug or refactor, no spec needed | `openbb-execute` (route mode) → `openbb-ship` | Claude Code, then Copilot CLI |
| Fix found while validating `portfolio_validations` | `portfolio-validation` | either |

If you are in the wrong CLI for the next step, say so and give the user the exact prompt to use in
the other one. Do not run another tool's phase yourself: the model policy is by role (D1), with GPT
models in Copilot CLI and Claude models in Claude Code.

## Always

- Authority (D6): claims, heartbeats, board Status and commits on your own feature branch are
  fine. Ask each time before push, PR creation, merge, or closing issues by hand.
- Every `gh` call targets `--repo rashmijain02/OpenBB`; the only project is Project 1.
- Issue numbers written before 2026-11-02 use the legacy numbering:
  `docs/migration/legacy-issue-map.md`.
