# OpenBB + Hermes: architecture and integration design

**Status:** Proposed design. Interfaces described as new are not installed tools.
**Location:** `docs\Specs\gh-1312-hermes-financial-planning\`, as directed by the user.
**Source proposal:** [Personal Financial Intelligence](spec.md).
**Evidence:** [Coverage and research](research.md).
**Tracking:** [#1312 (Hermes integration and unified financial-planning proposal)](https://github.com/rashmijain02/OpenBB/issues/1312).
**Baseline:** `origin/portfolio` at `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7`.

## 1. Architecture

```text
Primary local Hermes WebUI               Native OpenBB Workspace
  conversation, workflows, run cards       detailed dashboard drill-through
                   \                    /
                    Finance agent adapter
                    Native Windows Hermes
                    existing LiteLLM -> approved local inference
                    reviewed skills and bounded scheduler
                              |
                    Deterministic policy boundary
                    manifests, approvals, budgets, evidence
                              |
       +----------------------+-----------------------+
       |                      |                       |
 Existing OpenBB MCP     Private planning MCP     Optional adapters
 Platform/Portfolio     household, lots, tax      Owl / Actual / SEC
 jobs, runs, artifacts  opaque references        isolated environments
       |                      |
 OpenBB analytics +     Local tax/retirement engines
 Nautilus adapter
       |                      |
 FMP Cached/MySQL       Private accepted snapshots
 approved providers     and encrypted local artifacts

 Workspace MCP: separate UI-publishing connection and credentials
 Existing Agents/Daytrade MCP: separate, narrow, reviewed surfaces
 TradingView: separate personal interactive research session only
```

The agent never receives the database password or a direct database handle.
Server-side financial code performs calculations. An API/DB boundary is a
privilege boundary, not merely a convenience wrapper.

The browser app is the primary entry point, not a replacement financial engine.
Its navigation, progress and evidence cards reference the same durable run IDs
as Workspace. Raw private artifacts are served to authorized local views, not
injected into chat transcripts or model context.

## 2. Ownership: Hermes is the sole production harness

Hermes owns conversation, intent-to-workflow selection, bounded planning,
approved tool calls, scheduling and run coordination. Reuse reviewed typed
contracts and server-side run/job infrastructure for durable execution and
evidence. Notebook files, kernels and chapter state are not production inputs.

The deterministic policy adapter validates allowed operations, dependencies,
budgets, approvals and required artifacts. Jobs may execute fixed computational
stages, but cannot select new goals or autonomously replan. These are service
responsibilities beneath Hermes, not another assistant harness.

Do not build or invoke a separate Notebook Companion planner, notebook runner
or Workspace assistant loop for production workflows. Preserve existing source
and tutorial utilities without making them a runtime dependency. Any existing
standalone agent endpoint is outside the new production path; a Workspace
conversation entry point, if exposed for this product, must delegate to the
same Hermes run coordinator rather than launch another planner.

Notebooks remain human-run learning and verification clients of shared
libraries. Reusable backend contracts currently under `notebook_guide` may be
adapted into the production integration after review; their historical location
does not make notebook source, inventory hashes or readiness scans necessary
for a production request. No notebook deletion or code migration is performed
by this proposal.

Roles such as Research, Portfolio, Tax and Retirement initially mean **skills
with different allowed tools**, not always-on separate agents. Introduce a
bounded specialist agent only when measured quality improves enough to justify
its context, cost and additional failure modes. A skeptic can flag missing
evidence, but cannot overrule deterministic financial or authorization checks.

## 3. Reuse map

| Existing component | Keep responsibility | Proposed addition |
|---|---|---|
| `Analysis\stock_analysis.py` | Seven-phase single-name analysis. | Hermes skill invokes its existing story adapter. |
| `portfolio_intel` | Look-through, events, risk, attribution, what-if and Portfolio paper semantics. | Household policy and tax scenario linkage, not duplicated analytics. |
| `techtrade` | Scans, signals, validation, tuning, order batches and TechTrade paper semantics. | Run presentation and contextual planning constraints. |
| `backtest` | OpenBB API/result/privacy contracts, validated statistics and reporting. | Versioned Nautilus data/strategy/execution adapter and controlled cutover from the in-house event engine; vectorized screening retained only if justified. |
| `fmp_cached` | Market-data cache/provider integration. | Explicit source entitlement and purpose policy. |
| `agents\...\notebook_guide` | Historical typed contracts, source inventories and tutorial readiness. | Selectively reuse backend contracts in the Hermes integration; no additional planner or runtime notebook-readiness dependency. |
| `notebooks\` and `docs\examples\` | Tutorials, learning and manual result verification. | Preserve source-to-capability references; no production notebook execution. |
| `mcp_server\...\story_adapters` | Run registry, analytics, artifacts, jobs and paper gates. | Reuse and qualify; add only genuinely absent domain operations. |
| Native widget backend | Workspace manifests/endpoints, Plotly/raw contracts, app groups, provenance and selected-widget agent context. | Household/Tax/Retirement widgets using its current conventions. |
| Private import/storage tools | Parse and reconcile local financial inputs. | Versioned household/lot snapshots with explicit tax semantics. |

Current source inspection found `contracts.py` and `readiness.py` in
`notebook_guide`, plus story manifests; it did not establish a completed Hermes
runner. The story-adapter directory includes analytics, attribution, single-name,
registry, artifacts, jobs, paper approval, batch and Portfolio paper modules.
File existence is not proof of a running server.

The existing native agent's selected-widget path is not the Hermes production
harness. Do not route new product requests into that separate model loop; reuse
its reviewed widget contracts as appropriate. Its existing behavior outside the
new product is not changed here. Private household/tax values must not enter
its external-provider context path. A connector token or redacted account label
is not sufficient proof that a numeric payload is safe to disclose.

> **[Reviewer Feedback — 2026-11-27]:**
> 1. **Decouple Runtime Workflow Contracts from `.ipynb` Paths (`spec.md` `PF-27`):** Current `StoryManifest` in `notebook_guide/contracts.py` and several `story_adapters` encode relative notebook paths, one-based cell positions, and source-only `.ipynb` hashes. Because `spec.md` §13 (*Harness independence*) requires production workflows to succeed with `notebooks/` unmounted, extract a notebook-agnostic `WorkflowManifest` (plus `Access` v2 literals `"household_meta"`, `"tax_compute"`, and `"document_evidence"` distinct from sanitized `"private_read"`) into `hermes_integration/`. Keep `.ipynb` hash/cell mappings strictly in optional build/CI parity metadata (`TutorialTraceabilityRef`). Also update §8 ("Checkpoints bind the source manifest") to say **workflow manifest**.
> 2. **Enforce `AGENT_DENIED_WIDGETS` on New Private Widgets (`#1272`):** In `widget_backend/agent_policy.py` (delivered in `#1272 ([portfolio-ux] Align Workspace agent capabilities)`), explicitly register every future Household, Tax Center, Retirement, and Document Vault widget as **denied** on the external-model `/query` copilot (`privacy_class="household_private"`), or route Workspace `/query` exclusively through the local Hermes coordinator so selecting a Tax widget inside Workspace can never leak private rows to an external LLM.

