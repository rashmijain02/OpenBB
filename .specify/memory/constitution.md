# rashmijain02/OpenBB Constitution

Spec Kit reads this file during `/speckit-specify`, `/speckit-plan`, `/speckit-tasks` and
`/speckit-analyze`. It states the principles every spec and plan must satisfy. The detailed,
binding rules live in the files named under each principle; when they disagree with this summary,
those files win. Do not copy rule text here; link to it.

## Core Principles

### I. Fork independence
All work is pushed, reviewed and merged only inside `rashmijain02/*`. Every `gh pr` / `gh issue`
call targets `--repo rashmijain02/OpenBB`. Remote `upstream` is fetch-only.
Source: `CLAUDE.md` → "Fork independence".

### II. Issue first, board as the record
No issue, no work. Every feature has a parent issue on the
[Portfolio Intelligence Engine board](https://github.com/users/rashmijain02/projects/1/views/1)
(Project 1), and each user story becomes a sub-issue with Phase, Lane and Type set. Status lives on
the board, never in local task tools. `tasks.md` is a committed plan, not a tracker.
Source: `CLAUDE.md` → "Coordination — GitHub Issues only"; `docs/dev-strategy.md` (D3, D4).

### III. Test first (non-negotiable)
Every behaviour change starts with a failing test (red → green → refactor). Fixtures have
realistic shapes, empty results are loud, and seams are tested with real contracts. Green pytest
is not enough: the plan names a real-path check (the changed entry point run for real), and its
output is recorded.
Source: `CLAUDE.md` → "Testing Rules" (R1–R11); `rules/DEVELOPMENT_RULES.md` §7.

### IV. Data providers
`fmp_cached` first. Raw `fmp` only as a tracked fallback (an `area:fmp-cached-gap` issue plus a
`TODO(gh-NN)` at the call site). Never yfinance.
Source: `CLAUDE.md` → provider rule and FMP tier gate.

### V. Private data stays private
Brokerage exports, credentials and personal paths never enter the repo, GitHub artifacts, or
agent context. Notebooks are committed stripped; personal-data runs stay in the local sandbox.
Source: `CLAUDE.md` → "Sensitive data", "Notebook check-in hygiene", "Notebook local sandbox".

### VI. Integration flow
`develop → portfolio` is a one-way absorb. Work happens on issue-linked side branches named
`feat|fix|docs/<topic>-gh-<NN>`, cut from `portfolio` (or `portfolio_validations` in that
workspace), and merges only by PR. The owner merges; agents never merge locally into an
integration branch.
Source: `CLAUDE.md` → "Workflow rules"; `docs/dev-strategy.md` (D6).

## Technical Standards

- Python environment: `.venv_portfolio\Scripts\python.exe`. Run `black --check` before pushing
  (Black 88 and ruff 122 disagree; CI enforces both).
- Windows, database, FMP API and parsing patterns: `rules/DEVELOPMENT_RULES.md`.
- FinanceToolkit usage: `rules/FINANCETOOLKIT_RULES.md`.

## Development Workflow

Dev Strategy v4 (`docs/dev-strategy.md`): Phase 1 specify and plan in Copilot CLI (`openbb-spec`,
`openbb-issues`); Phase 2 execute in Claude Code (`openbb-execute`); Phase 3 ship in Copilot CLI
(`openbb-ship`). Specs live in `specs/gh-<NN>-<slug>/`. Do not run `/speckit-implement`;
Phase 2 replaces it.

## Governance

The owner, Rashmi Jain, approves amendments. Change this file and `docs/dev-strategy.md` in the
same PR, and record the decision in `docs/dev-strategy.md`.

**Version**: 1.0.0 | **Ratified**: 2026-11-20 | **Last Amended**: 2026-11-20
