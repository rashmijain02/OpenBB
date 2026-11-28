# Hermes financial assistant - proposed GitHub delivery hierarchy

Plan `hermes-financial-planning`; SHA256 `51090ba02c432a36d557abf2060f9aec025516353d560e9c1b98342e598e1cbb`.

Target: `rashmijain02/OpenBB`, Project 1 owned by `rashmijain02`.
Draft planning artifact. GitHub publication and product implementation require separate approval.

## Decisions

- Interview: personal reusable skill, adapting to each repository's rules.
- Epic -> Feature -> PBI are GitHub issues; Tasks are checklists, not separate issues.
- Full decomposition across all selected roadmap phases; no fixed dates or staffing assumptions.
- Relative S/M/L estimates with rationale and low confidence until child implementation specs are qualified.
- YAML is the canonical plan; generated Markdown is a view; GitHub remains execution-status authority.
- Product descendants use proposed program:hermes-financial-planning; FMP cron descendants inherit program:openbb-jobs.
- Add PBI to project Type and a separate Roadmap phase field only after preview approval; preserve the existing Phase field.
- Keep Paperless + Docling as the baseline; Vault-Lite remains an unselected alternative.
- Publishing planning issues is not G1 approval, execution authorization, deployment consent or source publication.
- Issue #1312 (financial-planning proposal) stays unchanged as the design reference.
- Each Task delivers a tested observable slice; red-first and real-path evidence are required before marking it done.

## Excluded

- PF-28 through PF-33 candidate extensions, template valuation haircuts, options illustrations and automated order tickets.
- Gmail, WhatsApp, new external messaging accounts and other future personal connectors.
- Live brokerage access, trades, transfers, tax filing or payments.
- FMP storage/schema/retention/prune redesign; existing owner issues remain dependencies.
- Reinstallation of OpenBBPortfolio service, new scheduler daemons, unrestricted agent shell/SQL or a second harness.
- Automatic choice of pilot states, activation of semantic search/digest, or raw-document model access.
- Unrequested commits, pushes, PRs, issue closure/deletion/reparenting, private input reads or runtime changes.

## Hierarchy

| ID | Kind | Parent | Phase | Outcome |
|---|---|---|---|---|
| HFP-E01 | epic | - | cross | Safe native Hermes financial workspace |
| HFP-E02 | epic | - | cross | Deterministic FMP cache operations |
| HFP-E03 | epic | - | cross | OpenBB analytical capability parity |
| HFP-E04 | epic | - | 1b | Nautilus strategy and simulation migration |
| HFP-E05 | epic | - | cross | Private household tax and document foundation |
| HFP-E06 | epic | - | 4 | Tax-aware wealth and retirement planning |
| HFP-E07 | epic | - | 5 | Evidence delivery and operational qualification |
| HFP-F01 | feature | HFP-E01 | 0 | Runtime and privacy admission |
| HFP-F02 | feature | HFP-E01 | 1 | Notebook-free workflow and run contracts |
| HFP-F03 | feature | HFP-E01 | 1 | Unified web and Workspace experience |
| HFP-F04 | feature | HFP-E02 | cross | FMP warming validation and gated expansion |
| HFP-F05 | feature | HFP-E03 | 2A | Core portfolio and single-name research |
| HFP-F06 | feature | HFP-E03 | 2B | Remaining capability and knowledge qualification |
| HFP-F07 | feature | HFP-E04 | 1b | Isolated Nautilus runtime and adapters |
| HFP-F08 | feature | HFP-E04 | 1b | Independent statistical qualification and cutover |
| HFP-F09 | feature | HFP-E05 | 3 | Household facts and cash reconciliation |
| HFP-F10 | feature | HFP-E05 | cross | Qualified tax engines and jurisdiction coverage |
| HFP-F11 | feature | HFP-E05 | 3a | Private document evidence pipeline |
| HFP-F12 | feature | HFP-E06 | 4 | Lots compensation and tax-aware alternatives |
| HFP-F13 | feature | HFP-E06 | 4 | Retirement and household goals |
| HFP-F14 | feature | HFP-E07 | 5 | Monitoring and private review packages |
| HFP-F15 | feature | HFP-E07 | 5 | Product resilience and release qualification |
| HFP-P01 | pbi | HFP-F01 | 0 | Qualify native runtime provenance and connection health |
| HFP-P02 | pbi | HFP-F01 | 0 | Enforce private data and immutable skill boundaries |
| HFP-P03 | pbi | HFP-F02 | 1 | Extract notebook-independent workflow manifests |
| HFP-P04 | pbi | HFP-F02 | 1 | Bind Hermes runs to resumable jobs and approvals |
| HFP-P05 | pbi | HFP-F03 | 1 | Deliver the native Hermes web vertical slice |
| HFP-P06 | pbi | HFP-F03 | 1 | Unify Workspace conversation and private metric display |
| HFP-P07 | pbi | HFP-F04 | 1 | Run guarded price warming through Hermes no-agent cron |
| HFP-P08 | pbi | HFP-F04 | 1 | Extend market readiness and independent operational audits |
| HFP-P09 | pbi | HFP-F04 | 2B | Admit retention-safe ETF and reference schedules |
| HFP-P10 | pbi | HFP-F05 | 2A | Expose core look-through risk attribution and catalysts |
| HFP-P11 | pbi | HFP-F05 | 2A | Reconcile seven-phase analysis with independent filings |
| HFP-P12 | pbi | HFP-F06 | 2A | Qualify core portfolio scenario and analyst-basket workflows |
| HFP-P13 | pbi | HFP-F06 | 2B | Qualify TechTrade workflows against the selected backend |
| HFP-P14 | pbi | HFP-F06 | 2B | Disposition documentation examples and provider variants |
| HFP-P15 | pbi | HFP-F07 | 1b | Qualify the isolated Nautilus runtime and data catalog |
| HFP-P16 | pbi | HFP-F07 | 1b | Standardize reviewed strategies and preserve OpenBB callers |
| HFP-P17 | pbi | HFP-F08 | 1b | Preserve independent validation and complete trial accounting |
| HFP-P18 | pbi | HFP-F08 | 1b | Cut over qualified simulation and paper consumers |
| HFP-P19 | pbi | HFP-F09 | 3 | Accept versioned household inputs in an isolated private store |
| HFP-P20 | pbi | HFP-F09 | 3 | Reconcile household balance sheet and cash flow |
| HFP-P21 | pbi | HFP-F10 | 3 | Qualify the initial federal annual-tax subset |
| HFP-P22 | pbi | HFP-F10 | 3 | Qualify federal-to-California tax comparisons |
| HFP-P23 | pbi | HFP-F10 | 5 | Expose jurisdiction coverage and one selected residency pilot |
| HFP-P24 | pbi | HFP-F11 | 3a | Integrate the private Paperless document vault |
| HFP-P25 | pbi | HFP-F11 | 3a | Review extracted fields before accepting financial facts |
| HFP-P26 | pbi | HFP-F11 | 3a | Deliver authorized exact search and qualify optional semantics |
| HFP-P27 | pbi | HFP-F12 | 4 | Reconcile lot basis and RSU/ESPP compensation events |
| HFP-P28 | pbi | HFP-F12 | 4 | Apply bounded household wash-sale and lot constraints |
| HFP-P29 | pbi | HFP-F12 | 4 | Compare tax-aware portfolio alternatives |
| HFP-P30 | pbi | HFP-F13 | 4 | Qualify bounded retirement and conversion scenarios |
| HFP-P31 | pbi | HFP-F13 | 4 | Compare household reserve debt and goal scenarios |
| HFP-P32 | pbi | HFP-F14 | 5 | Schedule bounded briefings and deadline reminders |
| HFP-P33 | pbi | HFP-F14 | 5 | Export an authorized private decision and CPA package |
| HFP-P34 | pbi | HFP-F15 | 5 | Qualify resource admission backup and failure recovery |
| HFP-P35 | pbi | HFP-F15 | 5 | Certify the selected capability and privacy release matrix |
| HFP-P36 | pbi | HFP-F12 | 4 | Qualify ISO AMT and compensation sourcing extensions |
| HFP-P37 | pbi | HFP-F11 | 3a | Enforce private document revocation deletion and restore |
| HFP-P38 | pbi | HFP-F06 | 2B | Build scoped public knowledge and source-grounded Q&A |