### 3.1 Nautilus adapter and ownership boundary

**Reconciled production contracts:** extract a notebook-independent
`WorkflowManifest` under the Hermes integration, with workflow/version,
capability/tool schema hashes, access policy, stages and input/artifact schemas.
Checkpoints bind `workflow_manifest_sha256`. An optional build/CI
`TutorialTraceabilityRef` maps notebook paths/cells/hashes to that workflow;
production must not import notebook validators or open `.ipynb` files.
Version new access capabilities (`household_meta`, `tax_compute`,
`document_evidence`) explicitly; they are not synonyms for `private_read` and
unknown values deny by default. Scope capabilities by operation and principal.

Workspace `/query` delegates to this same coordinator in the production profile;
disable it there until delegation is qualified. Enforce private-widget denials
server-side (including `AGENT_DENIED_WIDGETS` or its qualified successor) on
every context path; new Household/Tax/Retirement/Vault widgets default denied
to external models. No independent Workspace agent loop survives the cutover.

NautilusTrader is the selected target for standardized strategies and
event-driven backtesting, not a second assistant harness. Hermes coordinates
approved runs; Nautilus executes deterministic trading simulations beneath the
existing OpenBB API and policy/job infrastructure.

```text
Hermes -> approved backtest request -> OpenBB facade / authorization
                                      |
                          versioned run specification + job ID
                                      |
                          isolated local Nautilus worker
                         /              |               \
              derived catalog    reviewed strategy    simulation config
                                      |
                           normalized result + provenance
                                      |
                     privacy filter / validation / artifacts
```

Retain `obb.backtest.run`, `sweep`, `reconcile`, `validate` and `tearsheet`
contracts where compatible. A new engine selector is proposed, not currently
implemented. Preserve argument precedence and make backend resolution explicit
in each run record. Old artifacts retain their original engine/semantics;
replaying them must not silently recompute with Nautilus defaults.

The facade submits typed, versioned requests to a bounded worker. Do not pass
live Python strategy objects between environments or expose arbitrary Python,
module names, paths or code through MCP. Use opaque dataset/run IDs and
allowlisted strategy IDs; worker-side resolution enforces authorization.
CPU/memory/wall-time/concurrency budgets and cancellation apply to every sweep.
Timeout/retry observes the same durable job rather than duplicating a paper effect.

### 3.2 Data and strategy standardization

FMP Cached/MySQL remains the market-data ingestion authority. Generate a
Nautilus-compatible catalog as a reproducible derivative, not a second
independently refreshed market-data truth. Preserve source/bundle hashes,
instrument identity, exchange calendar/timezone, currency, price/quantity
precision, bar interval/availability timestamps, corporate-action policy and
fundamental publication lags. Catalog format/version belongs to the chosen
Nautilus release; conversion cannot assert higher precision than the source.
Prevent double adjustment of prices/dividends and reject unsupported instruments
or ambiguous identifier mappings.

Define a reviewed `StrategySpec` with canonical strategy ID/version/code hash,
typed parameter schema, required data, warm-up, decision timing, sizing/risk
constraints and execution assumptions. Translate existing TechTrade intent and
portfolio target weights into that approved implementation, retaining their
economic meaning. Use Nautilus strategy lifecycle conventions; do not maintain
parallel handwritten strategy versions to force cross-engine agreement.

For vectorized screening, expose only compatible projections of the canonical
strategy intent. Reject unsupported path-dependent semantics. A screen result
is not an execution-grade result; revalidate finalists using the qualified
Nautilus backend. Shared code or correlated assumptions mean cross-engine
agreement alone is not an independent correctness check.

Normalize worker output into the existing result/evidence contracts, including
engine/adapter/strategy versions, data hash, execution assumptions, warnings,
units, trades, cash and return timestamps. Private position/lot details stay
behind the existing facade's sanitization boundary. Preserve the distinct
Portfolio and TechTrade ledgers: only their approved adapters can commit
normalized fills, idempotently, under existing human-issued paper approvals.
Nautilus simulation accounts are not household records or tax-lot truth.

### 3.3 Qualification, migration and retirement

Implement these gates in order:

1. Pin a maintained release and matching documentation; qualify Python/platform
   packaging and review licenses/dependencies. Do not install a prerelease
   merely because examples in `latest` docs require it.
2. Run three independent synthetic golden cases: buy-and-hold, periodic
   target-weight rebalance, and TechTrade entry/stop/target. Validate cash,
   quantities, equity, fees, timing and explicit ambiguous-bar behavior.
3. Compare the existing engine on matching assumptions as a diagnostic.
   Explain material differences; do not tune Nautilus to reproduce a legacy
   error or compare incompatible fill modes as though they were equivalent.
4. Route qualified validation folds and sweeps through the same adapter.
   Requalify WFO/CPCV, overfitting statistics and reports against the normalized
   returns, calendars, costs and trial accounting. Do not assume old thresholds
   or metrics remain valid after execution semantics change.
5. Explicitly cut over each accepted capability and record its backend/version.
   Fail closed on unsupported features; never silently fall back to a custom
   simulator. A rollback is an operator-approved configuration/version change.
6. Retire redundant event/broker/fill paths after all their supported consumers
   and regression cases are migrated. Keep historical artifacts and necessary
   versioned replay support; no indefinite dual authoritative engines.

Existing vectorized screening is optional and benchmark-driven, not a reason
to keep expanding an independent execution simulator. Existing paper simulation
may remain during staged migration, but the target is reused Nautilus mechanics
under distinct product ledger/approval contracts, not two sets of fill logic.

Backtest workers have no brokerage credentials or broker-network permissions.
Future Nautilus broker adapters require separately approved deployment profiles,
paper-account reconciliation, order/position recovery, emergency controls and
account-specific settlement/sizing rules. Their existence does not authorize
IBKR access or live trading here. Generated strategy code requires review and
explicit promotion before any worker can load it.

