---
description: Execution model policy by role for repository agents and subagents (Dev Strategy v4, D1)
applyTo: '**'
---

# Agent Model Policy (Dev Strategy v4, D1)

You are running in GitHub Copilot CLI or another Copilot surface.

- Copilot runs Phase 1 (specify, plan, issues), Phase 3 (ship) and the small-fix route of
  `docs/dev-strategy.md`. Use **GPT-family** models for these, chosen by task complexity.
- Name the selected model explicitly whenever an agent-dispatch interface accepts one. Do not rely
  on a session default.
- If the model you need is unavailable, stop and report the blocker. Do not fall back to a model
  from another family.
- Phase 2 (execute) belongs to Claude Code with Claude models. Do not run it here; hand off with
  "Use openbb-execute for #NN" in Claude Code.
- This policy governs execution agents. It does not restrict models that the repository deploys,
  trains, evaluates, documents, or exposes as product functionality.