## External prerequisites

- **G1:** Owner approval of the reconciled spec and implementation plan; all implementation remains gated
- **OPS-ATTEST:** Separately authorized operator evidence of credential remediation, network isolation, backup target and runtime identity
- **FMP-QUOTA:** Verified current entitlement and shared account request/bandwidth allocation
- **STORE-1300:** rashmijain02/OpenBB#1300 (Persistent raw store): approved non-destructive ETF/reference refresh interface; no duplicated storage work
- **SWITCH-1301:** rashmijain02/OpenBB#1301 (Switch-over and plan-limited fixtures): compatible routing/provenance acceptance
- **PRIVATE-APPROVAL:** Explicit private-service identity, storage and data-access approval; synthetic inputs until then
- **TAX-YEAR:** Owner-selected tax year and qualified statutory manifest; official forms and exceptions verified
- **STATE-PILOT:** Owner selects a non-CA pilot jurisdiction and bounded residency/features
- **OPTIONAL-SEMANTIC:** Owner accepts benchmark results and separately permits the local semantic index
- **SOURCES-PINNED:** Approved release/runtime/source hashes and dependency licenses verified before execution
- **WEBUI-OWNER:** Owner-approved WebUI-fork work if required; OpenBB issues own integration and acceptance, not authorization to modify another repository

## Issue-ready bodies

### HFP-E01: Safe native Hermes financial workspace

<!-- spec-plan:hermes-financial-planning:HFP-E01 -->
**Outcome:** One local harness and authenticated browser experience with explicit private-data boundaries
**Kind / parent / phase:** epic / - / cross
**Program / area / priority:** program:hermes-financial-planning / area:core / P0
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E02: Deterministic FMP cache operations

<!-- spec-plan:hermes-financial-planning:HFP-E02 -->
**Outcome:** Freshness and health are observable without LLM calls or durable-data deletion
**Kind / parent / phase:** epic / - / cross
**Program / area / priority:** program:openbb-jobs / area:jobs / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E03: OpenBB analytical capability parity

<!-- spec-plan:hermes-financial-planning:HFP-E03 -->
**Outcome:** Existing financial capabilities are qualified through Hermes rather than notebook execution
**Kind / parent / phase:** epic / - / cross
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E04: Nautilus strategy and simulation migration

<!-- spec-plan:hermes-financial-planning:HFP-E04 -->
**Outcome:** One qualified event-simulation authority behind existing OpenBB interfaces
**Kind / parent / phase:** epic / - / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E05: Private household tax and document foundation

<!-- spec-plan:hermes-financial-planning:HFP-E05 -->
**Outcome:** Reviewed household facts and evidence support qualified federal and state calculations
**Kind / parent / phase:** epic / - / cross
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E06: Tax-aware wealth and retirement planning

<!-- spec-plan:hermes-financial-planning:HFP-E06 -->
**Outcome:** Deterministic lot and long-horizon alternatives respect household constraints
**Kind / parent / phase:** epic / - / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-E07: Evidence delivery and operational qualification

<!-- spec-plan:hermes-financial-planning:HFP-E07 -->
**Outcome:** Reports monitoring and recovery remain useful truthful and private across the product
**Kind / parent / phase:** epic / - / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F01: Runtime and privacy admission

<!-- spec-plan:hermes-financial-planning:HFP-F01 -->
**Outcome:** Misconfigured or unsafe runtimes fail closed before financial operations
**Kind / parent / phase:** feature / HFP-E01 / 0
**Program / area / priority:** program:hermes-financial-planning / area:core / P0
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F02: Notebook-free workflow and run contracts

<!-- spec-plan:hermes-financial-planning:HFP-F02 -->
**Outcome:** Hermes owns orchestration with resumable typed workflows
**Kind / parent / phase:** feature / HFP-E01 / 1
**Program / area / priority:** program:hermes-financial-planning / area:agents / P0
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F03: Unified web and Workspace experience

<!-- spec-plan:hermes-financial-planning:HFP-F03 -->
**Outcome:** One authenticated conversation and evidence identity across both UIs
**Kind / parent / phase:** feature / HFP-E01 / 1
**Program / area / priority:** program:hermes-financial-planning / area:workspace / P0
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F04: FMP warming validation and gated expansion

<!-- spec-plan:hermes-financial-planning:HFP-F04 -->
**Outcome:** Shared guarded warmers provide counts-only operational evidence
**Kind / parent / phase:** feature / HFP-E02 / cross
**Program / area / priority:** program:openbb-jobs / area:jobs / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F05: Core portfolio and single-name research

<!-- spec-plan:hermes-financial-planning:HFP-F05 -->
**Outcome:** Existing analytics and independent filing evidence remain traceable
**Kind / parent / phase:** feature / HFP-E03 / 2A
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F06: Remaining capability and knowledge qualification

<!-- spec-plan:hermes-financial-planning:HFP-F06 -->
**Outcome:** Tutorials and public references map to tested production capabilities
**Kind / parent / phase:** feature / HFP-E03 / 2B
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F07: Isolated Nautilus runtime and adapters

<!-- spec-plan:hermes-financial-planning:HFP-F07 -->
**Outcome:** Pinned data strategy and result contracts preserve callers
**Kind / parent / phase:** feature / HFP-E04 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F08: Independent statistical qualification and cutover

<!-- spec-plan:hermes-financial-planning:HFP-F08 -->
**Outcome:** Accepted simulations migrate without losing trials ledger boundaries or rollback
**Kind / parent / phase:** feature / HFP-E04 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F09: Household facts and cash reconciliation

<!-- spec-plan:hermes-financial-planning:HFP-F09 -->
**Outcome:** Accepted private snapshots are complete versioned and reconciled
**Kind / parent / phase:** feature / HFP-E05 / 3
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F10: Qualified tax engines and jurisdiction coverage

<!-- spec-plan:hermes-financial-planning:HFP-F10 -->
**Outcome:** Supported tax cases are distinguishable from unknown or unsupported cases
**Kind / parent / phase:** feature / HFP-E05 / cross
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F11: Private document evidence pipeline

<!-- spec-plan:hermes-financial-planning:HFP-F11 -->
**Outcome:** Reviewed extraction and authorized retrieval preserve document lineage
**Kind / parent / phase:** feature / HFP-E05 / 3a
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F12: Lots compensation and tax-aware alternatives

<!-- spec-plan:hermes-financial-planning:HFP-F12 -->
**Outcome:** Basis income and household constraints survive portfolio comparisons
**Kind / parent / phase:** feature / HFP-E06 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F13: Retirement and household goals

<!-- spec-plan:hermes-financial-planning:HFP-F13 -->
**Outcome:** Bounded long-horizon and goal scenarios disclose assumptions and limitations
**Kind / parent / phase:** feature / HFP-E06 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F14: Monitoring and private review packages

<!-- spec-plan:hermes-financial-planning:HFP-F14 -->
**Outcome:** Owner receives timely evidence without implicit transactions
**Kind / parent / phase:** feature / HFP-E07 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-F15: Product resilience and release qualification

<!-- spec-plan:hermes-financial-planning:HFP-F15 -->
**Outcome:** Recovery privacy and full selected-scope coverage have independent evidence
**Kind / parent / phase:** feature / HFP-E07 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Acceptance:** All child outcomes accepted; no independent implementation scope or double-counted effort.

### HFP-P01: Qualify native runtime provenance and connection health

<!-- spec-plan:hermes-financial-planning:HFP-P01 -->
**Outcome:** Owner can distinguish configured authenticated admitted callable and qualified services before use.
**Kind / parent / phase:** pbi / HFP-F01 / 0
**Program / area / priority:** program:hermes-financial-planning / area:core / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `11`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `12`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `9`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-20, PF-26
**Primary for:** PF-20, PF-26
**Dependencies:** G1, SOURCES-PINNED
**Estimate:** L (low): Multiple native processes and independent package origins require real-path qualification

**Acceptance**
- Given the selected native runtime and local aliases, health reports exact process and module provenance without secret values.
- Given a stopped model, wrong database or incompatible ABI, admission blocks and reports the failed layer instead of installing or falling back.

