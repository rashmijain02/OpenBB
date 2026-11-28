# Plan: HFP-P03 notebook-independent workflow manifests (#1340)

Status: **design draft, not committed.** Base `origin/portfolio` @ `75f442402`; branch
`feat/hfp-workflow-manifests-gh-1340`. Parent #1324 (HFP-F02). Requirements PF-27 (primary), PF-03.
Design sources: `docs/Specs/gh-1312-hermes-financial-planning/` spec.md "Notebook role versus
production runtime", PF-27, PF-03; plan.md §3 (reuse map, reviewer note 1, §3.1 "Reconciled production
contracts"), §5 (`WorkflowManifest`, `TutorialTraceabilityRef`), §14; github-plan/plan.md HFP-P03.
Sibling plan: `specs/gh-1338-hfp-runtime-privacy-admission/plan.md` (§2 layout, §8 decisions) on
branch `feat/hfp-runtime-provenance-gh-1338`. Synthetic data only; no private data, no services.

## 1. Existing assets and the coupling to remove

| Asset | File / symbol | What couples it to notebooks |
|---|---|---|
| Story contracts | `openbb_platform/extensions/agents/openbb_agents/notebook_guide/contracts.py`: `StoryManifest`, `StoryStage`, `CapabilityRef`, `CapabilityCatalog`, `InputBinding`, `Access`, `validate_stage_graph`, `_check_acyclic`, `_upstream` | `StoryManifest.notebook_path` (regex `^notebooks/...\.ipynb$`), `source_sha256` (source-only `.ipynb` hash), `StoryStage.cells` (one-based cell positions, `min_length=1`), `validate_stage_graph` enforces cell ownership. |
| Access vocabulary (legacy) | `contracts.Access = Literal["metadata","provider_read","private_read","analysis","artifact","paper"]` | Unversioned; unknown literals are rejected only by pydantic. |
| Access vocabulary (server) | `openbb_mcp_server/models/capability.py`: `AccessClass` (10 literals) | No compute class: `capability_inventory.py` classifies every non-GET route, including pure-math `story_concentration`, as `financial_mutation`. |
| Readiness | `notebook_guide/readiness.py`: `check_readiness`, `summarize_readiness`, `ReadinessReport` | Pure, but typed on `StoryManifest`; tutorial-maintenance diagnostic only. No production import today (only `tests/notebook_guide/test_readiness.py`). |
| Story manifests + catalog | `notebook_guide/stories/{portfolio,portfolio_yfinance,techtrade}__NN.json` (25) and `capability_catalog.json` (64 entries, reviewed `schema_sha256` pins) | Every manifest carries `notebook_path`, `source_sha256`, `cells`. |
| Generator | `scripts/build_story_manifests.py`: `build_manifest`, `_tool_schemas` (canonical `json.dumps(tool.parameters, sort_keys, separators)` SHA-256 on an in-process `portfolio-ops` server), `build_catalog`; imports `scripts/notebook_story_inventory.py` (`inventory_notebooks`, `NotebookSource`) | Reads `notebooks/*.ipynb` by design (build/CI only). |
| Run registry | `openbb_mcp_server/story_adapters/registry.py`: `StoryCatalog.version()` = `story_id@source_sha256[:12]`; `StorySummary.notebook_path`; `default_manifest_dir()` -> `openbb_agents/notebook_guide/stories`; `RunRecord.manifest_version`; `compose_story_registry_app` | **Run identity is the notebook hash.** Editing a notebook cell changes every new run's `manifest_version`; the runtime loads manifests from the tutorial package dir. |
| Downstream of `manifest_version` | `story_adapters/paper.py` (approval rows store and compare `manifest_version`, "The run's manifest changed since approval"), `jobs.py`, `artifacts.py` ("Stage ... is not in {run.manifest_version}"), `paper_approve.py` | Inherit the notebook-hash coupling. |
| Shared engine | `story_adapters/analytics.py` `story_concentration`, `story_construction_targets` -> `openbb_portfolio_intel.analytics.basket_lookthrough.concentration`, `construction_targets` ("the same engine the notebook calls"); composed in `app/app.py` (~L786) for `portfolio-ops` | None; pure math on weight maps, no provider call. Tutorial anchor: `portfolio__03.json` stages `7-concentration-...` and `8-portfolio-construction-...`. |
| Tests | `agents/tests/notebook_guide/` (network-denied conftest, `test_manifests.py` reads `notebooks/` via inventory), `mcp_server/tests/story_adapters/test_registry.py`, `test_analytics.py` | Tutorial tests legitimately read notebooks; keep them as CI traceability. |
| Diagnostic | `scripts/notebook_story_inventory.py --check docs/cross_repo_workflow/notebook-mcp-story-inventory.csv` | 21 known source-hash mismatches (plan.md §14). Not a gate here; do not regenerate. |

