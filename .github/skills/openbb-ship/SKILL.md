---
name: "openbb-ship"
description: "Phase 3 of Dev Strategy v4 for rashmijain02/OpenBB: independent local review, push and PR into portfolio (asking first), CI watch, findings loop and close-out. Use when Claude Code has finished Phase 2 and the user says ship, open the PR, or 'use openbb-ship for #NN'. Also ends the small-fix route."
compatibility: "Requires gh authenticated as rashmijain02 and the personal local-code-review, local-security-review and local-privacy-review skills"
metadata:
  author: "rashmijain02"
  strategy: "docs/dev-strategy.md"
---

# openbb-ship: review, publish, converge (Phase 3)

You run Phase 3 of the relay in `docs/dev-strategy.md`. Input: a feature branch with commits and
`specs/gh-NN-slug/handoff.md` (or, on the small-fix route, a `fix/<topic>-gh-NN` branch). Output:
a fork-internal PR with green CI and every finding resolved, merged by the owner.

Model (D1): GPT family, named explicitly on every dispatch. If unavailable, stop.

## Authority (D6)

Ask the user, each time, before: `git push`, `gh pr create`, `gh pr merge`, closing issues by
hand. A "yes" covers that one action only. You may, without asking: read, run tests, run the
local reviews, comment review triage on the PR you opened, heartbeat the claim, and set board
Status. Never merge; the owner merges. Promotion PRs (`portfolio_validations → portfolio`,
`portfolio → develop`) only when the owner asks for that exact PR.

## Steps

1. **Read the handoff.** Check out the branch (or `cd` into its worktree). Confirm HEAD matches
   `handoff.md`. If it does not, stop and ask.
2. **Independent review (D5, Copilot pass).** Run `local-code-review`, `local-security-review`
   and `local-privacy-review` (personal skills in `~\.copilot\skills`) against the same
   merge-base, HEAD and working tree, including relevant untracked files. Keep findings with
   confidence ≥ 70; reject a finding only with concrete refuting evidence at ≥ 85. If a skill is
   missing, report BLOCKED; do not skip the gate. All three must PASS on the same snapshot.
   - Small findings (lint, typo, a one-line guard): fix here with a failing test where it applies,
     commit, and re-run the affected review.
   - Anything else: hand back to Claude Code as new tasks ("Use openbb-execute for #NN: fix
     <finding>") and stop.
3. **Push** (ask first): `git push -u origin <branch>`.
4. **Open the PR** (ask first):
   ```bash
   gh pr create --repo rashmijain02/OpenBB --base portfolio --head <branch> \
     --title "<type>(<scope>): <what> (#NN)" --body-file <tmp>
   ```
   Body: summary against `spec.md`, the user stories with their issues as `#NN (title)`, one
   `Closes #NN` per line (CI `closes-syntax-check.sh`), the test and verify evidence from
   `handoff.md`, and the review triage table. Base is `portfolio_validations` (or the stack
   parent) in that workspace.
5. **Watch CI** (`gh pr checks <pr> --watch`). Fix lint and workflow failures here; send real
   test or logic failures back to Phase 2.
6. **Converge.** Re-run the three local reviews on each new HEAD. Loop until every finding is
   applied and verified, or deferred with an issue (`deferred-from-review`, written reason).
   Filing an issue is progress, not exit. After 5 rounds without convergence, stop and show the
   user the open findings.
7. **Owner merges.** Tell the user the PR is ready; do not merge it.
8. **Close out** after the owner merges: set board Status to Done
   (`pi_claim.py <NN> done` or the Status field), confirm `Closes` closed the issues (in this
   fork `Closes` into `portfolio` may not auto-close; ask before closing by hand), append lessons
   to `docs/MEMORIES.md` on a `docs/` branch if there are any, and remove the worktree
   (`git worktree remove .worktrees/<name>`).

## Never

- Target any repo but `rashmijain02/OpenBB`, or any project but Project 1.
- Push to `portfolio`, `portfolio_validations` or `develop`.
- Treat a bot approval or a small diff as permission to merge.