**Tasks**
- [ ] HFP-P01-T01: Implement metadata-only provenance checks with wrong-origin and wrong-database regression cases.
- [ ] HFP-P01-T02: Qualify the selected Hermes/WebUI and provider handshake matrix with unavailable-service outcomes.
- [ ] HFP-P01-T03: Bind existing LiteLLM aliases to verified local backends and prove refused-backend behavior with synthetic sentinels.

**Verification:** Run the real native health/preflight path against a synthetic profile and denied backend; record versions and failure states.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P02: Enforce private data and immutable skill boundaries

<!-- spec-plan:hermes-financial-planning:HFP-P02 -->
**Outcome:** Raw household facts stay in authorized services while Hermes receives only reviewed evidence projections.
**Kind / parent / phase:** pbi / HFP-F01 / 0
**Program / area / priority:** program:hermes-financial-planning / area:core / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `4.8`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `4`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `12`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-18, PF-26
**Primary for:** PF-18
**Dependencies:** HFP-P01, PRIVATE-APPROVAL
**Estimate:** L (low): Cross-process authorization and inference-risk controls must agree

**Acceptance**
- Given private-shaped sentinels, model logs callbacks memory and provider requests contain no raw values.
- Given unauthorized artifact fields, writable runtime skills or a hosted fallback route, the request fails closed.

**Tasks**
- [ ] HFP-P02-T01: Implement principal and operation-scoped access capabilities with default-deny tests.
- [ ] HFP-P02-T02: Enforce read-only admitted skills and quarantined proposals using synthetic write-denial cases.
- [ ] HFP-P02-T03: Qualify field-level evidence projections and local-only routing under inference logging and fallback failures.

**Verification:** Exercise denied routes and artifact reads through the actual policy boundary using synthetic private-shaped data.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P03: Extract notebook-independent workflow manifests

<!-- spec-plan:hermes-financial-planning:HFP-P03 -->
**Outcome:** Production workflows run without notebook files kernels or notebook readiness imports.
**Kind / parent / phase:** pbi / HFP-F02 / 1
**Program / area / priority:** program:hermes-financial-planning / area:agents / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-27`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.1`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `5`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-27, PF-03
**Primary for:** PF-27
**Dependencies:** HFP-P01
**Estimate:** M (low): Existing story contracts can be reused but path and hash coupling must be removed

**Acceptance**
- Given an admitted WorkflowManifest, the same shared engine executes with notebook directories unmounted.
- Given unknown access literals, schema drift or a runtime notebook dependency, admission rejects the workflow.

**Tasks**
- [ ] HFP-P03-T01: Extract typed workflow and access-version contracts with schema-drift rejection cases.
- [ ] HFP-P03-T02: Move cell/hash mappings to optional tutorial traceability without runtime imports.
- [ ] HFP-P03-T03: Demonstrate an engine-backed workflow with notebook files and kernels absent.

**Verification:** Run a synthetic browser-independent workflow against shared services in a notebook-free runtime.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P04: Bind Hermes runs to resumable jobs and approvals

<!-- spec-plan:hermes-financial-planning:HFP-P04 -->
**Outcome:** Lost replies cancellation and restart cannot duplicate jobs artifacts or paper effects.
**Kind / parent / phase:** pbi / HFP-F02 / 1
**Program / area / priority:** program:hermes-financial-planning / area:agents / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-17`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `8`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-17, PF-27
**Primary for:** PF-17
**Dependencies:** HFP-P03, HFP-P02
**Estimate:** L (low): Reuses issue 215 adapters but introduces new coordinator and restart boundaries

**Acceptance**
- Given repeated delivery of one operation, existing job/artifact adapters retain one logical outcome.
- Given expired approval changed arguments or drifted workflow hashes, resume requires a new decision and partial states never become success.

**Tasks**
- [ ] HFP-P04-T01: Bind existing job and artifact adapters to Hermes run IDs and workflow digests with duplicate-submit tests.
- [ ] HFP-P04-T02: Add explicit cancel-requested confirmed and too-late outcomes without promising unsupported interruption.
- [ ] HFP-P04-T03: Prove restart and approval-replay behavior while preserving the existing Portfolio/TechTrade action contracts.

**Verification:** Exercise actual adapter calls with lost responses and restarted coordinator; inspect durable receipts rather than LLM prose.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P05: Deliver the native Hermes web vertical slice

<!-- spec-plan:hermes-financial-planning:HFP-P05 -->
**Outcome:** Owner can select a workflow preview its plan approve it and inspect run evidence in one local browser app.
**Kind / parent / phase:** pbi / HFP-F03 / 1
**Program / area / priority:** program:hermes-financial-planning / area:workspace / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `6`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `12`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `12`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-25, PF-26
**Primary for:** PF-25
**Dependencies:** HFP-P04, WEBUI-OWNER
**Estimate:** L (low): WebUI delegation and native runtime compatibility are not yet qualified

**Acceptance**
- Given the synthetic basket x-ray workflow, browser interaction reaches native Hermes and returns engine-backed evidence.
- Given reconnect duplicate clicks or cross-origin approval attempts, the UI observes existing state or rejects the request without duplicate work.

**Tasks**
- [ ] HFP-P05-T01: Qualify native WebUI delegation and authenticated sessions with cross-origin rejection tests.
- [ ] HFP-P05-T02: Implement plan/run/approval cards using shared IDs and explicit unavailable states.
- [ ] HFP-P05-T03: Demonstrate browser disconnect and reconnect without restarting the run or enabling another agent loop.

**Verification:** Real browser journey from workflow selection to authorized result using synthetic engine inputs.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P06: Unify Workspace conversation and private metric display

<!-- spec-plan:hermes-financial-planning:HFP-P06 -->
**Outcome:** Workspace shares Hermes run identity while exact private metrics render only through authorized UI requests.
**Kind / parent / phase:** pbi / HFP-F03 / 1
**Program / area / priority:** program:hermes-financial-planning / area:workspace / P0
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `6`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.1`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `4`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-16, PF-18, PF-25
**Primary for:** PF-16
**Dependencies:** HFP-P05
**Estimate:** L (low): Two UIs and multiple artifact/context paths must enforce one policy

**Acceptance**
- Given an authorized drill-through, both UIs refer to the same run and private fields hydrate only in the browser.
- Given an external copilot path or unauthorized field token, private widgets remain denied; unqualified query delegation stays disabled.

**Tasks**
- [ ] HFP-P06-T01: Proxy the production query contract to Hermes or explicitly disable it until qualified.
- [ ] HFP-P06-T02: Implement principal/run/artifact/field authorization for metric tokens and deny arbitrary paths.
- [ ] HFP-P06-T03: Prove hydrated values do not re-enter chat memory telemetry or external widget context.

**Verification:** Native Workspace browser acceptance with selected private-shaped widgets and handcrafted denied queries.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P07: Run guarded price warming through Hermes no-agent cron

<!-- spec-plan:hermes-financial-planning:HFP-P07 -->
**Outcome:** Approved ticker scope is warmed through existing functions with bounded cost and private operational receipts.
**Kind / parent / phase:** pbi / HFP-F04 / 1
**Program / area / priority:** program:openbb-jobs / area:jobs / P0
**Sources (local planning references, not published permalinks):** `prompts\out\fmp-cache-hermes-sync-design.md` section `4`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `5`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `8`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `13`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`
**Requirements:** OPS-01, OPS-03, OPS-06
**Primary for:** OPS-01, OPS-03, OPS-06
**Dependencies:** HFP-P01, OPS-ATTEST, FMP-QUOTA
**Estimate:** L (low): Direct warmer reuse is bounded by process locks transport accounting and durable state

**Acceptance**
- Given an approved database and ticker manifest, the existing history warmer runs without LLM calls and produces structured status/history.
- Given wrong target, lock contention, secret-bearing failure or quota exhaustion, it blocks/defers safely without raw output or durable deletion.

**Tasks**
- [ ] HFP-P07-T01: Add shared manual/cron locking and explicit target/universe admission with wrong-target and contention tests.
- [ ] HFP-P07-T02: Wrap existing warming with transport-accounted budgets cancellation deadlines and sanitized structured outcomes.
- [ ] HFP-P07-T03: Render versioned paused cron wrappers and durable state-change receipts including Windows replacement failure handling.

**Verification:** Disposable-database no-agent run plus a second manual process contending for the same lock; capture API counts and redacted receipts.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P08: Extend market readiness and independent operational audits

<!-- spec-plan:hermes-financial-planning:HFP-P08 -->
**Outcome:** The owner can distinguish real coverage gaps lifecycle exclusions infrastructure failure and unknown evidence.
**Kind / parent / phase:** pbi / HFP-F04 / 1
**Program / area / priority:** program:openbb-jobs / area:jobs / P1
**Sources (local planning references, not published permalinks):** `prompts\out\fmp-cache-hermes-sync-design.md` section `6`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `9`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `10`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`
**Requirements:** OPS-02, OPS-04, OPS-07
**Primary for:** OPS-02, OPS-04, OPS-07
**Dependencies:** HFP-P07
**Estimate:** L (low): Calendar data semantics and recovery faults require independent fixtures

