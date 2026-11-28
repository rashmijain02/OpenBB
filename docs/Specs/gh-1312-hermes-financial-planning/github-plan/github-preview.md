# GitHub preview: hermes-financial-planning

Reviewed-plan digest: `51090ba02c432a36d557abf2060f9aec025516353d560e9c1b98342e598e1cbb`.
Target: `rashmijain02/OpenBB`, Project 1 / `rashmijain02`.

Hierarchy: 7 Epics, 15 Features, 38 PBIs; 114 checklist Tasks.

## Proposed schema and labels

- Existing Type field: preserve Epic, Feature, Task and Bug option IDs; add only PBI.
- Create Roadmap phase single-select field with exactly the phase_mapping values, only if no equivalent existing field is discovered.
- Leave existing Phase, Lane, Start, End and existing item values unchanged.
- New label: `program:hermes-financial-planning`

Preserve all existing field options/IDs, Phase values and unrelated items.

## Exact planned item set

| Stable ID | Action | Issue title | Parent | Labels | Type | Roadmap phase | Status |
|---|---|---|---|---|---|---|---|
| HFP-E01 | create | [HFP-E01] Safe native Hermes financial workspace | - | program:hermes-financial-planning, area:core, priority:P0, type:epic, tracking:container | Epic | Cross-phase | Todo |
| HFP-E02 | create | [HFP-E02] Deterministic FMP cache operations | - | program:openbb-jobs, area:jobs, priority:P1, type:epic, tracking:container | Epic | Cross-phase | Todo |
| HFP-E03 | create | [HFP-E03] OpenBB analytical capability parity | - | program:hermes-financial-planning, area:analysis, priority:P1, type:epic, tracking:container | Epic | Cross-phase | Todo |
| HFP-E04 | create | [HFP-E04] Nautilus strategy and simulation migration | - | program:hermes-financial-planning, area:backtest, priority:P1, type:epic, tracking:container | Epic | 1b - Nautilus | Todo |
| HFP-E05 | create | [HFP-E05] Private household tax and document foundation | - | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:epic, tracking:container | Epic | Cross-phase | Todo |
| HFP-E06 | create | [HFP-E06] Tax-aware wealth and retirement planning | - | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:epic, tracking:container | Epic | 4 - Compensation and retirement | Todo |
| HFP-E07 | create | [HFP-E07] Evidence delivery and operational qualification | - | program:hermes-financial-planning, area:validation, priority:P1, type:epic, tracking:container | Epic | 5 - Expansion and operations | Todo |
| HFP-F01 | create | [HFP-F01] Runtime and privacy admission | HFP-E01 | program:hermes-financial-planning, area:core, priority:P0, type:feature, tracking:container | Feature | 0 - Foundation | Todo |
| HFP-F02 | create | [HFP-F02] Notebook-free workflow and run contracts | HFP-E01 | program:hermes-financial-planning, area:agents, priority:P0, type:feature, tracking:container | Feature | 1 - Core Hermes | Todo |
| HFP-F03 | create | [HFP-F03] Unified web and Workspace experience | HFP-E01 | program:hermes-financial-planning, area:workspace, priority:P0, type:feature, tracking:container | Feature | 1 - Core Hermes | Todo |
| HFP-F04 | create | [HFP-F04] FMP warming validation and gated expansion | HFP-E02 | program:openbb-jobs, area:jobs, priority:P1, type:feature, tracking:container | Feature | Cross-phase | Todo |
| HFP-F05 | create | [HFP-F05] Core portfolio and single-name research | HFP-E03 | program:hermes-financial-planning, area:analysis, priority:P1, type:feature, tracking:container | Feature | 2A - Core analytics | Todo |
| HFP-F06 | create | [HFP-F06] Remaining capability and knowledge qualification | HFP-E03 | program:hermes-financial-planning, area:analysis, priority:P1, type:feature, tracking:container | Feature | 2B - Remaining capabilities | Todo |
| HFP-F07 | create | [HFP-F07] Isolated Nautilus runtime and adapters | HFP-E04 | program:hermes-financial-planning, area:backtest, priority:P1, type:feature, tracking:container | Feature | 1b - Nautilus | Todo |
| HFP-F08 | create | [HFP-F08] Independent statistical qualification and cutover | HFP-E04 | program:hermes-financial-planning, area:backtest, priority:P1, type:feature, tracking:container | Feature | 1b - Nautilus | Todo |
| HFP-F09 | create | [HFP-F09] Household facts and cash reconciliation | HFP-E05 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:feature, tracking:container | Feature | 3 - Household and tax | Todo |
| HFP-F10 | create | [HFP-F10] Qualified tax engines and jurisdiction coverage | HFP-E05 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:feature, tracking:container | Feature | Cross-phase | Todo |
| HFP-F11 | create | [HFP-F11] Private document evidence pipeline | HFP-E05 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:feature, tracking:container | Feature | 3a - Document evidence | Todo |
| HFP-F12 | create | [HFP-F12] Lots compensation and tax-aware alternatives | HFP-E06 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:feature, tracking:container | Feature | 4 - Compensation and retirement | Todo |
| HFP-F13 | create | [HFP-F13] Retirement and household goals | HFP-E06 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:feature, tracking:container | Feature | 4 - Compensation and retirement | Todo |
| HFP-F14 | create | [HFP-F14] Monitoring and private review packages | HFP-E07 | program:hermes-financial-planning, area:validation, priority:P1, type:feature, tracking:container | Feature | 5 - Expansion and operations | Todo |
| HFP-F15 | create | [HFP-F15] Product resilience and release qualification | HFP-E07 | program:hermes-financial-planning, area:validation, priority:P1, type:feature, tracking:container | Feature | 5 - Expansion and operations | Todo |
| HFP-P01 | create | [HFP-P01] Qualify native runtime provenance and connection health | HFP-F01 | program:hermes-financial-planning, area:core, priority:P0, type:task | PBI | 0 - Foundation | Todo |
| HFP-P02 | create | [HFP-P02] Enforce private data and immutable skill boundaries | HFP-F01 | program:hermes-financial-planning, area:core, priority:P0, type:task | PBI | 0 - Foundation | Todo |
| HFP-P03 | create | [HFP-P03] Extract notebook-independent workflow manifests | HFP-F02 | program:hermes-financial-planning, area:agents, priority:P0, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P04 | create | [HFP-P04] Bind Hermes runs to resumable jobs and approvals | HFP-F02 | program:hermes-financial-planning, area:agents, priority:P0, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P05 | create | [HFP-P05] Deliver the native Hermes web vertical slice | HFP-F03 | program:hermes-financial-planning, area:workspace, priority:P0, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P06 | create | [HFP-P06] Unify Workspace conversation and private metric display | HFP-F03 | program:hermes-financial-planning, area:workspace, priority:P0, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P07 | create | [HFP-P07] Run guarded price warming through Hermes no-agent cron | HFP-F04 | program:openbb-jobs, area:jobs, priority:P0, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P08 | create | [HFP-P08] Extend market readiness and independent operational audits | HFP-F04 | program:openbb-jobs, area:jobs, priority:P1, type:task | PBI | 1 - Core Hermes | Todo |
| HFP-P09 | create | [HFP-P09] Admit retention-safe ETF and reference schedules | HFP-F04 | program:openbb-jobs, area:jobs, priority:P1, type:task | PBI | 2B - Remaining capabilities | Todo |
| HFP-P10 | create | [HFP-P10] Expose core look-through risk attribution and catalysts | HFP-F05 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2A - Core analytics | Todo |
| HFP-P11 | create | [HFP-P11] Reconcile seven-phase analysis with independent filings | HFP-F05 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2A - Core analytics | Todo |
| HFP-P12 | create | [HFP-P12] Qualify core portfolio scenario and analyst-basket workflows | HFP-F06 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2A - Core analytics | Todo |
| HFP-P13 | create | [HFP-P13] Qualify TechTrade workflows against the selected backend | HFP-F06 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2B - Remaining capabilities | Todo |
| HFP-P14 | create | [HFP-P14] Disposition documentation examples and provider variants | HFP-F06 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2B - Remaining capabilities | Todo |
| HFP-P15 | create | [HFP-P15] Qualify the isolated Nautilus runtime and data catalog | HFP-F07 | program:hermes-financial-planning, area:backtest, priority:P1, type:task | PBI | 1b - Nautilus | Todo |
| HFP-P16 | create | [HFP-P16] Standardize reviewed strategies and preserve OpenBB callers | HFP-F07 | program:hermes-financial-planning, area:backtest, priority:P1, type:task | PBI | 1b - Nautilus | Todo |
| HFP-P17 | create | [HFP-P17] Preserve independent validation and complete trial accounting | HFP-F08 | program:hermes-financial-planning, area:backtest, priority:P1, type:task | PBI | 1b - Nautilus | Todo |
| HFP-P18 | create | [HFP-P18] Cut over qualified simulation and paper consumers | HFP-F08 | program:hermes-financial-planning, area:backtest, priority:P1, type:task | PBI | 1b - Nautilus | Todo |
| HFP-P19 | create | [HFP-P19] Accept versioned household inputs in an isolated private store | HFP-F09 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3 - Household and tax | Todo |
| HFP-P20 | create | [HFP-P20] Reconcile household balance sheet and cash flow | HFP-F09 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3 - Household and tax | Todo |
| HFP-P21 | create | [HFP-P21] Qualify the initial federal annual-tax subset | HFP-F10 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3 - Household and tax | Todo |
| HFP-P22 | create | [HFP-P22] Qualify federal-to-California tax comparisons | HFP-F10 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3 - Household and tax | Todo |
| HFP-P23 | create | [HFP-P23] Expose jurisdiction coverage and one selected residency pilot | HFP-F10 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 5 - Expansion and operations | Todo |
| HFP-P24 | create | [HFP-P24] Integrate the private Paperless document vault | HFP-F11 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3a - Document evidence | Todo |
| HFP-P25 | create | [HFP-P25] Review extracted fields before accepting financial facts | HFP-F11 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3a - Document evidence | Todo |
| HFP-P26 | create | [HFP-P26] Deliver authorized exact search and qualify optional semantics | HFP-F11 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3a - Document evidence | Todo |
| HFP-P27 | create | [HFP-P27] Reconcile lot basis and RSU/ESPP compensation events | HFP-F12 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P28 | create | [HFP-P28] Apply bounded household wash-sale and lot constraints | HFP-F12 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P29 | create | [HFP-P29] Compare tax-aware portfolio alternatives | HFP-F12 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P30 | create | [HFP-P30] Qualify bounded retirement and conversion scenarios | HFP-F13 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P31 | create | [HFP-P31] Compare household reserve debt and goal scenarios | HFP-F13 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P32 | create | [HFP-P32] Schedule bounded briefings and deadline reminders | HFP-F14 | program:hermes-financial-planning, area:validation, priority:P1, type:task | PBI | 5 - Expansion and operations | Todo |
| HFP-P33 | create | [HFP-P33] Export an authorized private decision and CPA package | HFP-F14 | program:hermes-financial-planning, area:validation, priority:P1, type:task | PBI | 5 - Expansion and operations | Todo |
| HFP-P34 | create | [HFP-P34] Qualify resource admission backup and failure recovery | HFP-F15 | program:hermes-financial-planning, area:validation, priority:P1, type:task | PBI | 5 - Expansion and operations | Todo |
| HFP-P35 | create | [HFP-P35] Certify the selected capability and privacy release matrix | HFP-F15 | program:hermes-financial-planning, area:validation, priority:P1, type:task | PBI | 5 - Expansion and operations | Todo |
| HFP-P36 | create | [HFP-P36] Qualify ISO AMT and compensation sourcing extensions | HFP-F12 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 4 - Compensation and retirement | Todo |
| HFP-P37 | create | [HFP-P37] Enforce private document revocation deletion and restore | HFP-F11 | program:hermes-financial-planning, area:portfolio-intel, priority:P1, type:task | PBI | 3a - Document evidence | Todo |
| HFP-P38 | create | [HFP-P38] Build scoped public knowledge and source-grounded Q&A | HFP-F06 | program:hermes-financial-planning, area:analysis, priority:P1, type:task | PBI | 2B - Remaining capabilities | Todo |

