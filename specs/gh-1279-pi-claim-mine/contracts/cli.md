# CLI Contract: `pi_claim.py --mine`

**Parent**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)

## Invocation

```powershell
& .\.venv_portfolio\Scripts\python.exe scripts\pi_claim.py --mine
```

Document the option in existing module usage text. No required positional arguments.
GitHub CLI authentication and Project 1 read access are runtime prerequisites.

## Successful Output

Each eligible row contains `#<number>`, title (up to 60 characters), `age=<N>min`,
and exactly one `ok`, `DUE`, or `STALE` label. Column spacing is not a machine interface.
Rows preserve project traversal order. Example with synthetic metadata:

```text
  #9001  age=5min (ok)  Synthetic current claim
  #9002  age=11min (DUE)  Synthetic overdue claim
  #9003  age=121min (STALE)  Synthetic abandoned claim
```

No matches: print a clear line such as `no In Progress claims for current user`.
Successful listings return 0, including overdue, stale, and empty listings.
Negative ages retain existing signed-minute conventions.

## Invalid Invocations and Failures

With `--mine`, reject any issue/action positional, `--note` (including `--note ""`),
`--list-stale`, or `--status`. Emit a usage error, exit 2, and make no GitHub calls.
This is Q2's recommendation confirmed by the owner at G1 (2026-11-20).
`--help` may display help and return 0 without any GitHub calls.

Authentication/project/comment failures must surface visibly with a nonzero outcome,
never as the no-claims line. Preserve existing helper exception semantics.

## Read-Only Boundary

Allowed: authenticated-user read, GraphQL project queries, REST issue-comment GETs.
Forbidden: GraphQL mutations, POST/PATCH/PUT/DELETE, assignments, field updates,
comment creation, automatic heartbeat, reclaim, or local claim-state persistence.

## Compatibility

Without `--mine`, existing command behavior/output remain unchanged. Trusted-marker
parsing and current comment-history limits are inherited, not extended.