**Acceptance**
- Given holidays half-days DST and next-year fixtures, Pacific schedules evaluate the correct Eastern market session and real dry-run readiness.
- Given NULL partitions missing private-table grants ambiguous timestamps or unknown delivery, checks report explicit states without fabricated health or repeated fetch storms.

**Tasks**
- [ ] HFP-P08-T01: Extend existing readiness with dry-run evaluation optional private counts table-case checks and lifecycle-aware sessions.
- [ ] HFP-P08-T02: Add bounded integrity and matched-basis fundamental diagnostics with loud empty and unavailable evidence cases.
- [ ] HFP-P08-T03: Prove backup/binlog/disk observability and catch-up recovery under test gateway failure and simulated 429 responses.

**Verification:** Synthetic calendar and disposable SQL fixtures plus test-only recovery exercises; no production service interruption.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P09: Admit retention-safe ETF and reference schedules

<!-- spec-plan:hermes-financial-planning:HFP-P09 -->
**Outcome:** Additional approved datasets refresh only through storage-owner-qualified non-destructive interfaces.
**Kind / parent / phase:** pbi / HFP-F04 / 2B
**Program / area / priority:** program:openbb-jobs / area:jobs / P1
**Sources (local planning references, not published permalinks):** `prompts\out\fmp-cache-hermes-sync-design.md` section `3`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `7`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`; `prompts\out\fmp-cache-hermes-sync-design.md` section `11`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`
**Requirements:** OPS-05, OPS-01, OPS-02
**Primary for:** OPS-05
**Dependencies:** HFP-P08, STORE-1300, SWITCH-1301
**Estimate:** M (low): Integration reuses warmers but depends on separately delivered storage capability

**Acceptance**
- Given accepted storage interfaces and quotas, weekly ETF and selected reference refreshes preserve historical records and validate pagination.
- Given legacy delete/truncate paths or incomplete capability acceptance, jobs remain blocked even when manually triggered.

**Tasks**
- [ ] HFP-P09-T01: Bind capability admission to approved owner interfaces and reject destructive legacy fallbacks.
- [ ] HFP-P09-T02: Qualify selected dataset cadence completeness and shared budget behavior with retained-history fixtures.
- [ ] HFP-P09-T03: Preview approved trigger cutover and prove pause/rollback leaves unrelated jobs backups and data unchanged.

**Verification:** Disposable retention and paging tests followed by explicitly approved paused-job deployment evidence.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P10: Expose core look-through risk attribution and catalysts

<!-- spec-plan:hermes-financial-planning:HFP-P10 -->
**Outcome:** Owner receives the existing portfolio analytical evidence with aligned coverage and as-of dates.
**Kind / parent / phase:** pbi / HFP-F05 / 2A
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-06`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W1`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `3`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-06, PF-03
**Primary for:** PF-06
**Dependencies:** HFP-P05
**Estimate:** M (low): Existing domain engines reduce implementation but cross-adapter evidence needs qualification

**Acceptance**
- Given a synthetic portfolio, shared engines produce independently expected concentration risk attribution and catalyst artifacts.
- Given missing constituents mismatched dates or absent provider data, coverage limitations are visible rather than filled with invented values.

**Tasks**
- [ ] HFP-P10-T01: Map existing look-through/risk adapters to notebook-free workflow inputs and independent fixtures.
- [ ] HFP-P10-T02: Normalize as-of and coverage metadata across attribution and catalyst evidence.
- [ ] HFP-P10-T03: Exercise the combined x-ray workflow through Hermes without reimplementing financial engines.

**Verification:** Engine-backed synthetic x-ray with missing-data and mixed-date cases rendered in the real UI.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P11: Reconcile seven-phase analysis with independent filings

<!-- spec-plan:hermes-financial-planning:HFP-P11 -->
**Outcome:** A single-name memo separates pipeline results filing evidence discrepancies and unknowns.
**Kind / parent / phase:** pbi / HFP-F05 / 2A
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W2`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `VendorReconciliationReport`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `R18`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-05, PF-15
**Primary for:** PF-05
**Dependencies:** HFP-P10
**Estimate:** L (low): Filing coverage and accounting-basis reconciliation are substantial domain boundaries

**Acceptance**
- Given complete synthetic filing evidence, all seven existing phases and eight matched-basis vendor diagnostics appear with provenance.
- Given truncated filings unsupported XBRL or repeated legitimate shares, the memo reports unknown/diagnostic states without overwriting vendor data or applying unselected heuristics.

**Tasks**
- [ ] HFP-P11-T01: Bridge the actual seven-phase pipeline and preserve gates and source timestamps.
- [ ] HFP-P11-T02: Implement the independent filing-evidence adapter and matched-basis discrepancy report before synthesis sees pipeline conclusions.
- [ ] HFP-P11-T03: Generate the scorecard and differences section with missing-source abstention and no illustrative trade tickets.

**Verification:** Replay recorded public/synthetic filing shapes and compare deterministic report facts against independent expected values.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P12: Qualify core portfolio scenario and analyst-basket workflows

<!-- spec-plan:hermes-financial-planning:HFP-P12 -->
**Outcome:** Owner can compare portfolio what-if and analyst-basket alternatives without running tutorial cells.
**Kind / parent / phase:** pbi / HFP-F06 / 2A
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-03`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `3`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-03, PF-06
**Primary for:** -
**Dependencies:** HFP-P10
**Estimate:** L (low): Multiple existing workflows need consolidated independent acceptance rather than new engines

**Acceptance**
- Given approved synthetic inputs, core portfolio workflow results match independent service-level expectations and retain do-nothing comparisons.
- Given fixture gaps or provider mismatches, the workflow blocks the affected result rather than mixing unapproved modes.

**Tasks**
- [ ] HFP-P12-T01: Map the eight core portfolio tutorial capabilities to runtime workflows and approved provider contracts.
- [ ] HFP-P12-T02: Qualify what-if attribution and analyst-basket outputs with independent scenario fixtures.
- [ ] HFP-P12-T03: Verify mode/source provenance and user-visible partial outcomes without any notebook runtime dependency.

**Verification:** Direct service and controlled Hermes replay for core portfolio scenarios; simulation-specific evidence links to the qualified Nautilus track.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P13: Qualify TechTrade workflows against the selected backend

<!-- spec-plan:hermes-financial-planning:HFP-P13 -->
**Outcome:** Scans tuning batches workbooks and paper fills retain intent and ledger boundaries after integration.
**Kind / parent / phase:** pbi / HFP-F06 / 2B
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-08`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `9.1`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.3`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-08, PF-03, BT-03
**Primary for:** PF-08
**Dependencies:** HFP-P18, HFP-P12
**Estimate:** L (low): Existing workflows span several state machines and depend on backend cutover

**Acceptance**
- Given reviewed synthetic strategy inputs, scans through approved paper artifacts retain expected intent and bounded validation evidence.
- Given duplicate delivery mismatched strategy hash or unsupported intrabar assumptions, no duplicate fills or success-shaped fallback occurs.

