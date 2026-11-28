---
name: openbb-dev-cycle
description: Canonical entry point for development in rashmijain02/OpenBB. Picks the route (full relay, small fix, tricky bug/refactor, portfolio validation, ops/design-only), applies the per-tool model policy and the active authority profile (owner-interactive or lead-delegated), and lists the phase gates (tests, local reviews, local CI, Pester under pwsh 7, .NET, live elevated acceptance), the batching rule and environment traps. Use when asked to start or resume a development cycle, or when a lead dispatches a subagent for an issue. Never use for other repositories.
---

# openbb-dev-cycle (canonical)

This file is the repo source of truth for the development cycle. Where a rule lives elsewhere it
is linked, not copied:

- Strategy, phases and decisions D1–D17: [`docs/dev-strategy.md`](../../../docs/dev-strategy.md)
- Operating model OM1–OM9 and the inventory of skills: [`docs/dev-cycle/STATE.md`](../../../docs/dev-cycle/STATE.md)
- Binding repo rules (tracking, heartbeats, PII, notebooks, provider rule): [`CLAUDE.md`](../../../CLAUDE.md)

Activate only inside a `rashmijain02/OpenBB` checkout, after the user or the lead asks for a
cycle. Every `gh` call uses `--repo rashmijain02/OpenBB`; `upstream` is fetch-only.

## 1. Pick the route

No issue, no work: find or create the issue first (create only with the user's or lead's OK).

| Route | Use when | Tool | Path |
|---|---|---|---|
| Full relay | A feature, or anything needing design | Copilot → Claude Code → ship | Phase 1 `openbb-spec` + `openbb-issues`, Phase 2 [`openbb-execute`](../openbb-execute/SKILL.md), Phase 3 ship (§5) |
| Small fix | One file, obvious bug | Copilot CLI (or a Claude Code subagent under D15) | Branch `fix/<topic>-gh-<NN>`, failing test first, then ship (§5). No Spec Kit. |
| Tricky bug / refactor | Hard to reason about, no spec needed | Claude Code | `openbb-execute` in route mode, then ship (§5) |
| Portfolio validation | Fixes found while validating | either | Side branch off `portfolio_validations`, small-fix route (`.agents/skills/portfolio-validation`) |
| Ops / design-only | No product code: docs, design notes, skills, runbooks, CI or workflow config, board hygiene | either | Issue, branch `docs/<topic>-gh-<NN>` (or `chore/`), edit, run the "docs" gates in §4, ship (§5). No TDD or Spec Kit unless the change alters executable behaviour; if it does, switch to small fix. |

If a `specs/gh-<NN>-<slug>/handoff.md` already exists, the work is ready to ship (§5).

## 2. Models (per tool)

Canonical: D1 in `docs/dev-strategy.md`. In short: use the best available model suited to the
task (complexity, ambiguity, risk), in whichever tool you are running. Name the model explicitly
on every dispatch; if none is suitable, stop and report. Never pin a model family or ID as a
requirement; concrete names are examples only. A model clause inside any skill copy (including the
user-level `local-*-review` skills) is never a reason to report BLOCKED.

### Model selection

Sonnet is the default for well-specified work; escalate to Opus for design, ambiguous or high-risk work, tricky root causes and security or large-batch reviews.
Canonical guidance: [`docs/dev-cycle/model-selection.md`](../../../docs/dev-cycle/model-selection.md).

## 3. Authority profiles

Exactly one profile is active. If unsure, it is owner-interactive.

| Action | Owner-interactive (default; D6) | Lead-delegated (D15; owner delegated a program to a lead) |
|---|---|---|
| Read, test, verify, claim/heartbeat/release (`scripts/pi_claim.py`), board fields | No ask | No ask |
| Commit on your own feature branch | No ask | Subagent: yes, in its worktree |
| Create issues | Up to 3; more: confirm | Lead: up to 3; more: confirm with owner |
| `git push` of the feature branch, `gh pr create` into `portfolio` | Ask each time | Subagent: only when its brief says so; lead: yes |
| Address PR review comments on its own PR | Ask before push | Subagent that owns the issue (OM3) |
| `gh pr merge` into `portfolio` | Owner only | Lead only, after §4 gates are clean on the PR diff vs `portfolio` (OM7, OM8); merges serialized (OM9) |
| Promotion PRs (`portfolio_validations → portfolio`, `portfolio → develop`) | Only on the owner's explicit request for that exact PR | Same; never delegated |
| Local merge into `portfolio`, `portfolio_validations`, `develop` | Never | Never |

