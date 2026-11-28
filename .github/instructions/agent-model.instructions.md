---
description: Execution model policy by role for repository agents and subagents (Dev Strategy v4, D1)
applyTo: '**'
---

# Agent Model Policy (Dev Strategy v4, D1)

You are running in GitHub Copilot CLI or another Copilot surface.

- Copilot runs Phase 1 (specify, plan, issues), Phase 3 (ship) and the small-fix route of
  `docs/dev-strategy.md`. Use the best available model for the task (D1), chosen by complexity, ambiguity and risk; never pin a model family.
- Name the selected model explicitly whenever an agent-dispatch interface accepts one. Do not rely
  on a session default.
- If no suitable model is available, stop and report the blocker. Never silently degrade.
- Phase 2 (execute) belongs to Claude Code. Do not run it here; hand off with
  "Use openbb-execute for #NN" in Claude Code.
- This policy governs execution agents. It does not restrict models that the repository deploys,
  trains, evaluates, documents, or exposes as product functionality.