> **[Reviewer Feedback — 2026-11-27]:** Four implementation constraints discovered by cross-checking `openbb_platform/extensions/backtest/` and the installed Windows environment:
> 1. **CPython ABI & Windows Binary Wheel Pinning:** `fmp-cache-hermes-sync-design.md` §2 observes installed Hermes on **Python 3.14.9**, while `openbb-backtest/pyproject.toml` requires `python = ">=3.10,<3.14"`, and NautilusTrader ships compiled Rust/PyO3 + Cython wheels with strict CPython minor-version and precision-mode matrix limits (standard 64-bit `<=9` decimals vs. high-precision 128-bit, which has historically differed on Windows builds). Explicitly pin the isolated Nautilus worker's Python minor (e.g., Python 3.12) and verify Windows 64-bit vs. 128-bit precision behavior against `openbb_backtest/engine/execution.py`'s `Decimal` arithmetic during Gate 1.
> 2. **Arrow/Parquet Catalog URI Passing (Zero JSON Bar Serialization):** For `obb.backtest.sweep` and multi-year daily/intraday runs, pass content-addressed local Parquet/Arrow catalog URIs + SHA256 digests to the Nautilus worker rather than serializing OHLCV bars over HTTP/JSON IPC.
> 3. **Daily-Bar Multi-Asset Rebalance Order Staging:** Require deterministic **sell-before-buy** order sequencing in target-weight rebalance strategies so freed cash from trims settles before buy legs execute on the same daily bar without false margin rejections.
> 4. **Preserve Cross-Worker Deflated Sharpe / CPCV Trial Counts:** Ensure `openbb_backtest/validation/stats.py` receives cumulative sweep trial counts (`N_trials`) from the Nautilus worker so Deflated Sharpe Ratio and Probability of Backtest Overfitting penalties remain intact.

Nautilus qualification additionally pins release, wheel digest, CPython minor,
OS/architecture and standard/high-precision mode. Python 3.12 is an evaluation
candidate, not a verified compatible installation. Hermes' Python 3.14 runtime
must not be reused for OpenBB backtest (whose inspected constraint is `<3.14`).
Compare native Windows and local Linux-container workers before choosing.
Pass allowlisted, content-addressed catalog references and SHA256 digests rather
than multi-year bars in JSON; verify paths, hashes and provenance in the worker.
Arrow/Parquet avoids unnecessary serialization but is not a zero-copy guarantee.

Sell-before-buy staging respects settlement and account type; unavailable sale
proceeds cannot fund same-bar buys in a cash-account simulation. Declare
instrument precision, rounding direction and bounded reconciliation tolerances
per field; verify cash/fees independently. Preserve all evaluated configurations,
fold returns and exclusions, with retries deduplicated by trial ID. DSR trial
accounting and CPCV/PBO result matrices must remain complete across worker splits.

## 4. Two data planes

### Public/provider plane

Contains approved market data, source filings, financial statements, rates,
economic series and redistributable fixtures. Provider terms still apply.
Storage has source identity, entitlement/retention rules and as-of semantics.

### Private household plane

Contains financial documents, account identities, actual balances, tax lots,
compensation events, residency facts and tax inputs. Raw data remain outside
the repository and outside notebook outputs.

Existing sanitized `portfolio_basket` data are useful for analysis but are not
a substitute for actual tax inputs. Normalized amounts cannot recover a
household's brackets, basis, income or liabilities.

A new private computation channel requires an explicit design/permission gate.
It must not weaken the existing denied raw position/cost/tax MCP routes.

### Output separation

1. **Machine-private input/output:** exact values available to local authorized
   deterministic services.
2. **User-private display:** local widgets/reports containing authorized exact
   results, delivered directly from artifact services.
3. **Model-safe evidence:** opaque IDs, capability status, finding codes,
   non-sensitive descriptions and approved aggregates only.
4. **Public development fixtures:** synthetic scenarios with no derivation from
   private accounts.

Hashing an account number, removing a name or preserving exact weights does
not automatically anonymize financial information. Redaction must consider
combinations and re-identification.

Default to no financial facts in Hermes persistent memory. Store reviewed
procedural skills and harmless workflow preferences only. Consent to use a
local model does not automatically authorize copying raw lots into its context
or training logs.

### Physical persistence and model projection

| Data | Proposed authority and boundary |
|---|---|
| Provider/market records | Existing native MySQL/FMP store; existing retention ownership unchanged. |
| New household, lots, investment events and accepted document facts | Separate encrypted-at-rest local store outside Git, with a dedicated identity, schema ownership and restore/key procedure; select SQLCipher or qualified encrypted-volume SQLite at deployment qualification. |
| Originals, OCR, FTS and optional vectors | Private encrypted storage with the same authorization/deletion lineage; vault adapter does not confer model access. |
| Legacy private MySQL tables | Still private. No expansion through this feature; inventory/quarantine or migration is a separately approved project, not a cron action. |

The source importer supports **both MySQL and SQLite**, defaults to MySQL, and
can fall back to SQLite. Its runtime backend/current snapshot has not been
verified here. Do not describe SQLite as today's authoritative household store
or claim that MySQL currently contains only public data. Existing imports are
not redirected by this plan.

`PrivateMetricRef` uses run/artifact/field identifiers, not paths or bearer
permissions. The UI reauthorizes each reference against a field allowlist and
renders plain values without returning hydrated DOM/content to agent tools,
chat persistence or telemetry. A local-only derived-evidence allowlist may expose
bounded ratios/categories after inference-risk review; percentages and weights
are not inherently non-private. Exact amounts/quantities remain excluded.

> **[Reviewer Feedback — 2026-11-27]:**
> 1. **Explicit Physical Persistence Boundary (MySQL vs. Private SQLite/SQLCipher):** `fmp-cache-hermes-sync-design.md` §3 reveals that `MySQL84` (`openbb_fmp_cache_test`, listening on `0.0.0.0:3306`) still contains legacy `portfolio_positions` (586 rows, Feb 20), `account_owner` (9 rows), and `espp_plan` (2 rows), while newer position imports use append-only user-local SQLite (`~/.portfolio_importer/positions.db`). Codify a hard rule here: **MySQL owns only the Public/Provider plane (`fmp_cached`)**, while all new Household, TaxLot, InvestmentEvent, and AcceptedFact tables live in an **encrypted-at-rest local store outside the repo** (extending `~/.portfolio_importer/` with SQLCipher or DPAPI/BitLocker single-user ACLs) and legacy private tables in `openbb_fmp_cache_test` are migrated/quarantined rather than expanded.
> 2. **Specify Client-Side Metric-Token Hydration:** Add the concrete wire contract connecting item 2 (*User-private display*) and item 3 (*Model-safe evidence*): Hermes emits structured tokens (`[[metric:run_id:artifact_id:field_key]]`) alongside dimensionless `Tier 1` analytical ratios (`bps`, `%` weights, marginal bracket `%`), and Hermes WebUI resolves exact `$` values directly from the local artifact endpoint using browser session auth—never writing resolved dollar strings into Hermes chat history or LiteLLM logs.

## 5. Proposed domain contracts

Use versioned, strict schemas following the existing Pydantic conventions.
Names below describe proposed data contracts, not implemented Python classes.

