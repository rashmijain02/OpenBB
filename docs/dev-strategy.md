# Dev Strategy v4

Owner: Rashmi Jain · Approved: 2026-11-20 (decisions D1–D12); amended 2026-11-27 (D13–D17, #1314) · Tracking: #1277 (Adopt Dev Strategy v4)
Tracker: [Portfolio Intelligence Engine](https://github.com/users/rashmijain02/projects/1/views/1) (Project 1)

Plan and ship in **GitHub Copilot CLI** with Spec Kit. Execute in **Claude Code** with
Superpowers (worktrees, strict TDD, subagent review). GitHub Issues on Project 1 remain the only
record of work. Every rule in `CLAUDE.md` that this document does not amend stays in force.

This document replaces the 10-phase `openbb-dev-cycle` skill, the 8-phase `/openbb-dev-cycle`
command and the #1260 8-gate Copilot orchestration as the definition of the development cycle.
*Superseded in part 2026-11-27 (D16):* the procedure (routes, authority profiles, gates,
environment traps) now lives in the canonical repo skill
[`.claude/skills/openbb-dev-cycle/SKILL.md`](../.claude/skills/openbb-dev-cycle/SKILL.md); the
`/openbb-dev-cycle` command and the user-level skill copies route to it. The current inventory,
gaps and the lead/subagent operating model are in [`docs/dev-cycle/STATE.md`](dev-cycle/STATE.md).

## The relay

| Phase | Tool | Skill | Output | Gate |
|---|---|---|---|---|
| 1. Specify and plan | Copilot CLI + Spec Kit | `openbb-spec`, then `openbb-issues` | `specs/gh-<NN>-<slug>/{spec,plan,tasks}.md`, sub-issues on the board | **G1:** owner approves spec and plan; issues exist; spec folder committed |
| 2. Execute | Claude Code + Superpowers | `openbb-execute` | commits on `feat/pi-<topic>-gh-<NN>`, `handoff.md` | **G2:** all tasks green, verify log captured, no unresolved review findings, handoff written. Nothing pushed. |
| 3. Ship | Copilot CLI (or Claude Code on Claude-only routes, D15) | `openbb-ship` | PR into `portfolio`, local gates green | **G3:** local gates green (local CI is the merge gate, OM8), every finding fixed or filed; the owner merges, or the lead under D15 |

Phase 1 → 2 handoff: the spec folder plus the issue numbers. Phase 2 → 3 handoff:
`specs/gh-<NN>-<slug>/handoff.md` (template: `specs/_templates/handoff.md`).

Copilot CLI's main agent for Phases 1 and 3 is `.github/agents/openbb-orchestrator.agent.md`
(`copilot --agent openbb-orchestrator`).

## Routes by size

| Route | Tool | When | How |
|---|---|---|---|
| Full relay | both | A feature, or anything needing design | Phases 1 → 2 → 3 |
| Small fix | Copilot CLI (or a Claude Code subagent under D15) | One file, an obvious bug | Issue first, branch `fix/<topic>-gh-<NN>`, failing test first, then `openbb-ship`. No Spec Kit. |
| Tricky bug or refactor | Claude Code only | Hard to reason about, no spec needed | Issue first, `openbb-execute` in route mode (Superpowers `systematic-debugging` or `test-driven-development`), then `openbb-ship` |
| Portfolio validation | either | Fixes found while validating | Side branch off `portfolio_validations`, small-fix route (`portfolio-validation` skill) |
| Ops / design-only | either | Docs, design notes, skills, runbooks, CI config; no product behaviour change | See the route selector in the canonical `openbb-dev-cycle` skill (D17) |

## Decisions (approved 2026-11-20)

| ID | Decision | Effect |
|---|---|---|
| D1 | Model policy by role | Copilot phases use GPT-family models; Claude Code phases use Claude models (Opus main agent, Claude subagents). Every dispatch names its model; if it is unavailable, stop and report. No cross-family fallback. |
| D2 | Spec location and branches | Spec Kit writes to `specs/gh-<NN>-<slug>/` (set `SPECIFY_FEATURE_DIRECTORY`). Spec Kit's `git` branching extension is not installed; Phase 2 cuts the branch. `docs/superpowers/{specs,plans}` are frozen as an archive. |
| D3 | `tasks.md` and TodoWrite | `tasks.md` is a committed plan, not a tracker. TodoWrite is allowed only as an in-session mirror of `tasks.md` during Phase 2. Status lives on the board. |
| D4 | Issue granularity | One sub-issue per user story (sub-issue of the parent issue), tasks as a checklist in its body. Confirm before creating more than 3 issues. |
| D5 | Unified review gate | Claude: subagent review per task, then `/code-review` and `/security-review` before commit. Copilot: independent local code, security and privacy review on the same snapshot before push. CodeRabbit is not used. |
| D6 | Git authority | Standing permission: claims, heartbeats, board Status updates, commits on your own feature branch. Push, PR creation and merge ask each time (default, owner-interactive profile; see D15 for the lead-delegated profile). Never merge locally into an integration branch. |
| D7 | Portfolio validation | No direct commits to `portfolio_validations`; validation fixes use the small-fix route on side branches. |
| D8 | Superpowers source | The Superpowers plugin (`superpowers@superpowers-marketplace`) is declared in `.claude/settings.json`. The 13 copied skills in `.agents/skills/` are removed after the pilot. Not installed in Copilot for now. |
| D9 | Roles instead of personas | Owner (Rashmi Jain) approves and promotes. Reviewers are named by function (code reviewer, security reviewer, privacy reviewer). |
| D10 | Legacy instructions | `AGENTS.md` rewritten without beads; `.codex/` (beads hooks) removed; legacy workflow docs moved to `docs/archive/`. |
| D11 | #1260 orchestration | The Copilot orchestrator becomes the main agent for Phases 1 and 3, without a hard-coded model. |
| D12 | Create the skills | `openbb-spec`, `openbb-issues`, `openbb-ship`, `openbb-execute`, the router, the constitution and the handoff template. |

### Decisions added 2026-11-27 (#1314)

| ID | Decision | Effect |
|---|---|---|
| D13 | D1 is per tool and governs every skill copy | The tool decides the model family: Copilot → GPT, Claude Code → Claude. A "GPT-only" or "Claude-only" clause in any skill (including the user-level `local-*-review` skills) applies only when that skill runs in its own tool; it is never grounds for BLOCKED in the other tool. Approves Claude models for Claude Code execution (OM6). |
| D14 | Lead/subagent operating model | Rules OM1–OM9 are canonical in [`docs/dev-cycle/STATE.md`](dev-cycle/STATE.md#operating-model). |
| D15 | Lead-delegated authority profile | When the owner delegates a program to a lead, the lead may push, open PRs and merge into `portfolio` after clean local code/security/privacy reviews and local CI (OM7, OM8; local CI is always a merge gate, with evidence per OM8); subagents push and open PRs only when their brief says so. D6 stays the default (owner-interactive) profile. Table: canonical skill §3. Promotions are never delegated. Never push, open PRs, or write issues or comments to `prajoria/*`, `openbq-org/*`, `OpenBB-finance/*` or any upstream; `upstream` remotes are fetch-only. |
| D16 | Canonical dev-cycle skill | `.claude/skills/openbb-dev-cycle/SKILL.md` is the source of truth for routes, authority profiles, gates and environment traps; the owner copies it to the user-level `~/.claude/skills` and `~/.copilot/skills` (not in git). Other entry points link to it. |
| D17 | Gates beyond Python and the ops route | Pester under pwsh 7 + Pester 4.10.1, `dotnet test` for `services/windows`, a human-in-the-loop template for live acceptance needing elevation, and an ops/design-only route. Defined in the canonical skill §1 and §4. |

### Notes from implementation (2026-11-20)

- Spec Kit 1.4.x names its commands as skills with a hyphen: `/speckit-specify`, `/speckit-clarify`,
  `/speckit-plan`, `/speckit-tasks`, `/speckit-analyze`. There is no built-in `taskstoissues`;
  `openbb-issues` creates the issues with `gh`, because it must also set sub-issues and board fields.
- Copilot is the default Spec Kit integration; Claude is installed alongside (`.specify/integration.json`).
- D10 was narrowed: `rules/DEVELOPMENT_RULES.md` and `rules/FINANCETOOLKIT_RULES.md` are live
  technical standards (tests cite rule R7.1), so they stay. `rules/COLLABORATION_RULES.md`,
  `rules/DOCUMENTATION_RULES.md`, `context/` and `.github/copilot/` moved to `docs/archive/`.

## Pilot results (2026-11-20)

Pilot: #1279 (pi_claim: add `--mine` to list my claims and flag overdue heartbeats), run through all
three phases; PR #1283. What changed in the skills as a result:

| # | Friction | Change |
|---|---|---|
| 1 | `.venv_portfolio` does not exist inside worktrees | Skills use the main checkout's venv via `git rev-parse --git-common-dir` |
| 2 | `/verify` is not defined in this repo | Replaced by a **real-path check**: the plan names the exact command; the executor runs it and records output |
| 3 | Spec Kit produced ~650 lines of spec for ~60 lines of code | `openbb-spec` keeps artifacts proportionate and suggests the small-fix route for one-file changes |
| 4 | Superpowers absent when Claude Code starts outside the repo | Start Phase 2 sessions inside the repo or worktree |
| 5 | A task could not start red (value and its display were split) | Tasks must be able to start red; `/speckit-analyze` flags those that cannot |
| 6 | One reviewer per task is costly | Review per user story; per task only for large or risky stories |
| 7 | Headless clarify cannot ask the owner | Kept: recommended answers recorded as G1 assumptions |
| 8 | Pilot had to stack on this PR | Normal work cuts from `portfolio` once this merges |
| 9 | Copilot CLI cannot allow `gh pr create` without `gh pr merge` | Headless Copilot writes the PR body; the owner's executor runs `gh pr create` |

## Authority (D6)

This is the default, owner-interactive profile. The lead-delegated profile (D15) is defined in
the canonical skill §3.

| Action | Needs asking? |
|---|---|
| Read anything in the repo, run tests, run the verify harness | No |
| Claim, heartbeat or release an issue with `pi_claim.py`; set board fields | No |
| Commit on your own feature branch in a worktree | No |
| Create issues (1–3) | No; more than 3 at once: confirm the count first |
| `git push`, `gh pr create`, `gh pr merge`, close issues by hand | Yes, each time (under the lead-delegated profile, D15, see the canonical skill §3) |
| Promotion PRs (`portfolio_validations → portfolio`, `portfolio → develop`) | Only when the owner asks for that exact PR |

## Rollout

1. Setup and skills: this change (#1277).
2. Pilot: one Todo item from the board, end to end; friction recorded on its issue.
3. Retire: remove the 13 copied Superpowers skills from `.agents/skills/` once the pilot passes.
4. Review this document after three features have shipped through it.
