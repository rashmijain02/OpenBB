# Data Model: Read-Only Claim View

**Parent**: #1279 ([dev-env] pi_claim: add --mine to list my claims and flag overdue heartbeats)

No new persisted model, schema, cache, or state transition.

| Entity | Existing fields | Rules |
| --- | --- | --- |
| ProjectItem | `content.number`, `content.title`, named `fieldValues.nodes` | Require issue number and `Status` equal to `In Progress` |
| CurrentIdentity | `login` from `whoami()` | Resolve once; auth failure propagates |
| TrustedMarker | `owner`, `hb`, `action` | Latest valid trusted marker; exact owner equality; no extra action restriction |
| DisplayRow | `number`, `title`, `age`, `urgency` | Ephemeral; traversal order; title up to 60 characters; signed whole minutes |

Canonical field references for implementation tasks:

- `ProjectItem.content.number`: required issue number; absent content/number is skipped.
- `ProjectItem.fieldValues.nodes`: use the field named `Status`; require `In Progress`.
- `CurrentIdentity.login`: exact login from existing authenticated identity resolution.
- `TrustedMarker.owner`: must equal `CurrentIdentity.login` exactly.
- `TrustedMarker.hb`: parseable timestamp selected by the existing trusted-comment parser.
- `TrustedMarker.action`: retained protocol field; no extra eligibility filter.
- `DisplayRow.number`: issue number from `ProjectItem.content.number`.
- `DisplayRow.title`: `ProjectItem.content.title` or empty string, truncated to 60 characters.
- `DisplayRow.age`: signed whole-minute floor of the existing age timedelta.
- `DisplayRow.urgency`: exactly one of `ok`, `DUE`, `STALE`, derived below before rounding.

## Derivation

Project item -> In Progress issue -> latest trusted marker -> owner matches current
identity -> age -> one display row. Missing or non-owned markers do not produce rows.
An error retrieving input is a failure, not a missing marker.

| Unrounded heartbeat age | Urgency |
| --- | --- |
| At most 10 minutes (including negative ages) | `ok` |
| More than 10 minutes and at most 2 hours | `DUE` |
| More than 2 hours | `STALE` |

No displayed state causes any write or lifecycle transition. Exact boundaries follow
the issue; existing reclaim semantics are unchanged.