| Contract | Important fields and invariants |
|---|---|
| HouseholdSnapshot | Server-issued ID, version, accepted-at, ownership relationships, scoped source refs, completeness flags. No account identity in client prompts. |
| FinancialPolicy | Goals, horizons, liquidity floors, restricted assets, risk constraints, approval/version history. |
| AccountSnapshot | Account type, currency, opening/closing reconciliation, pending transactions, source timestamps. |
| InvestmentEvent | Acquisition/disposition/corporate action/transfer, dates, quantity, unit, currency, evidence and correction linkage. |
| TaxLot | Broker basis and adjusted basis separately, ordinary-income adjustment, holding period, federal/state differences, unknown-basis marker. |
| ResidencyTimeline | Domicile/residency claims, work locations/dates, supporting document refs and unresolved facts. |
| TaxScenario | Tax year, jurisdiction/case, baseline snapshot, proposed events, engine/revision, rounding and feature coverage. |
| RetirementScenario | Accepted account buckets, cost basis, time convention, income/benefit units, model assumptions, solver bounds. |
| EvidenceEnvelope | Run/stage/tool IDs, inputs hash, source dates, provider identity, engine version, artifacts, warnings, exclusions. |
| JurisdictionCoverage | Year, form/feature/case support, tests, official sources, review date and certification expiry. |
| Approval | Principal, operation, argument hash, run/version, destination/sandbox, expiry and one-use nonce. |
| WorkflowManifest | Notebook-free runtime workflow/version, typed stages, access capabilities and schema hashes; referenced by checkpoint digest. |
| TutorialTraceabilityRef | Optional build/CI linkage to tutorial cells/source hashes; never a production prerequisite. |
| PrivateMetricRef | Run/artifact/allowlisted field plus authorization scope; display reference only, never an access token. |
| StatutoryLawManifest | Tax year/jurisdictions, enacted/effective cutoffs, official-source revisions, engine parameters, conflict decisions and qualification state; pinned by every TaxScenario. |
| VendorReconciliationReport | Matched dates/classes/units/basis, eight W2 check outcomes, independent source refs, coverage gaps and unresolved discrepancies; no cache correction side effect. |

Extend `TaxLot` with Form 8949 categories **A-F**, adjustment codes/amounts,
supplemental stock-plan evidence references and separate federal/state adjusted
basis. Unknown/nonapplicable categories remain explicit. Forms 3921/3922 are not
universal RSU documents; use the applicable broker/payroll evidence. Existing
float-based input helpers need decimal/rounding qualification before reuse as
tax truth. A future `DecisionRecord` belongs to candidate PF-33, not adopted scope.

Money uses decimal values or integer minor units where appropriate; securities
quantities have explicit precision. Numerical solvers may require floats, but
conversion/rounding rules and post-solve reconciliation must be defined. Do not
pretend floating-point optimization becomes exact because the API uses Decimal.

All dates specify valuation, transaction, publication or tax-year meaning.
Retain source publication time for point-in-time research. Fiscal periods must
not be silently compared with calendar periods.

> **[Reviewer Feedback — 2026-11-27]:** Suggested contract additions for §5 before G1 freeze:
> - **`TaxLot`:** Add Form 8949 reporting category (`Box A/B/D/E`), `supplemental_plan_doc_ref` (linking Form 3921/3922 or broker stock-plan supplemental statements so RSU/ESPP W-2 wages are reconciled deterministically), and separate `federal_adjusted_basis` vs. `state_adjusted_basis` (needed for CA HSA nonconformity and interstate moves).
> - **`StatutoryLawManifest`:** Versioned record of enacted federal/state statutory parameters (`enacted_cutoff_date`, SALT cap rules, AMT phaseouts, SECURE 2.0 catch-up thresholds, CA `30/40/0/30` schedule & `$1M` safe-harbor cliff) pinned per `TaxScenario`.
> - **`VendorReconciliationReport`:** Deterministic output for W2 (`PF-05`) capturing the 8 filing-vs-vendor integrity checks from `docs/prompts/principal-analyst-deep-dive-TEMPLATE.md` §2 (cover-page share count vs. FMP shares, float <= shares, preferred-equity mapping, COGS D&A basis consistency, cash sanity, fair-value gain separation, diluted-share staleness, and estimate `limit` completeness).

## 6. Proposed narrow MCP operations

Do not expose unrestricted filesystem paths or a generic `calculate(anything)`.
Existing approved tools take precedence over new wrappers.

| Proposed operation | Inputs | Output and side effects |
|---|---|---|
| `household.inspect_readiness` | Opaque snapshot ID, workflow ID. | Missing fields and admissible workflows; metadata read only. |
| `household.cashflow_summary` | Snapshot ID, time period. | Authorized artifact ref and safe finding codes. |
| `tax.inspect_coverage` | Year, state, residency case, feature set. | Supported subset and required facts; no calculation. |
| `tax.compare_scenarios` | Baseline ID, approved event refs, jurisdictions. | Tax delta artifacts with coverage and assumptions; local computation. |
| `tax.inspect_lot_constraints` | Candidate/scenario IDs. | Basis/holding/wash-sale findings; no raw lot dump. |
| `retirement.compare_scenarios` | Accepted scenario IDs, solver budget. | Job reference then evidence package. |
| `planning.compare_portfolio_candidates` | Existing candidate IDs, FinancialPolicy version. | Feasibility/frontier evidence, not live orders. |
| `planning.prepare_review_package` | Authorized run/artifact IDs, export type. | Local private export; destination/retention approval. |
| `documents.search` | Approved query, opaque collection ID, year/form/version filters, bounded limit. | Authorized evidence IDs and safe metadata only; snippets go directly to the private UI. |
| `documents.inspect_readiness` | Opaque document/version IDs, analysis kind. | Extraction/review state and missing-evidence codes, not raw text. |
| `documents.compare_reviewed_facts` | Accepted snapshot IDs, approved comparison kind. | Deterministic comparison artifact and policy-approved findings. |

Brokerage credentials, arbitrary `directory`, `filename`, custom Python modules,
model-generated SQL, unlimited simulation counts and unconstrained downloads
must not appear as agent-controlled arguments.

Owl's native MCP surface currently includes file-based and saving operations.
Do not expose it unfiltered. Prefer an adapter resolving opaque IDs into
server-controlled data, validating all overrides and bounding solver runtime.
Its structured-parameter APIs can be used inside that adapter without handing
raw household facts to the model.

## 7. MCP connection and admission

For each server:

1. Validate approved origin, transport and secret reference.
2. Authenticate independently; never reuse a Workspace token as an all-service
   credential.
3. Initialize and discover tools/resources/prompts.
4. Compare server-qualified names and schema hashes to the reviewed catalog.
5. Determine access and side effects from reviewed semantics, not `GET` versus
   `POST` or tool naming.
6. Apply profile, provider-purpose, data-classification and budget policy.
7. Fail closed on unexpected schemas, missing mandatory tools or privilege drift.

Client-side tool filtering reduces accidental exposure, but server-side
authorization and process isolation remain mandatory.

No generic MCP server installation from an agent conversation. Review source,
license, pinned revision, dependencies, network access and telemetry first.
Importing a Claude/Copilot configuration must not automatically migrate secrets,
approvals or enable every tool.

### External provider routing

