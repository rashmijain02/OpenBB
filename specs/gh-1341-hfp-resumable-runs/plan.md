# Plan: HFP-P04 bind Hermes runs to resumable jobs and approvals (#1341)

Status: **design draft, not committed.** Base `origin/portfolio` @ `1f9d16208` (contains #1338/PR #1388,
#1339/PR #1389, #1340/PR #1390); branch `feat/hfp-resumable-runs-gh-1341`. Parent #1324 (HFP-F02). Requirements
PF-17 (primary), PF-27. Sources: `docs/Specs/gh-1312-hermes-financial-planning/plan.md` §5 (`Approval`,
`EvidenceEnvelope`), §8 (state machine, "timeout means inspect/reconcile, not repeat"), §9 (durable watermarks),
§12 ("one active scheduler/lease and the existing durable run store"); `spec.md` PF-17, "Replay" row; `github-plan`
HFP-P04 ("reuse #215 adapters; bind only Hermes-specific contracts"). Synthetic data only; no services, no secrets.

## 1. Existing assets (reuse, do not rebuild)

| Asset | File / symbol | What it already guarantees | Gap for P04 |
|---|---|---|---|
| Run registry | `mcp_server/openbb_mcp_server/story_adapters/registry.py`: `RunCreate`, `RunRecord` (`workflow_manifest_sha256`), `RunStore` (SQLite `story_runs`, `checkpoint` = `BEGIN IMMEDIATE` + version CAS), `ensure_workflow_current` (409 `workflow_changed`), `default_store_path` (`OPENBB_STORY_RUN_STORE`) | Digest-bound runs; stale checkpoint is 409 and changes nothing | `story_run_create` is **not idempotent** (new `uuid4` per call); no run-level status, cancel or Hermes binding |
| Jobs | `story_adapters/jobs.py` `story_job_submit/list/get/cancel`, `CancelOutcome{cancelled,too_late,already_finished}`; `story_job_kinds.py` `SubmissionLedger` (`story_jobs`, PK `(principal, operation_id)`), `payload_digest`, worker `_execute` (refuses unattached/mismatched submissions); core `JobService.enqueue(idempotency_key=)` (`job_run.dedupe_key UNIQUE`) | Same `operation_id` -> same job, also across a crash before `attach_job`; different payload -> 409; worker never interrupts a claimed job; `max_attempts=1` | A model re-issue gets a **new** operation_id -> second job; cancel vocabulary lacks `cancel_requested` |
| Artifacts | `story_adapters/artifacts.py` `ArtifactStore.write` (`UNIQUE(principal, run_id, name)`, `_create_exclusive`) | Never overwrites | Re-delivered identical write is a **409**, so a lost reply looks like failure |
| Paper | `story_adapters/paper.py` `Prepare`/`Apply`, `story_paper_requests` (`UNIQUE(principal, operation_id)`), `SIGNED_FIELDS` (request, principal, sandbox, run, action, `argument_sha256`, `manifest_version`, `expires_at`, nonce), status `pending->applying->applied|failed`; `paper_approve.py` (human TTY approval) | Re-delivered apply returns first result; `applying` -> 409 "uncertain"; expiry 410; changed args 409 `approval_mismatch`; manifest change 409 | Expired/drifted rows stay `pending` forever; no logical-duplicate guard; no run-level outcome |
| Contracts kept | `paper.py` `ACTIONS` (TechTrade `submit_batch/record_fill/cancel_order`), `paper_portfolio.py` `SubmitOrder`, `paper_batch.py`, `techtrade_story.py` | Covered by `tests/story_adapters/test_paper*.py`, `test_techtrade_story.py`, `test_workflow_changed_mutations.py` | Must stay byte-identical in input schema |
| Coordinator | `agents/openbb_agents/hermes_integration/workflow_runner.py` `run_workflow`, `ToolInvoker`, `FastMcpInvoker`, CLI `main`; `admission.py` `admit_workflow`; `workflow.py`; `access.py` `ToolGate`; `tool_access.py` (reviewed classes from `mcp_server/assets/capability_policy{.json,_operations.csv}`) | Admitted, digest-bound, no retry/no fallback | No resume; a lost checkpoint reply is just "failed" |
| Scheduling | core `SqliteJobStore.enqueue_due_schedules` (`dedupe_key = schedule:<job>:<instant>`), `JobWorker` heartbeat/lease, `recover_abandoned_runs` | Restart-safe OpenBB schedules | Second scheduler (Hermes cron) not yet reconciled |

## 2. Hermes identifiers (fork `hermes-agent` @ `710fa8a`, read-only, verified)

- MCP calls carry **only the model's arguments** (+ optional `_meta.progressToken`):
  `tools/mcp_tool_handlers.py::_call_tool_racing_stdio_death`. No session/tool-call ID reaches the OpenBB server.
- IDs exist in-process: `model_tools.py::handle_function_call(task_id, tool_call_id, session_id, turn_id,
  api_request_id)`; a plugin `pre_tool_call` hook receives them and may return `{"action": "modify", "args": {...}}`
  (`hermes_cli/plugins.py::_get_pre_tool_call_directive_details`, shallow merge before dispatch).
- Cron: `cron/execution_identity.py::CronExecution(job_id, execution_id, scheduled_instant)` via
  `ctx.current_cron_execution()`; one ticker per home (`cron/scheduler.py` `~/.hermes/cron/.tick.lock` + runtime lock).
- Retry: Hermes replays a call only pre-dispatch or for `readOnlyHint` tools; an in-flight write is reported as
  "outcome uncertain ... do NOT retry automatically" (`_STDIO_OUTCOME_UNCERTAIN_MSG`, session-expired path). So the
  dangerous duplicate is a **model re-issue with a new `tool_call_id`**, not a transport replay.

Consequence: there is no "Hermes run ID" on the wire. The durable run identity stays the OpenBB `run_id`; Hermes IDs
are bound through a hashed **binding key** injected by an OpenBB-owned Hermes plugin, and logical duplicates are
stopped **server-side** so correctness never depends on the plugin or the model.

## 3. Design

### 3.1 Two keys, enforced in the adapter layer (not the registry)

| Key | Value | Purpose | Enforced in |
|---|---|---|---|
| Binding key (run) | `hs-` + sha256(session_id, tool_call_id)[:32] (interactive) or `hc-` + sha256(cron job_id, execution_id, workflow_id)[:32] | One Hermes start / one cron fire -> one story run | `registry.RunStore.create` (new `story_run_bindings`, PK `(principal, binding_key)`, same transaction as the run insert) |
| Delivery key (op) | existing `operation_id`; plugin sets `hd-` + sha256(session_id, tool_call_id)[:32] when Hermes-bound | Transport re-delivery returns the same outcome | existing ledgers (unchanged) |
| Logical key (LOK) | sha256(canonical_json{v:1, tool, run_id, workflow_manifest_sha256 or manifest_version, stage_id, args_sha256}) | Model re-issue of the same operation under a new operation_id returns the first outcome | new `story_adapters/receipts.py` `ReceiptLedger` (`story_receipts`, `UNIQUE(principal, logical_key)`), called by jobs/artifacts/paper routes |

`args_sha256` reuses existing digests: `payload_digest` (jobs), `argument_digest` + `sandbox_id` (paper), rendered
bytes sha256 + kind + media type (artifacts). The registry keeps only CAS and digest binding; operation semantics
live with the adapters that own them, and one shared ledger avoids three copies. LOK collapse applies **only to
Hermes-bound runs** (`RunRecord.binding is not None`), so legacy story runs keep today's exact semantics.

### 3.2 Lost-response / duplicate-delivery semantics

| Operation | Replay with same delivery key | Re-issue, new key, same LOK (Hermes-bound) | Never |
|---|---|---|---|
| `story_run_create` (+`binding`) | same `run_id` | n/a | 2 runs per binding key; same key + other story -> 409 |
| `story_job_submit` | same job (today) | existing job + `replay_of=<first op>` unless it ended `failed/cancelled` (then a new job) | second queued/running job for one LOK |
| `story_artifact_*` | same record if bytes, kind, media type, stage, retention equal (**all runs**) | same | overwrite; different content under a taken name stays 409 |
| `story_paper_prepare` | same request (today) | existing request if `pending`+unexpired, `applying` or `applied`; new request if `expired/superseded/withdrawn/failed` | two live requests for one LOK |
| `story_paper_apply` | first result if `applied`; 409 uncertain if `applying` (today) | n/a (request-bound HMAC + one-use claim) | second engine effect |
| `story_run_checkpoint` | 409 stale; runner reloads and treats `stage_status==status && state==body` as done | n/a | blind re-write |

### 3.3 Approval binding (keep `SIGNED_FIELDS` v1 unchanged)

The §5 `Approval` contract already exists: principal, operation, argument hash, run/version, sandbox, expiry, one-use
nonce. Apply also checks the run's full digest (`ensure_workflow_current`). P04 adds visibility, not new crypto:
`expired` is derived when `expires_at <= now` (reads and outcome); apply on drift sets `status='superseded'`
(`superseded_reason='workflow_changed'|'manifest_changed'`); `story_run_cancel` sets pending rows `withdrawn`. Any of
these, or changed arguments, requires a new `prepare` and a new human decision. A re-prepare after expiry gets a new
`request_id` and nonce because LOK lookup skips terminal-unsuccessful rows. Columns added with guarded
`ALTER TABLE ADD COLUMN` (nullable): `logical_key`, `superseded_reason`.

### 3.4 Cancel semantics (no promised interruption)

New additive field `CancelOutcome.cancel_state` in {`cancel_confirmed` (queued job -> `cancelled`),
`cancel_requested` (recorded; in-flight work allowed to finish), `too_late` (worker claimed it; handler never
interrupted), `already_finished`}; `outcome` keeps its current literals. New `story_run_cancel` (POST): sets
`RunRecord.cancel_requested_at`, cancels queued jobs (confirmed), withdraws pending paper requests (confirmed), lists
running jobs and `applying` requests as `too_late`; returns `cancel_requested` until none remain, then `cancelled`.
A shared guard `ensure_run_open` (next to `ensure_workflow_current`) makes every mutating route 409 `run_cancelled`.

### 3.5 Run outcome (plan §8) from durable receipts, first match wins

| Derived state | Rule |
|---|---|
| `blocked` | workflow digest drift (`ensure_workflow_current` would 409): resume needs a new run/plan |
| `cancelled` / `cancel_requested` | `cancel_requested_at` set; `cancel_requested` while a job runs or a request is `applying` |
| `partial` (+`uncertain`) | a request `applying` longer than `APPLY_STALE` (120 s), or a submission without a durable job |
| `failed` | a mandatory stage `failed`, or a mandatory stage's job `failed` |
| `waiting_job` | a job `queued`/`running` |
| `awaiting_approval` / `needs_input` | a `pending` request unexpired / expired (`reason=approval_expired`) |
| `succeeded` | every mandatory stage `succeeded`, its jobs succeeded, every cited artifact live and hash-valid |
| `partial` | mandatory stages succeeded but an optional stage failed (decision D3) |
| `running` / `ready` | some stage written / none written |

Served by new read-only `story_run_outcome` (in `jobs.py` router, which already holds the `JobService` dependency).
`WorkflowRunResult.succeeded` additionally requires `outcome == "succeeded"`. Nothing maps `partial` to success.

### 3.6 Restart and scheduler ownership

Coordinator restart: `run_workflow(..., resume_run_id=)` reloads the run, re-admits the document and refuses on digest
mismatch (`blocked`), skips stages whose checkpoint holds `succeeded` + `output_sha256`, re-sends jobs/prepares with
the same derived keys (returns existing outcomes), and reconciles checkpoints per 3.2. Process ownership: tools run
in the `openbb-mcp` server process (routes) and the `openbb-jobs` worker (handlers); Hermes only calls. Scheduler
(decision D4): Hermes cron is the single scheduler for Hermes finance runs (its tick lock is the lease; `execution_id`
is the watermark via the `hc-` binding key); OpenBB `enqueue_due` keeps owning native openbb-jobs schedules; story
kinds never get OpenBB schedules (asserted). No new lease table.

## 4. File layout

```
openbb_platform/extensions/mcp_server/openbb_mcp_server/story_adapters/
  receipts.py      # T01 logical_operation_key(), ReceiptLedger (story_receipts)
  registry.py      # T01 RunBinding, RunCreate.binding, story_run_bindings; T02 cancel_requested_at, ensure_run_open,
                   #   story_run_cancel
  jobs.py / story_job_kinds.py  # T01 LOK + replay_of; T02 cancel_state; T03 story_run_outcome
  artifacts.py     # T01 same-content replay
  paper.py         # T01 LOK on prepare; T03 superseded/expired/withdrawn
  run_outcome.py   # T03 derive_outcome(record, receipts, jobs, requests, artifacts) - pure
openbb_mcp_server/assets/capability_policy_operations.csv, capability_policy.json (sha), runtime_profiles.json  # T02/T03
openbb_platform/extensions/agents/openbb_agents/hermes_integration/
  binding.py       # T01 binding_key(), delivery_key(); pre_tool_call hook function (pure, no Hermes import)
  hermes_plugin/   # T01b plugin manifest + register(ctx) wiring binding.py (activated only in LIVE step)
  workflow_runner.py  # T03 resume + checkpoint reconcile; --resume, fault flag gated by OPENBB_HFP_FAULT_INJECTION=1
  replay_probe.py  # T01-T03 real-path CLI: own temp store + in-process portfolio-ops + JobService, synthetic only
  run_receipts.py  # T03 read-only receipt dump of one run (no payload values, hashes and states only)
  workflows/synthetic.concentration_review.workflow.json  # T01 re-pin story_run_create schema_sha256
tests: mcp_server/tests/story_adapters/{test_run_binding,test_receipts_replay,test_cancel_semantics,
  test_run_outcome,test_approval_replay,test_contract_preservation}.py;
  agents/tests/hermes_integration/resume/{conftest,test_binding,test_workflow_resume,test_replay_probe}.py
```

## 5. Commands (PowerShell 7, worktree root)

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = @((Resolve-Path openbb_platform\extensions\agents).Path,
                    (Resolve-Path openbb_platform\extensions\mcp_server).Path) -join ';'
$S = 'openbb_platform/extensions/mcp_server/tests/story_adapters'; $R = 'openbb_platform/extensions/agents/tests/hermes_integration/resume'
& $py -m pytest $S openbb_platform/extensions/agents/tests/hermes_integration -q   # regression after every task
& $py -m black --check <changed>; & $py -m ruff check <changed>
```
Evidence: `.dev-cycle/verify-gh-1341.log` (git-ignored) and `handoff.md`. Conftests set tmp HOME/USERPROFILE,
`OPENBB_STORY_RUN_STORE`, `OPENBB_STORY_ARTIFACT_ROOT`, `OPENBB_STORY_PAPER_ROOT` and a generated test approval key.

## 6. Tasks

### T01: bind job/artifact/paper adapters to Hermes runs and workflow digests (CODE-ONLY)

Goal: 3.1 + 3.2. `RunBinding{harness: Literal["hermes"], binding_key (OPERATION_ID pattern), origin:
Literal["interactive","cron"]}`; `ReceiptLedger`; LOK on job submit and paper prepare (bound runs); artifact
same-content replay (all runs); `binding.py` key derivation + `pre_tool_call` hook (rewrites only `operation_id` /
`binding` of the story mutation tools; never other args). Re-pin `story_run_create` in the synthetic workflow.

| Acceptance bullet | Red-first tests |
|---|---|
| repeated delivery -> one logical outcome (jobs) | `test_bound_resubmit_with_new_operation_id_returns_first_job` (asserts `job_run` row count 1 and `replay_of`); `test_failed_job_allows_a_new_job_for_same_lok`; `test_legacy_run_keeps_one_job_per_operation_id` |
| same (artifacts) | `test_identical_artifact_redelivery_returns_first_record` (1 file on disk, same `artifact_id`); `test_changed_bytes_same_name_still_409`; existing `test_names_are_unique_per_run_so_nothing_is_overwritten` green |
| same (runs) | `test_same_binding_key_returns_same_run`; `test_binding_key_for_other_story_conflicts`; `test_concurrent_creates_one_run` (two threads) |
| same (paper prepare) | `test_bound_reprepare_returns_pending_request`; `test_reprepare_after_apply_returns_applied_request_no_second_fill` |
| workflow digest bound | `test_lok_differs_when_workflow_digest_differs`; `test_receipt_records_digest_and_args_hash_not_values` |
| Hermes IDs | `test_binding_keys_from_session_and_tool_call` (`resume/test_binding.py`); `test_hook_rewrites_only_story_mutation_tools`; `test_cron_execution_key_is_stable_per_execution` |

Mutation checks: drop the LOK lookup -> bound resubmit test sees 2 jobs; remove the digest from LOK -> digest test
fails; compare only `sha256` (not stage) in artifact replay -> a stage-mismatch test fails.
Focused: `& $py -m pytest "$S/test_run_binding.py" "$S/test_receipts_replay.py" "$R/test_binding.py" -q`.
Real path: `& $py -m openbb_agents.hermes_integration.replay_probe --scenario duplicate-delivery --format json`
Expect exit 0 and, per operation, `deliveries: 2, outcomes: 1` read back from SQLite (not from responses). The probe
creates its own temp directory and refuses any external store path.
**T01b (CODE-ONLY code, LIVE activation):** `hermes_plugin/` wiring; unit-tested by calling the hook with synthetic IDs.

### T02: cancel_requested / cancel_confirmed / too_late without promised interruption (CODE-ONLY)

Goal: 3.4. `cancel_state` on `CancelOutcome`; `story_run_cancel`; `ensure_run_open` on every mutating route; policy
rows + profile placement for the new tool (D5).

| Acceptance / task bullet | Red-first tests (`test_cancel_semantics.py`) |
|---|---|
| explicit outcomes | `test_queued_job_cancel_is_confirmed`; `test_claimed_job_is_too_late_and_still_completes` (claim via `JobService.claim_next`, complete, assert result kept); `test_finished_job_is_already_finished`; `test_cancel_outcome_literals_unchanged` |
| no unsupported interruption | `test_run_cancel_is_requested_while_a_job_runs_then_cancelled_after` |
| partial never success | `test_cancelled_run_outcome_is_never_succeeded`; `test_mutations_after_run_cancel_are_409`; `test_pending_request_withdrawn_cannot_apply` |
| reads stay open | extend `test_workflow_changed_mutations.py::test_reads_and_cancel_stay_open_after_change` for `story_run_cancel` |

Focused: `& $py -m pytest "$S/test_cancel_semantics.py" "$S/test_jobs.py" "$S/test_workflow_changed_mutations.py" -q`.
Real path: `replay_probe --scenario cancel --format json` -> exit 0; `queued: cancel_confirmed`, `claimed: too_late`,
`run: cancel_requested -> cancelled` after the probe completes the claimed job.

### T03: restart and approval replay; Portfolio/TechTrade contracts preserved (CODE-ONLY + LIVE follow-up)

Goal: 3.3, 3.5, 3.6. `run_outcome.py` + `story_run_outcome`; paper `superseded/expired/withdrawn`; runner resume.

| Acceptance bullet | Red-first tests |
|---|---|
| expired approval -> new decision | `test_expired_request_reads_expired_and_reprepare_creates_new_request_and_nonce`; `test_old_approval_cannot_apply_new_request` (`test_approval_replay.py`) |
| changed args -> new decision | existing `test_changed_arguments_require_new_approval` + `test_changed_args_reprepare_is_new_request` |
| drifted digest -> new decision, not success | `test_drift_marks_request_superseded`; `test_resume_after_drift_is_blocked_not_succeeded` (`resume/test_workflow_resume.py`) |
| partial never success | `test_outcome_table` (parametrised over every row of 3.5); `test_stale_applying_is_partial_uncertain`; `test_runner_succeeded_requires_outcome_succeeded` |
| restart | `test_resume_skips_checkpointed_stages` (invoker call counts); `test_lost_checkpoint_reply_reconciles_not_rewrites`; `test_fresh_app_over_same_store_returns_same_job_and_applied_result` |
| scheduler | `test_story_job_definitions_have_no_schedule`; `test_cron_refire_same_execution_one_run` |
| contracts preserved | `test_contract_preservation.py`: input-schema sha256 of every `story_paper_*`, `story_job_*`, `story_artifact_*` tool equals a fixture captured from `origin/portfolio` before T01; existing `test_paper*.py`, `test_techtrade_story.py`, `test_paper_batch.py` unchanged and green |

Focused: `& $py -m pytest "$S/test_run_outcome.py" "$S/test_approval_replay.py" "$S/test_contract_preservation.py" "$R" -q`.
Real path (two real processes, one temp store):
```powershell
$env:OPENBB_STORY_RUN_STORE = Join-Path ([IO.Path]::GetTempPath()) "gh1341-$(Get-Random)\runs.sqlite"
$env:OPENBB_HFP_FAULT_INJECTION = '1'
& $py -m openbb_agents.hermes_integration.workflow_runner --workflow synthetic.concentration_review --inputs synthetic --server portfolio-ops --crash-after concentration --format json   # Expect exit 75, run_id printed first
& $py -m openbb_agents.hermes_integration.workflow_runner --resume <run_id> --workflow synthetic.concentration_review --inputs synthetic --server portfolio-ops --format json   # Expect exit 0, concentration "reused"
& $py -m openbb_agents.hermes_integration.run_receipts --run <run_id> --format json   # Expect outcome succeeded, 1 checkpoint per stage
& $py -m openbb_agents.hermes_integration.replay_probe --scenario approval-replay --format json   # Expect expired/changed/drifted -> new request, 0 extra fills
```

### T04: live Hermes binding and scheduler proof (LIVE, owner; after #1338/#1339 L2-L5)

Owner-run, template in `openbb-dev-cycle` §4, in the L2 qualification home only: install `hermes_plugin`; one turn
runs the synthetic workflow and submits one story job; stop the MCP server mid-call, confirm Hermes reports
"outcome uncertain", let the model re-issue; `run_receipts` shows one job and one `replay_of`; restart the gateway,
reconnect, observe the run via `story_run_outcome` (no new run); "Run now" the same cron execution twice -> one run;
record PIDs of the tool-executing processes. Report exit codes and mismatched expectations; recorded on #1341.

## 7. Backward compatibility

- Legacy story runs (`binding is None`): job, paper and checkpoint behaviour unchanged; only artifact identical
  re-delivery changes 409 -> 200 (D1). `RunRecord` gains optional `binding`, `cancel_requested_at` (old JSON rows
  load with defaults). `CancelOutcome.outcome` literals unchanged; `cancel_state`, `replay_of` are additive outputs.
- Input schemas of all paper/job/artifact tools unchanged (T03 contract test). `story_run_create` input gains
  optional `binding`: re-pin the synthetic workflow (its digest changes; no live runs depend on it, D7).
- SQLite: new tables `CREATE IF NOT EXISTS`; `story_paper_requests` columns added nullable behind a `PRAGMA
  table_info` check; `SIGNED_FIELDS` untouched, so outstanding approvals stay valid. New status values `superseded`,
  `withdrawn` only on rows that would otherwise be stuck `pending`.
- Policy assets: two new rows (`story_run_cancel`, `story_run_outcome`) + recomputed `capability_policy.json` sha.

## 8. PR batching

One branch and one PR for T01-T03 (shared ledger, same files, one long-gate run; OM5): commits per task. T04 is
not a PR; it is the owner's live acceptance recorded on #1341 after merge and after L2-L5. Gates: focused + regression
pytest, black/ruff, local code/security/privacy reviews on the PR diff vs `portfolio`, `scripts/local_ci.py
--merged-with origin/portfolio` (or the per-workflow fallback), real-path log.

## 9. Risks and open questions (recommended answers)

| # | Question / risk | Recommendation |
|---|---|---|
| D1 | Artifact identical re-delivery returns 200 for all runs? | Yes: strictly safer, no caller relies on 409 for identical bytes (only changed-content test exists). |
| D2 | LOK may collapse a deliberate identical repeat (e.g. two equal TechTrade batches) | Bound runs only; a deliberate repeat needs differing args (`plan_id`, `notes`, `reason`) or a new run; document in the skill. |
| D3 | Optional stage failed, mandatory passed | `partial`, never `succeeded` (plan §8 wording). |
| D4 | Which scheduler owns finance runs | Hermes cron (tick lock = lease, `execution_id` = watermark); OpenBB schedules never for story kinds; align with #1344. Owner confirms. |
| D5 | New tools in reviewed policy/profiles | `story_run_cancel` in profiles that have `story_job_cancel`; `story_run_outcome` read in every story profile. |
| D6 | Stale `applying` resolution | Report `partial`+`uncertain`; operator inspects `story_paper_state`; no auto-resolution in P04 (file a follow-up if wanted). |
| D7 | Re-pin `story_run_create` schema | Accept in T01; admission correctly rejects the old pin until updated. |
| R1 | Hermes `modify` hook not applied to MCP tools at runtime | Server-side LOK still prevents duplicates; T04 verifies the hook; plugin absence only loses the Hermes correlation. |
| R2 | SQLite contention across server + worker | Keep `BEGIN IMMEDIATE` short; LOK insert uses `INSERT ... ON CONFLICT DO NOTHING` then read-back. |
| R3 | Receipts leaking private values | Store hashes, IDs and states only; `run_receipts` prints no payload values; privacy review checks it. |

## Lead decisions (2026-11-28, under the owner's delegation)

D1–D7 are accepted as recommended:
- D1: an identical artifact re-delivery returns 200 for all runs.
- D2: the logical operation key applies to Hermes-bound runs only.
- D3: an optional-stage failure reports `partial`, never `succeeded`.
- D4: Hermes cron is the only scheduler for Hermes finance runs. Its tick lock is the lease and `execution_id` is the watermark; there is no new lease table. This aligns with #1344.
- D5: `story_run_cancel` goes in the profiles that already expose `story_job_cancel`; `story_run_outcome` is readable in every story profile. Both get reviewed policy rows and a recomputed policy sha.
- D6: a request stuck in `applying` reports `partial` plus uncertain, and the operator resolves it.
- D7: the optional `binding` input is accepted, and the synthetic workflow is re-pinned in T01.

Model policy: the `portfolio` `CLAUDE.md` (D1, model-agnostic) governs. The GPT-only clause in the main checkout belongs to an older branch.

T04 is LIVE and depends on the owner's L2–L5 from #1338 and #1339.
