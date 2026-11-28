# Existing coverage and open-source research

**Research date:** November 26, 2026, Pacific time.
**Proposal:** [Personal Financial Intelligence](spec.md).
**Design:** [Architecture](plan.md).
**Tracking:** [#1312 (Hermes integration and unified financial-planning proposal)](https://github.com/rashmijain02/OpenBB/issues/1312).
**Baseline:** `origin/portfolio` at `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7`.

This is a source/documentation research assessment, not a deployment,
benchmark, security audit or tax certification. No personal financial datasets
or notebook saved outputs were used. External products were not installed.

## 1. Evidence strength

| Label | Meaning |
|---|---|
| Source inspected | Relevant local source, manifest or metadata was inspected. |
| Repository-documented | A current local report states the capability; not re-run live here. |
| Upstream-documented | Official upstream documentation/README describes it; not qualified locally. |
| Proposed | New behavior needed for this product. |
| Unverified | Evidence insufficient to establish readiness or suitability. |

Search-result snippets are not equivalent to a successful full-page fetch.
For FMP's MCP documentation, indexed official-page content was available, but a
direct page fetch returned HTTP 403. Reconfirm its complete current terms and
authentication contract during integration.

## 2. Existing product foundation

**Review reconciliation (November 27, 2026):** source checks below refine the
reviewer's observations; original comments remain preserved. No source/runtime
qualification here constitutes G1 approval or permission to deploy.

All local paths below are relative to the OpenBB repository root.

| ID | Source | Important finding |
|---|---|---|
| R01 | `docs\Specs\notebook-mcp-agent\requirements.md` | 25 source stories, MCP-only financial execution, artifacts, local model, explicit paper approvals, readiness and replay requirements. |
| R02 | `docs\designs\notebook-mcp-agent-design.md` | Contracts and component boundaries; actual Analysis pipeline must be bridged rather than replaced with a similarly named implementation. |
| R03 | `docs\cross_repo_workflow\notebook-mcp-story-coverage.md` | Story mapping and evolving bridge status; historical stage-readiness numbers are not live acceptance. |
| R04 | `docs\cross_repo_workflow\mcp-coverage-report.md` | Current reviewed surfaces and denominators, including 181 routed FMP Cached registrations and separately verified specialist servers. |
| R05 | `docs\Specs\mcp-capability-parity\inventory.md` | Metadata-only capability inventory; no provider/credential reads; registrations do not equal runtime readiness. |
| R06 | `docs\Specs\mcp-capability-parity\runtime-profiles.md` | Platform and Portfolio runtime isolation, source-origin verification and optional dependency handling. |
| R07 | `docs\Specs\mcp-capability-parity\exposure-policy.md` | Fail-closed access classification; later paper adapters supply explicit gates rather than general mutation authority. |
| R08 | `docs\planning\portfolio-intelligence-workspace-native-terminal-plan.md` | Preserve native Workspace widgets/apps and supported agent integration; standalone viewer is reference only. |
| R09 | `docs\Specs\Portfolio-Intelligence-Engine-PRD.md` | Portfolio intelligence scope, provider/cache reuse and original tax-engine non-goal. |
| R10 | `openbb_platform\extensions\agents\README.md` | One current Q&A agent and two MCP tools, not all five agents described in the earlier ADK design. |
| R11 | `docs\OpenBB Agent\DESIGN.md`; `google_adk_openbb_proposal.md` | Earlier five-agent and ESPP planning concepts; not implementation evidence. |
| R12 | `openbb_platform\extensions\mcp_server\openbb_mcp_server\story_adapters\` | Analytics, single-name, attribution, registry, artifacts, jobs and paper modules present. |
| R13 | `openbb_platform\extensions\agents\openbb_agents\notebook_guide\` | Contracts/readiness and source story manifests present; no completed Hermes loop established. |
| R14 | `scripts\notebook_story_inventory.py` | Source-only check on `portfolio` finds 25 stories and 21 hash mismatches; known TechTrade narrative-in-code diagnostic retained. |
| R15 | `openbb_platform\tools\portfolio_utils\portfolio_utils\{load_espp_plan,share_cost_basis,mortgage_amortization,enrich_cusip_figi,populate_cusip_map,populate_market_holidays}.py`; sibling `portfolio_snapshot_importer` and `portfolio_export` | Reusable input/identity/mortgage utilities, not a complete tax engine. ESPP/basis helpers use floats; ESPP loader writes MySQL. Importer has MySQL and SQLite backends, defaults to MySQL with SQLite fallback; actual active backend is unverified. Export config guards paths outside the repo. |
| R16 | `docs\Specs\Backtesting-Engine-PRD.md`; `TechnicalTrading-Engine-PRD.md`; `Quant-Analysis-Module-Proposal.md` | Preserve existing analysis/simulation domains rather than introduce a second trading platform. |
| R17 | Supplemental original-checkout `docs\planning\kite-cached-indian-markets-project-plan.md`; `docs\Specs\Kite-Cached-Indian-Markets-PRD.md` | These untracked documents are not on the selected baseline. Preserve that separate work; it is not a US tax-planning dependency. |
| R18 | Supplemental original-checkout `docs\prompts\principal-analyst-deep-dive-TEMPLATE.md` v2.3 and `docs\research\` | Not baseline functionality. Template lists eight vendor/filing reconciliation traps, independent audit ordering and a 12-check scorecard. Reuse checks after qualification, not its standalone ban on OpenBB, automatic heuristics or illustrative options tickets. Its roughly 49 KB truncation observation is specific to a reported tool/environment, not a universal fetch limit. |
| R19 | `specs\gh-1272-agent-capabilities\handoff.md`; widget backend `README.md` | Current native selected-widget agent context, origin checks, bounded/redacted payloads and external-provider disclosure. |
| R20 | `specs\gh-1271-techtrade-native\handoff.md` | Current native TechTrade charts/tables and reported zero strict manifest debt; browser qualification remains distinct. |
| R21 | `docs\dev-strategy.md`; `.specify\memory\constitution.md` | Current specification location, workflow and privacy/provider principles; old documentation-organization rules are archived. |
| R22 | `openbb_platform\extensions\backtest\openbb_backtest\engine\{vectorized,event_driven,execution,reconcile}.py`; `data\bundle.py`; `routers\run_router.py`; extension `pyproject.toml` | Current custom NumPy/Pandas/optional Numba and Python event engines, Parquet bundle ingestion, API routing and simplified execution assumptions. Not a Nautilus wrapper. |
| R23 | `openbb_platform\extensions\techtrade\openbb_techtrade\validation\backtest_bridge.py`; `execution\{broker,order_sink}.py` | TechTrade validation delegates to OpenBB backtest; local paper simulation and CSV/XLSX handoff exist. Broker interface comments are not implemented IBKR connectivity. |

> **[Reviewer Feedback — 2026-11-27]:**
> - **Expand `R15` to cover sibling baseline tools & record precision debt:** `openbb_platform\tools\` also contains `portfolio_snapshot_importer` (append-only, SHA256-idempotent `~/.portfolio_importer/positions.db` store with extensible `LOADERS`), `portfolio_export` (Playwright manual-login export with `Config._validate_outside_repo()`), `mortgage_amortization.py` (fixed-rate + extra-principal schedule reusable for W9), and CUSIP/FIGI/holiday utilities (`enrich_cusip_figi.py`, `populate_cusip_map.py`, `populate_market_holidays.py`). Also note that `load_espp_plan.py` and `share_cost_basis.py` currently use Python `float` rather than `Decimal`, and `load_espp_plan.py` writes directly to MySQL (`ESPP_Plan`).
> - **Upgrade `R18` with inspected `docs\prompts\principal-analyst-deep-dive-TEMPLATE.md` (v2.3) findings:** Beyond report formatting, v2.3 documents **8 empirically observed FMP vendor traps** (share-count lag up to `-65%` / `2.8x` market-cap error; `float > shares_outstanding`; redeemable preferred mis-mapped into common equity; COGS D&A basis switches; mis-parsed cash quarters; warrant fair-value gains labeled as marketable securities; stale repeated diluted share counts; and `financial-estimates` small `limit` dropping the current FY due to newest-first sorting) plus the **~49 KB web-fetch truncation limit** that cuts off 10-Q MD&A—directly proving the need for local `edgartools` and full XBRL (`financial-reports-form-10-k-json`) ingestion in `W2` and vendor-integrity checks in `fmp-cache-hermes-sync-design.md`.

Some foundational docs contain old branches, paths, project numbers or designs
that later work superseded. The proposal prioritizes current source and the
reviewed coverage report over older headline counts.

### What exists versus what needs adding

| Domain | Current evidence | Product delta |
|---|---|---|
| Market/provider integration | Existing OpenBB and FMP Cached infrastructure. | Purpose/entitlement-aware workflow admission and clear health. |
| Portfolio/TechTrade/backtest analytics | Custom engines and many story adapters present. | Adopt qualified Nautilus execution behind existing APIs; preserve domain logic, Hermes-only orchestration and notebook-independent acceptance. |
| Run state, artifacts and jobs | Reviewed adapters documented and source files present. | Unified user journey, policy integration and failure/resume acceptance. |
| Native Workspace | Contracts, provenance, groups, TechTrade rendering and bounded selected-widget agent context now implemented on baseline. | Extend existing UX; separate private-tax data flow from existing external-model context. |
| Paper approval | Existing server-side person-granted gate and separate paper engines. | Preserve it; do not let Hermes approve itself. |
| Household intake and budget | Not established by inspected core portfolio workflows. | New accepted facts, cash-flow and goal contracts. |
| Annual federal/CA tax | Not established. | Qualified tax-engine adapter and jurisdiction matrix. |
| Tax-lot/compensation planning | Some input utilities and older concepts. | Correctness-tested event/basis/compensation layer and safe private channel. |
| Retirement optimization | Not established. | Bounded Owl integration plus validation and limitation handling. |
| Hermes integration | Prior work in another repo, not unified here. | Narrow finance profile/adapter, no runtime or frontend replacement. |

## 3. All 25 primary notebook cases

These notebooks are retained for learning, tutorials and human-run verification.
Their source inventory maps reference capabilities, not production executables.
Hermes is the only production harness; independent service-level cases qualify
equivalent financial outcomes without notebook kernels, saved outputs or chapter
state. Earlier Notebook Companion proposals are reusable design history, not a
requirement to implement another agent loop.

The root is `notebooks\`. The source-only manifest check on the selected
`portfolio` baseline reported 25 stories, 17 families and 21 source-hash
mismatches. Existing documentation reports only partial story readiness;
no end-to-end notebook runs were performed for this proposal.

Each paired provider variant remains its own acceptance case.

| # | Exact path below `notebooks` | Required product outcome |
|---|---|---|
| 1 | `portfolio\01-getting-started-and-providers.ipynb` | Provider/capability orientation, quotes/fundamentals, cache/freshness and prerequisite evidence. |
| 2 | `portfolio\02-single-name-deep-dive.ipynb` | Actual seven-phase Analysis pipeline, feature/regime variants, evidence and diagnostic cases. |
| 3 | `portfolio\03-basket-xray-and-risk.ipynb` | Fund look-through, sector/concentration/risk analysis and charts. |
| 4 | `portfolio\04-events-and-smart-money.ipynb` | Joined events, news, insider/institutional evidence and publication lags. |
| 5 | `portfolio\05-whatif-attribution-and-paper.ipynb` | What-if changes, Brinson attribution, candidate trades and Portfolio paper outcomes. |
| 6 | `portfolio\06-backtest-and-validation.ipynb` | Bundles, backtests, sweeps, factor evaluation, validation and tearsheet artifacts. |
| 7 | `portfolio\07-offline-recording-and-end-to-end.ipynb` | Typed recording/replay, source lineage, prior artifacts and complete story reconstruction. |
| 8 | `portfolio\08-analyst-recommendations-basket.ipynb` | Analyst-basket construction, coverage, concentration and validation; not excluded as optional. |
| 9 | `portfolio_yfinance\01-getting-started-and-providers.ipynb` | Explicit free-provider/recorded-data orientation with unavailable fields visible. |
| 10 | `portfolio_yfinance\02-single-name-deep-dive.ipynb` | Distinct free-data research path; not represented as the paid Analysis pipeline. |
| 11 | `portfolio_yfinance\03-basket-xray-and-risk.ipynb` | Free-provider basket look-through/risk with its own inputs and limitations. |
| 12 | `portfolio_yfinance\04-events-and-smart-money.ipynb` | Free-source dividends, filings and ownership composition without fabricated paid coverage. |
| 13 | `portfolio_yfinance\05-whatif-attribution-and-paper.ipynb` | Provider-specific state, attribution and approved Portfolio paper flow. |
| 14 | `portfolio_yfinance\06-backtest-and-validation.ipynb` | Same classes of validation artifacts over different qualified inputs. |
| 15 | `portfolio_yfinance\07-offline-recording-and-end-to-end.ipynb` | Safe free-track recorded data, resumable runs and replay. |
| 16 | `portfolio_yfinance\08-analyst-recommendations-basket.ipynb` | Free-track recommendation availability, basket rationale and outputs. |
| 17 | `techtrade\01-foundations-techtrade-and-analysis.ipynb` | Scans/signals/plans, market weather and validation; setup is guided rather than automated. |
| 18 | `techtrade\02-morning-scan.ipynb` | Segments/movers/ranked scan and workbook; retain classified narrative-in-code cell 7. |
| 19 | `techtrade\03-single-position-deep-dive.ipynb` | Votes/signals, plan, risk and simulation evidence. |
| 20 | `techtrade\04-validation-gate.ipynb` | Typed validation results, folds, thresholds and verdict gates. |
| 21 | `techtrade\05-tuning-per-sector.ipynb` | Bounded tuning jobs, reviewed configuration changes and rollback evidence. |
| 22 | `techtrade\06-audit-and-replay.ipynb` | Authorized workbook access, forward replay and discipline metrics. |
| 23 | `techtrade\07-t5-order-batch-and-xlsx-workbook.ipynb` | Typed batch, gate verdict, CSV and six-sheet workbook; no actual order placement. |
| 24 | `techtrade\08-t5-paper-trading-engine-walkthrough.ipynb` | Separate TechTrade SQLite paper engine, fills/cancel/reopen, approval and reconciliation. |
| 25 | `techtrade\09-t5-end-to-end-plan-to-fills.ipynb` | Full plan-to-batch-to-artifact-to-approved-paper-fill evidence chain. |

Important source distinctions:

- The existing coverage document's 40 literal `obb.*` route matches never proved
  full story coverage.
- Imported pipeline logic, notebook-local calculations, artifacts and paper
  operations require their own adapter mappings.
- Existing source-hash tests do not validate finance results.
- The current documentation reports 11/25 statically ready stories at an
  intermediate bridge stage. That is a historical readiness figure, not a
  newly measured or certified runtime result.
- The 21 mismatches affect all eight Portfolio notebooks, all eight
  Portfolio YFinance notebooks and TechTrade chapters 01, 02, 03, 04 and 06.
  A sampled source diff includes migrated issue links, but no claim is made
  that every mismatch is purely cosmetic. One story manifest also has migrated
  stage/output IDs. Reconcile source identity before using old readiness counts.
- Preserve free-provider variants for fixture/source parity. The baseline's
  current provider rule does not authorize live yfinance; live qualification
  needs an explicit policy decision.

## 4. Eleven additional documentation notebooks

These were inventoried separately because the existing story catalog only
covers `notebooks\`. Cell types and literal `obb.*` source symbols were inspected
without emitting saved outputs. Titles/symbols support the classifications below;
independent Hermes/service capability tests and any missing engine bindings are
future work. No notebook runtime or new notebook execution manifests are required.

| Path below `docs\examples` | Source evidence / intended outcome | Disposition |
|---|---|---|
| `copperToGoldRatio.ipynb` | Futures history and FRED series. | Add a macro commodity-ratio research story with source/unit alignment. |
| `usdLiquidityIndex.ipynb` | FRED search/series. | Add liquidity-indicator construction with component provenance and limitations. |
| `financialStatements.ipynb` | Statements, ratios, metrics, historical attributes, dividends and market cap. | Map to existing fundamental capabilities; retain accounting/fiscal-period semantics. |
| `findSymbols.ipynb` | Equity/ETF/index search, screening and SEC institution lookup. | Add an instrument-resolution story; distinguish listings/currencies and entity identifiers. |
| `loadHistoricalPriceData.ipynb` | Equity, crypto and currency history. | Add a multi-asset history story with calendars, adjustments and FX units. |
| `impliedEarningsMove.ipynb` | Options chains and earnings calendar. | Add a bounded options-implied-move calculation; expiry, spread and quote freshness matter. |
| `platform_standardization.ipynb` | News surface/provider standardization. | Provider-comparison educational story; missing fields are explicit. |
| `openbb_vs_langchain.ipynb` | Comparison groups, consensus and screening. | Preserve financial outcomes; framework comparison is explanatory, not a dependency. |
| `openbbPlatformAsLLMTools.ipynb` | Coverage/schema inspection, quote/history and account setup. | MCP/tool-use demonstration; no generated-code or login bypass. |
| `googleColab.ipynb` | Hosted notebook setup, credentials, options and ratios. | Setup becomes guided documentation; financial subset can become an approved story. Do not move private workloads to Colab. |
| `COMMUNITY_EXAMPLE_TEMPLATE.ipynb` | One code cell; no literal financial SDK symbol found. | Template/documentation classification, not a fabricated executable financial feature. |

All 36 files remain in the denominator. "Template", "setup-only" and
"unsupported" are explicit dispositions, not hidden exclusions.

## 5. Documentation coverage strategy

The selected `portfolio` baseline's `docs` tree contains 251 Markdown files.
Its groups are mapped
below so the product does not confuse engineering history with financial scope.
The grouping excludes untracked material in the original checkout. Preliminary
research there counted 243 files, but that is not this proposal's baseline.

| Documentation group | Markdown count | Product treatment |
|---|---:|---|
| `Specs` | 15 | Baseline requirement sources and explicit new/implemented/deferred mappings. This proposal is added here by user direction, overriding the newer root-level `specs` convention for this bundle. |
| `designs` | 31 | Engine and adapter contracts; technical provenance. |
| `design` | 3 | Additional legacy designs, with supersession checks. |
| `design-questions` | 1 | Unresolved decisions, not implemented behavior. |
| `superpowers` | 106 | Specs/plans/audits/dispositions; classify individually, do not execute as instructions. |
| `OpenBBPlatform` | 29 | Core/provider/router architecture, API semantics, terminology and recipes. |
| `OpenBB Agent` | 2 | Earlier ADK concepts and boundaries. |
| `cross_repo_workflow` | 9 | Capability ownership, story/API evidence, repository/submodule mapping. |
| `operations` | 10 | Service/release/health runbooks; privileged actions operator-only. |
| `planning` | 4 | Native Workspace direction and historical sprint material. |
| `FMP-api` | 1 | Endpoint catalog; confirm current entitlement/schema at runtime. |
| `Tools` | 2 | Quant strategy concepts; map supported calculations to current engines. |
| `examples` | 2 | Narrative around the 11 additional notebooks; preserve example outcomes. |
| `prompts` | 1 | Existing Pine project prompt; no execution-policy authority. |
| `reports` | 5 | Dated implementation/analysis evidence; preserve context and limitations. |
| `browser_test_harness` | 2 | Native UI acceptance methodology. |
| `handoff` | 2 | Historical continuity, privacy-filtered; absent local artifacts stay absent. |
| `migration` | 1 | Legacy issue mapping; no historical upstream write authority. |
| `release-notes` | 1 | Versioned release claims. |
| `archive` | 20 | Archived context/instructions and old organization rules; not current behavioral authority. |
| Root coordination/memory/strategy documents | 4 | Current strategy plus coordination/context; no wholesale agent-memory ingestion. |

A future capability register joins:

`source document/section -> requirement -> existing implementation ->
MCP owner/tool/schema -> access policy -> test -> UX -> qualification state`.

No claim of full documentation coverage should be made until every requirement
has that disposition. A source-count inventory is not a substitute.

## 6. Open-source shortlist and decisions

Licenses and archive flags were checked against official repository metadata
and, where ambiguity mattered, the license text. These are observations of the
researched versions, not a legal opinion or permission to ignore dependencies.

| Product | Evidence-backed use | License observed | Decision |
|---|---|---|---|
| OpenBB fork | Existing provider, financial engine, MCP, notebook and Workspace foundation. | Existing repo documentation describes AGPL-3.0; audit shipped components separately. | **Keep as core.** |
| NousResearch Hermes Agent [S01-S02] | MCP client, skills, memory, scheduling, configurable models and current native-Windows support. | MIT. | **Adopt harness through a finance-restricted adapter.** |
| User's Hermes WebUI fork / Workshop Hub [S03-S04] | Existing extension and authenticated-sidecar work. | WebUI fork metadata: MIT. | **Primary local chat-first UI**, per user direction; retain native Workspace for detailed dashboards. Native Windows startup and financial integration remain to qualify. |
| PolicyEngine US [S05] | Household-level US federal/state tax-benefit calculations. | AGPL-3.0. | **Preferred annual-tax candidate**, feature/year qualification required. |
| Owl [S06-S08] | Retirement spending, withdrawal/conversion optimization, historical/stochastic scenarios and native MCP. | GPL-3.0 code; CC-BY-NC-SA-4.0 docs; reserved name/logo/image rights. | **Preferred retirement candidate**, not the tax-lot truth. |
| Tax-Calculator [S09-S10] | Federal individual-income/payroll microsimulation and independent federal comparisons. | CC0-1.0 dedication; API metadata returned NOASSERTION, so license text was checked. | **Validation/reference engine**, not all-state planner. |
| OpenTaxSolver [S11-S12] | Local form calculations and PDF filling for supported federal/state returns. Current site advertises tax year 2025. | SourceForge lists GPLv2; verify exact release notices. | **Optional reference/form tool**, not current-year universal service. |
| tenforty [S13] | Python scenarios around OTS and a newer graph backend, explicit support/error states. | MIT wrapper; retain underlying OTS/dependency obligations. | **Conditional reference adapter**, platform/year restrictions are material. |
| Actual Budget [S14-S15] | Local-first envelope budgeting, transaction/cash-flow source and programmatic API. | MIT. | **Optional budget integration**, read-only first. |
| Wealthfolio [S16] | Local portfolio, net worth, spending, goals, simulations, addons and MCP. | AGPL-3.0. | **Best alternate standalone tracker**, but do not deploy as a competing primary ledger. |
| Ghostfolio [S17] | Self-hosted portfolio tracking, transactions, composition/performance and experimental MCP. | AGPL-3.0. | **UX/reference or optional import source**, not replacement core. |
| Maybe [S18] | Personal-finance UI and self-hosting reference. | AGPL-3.0; trademark restrictions. | **Do not select as a new core**: repository archived and explicitly unmaintained. |
| FinanceToolkit [S19] | Transparent ratios/performance/risk calculations and current upstream MCP. Existing fork/extension already available. | Existing user fork metadata: MIT. | **Reuse existing integration first**, avoid parallel hosted financial truth. |
| EdgarTools [S20] | Parsed SEC filings, financial statements, 13F/Form 4/N-PORT and current upstream MCP. | MIT. | **Selective reuse behind existing SEC ownership**, fair-access policy required. |
| FinRobot [S21] | Financial research/reporting patterns and deterministic-compute/provenance design. Existing user fork available. | Existing user fork metadata: Apache-2.0. | **Reference/selective components**, not another orchestrator or desktop shell. |
| PyPortfolioOpt [S22] | Mean-variance, Black-Litterman, shrinkage and HRP optimization. | MIT in current README. | **Optional library**, only for a demonstrated gap in existing optimizers. |
| NautilusTrader [S31-S34] | Standardized event simulation/strategy/catalog target beneath OpenBB. | LGPL v3 license text verified at candidate tag `v1.231.0`; per-component/wheel notices still require review. | **Selected architecture target, not installed or release-qualified.** Optional broker dependencies such as IBKR `ibapi` remain separately licensed and out of scope. |

> **[Reviewer Feedback — 2026-11-27]:** Add a row to this license table for **NautilusTrader (`nautechsystems/nautilus_trader`)** `[S31-S33]` now that it is selected as a core architecture target in `spec.md` §9.1 and `plan.md` §3.1: upstream core is licensed under **LGPL-3.0** (verify compiled Rust/Cython crate notices for the pinned release, and treat optional third-party broker adapters such as IBKR `ibapi` as out-of-scope / separately audited if ever enabled). Also note in `R22` that `openbb_backtest/engine/execution.py` uses exact `Decimal` arithmetic across both current engines, so the Nautilus evaluation should explicitly check 64-bit standard vs. 128-bit high-precision fixed-point wheels on Windows.

The market-data services FMP and TradingView are not made open-source merely
because an MCP client/server wrapper is open-source. Their service/data terms
remain a separate layer.

### NautilusTrader decision and migration evidence

**Decision:** adopt NautilusTrader as the target strategy/event-simulation
foundation beneath the OpenBB backtest API, while retaining product-owned
orchestration, approval/privacy contracts, FMP ingestion, TechTrade intent,
qualified statistical validation and household/tax logic. This supersedes the
earlier blanket recommendation to retain the custom backtest engine indefinitely.

Repository inspection [R22-R23] found custom vectorized and event-driven
implementations, not Zipline/VectorBT/Nautilus engines behind the run route.
The vectorized path has simplified cost accounting; the broker's named VWAP
reference is an OHLC approximation and tiered commission defaults to per-share
without a volume schedule. These are reasons to qualify execution assumptions
and reduce duplicated simulator ownership, not claims of measured live failures.
Existing engine agreement shares helpers and is not an independent oracle.

The shared `engine\execution.py` uses Decimal for money arithmetic; this does
not establish exact arithmetic throughout every vectorized/statistical path.
The extension declares Python `>=3.10,<3.14`. Compare the selected Nautilus
wheel's fixed-point mode, rounding and cash outcomes against independent
fixtures, not against the assumption that all legacy outputs are exact.

Official Nautilus documentation [S31] describes common backtest/live components,
event processing, strategies, catalogs, matching/fill models and account
simulation. Its IBKR documentation [S33] describes broker integration, but does
not by itself qualify this product's settlement, whole-share, tax or approval
policies. A richer simulator also cannot infer true intrabar paths from daily
FMP data.

The installation page reviewed on November 27, 2026 [S32] describes latest
2.x documentation versus stable 1.x installs, differing APIs and 2.x release
candidates; it cautions against prereleases for real-capital deployment.
It lists a specific Python/platform support matrix, not proof of this desktop's
compatibility. Pin a chosen release with matching docs and qualify an isolated
local runtime. No package was installed or version selected by this research.

| Tradeoff | Decision |
|---|---|
| Avoid rebuilding execution infrastructure | Prefer Nautilus after independent golden-case qualification. |
| Preserve existing workflows and financial value | Keep OpenBB as facade and normalize data/strategy/results through a bounded adapter. |
| Fast daily portfolio sweeps | Retain vectorized screening only if measured value warrants it; event validation remains authoritative. |
| Migration and modeling differences | Start with buy-and-hold, rebalance and TechTrade cases; explain differences rather than matching a legacy error. |
| Future trading connectivity | Design the adapter boundary now; broker-paper and live enablement remain separate approvals/scopes. |

### Local browser UX and native runtime

The user's WebUI fork README [S04] describes browser interaction with the actual
Hermes agent and an in-process agent backend by default. It reads the local
Hermes configuration; this is not simply a generic chat client pointing at an
external agent API. Its README distinguishes optional gateway routing from
full agent-loop delegation, which it describes as not yet shipped. These
observations do not establish native Windows startup or financial-profile
safety; neither was run for this proposal.

Official Hermes documentation also describes an Open WebUI integration [S30]
through the Hermes API server, with the real agent/tool loop running on the
API-server host. That is a reference/fallback architecture, not a decision to
deploy a second frontend. It demonstrates why agent-runtime location must be
verified independently from the browser/container location.

The approved target is the existing Hermes WebUI as primary app, native Windows
Hermes/MySQL, local private inference and local supporting services. Dockerizing
the default in-process WebUI would also containerize Hermes, contrary to that
target. Prefer qualified native WebUI startup; any UI-only container requires
verified delegation to the host agent. Do not equate a local proxy URL with
local inference, or local hosting with offline live-market access.

The user additionally reports an existing LiteLLM installation and requests its
reuse for AI endpoints. This is user-provided environment context, not a live
service or configuration verification. The design therefore reuses it rather
than introducing another proxy, subject to approved alias/backend mappings,
local-only private routes and verification of logging, retries and fallbacks.
No LiteLLM credential files were inspected for this proposal update.

### Private document/search additions

Official documentation reviewed for the requested private IRS/state-return and
financial-document workflow supports the following candidates. These are
documentation-level findings, not installed or locally qualified integrations.
Release pins, dependency/model licenses and Windows deployment acceptance remain
preconditions; no new license audit is claimed for these additions.

| Candidate | Verified documentation capability | Proposed role and limitation |
|---|---|---|
| Paperless-ngx [S26-S27] | Local original-document storage, OCR, document organization and full-text search. Optional remote processing/AI features require deliberate configuration. | Primary document vault and initial exact search. Disk storage does not imply encryption; disable hosted OCR/AI for the private corpus. |
| Docling [S28] | Local document processing, PDF layout/table understanding, OCR, structured output and MCP/API integration options. | Bounded extraction worker behind our adapter. General PDF understanding is not validated IRS field extraction or tax correctness. |
| Qdrant [S29] | Hybrid/multi-stage queries combining dense semantic and exact/sparse retrieval with rank fusion. | Optional local retrieval index using local embeddings and server-enforced metadata/ACL scope. Not original-file storage or accepted financial truth. |

Adopt exact/full-text search first. Evaluate semantic retrieval against a
held-out synthetic corpus with form identifiers, tax years, wrong-year near
matches, amended/corrected documents and conceptual questions. Require
document/page evidence and abstention when unsupported. A local vector database
does not prevent disclosure if embedding, OCR or inference requests go off-host.
Do not expose generic upstream MCP file/administration tools to Hermes simply
because a product offers an MCP integration.

Vault-Lite (encrypted content-addressed files, Docling and SQLite FTS5) is a
lower-service-count **alternative for owner selection**, not a claim of an
existing qualified vault. FTS5 neither encrypts nor authorizes documents; the
same lineage, ACL, review, deletion and restore contracts apply. Paperless
remains the earlier proposed adapter and Qdrant remains optional for either.

### Selection criteria

Preference order:

1. Preserve reviewed OpenBB domain logic and stable product contracts.
2. Prefer a qualified maintained engine behind those services where it avoids
   duplicated infrastructure; Nautilus execution is the selected example.
3. Add an isolated specialist engine if it closes a substantial gap.
4. Add another whole application only when its user value exceeds the cost of
   maintaining another database, UI and reconciliation path.

Do not choose on GitHub stars or agentic marketing. Evaluate input coverage,
numerical transparency, supported platform/year, failure semantics, licensing,
dependency health, privacy and maintenance.

## 7. Findings that materially change the design

### Hermes is capable, but unrestricted defaults are unsuitable

Current upstream documentation describes stdio/HTTP MCP, per-server tool
filtering, resources/prompts, OAuth support and native Windows. It also describes
terminal access, code execution, self-improving skills and broad integrations.

Use its MCP and conversational capabilities, not unrestricted financial-machine
control. Pin and qualify the actual chosen revision; do not assume the user's
older fork contains everything in current upstream.

Preserve the local-model/no-hosted-fallback safety intent from earlier Notebook
Companion work in the new Hermes/LiteLLM policy. Do not require its runtime or
configuration loader, and do not inherit general-purpose automatic model probing
or cloud fallback from older agent configuration.

### PolicyEngine is a rules engine, not a complete tax preparer

The current README explicitly retains household calculations while moving
population microsimulation to another package. The proposed product needs
household calculations, not national microdata.

Its current dependency requirements include pandas 3+, making environment
isolation important. Its source-conflict policy also distinguishes statutes
from forms/agency practice. Pin year/rule/source versions and expose conflicts.

National breadth does not establish full treatment of every compensation,
residency, local tax, basis adjustment or tax form. That remains qualification
work.

### Owl is unusually well aligned, but its limitations are decisive

Owl already exposes MCP tools for scenarios, optimization, comparisons and
explanation. A new natural-language retirement solver is unnecessary.

Its detailed modeling document identifies limitations that its broad README
headline can obscure:

- Taxable gains use average-cost treatment and are treated as long-term;
  no tax-loss harvesting or detailed tax-lot selection.
- Standard deduction rather than general itemized-deduction modeling.
- IRA pro-rata basis and inherited-IRA rules are not generally modeled.
- State AMT, local taxes and state-specific credits are omitted.
- Its documented move model applies December 31 residence to the whole year;
  it is not a proper part-year-residency calculation.
- State parameter tables need annual review.
- First-year planning uses annual conventions with specific mid-year caveats.
- Important HSA eligibility/limit and Social Security/ACA exceptions remain.
- Some stochastic optimization allows later decisions to adapt to scenario
  paths; outcomes are conditional on those modeling assumptions.

Therefore: use Owl for bounded long-horizon scenarios, compare feasible first-year
decisions under qualified tax calculations, and explicitly block cases outside
its scope. Do not market its output as a certified lifetime tax minimum.

### tenforty has a Windows/California trap

Its current README states that Windows builds provide the graph backend only,
while several California paths still require OTS. It distinguishes validated
graph states/years from unvalidated ones and documents specific refusals.

Do not turn on an `allow_unvalidated` option to obtain a desired answer.
If using it as a reference, qualify an appropriate isolated supported runtime
or restrict it to the cases it actually supports.

OpenTaxSolver's own site offers Windows executables; that does not contradict
tenforty's embedded OTS build limitation. They are different packaging paths.

### TradingView is not a data source for unattended finance agents

The official support page expressly limits MCP to personal interactive use
and excludes unattended/scheduled/bulk collection and feeding MCP data into
automated trading or decision systems [S24].

The detailed guide [S23] and support page differ on some capabilities and limits.
Do not infer current tool availability from an old count. The detailed guide
also classifies `get_active_watchlist` as a write because of possible creation/
activation effects.

The proposed safe boundary is a separate user-driven research session, subject
to current terms and authorization. No credential forwarding to unapproved
services, automated ingestion, quote-store population or optimizer input.

### FMP MCP complements, rather than replaces, FMP Cached

Indexed official documentation describes a plan-dependent grouped tool surface,
existing API usage limits and key/header or registered OAuth-client options
[S25]. Tool discovery does not establish endpoint entitlement.

Direct official MCP calls bypass the repository's cache unless a reviewed
integration explicitly reconciles them. Reuse `fmp_cached` first, and track
actual missing capabilities rather than swapping providers silently.

### An all-in-one finance app would duplicate substantial existing work

Wealthfolio is the strongest fit among the inspected standalone alternatives
for local-first tracking and broader household UX. Ghostfolio is also useful,
with a heavier PostgreSQL/Redis web stack and an experimental MCP surface.

Neither was shown to reproduce this fork's 25 story cases or provide a fully
qualified US/CA tax-lot and compensation planner. Use them as design references
or explicit data sources, not automatic replacements.

## 8. Official tax-source register

| ID | Primary source | Requirement supported |
|---|---|---|
| T01 | [IRS Publication 550](https://www.irs.gov/publications/p550) | Investment income, basis and wash sales; reviewed wash-sale text covers 30 days before/after, spouse cases and IRA/Roth IRA replacement differences. |
| T02 | [IRS Topic 427: Stock options](https://www.irs.gov/taxtopics/tc427) | Statutory/nonstatutory distinction, ISO AMT, compensation basis adjustment and Forms 3921/3922. |
| T03 | [IRS Publication 525](https://www.irs.gov/publications/p525) | Detailed stock compensation rules; linked by IRS Topic 427, to be pinned/reviewed for tax implementation. |
| T04 | [California capital gains](https://www.ftb.ca.gov/file/personal/income-types/capital-gains-and-losses.html) | California has no lower capital-gains rate; gains taxed as ordinary income. |
| T05 | [FTB Publication 1004](https://www.ftb.ca.gov/forms/misc/1004.html) | Equity compensation, qualifying disposition dates and residency/workday sourcing. Publication is revised 2015; confirm current law for each release. |
| T06 | [2025 Schedule CA instructions](https://www.ftb.ca.gov/forms/2025/2025-540-ca-instructions.html) | Official indexed guidance on HSA nonconformity and federal/state adjustments. Do not extrapolate to another year unchecked. |
| T07 | [Washington capital gains tax](https://dor.wa.gov/taxes-rates/other-taxes/capital-gains-tax) | General-income-tax absence does not eliminate investment-tax obligations. |
| T08 | [IRS Publication 505](https://www.irs.gov/publications/p505) and [Form 2210 instructions](https://www.irs.gov/instructions/i2210) | Required year-pinned references for withholding timing, exceptions and annualized installments; this reconciliation does not certify current-year calculations. |
| T09 | [Form 6251 instructions](https://www.irs.gov/instructions/i6251) and [Form 8801 instructions](https://www.irs.gov/instructions/i8801) | ISO/AMT and minimum-tax credit qualification sources, including timing and carryforward distinctions. |
| T10 | [Form 8606 instructions](https://www.irs.gov/instructions/i8606) | IRA basis, year-end aggregation and conversion qualification; do not assume all balances/accounts have identical treatment. |
| T11 | [2025 Form 540-ES instructions](https://www.ftb.ca.gov/forms/2025/2025-540-es-instructions.html); [FTB forms lookup](https://www.ftb.ca.gov/forms/search/) for the corresponding Form 5805 | 2025 page verified: 30/40/0/30 installments; prior-year limits based on filing status; current-year CA AGI **equal to or greater than** $1M/$500k MFS invokes current-year basis. Payment dates include weekend/holiday adjustments. Requalify for the selected tax year. |
| T12 | [CA Revenue and Taxation Code 17145](https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=RTC&sectionNum=17145.) and [FTB forms lookup](https://www.ftb.ca.gov/forms/search/) for Publication 1001 | Required primary authority for qualifying-fund tests and attributable exempt income, not blanket ETF exemption. Direct statute fetch returned 403 and guessed Publication 1001 HTML paths returned 404; exact year-specific publication retrieval remains a qualification gate. |

T08-T10 are registered qualification sources, not newly certified engine
coverage. Year-specific SDI wage/rate rules need EDD authority; mortgage and
surtax cases need the selected year's FTB instructions. Do not promote review
examples such as supplemental withholding percentages, mortgage caps or SDI
rates into evergreen constants. The statutory manifest records effective dates,
filing status, exceptions and unresolved authority conflicts.

These sources establish important design requirements. They do not constitute
an exhaustive legal reference set for all proposed tax features.

> **[Reviewer Feedback — 2026-11-27]:** Before Phase 3/4 qualification, expand §8 with five primary authorities covering the highest-impact Federal + California planning mechanics:
> - **IRS Publication 505 & Form 2210 (Schedule AI):** Withholding ratable-treatment rules and annualized income installment safe harbors.
> - **IRS Form 6251 & Form 8801 Instructions:** ISO bargain-element AMT calculation and multi-year Minimum Tax Credit carryforward recovery.
> - **IRS Form 8606 Instructions (IRC § 408(d)(2)):** Non-deductible Traditional IRA basis tracking and Dec 31 pro-rata aggregation rules for Roth conversions.
> - **FTB Form 540-ES & Form 5805 Instructions:** California's `30% / 40% / 0% / 30%` front-loaded installment schedule and `$1,000,000` AGI disqualification of the 110% prior-year safe harbor.
> - **CA Rev. & Tax Code § 17145 & FTB Publication 1001:** US Treasury interest subtraction and the `>=50%` quarterly fund-asset threshold for ETF/money-market pass-through exemption.

## 9. Source register for product research

| ID | Official source |
|---|---|
| S01 | [Hermes Agent README](https://github.com/NousResearch/hermes-agent/blob/main/README.md) |
| S02 | [Hermes MCP documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) |
| S03 | [User's Workshop Hub plan](https://github.com/rashmijain02/multi-lora/blob/main/ux-workspace/PLAN.md) |
| S04 | [User's Hermes WebUI fork](https://github.com/rashmijain02/hermes-webui) |
| S05 | [PolicyEngine US README](https://github.com/PolicyEngine/policyengine-us/blob/main/README.md) |
| S06 | [Owl README](https://github.com/mdlacasse/Owl/blob/main/README.md) |
| S07 | [Owl modeling capabilities and limitations](https://github.com/mdlacasse/Owl/blob/main/info/modeling-capabilities.md) |
| S08 | [Owl MCP contract](https://github.com/mdlacasse/Owl/blob/main/info/mcp.md) |
| S09 | [Tax-Calculator README](https://github.com/PSLmodels/Tax-Calculator/blob/master/README.md) |
| S10 | [Tax-Calculator license](https://github.com/PSLmodels/Tax-Calculator/blob/master/LICENSE) |
| S11 | [OpenTaxSolver project site](https://opentaxsolver.sourceforge.net/) |
| S12 | [OpenTaxSolver SourceForge project/license](https://sourceforge.net/projects/opentaxsolver/) |
| S13 | [tenforty README](https://github.com/mmacpherson/tenforty/blob/main/README.md) and [license](https://github.com/mmacpherson/tenforty/blob/main/LICENSE.txt) |
| S14 | [Actual Budget README](https://github.com/actualbudget/actual/blob/master/README.md) |
| S15 | [Actual Budget API documentation](https://actualbudget.org/docs/api/) |
| S16 | [Wealthfolio README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md) |
| S17 | [Ghostfolio README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md) |
| S18 | [Maybe maintenance notice](https://github.com/maybe-finance/maybe/blob/main/README.md) |
| S19 | [FinanceToolkit README](https://github.com/JerBouma/FinanceToolkit/blob/main/README.md) |
| S20 | [EdgarTools README](https://github.com/dgunning/edgartools/blob/main/README.md) |
| S21 | [FinRobot README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md) |
| S22 | [PyPortfolioOpt README](https://github.com/PyPortfolio/PyPortfolioOpt) |
| S23 | [TradingView detailed MCP guide](https://www.tradingview.com/mcp/docs) |
| S24 | [TradingView MCP support and permitted use](https://www.tradingview.com/support/solutions/43000795699-mcp-server-connect-your-ai-assistant-to-tradingview/) |
| S25 | [FMP official MCP documentation](https://site.financialmodelingprep.com/developer/docs/mcp-server) - indexed official content reviewed; full fetch returned 403. |
| S26 | [Paperless-ngx documentation](https://docs.paperless-ngx.com/) |
| S27 | [Paperless-ngx advanced usage and AI privacy considerations](https://docs.paperless-ngx.com/advanced_usage/) |
| S28 | [Docling capabilities and local document processing](https://docling-project.github.io/docling/) |
| S29 | [Qdrant hybrid and multi-stage queries](https://qdrant.tech/documentation/search/hybrid-queries/) |
| S30 | [Official Hermes Open WebUI integration and agent runtime location](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/open-webui) |
| S31 | [NautilusTrader backtesting architecture](https://nautilustrader.io/docs/latest/concepts/backtesting/) |
| S32 | [NautilusTrader installation, release/API and platform guidance](https://nautilustrader.io/docs/latest/getting_started/installation/) |
| S33 | [NautilusTrader Interactive Brokers integration](https://nautilustrader.io/docs/latest/integrations/interactive_brokers/) |
| S34 | [NautilusTrader candidate v1.231.0 source](https://github.com/nautechsystems/nautilus_trader/tree/v1.231.0) and [license](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/LICENSE) |

Selected branch tips captured during research for later reproducibility:

| Repository | Observed revision |
|---|---|
| Authoritative OpenBB baseline, fetched `origin/portfolio` | `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7` |
| `rashmijain02/multi-lora` main | `111333761939668c5fce11938c0aa22f86921622` |
| `NousResearch/hermes-agent` main | `ab7e19a761e0ef52ef0d1c5f0417c5784c653446` |
| Installed native Hermes v0.22.5 (earlier local inspection; Python 3.14.9) | `bf0203a794a07aac3ff764972ab9087baa4e4f4e` |
| Local Hermes research fork (earlier inspection) | `710fa8a073f9a8136e10749b083a16779341faef` |
| `rashmijain02/hermes-webui` remote HEAD (read-only reconciliation lookup) | `2ea43049ed2ed18ad0b8129f6a3a31456b954b30` |
| Nautilus candidate `v1.231.0` tag ref (read-only lookup) | `d3e1685e979925d7b0ffacd1b3f442547686e18f` |
| `PolicyEngine/policyengine-us` main | `0fbed6ddb1c7e632e21f48357249e6c7bb40403f` |
| `mdlacasse/Owl` main | `3220bc1587c6bbb38e29f2e5f3710326230debaf` |
| `mmacpherson/tenforty` main | `ac63cc4d93a6aef48bb7c27f04dc088977f26c92` |

These are observed branch tips, not installed versions or recommended release
pins. Pages were read around the time these tips were captured, not obtained
as a fully archived byte-for-byte source bundle.

These three Hermes revisions have different roles, not conflicting installation
claims. Installed source governs cron findings; upstream/fork observations do
not prove the installed runtime's MCP/WebUI parity. Phase 0 must qualify one
native runtime against both contracts and record WebUI/runtime compatibility.
The Nautilus tag is an evaluation candidate only: bind matching source/docs,
wheel hashes, ABI/platform and precision before deployment; latest 2.x web
documentation cannot certify the candidate 1.x behavior.

## 10. Licensing and personal-use conclusion

Personal use makes some deployment/distribution obligations less likely to be
triggered, but **"any license will work" is not a safe universal assumption**.

Keep source notices and dependency licenses. Review modifications/distribution
or network-use obligations before sharing the system. Do not copy reserved
logos/trademarks, reproduce documentation wholesale, redistribute provider
datasets, ignore model-weight licenses, or assume a paid data feed permits
automation because the client is free software.

The recommended core can be assembled from the existing OpenBB fork, Hermes,
qualified tax/retirement engines and optional budget tooling without adopting
a proprietary all-in-one finance platform. The real work is **correct
integration, evidence, permissions and qualification**, not finding one more
agent framework.

---

## Appendix: Reviewer Comments & Evidence Gaps to Close Before G1 (2026-11-27)

1. **Reconcile Three Observed Hermes Revisions Across the Bundle:** §9 above records `NousResearch/hermes-agent` `main` at `ab7e19a761e0ef52ef0d1c5f0417c5784c653446`, whereas `prompts\out\fmp-cache-hermes-sync-design.md` §2 observes installed local Hermes CLI `v0.22.5` at `bf0203a794a07aac3ff764972ab9087baa4e4f4e` (running on Python `3.14.9`) and a local research fork at `710fa8a073f9a8136e10749b083a16779341faef`. Record `rashmijain02/hermes-webui`'s exact SHA and `nautechsystems/nautilus_trader`'s candidate stable 1.x release tag in §9, and confirm during Phase 0 whether the installed `v0.22.5` runtime satisfies both cron (`fmp-cache-hermes-sync-design.md`) and MCP/WebUI (`spec.md` / `plan.md`) requirements.
2. **Document Vault Baseline Simplification (§6):** Note that for a single household's annual tax corpus, an encrypted content-addressed local directory + Docling + SQLite FTS5 ("Vault-Lite") provides a lower-risk Phase 3a starting point than standing up full Paperless-ngx + Qdrant before extraction accuracy is proven.
3. **Cross-Reference Companion Input:** Additional domain feature candidates and detailed codebase cross-checks remain preserved in [recommendations.md](./recommendations.md).

## Review disposition and evidence corrections

R15/R18, the Nautilus license row, tax-source register and revision-role table
are updated. Importer source (`store.py:1-20,310-365`) explicitly selects MySQL
by default with SQLite fallback, contrary to the review's blanket SQLite
assumption; no private store or configuration was opened to discover actual use.
The current legacy table's age does not establish the age/location of all imports.

W2 vendor observations are template evidence, not reproduced incidents or
universal provider defects. Reconcile units/classes/dates before applying
diagnostic thresholds. The source template's heuristic haircut/order examples
are not adopted tax or investment rules. Original reviewer comments and
`recommendations.md` remain unchanged; candidate numbering is controlled by
the spec's explicit pending-selection table.

Vault choice, candidate release/platform qualification and remaining primary
tax-source retrieval stay open. This is a reconciled design, not completed G1
approval, software installation or operational certification.