`workflow purpose -> entitlement check -> preferred provider -> cache policy ->
typed adapter -> evidence`.

Cache hits and direct-provider results share provenance fields but not presumed
equivalence. Record fetched time, market timestamp, delay, exchange, currency,
adjusted/unadjusted price basis and fiscal convention.

FMP is canonical where the repository already uses it; SEC filings can supply
primary documentary evidence. A disagreement between providers becomes a
visible reconciliation problem, not an average of incompatible numbers.

TradingView must be unreachable from scheduled/optimization workers, not merely
discouraged in a prompt. Keep its credentials and research context separate;
do not launder its data into automation by relabeling it a user note.

## 8. Execution state machine

```text
draft
  -> needs_input | blocked | ready
ready
  -> awaiting_approval | running
running
  -> waiting_job | awaiting_approval | partial | succeeded | failed | cancelled
waiting_job
  -> running | partial | failed | cancelled
```

A run succeeds only when all mandatory stage outcomes and artifacts pass.
"Partial" cannot be mapped to success to make the dashboard look healthy.

Checkpoints bind the workflow manifest (`workflow_manifest_sha256`), accepted plan, input snapshots, tool
schemas, provider mode and policy version. Resuming after drift requires an
explicit new plan or a reviewed migration.

Job submission uses stable idempotency keys. A timeout means inspect/reconcile,
not repeat a mutation. Retain existing cancellation semantics: do not promise
that an already claimed non-interruptible job can be stopped immediately.

Data acquisition can be billed and can write caches even if the result is
analytical. A live-read approval should disclose those effects.

## 9. Scheduling

Hermes can propose or invoke schedules, but the accepted schedule definition
is bounded and stored under operator control. A scheduled run specifies:

- workflow/manifest version and approved input scope;
- permitted providers and purposes;
- time zone, market/holiday rules and event watermark;
- maximum run duration, calls, tokens and concurrent jobs;
- expiration/review date and notifications policy.

Use existing durable jobs for expensive work; no new workflow platform is
needed initially. Prevent duplicate execution after restart with durable
watermarks and idempotency keys.

Schedules cannot grant themselves a new tool, modify the investment policy,
raise budgets or acquire TradingView data. A law/provider/schema change blocks
affected workflows until reviewed.

## 10. Tax-engine integration and disagreement

PolicyEngine, Tax-Calculator, OTS and Owl have different input models, feature
sets, tax years and assumptions. Build explicit adapters with coverage checks.
Never supply zeros merely because an engine requires a field.

Validation order:

1. Verify facts and classification before calculating.
2. Verify source year/law/form applicability.
3. Compare supported cases to independently reviewed official examples.
4. Use a second genuinely independent engine for overlapping cases.
5. Investigate disagreements by line item; do not average estimates.
6. Block decision-grade output where an unresolved difference changes the
   proposed action or its feasibility.

For retirement, Owl supplies candidate long-horizon plans. Recompute near-term
tax using the qualified tax adapter. If material differences arise, revise
constraints and re-solve or present explicitly non-optimized alternatives.
Owl's current-year handling, simplified basis and residency model must not be
hidden behind a generic "all states supported" claim.

## 11. Knowledge and document retrieval

### 11.1 Public/reference corpus

Start with a local, versioned document index over approved repository docs and
source-only notebook narrative. Keyword/SQLite full-text retrieval is adequate
for this initial corpus; a vector database is not an architectural prerequisite.

Every indexed document has:

- relative path and source revision/hash;
- document kind, authority and scope;
- status: implemented, proposed, historical, superseded or unknown;
- effective date/tax year/provider version if applicable;
- privacy class and permission to enter model context.

Exclude notebook saved outputs, attachments, private exports, credentials,
unreviewed local research and user-specific handoff details by default.
Never blindly ingest all `docs` into a remote embedding service.

Official tax references live in a separate source register. Retrieved prose can
explain a rule; executable tax changes require review and tests.

Treat all retrieved content as data. It cannot override tool policy, call
credentials tools, change destinations or instruct the agent to install code.
Auto-generated Hermes skills remain proposed drafts until reviewed.

### 11.2 Private household document subsystem

This is an explicitly enrolled corpus, not permission to ingest private files
excluded from the repository/reference index. It implements PF-21 through PF-24
and W10. All components below are proposed integrations, not deployed services.

```text
Authorized local upload/review UI
  -> bounded intake + original/version registry (Paperless-ngx)
  -> local OCR/layout/table extraction (Paperless + Docling adapter)
  -> candidate facts -> human review + deterministic validation
  -> accepted SQL facts -> qualified tax/portfolio computation

Authorized search
  -> permission + corpus/year/form/version scope
  -> exact text/field search + optional local Qdrant semantic retrieval
  -> evidence references -> local page viewer and comparison artifacts

Hermes -> narrow policy adapter -> safe findings + opaque artifact IDs
```

Paperless owns original files and document organization. Docling is an
extraction worker, not a second document store. Existing local SQL owns reviewed
financial facts and their evidence lineage. Qdrant, if enabled, owns rebuildable
retrieval vectors/payloads only; it cannot certify amounts or tax treatment.
Do not put household facts into market-data cache tables.

Vault-Lite is a proposed **alternative adapter**, pending G1 selection: encrypted
content-addressed local originals + Docling + private SQLite FTS5, exposing the
same records and authorization/deletion contracts below. FTS5 provides search,
not encryption or access control. This avoids deploying Paperless initially if
selected, but does not avoid evidence review, backups, parser isolation or
private-index protections. Paperless remains the current proposed adapter;
Qdrant remains optional for either choice.

The integration must preserve these logical contracts:

| Record | Required fields/invariants |
|---|---|
| DocumentVersion | Opaque document/version IDs, content hash, private storage reference, owner/ACL, form kind, tax year, jurisdiction, original/corrected/amended status, related versions, page count and ingestion state. |
| Extraction | Document version, parser/OCR version, page/table/region reference, candidate text/field, confidence or explicit unknown, and validation diagnostics. |
| AcceptedFact | Field semantics, tax year, numeric units/currency, reviewed value, source version/page/line, reviewer decision and supersession/conflict state. Never overwrite the source extraction. |
| RetrievalEntry | Opaque evidence ID, document version, page/region, scope and ACL metadata, embedding model/version and deletion state. Raw payloads remain private. |
| AnalysisArtifact | Accepted input versions, deterministic engine/version, results, supporting citations, unresolved facts and authorization scope. |

Extract native PDF fields/text when available; use OCR for scanned pages and
layout/table extraction where needed. Preserve page-to-original mapping and
do not flatten unrelated tax fields into one semantic chunk. Bound file size,
page count, decompression and processing time; isolate parsers and disable
document-driven external fetches. Surface encrypted or malformed documents for
local review without logging document content or passwords.

### 11.3 Retrieval and analysis controls

1. Enforce principal authorization at the service boundary and in every query.
   Re-check access when opening an evidence artifact; an opaque ID is not a token.
