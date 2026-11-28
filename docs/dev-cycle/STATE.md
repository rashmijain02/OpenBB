# Dev-cycle state and operating model

Recorded 2026-11-27 for #1314 (record dev-cycle state and lead/subagent operating model). This
file is the canonical home of the **operating model** (rules OM1–OM9 below). The development
strategy and its decisions live in [`docs/dev-strategy.md`](../dev-strategy.md); the procedure that
applies them lives in the canonical skill
[`.claude/skills/openbb-dev-cycle/SKILL.md`](../../.claude/skills/openbb-dev-cycle/SKILL.md).

## Inventory

| Layer | Item | Where | Tool | Status |
|---|---|---|---|---|
| 1. User-level (not in git) | `openbb-dev-cycle`, `local-code-review`, `local-security-review`, `local-privacy-review`, `development-orchestrator` | `~/.claude/skills/` and identical copies in `~/.copilot/skills/` | both | Not versioned. Their model clauses say GPT-only with no non-GPT fallback. Refreshed from the repo by the owner (see the skill's sync note). |
| 2. Repo, Dev Strategy v4 | `openbb-spec`, `openbb-issues`, `openbb-ship` | [`.github/skills/`](../../.github/skills/) | Copilot CLI | Phases 1 and 3, small-fix route |
| 2. Repo, Dev Strategy v4 | `openbb-execute` | [`.claude/skills/openbb-execute/`](../../.claude/skills/openbb-execute/SKILL.md) | Claude Code | Phase 2, tricky-bug/refactor route |
| 2. Repo, Dev Strategy v4 | `speckit-*` | `.github/skills/` and `.claude/skills/` | both | Spec Kit commands |
| 2. Repo | `openbb-dev-cycle` | [`.claude/skills/openbb-dev-cycle/`](../../.claude/skills/openbb-dev-cycle/SKILL.md) | both | **Canonical** router, gates, authority profiles, env traps |
| 2. Repo (legacy) | `/openbb-dev-cycle` command | [`.claude/commands/openbb-dev-cycle.md`](../../.claude/commands/openbb-dev-cycle.md) | Claude Code | Thin pointer to the canonical skill |
| 2. Repo | Model policy for Copilot | [`.github/instructions/agent-model.instructions.md`](../../.github/instructions/agent-model.instructions.md) | Copilot | Matches D1 |
| 3. Helpers | `scripts/pi_claim.py` | [`scripts/pi_claim.py`](../../scripts/pi_claim.py) | both | Targets `rashmijain02` Project 1; safe to run |
| 3. Helpers | `scripts/local_ci.py` | not yet on `portfolio` | both | Local CI gate; only on the unmerged branch for #1274 (Workspace browser and performance acceptance) / #1275 (quality and local review release gates) |

## Gaps found (2026-11-27)

| # | Gap | Resolution |
|---|---|---|
| G1 | User-level skills mandate GPT-only execution and "never a non-GPT fallback", so a Claude Code run reported the security review BLOCKED, although D1 assigns Phase 2 to Claude. | D13 in `docs/dev-strategy.md`: D1 is per tool and overrides model clauses in any skill copy. The canonical skill states it; the owner re-syncs the user-level copies. |
| G2 | Overlapping entry points (`/openbb-dev-cycle` command, `openbb-execute`, `.github/skills/openbb-*`, user-level skill); none canonical for Claude-only routes. | `.claude/skills/openbb-dev-cycle/SKILL.md` is canonical; the others link to it. |
| G3 | The owner's operating model was not in the repo. | OM1–OM9 below; D14 in `docs/dev-strategy.md`. |
| G4 | No CI or workflow runs `deploy/windows` Pester tests or `services/windows` .NET tests. The Windows installer shipped with 5+ defects (#1311, Windows service install cannot reach a healthy state). | Gate checklist in the canonical skill requires them locally when those paths change. Adding them to local CI is follow-up work. |
| G5 | No gate guidance for PowerShell/Pester (needs pwsh 7 with Pester 4.10.1; Windows PowerShell 5.1 only has Pester 3.4), .NET tests, or live acceptance that needs admin/UAC. | Gate checklist plus a human-in-the-loop live-acceptance template in the canonical skill. |
| G6 | No route for ops or design-only work. | "Ops / design-only" route in the canonical skill. |
| G7 | Environment traps were tribal knowledge (no global git identity on the dev host; worktree imports resolving to the main checkout; PowerShell here-strings piped to `git commit -F -`; Black 88 vs ruff 122). | "Environment traps" in the canonical skill. |

## Operating model

Owner decision, 2026-11-27. These rules are canonical here; other documents link to them.

| ID | Rule |
|---|---|
| OM1 | `portfolio` remains the main feature-integration branch. |
| OM2 | The lead orchestrates only. All feature and issue work is done by subagents, each in its own worktree under `.worktrees/`. |
| OM3 | One subagent per issue. It handles that issue and its PR review comments, then is retired. The next issue gets a fresh subagent. |
| OM4 | Token economy: each subagent's context stays at 100K tokens or less (tight briefs, file pointers, split oversized issues). |
| OM5 | Group meaningful related issues into one branch and PR before running long CI (local CI, full suites, live acceptance), so expensive gates run once per batch. |
| OM6 | Claude models are approved for Claude Code execution (D1). |
| OM7 | The lead may merge into `portfolio` once the local code, security and privacy reviews and local CI are clean on the PR diff against `portfolio`. |
| OM8 | Local CI (`scripts/local_ci.py --merged-with origin/portfolio`) is the permanent merge gate, not GitHub Actions. Local CI is always a merge gate: until it lands on `portfolio`, the lead runs, locally, every GitHub Actions job the PR's changed files would trigger (commands from `.github/workflows/*.yml`), posts the evidence in a PR comment, and names any job that cannot be reproduced (never counted as passed). No merge without that evidence. |
| OM9 | Up to 2–3 implementer slots and 2–3 review slots run in parallel; the lead serializes merges. |

OM1–OM5 are new on 2026-11-27; OM6–OM9 were already standing owner decisions and are recorded
here so they live in the repo.