**Tasks**
- [ ] HFP-P13-T01: Bind existing scan/tuning and workbook surfaces without recreating the fmp_trading bridge owned by issue 151.
- [ ] HFP-P13-T02: Route simulation-dependent validation through the accepted Nautilus adapter and retain trial lineage.
- [ ] HFP-P13-T03: Exercise end-to-end batches and separate Portfolio/TechTrade paper state with duplicate-effect rejection.

**Verification:** Synthetic scan-to-workbook-to-approved-paper journey with deterministic expected fills and failure cases.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P14: Disposition documentation examples and provider variants

<!-- spec-plan:hermes-financial-planning:HFP-P14 -->
**Outcome:** Every referenced example and alternate provider capability has an explicit supported or excluded production disposition.
**Kind / parent / phase:** pbi / HFP-F06 / 2B
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-04`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `3`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `4`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-04, PF-03
**Primary for:** PF-04
**Dependencies:** HFP-P12
**Estimate:** M (low): Classification and adapter qualification reuse existing capabilities

**Acceptance**
- Given the eleven documentation examples and alternate-provider tutorials, each maps to analytics explanation setup-only or template coverage.
- Given a YFinance illustration or unavailable field, production policy remains cache-first and does not authorize the disallowed provider.

**Tasks**
- [ ] HFP-P14-T01: Create source-to-capability dispositions for all eleven examples with independent evidence references.
- [ ] HFP-P14-T02: Map alternate-provider tutorial intent to approved production sources or explicit unsupported outcomes.
- [ ] HFP-P14-T03: Preserve tutorials for manual learning while checking that no production workflow imports their execution state.

**Verification:** Validate the complete example inventory and run its selected service-level cases without notebook kernels.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P15: Qualify the isolated Nautilus runtime and data catalog

<!-- spec-plan:hermes-financial-planning:HFP-P15 -->
**Outcome:** Approved historical data reaches a pinned isolated worker with reproducible transformations and no broker access.
**Kind / parent / phase:** pbi / HFP-F07 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `9.1`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.1`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `S34`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** BT-02, BT-01
**Primary for:** -
**Dependencies:** HFP-P01, SOURCES-PINNED
**Estimate:** L (low): Compiled runtime compatibility and data normalization are unqualified

**Acceptance**
- Given the selected wheel and dataset, worker ABI precision calendar and catalog hashes are recorded and accepted transformations reproduce.
- Given arbitrary paths wrong hashes incompatible precision or a broker endpoint, worker admission rejects the request.

**Tasks**
- [ ] HFP-P15-T01: Compare the candidate native and local-container runtimes with pinned wheel/license/precision evidence.
- [ ] HFP-P15-T02: Adapt cache-derived data to content-addressed catalogs with action basis and calendar checks.
- [ ] HFP-P15-T03: Enforce authenticated worker bounds and verify no broker credentials or order-network permissions exist.

**Verification:** Independent buy-and-hold data case on the selected real worker; no generic adapter framework duplication of issue 4.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P16: Standardize reviewed strategies and preserve OpenBB callers

<!-- spec-plan:hermes-financial-planning:HFP-P16 -->
**Outcome:** Existing callers invoke a versioned Nautilus backend with typed strategy and result contracts.
**Kind / parent / phase:** pbi / HFP-F07 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `BT-01`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `BT-02`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.2`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** BT-01, BT-02
**Primary for:** BT-01, BT-02
**Dependencies:** HFP-P15, HFP-P03
**Estimate:** L (low): Strategy semantics cash availability and result compatibility must be reconciled

**Acceptance**
- Given a reviewed StrategySpec, code and parameter hashes bind event timing sizing and normalized output to the run.
- Given an unsupported strategy arbitrary plugin or settlement assumption, the facade rejects it instead of silently using the legacy engine.

**Tasks**
- [ ] HFP-P16-T01: Implement reviewed strategy metadata and loader allowlists with code/parameter drift rejection.
- [ ] HFP-P16-T02: Add explicit backend selection and normalized result projection behind the existing facade.
- [ ] HFP-P16-T03: Prove settlement-aware sell-before-buy staging and declared fixed-point rounding against independent cash cases.

**Verification:** Buy-and-hold and multi-asset rebalance golden cases through the actual OpenBB facade and worker.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P17: Preserve independent validation and complete trial accounting

<!-- spec-plan:hermes-financial-planning:HFP-P17 -->
**Outcome:** Statistical conclusions retain the full experiment population across isolated worker folds and retries.
**Kind / parent / phase:** pbi / HFP-F08 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `BT-03`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.3`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** BT-03
**Primary for:** -
**Dependencies:** HFP-P16
**Estimate:** L (low): Statistical qualification needs complete experiment semantics not only a count field

**Acceptance**
- Given sweeps and folds split across workers, retained trial IDs return matrices and exclusions reproduce qualified DSR/PBO/CPCV results.
- Given worker retries failed trials or changed data, deduplication and provenance prevent understated multiple-testing penalties.

**Tasks**
- [ ] HFP-P17-T01: Normalize fold returns and trial lineage while preserving all evaluated configurations and exclusions.
- [ ] HFP-P17-T02: Qualify statistical bridges against independent matrices rather than legacy engine agreement.
- [ ] HFP-P17-T03: Benchmark realistic bounded jobs using existing test infrastructure and document material modeling differences.

**Verification:** Independent fold/sweep golden matrices and controlled failed-worker retries with known trial counts.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P18: Cut over qualified simulation and paper consumers

<!-- spec-plan:hermes-financial-planning:HFP-P18 -->
**Outcome:** Accepted consumers use one simulation authority with explicit rollback and preserved paper approvals.
**Kind / parent / phase:** pbi / HFP-F08 / 1b
**Program / area / priority:** program:hermes-financial-planning / area:backtest / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `9.1`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `3.3`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** BT-03, PF-08, PF-17
**Primary for:** BT-03
**Dependencies:** HFP-P17, HFP-P04
**Estimate:** L (low): Migration correctness spans callers historical evidence and paper effects

**Acceptance**
- Given qualified cases, each consumer records the chosen backend and preserves distinct paper ledgers and operation IDs.
- Given a rollback or unsupported feature, no silent fallback duplicate effect or unapproved brokerage capability appears.

**Tasks**
- [ ] HFP-P18-T01: Inventory consumer semantics and qualify the TechTrade case alongside the independent portfolio cases.
- [ ] HFP-P18-T02: Implement reviewed capability-by-capability selection and operator-controlled rollback using existing approvals.
- [ ] HFP-P18-T03: Retire only redundant migrated simulator paths while retaining historical replay and benchmark-justified screening.

**Verification:** Consumer cutover/replay matrix with approval mismatch duplicate delivery and rollback fixtures.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P19: Accept versioned household inputs in an isolated private store

<!-- spec-plan:hermes-financial-planning:HFP-P19 -->
**Outcome:** Owner supplies and confirms required facts before personalized computation is admitted.
**Kind / parent / phase:** pbi / HFP-F09 / 3
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-01`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `4`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `5`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-01, PF-18
**Primary for:** PF-01
**Dependencies:** HFP-P02, HFP-P06, PRIVATE-APPROVAL
**Estimate:** L (low): New private authority and consent boundary require independent qualification

**Acceptance**
- Given confirmed synthetic household inputs, accepted snapshots retain units ownership evidence and completeness state.
- Given missing facts stale versions or unauthorized principals, recommendations block without exposing raw facts or extending the market schema.

**Tasks**
- [ ] HFP-P19-T01: Implement private snapshot schemas and readiness with missing-fact and version-conflict cases.
- [ ] HFP-P19-T02: Qualify the separate encrypted store and key/restore permissions without redirecting existing imports.
- [ ] HFP-P19-T03: Provide authenticated intake/review that exposes only opaque references to Hermes.

**Verification:** Synthetic intake-to-readiness journey and denied cross-principal reads on the actual private service.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P20: Reconcile household balance sheet and cash flow

<!-- spec-plan:hermes-financial-planning:HFP-P20 -->
**Outcome:** Owner sees accepted assets liabilities and cash movements with discrepancies separated from income.
**Kind / parent / phase:** pbi / HFP-F09 / 3
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-02`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `HouseholdSnapshot`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-02, PF-13
**Primary for:** PF-02
**Dependencies:** HFP-P19
**Estimate:** M (low): Bounded accounting reconciliation reuses accepted private snapshot contracts

