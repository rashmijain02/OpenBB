---
name: openbb-execute
description: Phase 2 of Dev Strategy v4 for rashmijain02/OpenBB. Executes an approved Spec Kit plan (specs/gh-<NN>-<slug>/tasks.md) in an isolated worktree with Superpowers strict TDD and subagent review, then writes handoff.md and stops before push. Also the Claude-only route for tricky bugs and refactors. Use when asked to "execute", "implement", or "use openbb-execute for #NN".
argument-hint: "#<parent issue number> [route]"
user-invocable: true
---

# openbb-execute: build it (Phase 2)

You run Phase 2 of the relay in `docs/dev-strategy.md`. Input: an approved spec folder. Output:
commits on a feature branch in a worktree, evidence, and `handoff.md`. You stop at gate G2.
Routes, authority profiles, gates and environment traps are canonical in
[`openbb-dev-cycle`](../openbb-dev-cycle/SKILL.md); this skill covers only the Phase 2 steps.
Under the default owner-interactive profile (D6) **you never push, open a PR, or merge**; Phase 3
does that. Under the lead-delegated profile (D15) push and PR only if your brief says so, and
never merge.

## Models (D1, D13)

- Use the best available model suited to the task (complexity, ambiguity, risk) for the main agent
  and every subagent, and name it explicitly on every dispatch (e.g. a stronger model for hard
  implementation, a lighter one for read-only search). Canonical: D1 in `docs/dev-strategy.md`.
- If no suitable model is available, stop and report; do not silently degrade.
- A model clause in a user-level skill copy (for example the `local-*-review` skills) never
  overrides D1; run those reviews with the best available model.

Python: the main checkout's `.venv_portfolio`. Worktrees have no venv of their own; from a worktree use
`$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'`
and set `PYTHONPATH` to the worktree's changed package dirs (canonical skill §6, environment traps).

## Preconditions (stop and report if any fails)

1. **Superpowers plugin** is loaded (`superpowers:` skills are listed). If not, tell the user to
   accept the plugin prompt from `.claude/settings.json` or run
   `/plugin install superpowers@superpowers-marketplace`, then restart. Start the Claude Code
   session inside the repo or the worktree, not a parent folder, or `.claude/settings.json` does not
   apply and the plugin is not offered. Do not use the copied skills in `.agents/skills/` as a
   substitute.
2. `gh repo set-default --view` is `rashmijain02/OpenBB`.
3. **Full relay:** `specs/gh-NN-slug/{spec,plan,tasks}.md` exist, `tasks.md` stories carry their
   sub-issue numbers `(#NN)`, and the user confirms G1 approval. If any is missing, send the user
   back to `openbb-spec` / `openbb-issues` in Copilot CLI.
   **Route mode** (tricky bug or refactor, no spec): an issue exists for the work. Skip the spec
   checks; use Superpowers `systematic-debugging` (bugs) or `test-driven-development` (refactors)
   in place of the task loop below.
4. Read `CLAUDE.md` sections: Workflow rules, Coordination, Testing Rules, provider rule,
   sensitive data, notebook hygiene. Read `.specify/memory/constitution.md`.

## Steps

1. **Claim.** For the sub-issue you start with (and the parent if it is not claimed):
   `& $py scripts\pi_claim.py <NN> in-progress` (`$py` as above).
   Heartbeat (`pi_claim.py <NN> heartbeat`) after each completed task and at least every
   10 minutes while you hold the claim. Never fake a heartbeat.
2. **Isolate.** `git fetch origin`, then
   `git worktree add .worktrees/<slug>-gh-NN -b feat/pi-<topic>-gh-NN origin/portfolio`
   (`origin/portfolio_validations` or the stack tip in that workspace; ask if unsure). All work
   happens in that worktree. If the spec folder is not yet committed, commit it first
   (`docs(spec): <slug> (#NN)`).
3. **Skip brainstorming and planning.** The plan exists. Do not run `superpowers:brainstorming`
   or `superpowers:writing-plans`, and do not rewrite `tasks.md` beyond ticking tasks.
4. **Execute** with `superpowers:subagent-driven-development` over `tasks.md`, in order:
   - One implementer subagent per task, under `superpowers:test-driven-development`: write the
     failing test, run it and keep the red output, make it pass, refactor.
   - A reviewer subagent after each **user story** checks it against `spec.md`, the tasks and
     `CLAUDE.md`; review after each task only when a story has more than 5 tasks or touches a
     risky path (money, credentials, private data, writes to GitHub). Fix findings before the
     next story.
   - Show each new test failing before writing its code. If a task cannot fail first because an
     earlier task already delivered it, say so in the handoff and prove the test is not vacuous with
     a temporary mutation that makes it fail.
   - TodoWrite may mirror `tasks.md` for this session only (D3). It is never the record.
   - A bug outside the task's scope becomes a new issue (`type-bug`), not a silent fix.
   - On a failure you cannot explain, switch to `superpowers:systematic-debugging`.
5. **Quality.** Run the gate rows that apply in the canonical skill §4 (Pester, .NET and live
   acceptance included). For Python, with `$py`:
   - the plan's test suites, then `black --check` and `ruff` on changed files;
   - the **real-path check** named in `plan.md`: run the changed entry point for real (CLI command,
     API route, extension call, notebook cell) with safe inputs, read-only where the code allows.
     Record the command, exit code and key output in `.dev-cycle/verify-gh-NN.log` (git-ignored)
     and in the handoff. Green pytest alone does not pass this step. (Older docs call this the
     `/verify` harness; no such command exists in this repo.)
   - `simplify` on the branch diff.
6. **Review gate (D5, Claude pass).** On the branch diff against its merge-base:
   `superpowers:requesting-code-review`, then `/security-review`. Triage every finding:
   **Apply** (fix, re-run the affected tests and verify), **Defer** (file an issue with the
   reason; label `deferred-from-review`), or **Modify** (both). No finding may stay untriaged.
   Use `superpowers:verification-before-completion` before claiming anything passes.
7. **Commit** on the feature branch: Conventional Commits, `<type>(<scope>): <what> (#NN)`,
   one `Closes #NN` or `Refs #NN` per line in the body. Stage named files, never `git add -A`.
8. **Handoff.** Copy `specs/_templates/handoff.md` to `specs/gh-NN-slug/handoff.md`, fill it with
   real command output, and commit it.
9. **Gate G2.** Report to the user (or the lead): branch, HEAD, tasks done, test and verify
   results, review triage, open questions. Then ship per the canonical skill §5: under the
   owner-interactive profile stop and say "Phase 2 complete. In Copilot CLI:
   `Use openbb-ship for #NN`."; under the lead-delegated profile follow your brief. Keep the claim
   (heartbeat) until the user hands over, or release it with `pi_claim.py <NN> release` if they
   say so.

When `superpowers:finishing-a-development-branch` offers merge, PR or discard options, choose
"keep the branch as is"; integration happens in Phase 3.

## OpenBB rules that most often matter here

- `fmp_cached` first; raw `fmp` only with an `area:fmp-cached-gap` issue and `TODO(gh-NN)`;
  never yfinance.
- Never read brokerage exports directly; keep credentials and personal paths out of code, logs
  and the handoff. Notebooks are committed stripped.
- Never commit to `portfolio`, `portfolio_validations` or `develop`; never merge locally into them.