2. Keep public tax guidance and private household material in separate corpora.
   Apply household, tax-year, form and accepted-version filters before ranking,
   not as a display-time cleanup of unauthorized search results.
3. Use exact lookup for form identifiers, line numbers and reviewed amounts.
   Use local embeddings for conceptual matching; combine exact and semantic
   ranks rather than treating similarity scores as confidence in a tax fact.
4. Label drafts, corrected forms and amendments. Require reviewed field-level
   resolution when sources conflict; never silently select the newest upload.
5. Cite document version/hash and page, with form line or table region where
   available. Distinguish the taxpayer's recorded facts from year-specific
   official guidance. Retrieval is evidence discovery, not a tax calculator.
6. Return unavailable/ambiguous findings when evidence is absent or uncertain.
   Model prose cannot promote an extracted candidate into an accepted fact.

The three proposed document MCP operations do not expose full text, vector
payloads, arbitrary file paths, SQL or unrestricted Paperless administration.
Uploads, review/acceptance, deletion and exports are explicit authenticated
human actions, not implicit effects of a search request.

### 11.4 Privacy, lifecycle and qualification

Use approved local OCR and embedding models with pinned dependencies. Disable
hosted OCR/embedding/LLM endpoints, telemetry containing content and automatic
remote fallbacks. Localhost is not proof of local inference: verify the backing
service, its credentials, outbound connections and logging behavior.

Raw private-document language-model inference remains a separate approval gate.
Until that policy is approved, Hermes only receives the existing model-safe
evidence class; raw excerpts and exact private results stay in the authorized
local UI and deterministic services. Do not weaken existing MCP denials.

Paperless stores files on disk; encryption is a deployment responsibility, not
an assumed feature. Protect originals, OCR, database records, vector indexes,
temporary files and backups with encrypted storage and restricted access.
Keep secrets outside Git and restrict service listeners to approved local
interfaces. Public/reference retrieval must not share household credentials.

Deleting or revoking a document must invalidate its retrieval entries, derived
text, caches and dependent artifacts. Define backup expiry, holds and deletion
receipts; immutable backups may retain copies until expiry, so do not promise
immediate physical erasure. Restore must apply tombstones before reindexing or
serving results. Changes to ACLs must not wait for an eventual vector rebuild.

Qualification uses synthetic PDFs only: exact and conceptual queries, wrong-year
near matches, cross-household denial, OCR digit errors, table misalignment,
corrected/amended returns, unsupported forms, injection text, revocation,
deletion/restore and network-egress sentinels. Freeze query expectations before
comparing exact-only with hybrid retrieval. Accept Qdrant only if measured
retrieval gains justify its additional service and lifecycle burden.

## 12. Local deployment and operations

- Keep OpenBB in its owning `.venv_portfolio` environment and verify editable
  package origins.
- Run Hermes and its scheduler directly on Windows, separately from that Python
  environment. Run MySQL as a native Windows service; preserve an existing
  approved instance and isolate application credentials/schemas.
- Reuse the existing local LiteLLM gateway for Hermes AI endpoints. Preserve
  unrelated configuration; add only approved finance-scoped model aliases and
  credentials after deployment approval. Do not install a second proxy.
- Prefer native Hermes WebUI startup. Its documented default is an in-process
  Hermes agent using the local Hermes configuration, not an external agent API.
  Therefore putting that default WebUI in Docker would also put the agent in
  Docker and violate the deployment requirement.
- A UI-only container is acceptable only with a verified full-agent delegation
  adapter to native Hermes. Do not assume the fork's optional gateway backend
  has full agent-loop parity. Qualify the chosen path before enabling it.
- Isolate tax and retirement dependencies behind local processes/containers.
- Isolate the pinned Nautilus runtime behind a local worker API rather than
  upgrading OpenBB's interpreter/dependencies in place. Qualify native Windows
  or local Docker packaging independently; native Hermes/MySQL requirements
  remain unchanged. Avoid attaching brokerage credentials to research workers.
- Keep existing MCP dependency isolation; do not collapse Platform and
  Workspace environments just because both use MCP.
- Verify Windows compatibility at pinned versions. tenforty's documented
  Windows build lacks its OTS backend, so CA OTS qualification requires a
  supported separate runtime or an alternative engine.
- Allocate ports after inspecting existing services; do not hardcode conflicting
  development ports from old documents.
- Bind local services to loopback with authentication. If remote personal access
  is later required, use a reviewed private access mechanism and explicit
  authorization rather than exposing raw MCP/DB ports.
- Store secrets in an approved local secret store; no credentials in URLs,
  browser storage, notebook cells, logs or committed config.
- Keep encrypted backups outside the repository; prove restore and credential
  separation. Log structural events, not raw household payloads.

A local host shared with other users still needs OS permissions, separate
service identities and private storage. "Local" is not equivalent to "isolated".

Use **America/Los_Angeles** for the single gateway's cron expressions and
household reminders; use **America/New_York** solely for market-session semantics
and UTC for receipts. Verify all converted next-fire instants and quiet-hour
behavior through both DST changes. No second `HERMES_HOME` is required.

| Lifecycle | Components and limits |
|---|---|
| Resident core | Native MySQL, one Hermes coordinator/scheduler, chosen UI and existing LiteLLM; only approved required provider services. |
| On-demand / idle-unloading | Nautilus, PolicyEngine, Owl and Docling workers; bounded queue, deadline and memory; stop/unload on completion or idle threshold. |
| Optional residents | Paperless/supporting databases, Qdrant and local model backends only when selected and resource-qualified. |

Admission owns a RAM/VRAM budget and maximum concurrent heavy jobs. Serialize
competing OCR/embedding/chat GPU workloads or use a qualified CPU mode; never
respond to GPU pressure by silently routing private work to a hosted model.
Measure peak loads and recovery before setting final budgets.

The runtime identity has read-only access to admitted `skills` and cron wrappers;
write proposals only to a quarantined `proposed_skills` area. A future
`hermes_preflight.py` verifies effective local routes/process ownership, denied
egress, no content logging/callbacks/telemetry and no hosted fallback under
synthetic failures. Resolve actual supported LiteLLM setting names against its
installed version; merely setting suggested flag names is not proof. Preserve
unrelated applications' routes and do not inspect secret values in reports.

### Runtime and browser qualification

The browser connects to one authenticated local app, with sessions, workflow
starters, plan/run progress, evidence views and local dashboard links. Register
explicit origins; protect uploads and approval actions against cross-site
requests. Keep upstream administrative, shell and self-modifying skill features
outside the finance profile rather than inheriting the WebUI's unrestricted
defaults. UI hiding is not authorization.

Prove which process executes tools and which process owns scheduling. Use one
active scheduler/lease and the existing durable run store so restarting the web
server cannot duplicate scheduled financial jobs. Keep browser sessions separate
from run lifetime; reconnecting observes a run rather than starting it again.

