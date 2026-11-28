# Model selection

This applies to all future work in this repo. These are defaults under D1 (`docs/dev-strategy.md`), not pins; revisit as models change.

| Tier | Use for |
|---|---|
| Sonnet (default) | Well-specified implementation, docs and skill edits, review-comment fixes, test writing, routine reviews, CI evidence |
| Opus | Design and specs, ambiguous requirements, high-risk or cross-cutting changes (security, auth, data migration and retention, concurrency, brokerage and personal data), tricky-bug root cause, security review of sensitive diffs, final review of large batches |

## Rules

- Start with Sonnet; escalate to Opus when a subagent stalls, needs a second retry, or review finds correctness issues.
- For high-risk changes the reviewer's tier is at least the implementer's.
- Split an issue instead of escalating when the brief will not fit the 100K context budget.
- Name the model on every dispatch; do not rely on the session default.
- Defaults under D1, not pins; revisit as models change.