Facts: `.venv_portfolio` is CPython 3.12.15 with fastmcp 3.4.0 and no `nbformat`/`nbclient`/
`ipykernel`/`jupyter_client`. `openbb_agents` is not installed (tests use `sys.path`);
`openbb_agents/__init__.py` injects `portfolio_app/src`, `core`, `fmp_cached` onto `sys.path`
(not notebook-related, accepted by the #1338 plan).

## 2. File layout

Package confirmed by the #1338 plan §2: `openbb_agents/hermes_integration/`. Dependency direction
stays **agents -> mcp_server** (as in #1338); `openbb_mcp_server` never imports `openbb_agents`.

```
openbb_platform/extensions/mcp_server/openbb_mcp_server/
  utils/schema_digest.py         # T01: canonical_json_sha256(obj), tool_input_schema_sha256(params)
                                 #   (moved from build_story_manifests._tool_schemas; single source)
  story_adapters/registry.py     # T02: WorkflowCatalog, default_workflow_dir(), workflow-bound runs
openbb_platform/extensions/agents/openbb_agents/
  _stage_graph.py                # T01: pure check_unique/acyclic/upstream/bindings, moved out of
                                 #   notebook_guide/contracts.py (contracts.py re-imports; behaviour same)
  hermes_integration/
    __init__.py                  # shared with #1338/#1339: empty, no side effects
    workflow.py                  # T01: WorkflowManifest, WorkflowStage, CapabilityPin, SchemaRef,
                                 #   ACCESS_VOCABULARIES, workflow_manifest_sha256(), validate_workflow()
    admission.py                 # T01: admit_workflow() -> WorkflowAdmission (fail-closed, never raises)
    workflow_admit.py            # T01 CLI: python -m openbb_agents.hermes_integration.workflow_admit
    notebook_guard.py            # T03: audit-hook guard (blocks .ipynb/notebooks opens, jupyter imports)
    workflow_runner.py           # T03: deterministic stage executor + CLI over an injected ToolInvoker
    workflows/synthetic.concentration_review.workflow.json   # T01: first reviewed workflow
  notebook_guide/
    traceability.py              # T02: TutorialTraceabilityRef (build/CI only)
    traceability/synthetic.concentration_review.json         # T02: generated, portfolio/03 stages 7-8
scripts/build_workflow_traceability.py   # T02: generate/--check; no live server
scripts/build_story_manifests.py         # T01: import schema_digest (2-line refactor)
openbb_platform/extensions/agents/tests/hermes_integration/workflow/
  conftest.py                    # network deny, tmp HOME/USERPROFILE, OPENBB_STORY_RUN_STORE=tmp
  fixtures/{drifted,unknown-access,unknown-version,notebook-path,cells-field,kernel-server,
            cyclic,v2-household}.workflow.json
  test_workflow_contracts.py, test_workflow_admission.py, test_import_hygiene_workflow.py,
  test_traceability.py, test_notebook_free_run.py
openbb_platform/extensions/mcp_server/tests/story_adapters/test_registry_workflows.py
```

Tests sit in a `workflow/` subdirectory so they never edit the `tests/hermes_integration/conftest.py`
that 1338-T01 creates (parent conftest, if present, still applies and is compatible).

**WorkflowManifest v1 (proposed fields).** `schema_version: Literal[1]`; `workflow_id: Identifier`;
`version: str` (semver); `access_version: int`; `title`; `capabilities: Mapping[Identifier,
CapabilityPin(server, tool, schema_sha256, access: str)]` (self-contained pins, no external catalog
file at runtime); `stages: list[WorkflowStage(id, title, kind, depends_on, capabilities, inputs,
outputs, optional)]` (no `cells`; `kind` excludes `setup`/`narrative`); `input_schemas`,
`artifact_schemas: Mapping[name, Sha256]`; `limitations`. `extra="forbid", frozen=True`. Digest:
`workflow_manifest_sha256 = canonical_json_sha256(document)`; the file never contains its own digest.
`ACCESS_VOCABULARIES = {1: the six legacy story literals, 2: v1 + household_meta, tax_compute,
document_evidence}` (plan.md §3.1). v2 literals parse but deny as `access_unmapped` until a PolicyGate
mapping exists (T01b).

## 3. Common commands (PowerShell 7, from the worktree root)

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = @((Resolve-Path openbb_platform\extensions\agents).Path,
                    (Resolve-Path openbb_platform\extensions\mcp_server).Path) -join ';'   # worktree code
$W = 'openbb_platform/extensions/agents/tests/hermes_integration/workflow'
& $py -c "import openbb_mcp_server, openbb_agents; print(openbb_mcp_server.__file__, openbb_agents.__file__)"  # must show the worktree
& $py -m black --check <changed files>; & $py -m ruff check <changed files>
```

Regression set run after every task: `& $py -m pytest openbb_platform/extensions/agents/tests/notebook_guide
openbb_platform/extensions/mcp_server/tests/story_adapters -q`. Real-path evidence goes to
`.dev-cycle/verify-gh-1340.log` (git-ignored) and the handoff.

## 4. Tasks

### T01: typed workflow and access-version contracts with schema-drift rejection (CODE-ONLY)

Goal: a strict, notebook-free `WorkflowManifest` and a fail-closed `admit_workflow(document, *,
live_tools: Mapping[str,str], supported_access_versions={1}, allowed_access=None)` returning
`WorkflowAdmission(admitted, workflow_id, workflow_manifest_sha256, rejections[code, detail])`.
Codes: `schema_invalid` (unknown field, unknown `schema_version`), `access_version_unsupported`,
`unknown_access`, `access_unmapped`, `access_not_granted`, `capability_unresolved`, `tool_absent`,
`schema_drift`, `notebook_dependency`, `graph_invalid`. `notebook_dependency` triggers on any string
value or key matching `.ipynb`, a `notebooks/` / `notebooks_local/` / `docs/examples/` segment, `cells`,
`notebook_path`, `source_sha256`, or a server/tool in `{notebook, kernel, jupyter, workspace-notebook}`.
Graph checks reuse `_stage_graph.py` (moved, not duplicated, so tutorial and runtime share one rule).

Files: `_stage_graph.py`, `notebook_guide/contracts.py` (re-import only), `hermes_integration/{workflow,
admission,workflow_admit}.py`, `workflows/synthetic.concentration_review.workflow.json` (stages
`concentration` -> `construction` -> `checkpoint`; pins copied from `capability_catalog.json` for
`platform:story_concentration`, `platform:story_construction_targets`, `platform:story_run_checkpoint`),
`openbb_mcp_server/utils/schema_digest.py`, `scripts/build_story_manifests.py`, tests.

| Acceptance bullet | Red-first tests (`test_workflow_admission.py` unless noted) |
|---|---|
| admitted WorkflowManifest | `test_shipped_synthetic_workflow_admits_against_matching_live_hashes`; `test_workflow_digest_is_stable_across_key_order` (contracts) |
| unknown access literals rejected | `test_unknown_access_literal_rejected` (fixture `unknown-access`); `test_unknown_access_version_rejected`; `test_v2_household_literal_denied_as_unmapped`; `test_access_outside_allowed_set_not_granted` |
| schema drift rejected | `test_live_hash_mismatch_is_schema_drift`; `test_tool_absent_from_server_rejected`; `test_tool_of_same_name_on_other_server_never_counts`; `test_unknown_manifest_field_is_schema_invalid`; `test_schema_version_2_rejected` |
| runtime notebook dependency rejected | parametrised `test_notebook_dependency_rejected` over `notebook-path`, `cells-field`, `kernel-server` fixtures and an `.ipynb` string inside `limitations` |
| fail closed | `test_admission_never_raises_on_garbage` (non-dict, bytes, deep nesting); `test_cyclic_graph_rejected` |
| shared rules unchanged | existing `tests/notebook_guide/test_contracts.py` stays green after the `_stage_graph` move; `test_schema_digest_matches_reviewed_catalog_pins` recomputes one pin |

Mutation checks (rule 7): drop the `live_hash != pin` branch -> drift test fails; widen v1 vocabulary
to accept any string -> unknown-access test fails; remove the `notebook_dependency` scan -> the
parametrised test fails (extra=forbid alone does not catch `.ipynb` inside `limitations`).

Focused: `& $py -m pytest "$W/test_workflow_contracts.py" "$W/test_workflow_admission.py" -q`

Real-path (in-process `portfolio-ops` server, the same construction `build_story_manifests._tool_schemas`
uses, tmp HOME so no `user_settings.json` is read):
`& $py -m openbb_agents.hermes_integration.workflow_admit --workflow synthetic.concentration_review --live portfolio-ops --format json`
Expect exit 0, `admitted: true`, digest printed. Then `--workflow-file "$W/fixtures/drifted.workflow.json"`
Expect exit 2, `schema_drift`. Exit 3 = usage.

**T01b (after 1339-T01 `access.py` merges, small, same PR if timing allows):** map every v1/v2
workflow access literal to a PolicyGate operation (`AccessClass` + `household_read`,
`household_display`, `evidence_projection_read`); unmapped -> `access_unmapped`.
Test: `test_every_workflow_access_literal_maps_to_a_policy_operation` (imports `access.py`).

### T02: cell/hash mappings become optional tutorial traceability (CODE-ONLY)

Goal: runtime identity is the workflow digest, not the notebook hash; cells and `.ipynb` hashes live
only in `TutorialTraceabilityRef`, used by build/CI.

- `notebook_guide/traceability.py`: `TutorialTraceabilityRef(schema_version 1, workflow_id,
  workflow_manifest_sha256, story_id, notebook_path, source_sha256, stage_map: {workflow_stage_id:
  {story_stage_id, cells}})`.
- `scripts/build_workflow_traceability.py [--check]`: reads workflow JSON + story manifests only (no
  live server, no `.ipynb` open); writes `notebook_guide/traceability/<workflow_id>.json`.
- `registry.py`: `default_workflow_dir()` = `find_spec("openbb_agents")` location / `hermes_integration/
  workflows` (top-level spec only, no import, as `default_manifest_dir` does today); `WorkflowCatalog`
  loads `*.workflow.json`, refuses documents with notebook keys, digests via `schema_digest`; IDs are
  namespaced `workflow:<id>` so `RunCreate.story_id` keeps its input schema (pinned hashes unchanged).
  Workflow runs set `manifest_version = workflow:<id>@<digest[:12]>` and a new optional
  `RunRecord.workflow_manifest_sha256` (default `None`, so stored legacy rows still validate).
  `POST /runs/{id}/checkpoint` returns 409 if the loaded workflow digest differs from the run's.
  `StorySummary.notebook_path` becomes `str | None` (output only). Legacy story runs are unchanged.
- `StoryManifest` and the 25 story JSONs are **not** rewritten (decision Q2).

| Acceptance bullet | Red-first tests |
|---|---|
| admitted workflow runs without notebook identity | `test_registry_workflows.py::test_workflow_run_version_is_workflow_digest_not_notebook_hash`; `::test_workflow_run_survives_missing_story_manifest_dir` (manifest_dir=tmp empty, workflow_dir set) |
| checkpoints bind the workflow digest | `::test_checkpoint_rejected_when_workflow_manifest_changed`; `::test_legacy_rows_without_workflow_digest_still_load` |
| runtime notebook dependency rejected | `::test_workflow_catalog_refuses_documents_with_cells_or_notebook_path`; `test_import_hygiene_workflow.py::test_runtime_modules_never_import_notebook_code` (AST over `hermes_integration/**` and `registry.py`: no `openbb_agents.notebook_guide`, `scripts.*`, `nbformat`, `nbclient`, `jupyter_client`, `ipykernel`, `IPython`, `papermill`; no string constant ending `.ipynb`) |
| traceability is optional and correct | `test_traceability.py::test_traceability_matches_generator` (`--check` equivalence); `::test_traceability_digest_matches_current_workflow`; `::test_mapped_story_stages_bind_the_same_tools` (portfolio/03 stages 7, 8) |

Mutation checks: make `WorkflowCatalog.version` use any notebook field -> version test fails; add
`from openbb_agents.notebook_guide import readiness` to `admission.py` -> hygiene test fails (AST,
not `inspect.getsource`, per rule 8).

Focused: `& $py -m pytest "$W/test_traceability.py" "$W/test_import_hygiene_workflow.py" openbb_platform/extensions/mcp_server/tests/story_adapters/test_registry_workflows.py -q`

Real-path: `& $py scripts/build_workflow_traceability.py --check` (exit 0), then the T01 admit CLI
with `--show-run-version` creating one run in a tmp store: Expect `workflow:synthetic.concentration_review@<12 hex>`
equal to the admitted digest prefix.

### T03: engine-backed workflow with notebook files and kernels absent (CODE-ONLY)

Goal: `workflow_runner.run_workflow(manifest, inputs, invoker, *, live_tools)` admits, creates a
registry run, executes stages in topological order through a `ToolInvoker` protocol, checkpoints
state bound to the digest, and returns a typed `WorkflowRunResult` (stage statuses, output SHA-256s,
evidence ids). Default invoker: `fastmcp.Client` in-memory against `create_mcp_server(MCPSettings
(capability_profile="portfolio-ops"), app, auth=(principal, token))`. `notebook_guard.install()` uses
`sys.addaudithook` to refuse `open`/`os.listdir`/`os.scandir` on `.ipynb` or a `notebooks`,
`notebooks_local`, `docs/examples` segment and imports of jupyter modules, counting attempts.
No retry, no fallback, no LLM: Hermes is not in this path.

| Acceptance bullet | Red-first tests (`test_notebook_free_run.py`) |
|---|---|
| same shared engine executes, notebooks unmounted | `test_synthetic_workflow_runs_with_notebook_guard` (guard on, cwd=tmp, synthetic weights; asserts concentration HHI and construction targets equal direct `basket_lookthrough.concentration` / `construction_targets` results on the same inputs); `test_runner_reports_zero_blocked_notebook_accesses` |
| guard is real (not ceremonial) | `test_guard_blocks_ipynb_open_and_jupyter_import` (open a tmp `x.ipynb`, import a stub `nbformat` -> both refused) |
| rejected workflows never execute | `test_drifted_workflow_runs_no_stage` (invoker sentinel raises if called) |
| no notebook module loaded | `test_no_notebook_modules_in_sys_modules_after_run` (subprocess, `-X importtime` not needed; inspects `sys.modules`) |

Mutation checks: make the runner call `notebook_guide.readiness.check_readiness` -> guard/AST test
fails; swap `concentration` for a stub -> engine-equality test fails.

Focused: `& $py -m pytest "$W/test_notebook_free_run.py" -q`

**Real-path command (replaces "Command: Not yet qualified" on #1340):**

```powershell
$tmp = Join-Path $env:TEMP 'hfp-1340-notebook-free'; $home1340 = Join-Path $env:TEMP 'hfp-1340-home'
git worktree add --detach --no-checkout $tmp HEAD
git -C $tmp sparse-checkout set --no-cone '/*' '!/notebooks/' '!/notebooks_local/' '!/docs/examples/'
git -C $tmp checkout
New-Item -ItemType Directory -Force $home1340 | Out-Null
$env:HOME = $home1340; $env:USERPROFILE = $home1340; $env:OPENBB_STORY_RUN_STORE = "$home1340\runs.sqlite"
$env:PYTHONPATH = "$tmp\openbb_platform\extensions\agents;$tmp\openbb_platform\extensions\mcp_server"
Push-Location $home1340
& $py -m openbb_agents.hermes_integration.workflow_runner --workflow synthetic.concentration_review `
    --inputs synthetic --server portfolio-ops --forbid-notebooks --format json
Pop-Location; Test-Path "$tmp\notebooks"    # Expect False
git worktree remove --force $tmp
```

Expect: exit 0; `admitted: true`; stages `concentration`, `construction`, `checkpoint` = `succeeded`;
`manifest_version` = `workflow:synthetic.concentration_review@<digest12>`; `notebook_guard:
{blocked_opens: 0, blocked_imports: 0}`; no network beyond loopback. Negative: `--workflow-file
<drifted>` -> exit 2, zero stages run. Caveat: editable installs of unchanged packages
(`openbb_portfolio_intel`, `openbb_core`) still resolve to the main checkout, which has `notebooks/`;
the audit hook proves they are not touched.

## 5. Ordering vs #1338 / #1339

| Work | Depends on | Can start now on `portfolio`? |
|---|---|---|
| T01 (v1 vocabulary, v2 parsed-but-unmapped), T02, T03 | `openbb_mcp_server` and `notebook_guide` only | **Yes.** No import from #1338/#1339 modules (`models.py`, `profile.py`, `provenance.py`, `access.py`). |
| `hermes_integration/__init__.py` | 1338-T01 creates it (empty) | Create the identical empty file; rebase before PR (same mitigation as 1339-T01). |
| T01b access mapping | 1339-T01 `access.py` merged | No. |
| Hermes-driven run of the workflow, PolicyGate at call time, preflight-qualified runtime | 1338 L1/L2 (LIVE), 1339-T01 gate, HFP-P04 run binding | No; out of #1340 scope (Q4). |

Issue-level "Dependencies: HFP-P01" is satisfied for code by this split: nothing in #1340 needs the
provenance preflight to compile or test.

## 6. PR batching (OM5)

One branch/PR **C** `feat/hfp-workflow-manifests-gh-1340` = T01 + T02 + T03 (+ T01b if 1339-T01 has
merged by then; otherwise T01b is a small follow-up PR on #1340 with `Refs`). Per-task gates: focused
pytest + regression set, black/ruff, real-path log, `/code-review`, `/security-review`,
`local-privacy-review` on the diff vs `portfolio`. Batch gate: local CI on C's tip merged with
`origin/portfolio` (after A/B merge, so it covers the shared `__init__.py`); until `scripts/local_ci.py`
is on `portfolio`, reproduce `test-unit-platform` + `general-linting` (triggered by
`openbb_platform/**` and `scripts/**`) and post the evidence. Merge order A (#1338), B (#1339), C;
C does not wait for B unless T01b is included. No Pester or .NET gate. PR body: `Closes #1340` if Q4
is accepted, else `Refs #1340`.

## 7. Risks and open questions

| # | Question / risk | Recommendation |
|---|---|---|
| Q1 | Access literal names conflict: design source v2 = `household_meta`, `tax_compute`, `document_evidence`; 1339-T01 PolicyGate ops = `household_read`, `household_display`, `evidence_projection_read`; server `AccessClass` lacks a compute class. | Keep workflow literals as declared requirements (v1 = legacy six, v2 = design names) and own the literal -> operation map in `access.py` (T01b). `tax_compute` stays unmapped (deny) until the tax PBI. Do not widen `AccessClass` here. |
| Q2 | Rewrite `StoryManifest`/25 JSONs to drop `cells`/`source_sha256`? | No. They are the tutorial artifact (plan.md §3 "historical typed contracts"); production stops reading them. Avoids churning `test_manifests.py`, paper approvals and the companion. |
| Q3 | Workflow runs change `manifest_version` format; old paper approvals bound to a story version won't match workflow runs. | Acceptable and fail-closed ("approve again"). Legacy story runs keep the old format. |
| Q4 | Can #1340 close on CODE-ONLY evidence, or must Hermes itself drive the workflow (LIVE, needs 1338 L1/L2)? | Close on CODE-ONLY: the acceptance names the shared engine and admission, not Hermes. Hermes-driven execution belongs to HFP-P04 (#1341 run binding). **NEEDS-OWNER-DECISION** (lead may decide under D15). |
| Q5 | Which workflows ship first? | Only `synthetic.concentration_review` (pure math, no provider, no private data). Real portfolio workflows follow per PF-03 capability issues. |
| Q6 | Registry exposure of workflows in the production profile vs legacy stories under `portfolio-ops`. | Serve both now (namespaced IDs); the production-profile filter comes with the Workspace `/query` cutover (plan.md §3.1), not here. |
| R1 | `find_spec("openbb_agents")` resolves to the main checkout when PYTHONPATH is wrong -> tests silently use main-checkout workflows. | The import-location print in §3 is a mandatory first step; tests assert `default_workflow_dir()` is under the worktree. |
| R2 | In-process `portfolio-ops` composition imports `openbb_core` and `fmp_cached`; may read `user_settings.json`. | Tmp HOME/USERPROFILE in conftest and real-path; network denied; no credentials needed for the pure-math tools. |
| R3 | Pinned schema hashes drift when unrelated platform changes regenerate tool schemas. | That is the intended `schema_drift` denial; update pins via review, with `test_schema_digest_matches_reviewed_catalog_pins`. |
| R4 | Moving `_tool_schemas` hashing and graph helpers could change generator output. | Behaviour-preserving move; `test_committed_manifests_match_the_generator` and `test_contracts.py` must stay green before any new code. |
| R5 | Audit hooks cannot be removed once installed. | Install only in the runner CLI process and in subprocess-based tests, never in the shared pytest process. |

## Lead decisions (2026-11-28, under the owner's delegation)

| # | Decision |
|---|---|
| Q1 | Workflow manifests keep the design access names (`household_meta`, `tax_compute`, `document_evidence`). T01b maps them to the policy operations in `access.py` from #1339-T01. `tax_compute` stays denied until the tax PBI. `AccessClass` is not widened here. |
| Q2 | `StoryManifest` and the 25 story JSON files are not rewritten. They remain tutorial artifacts; production stops reading them. |
| Q3 | Accepted: approvals bound to a story version fail closed with "approve again". |
| Q4 | #1340 closes on CODE-ONLY evidence once its PR merges. Hermes-driven execution belongs to HFP-P04 (#1341). |
| Q5 | Ship only the synthetic pure-math workflow. |
| Q6 | The registry exposes both legacy story runs and workflow runs for now. |

Model policy: the worktree `CLAUDE.md` on `portfolio` (D1, model-agnostic) governs.