**Acceptance**
- Given synthetic transfers debt and account snapshots, balance and cash-flow totals reconcile without double-counting transfers.
- Given unknown balances stale membership or missing liabilities, the artifact shows incompleteness rather than a false consolidated net worth.

**Tasks**
- [ ] HFP-P20-T01: Implement normalized account/cashflow facts with transfer and currency-unit tests.
- [ ] HFP-P20-T02: Produce deterministic reconciliation and discrepancy artifacts from accepted snapshots.
- [ ] HFP-P20-T03: Render authorized household views with exact values kept outside model context.

**Verification:** Independent synthetic balance-sheet/cash-flow reconciliation through the private UI.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P21: Qualify the initial federal annual-tax subset

<!-- spec-plan:hermes-financial-planning:HFP-P21 -->
**Outcome:** Qualified federal scenarios return reproducible liabilities deltas and explicit unsupported features.
**Kind / parent / phase:** pbi / HFP-F10 / 3
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.2`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `TaxScenario`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `8`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-09
**Primary for:** -
**Dependencies:** HFP-P19, TAX-YEAR
**Estimate:** L (low): Year-specific tax correctness requires independent authority and engine qualification

**Acceptance**
- Given the selected year and supported wages interest dividends gains and deduction inputs, results match independent fixtures and prescribed rounding.
- Given unsupported forms expired law manifests or engine gaps, the service blocks the claimed result instead of returning zero tax.

**Tasks**
- [ ] HFP-P21-T01: Pin the statutory manifest and isolated PolicyEngine adapter with source-conflict and coverage tests.
- [ ] HFP-P21-T02: Qualify the initial income deduction credit payroll and estimated-tax subset against independent expected cases.
- [ ] HFP-P21-T03: Return opaque comparison artifacts and explicit unsupported treatment without raw tax facts in prompts.

**Verification:** Year-specific federal boundary fixtures and direct private-service scenario comparison.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P22: Qualify federal-to-California tax comparisons

<!-- spec-plan:hermes-financial-planning:HFP-P22 -->
**Outcome:** California differences and payment rules remain explicit rather than inheriting federal treatment.
**Kind / parent / phase:** pbi / HFP-F10 / 3
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.3`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `T11`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `T12`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-09, PF-10
**Primary for:** PF-09
**Dependencies:** HFP-P21
**Estimate:** L (low): State nonconformity and qualified authority coverage are correctness-heavy

**Acceptance**
- Given qualified California cases, state basis HSA treatment installments income thresholds and covered payroll rules use the selected year's authorities.
- Given an unsupported residency case missing issuer allocation or unverified authority, coverage is unknown/blocked rather than applying blanket exemption.

**Tasks**
- [ ] HFP-P22-T01: Implement qualified federal-to-state adjustment and separate basis/carryforward contracts.
- [ ] HFP-P22-T02: Test installment equality thresholds SDI coverage surtax and mortgage/fund-income exceptions against year-specific references.
- [ ] HFP-P22-T03: Publish combined federal/CA scenario evidence with independent rounding and unsupported-case checks.

**Verification:** Federal/CA golden comparisons including threshold equality wrong tax-year and missing Treasury-income allocation cases.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P23: Expose jurisdiction coverage and one selected residency pilot

<!-- spec-plan:hermes-financial-planning:HFP-P23 -->
**Outcome:** Owner can compare only certified state/year/residency subsets while all other jurisdictions remain honestly classified.
**Kind / parent / phase:** pbi / HFP-F10 / 5
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.4`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `JurisdictionCoverage`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-10
**Primary for:** PF-10
**Dependencies:** HFP-P22, STATE-PILOT
**Estimate:** L (low): Pilot scope cannot be finalized until the owner selects its jurisdiction and cases

**Acceptance**
- Given a selected pilot and qualified residency facts, its bounded comparison cites effective rules and support dimensions.
- Given any unqualified state feature expired certification or missing workday evidence, the 51-jurisdiction matrix does not advertise support or zero liability.

**Tasks**
- [ ] HFP-P23-T01: Implement multidimensional jurisdiction coverage and expiry with deny-on-unknown behavior.
- [ ] HFP-P23-T02: Qualify one owner-selected pilot's declared residency/income cases and source timeline.
- [ ] HFP-P23-T03: Render comparison limits and a repeatable qualification template without claiming all-state completion.

**Verification:** One explicitly selected pilot's boundary fixtures plus unsupported and expired entries across the coverage matrix.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P24: Integrate the private Paperless document vault

<!-- spec-plan:hermes-financial-planning:HFP-P24 -->
**Outcome:** Authorized originals and versions remain encrypted outside Git with controlled intake and recovery.
**Kind / parent / phase:** pbi / HFP-F11 / 3a
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W10`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.2`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-21, PF-24
**Primary for:** PF-21
**Dependencies:** HFP-P19
**Estimate:** L (low): Multi-service deployment and document isolation are unqualified

**Acceptance**
- Given authorized synthetic tax PDFs, originals hashes versions and ACLs survive ingestion and restore.
- Given malformed archives encrypted uploads or unapproved remote processing, intake isolates or blocks without logging content or passwords.

**Tasks**
- [ ] HFP-P24-T01: Qualify Paperless storage/encryption and bounded intake using synthetic documents only.
- [ ] HFP-P24-T02: Implement original/version identity corrected/amended relationships and private evidence references.
- [ ] HFP-P24-T03: Verify encrypted backup/restore and parser isolation without enabling hosted OCR or generic administration tools.

**Verification:** Real local synthetic upload/version/restore journey on the selected Paperless adapter.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P25: Review extracted fields before accepting financial facts

<!-- spec-plan:hermes-financial-planning:HFP-P25 -->
**Outcome:** Candidate OCR values become tax inputs only after review and deterministic validation with source lineage.
**Kind / parent / phase:** pbi / HFP-F11 / 3a
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-23`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.2`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.3`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-23, PF-21
**Primary for:** PF-23
**Dependencies:** HFP-P24
**Estimate:** L (low): Document interpretation and year-specific field semantics require reviewable evidence

**Acceptance**
- Given a reviewed synthetic form, accepted facts retain document version page/form-line units and correction decisions.
- Given low-confidence OCR conflicting versions or changed year layouts, no candidate silently becomes a calculation input.

**Tasks**
- [ ] HFP-P25-T01: Integrate bounded Docling extraction and preserve page/table/region mappings.
- [ ] HFP-P25-T02: Implement review acceptance and supersession with conflicting-field and OCR-error fixtures.
- [ ] HFP-P25-T03: Reconcile accepted cross-document facts through deterministic services and surface unsupported extraction.

**Verification:** Synthetic return/W-2 comparison including OCR error corrected upload and cited accepted facts.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P26: Deliver authorized exact search and qualify optional semantics

<!-- spec-plan:hermes-financial-planning:HFP-P26 -->
**Outcome:** Owner finds document evidence within allowed year/form/version scope with supported citations and abstention.
**Kind / parent / phase:** pbi / HFP-F11 / 3a
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-22`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.3`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `S29`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-22, PF-24
**Primary for:** PF-22
**Dependencies:** HFP-P25
**Estimate:** L (low): Retrieval quality must improve without weakening scope and privacy boundaries

**Acceptance**
- Given exact queries and conceptual benchmark cases, scope filters apply before ranking and results cite supporting document versions/pages.
- Given unauthorized wrong-year absent-answer or denied semantic-index cases, no private snippet leaks and unsupported answers abstain.

**Tasks**
- [ ] HFP-P26-T01: Implement exact field/text search through the authorized evidence adapter with pre-retrieval ACL tests.
- [ ] HFP-P26-T02: Compare an isolated local semantic candidate against the frozen exact-search benchmark without enabling it by default.
- [ ] HFP-P26-T03: Gate Qdrant activation on separate OPTIONAL-SEMANTIC approval and prove snippets bypass model context.

**Verification:** Held-out synthetic retrieval suite with exact-only baseline, wrong-year near matches and unauthorized documents.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P27: Reconcile lot basis and RSU/ESPP compensation events

