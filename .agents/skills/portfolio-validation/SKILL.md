---
name: portfolio-validation
description: Small-fix route for validation work in the Portfolio Validation workspace of rashmijain02/OpenBB. Each fix found while validating goes on its own issue-linked side branch off portfolio_validations, with a failing test first, and ships through openbb-ship. Use when the user is validating or making small fixes on portfolio_validations. For features, use the full relay in docs/dev-strategy.md.
---

# Portfolio validation (small-fix route)

Dev Strategy v4 (`docs/dev-strategy.md`, D7) retired direct commits to `portfolio_validations`.
Validation fixes now follow the **small-fix route** on side branches, as the "Workspace override —
Portfolio Validation checkout" section of `CLAUDE.md` requires.

Tracking board: [Portfolio Intelligence Engine](https://github.com/users/rashmijain02/projects/1/views/1)
(Project 1, owner `rashmijain02`).

## Branch topology

```
portfolio ◀── promotion PR (only when the owner asks for that exact PR)
    ▲
portfolio_validations ◀── PR per fix (merged by the owner, in dependency order)
    ▲
fix/<topic>-gh-<NN>   ◀── all edits happen here
```

- Never commit to `portfolio_validations` or `portfolio` directly.
- Cut each side branch from `origin/portfolio_validations` (or the tip of an active stack rooted
  there). PRs target `portfolio_validations` (or the stack parent), always with
  `--repo rashmijain02/OpenBB`.
- Drain stacked PRs in dependency order and confirm `portfolio_validations` is clean before any
  promotion is proposed. The `portfolio_validations → portfolio` promotion PR is created only when
  the owner asks for that exact PR.

## Steps

1. **Issue first.** One issue per fix (`gh issue create --repo rashmijain02/OpenBB`, add to
   Project 1), then claim it: `.venv_portfolio\Scripts\python.exe scripts\pi_claim.py <NN> in-progress`.
2. **Branch.** `git fetch origin` and `git switch -c fix/<topic>-gh-<NN> origin/portfolio_validations`
   (a worktree under `.worktrees/` if other work is in progress in this checkout).
3. **Failing test first**, then the fix, then the relevant suite, `black --check` and `ruff`.
   For anything touching a real data path, run the `/verify` harness as well.
4. **Commit** on the side branch: `fix(<scope>): <what> (#NN)`, `Closes #NN` on its own line.
5. **Ship** with `openbb-ship` (Copilot CLI) targeting `portfolio_validations`; it asks before
   push and PR creation, runs the independent review, and leaves the merge to the owner.

If the fix grows beyond one or two files, or needs design, stop and move it to the full relay
(`openbb-spec` in Copilot CLI).

Authority (D6): claims, heartbeats, board Status and side-branch commits are fine; ask each time
before push, PR creation, merge, or closing issues by hand.