Proposed new issues: **60**. Each new issue also needs project membership, Type, Roadmap phase and Status.
Proposed parent links: **53**. Checklist Tasks create no separate issues.
These are logical operations, not a guarantee of API request counts.

## Existing-work dispositions

- #1312 (financial-planning proposal): reference only; no title/body/label/status changes.
- #1298-#1301 (FMP cached MCP/storage program): external capability dependencies; no new storage implementation issues or reparenting.
- #4 (optional non-vendored engine adapters): legacy generic adapter scope; HFP-P15/P16 cover selected Nautilus qualification/integration only, not a competing generic framework.
- #5 (test harness, CI and NFR benchmarks): reuse existing test infrastructure; HFP-P17/P35 add product-specific acceptance, not another general harness.
- #151 (backtest bridge for historical intraday): existing fmp_trading bridge remains owned there; HFP-P13/P18 adapt approved callers and do not recreate that route.
- #215 (artifacts, jobs, paper gates and provider modes): reuse existing adapters; HFP-P04/P06/P18 only bind Hermes/Nautilus-specific contracts. Existing children and migration references stay unchanged.
- #1311 (Windows service installation): explicitly excluded; do not revive its service-host scope.
- Searches included targeted open-work results and existing container issues; refresh overlaps before apply, and stop rather than duplicate newly discovered work.

## Publication blockers

- Owner must review YAML/Markdown and explicitly approve the final issue count, schema changes and exact mutation set.
- Refresh project fields/labels and stable-marker searches immediately before approval/apply; any drift requires a new preview.
- Verify the four source hashes and baseline provenance; the source documents remain local and unpushed.
- Obtain any remaining cross-repository ownership decisions before implementation; this preview targets only rashmijain02/OpenBB.
- Real-path commands and package pins are qualification tasks, not claims of execution readiness.

No GitHub writes approved. Refresh remote state and source hashes, resolve overlaps, and obtain explicit approval of the final mutation set.
No commits, pushes, PRs, issue closure/deletion, implementation or runtime changes are included.
