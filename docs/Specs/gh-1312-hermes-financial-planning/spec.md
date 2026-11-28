# OpenBB + Hermes: Personal Financial Intelligence

**Status:** Research-backed proposal, not an implementation or deployment approval.
**Research date:** November 26, 2026, Pacific time.
**Audience:** One person's private financial assistant; no commercial service.
**Tracking:** [#1312 (Hermes integration and unified financial-planning proposal)](https://github.com/rashmijain02/OpenBB/issues/1312).
**Baseline:** `origin/portfolio` at `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7`.
**Branch:** `docs/hermes-financial-planning-gh-1312`.
**Companions:** [Architecture](plan.md) and
[existing-capability coverage and open-source research](research.md).

This is a pre-G1 product proposal, not a completed implementation-ready Spec Kit
relay. Feature-level task decomposition and implementation approvals follow
product-direction review. The dedicated worktree was created at the user's
explicit request; the original checkout and unrelated work remain untouched.

## 1. Recommendation

**Review reconciliation (November 27, 2026):** document changes only; G1 remains
unapproved. Original reviewer quotations and appendices are preserved as review
history. The operative requirements and the disposition section below distinguish
incorporated clarifications from proposals still requiring an owner decision.

Build an **AI-native personal financial cockpit on the existing OpenBB fork**.
Use **Hermes WebUI as the primary chat-first app**, **Hermes Agent as the sole
production orchestration harness**, and existing OpenBB MCP services as
the financial execution layer. Keep **native OpenBB Workspace for detailed
analytical dashboards**, reached from the Hermes app.

The user-approved deployment direction is one-machine local hosting: Hermes
and MySQL run directly on Windows, private inference runs locally, and suitable
supporting services may use local Docker. This approves the proposal direction,
not installation, unrestricted tools or access to private data.
Reuse the existing local LiteLLM installation as the shared AI endpoint gateway;
its installation is user-reported, while routing and readiness remain to verify.

Preserve Portfolio Intelligence, TechTrade, the OpenBB backtest API,
`fmp_cached`, the durable job service and approval/artifact infrastructure.
Adopt NautilusTrader as the target standardized strategy and event-driven
backtesting foundation behind those interfaces, replacing overlapping in-house
execution simulation after qualification rather than rebuilding it.
Retain notebooks and their source inventories as tutorials and
manual-verification assets, not a production execution harness. Complete the
engine-to-Hermes workflow connections and add a bounded household/tax layer.

The system should act as:

| Role | Intended outcome |
|---|---|
| Personal financial advisor assistant | Connect goals, cash flow, liabilities, investments, taxes, retirement and uncertainty into an explainable plan. |
| Portfolio manager assistant | Monitor exposures, research holdings, compare changes, produce tax-aware proposals and validate them in simulation. |
| Tax-planning assistant | Estimate federal and state consequences, reconcile investment tax inputs, compare lawful scenarios and prepare a review package. |
| Research analyst | Reproduce the repository's analytical stories and create source-linked research, not merely summarize news. |
| Financial operations assistant | Track missing information, stale evidence, deadlines, approvals and reproducible reports. |

These are **decision-support roles**, not claims of professional licensing,
fiduciary status, guaranteed returns, or a validated tax-filing product.
Actual trades, transfers, elections, filings and payments remain with the user
and, where needed, a CPA, EA, attorney or licensed advisor.

### Smallest coherent technology stack

1. **Keep:** OpenBB Platform, Portfolio Intelligence, TechTrade, backtesting,
   FMP Cached, MySQL, existing private import/storage boundaries and Workspace.
2. **Connect:** Hermes to reviewed MCP capabilities through a finance-specific
   policy adapter; reuse typed backend contracts while retaining notebook
   manifests for reference and coverage tracking only.
   Use a versioned NautilusTrader adapter beneath the OpenBB backtest interface;
   Hermes remains the only assistant harness.
3. **Add after qualification:** PolicyEngine US for household tax scenarios.
4. **Add after qualification:** Owl for long-horizon retirement and withdrawal
   optimization, with explicit limitations and independent tax checks.
5. **Optional:** Actual Budget as a cash-flow source, not a replacement portfolio
   database.
6. **Use selectively:** existing FinanceToolkit and SEC/EdgarTools capabilities.
7. **Keep separate:** TradingView MCP for permitted personal, interactive research.

**Do not install all the evaluated products.** A collection of dashboards and
agent frameworks would create more reconciliation work than it removes.

## 2. What already existed

### Was there a Hermes-based proposal?

**Related Hermes product work exists; a unified Hermes/OpenBB financial-advisor,
portfolio-manager and US tax-planner proposal was not located in the searched
evidence.**

Evidence searched:

- OpenBB `docs`, notebook documentation and instruction material for Hermes
  references, followed by a fresh search of `docs`, `notebooks` and `specs`
  on the selected `portfolio` baseline.
- Local Git commit messages across available refs, and OpenBB GitHub issue/PR
  searches for Hermes.
- Available local conversation history covering the previous 90 days, with
  targeted financial/Hermes searches.
- The existing `rashmijain02/multi-lora` Workshop Hub plan, fetched from GitHub.

What was found:

| Prior work | Relevance | What it does not prove |
|---|---|---|
| `multi-lora\ux-workspace\PLAN.md` | Hermes WebUI extension, manifest-driven hub, authenticated local sidecar and staged execution plan. Phase 1 is documented as built. | A financial product or financial calculation correctness. |
| Earlier PersonaDesk/Hermes WebUI planning in session history | Prior consideration of personalized workbenches and extending the user's WebUI fork. | Current installed behavior or permission to reuse personal datasets. |
| OpenBB Notebook MCP Companion requirements/design | Reusable prior design for typed workflows, MCP execution, artifacts, approvals, jobs and local-model policy. | A completed Hermes integration or authorization to retain a second production harness. |
| OpenBB Google ADK agent proposal | Portfolio Q&A, research, import assistance, cache stewardship and ESPP planning were envisioned. | All five agents being implemented. The current README says only one Q&A agent and two MCP tools are implemented. |
| Native Workspace Terminal plan | Existing direction for a complete native Portfolio/TechTrade UX. | All widgets being live, correct or browser-certified today. |

Searches are not proof that no other proposal exists in another checkout,
private note, unindexed conversation or unsearched branch content. This proposal
is a consolidation of located work, not a claim to have recovered a missing file.

### Important baseline corrections

- The authoritative baseline is freshly fetched `origin/portfolio` at
  `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7`. The local `portfolio` ref was
  48 commits behind, so the new documentation worktree uses the fetched branch
  rather than that stale local ref. No integration branch was modified.
- There are **25 notebooks under `notebooks`**, representing **17 story
  families**, plus **11 additional notebooks under `docs\examples`**.
  The full requested inventory is therefore **36 notebook files**.
- On the selected baseline, the existing source-only inventory check finds all
  25 main notebooks but reports **21 source-hash mismatches** against its stored
  inventory. The known narrative-in-code cell remains classified, with no new
  unclassified parse diagnostics. Reconcile the inventory before claiming
  current parity; no notebook execution was performed.
- There are **251 Markdown documents under `docs` on this baseline**. This is
  an inventory count, not a claim that every document was read line by line.
  Supplemental untracked research/Kite documents seen in the original checkout
  are not treated as part of `portfolio`.
- Current reviewed MCP coverage documentation reports **181/181 FMP Cached
  model registrations routed**, split into **123 dedicated/persistent and
  58 non-persistent fallback registrations**. Older reports saying 70/181
  are historical, not the best current baseline.
- Routed models, callable tools, complete stories and live readiness are
  different measurements.
- Older references to root `Tools\` are stale for the inspected ESPP/cost-basis
  utilities. Their current location is
  `openbb_platform\tools\portfolio_utils\portfolio_utils\`.
- Native widget contracts, data-state/provenance, app grouping, TechTrade
  rendering and selected-widget agent context now have implementations on
  `portfolio`. Reuse them; do not plan to build them from scratch.
- The current development convention is `specs\gh-<NN>-<slug>\`, defined in
  `docs\dev-strategy.md`. The older `docs\Specs` organization rule is archived.
  At the user's explicit direction, this proposal instead lives in
  `docs\Specs\gh-1312-hermes-financial-planning\` within its dedicated worktree.

## 3. Scope and interpretation

The request is interpreted as **US federal + California first, then other US
states and DC**. No actual residency, filing status, age, income, holdings,
account ownership or goals are inferred.

The initial product is single-user, local-first, Windows-compatible and
read-only by default. A household may contain multiple people and accounts,
but that does not make the product a multi-tenant service.

### What "everything in notebooks and docs" means

Every source gets a disposition; not every document becomes an executable tool.

- **Analytical stories:** reproduce their required outcomes and artifacts.
- **Product specifications:** maintain a requirement-to-capability map, including
  requirements not yet implemented.
- **Provider/architecture documentation:** searchable evidence and contracts.
- **Operational runbooks:** explain/diagnose by default; privileged actions remain
  outside ordinary financial workflows.
- **Historical plans and handoffs:** retain as historical context, with explicit
  supersession and missing-file markers.
- **Research reports and prompts:** reusable analytical structures and evidence,
  never live market truth or executable instructions.
- **Templates and environment tutorials:** classify explicitly rather than
  pretending they are missing financial calculations.

The analytical capabilities illustrated by the 25 main notebooks remain in
scope. The 11 documentation notebooks form a second reference track;
setup/login cells remain guided instructions, not automatic credential access.
Capability parity means equivalent reviewed calculations and artifacts through
Hermes, not execution of notebook cells or duplication of their chapter order.

### Notebook role versus production runtime

Keep both surfaces with deliberately different responsibilities:

| Surface | Responsibility |
|---|---|
| Notebooks | Learning, tutorials, hands-on experiments and human-run verification against shared engines. Preserve them for ongoing manual testing. |
| Hermes | The only production assistant harness: intent handling, bounded planning, approved tool use, scheduling, run coordination, recovery and user interaction. |
| OpenBB and deterministic services | Financial calculations, validation, policy/approval enforcement, durable jobs and evidence. These are tools/services, not competing assistant harnesses. |
| Workspace | Detailed dashboards and authorized artifact display; no separate production planner or scheduler. |

Production workflows must run without Jupyter, a notebook kernel, `.ipynb`
files, saved cell outputs or chapter-order state. Reuse shared library/MCP
implementations instead of translating or executing notebook cells. Existing
story manifests can inform reviewed workflow definitions and regression
fixtures, but notebook files and their inventories are not runtime prerequisites.
Notebook maintenance remains useful even when production services are healthy.

Automated production acceptance exercises Hermes-to-service paths with
independent synthetic expected results. Manual notebook checks supplement
those tests; neither notebooks nor another LLM certify production correctness.

The live provider rule remains `fmp_cached` first with tracked FMP fallback,
not live yfinance. Preserve the eight `portfolio_yfinance` stories as distinct
source/fixture acceptance cases. Any live execution of that track requires an
explicit provider-policy decision; it is not silently authorized by this plan.

### Intended change to earlier product boundaries

The old ADK agent explicitly excludes investment advice; the Portfolio
Intelligence PRD excludes a tax engine. This proposal deliberately adds
**reviewable planning suggestions and deterministic tax scenarios in a new
product layer**. It does not silently change the guarantees of those existing
agents or expose their denied raw-data routes.

Hermes is the sole production harness for financial support and the future
broader personal assistant. This supersedes any earlier plan for a separate
Notebook Companion agent loop; retain useful contracts and backend tools, not
a second runtime. It is not justification to add LangGraph, AutoGen, n8n or
another orchestration platform. This specification implements financial support
only; broader personal integrations remain future work.

## 4. Product principles

1. **Software calculates; models explain and coordinate.** Tax, cash-flow,
   performance, risk and optimization outputs come from reviewed tools.
2. **One financial truth, multiple views.** Do not maintain competing position
   books in OpenBB, a new tracker and Hermes memory.
3. **An answer is an evidence package.** Preserve input versions, timestamps,
   calculation versions, assumptions, limitations and reproducible artifacts.
4. **No silent substitution.** Missing price is not zero; missing basis is not
   purchase price; missing tax data is not an assumed middle tax bracket.
5. **Approval is a server-enforced capability.** A model saying "approved" is
   not approval.
6. **No automatic data-rights expansion.** Personal use does not waive market
   data terms, software notices or third-party rights.
7. **Partial is a real state.** Unsupported tax cases or unavailable providers
   stay visible and cannot count as successful coverage.
8. **Learning improves procedure, not law or authority.** Hermes may propose
   better research skills; it may not rewrite tax rules, risk limits or approvals.

## 5. Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| PF-01 | Guided household intake with goals, horizons, liquidity needs, account types, liabilities and explicit missing facts. | No personalized recommendation before its required facts are supplied and confirmed. |
| PF-02 | Consolidated balance sheet and cash-flow view. | Transfers are not income; assets, debt and cash reconcile to accepted snapshots. |
| PF-03 | Hermes coverage of the financial capabilities illustrated by all 25 main notebooks. | Independent service-level expected outcomes and artifacts, with controlled Hermes replay; notebooks remain tutorial/manual-verification references, not executable production plans. |
| PF-04 | Explicit qualification of all 11 `docs\examples` notebooks. | Each source maps to analytics, explanation, setup-only or template classification. |
| PF-05 | Seven-phase single-name analysis and research memo. | Actual `Analysis\stock_analysis.py` pipeline, all phases and gate diagnostics retained. |
| PF-06 | Look-through, concentration, risk, attribution and catalysts. | Existing Portfolio Intelligence calculations; coverage and as-of alignment disclosed. |
| PF-07 | Tax-aware portfolio proposals. | Compare do-nothing, contribution-first and sale-funded alternatives; account constraints and tax deltas visible. |
| PF-08 | TechTrade scans, validation, tuning, batches, workbooks and paper fills. | Preserve strategy intent, approvals and separate Portfolio/TechTrade ledger semantics; qualify Nautilus-backed simulation behind the existing interfaces without duplicate fills. |
| PF-09 | Federal + CA annual tax projection for qualified scenarios. | Versioned tax-year rules, documented input coverage, independent reference checks. |
| PF-10 | State comparison and residency planning. | Separate state, tax-year, form, residency and income-type support; no unsupported zero-tax outputs. |
| PF-11 | Equity compensation and investment-lot analysis. | Adjusted basis, wages, capital gains, dates and state sourcing reconciled rather than inferred. |
| PF-12 | Retirement, withdrawals, Roth-conversion and Social Security scenarios. | Solver limitations, assumptions, units, current-year reconciliation and validation disclosed. |
| PF-13 | Goal planning: emergency reserves, debt, education, major purchases and charitable giving. | Inputs and constraints explicit; specialist cases referred rather than fabricated. |
| PF-14 | Scheduled monitoring and deadline reminders. | Only approved providers; bounded frequency/cost; no TradingView background data collection. |
| PF-15 | Evidence-backed document Q&A. | Source path/section/revision, authority level and supersession available for material claims. |
| PF-16 | Native Workspace dashboards and conversational access. | Same backend run/evidence IDs from Workspace and Hermes interfaces. |
| PF-17 | Resume, cancel, reconcile and replay. | Lost replies cannot duplicate a job, paper mutation or published artifact. |
| PF-18 | Private financial data remain in approved local services. | No raw lots, tax documents or credentials in model memory, provider requests or remote telemetry. |
| PF-19 | Export a private decision/CPA package. | Deterministic calculation tables, open questions, evidence links and explicit exclusions. |
| PF-20 | Visible service, entitlement and coverage health. | Configured, authenticated, discovered, admitted, callable and qualified are distinct states. |
| PF-21 | Private document vault for IRS/state returns, W-2s, 1099s, brokerage statements, receipts and other approved documents. | Originals preserved outside Git; OCR, versions, document hashes, access control and encrypted backup/restore verified. |
| PF-22 | Hybrid document search with exact-field and semantic retrieval. | Permission, household, tax-year, form and version filters apply before retrieval; results cite the exact document version/page and form line where available. |
| PF-23 | Reviewed document-to-financial-fact extraction and cross-document analysis. | Extracted values remain candidates until validated; accepted facts retain source evidence, units, corrections and review status; calculations use deterministic services. |
| PF-24 | Private document lifecycle and model-boundary enforcement. | No document text or embeddings reach hosted services; revocation/deletion covers derived indexes, caches and exports, with an explicit backup-retention policy. |
| PF-25 | One local chat-first Hermes web app for all admitted financial workflows. | Browser chat, workflow selection, plan/run progress, human approval, document review and evidence navigation use the same backend run IDs; detailed dashboards open in native Workspace. |
| PF-26 | Native Windows Hermes and MySQL with local inference through the existing LiteLLM gateway for private workflows. | Runtime/process provenance, authenticated readiness, approved LiteLLM alias/backend mappings and outbound-denial checks demonstrate native agent/DB execution and no hosted inference fallback; unavailable local models fail visibly. |
| PF-27 | Hermes is the only production assistant harness; notebooks remain available for learning and manual verification. | A browser-to-engine workflow succeeds with notebook files and kernels absent; no Notebook Companion/Workspace agent loop is invoked; tutorial and production paths reuse the same financial libraries. |

> **[Reviewer Feedback — 2026-11-27]:**
> 1. **Workspace `/query` Coexistence (`PF-16` vs. `PF-27`):** `PF-27` requires that *"no Notebook Companion/Workspace agent loop is invoked,"* while §6 states that native Workspace retains `agents.json` and its `/query` streaming contract (`openbb_portfolio.copilot` from `#1272 ([portfolio-ux] Align Workspace agent capabilities)`). Explicitly clarify whether Workspace's `/query` endpoint will be **proxied into the native Hermes run coordinator** (recommended so clicking "Ask Copilot" inside Workspace shares the single Hermes brain and local LiteLLM policy) or **disabled in the production profile** so an external-provider model loop cannot remain active alongside Hermes.
> 2. **Requirement Numbering Alignment:** Preserve `PF-27` here for Harness Independence; if any candidate tax/wealth capabilities from companion reviewer input [recommendations.md](./recommendations.md) are adopted at G1, assign them `PF-28+` to avoid ID collisions.

## 6. User experience: Hermes front door, native Workspace dashboards

**Primary UI: a locally hosted Hermes WebUI app in the browser.** Provide a
simple conversational entry point comparable in interaction style to familiar
desktop AI chat apps, without claiming feature parity with those products.
Native OpenBB Workspace remains the detailed financial dashboard. Reuse its
widget backend, `widgets.json`, `apps.json`, `agents.json` and supported
streaming/query contract. Do not embed the standalone Local Viewer as the shell.

In this product's production profile, Workspace `/query` must delegate to the
same native Hermes coordinator and local-inference policy. Until that adapter
is qualified, disable Workspace's conversational endpoint in this profile while
keeping its dashboards available. Do not retain an independent external-provider
copilot loop. Unrelated existing profiles are not changed by this proposal.
Private and unknown-classification widgets remain server-side denied to external
model context, even if a client selects them or sends a handcrafted query.

The existing Native Workspace plan describes 61 widget definitions, three app
templates, a 12-tab Portfolio Terminal and a six-tab TechTrade Desk. Treat those
as its documented baseline, not newly measured runtime counts.

The selected `portfolio` baseline also contains the native-workstream
implementations and handoffs: the agent has a 61-widget inventory with 59
readable widgets and two denied widgets; selected data are bounded and checked
by origin. TechTrade's handoff reports zero remaining manifest debt under the
strict validator. These are repository-recorded results, not a new live browser
verification. The new product must extend this work rather than repeat it.

The existing selected-widget agent can send data to its configured external
model provider. It is not automatically the new product's private tax channel.
Keep household/tax artifacts on the stricter local-display/model-safe boundary
in the architecture.

### Proposed navigation

| Area | What the user sees |
|---|---|
| Today | Material changes, unresolved facts, upcoming events and requested approvals; quiet when nothing needs attention. |
| Household | Net worth, cash runway, debts, recurring flows and account reconciliation. |
| Portfolio | Existing holdings, look-through, risk, attribution and scenario widgets. |
| Research | Existing seven-phase deep dives, documents, thesis history and contrary evidence. |
| Tax Center | Federal/CA estimates, realized gains, basis exceptions, compensation events and jurisdiction coverage. |
| Retirement & Goals | Sustainable spending scenarios, withdrawals, Roth conversions, goal funding and stress tests. |
| TechTrade | Existing desk, validation gates, paper orders, fills and replay. |
| Runs & Evidence | Stage status, artifacts, provenance, assumptions, approvals and provider failures. |
| Connections & Coverage | MCP health, capabilities, data rights, package versions and unavailable features. |

Expose these areas as workflow/navigation entries in Hermes, with run/evidence
cards and links to the appropriate native Workspace views. Detailed financial
views should use native app tabs/widget types where supported. Do not rebuild
Portfolio or TechTrade tabs as a second charting application.

The Hermes shell needs conversation history, reviewed workflow starters,
visible tool/run status, cancellation, approval links, document intake/review
links, citations, artifacts and connection/model health. These are integration
requirements, not claims that the current WebUI fork already provides every
financial interaction. Private artifacts open through authenticated local
views; they must not be serialized into ordinary chat history.

### Agent interaction

A request first becomes a **plan preview**, showing:

- the financial question and selected story/scenario;
- required inputs, missing facts and as-of dates;
- proposed tools, data destinations, provider costs and runtime budget;
- read versus write effects;
- expected tables, charts and report artifacts.

Results show **Facts / Calculations / Assumptions / Interpretation / Limitations /
Possible next actions** separately. Suggested actions have before/after metrics
and a do-nothing comparator. A generic green "success" badge is insufficient.

Exact private monetary values can be rendered locally in authenticated widgets
without placing those values in an LLM prompt. The model can reference opaque
scenario IDs and safe finding codes; the UI joins authorized numeric artifacts
for the user.

Use a field-level, local-only evidence projection for useful explanations.
Public statutory rates and approved coarse ratios, constraint breaches or
dominance flags may be included; household-derived percentages, weights and
holding-period signals are still sensitive, not automatically anonymous.
Exact amounts, quantities, identifiers and raw excerpts remain excluded.
Each derived field needs a purpose, precision bound and inference-risk review;
the conservative default is a finding/category rather than exact weights.

Structured references such as `[[metric:run_id:artifact_id:field_key]]` are
resolved by the authenticated browser directly against the private artifact
service. They confer no access by themselves. Reauthorize principal, run,
artifact and allowlisted field, and keep hydrated values out of model requests,
conversation persistence, telemetry and unapproved exports.

> **[Reviewer Feedback — 2026-11-27]:** Prevent **"Opaque Numeric Blindness"** by distinguishing two non-PII analytical tiers: (a) keep exact dollar balances, share counts, tax liabilities, and account/taxpayer identifiers out of LLM context (`Tier 0`), while (b) explicitly permitting **dimensionless ratios and bounded domain signals** (`%` portfolio weights vs. IPS caps, `bps` tracking-error deltas, statutory marginal tax-rate `%`, holding-period days to LTCG, and Pareto-dominance flags) in local-only LLM context so Hermes can genuinely explain *why* one scenario dominates another rather than expanding canned text. Pair this with a concrete inline hydration token syntax (e.g., `[[metric:run_id:artifact_id:field]]`) resolved directly between the browser UI and the authenticated local artifact service.

### Hermes WebUI integration

Reuse the user's Hermes WebUI fork as the **required primary conversational
surface**: run cards, workflow catalog, approval links, document-evidence links
and drill-through to native Workspace. The Workshop Hub's manifest/sidecar
pattern is useful prior art.

Prove the first end-to-end workflow from this browser UI into the real,
native-hosted Hermes runtime and existing OpenBB engines. A generic chat page
connected only to a model is not sufficient. Keep finance policy enforcement
server-side, regardless of what upstream WebUI controls advertise.

## 7. Core agentic workflows

### W1. Morning and weekly financial briefing

**Trigger:** user request or approved schedule.

1. Check freshness, provider rights and accepted portfolio snapshot.
2. Retrieve material events, price changes, filings and risk changes through
   OpenBB/FMP Cached and approved SEC/FRED paths.
3. Compare with the previous accepted evidence snapshot.
4. Rank changes by policy-defined materiality, not headline volume.
5. Produce a concise briefing with drill-down widgets and missing-data warnings.
6. Notify with a generic "report ready" message unless the destination is
   explicitly approved for financial content.

**Outputs:** event timeline, exposure delta, investigation queue and citations.
**No:** TradingView cron collection, orders, portfolio edits or invented news.

### W2. Single-name investigation

**Trigger:** "Explain this holding and whether it still fits my plan."

Run the actual seven-phase pipeline, retrieve relevant filing evidence, identify
accounting/valuation assumptions and show bull/base/bear scenarios. Add the
portfolio's concentration and liquidity constraints through local computations.
Separate investment quality from tax cost of changing the position.

TradingView can be opened in a separate user-driven research session where
permitted. Its output must not feed the automated ranking, optimizer, scheduled
pipeline or backtest store. If quantitative corroboration is needed in that
pipeline, obtain it independently from an approved source.

**Outputs:** seven-phase evidence, thesis memo, contrary evidence, valuation
sensitivity and open questions. Principal-analyst prompts observed in the original checkout can inform
report structure after review, but are not present in this `portfolio` baseline;
previous reports are not current evidence.

Make filing-versus-vendor reconciliation part of PF-05/W2: compare share count
and float, common versus preferred equity, consistent D&A/margin basis, cash,
warrant/fair-value gains, diluted-share history and fiscal-year estimate coverage.
Match dates, share classes, currency, units and split basis before declaring a
discrepancy. Repeated shares or a missing estimate period is a diagnostic, not
proof the vendor is wrong. Preserve discrepancies and source limitations in a
`VendorReconciliationReport`; do not overwrite provider records.

Run the filing-grounded evidence leg without reading the pipeline's conclusions
first, then publish "Differences vs. pipeline". Independent evidence is not a
second agent harness: Hermes coordinates approved deterministic adapters and
one bounded synthesis. Reuse authorized SEC/EdgarTools parsing with full-document
coverage checks; FMP XBRL is optional and entitlement-gated, not presumed available.
The supplemental template's standalone prohibition on using OpenBB is not
adopted into this integration.

Retain a plain-language red-flag scorecard with explicit UNKNOWN states.
Template-specific valuation haircuts, rigid buy/trim/stop formulas, illustrative
order tickets and iron-butterfly examples remain **unselected G1 proposals**.
They are not validated financial rules or permission to expand options scope.

> **[Reviewer Feedback — 2026-11-27]:** Promote the concrete analytical controls from `docs/prompts/principal-analyst-deep-dive-TEMPLATE.md` (v2.3) into first-class **W2 / `PF-05`** requirements rather than leaving them as informal inspiration:
> - **Unanchored Two-Track Audit + "Differences vs. Pipeline" Section:** Run the deterministic 7-phase `Analysis\stock_analysis.py` pipeline *and* an independent filing-grounded audit (XBRL `Cover` + notes via `financial-reports-form-10-k-json`, EDGAR 8-K Ex-99.1, and full 10-Q/10-K MD&A via local `edgartools` to avoid 49 KB HTTP fetch truncation), reconciling disagreements explicitly.
> - **8 Mandatory FMP Vendor-Trap Reconcilers:** Deterministically check cover-page share count vs. lagging vendor shares/market cap, `float > shares_outstanding`, redeemable preferred mis-mapped as common equity, COGS D&A basis switches, mis-parsed cash vs. filing balance sheet, warrant fair-value gains vs. operating profit, stale repeated diluted share counts, and `financial-estimates` `limit >= 10` so newest-first sorting does not drop the current fiscal year.
> - **12-Check Plain-Language Red-Flag Scorecard & Rule-Based Reference Levels:** Include the 12 PASS/CAUTION/FAIL checks (with `-10%` base fair-value haircut per FAIL, capped at `30%`), dilution overhang / 13D lock-up unlock dates, and ATR(14)-based accumulate/trim/protective-stop reference levels with strict mathematical ordering checks (`new_entry_stop < buy_3 < buy_2 < buy_1 < base_fair_value < trim_1`) and valid-until expiry dates.
> - **Explicit Policy Decision on §5b Illustrative Order & Iron-Butterfly Tickets:** If W2 adopts the template's bracket-order and Black-Scholes iron-butterfly tables, require the verbatim cautionary banners, enforce non-execution (`illustrative reference only`), and cross-check live options-chain availability/earnings dates rather than silently conflicting with §8.2's specialist-options boundary.

### W3. Tax-aware rebalance

**Trigger:** user request or a drift alert that requests a review.

1. Validate an accepted Investment Policy Statement and fresh snapshots.
2. Generate constrained portfolio candidates with existing what-if/risk engines.
3. Evaluate contribution-only and dividend/cash allocation before taxable sales.
4. Send opaque candidate IDs to the private tax-lot service.
5. Compute incremental federal/state tax, lot feasibility, wash-sale risks,
   concentration reduction, turnover and cash effects.
6. Present non-dominated alternatives; do not invent a single "optimal" blend of
   tax dollars and volatility without user-approved objectives.
7. Optionally run an approved paper simulation; live execution remains manual.

**Outputs:** alternatives table, affected-lot references, taxes/fees/cash bridge,
constraint violations, wash-sale monitoring plan and paper evidence.

### W4. ESPP/RSU/option disposition planning

**Trigger:** upcoming disposition window, vesting event or user request.

Validate grant, purchase/exercise, vest and sale dates; source document
completeness; compensation classification; adjusted basis; and applicable state
work/residency history. Compare sell-now, staged-sale and hold scenarios, showing
both concentration exposure and tax consequences.

A qualifying ESPP disposition is **not simply "everything taxed as LTCG."**
Ordinary compensation and capital gain can both apply. Already-reported wages
must be reconciled to basis to avoid double taxation. ISO AMT, NSO compensation
and RSUs are different cases, not one generic stock-plan formula.

**Outputs:** event calendar, scenario deltas, basis exceptions and a document
request list. Missing required facts block personalized numeric advice.

### W5. Year-end federal + California tax review

Reconcile year-to-date income, gains/losses, carryforwards, compensation,
contributions, estimated payments and withholding. Distinguish measured YTD
facts from remaining-year projections. Evaluate supported harvesting, gain
realization, charitable giving, contributions and conversion scenarios.

Estimate **incremental whole-return tax**, not gain multiplied by a guessed
marginal rate. Show federal, state and interaction effects separately.
Use official year-specific law, forms and instructions; flag unresolved source
conflicts and changes in law.

**Outputs:** baseline projection, scenario comparison, payment/deadline review,
missing facts and CPA/EA handoff package. No return submission or tax payment.

### W6. Retirement and Roth-conversion planning

Reuse Owl behind a bounded local adapter for account-bucket optimization.
Confirm monthly versus annual units, Social Security PIA versus actual check,
nominal versus real dollars, basis, prior MAGI and the plan start date.

Compare spending, conversion and withdrawal policies under historical and
stochastic scenarios. Independently validate the proposed near-term tax flows
with the qualified household tax engine. Do not merely add a tax adjustment to
an Owl optimum and continue calling it optimal: if it changes cash flow or
feasibility, re-solve within reviewed constraints or label the result provisional.

**Outputs:** cash-flow ladder, conditional success/shortfall distribution,
conversion scenarios, sensitivity to longevity/inflation/returns, and model
limitations. No guaranteed "safe" withdrawal rate.

### W7. State move comparison

Compare explicitly supplied states and move dates. Include domicile versus
residency, workday sourcing, ordinary income, capital gains, retirement income,
other-state credits and local/special taxes where supported.

Owl's current single-move approximation is not a part-year tax calculation.
Detailed move-year results require qualified residency logic. Washington must
not be treated as "all investment income tax-free" simply because it lacks a
general individual income tax.

**Outputs:** qualified comparisons where possible; otherwise a partial estimate
with excluded items and questions for a professional.

### W8. Reproducible financial workflow and paper rehearsal

Choose a financial workflow in Hermes, show prerequisites, coordinate approved
backend operations, produce expected artifacts and preserve run/input lineage.
Expensive work uses existing jobs; artifact-producing stages cannot pass with
prose only. A user may independently run the corresponding tutorial notebook
for hands-on verification, but production does not launch or depend on it.

For TechTrade: plan -> validation -> order batch -> workbook -> explicit paper
approval -> fills -> reconciled replay. Preserve the separate Portfolio paper
ledger and its behavior. Migrate overlapping fill simulation only through the
Nautilus qualification gate; do not merge ledgers or rewrite historical fills.

### W9. Household goals and resilience

Combine accepted budget summaries, debt schedules, investment balances and goal
horizons. Evaluate emergency reserves, education funding, mortgage/debt tradeoffs,
large purchases, insurance inventory and estate-document completeness.

Start with deterministic cash-flow scenarios. Policy/tax eligibility, insurance
adequacy and estate/legal recommendations need their own coverage gates.
The first release can collect facts and identify missing documents without
pretending to calculate every legal or insurance outcome.

### W10. Private document vault and tax-document analysis

**Inputs:** Explicitly selected IRS Form 1040 returns and schedules, amended
returns, W-2s, 1099s, California/other state returns, brokerage statements,
receipts and other approved financial documents. Do not crawl home directories,
email accounts or cloud drives automatically.

**Proposed stack:**

| Layer | Candidate and responsibility |
|---|---|
| Document system of record | Paperless-ngx: preserve originals, organize document types/tags and provide OCR/full-text search. |
| Structured extraction | Docling: local PDF text, tables and page structure; reuse suitable existing OCR rather than blindly processing every file twice. |
| Exact search | Paperless full-text search plus structured SQL field lookup; sufficient for the first release. |
| Semantic/hybrid index | Optional self-hosted Qdrant with local embeddings; combine semantic retrieval with exact search after a synthetic benchmark proves added value. |
| Accepted financial facts | Existing local SQL infrastructure through a private service; not vector similarity, chat memory or unreviewed OCR. |
| User and agent access | Native Workspace evidence/review views and narrow authenticated MCP operations coordinated by Hermes. |

The vector database is a rebuildable retrieval index, not the original-file
vault or the tax/accounting system of record. Paperless is a document manager,
not a replacement portfolio ledger or financial workspace.

**Workflow:** approved upload -> bounded file validation -> original/version
registration -> local extraction/OCR -> candidate-field review -> scoped
indexing -> cited analysis -> accepted facts supplied to qualified tax engines.
Encrypted/unreadable files, ambiguous form years and missing pages produce
visible review states, not guessed content. Corrected and amended documents
remain linked to their predecessors; amendments do not automatically replace
every fact in a return.

Supported analysis journeys include:

- Compare reviewed returns across years and explain income/deduction/tax deltas.
- Locate capital-loss carryforwards and their supporting schedules.
- Reconcile W-2/1099 figures against return fields and flag mismatches.
- Identify missing documents and possible brokerage basis adjustments.
- Prepare reviewed tax/retirement inputs and a cited CPA question package.

Every material result links to a document version, page, extraction evidence
and form line when available. Tax-year-specific field mapping is required;
line numbers can change between years. OCR confidence alone never establishes
financial correctness, and missing data are not zero.

**Privacy:** Keep originals, OCR, embeddings, SQL facts, indexes and backups in
approved local storage outside the repository. Apply encryption at rest, local
service authentication and authorization before retrieval. Keep public
IRS/state guidance separate from household documents. Embeddings are sensitive
derived data, not anonymized records.

The default Hermes/model path receives only policy-approved findings and opaque
evidence references; exact amounts and excerpts render directly in the local
authorized UI. Free-form analysis of raw private text by a dedicated local
model is a separate design/permission gate, not an exception silently granted
by installing Qdrant or selecting a localhost model endpoint. If later approved,
it requires bounded transient context, no persistent memory, no external
fallback and verified egress controls. Existing raw-data restrictions remain.

**Outputs:** A searchable local document inventory, reviewable extracted facts,
deterministic comparisons, missing-evidence findings and cited private reports.
No automatic tax filing, financial-account changes or external document uploads.

## 8. Tax scope: full approach, honest coverage

### 8.1 Three distinct engines

| Layer | Responsibility | Candidate |
|---|---|---|
| Investment event/lot layer | Basis, holding periods, compensation split, realized gain/loss, wash-sale adjustments and scenario event construction. | New bounded adapter/service reusing reviewed local utilities; materially new correctness work. |
| Annual household tax layer | Federal and state liability, deductions, credits, interactions, income classification and scenario deltas. | PolicyEngine US, qualified feature by feature. |
| Long-horizon planning layer | Retirement withdrawals, spending and conversion optimization under declared simplifications. | Owl, with independent annual-tax checks. |

Tax-Calculator provides a federal cross-check, not state coverage. OpenTaxSolver
and tenforty can provide form-oriented historical/reference comparisons within
their supported years and cases; tenforty using OTS is not an independent second
engine from OTS.

### 8.2 Federal release priorities

**Initial qualification:** wages, ordinary and qualified dividends, interest,
short-/long-term gains and losses, applicable carryforwards, filing status,
standard/itemized deductions, relevant credits, NIIT, payroll interactions,
withholding and estimated-tax scenarios.

**Next:** equity compensation, ISO AMT, retirement distributions, IRA basis and
Form 8606, Roth conversions, RMDs, charitable gifts, education accounts and ACA/
Medicare interactions where relevant.

**Specialist/blocked until separately implemented:** partnership/K-1 complexity,
trust returns, foreign reporting/PFICs, entity planning, complex options/straddles,
Section 1256, QSBS determinations, property depreciation/recapture, inherited
account exceptions and estate/gift returns.

Recognize these cases at intake and route them to a professional. Detection is
not calculation support.

### 8.3 California first

Qualification must include:

- Capital gains taxed at ordinary California rates, not federal preferential
  capital-gain rates.
- Federal-to-California adjustments and separate state basis/carryforward
  handling where required.
- California HSA nonconformity; no automatic reuse of federal HSA treatment.
- California treatment of Social Security, retirement income, relevant
  municipal/Treasury income and state-specific deductions/credits.
- High-income surtaxes and state AMT where applicable.
- Equity compensation sourcing, workday allocations, resident/nonresident and
  part-year cases, plus other-state credit interactions.
- Filing-status and community-property issues, including distinctions involving
  registered domestic partnerships where relevant.
- Year-specific estimated-payment schedules and safe-harbor rules; do not copy
  federal payment percentages into California.

These are required product capabilities to qualify, not claims that the
selected engines currently cover all of them.

Qualification fixtures must cover California installment timing and prior-year
safe-harbor eligibility, including filing-status thresholds and equality at the
threshold; SDI on covered wages using the applicable year's rate/coverage;
the separate taxable-income surtax; federal/state mortgage acquisition-debt
differences including grandfathering; and eligible US-obligation fund income.
Use year-pinned official sources, not the review's illustrative rates as constants.
Fund qualification does not exempt an entire ETF dividend: verify qualifying
asset tests and the issuer's eligible-income allocation. Do not equate an AGI
threshold with a taxable-income threshold or assume all wage types are SDI-covered.

> **[Reviewer Feedback — 2026-11-27]:** Make the California qualification checklist explicitly testable by naming the five highest-dollar statutory traps:
> 1. **CA Form 540-ES `30% / 40% / 0% / 30%` front-loaded installment schedule** (70% due by June 15) + **CA's $1,000,000 AGI cliff** ($500k MFS) that eliminates the 110% prior-year safe harbor entirely and forces 90% current-year accuracy or Form 5805 annualization.
> 2. **Uncapped CA SDI payroll tax (~1.1%+ with no wage ceiling post-2024)** on all wages, bonuses, RSU vests, and NSO exercises.
> 3. **CA 1% Mental Health Services Tax** above $1M taxable income (pushing top statutory rate to 13.3%, or 14.4%+ on wages with SDI).
> 4. **CA Rev. & Tax Code § 17145 ≥50% quarterly asset threshold** for US Treasury ETF/money-market state-tax exemption (Schedule CA subtraction) vs. CA taxation of out-of-state municipal bonds.
> 5. **Mortgage interest acquisition-debt nonconformity** ($1,000,000 California deductible principal cap vs. $750,000 federal post-TCJA cap).

### 8.4 Every state and DC

Maintain a 51-jurisdiction matrix. A single `supported=true` field is prohibited.
For every jurisdiction record:

`tax_year`, `residency_case`, `filing_status`, `income_types`, `deductions`,
`credits`, `local_taxes`, `special_capital_gains_tax`, `retirement_rules`,
`equity_compensation`, `forms`, `source_revision`, `engine_version`,
`fixture_count`, `last_reviewed`, `known_exclusions`, `qualification_state`.

Qualification states:

| State | User-visible meaning |
|---|---|
| Catalogued | Official sources identified; no numerical support promised. |
| Estimate-only | Engine exists; known gaps prevent decision-grade use. |
| Qualified subset | Named year/case/features pass reviewed acceptance; other cases blocked. |
| Qualified expanded | Broader tested coverage, still with explicit exclusions. |
| Unsupported / expired | No valid calculation, or annual review is overdue. |

Rollout:

1. Federal + CA full-year resident qualified subset.
2. Pilot contrasts: WA, NY including local-tax detection, TX, MA and NJ.
3. Add all remaining states/DC in groups by actual features and user need.
4. Qualify part-year/nonresident, interstate credits and compensation sourcing
   separately rather than inheriting full-year certification.

General-income-tax-free states still require source-year review of capital-gain,
payroll, property, local and other taxes relevant to the scenario. No fixed list
may substitute for the feature matrix.

### 8.5 Investment tax-lot requirements

Persist immutable acquisition/disposition events and correction lineage. Keep
broker-reported basis separate from validated adjusted basis. Include corporate
actions, transfers with missing basis, return of capital, reinvested distributions,
specific identification evidence, and ordinary compensation adjustments.

The wash-sale analysis covers 30 days before and after the loss sale, partial
replacement quantities, relevant cross-account/spouse transactions, DRIPs,
compensation acquisitions and IRA/Roth IRA cases. "Substantially identical"
requires reviewed rules and ambiguity flags; a different ticker alone does not
prove safety.

Future purchases cannot be known at sale time. A proposed harvest remains
conditional through its monitoring window; later events can invalidate an
earlier projection. Do not treat a broker's wash-sale field as complete household
coverage.

A paper engine's FIFO/LIFO behavior is not automatically a valid tax election or
adequate identification instruction for an actual brokerage account.

### 8.6 Versioning and numerical evidence

Every estimate records the tax year, enacted-law cutoff, engine version,
input-snapshot hash, scenario definition, rounding rules and missing features.
Do not silently calculate tax year 2026 using a 2025-only form engine.

Keep proposed-law scenarios separate from enacted law. Official forms can lag
statutes; disagreements must be visible and reviewed, not resolved by an LLM
choosing whichever source seems more plausible.

## 9. Portfolio intelligence and optimization

Keep the current analysis stack. Add planning constraints around it:

- account type, cash needs, horizon and withdrawal obligations;
- user-confirmed target allocation and concentration limits;
- liquidity, restricted securities, trading windows and settlement constraints;
- lot feasibility, estimated taxes, transaction costs and contribution routing;
- current data coverage and uncertainty.

Use constraint-based candidates and sensitivity analysis before introducing
complex return forecasting. PyPortfolioOpt is an optional optimization building
block if an existing engine cannot express a required objective.

Use multiple objectives transparently: expected risk, liquidity, turnover,
taxes and goal funding. Prefer a small frontier of feasible alternatives over
an opaque composite score.

Backtesting must preserve point-in-time data, publication lags, corporate
actions, survivorship constraints, costs and out-of-sample validation. In
particular, 13F/N-PORT reports are delayed disclosures, not current trades.

### 9.1 NautilusTrader as the standardized strategy/backtest foundation

**Direction approved by the user:** retain the product-specific OpenBB layer,
but use NautilusTrader for the trading-engine capabilities it already provides.
This is an architecture/migration decision, not a completed integration or
permission to connect a brokerage account.

| Keep product-owned | Delegate to the qualified Nautilus integration |
|---|---|
| Hermes orchestration, permissions, approvals and durable run coordination | Deterministic event-driven simulation and execution lifecycle, not assistant orchestration |
| OpenBB API contracts, privacy filtering, jobs and evidence | Backtest engine, simulated orders/fills and account/position accounting within a run |
| FMP cache-first ingestion, point-in-time availability and data rights | Typed instruments/market events and a derived Nautilus-compatible catalog |
| TechTrade strategy intent and portfolio allocation constraints | Reviewed strategy implementations using Nautilus lifecycle conventions |
| Independently qualified statistical validation and reporting | Trial execution producing normalized returns, fills and equity evidence |
| Household, tax, portfolio snapshots and separate paper ledgers | No replacement of household records, tax-lot truth or approval policy |

The current `openbb-backtest` implementation is custom NumPy/Pandas/optional
Numba research accounting plus a Python event-driven simulator. Keep its API
as the integration facade; do not indefinitely expand its duplicate broker/fill
machinery. Nautilus is the target authoritative event engine once a capability
passes acceptance. The existing vectorized engine may remain only as an
explicitly labeled fast screening backend if benchmarks justify it; screened
candidates must be revalidated by the authoritative event engine.

| ID | Migration requirement | Acceptance |
|---|---|---|
| BT-01 | Preserve OpenBB callers while adding a versioned Nautilus adapter and explicit backend selection. | Existing result/privacy contracts remain valid; engine/data/strategy versions are recorded; no silent fallback to legacy simulation. |
| BT-02 | Standardize reviewed strategy artifacts and data conversion. | A strategy version binds code hash, parameter schema, instruments, data requirements, sizing and event timing; point-in-time/corporate-action transformations are reproducible and unsupported semantics fail closed. |
| BT-03 | Qualify and cut over by capability, retiring redundant simulator paths. | Independent golden cases pass, modeled differences are explained, cutover/rollback is explicit and paper effects remain idempotent; legacy code is a bounded migration reference, not a second permanent authority. |

Hermes selects approved strategy IDs and bounded parameters. It may propose
changes for review, but cannot execute arbitrary generated strategy code, install
plugins, promote a strategy or change a live deployment. A reviewed strategy has
one canonical implementation/version; avoid separate hand-maintained copies
for different simulators.

Initial acceptance covers buy-and-hold, periodic portfolio rebalancing and a
TechTrade entry/stop/target strategy. Use identical synthetic data and explicit
fill/cost assumptions, with independent expected cash, quantities and returns.
Agreement with the old engine is diagnostic, not an oracle. Daily OHLC bars
do not establish actual intrabar sequencing or market liquidity.

Future broker adapters, including IBKR, are a reason to choose this foundation,
not an enabled product capability. Broker-paper connectivity and live trading
each need separate scope/approval, reconciliation, kill-switch and account-rule
qualification. Do not assume Nautilus automatically supplies whole-share policy,
settled-cash/T+1 checks or prevention of good-faith violations for every account.

> **[Reviewer Feedback — 2026-11-27]:** Add three concrete acceptance constraints to `BT-01`–`BT-03`:
> 1. **Deterministic Sell-Before-Buy Cash Sequencing on Daily Bars:** Unlike vectorized target-weight engines, event-driven multi-asset portfolio rebalancing in Nautilus will reject buy orders for insufficient cash if buys and sells on the same rebalance bar are submitted concurrently without sell-first cash settlement or margin allowance. Require deterministic sell-then-buy order staging in the rebalance strategy adapter.
> 2. **Fixed-Point vs. `Decimal` Reconciliation:** Current `openbb_backtest/engine/execution.py` uses `Decimal` arithmetic across both vectorized and event-driven paths; Nautilus uses compiled fixed-point `Price`/`Quantity`/`Money` types (64-bit standard vs. 128-bit high-precision wheels). Document explicit precision-rounding tolerances for `obb.backtest.reconcile` post-cutover.
> 3. **Preserved Deflated Sharpe / CPCV Trial Accounting:** When parameter sweeps run across isolated Nautilus workers, ensure total trial counts still flow into `openbb_backtest/validation/stats.py` so multiple-testing haircuts (DSR/PBO) are never diluted.

Additional BT-01 through BT-03 acceptance: stage sells before dependent buys,
but release buying power only when the declared account/settlement model permits
it; same-bar ordering does not make cash proceeds settled. Pin the worker's
Python ABI and numeric precision mode separately from Hermes. Reconcile explicit
Price/Quantity/Money rounding against independent cash/fee fixtures, and preserve
the full sweep/fold result matrix and deduplicated trial lineage across workers
for DSR/PBO/CPCV qualification. No blanket tolerance may hide a wrong fill or
settlement rule.

## 10. MCP and data-source policy

| Connection | Role | Default boundary |
|---|---|---|
| OpenBB Platform/Portfolio MCP | Canonical market/portfolio analytics, stories and approved jobs/artifacts. | Reviewed profile; private data and mutation controls retained. |
| Workspace MCP | Dashboard/widget publication and inspection. | Separate auth; UI mutations require approval; no financial execution authority. |
| Existing Agents MCP | Two sanitized Q&A tools. | Preserve narrow surface; do not advertise planned agents as enabled. |
| Existing Daytrade MCP | Reviewed read-only market/session tools. | Not a live broker/order interface. |
| Official FMP MCP | Interactive discovery and genuine coverage gaps. | Explicit plan/endpoint entitlements and budget; do not silently bypass cache-first policy. |
| TradingView MCP | Personal, interactive research in a separate session. | No unattended/bulk collection, optimizer ingestion or automated decision-system feed. |
| Tax planning MCP, proposed | Authorized local annual-tax and lot-scenario tools. | Opaque dataset IDs, local computation, no filing/payment tools. |
| Retirement MCP adapter, proposed | Bounded Owl scenarios and evidence. | No arbitrary paths, plugins, Python or unrestricted saves. |
| Budget adapter, optional | Accepted Actual Budget summaries. | Read-only bounded API adapter initially. |

FMP Cached remains preferred for repository workflows. A direct FMP MCP call
does not automatically populate that cache or have identical schemas.
Identify endpoint gaps and add reviewed server-side adapters instead of teaching
the LLM to select a different provider on every failure.

**TradingView terms are a hard design constraint.** Its official pages describe
OAuth, plan-based access and changing capabilities. They also prohibit
unattended collection and automated decision-system use. Personal,
non-commercial intent does not remove those restrictions. If connecting the
custom harness or using a particular research output is ambiguous, leave that
integration disabled pending permission; use a supported personal client.

The two official TradingView pages reviewed differ on some capabilities and
rate limits. Discover the actual authorized tool schemas and apply current
terms. Do not hardcode a tool count, assume Pine/backtests exist, or classify
`get_active_watchlist` as read-only: its current detailed guide marks it as
mutating because it may activate/create a watchlist.

## 11. Deployment, cost and operations

Use separate environments for Hermes, existing OpenBB and optional tax/
retirement engines. Do not upgrade OpenBB's Python/pandas stack to satisfy an
unrelated engine. PolicyEngine currently documents pandas 3+; current Hermes
installation guidance also differs from the existing OpenBB environment.

### Required single-machine topology

| Component | Deployment decision |
|---|---|
| MySQL | Native Windows service, not Docker. Reuse an approved existing instance without overwriting its databases or configuration. |
| Hermes agent and scheduler | Native Windows processes in an isolated environment, not a container or remote runtime. |
| Hermes WebUI | Prefer a native local web server using the host Hermes runtime; qualify the fork's Windows startup. A containerized UI is allowed only if it delegates the actual agent loop to native Hermes. |
| OpenBB and existing MCP services | Preserve approved local environments and launchers; no unnecessary migration into Docker. |
| Native Workspace | Keep its supported local deployment as the dashboard service, including existing Docker components where required. |
| Document/search and tax services | Native or local Docker as supported; Paperless may retain its own supported database rather than being forced onto MySQL. |
| Model inference, embeddings and OCR | Approved local runtimes; no hosted fallback for private workflows. |
| LiteLLM | Reuse the existing local installation as the shared AI endpoint gateway; do not install a duplicate or overwrite unrelated routes. |
| NautilusTrader | Isolated local worker/environment behind OpenBB; pin a qualified release and matching API docs. Native or local Docker is allowed; Hermes and MySQL remain native Windows. |

Choose model size/runtime only after inspecting available RAM/VRAM and measuring
structured tool calling, quality and latency. Do not assume a local model is
already installed or promise full capability on unknown hardware. A missing or
incapable local model blocks that workflow instead of routing it to the cloud.
A localhost proxy backed by a hosted model is not local inference.

Hermes calls an approved LiteLLM model alias rather than embedding provider
credentials or choosing arbitrary endpoints. Private aliases must resolve only
to qualified local inference backends, including every retry/fallback route.
Use separately scoped credentials and disable content logging/tracing for private
requests. Embeddings may use LiteLLM where the qualified local backend supports
the required API; otherwise keep the approved local embedding worker isolated.
LiteLLM routes requests; it does not itself make a model local or supply model
weights. Existing cloud routes, if present, are not authorized for private use.

Local hosting is distinct from offline operation. FMP and TradingView remain
external services with their existing purpose restrictions; private documents
must not enter those requests. Offline mode uses local documents, deterministic
engines and permitted cached data, and labels stale/unavailable market evidence.
Model/OCR assets can require an approved initial download; steady-state private
processing must not depend on external inference or model downloads.

Costs to track per run:

- model input/output and retrieval context;
- upstream API calls and cache misses;
- provider entitlements, storage/retention and machine runtime;
- expensive simulation/optimization jobs;
- optional brokerage sync or external messaging.

Proposed inherited starting limits: 40 tool calls, two argument-repair attempts,
15 minutes wall time and one mutating operation at a time, as in the Notebook
Companion specification. Long jobs have separate approved budgets and solver
limits; they are not exempt from cost controls.

Show estimated and actual costs. Fixture mode makes no provider-network calls.
Scheduled jobs need a dedicated bounded service identity and an explicit
disable switch.

Proposed shared-gateway timezone: **America/Los_Angeles** for household schedules
and cron expressions. Market-session calculations retain **America/New_York**,
and receipts retain UTC instants. Convert and test every named schedule; do not
change the host timezone or create a second scheduler. Active skills/wrappers
are read-only to the runtime identity; proposed skill changes are quarantined
for review. Heavy OCR, tax, retirement and Nautilus workers run on demand with
bounded memory/concurrency and idle unloading rather than all staying resident.

### Separate operations design: FMP cache sync through Hermes cron

The owner requested a specialized design under the separate prompt
`prompts\fmp-cached-hermes-cron-design-prompt.md` (workspace-relative).
Its G1 draft is at workspace-relative
`prompts\out\fmp-cache-hermes-sync-design.md`; no dedicated sync issue exists,
so the prompt's local-output fallback applies. This is not an implementation
approval or an expansion of the generic financial assistant's unrestricted tools.

Use Hermes **no-agent** cron scripts for routine sync, validation and changed-state
alerts, reusing the existing price-history warmer and extending its readiness
report. Routine operations make zero LLM/LiteLLM calls. Prefer direct importable
warmers over `openbb-jobs trigger --wait`, which needs a separate worker that
also schedules. Preserve an independent backup mechanism and do not reinstall
the removed bundled `OpenBBPortfolio` Windows service.

The first rollout is price history plus validation only. Current ETF and
directory refreshers delete/replace or truncate stored records, so they remain
blocked pending separately owned retention-safe interfaces. No storage, schema,
collation or prune changes are designed here. Detailed job schedules, budgets,
114-table inventory, privacy controls, failure recovery, draft issues and G1
decisions live in the specialized draft rather than this broader roadmap.

## 12. Delivery roadmap

These are planning ranges for one experienced maintainer working consistently,
not commitments. Dependency health and independent tax validation dominate
uncertainty. Part-time calendar duration will be longer.

| Phase | Planning range | Deliverable and exit gate |
|---|---|---|
| 0. Reconcile baseline | 1-2 weeks | Source-to-capability mapping, provider rights, environment provenance, missing engine adapters and accepted architecture decision. Notebook inventory drift tracked separately; no private-data ingestion yet. |
| 1. Hermes/OpenBB vertical slice | 2-3 weeks | One production workflow runs from Hermes WebUI through native Hermes -> policy adapter -> existing MCP -> evidence -> Workspace, without notebook files/kernels or another agent loop. |
| 1b. Nautilus qualification and migration | Re-estimate after the three-case comparison | Parallel specialist track after Phase 1 contracts; select release/runtime, qualify data/strategy/results and independent cases, then cut over simulation-dependent paths. No broker connection. |
| 2A. Core portfolio capabilities | Re-estimate within the former Phase 2 envelope | Qualify `portfolio/01-08` capabilities, including W2 evidence and what-if, through shared services. Simulation-dependent cases explicitly wait for Phase 1b; they do not block unrelated tax work. |
| 2B. Remaining referenced capabilities | Re-estimate; depends on relevant 1b/2A contracts | Complete TechTrade, YFinance-reference dispositions and 11 doc examples; retain the eventual 25-main/36-file coverage gate without making it a prerequisite for every household workflow. |
| 3. Household and CA tax foundation | 4-6 weeks, parallel with unrelated 1b/2B work | Starts after Phase 1 identity/privacy/artifact contracts and required input reconciliation, not after every tutorial capability. Qualify federal+CA subset and secure Tax Center. |
| 3a. Private document evidence | 2-4 additional weeks | Synthetic-first vault/OCR integration, reviewed field extraction, exact search, citations and lifecycle controls. Enable optional Qdrant only after retrieval and privacy acceptance. |
| 4. Equity compensation + retirement | 4-8 weeks | Validated lot/compensation features, constrained Owl adapter, annual-tax comparison, goal and retirement evidence. |
| 5. Broader state support and monitoring | 4-8+ weeks | Pilot-state qualification, remaining documentation analytics, scheduled read workflows, resilient deployment; additional jurisdictions continue incrementally. |

The earlier **20-37+ focused maintainer-week** envelope included document
evidence but not the newly selected Nautilus migration. It is not a current
total commitment. Rebaseline after Phase 1b's comparison, accounting for adapter
work and displaced in-house engine work rather than blindly adding both.
Private local-model approval/qualification also requires separate estimation.
Comprehensive all-state, all-form tax correctness
is ongoing work, not a credible fixed-date promise.

### First end-to-end slice

Use the existing Portfolio basket x-ray engine with synthetic fixtures:

`Local Hermes WebUI request -> native Hermes + local model -> plan preview ->
workflow readiness -> approved analytics -> run-scoped chart/table/report ->
Hermes result card + native Workspace drill-through -> replay`.

The Phase 1 gate includes native-host runtime proof and browser interaction;
the UI cannot be deferred as an optional companion. The planning ranges remain
provisional until the WebUI's Windows runtime and local-model capacity are
qualified; any required porting is re-estimated rather than hidden in the range.

Then add a synthetic, qualified federal+CA comparison to a portfolio what-if.
Only after those are reliable should real private household inputs be enabled.
For document ingestion, first demonstrate a synthetic return/W-2 reconciliation,
including an OCR error, a corrected document and a cited local report, without
sending private-content-shaped test sentinels to external services.

### Deliberate non-work

No new all-purpose coding agent, replacement portfolio ledger, live broker
automation, self-modifying financial logic, model training, general shell/SQL
MCP, mobile rewrite, public SaaS, automatic tax filing or multi-agent "swarm".
Only the documentation tracker
[#1312 (Hermes integration and unified financial-planning proposal)](https://github.com/rashmijain02/OpenBB/issues/1312)
was created; no implementation backlog, account connection changes or
dependency installation was performed.

## 13. Acceptance and quality gates

| Gate | Minimum evidence |
|---|---|
| Coverage | All 36 notebook files classified as tutorial/reference assets; the capabilities illustrated by all 25 main notebooks pass independent Hermes/service tests; documentation requirements remain in a maintained disposition register. |
| Engine parity | Independent fixtures/oracles, not two wrappers agreeing with the same broken implementation. Per-metric tolerances documented. |
| Agent reliability | Define 25 synthetic Hermes capability cases from the main notebook references and repeat twice; target at least 48/50 agent successes and 100% of showcase journeys, reporting all failures/retries. This is a proposed production suite, not a claim that an inherited suite already exists. |
| Financial safety | Zero live orders/transfers/filings/payments; malformed calls, expired approvals and changed arguments rejected. |
| Replay | Lost responses and restart tests prove idempotency; checkpoints bind source, tools, input versions and policy. |
| Tax | Exact expected categorical treatment and form rounding; documented numerical tolerances only where appropriate; boundary/unsupported cases cannot silently pass. |
| State honesty | No jurisdiction advertised beyond its certified year/features/residency cases; expired coverage blocks recommendations. |
| Privacy | No raw financial inputs or credentials in model traces, logs, remote requests, generated skills or public artifacts; authorized local UI is tested separately. |
| Document evidence | Synthetic PDFs exercise scans, tables, changed tax-year line mappings, duplicates, amended/corrected documents and ambiguous values; no unreviewed candidate becomes an accepted tax input. |
| Retrieval | A held-out synthetic query set covers exact forms/lines, conceptual questions, wrong-year near matches and absent answers; cited pages support claims, unauthorized documents never surface, and semantic search is enabled only when it improves on exact search without weakening these gates. |
| Document lifecycle | Reprocessing preserves version lineage; revocation blocks search and artifact access; deletion invalidates OCR, chunks, vectors, caches and dependent exports; restore replays deletion tombstones before serving data. |
| Data rights | TradingView cannot be reached by scheduled/automated decision paths; FMP/provider entitlements and retention are checked. |
| UX | Real native Workspace browser acceptance; provider failures and partial data render explicitly rather than blank or synthetic success. |
| Operations | Restart, backup/restore, secret revocation, cancellation and bounded job behavior demonstrated. |
| Local web deployment | Browser-to-native-Hermes real-path evidence; native MySQL identity; no duplicate agent loop/scheduler; authenticated local access, unavailable-model failure, offline behavior and no hosted private-inference traffic. |
| Harness independence | Production works with notebook directories unmounted and no notebook kernel installed; only Hermes coordinates assistant runs. Manual tutorial execution remains supported separately against shared engines. |
| Nautilus cutover | BT-01 through BT-03 pass on a pinned release: independent cash/fill/return fixtures, strategy/data provenance, unchanged privacy envelopes, bounded worker failures, explicit backend selection and no brokerage/network-order access. |

A narrative reviewer or a second LLM cannot certify arithmetic, tax compliance
or authorization. Those require deterministic checks and qualified human review.

## 14. Decisions proposed for approval

1. Use Hermes WebUI as the primary local chat app; preserve OpenBB Workspace
   as the detailed dashboard and retain product-specific financial logic.
2. Add Hermes through a bounded adapter, not as an unrestricted controller.
3. Reuse reviewed backend contracts from prior Notebook Companion work, but keep
   notebooks exclusively for tutorials and manual verification; Hermes is the
   sole production harness.
4. Add a distinct private household/tax service; do not expose denied raw routes.
5. Qualify PolicyEngine US first, Owl second, optional Actual Budget afterward.
6. Keep TradingView interactive and outside automated decisions.
7. Deliver federal+CA subsets before expanding jurisdiction claims.
8. Keep all execution, filing and payment actions manual.
9. Retain Paperless-ngx + Docling as the existing document-vault proposal, with
   Qdrant optional. A lower-footprint Vault-Lite adapter (encrypted local
   content-addressed files + Docling + SQLite FTS5) is an explicit alternative
   for G1, not an automatically approved replacement. Neither grants raw-document
   access to Hermes.
10. Run Hermes and MySQL directly on Windows; require local private inference
    and permit local Docker only for suitable supporting services.
11. Reuse existing LiteLLM for AI endpoints, with explicit local-only private
    routes and no automatic hosted fallback.
12. Adopt NautilusTrader behind the OpenBB backtest facade for standardized
    strategies and event simulation; retire overlapping in-house machinery
    after qualification, without enabling brokerage execution in this scope.

The unifying product is **one evidence-backed financial conversation and
decision workspace**, not one monolithic application or one LLM attempting to
perform every financial calculation.

### Future-work footnote: broader personal assistant

The same Hermes harness may later support Gmail, WhatsApp and other personal
interaction systems through separately reviewed connectors and permission
profiles. These integrations are **outside this specification's deliverables,
estimates and acceptance gates**: no mailbox/message ingestion, account linking,
message sending or new channel deployment is authorized here. Future work must
define consent, least-privilege access, retention, injection defenses and
explicit send/action approvals, without letting communication channels inherit
financial permissions. External messaging services also require internet access;
local Hermes hosting does not make those services offline or local.

---

## Appendix: Reviewer Feedback & Suggested Refinements (2026-11-27)

*This section records non-destructive review feedback across the updated four-document G1 set (`spec.md`, `plan.md`, `research.md`, and `prompts\out\fmp-cache-hermes-sync-design.md`). Companion reviewer notes in [recommendations.md](./recommendations.md) remain preserved separately.*

### A1. Cross-Document Consistency & Roadmap Observations

1. **Single-Gateway Timezone Alignment (`spec.md` §11 vs. `fmp-cache-hermes-sync-design.md` §4/§14):** Both documents commit to **one native Hermes gateway / cron scheduler**. However, Hermes cron resolves schedule expressions against a single profile-level `HERMES_TIMEZONE` (no per-job timezone field), and the sync draft writes cron expressions in `America/New_York` while household workflows, host clock, and quiet hours (`22:00–07:00 America/Los_Angeles`) use Pacific Time. Standardize the single gateway on `America/Los_Angeles` (expressing `18:30 ET` as `30 15 * * 1-5` PT—exact across all US trading sessions because NY and LA share identical DST transition dates) or explicitly document an isolated ops profile.
2. **Unblock Household & CA Tax Value Earlier (Split Phase 2 into 2A / 2B):** Phase 1b (Nautilus cutover) + Phase 2 (all 25 main stories including 8 `portfolio_yfinance` variants + 9 `techtrade` chapters + 11 `docs\examples` notebooks) sits ahead of Phase 3 (Household & Federal+CA tax). Splitting Phase 2 into **Phase 2A (`portfolio/01–08` core engines)** and **Phase 2B (`techtrade`, `portfolio_yfinance`, `docs\examples`, Nautilus cutover)** allows Phase 3 tax/household workflows to run in parallel rather than waiting 2–3+ months.
3. **Make Paperless-ngx Optional in Phase 3a ("Vault-Lite" Baseline):** For a single user's annual tax PDFs, an encrypted content-addressed local vault (`sha256`) + Docling structured extraction + SQLite FTS5 satisfies `PF-21`–`PF-24` without requiring Paperless-ngx's multi-container stack on day one. Keep Paperless-ngx as an optional connector when full document-management workflows are desired.

### A2. High-Leverage Candidate Functional Extensions (`PF-28+` for Owner Triage at G1)

| Candidate ID | Proposed capability | Why it fits this product's intent |
|---|---|---|
| **PF-28** | **Quarterly Safe-Harbor & Paycheck Withholding Pacing** | Models Fed + CA (`30/40/0/30` + `$1M` safe-harbor cliff) vouchers vs. **late-year W-4 extra payroll withholding** (treated as ratable across quarters to cure earlier underwithholding) vs. Form 2210 / FTB 5805 annualization. |
| **PF-29** | **Effective Marginal Tax Rate (EMTR) "Torpedo & Cliff" Radar** | Sweeps `+$1k` income/LTCG increments in PolicyEngine to surface hidden marginal rate spikes (NIIT `3.8%`, AMT phaseout, SALT cliffs, Medicare **IRMAA 2-year lookback cliffs**, ACA cliffs, CA `+1%` at `$1M`) before conversions or exercises. |
| **PF-30** | **RSU Supplemental Withholding-Gap Earmarker & ISO/AMT Form 8801 Simulator** | Computes exact shortfall between flat supplemental employer withholding (`22%` Fed / `10.23%` CA) and true household marginal rate at each vest, plus max AMT-free ISO exercise shares and multi-year Form 8801 credit recovery. |
| **PF-31** | **Cross-Account Asset Location & CA Tax-Equivalent Yield Optimizer** | Optimizes asset placement across Taxable, Traditional, Roth, and **CA-taxed HSAs**, and computes after-tax cash yields (e.g., `≥50%` US Treasury ETFs exempt from CA tax vs. HYSA/munis). |
| **PF-32** | **Pre-Signature Draft 1040 / CA 540 Return Diff & Carryforward Auditor** | Extends `W10` at filing time to check CPA/software draft returns against W-2/1099/3921/3922 and prior-year returns for Form 8949 double-taxed RSU/ESPP basis, dropped capital-loss/AMT/8606 carryforwards, and missed CA Treasury subtractions. |
| **PF-33** | **Decision Journal, Thesis-Invalidation Watchdog & Counterfactual Audit** | Stores accepted rebalance/tax/single-name decisions alongside `do-nothing` shadow baselines and evaluates 90/180/365-day ex-post after-tax alpha plus fundamental kill-criteria breaches from `W2`. |

## Review disposition (design only; G1 still pending)

| Feedback | Disposition |
|---|---|
| Workspace/Hermes coexistence, notebook independence, safe metric rendering | Incorporated into operative UX requirements and the plan's typed contracts; no extra agent loop or automatic permission for exact private ratios. |
| W2 filing audit and vendor checks | Incorporated with matched-basis/provenance checks. Template-specific numerical heuristics and options/order illustrations deferred for explicit selection and qualification. |
| California traps | Incorporated as year-specific fixture/authority obligations, not hardcoded rates or blanket tax conclusions. |
| Nautilus precision, order sequencing and sweep accounting | Incorporated with settlement-aware cash availability and complete fold/trial evidence. |
| Serial roadmap bottleneck | Split 2A/2B and allow qualified household work in parallel; all eventual coverage gates remain. No new calendar commitment. |
| Vault-Lite | Documented alternative; Paperless selection is unchanged pending owner choice. |
| Candidate PF-28 through PF-33 | Remain candidate-only. PF-27 remains Harness Independence; older IDs in `recommendations.md` are historical, not aliases for accepted requirements. |

G1 still needs the owner's vault choice, selection (if any) of new candidate
capabilities/valuation heuristics, and approval of the revised rollout defaults.
No requirement or reviewer note authorizes implementation or runtime changes.