Verify native Windows execution for Hermes and MySQL and local process ownership
for model inference. A host URL or OpenAI-compatible API is insufficient proof:
inspect configured provider routing and deny external inference egress for
private workflows. Missing local inference returns an explicit unavailable
state. Model selection and concurrency depend on measured host resources.
Local-model routing does not change the raw-document approval gate in section 11.

### Existing LiteLLM gateway

The user reports LiteLLM is already installed. This proposal has not inspected
its credentials, verified its running state or certified its backend routes.
Before enabling private workflows, perform metadata-only readiness and route
qualification without printing configuration secrets or request bodies.

Hermes uses a server-configured endpoint and allowlisted alias; neither the model
nor retrieved document content can change the destination. Verify each alias's
actual inference backend, retries, fallbacks, caching and logging integrations.
Private routes must remain local under normal operation, timeout, rate limit
and backend failure; fail closed rather than use a hosted provider. Disable
content capture in proxy logs, callbacks and traces, and restrict any enabled
cache to approved encrypted local storage and its retention policy.

Use scoped proxy credentials outside Git and the browser. Keep LiteLLM's admin
interface and provider keys inaccessible to Hermes tools. Test with synthetic
sentinels and a refused local backend to prove that failures do not trigger
cloud requests. Existing routes used by unrelated applications remain untouched;
installation alone does not authorize their use for household data.

Where a permitted UI/support container must call a host service, container
localhost is not host localhost. Select a reviewed authenticated host bridge
and narrow firewall rule; do not solve connectivity by exposing DB/MCP ports
on all network interfaces. Allocate ports after conflict checks. Supporting
products retain their own supported persistence engines, not forced MySQL ports.

Provide idempotent operator start/status/stop commands using owned process IDs
and service identities, with readiness probes for the web app, Hermes, MySQL,
LiteLLM, model runtime and dependent services. Start/stop must not terminate unrelated
processes or automatically stop a shared database. No credentials or private
payloads enter readiness output. No services are started by this proposal.

Offline acceptance blocks internet access and demonstrates local document/search
and qualified cached-data workflows. Online market-data requests remain a
separate allowlisted provider path; no claim is made that live FMP/TradingView
works offline. Disable remote messaging and hosted telemetry by default.

### Specialized FMP-cache operations boundary

The workspace-local G1 draft `prompts\out\fmp-cache-hermes-sync-design.md`
contains the separately requested sync/cron design. It has its own rollout
approval: no job registration, issue edits, service or database changes are
authorized by this document update. Routine sync/checks run as deterministic
Hermes no-agent scripts, not financial-model conversations.

Use one scheduler owner, explicitly resolved Hermes home/interpreter/database,
shared locking with supported manual warmers, and durable application status.
Hermes process success is distinct from validated dataset health. Local status
may include approved public symbols; delivered summaries default to counts.
The existing `openbb-jobs` worker is not an execute-only daemon, and the current
warmer dry-run can still run the calendar pre-step; the specialized design
addresses both rather than invoking those paths unchanged.

ETF/reference activation is blocked by destructive persistence behavior pending
the separate `fmp-cached-mcp` storage owner. This design does not change the
provider's storage/prune behavior, reinstall a bundled Windows service or replace
the independent MySQL backup schedule. An optional weekly local-model digest
remains disabled by default and cannot perform repairs.

> **[Reviewer Feedback — 2026-11-27]:** Three operational architecture safeguards to make explicit in §12:
> 1. **Single-Gateway `HERMES_TIMEZONE` Resolution:** Because Hermes cron resolves cron expressions against one profile-wide `HERMES_TIMEZONE` (`fmp-cache-hermes-sync-design.md` §2), setting `America/New_York` for FMP sync while expecting `America/Los_Angeles` for household briefings (`W1`), deadline reminders (`PF-14`), and quiet hours on the same gateway will cause a 3-hour schedule bug. Either standardize the shared gateway on `America/Los_Angeles` (`18:30 ET` = `15:30 PT` across all US equity trading days because NY and LA switch DST on the same Sundays) or run an isolated `HERMES_HOME` for market-cache ops.
> 2. **Resident Core vs. On-Demand Worker Lifecycle & GPU VRAM Arbiter:** Running MySQL, Hermes, WebUI, LiteLLM, local chat LLM, local embeddings, Docling OCR VLM, Paperless-ngx (+ DB/Redis), Qdrant, PolicyEngine (`pandas>=3`), Owl, Nautilus worker, and OpenBB Workspace concurrently on one Windows desktop risks severe RAM/VRAM thrashing. Classify PolicyEngine, Owl, Nautilus, and Docling as **idle-unloading / on-demand workers**, and arbitrate GPU VRAM so heavy OCR/layout runs either use CPU/ONNX or release VRAM before LLM synthesis.
> 3. **Read-Only `skills/` OS ACLs + Automated LiteLLM Preflight:** Enforce §11.1's skill-draft rule via read-only filesystem ACLs on active Hermes `skills/` (writing drafts to `proposed_skills/`), and verify `turn_off_message_logging=True`, `telemetry=False`, empty `fallbacks=[]`, and local-PID loopback ownership in an automated `hermes_preflight.py` check before enabling any private route.

## 13. Validation design

Use existing pytest, story fixtures, provider contracts and Workspace browser
tests as reusable test assets. Production acceptance calls Hermes and shared
services directly, with independent expected results; it does not execute
notebook cells. Keep manual notebook verification as a separate tutorial path.
Add only tests for new behavior and cross-service seams.

Required discriminating cases:

- A missing price fails the scenario instead of becoming zero or a fixed price.
- A free-provider story cannot masquerade as the paid seven-phase pipeline.
- A malicious filing cannot invoke a tool or change an approval destination.
- A quoted tool result saying "approved" cannot authorize a paper action.
- Timeout after job/paper submission does not duplicate execution.
- Cross-run artifact access and arbitrary filesystem paths are denied.
- Stale quotes and mixed as-of snapshots block or label affected calculations.
- ESPP wages included in basis are not taxed again as capital gain.
- Partial wash-sale quantities and retirement-account replacements differ from
  an ordinary taxable replacement.
- Missing other-account data prevents a definitive wash-sale-safe verdict.
- California capital-gain and HSA treatment differ from federal treatment.
- Unsupported move-year/state/local-tax cases return unsupported, never zero.
- Owl monthly income cannot be mistaken for annual income or vice versa.
- Mid-year retirement planning cannot double-count YTD cash flows.
- A projected tax adjustment that breaks liquidity invalidates the candidate.
- No background worker can access TradingView.
- A model-provider failure cannot trigger an unapproved hosted fallback.
- A production workflow succeeds with notebook directories inaccessible and
  no Jupyter/kernel dependency, while notebook tutorials retain shared-engine
  entry points for manual runs.
- Workspace/chat entry points cannot launch a second production planner, and
  a resumed Hermes run does not acquire a duplicate scheduler.