<!-- spec-plan:hermes-financial-planning:HFP-P27 -->
**Outcome:** Broker basis payroll income and adjusted federal/state basis agree before realized-gain scenarios.
**Kind / parent / phase:** pbi / HFP-F12 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-11`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `TaxLot`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `R15`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-11
**Primary for:** PF-11
**Dependencies:** HFP-P22, HFP-P25
**Estimate:** L (low): Basis reconstruction and compensation timing require independent domain tests

**Acceptance**
- Given synthetic acquisitions disposals RSU vests and ESPP cases, wages and gain basis reconcile without double taxation.
- Given missing basis supplemental evidence or incompatible date/precision, the service retains unknowns instead of assuming zero basis.

**Tasks**
- [ ] HFP-P27-T01: Implement decimal investment-event and tax-lot records with federal/state basis and evidence separation.
- [ ] HFP-P27-T02: Qualify RSU/ESPP treatment and Form 8949 A-F categories using relevant payroll and plan evidence.
- [ ] HFP-P27-T03: Reject unjustified float conversion and unresolved basis while producing a deterministic reconciliation artifact.

**Verification:** Independent synthetic lot and compensation fixtures including partial disposals missing basis and state differences.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P28: Apply bounded household wash-sale and lot constraints

<!-- spec-plan:hermes-financial-planning:HFP-P28 -->
**Outcome:** Proposed disposals disclose qualified replacement-account timing constraints without a new proactive trading product.
**Kind / parent / phase:** pbi / HFP-F12 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W3`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.2`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `T01`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-07, PF-11
**Primary for:** -
**Dependencies:** HFP-P27
**Estimate:** L (low): Cross-account evidence and tax treatment require bounded explicit support

**Acceptance**
- Given supported synthetic household transactions, before/after window and relevant account cases produce independently expected lot findings.
- Given unknown related-account activity or substantially-identical treatment, the candidate is blocked/uncertain rather than declared safe.

**Tasks**
- [ ] HFP-P28-T01: Qualify supported wash-sale timing and replacement-account adjustments against official cases.
- [ ] HFP-P28-T02: Expose narrow lot-constraint findings for opaque candidate IDs without raw lot dumps.
- [ ] HFP-P28-T03: Test incomplete household/DRIP evidence and preserve explicit unsupported identity judgments.

**Verification:** Synthetic household timing and account-type boundary suite through the lot-constraint API.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P29: Compare tax-aware portfolio alternatives

<!-- spec-plan:hermes-financial-planning:HFP-P29 -->
**Outcome:** Owner sees do-nothing contribution-first and sale-funded candidates with tax cash and risk trade-offs.
**Kind / parent / phase:** pbi / HFP-F12 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W3`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `planning.compare_portfolio_candidates`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-07, PF-06
**Primary for:** PF-07
**Dependencies:** HFP-P12, HFP-P28
**Estimate:** L (low): Analytics and private tax services must share consistent scenario identity

**Acceptance**
- Given qualified policy and snapshots, candidate comparisons retain account feasibility federal/state deltas cash bridge and approved objectives.
- Given incomplete lots unsupported tax treatment or no approved trade-off objective, no fabricated optimal portfolio or live order is produced.

**Tasks**
- [ ] HFP-P29-T01: Join existing what-if candidate IDs to private lot/tax constraints without duplicating optimization engines.
- [ ] HFP-P29-T02: Calculate qualified incremental taxes fees and cash feasibility with a do-nothing comparator.
- [ ] HFP-P29-T03: Render non-dominated alternatives and limitations without leaking exact private results to models.

**Verification:** Independent synthetic contribution-only and sale-funded comparison cases in the authenticated UI.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P30: Qualify bounded retirement and conversion scenarios

<!-- spec-plan:hermes-financial-planning:HFP-P30 -->
**Outcome:** Retirement alternatives disclose assumptions units solver bounds and independently checked annual tax.
**Kind / parent / phase:** pbi / HFP-F13 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-12`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `RetirementScenario`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `S06`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-12
**Primary for:** PF-12
**Dependencies:** HFP-P22, HFP-P20
**Estimate:** L (low): Long-horizon simplifications and annual tax contracts need independent validation

**Acceptance**
- Given supported synthetic account buckets and income assumptions, the isolated Owl adapter returns reproducible bounded scenarios with annual-tax checks.
- Given unsupported IRA basis RMD/benefit cases arbitrary files or solver timeout, it blocks or returns partial evidence instead of inventing a plan.

**Tasks**
- [ ] HFP-P30-T01: Map accepted facts to a narrow isolated Owl adapter with explicit time units and overrides.
- [ ] HFP-P30-T02: Qualify withdrawals conversions and supported benefit/RMD cases against independent annual-tax references.
- [ ] HFP-P30-T03: Enforce solver resource limits and safe artifact projection without exposing native file/admin operations.

**Verification:** Synthetic retirement scenarios with known annual reconciliations infeasible inputs and solver interruption.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P31: Compare household reserve debt and goal scenarios

<!-- spec-plan:hermes-financial-planning:HFP-P31 -->
**Outcome:** Owner evaluates liquidity debt education purchases and charitable goals under declared constraints.
**Kind / parent / phase:** pbi / HFP-F13 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W9`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-13`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `R15`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-13
**Primary for:** PF-13
**Dependencies:** HFP-P20, HFP-P22
**Estimate:** M (low): Reuses existing utility arithmetic with explicit goal and qualification bounds

**Acceptance**
- Given supported synthetic goals and cash flows, emergency reserves debt amortization and bounded goal alternatives reconcile to accepted inputs.
- Given specialist property charitable or education tax questions outside coverage, the service refers/blocks rather than extrapolating generic formulas.

**Tasks**
- [ ] HFP-P31-T01: Reuse and qualify mortgage/debt arithmetic with extra-principal and unit/rounding cases.
- [ ] HFP-P31-T02: Implement constrained reserve and goal comparisons using accepted household cash flows.
- [ ] HFP-P31-T03: Attach applicable tax coverage limits and side-by-side evidence without treating optional budget apps as required.

**Verification:** Independent amortization/reserve cases and missing-fact/specialist-case UI outcomes.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P32: Schedule bounded briefings and deadline reminders

<!-- spec-plan:hermes-financial-planning:HFP-P32 -->
**Outcome:** Owner receives useful evidence-ready notifications under shared timezone privacy and provider policy.
**Kind / parent / phase:** pbi / HFP-F14 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `W1`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-14`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `9`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-14, PF-20
**Primary for:** PF-14
**Dependencies:** HFP-P10, HFP-P22, HFP-P04
**Estimate:** M (low): Reuses established orchestration but adds schedule-specific evidence policy

**Acceptance**
- Given approved schedules, reminders use the Pacific gateway correct source dates and local counts-only delivery.
- Given quiet hours stale inputs disallowed TradingView automation or repeated unchanged failures, notifications defer/block/deduplicate without creating another scheduler.

**Tasks**
- [ ] HFP-P32-T01: Define approved briefing/deadline manifests with time-zone conversion and policy checks.
- [ ] HFP-P32-T02: Implement changed-state/materiality notification routing using run artifacts and separate delivery receipts.
- [ ] HFP-P32-T03: Prove restart quiet-hour and stale-evidence behavior without enabling external messaging connectors.

**Verification:** Synthetic scheduled briefing/deadline replay through the one gateway across DST and repeated-failure cases.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P33: Export an authorized private decision and CPA package

