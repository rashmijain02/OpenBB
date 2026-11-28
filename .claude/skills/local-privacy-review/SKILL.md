---
name: local-privacy-review
description: Review a local Git change for personal-data, credential, notebook-output, logging, export, retention, and agent-context leaks. Uses data-flow evidence and redacted reports without reading private datasets or publishing findings.
---

# Local privacy review

Review the local checkout and data-handling code, not real people's records.
The configured model provider still processes permitted context; "local" does
not mean offline inference. Do not upload sensitive data to prove a leak.
This skill authorizes a read-only review, not edits, tests/builds, data
collection, network operations, deletion, or publication.

## Scope without leaking the evidence

1. Read current repository privacy, security, agent, notebook, export, and
   retention instructions. Do not invent a legal requirement or a consent
   decision when the repository/user has not specified one.
2. Confirm the actual local integration/stack base or explicit commit range.
   Inventory merge-base-to-working-tree tracked changes plus relevant
   nonignored untracked files, covering commits, staged/unstaged changes,
   deletions, and renames. Never silently omit generated assets.
3. Record base/HEAD IDs, included paths and safe-file content hashes,
   exclusions, and unreviewable files. Enumerate filenames first; redact even
   filenames if they identify a person or account. Patch reads must disable
   external diff and text conversion (`--no-ext-diff --no-textconv`).
4. Never open private exports, real account databases, credential files,
   browser profiles/cookies, or access-restricted files to inspect raw rows.
   Do not pipe raw matches from a broad secret/PII search into model context.
   Use metadata/schema-only inspection and approved, locally reviewed
   validators that return aggregates or redacted categories.
5. Treat notebook outputs, HTML reports, images, recordings, logs, snapshots,
   and test fixtures as potentially sensitive before displaying them. Do not
   render a personal-data notebook or screenshot to see whether it leaks.
   Inspect producer/sanitizer code and safe validation results instead.
6. If relevant artifact contents cannot be safely inspected or validated,
   report BLOCKED with the missing safe check. A filename or `.gitignore`
   match alone does not establish that the content is safe.

## Trace collection to exposure and disposal

- For changed data paths, identify data categories, collection purpose,
  minimization, access boundaries, recipients, persistence, retention/deletion
  paths, and transformation/redaction points. Mark unknown requirements
  explicitly rather than filling them in with assumptions.
- Follow data into API responses, logs/exception traces, telemetry, caches,
  temporary files, backups, notebook outputs, screenshots, public GitHub
  artifacts, and LLM/MCP prompts/tool responses.
- Check redaction runs before serialization/logging/tool dispatch, including
  error and retry paths. Evaluate reversible identifiers, partial masks,
  small-group aggregates, linkable pseudonyms, embedded metadata, and secrets
  in URLs/paths. A regex or hash does not automatically anonymize data.
- Check user/tenant isolation, export/download authorization, private-to-public
  migration boundaries, and missing deletion/retention propagation where the
  applicable policy requires it. Do not perform a live migration to test it.
- Check repository boundary enforcement and already-tracked/force-added
  artifacts; `.gitignore` is defense-in-depth, not a content or path guard.
- In OpenBB, enforce current `CLAUDE.md` rules: brokerage exports and browser
  profiles stay outside the repository; personal-data notebook runs stay in
  gitignored `notebooks_local`; tracked notebooks preserve outputs only when
  those outputs are safe. Resetting execution metadata does not remove PII.
  Never read the user's account database or exports for this review.
- Use synthetic fixtures only for proposed reproduction/regression cases.
  Never copy a real identifier into findings, issue bodies, commit messages,
  tests, or session artifacts.
- Report actionable introduced/worsened exposures, not generic compliance
  advice. For each finding identify the data category, source, exposed sink/
  recipient, reachable condition, actual impact, and failed/missing safeguard.
  An unrelated pre-existing exposure is separate from the change verdict.
- Challenge findings against real guards. Retain findings at confidence
  >=70/100; reject only with recorded refuting evidence at >=85/100. Keep
  uncertain material risks explicit and block a clean verdict when unresolved.
- Review directly when evidence fits one context. Delegate only when caller
  rules require it or substantial separate context is necessary, with an
  an explicitly named model (the best available model suited to the scope's complexity, ambiguity and risk (see `docs/dev-strategy.md` D1)) and bounded read-only scope.
  Report BLOCKED if no suitable model is available. Do not launch an agent per data category.

## Report only redacted, actionable facts

| ID | Severity | File / lines | Data category and exposure path | Impact / safe regression check | Confidence |
|---|---|---|---|---|---|

Use `PRIVACY-1`, `PRIVACY-2`, etc. CRITICAL means widespread/high-impact
sensitive-data exposure, HIGH means significant reachable unauthorized
exposure, MEDIUM means a bounded exposure or policy-required lifecycle
failure, and LOW means a minor actual privacy defect.

Include a concise data-flow summary, scope/coverage, candidate refutations,
and validations actually run versus missing. End with **PASS**, **FINDINGS**,
or **BLOCKED**. PASS requires complete in-scope coverage and no retained
findings/material unknowns; it is not a legal compliance certification.
An empty change scope is not an audit of the repository.

Keep the report in the session and use redacted repository-relative paths.
Do not upload files, file issues, commit a report, erase evidence, rotate
credentials, or delete user data without explicit authorization. A relevant
base/HEAD/content/untracked-set change invalidates the verdict and requires
re-review. Fixes must be tested with synthetic data, not real personal data.

## Source of truth and sync

This repo file is the source of truth. The owner refreshes `~/.claude/skills/local-privacy-review/` and `~/.copilot/skills/local-privacy-review/` from `.claude/skills/local-privacy-review/SKILL.md`. A Copilot pointer skill lives at `.github/skills/local-privacy-review/SKILL.md`.
