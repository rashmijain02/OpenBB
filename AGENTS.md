# Agent Instructions

Instructions for every coding agent in `rashmijain02/OpenBB` (GitHub Copilot CLI, Claude Code,
Codex and others). `CLAUDE.md` holds the full, binding rules; this file is the short version.

## Development strategy

Development follows **Dev Strategy v4**: `docs/dev-strategy.md` (approved 2026-11-20).

| Phase | Tool | Skill |
|---|---|---|
| 1. Specify and plan | GitHub Copilot CLI + Spec Kit | `openbb-spec`, then `openbb-issues` |
| 2. Execute (TDD, worktree, subagent review) | Claude Code + Superpowers | `openbb-execute` |
| 3. Ship (review, PR, CI) | GitHub Copilot CLI | `openbb-ship` |

Copilot CLI main agent: `copilot --agent openbb-orchestrator`. Small fixes stay in Copilot CLI;
tricky bugs and refactors go to Claude Code. `openbb-dev-cycle` routes to the right place.
Specs live in `specs/gh-<NN>-<slug>/`; principles in `.specify/memory/constitution.md`.

## Model policy (D1)

Name the model explicitly on every dispatch that accepts one; if it is unavailable, stop and
report. Never fall back to another model family.

- **Copilot CLI** (Phases 1 and 3, small fixes): GPT family, chosen by task complexity.
- **Claude Code** (Phase 2, tricky bugs and refactors): Claude models only.

This governs execution agents, not models the product deploys, trains, evaluates or documents.

## Tracking

- **No issue, no work.** GitHub Issues in `rashmijain02/OpenBB` are the only record, on the
  [Portfolio Intelligence Engine board](https://github.com/users/rashmijain02/projects/1/views/1)
  (Project 1, `--owner rashmijain02`).
- Claim and heartbeat with `.venv_portfolio\Scripts\python.exe scripts\pi_claim.py <NN> in-progress|heartbeat|release`.
- Cite issues as `#NN (short title)`. Commit bodies carry `Closes #NN` or `Refs #NN`, one per line.
- Do not use beads (`bd`), local task tools, or scratch TODO files. The one exception: Claude
  Code may mirror `tasks.md` in TodoWrite during a Phase 2 session (D3).
- Durable lessons go in `docs/MEMORIES.md`. Issue numbers from before 2026-11-02 use the legacy
  numbering: `docs/migration/legacy-issue-map.md`.

## Git authority (D6)

- Without asking: read, test, verify, claim/heartbeat, set board fields, commit on your own
  feature branch, create up to 3 issues.
- Ask each time before: `git push`, `gh pr create`, `gh pr merge`, closing issues by hand,
  creating more than 3 issues.
- Every `gh` call uses `--repo rashmijain02/OpenBB`. Never target another owner's repository;
  `upstream` is fetch-only.
- Work on `feat|fix|docs/<topic>-gh-<NN>` side branches. Never commit or merge into `portfolio`,
  `portfolio_validations` or `develop`; the owner merges PRs.

## Environment

- Python: `.venv_portfolio\Scripts\python.exe`. Run `black --check` and `ruff` before handing off.
- Data providers: `fmp_cached` first, `fmp` only as a tracked fallback, never yfinance.
- Never read brokerage exports directly; keep credentials and personal paths out of code, logs,
  issues and PRs. Commit notebooks stripped.

## Non-interactive shell commands

Shell commands like `cp`, `mv` and `rm` may be aliased to interactive mode on some systems, which
makes an agent hang waiting for y/n input. Use the non-interactive forms:

```bash
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

Also: `scp` / `ssh` with `-o BatchMode=yes`, `apt-get -y`, `HOMEBREW_NO_AUTO_UPDATE=1` for `brew`.