<!-- spec-plan:hermes-financial-planning:HFP-P33 -->
**Outcome:** Owner can review deterministic calculations sources unresolved questions and exclusions in a bounded local export.
**Kind / parent / phase:** pbi / HFP-F14 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-19`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `planning.prepare_review_package`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-19, PF-18
**Primary for:** PF-19
**Dependencies:** HFP-P22, HFP-P25, HFP-P06
**Estimate:** M (low): Existing artifact mechanisms need private export policy and reconciliation

**Acceptance**
- Given authorized run and evidence IDs, the export contains consistent calculation tables citations versions and unresolved questions.
- Given unauthorized destinations revoked evidence formula injection or changed approval arguments, export is rejected without copying private data elsewhere.

**Tasks**
- [ ] HFP-P33-T01: Compose qualified calculation/evidence views through existing artifact writers.
- [ ] HFP-P33-T02: Bind export destination scope retention and one-use approval with traversal and formula-injection rejection.
- [ ] HFP-P33-T03: Reconcile exported totals and citations to accepted inputs and enforce revocation behavior.

**Verification:** Synthetic CPA package generation and local opening with exact expected contents and denied export cases.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P34: Qualify resource admission backup and failure recovery

<!-- spec-plan:hermes-financial-planning:HFP-P34 -->
**Outcome:** Native services and on-demand workers recover within explicit limits without hosted fallbacks or data loss.
**Kind / parent / phase:** pbi / HFP-F15 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `13`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `12`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `prompts\out\fmp-cache-hermes-sync-design.md` section `11`; SHA256 `9441326a80560a2a58eae6bd9aeb1b4d0684448f90858262e76d62f6e1dcfbbd`
**Requirements:** PF-17, PF-18, PF-26
**Primary for:** -
**Dependencies:** HFP-P06, HFP-P08, HFP-P15, HFP-P24, HFP-P30
**Estimate:** L (low): Whole-machine resource and recovery interactions require real deployed seams

**Acceptance**
- Given representative synthetic concurrent workloads, RAM/VRAM admission on-demand unloading and recovery stay within measured budgets.
- Given worker death disk pressure key revocation or restore, stale/partial states remain explicit and private routes never fall back to hosted services.

**Tasks**
- [ ] HFP-P34-T01: Measure and enforce resident/on-demand resource admission without assuming all models fit concurrently.
- [ ] HFP-P34-T02: Prove scoped cancellation worker death and browser/gateway restart recovery under synthetic load.
- [ ] HFP-P34-T03: Demonstrate encrypted restore/key separation and retained independent backup ownership without stopping production services.

**Verification:** Approved test-only fault matrix and measured resource evidence on the selected local deployment.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P35: Certify the selected capability and privacy release matrix

<!-- spec-plan:hermes-financial-planning:HFP-P35 -->
**Outcome:** Product claims reflect independent acceptance across all selected workflows rather than documentation counts.
**Kind / parent / phase:** pbi / HFP-F15 / 5
**Program / area / priority:** program:hermes-financial-planning / area:validation / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `13`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `3`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `5`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-03, PF-04, PF-18, PF-20, PF-27
**Primary for:** PF-03
**Dependencies:** HFP-P09, HFP-P13, HFP-P14, HFP-P23, HFP-P29, HFP-P31, HFP-P32, HFP-P33, HFP-P34, HFP-P36, HFP-P37, HFP-P38
**Estimate:** L (low): End-to-end qualification aggregates many independently delivered capabilities

**Acceptance**
- Given the selected scope, all 36 notebook files have dispositions and all 25 main capabilities pass independent service acceptance; controlled Hermes repeats report all failures.
- Given uncovered docs unsupported jurisdictions privacy leaks or failed showcase journeys, the release matrix blocks the corresponding claim rather than marking the whole product ready.

**Tasks**
- [ ] HFP-P35-T01: Join requirement source capability tool policy UX and independent-test evidence into one qualification register.
- [ ] HFP-P35-T02: Run the proposed 25-case/two-repeat Hermes suite with explicit reliability targets and notebook-free acceptance.
- [ ] HFP-P35-T03: Publish limitations and unresolved gates through existing CI/reporting without introducing a second test framework.

**Verification:** Source-to-capability matrix plus independent deterministic oracles, controlled 50-run reliability results and 100 percent showcase evidence.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P36: Qualify ISO AMT and compensation sourcing extensions

<!-- spec-plan:hermes-financial-planning:HFP-P36 -->
**Outcome:** Supported exercise/disposition scenarios preserve ordinary income AMT credit and state sourcing evidence.
**Kind / parent / phase:** pbi / HFP-F12 / 4
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.2`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `8.3`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `T09`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-11, PF-09
**Primary for:** -
**Dependencies:** HFP-P27, TAX-YEAR
**Estimate:** L (low): Multi-year credit and sourcing correctness cannot be inferred from basic lot arithmetic

**Acceptance**
- Given qualified synthetic ISO cases and workday/residency evidence, bargain-element timing credit carryforward and state differences reconcile.
- Given unsupported AMT recovery or missing sourcing facts, the scenario blocks rather than promising an optimal AMT-free exercise amount.

**Tasks**
- [ ] HFP-P36-T01: Qualify supported ISO exercise/disposition timing and separate ordinary/capital/AMT facts.
- [ ] HFP-P36-T02: Implement bounded Form 8801 carryforward reconciliation using qualified annual engines and independent cases.
- [ ] HFP-P36-T03: Add compensation sourcing evidence and missing-workday/residency rejection without adopting unselected PF-30 product scope.

**Verification:** Officially grounded synthetic ISO/AMT and sourcing boundary suite for the selected year.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P37: Enforce private document revocation deletion and restore

<!-- spec-plan:hermes-financial-planning:HFP-P37 -->
**Outcome:** Revoked document evidence becomes inaccessible across originals indexes caches and dependent exports.
**Kind / parent / phase:** pbi / HFP-F11 / 3a
**Program / area / priority:** program:hermes-financial-planning / area:portfolio-intel / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-24`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.4`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`
**Requirements:** PF-24, PF-21, PF-22
**Primary for:** PF-24
**Dependencies:** HFP-P26
**Estimate:** L (low): Multiple derived stores and backups must share lifecycle semantics

**Acceptance**
- Given authorized revocation/deletion, all derived evidence and artifacts honor the same tombstone and permission state.
- Given backup restore or a stale semantic cache, private material is not served before tombstones and ACLs are reconciled.

**Tasks**
- [ ] HFP-P37-T01: Propagate revocation across extraction accepted facts retrieval and artifact references with denial tests.
- [ ] HFP-P37-T02: Apply explicit retention/hold and backup tombstone semantics without deleting market history.
- [ ] HFP-P37-T03: Prove restore and stale-index behavior with synthetic documents and local-only model/embedding boundaries.

**Verification:** Synthetic end-to-end revoke/delete/restore including dependent artifacts and an optional-index test double.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.

### HFP-P38: Build scoped public knowledge and source-grounded Q&A

<!-- spec-plan:hermes-financial-planning:HFP-P38 -->
**Outcome:** Hermes can explain approved documentation and official references with authority revision and supersession visible.
**Kind / parent / phase:** pbi / HFP-F06 / 2B
**Program / area / priority:** program:hermes-financial-planning / area:analysis / P1
**Sources (local planning references, not published permalinks):** `docs\Specs\gh-1312-hermes-financial-planning\spec.md` section `PF-15`; SHA256 `82755ead712e67415492e9b8ceab134aad0f0fb6ed78e2a99ed9a7cf6a984ff2`; `docs\Specs\gh-1312-hermes-financial-planning\plan.md` section `11.1`; SHA256 `262321857620e2d0b99a945c489216fb5a2edf0770863130410657a457456d07`; `docs\Specs\gh-1312-hermes-financial-planning\research.md` section `5`; SHA256 `ec6de6673ef56268721003a942f3825e63152ad9752e11dee28ac8c7b52fe4d9`
**Requirements:** PF-15, PF-04
**Primary for:** PF-15
**Dependencies:** HFP-P03, HFP-P02
**Estimate:** M (low): Scoped retrieval reuses policy and evidence contracts without requiring another application

**Acceptance**
- Given approved public reference material, answers cite the correct source section revision and authority and distinguish proposed from implemented content.
- Given private files notebook outputs injected instructions or absent evidence, ingestion excludes them and answers abstain without overriding tool policy.

**Tasks**
- [ ] HFP-P38-T01: Implement an allowlisted public-source register and explicit document status/supersession metadata.
- [ ] HFP-P38-T02: Provide bounded exact retrieval and source-grounded synthesis through the same Hermes coordinator.
- [ ] HFP-P38-T03: Test prompt-injection ignored instructions private-path exclusion and unavailable-evidence abstention.

**Verification:** Frozen public/synthetic document corpus with wrong-revision near matches injection fixtures and missing answers.
**Command:** Not yet qualified; bind the exact existing test/real-path command before execution.
**Gate:** Planning publication does not authorize implementation, deployment or private-data access.