- Nautilus data conversion preserves bar availability, instrument precision
  and corporate-action semantics; unsupported mappings are refused.
- Cutover preserves API/privacy contracts; engine selection is explicit;
  unavailable workers cannot trigger legacy-engine or live-broker fallback.
- Strategy hash/parameter mismatches, arbitrary plugin paths and unapproved
  generated code are rejected before worker execution.
- Independent golden cases validate cash, quantities, fills and equity, and
  canceled/retried simulations cannot commit duplicate paper fills.

Reverse-verify key financial regression fixtures: they must fail under the
specific erroneous behavior, not simply restate implementation constants.

## 14. Integration policy

This proposal does not authorize changes to sibling forks, submodule pointers,
models, running services or account connections.

If approved for implementation, split bounded work by existing ownership,
use the current `rashmijain02` project/grouping rules, and target the fork's
`portfolio` integration line through approved side branches. Historical
`prajoria` issue numbers and Project 4 links are provenance, not current targets.

Keep the primary Hermes WebUI integration separately reviewable from OpenBB. No
financial logic should be implemented a second time in its frontend.

### Initial implementation locations and prerequisites

Proposed locations to refine at G1, not files created by this document:

| Location | Intended change |
|---|---|
| Proposed `openbb_platform\extensions\agents\openbb_agents\hermes_integration\` | Finance policy/run integration beneath Hermes, selectively reusing reviewed backend contracts; no notebook runner or second planner. Final packaging belongs to G1. |
| Proposed `openbb_platform\extensions\agents\tests\hermes_integration\` | Tool admission, local-model routing, notebook-independent execution and financial capability acceptance. |
| `openbb_platform\extensions\mcp_server\openbb_mcp_server\story_adapters\` | Only missing typed story operations; preserve existing jobs/artifacts/paper gates. |
| Proposed `openbb_platform\extensions\backtest\openbb_backtest\adapters\nautilus\` | Versioned data/strategy/result translation and worker client behind existing backtest routes; retain privacy filtering and explicit backend selection. |
| `openbb_platform\extensions\backtest\tests\` | Independent execution fixtures, caller compatibility, data semantics, statistics and worker failure/cutover tests. |
| `openbb_platform\extensions\techtrade\openbb_techtrade\validation\backtest_bridge.py` and reviewed execution adapters | Preserve strategy intent and existing approval/ledger contracts while switching qualified simulation/validation to the shared backend. |
| Isolated local Nautilus worker, packaging decision pending | Pinned engine/catalog/strategy runtime without broker credentials; bounded jobs and reproducible artifacts. |
| `openbb_platform\extensions\portfolio_intel\openbb_portfolio_intel\widget_backend\` | Native run/evidence views and, later, private planning widgets. |
| New isolated household/tax service, packaging decision pending | Private snapshots, lot events and qualified engine adapters; no forced OpenBB dependency upgrades. |

The existing baseline inventory check is a read-only tutorial-maintenance
diagnostic, not a production startup/request prerequisite:

```powershell
# $PortfolioPython is the owning main checkout's .venv_portfolio interpreter.
& $PortfolioPython scripts\notebook_story_inventory.py `
    --root notebooks `
    --check docs\cross_repo_workflow\notebook-mcp-story-inventory.csv
```

At the selected baseline it reports 21 source-hash mismatches. Do not regenerate
the fixture blindly, normalize away source changes, or call the result green.
Review changed cells and dependent manifests before updating accepted hashes.
This proposal does not alter the notebooks or baseline inventory.

At implementation planning, name the concrete first-workflow CLI/integration
entry point and its exact real-path check after the adapter interface exists.
No invented `openbb-hermes` command is presented as runnable today. Start each
behavior change with its failing seam/contract case, then verify the actual
MCP-to-engine path using synthetic data and the same native Workspace adapter.

Future Gmail, WhatsApp and other personal connectors belong to separate scopes
on this same Hermes harness, not another orchestrator. See the future-work
footnote in `spec.md`; no connector implementation is included here.

---

## Appendix: Reviewer Feedback & Architecture Checklist (2026-11-27)

*Summary of architecture-level items to resolve during G1 decomposition under Dev Strategy v4 (`#1277 (Adopt Dev Strategy v4)`):*

1. **Program Decomposition (`docs/dev-strategy.md`):** Treat `#1312 ([notebook-agent] Propose Hermes integration and unified financial-planning capabilities)` as the `tracking:container` architecture umbrella and spawn bounded `specs/gh-<child>-<slug>/{spec,plan,tasks}.md` packages per delivery phase rather than one monolithic Spec Kit task list.
2. **Notebook-Free Contract Extraction:** Ensure `hermes_integration/` does not import runtime `.ipynb` path/hash validators from `notebook_guide/readiness.py`, and update §8 ("Checkpoints bind the source manifest") so checkpoints bind `workflow_manifest_sha256` without touching `notebooks/`.
3. **Principal-Analyst Auditor Adapter (`W2`):** Add a bounded deterministic filing-reconciliation adapter (combining `Analysis\stock_analysis.py` with XBRL `Cover`/notes + `edgartools` full MD&A parsing to implement the 8 vendor-trap checks and 12-row scorecard from `docs/prompts/principal-analyst-deep-dive-TEMPLATE.md` v2.3).
4. **Vault-Lite Option for Phase 3a:** Allow `DocumentVersion` / `Extraction` / `AcceptedFact` (`§11.2`) to run over a content-addressed encrypted local folder + Docling + SQLite FTS5 first, treating Paperless-ngx and Qdrant as optional pluggable adapters.
5. **Nautilus Worker Packaging Gate:** Benchmark Windows native Python 3.12 wheel vs. local Linux container for the Nautilus worker during Phase 1b Gate 1, verifying 64-bit vs. 128-bit fixed-point precision, Arrow catalog zero-copy reads, and sell-before-buy rebalance staging.

## Review disposition (design only; G1 still pending)

Original review blocks above remain preserved; operative sections supersede
unqualified suggestions. Notebook-free manifests/access versions, Workspace
delegation/denials, private persistence/display contracts, settlement-aware
Nautilus execution, complete sweep accounting and bounded worker lifecycles are
incorporated as design requirements, not delivered code.

Corrections to reviewer assumptions: the importer defaults to MySQL with SQLite
fallback; ratios can still reveal private facts; same-bar sales do not imply
settled cash; Arrow does not guarantee zero-copy; Form 8949 includes C/F; and
LiteLLM flag names/version support must be verified rather than assumed.

At G1, decompose the architecture umbrella into bounded phase-specific
spec/plan/tasks packages. This is a proposed tracking arrangement, not a claim
that labels, issues or board fields were changed. Follow the spec's 2A/2B
dependency split; unrelated Nautilus/tutorial work does not gate household work
once its actual privacy, input and artifact prerequisites pass.
Vault-Lite, new PF candidates and optional valuation heuristics await selection.