**Lead-delegated mechanics:** one fresh subagent per issue in its own worktree, lead orchestrates only (OM2–OM5); see [`docs/dev-cycle/STATE.md#operating-model`](../../../docs/dev-cycle/STATE.md#operating-model).

Never push, open PRs, or write issues or comments to `prajoria/*`, `openbq-org/*`, `OpenBB-finance/*` or any upstream; `upstream` remotes are fetch-only.

## 4. Gates

Run what applies to the changed paths. Record command, exit code and key output; green unit tests
alone do not pass a gate.

| Changed | Gate |
|---|---|
| Python | Focused pytest with `.venv_portfolio` (see §6 for worktrees); `black --check` and `ruff check` on changed files; the plan's real-path check (`openbb-execute` step 5) |
| Docs / skills only | `uvx codespell@2.4.1 <files>`; every repo path and link in the diff resolves; no absolute user paths, usernames or secrets |
| PowerShell (`deploy/windows/**`) | Pester under **pwsh 7 with Pester 4.10.1**: `pwsh -NoProfile -Command "Import-Module Pester -RequiredVersion 4.10.1; Invoke-Pester deploy/windows/tests -EnableExit"`. Windows PowerShell 5.1 ships Pester 3.4 and is not a valid runner. |
| .NET (`services/windows/**`) | `dotnet test services/windows/OpenBB.ServiceHost/tests/OpenBB.ServiceHost.Tests` (builds the test child too) |
| Anything needing admin/UAC or a real service/browser | Live acceptance, human in the loop (template below) |
| Every PR before merge | Local code, security and privacy reviews (`local-code-review`, `local-security-review`, `local-privacy-review`, canonical at `.claude/skills/<name>/SKILL.md`; in Claude Code `/code-review` and `/security-review` cover the first two) on the PR diff vs its base; every finding fixed or filed |
| Every batch before merge | Local CI: `scripts/local_ci.py --merged-with origin/portfolio` (OM8). Until `scripts/local_ci.py` is on `portfolio`, the lead runs, locally, every GitHub Actions job the PR's changed files would trigger (commands from `.github/workflows/*.yml`), posts the evidence in a PR comment, and names in that comment any job that cannot be reproduced (never counted as passed). No merge without that evidence. |

No CI workflow runs the Pester or .NET suites (STATE.md gap G4), so they are mandatory locally when
those paths change.

**Live elevated acceptance template.** Agents cannot answer UAC prompts. Write the steps into the
PR body or the issue, then ask the owner to run them:

```text
Live acceptance for #NN (<title>) — run in an elevated pwsh 7 window
Preconditions: <build/commit, config file, ports free>
1. <exact command>            Expect: <observable result>
2. <exact command>            Expect: <...>
Cleanup: <uninstall / stop command>
Report back: exit codes and the "Expect" lines that did not match.
```

The gate passes only on the owner's reported result; record it on the PR.

**Batching (OM5).** Cheap gates (focused tests, lint, docs checks, local reviews) run per issue.
Long gates (local CI, full suites, live acceptance) run once per batch: group meaningful related
issues into one branch and PR first, then run them.

## 5. Ship

- Copilot CLI: [`openbb-ship`](../../../.github/skills/openbb-ship/SKILL.md).
- Claude Code (Claude-only routes, or lead-delegated): run the §4 review and gate rows, then push
  and open the PR per the active profile: `gh pr create --repo rashmijain02/OpenBB --base portfolio`,
  title `<type>(<scope>): <what> (#NN)`, each `Closes #NN` alone on its own line.

## 6. Environment traps

- **No global git identity on the dev host.** Commit with
  `git -c user.name="<name>" -c user.email="<noreply email>" commit ...`.
- **Commit messages from PowerShell.** A here-string piped to `git commit -F -` is mangled; write
  the message to a temp file and use `git commit -F <file>`.
- **Worktree imports.** `.venv_portfolio` lives in the main checkout and its editable installs point
  at the main checkout's sources. From a worktree, resolve the interpreter with
  `git rev-parse --path-format=absolute --git-common-dir` and set `PYTHONPATH` to the worktree's
  changed package dirs (for example `openbb_platform/extensions/<ext>`) so tests import the
  worktree code, not the main checkout.
- **Line length.** CI Black uses 88 columns; `ruff.toml` allows 122. Always run `black --check`.
- **Pester version.** See §4: pwsh 7 + Pester 4.10.1, never Windows PowerShell 5.1.

## 7. Sync to user-level copies

This file is the source. The owner copies it to `~/.claude/skills/openbb-dev-cycle/SKILL.md` and
`~/.copilot/skills/openbb-dev-cycle/SKILL.md` after it changes on `portfolio`. Those directories
are not in git; agents never edit them. Until a copy is refreshed, this repo file wins over it.
