# Review, Recommendations, and Feature Proposals

**Status:** Companion review and enhancement proposal; existing bundle files remain untouched.
**Review date:** November 26, 2026, Pacific time.
**Reviewed bundle:** [spec.md](./spec.md), [plan.md](./plan.md), and [research.md](./research.md).
**Tracking:** [#1312 ([notebook-agent] Propose Hermes integration and unified financial-planning capabilities)](https://github.com/rashmijain02/OpenBB/issues/1312).
**Baseline:** `origin/portfolio` at `827e226e47bf1b8cadbf6fba6b9c5eadc7665db7`.

---

## 1. Executive Assessment

### What the current proposal gets right

The three-document bundle (`spec.md`, `plan.md`, `research.md`) is an unusually disciplined pre-G1 architecture and product specification. Four design choices in particular stand out and should be preserved as non-negotiable invariants:

1. **Deterministic compute vs. LLM coordination (`spec.md` §4.1):** Drawing a hard line that software computes tax, risk, attribution, and optimization while the model plans, orchestrates, and explains eliminates the single biggest failure mode of "AI financial advisors."
2. **Dual-plane data architecture (`plan.md` §4):** Separating the Public/Provider plane from the Private Household plane—and keeping raw dollar balances, tax lots, and tax-return text out of model context, persistent agent memory, and external telemetry—is institutional-grade privacy design.
3. **Three-tier tax decomposition (`spec.md` §8.1):** Splitting **Investment Lot/Event accounting** from **Annual Household Tax (PolicyEngine US)** and **Long-Horizon Optimization (Owl)** accurately reflects the real domain boundaries uncovered in `research.md` §7 (Owl's average-cost/whole-year residency simplifications vs. PolicyEngine's annual statutory modeling).
4. **Honest capability states & data-rights enforcement (`spec.md` §8.4, §10):** Prohibiting a single `supported=true` state boolean in favor of a 17-field 51-jurisdiction matrix, enforcing `fmp_cached`-first routing, and air-gapping TradingView MCP from scheduled/automated pipelines prevent silent compliance and numerical traps.

### Top 4 risks to resolve before G1 approval

1. **"Opaque Numeric Blindness" in LLM explanations (`spec.md` §6, `plan.md` §4):** If Hermes sees *only* opaque scenario IDs and coarse finding codes without normalized relative ratios (basis points, weights, marginal rate brackets, holding-period days), the agent cannot reason meaningfully about tradeoffs—it degrades into a rigid template filler. Simultaneously, the client-side UI hydration contract that turns opaque IDs into exact dollar figures for the user is referenced conceptually but never specified at the wire/token level.
2. **Single-machine Windows resource & service sprawl (`spec.md` §11, `plan.md` §12):** Running native MySQL, Hermes Agent + Scheduler, Hermes WebUI, LiteLLM, local LLM inference (`vllm`/`llama-server`), local embeddings, Docling OCR/layout models, Paperless-ngx (+ its DB/broker), Qdrant, PolicyEngine US (pandas 3+), Owl, OpenBB Workspace, and three OpenBB Python services on one Windows workstation creates severe RAM/VRAM contention and operational fragility unless services are tiered into **Resident Core** vs. **Ephemeral On-Demand Workers**.
3. **Database boundary ambiguity vs. existing repository tools (`plan.md` §3, §4, §12; `research.md` §2):** The proposal repeatedly pairs "Native Windows MySQL" with "Existing local SQL infrastructure" without reconciling that the repository *already* enforces an append-only user-local SQLite architecture (`~/.portfolio_importer/positions.db`) for private brokerage snapshots, a separate SQLite database for TechTrade T5 paper trading, and MySQL for `fmp_cached` market data (plus legacy `float`-based ESPP loading in `load_espp_plan.py`).
4. **Linear roadmap bottleneck around year-end tax value (`spec.md` §12):** Gating *all* Household & Federal/CA tax foundation work (Phase 3) behind 100% completion of all 25 notebooks + 11 doc examples (Phase 2, including YFinance variants and TechTrade tuning chapters) delays the highest-value personal tax/planning workflows by 6–10+ weeks—missing critical year-end (Dec 31) and Q4 estimated-tax (Jan 15) decision windows.

---

## 2. Architecture & Engineering Recommendations (Codebase-Grounded)

### R1. Define a 3-Tier "Model-Safe Quantitative Signal" Contract + UI Hydration Protocol

**Problem:** `spec.md` §6 states *"Exact private monetary values can be rendered locally in authenticated widgets without placing those values in an LLM prompt. The model can reference opaque scenario IDs and safe finding codes; the UI joins authorized numeric artifacts for the user."* However, `plan.md` defines neither (a) what quantitative signals the model *is* allowed to see to compare candidates intelligently, nor (b) how Hermes WebUI hydrates opaque references inline.

**Recommendation:**

1. **Formalize three data-visibility tiers in `plan.md` §4:**
   - **Tier 0 — Exact Private Identifiers & Amounts (Never in LLM prompt by default):** Dollar balances, share quantities, dollar tax liabilities, SSNs/TINs, account numbers, employer names, street addresses, raw OCR text.
   - **Tier 1 — Normalized Analytical Signals (Permitted in local-only LLM context):** Dimensionless ratios and bounded domain signals that enable genuine financial reasoning without revealing net worth or identity—e.g., portfolio weight `%` (`18.4% vs 10.0% IPS cap`), tracking-error delta in bps (`-38 bps`), tax-efficiency ratio (`tax_cost / risk_reduction_bps`), statutory marginal bracket `%` (`37.0% Fed + 13.3% CA`), days remaining to long-term capital-gain status (`19 days`), wash-sale lockout booleans, and Pareto-frontier dominance flags.
   - **Tier 2 — Gate-Approved Ephemeral Local Raw Context:** Explicitly disabled by default; if later enabled by human policy override for a specific local-only document review, enforce zero message logging, in-memory-only context, automatic session purge, and verified loopback-only egress.
2. **Specify a deterministic UI Metric-Token Hydration Contract in `plan.md` §1 / §5:**
   - Have Hermes emit structured inline placeholders such as `[[metric:run_id:artifact_id:field_key]]` (for prose) and `EvidenceCardRef(run_id, artifact_id, schema_kind)` (for tables/charts).
   - Hermes WebUI resolves those tokens **client-side in the browser** via an authenticated loopback request directly to the Private Artifact Service (`GET /private/runs/{run_id}/metrics`), rendering exact formatted currency (`$14,820`), delta badges, and hover provenance tooltips—without exact dollar figures ever traversing Hermes Agent, LiteLLM, or chat transcript storage.

### R2. Codify the Physical Persistence Matrix (MySQL vs. Encrypted Local SQLite)

**Problem:** Cross-checking the repository reveals four distinct persistence mechanisms already in flight:
- **MySQL** (`fmp_cached` market/fundamental cache; also targeted by legacy `openbb_platform/tools/portfolio_utils/portfolio_utils/load_espp_plan.py`).
- **User-local append-only SQLite** (`~/.portfolio_importer/positions.db` in `openbb_platform/tools/portfolio_snapshot_importer/`, with `(source_sha256, user_id)` idempotency, Outside-Repo path validation, and filename-only provenance).
- **TechTrade paper SQLite** (`techtrade/08-t5-paper-trading-engine-walkthrough.ipynb`).
- **Paperless-ngx / Qdrant stores** (proposed in W10).

**Recommendation:** Add an explicit **Physical Persistence Matrix** to `plan.md` §4 and §12:

| Plane / Domain | Canonical Store | Why | Backup & Encryption Rule |
|---|---|---|---|
| Public market & fundamental cache (`fmp_cached`) | Native Windows MySQL | High-concurrency analytical cache shared across OpenBB extensions; zero household PII. | Standard DB backups (e.g., `Z:\DBBackup`); never co-mingle private tax/household tables here. |
| Private brokerage snapshots, lots, household facts, tax scenarios | Dedicated private SQLite/SQLCipher DB (extending `~/.portfolio_importer/` outside repo) *or* dedicated encrypted schema under separate OS service account | Preserves append-only snapshot provenance already built in `portfolio_snapshot_importer`; isolates private backup/restore/tombstone lifecycle from market cache. | Encrypted at rest (SQLCipher or Windows DPAPI/BitLocker volume); strict single-user Windows ACLs; outside Git root enforced by `Config._validate_outside_repo()`. |
| Durable run/job/approval/evidence registry | Dedicated operational store (`notebook_guide` / MCP registry) | Stores opaque IDs, input SHA256s, nonces, and stage state—safe to inspect for debugging without exposing dollar amounts. | Local authenticated access; optimistic concurrency (`state_version`). |
| Private document vault & retrieval index | Content-addressed encrypted local vault + SQLite FTS5 (+ optional Paperless-ngx / Qdrant) | Keeps original PDFs immutable by SHA256 and indexes rebuildable from source + tombstones. | Tombstone replay required on restore before re-enabling search (`PF-24`). |

**Related code debt to record in `research.md` R15:** Both `load_espp_plan.py` and `share_cost_basis.py` currently represent prices, FMVs, and cost basis as Python `float` rather than `Decimal`, and `load_espp_plan.py` writes `ESPP_Plan` directly to MySQL. Flag both for migration to `Decimal` contracts (`TaxLot` / `InvestmentEvent` in `plan.md` §5) and private-plane storage during Phase 3/4.

### R3. Expand `research.md` §2 to Credit Existing Reusable Tools in `openbb_platform/tools/`

`research.md` R15 mentions only `load_espp_plan.py` and `share_cost_basis.py`. The baseline already includes several high-leverage utilities under `openbb_platform/tools/` that directly accelerate Phases 0, 3, 4, and 5:

- [`openbb_platform/tools/portfolio_snapshot_importer/`](../../../openbb_platform/tools/portfolio_snapshot_importer/README.md): Append-only, SHA256-idempotent brokerage CSV ingestion (`Portfolio_Positions_*.csv`) with an extensible `LOADERS` registry designed for Schwab, Vanguard, and IBKR alongside Fidelity. Reuse this as the ingestion spine for `AccountSnapshot` rather than inventing a parallel CSV importer.
- [`openbb_platform/tools/portfolio_export/`](../../../openbb_platform/tools/portfolio_export/): Manual-login Playwright export scaffolding with `Config._validate_outside_repo()` path-boundary checks.
- [`mortgage_amortization.py`](../../../openbb_platform/tools/portfolio_utils/portfolio_utils/mortgage_amortization.py): Existing `MortgageCalculator` supporting full amortization schedules and `extra_monthly` principal paydown—directly reusable inside W9 (Household Goals & Debt Tradeoffs).
- `enrich_cusip_figi.py`, `populate_cusip_map.py`, `refresh_etf_holdings_cache.py`, `ingest_sec_13f.py`, and `populate_market_holidays.py`: Reusable building blocks for cross-broker security identity resolution (critical for cross-account wash-sale detection when one account reports CUSIP and another reports ticker) and market-holiday-aware scheduling (`plan.md` §9).

### R4. Align `notebook_guide/contracts.py` Access Tiers & Workspace Agent Coexistence (`#1272`)

1. **Extend `Access` and `StageKind` cleanly:** In [`contracts.py`](../../../openbb_platform/extensions/agents/openbb_agents/notebook_guide/contracts.py), `Access` is currently `Literal["metadata", "provider_read", "private_read", "analysis", "artifact", "paper"]`, where `"private_read"` specifically means sanitized `portfolio_basket` reads. Do not overload `"private_read"` for raw tax-lot, household, or tax-return vault operations. Propose `schema_version: 2` (or additive literals) introducing `"household_meta"`, `"tax_compute"`, and `"document_evidence"` so fail-closed profile checks distinguish sanitized portfolio analytics from household tax engines.
2. **Unify Workspace `/query` (`#1272`) and Hermes WebUI:** Handoff evidence from `#1272 ([portfolio-ux] Align Workspace agent capabilities)` shows `openbb_portfolio/copilot.py` already serves `/agents.json` + `/query` with 59 readable widgets, 2 denied mutation widgets (`pi_paper_ticket`, `pi_backtest_button`), provenance status updates, and external-provider redaction. Specify in `plan.md` §3 how new Household/Tax/Retirement native Workspace widgets interact with `copilot.py`:
   - Mark all new private Household/Tax/Document widgets as **denied on external-model Workspace agents** (`AGENT_DENIED_WIDGETS` or `privacy_class="household_private"` in `agent_policy.py`), preventing accidental leakage if a user selects a Tax Center widget while using a cloud-backed Workspace copilot.
   - Optionally register a second local-only Workspace agent endpoint (`/hermes-local/agents.json`) backed by the same native Hermes + local LiteLLM runner so drill-through into OpenBB Workspace preserves conversational continuity safely.

### R5. Introduce a "Resident Core vs. On-Demand Worker" Architecture &VRAM Arbiter

**Problem:** Running 10+ persistent services plus local LLM, OCR VLM, and embedding models simultaneously on one Windows host risks OOM crashes, GPU VRAM thrashing, port collisions, and brittle startup scripts.

**Recommendation:**

1. **Split runtime topology into two tiers in `plan.md` §12:**
   - **Resident Core (Always-On during active session):** Native MySQL, LiteLLM Gateway + Local Chat/Tool LLM, Native Hermes Agent/Scheduler + Hermes WebUI, OpenBB Portfolio/Platform MCP + Widget Backend.
   - **Ephemeral / On-Demand Workers (Spawned or woken per job, auto-idle unload):**
     - *Tax & Retirement Subprocess Workers:* PolicyEngine US (isolated `pandas>=3` venv) and Owl invoked via bounded local JSON-RPC / stdio / loopback worker with idle shutdown (e.g., 5-minute TTL).
     - *Document Ingestion Worker:* Docling OCR/table extraction runs only during explicit upload jobs, running either on CPU/ONNX or acquiring a GPU lease via LiteLLM/orchestrator before unloading so full VRAM returns to the primary reasoning model.
2. **Make Paperless-ngx Optional in Phase 3a ("Vault-Lite First"):**
   - For a single household uploading ~20–60 documents per year (W-2s, 1099s, 1040/540 returns, 3921/3922 statements, closing disclosures), deploying full Paperless-ngx (Django + Celery + Redis + PostgreSQL/MariaDB + Tika/Gotenberg containers) before getting basic W-2/1040 extraction working is heavy yak-shaving.
   - **Better path:** Implement **Vault-Lite** in Phase 3a as an encrypted, content-addressed local directory (`sha256/<doc_id>.pdf`) + `DocumentVersion` / `Extraction` / `AcceptedFact` SQLite tables + Docling parser + SQLite FTS5 exact search. Make **Paperless-ngx an optional upstream sync source** for users who already run it for household mail scanning, and keep **Qdrant optional** behind the synthetic retrieval benchmark gate already wisely proposed in `spec.md` §10.

### R6. Concrete Hardening Invariants for LiteLLM & Hermes Self-Improving Skills

1. **LiteLLM Startup Audit (`plan.md` §12):** Explicitly require an automated preflight (`scripts/hermes_preflight.py`) that inspects the live LiteLLM route table and refuses to start private workflows unless:
   - `finance-local-*` aliases map exclusively to `127.0.0.1` / `::1` inference servers owned by verified local PIDs;
   - router `fallbacks`, `context_window_fallbacks`, and `content_policy_fallbacks` for those aliases are empty (`[]`);
   - `turn_off_message_logging=True`, `telemetry=False`, and external callback integrations (Langfuse, Helicone, OpenTelemetry remote exporters, DB prompt logging) are disabled on private routes;
   - Windows Defender Firewall outbound block rule is verified on the local model-runner executable as OS-level defense-in-depth.
2. **Read-Only Skill Mount for Hermes (`spec.md` §4.8, `plan.md` §11.1):** Enforce Principle 8 (*"Hermes may propose better research skills; it may not rewrite tax rules, risk limits or approvals"*) structurally by mounting the active `skills/` directory **read-only** to the Hermes process OS identity. Route any agent-proposed skill improvements to a quarantined `proposed_skills/` directory as diff artifacts that require human review and git commit.

### R7. Align Program Governance with Dev Strategy v4 (`#1277`)

Per `docs/dev-strategy.md` (`#1277 (Adopt Dev Strategy v4)`), Spec Kit artifacts live at `specs/gh-<NN>-<slug>/{spec,plan,tasks}.md` with 1 sub-issue per user story and red-first real-path verification. Clarify in `plan.md` §14 that:
- `#1312 ([notebook-agent] Propose Hermes integration and unified financial-planning capabilities)` serves as the **Program Architecture & Direction Proposal** (`tracking:container` once decomposed).
- Upon G1 direction approval, each roadmap phase (Phase 0, Phase 1, Phase 2A, etc.) spawns its own right-sized Spec Kit feature directory under `specs/gh-<child>-<slug>/` rather than cramming a 30-week program into a single monolithic `tasks.md`.
- Phase 0's very first committed deliverable should reconcile the **21/25 notebook source-hash mismatches** in `docs/cross_repo_workflow/notebook-mcp-story-inventory.csv` and add a CI check so notebook edits can never silently drift from story manifests again.

---

## 3. Tax, Legal-Boundary & Domain Accuracy Improvements

`spec.md` §8 is already thoughtful, especially on ESPP compensation vs. basis and 51-state honesty. Adding the following specific US Federal + California mechanics will elevate the tax specification from "good generalist requirements" to **CPA-grade edge-case precision**:

### T1. Explicit California Tax Traps to Add to `spec.md` §8.3

1. **California "30 / 40 / 0 / 30" Estimated Tax Schedule & $1M AGI Safe-Harbor Cliff:**
   - Unlike Federal quarterly installments (25% / 25% / 25% / 25%), California Form 540-ES requires **30% in Q1 (Apr 15), 40% in Q2 (Jun 15), 0% in Q3 (Sep 15), and 30% in Q4 (Jan 15)**—meaning **70% of annual CA tax is due by June 15**.
   - Worse, once California AGI reaches **$1,000,000** ($500k MFS), California **completely eliminates the 110% prior-year safe harbor**, forcing 90% current-year tax accuracy (or FTB Form 5805 annualized income installment accounting). This is a top pain point for equity-compensated CA taxpayers and belongs explicitly in §8.3 and §13 validation tests.
2. **Uncapped California SDI Payroll Tax on Wages/RSUs/NSOs:**
   - Beginning in 2024, California repealed the wage ceiling on State Disability Insurance (SDI, ~1.1%+ on *all* wages, bonuses, RSU vests, and NSO exercises with no cap). Ignoring uncapped CA SDI systematically understates marginal payroll taxes on equity compensation in W4 and W5.
3. **California Mental Health Services Tax (1% surcharge > $1M taxable income):**
   - Explicitly test the 1% surcharge cliff pushing top CA statutory marginal rate from 12.3% to 13.3% (14.4%+ including uncapped SDI on compensation).
4. **US Treasury vs. Municipal Bond State-Tax Asymmetry (28 U.S.C. § 3124):**
   - Interest from direct US Treasuries (T-bills/notes/bonds) and qualifying Treasury ETFs/money-market funds (provided the fund meets California's **≥50% quarterly asset threshold** under CA Rev. & Tax Code § 17145!) is **100% exempt from California state income tax** while federally taxable. Conversely, non-California municipal bond interest is **taxable in California**. Failing to model CA's 50% fund-asset threshold and Schedule CA Treasury subtraction leaves thousands of dollars on the table for cash reserves.
5. **Mortgage Interest Acquisition-Debt Nonconformity ($750k Federal vs. $1M California):**
   - Federal law caps deductible acquisition mortgage debt at $750,000 (for post-2017 loans), whereas California still conforms to the pre-TCJA **$1,000,000 acquisition debt limit** (Schedule CA adjustment). Essential for W9 mortgage/refinance/paydown analysis in California.

### T2. Post-2025 Federal Statutory Versioning & SECURE 2.0 Rules (`spec.md` §8.2, §8.6)

- **Statutory Law Manifest (`tax_law_manifest.json`):** Because 2025–2027 spans major federal statutory transitions (post-2025 TCJA extension/amendment provisions, SALT deduction cap rules/phaseouts, AMT exemption thresholds, standard deduction levels, and SECURE 2.0 effective dates such as mandatory Roth catch-up contributions for prior-year FICA wages >$145k indexed and ages 60–63 enhanced catch-up limits), require every tax-engine run to emit the exact statutory parameter manifest version alongside `tax_year`.
- **IRS Form 8949 Basis Adjustment Codes (`B`, `E`, etc.) & Supplemental Lot Reconciliation:** Require the lot layer (`plan.md` §5 `TaxLot`) to distinguish **1099-B Box A/D (basis reported to IRS)** vs. **Box B/E (basis not reported)** and explicitly track **Employer Supplemental Stock Plan Lot Statements** alongside Form 3921 (ISO) and Form 3922 (ESPP), since brokers routinely report unadjusted grant/purchase price on 1099-B while ordinary income is already included in W-2 Box 1.

### T3. Golden-Oracle Verification Strategy (`plan.md` §10, §13)

- Specify *how* tax accuracy is proven independent of PolicyEngine's internal unit tests: maintain a versioned **Synthetic Tax Return Golden Suite** (~15–25 canonical synthetic households: W-2 only, RSU+ESPP qualifying vs. disqualifying disposition, ISO AMT trigger + Form 8801 credit recovery, CA $1.2M AGI with Treasury ETF dividend subtraction and HSA adjustment, wash sale across taxable + IRA, Backdoor Roth Form 8606 pro-rata trap, WA capital gains excise tax). Each case asserts exact form-line outputs derived directly from IRS/FTB worksheets.

---

## 4. Suggested New Features (High-Value Additions Aligned with Proposal Intent)

The existing `PF-01` through `PF-26` and `W1` through `W10` establish a strong foundation. Below are **12 high-leverage feature proposals (`PF-27` to `PF-38`)** and **4 workflow extensions (`W11` to `W14`)** tailored specifically for a single-household private financial advisor, portfolio manager, and US/CA tax strategist. None require adding a new UI shell or competing ledger.

| Proposed ID | Feature Title | User Problem Solved & Core Deterministic Logic | Target Phase |
|---|---|---|---|
| **PF-27** *(W11)* | **Safe-Harbor & Paycheck Withholding Pacing Optimizer** | Tracks YTD W-2 withholding + estimated payments against Federal (90% current / 100–110% prior year) and California (**30/40/0/30 schedule** + **$1M AGI cliff**). Compares quarterly estimated vouchers vs. **late-year W-4 extra payroll withholding** (treated as paid ratably across all 4 quarters to cure earlier underwithholding without penalties!) vs. **Annualized Income Installment** (IRS Form 2210 Sched AI / CA Form 5805). | Phase 3 |
| **PF-28** | **Cross-Account Asset Location & After-Tax Yield Optimizer** | Optimizes *which wrapper holds which asset* across Taxable, Traditional 401(k)/IRA, Roth, and HSA. Computes **Tax-Equivalent Yield** for cash/fixed income (e.g., direct T-bills / CA-qualifying ≥50% US Treasury ETFs vs. bank HYSA vs. CA munis) and applies **CA-specific HSA location rules** (avoiding high-churn/taxable distributions inside an HSA since CA taxes HSA interest, dividends, and realized gains annually). | Phase 3 / 4 |
| **PF-29** *(W12)* | **Effective Marginal Tax Rate (EMTR) "Torpedo & Cliff" Radar** | Statutory brackets hide violent marginal rate spikes caused by NIIT (+3.8%), Additional Medicare (+0.9%), AMT phaseout (effective 35%), SALT phaseout cliffs, ACA subsidy cliffs, Medicare **IRMAA 2-year lookback cliffs** (where $1 of extra MAGI triggers thousands in flat premium surcharges), and CA +1% Mental Health tax at $1M. Sweeps `+$1k` increments of ordinary income and LTCG around baseline in PolicyEngine to render an interactive **Headroom & Cliff Chart** for Roth conversions, gain harvesting, and ISO exercises. | Phase 3 / 4 |
| **PF-30** | **RSU Withholding-Gap Earmarker & ISO/AMT Credit Multi-Year Simulator** | Solves the two most painful equity-comp surprises: (1) **RSU Supplemental Under-Withholding Gap**—computes the exact shortfall between flat statutory employer withholding (22% Fed / 10.23% CA) and true household marginal rate on every RSU vest, earmarking the exact cash reserve into T-bills; (2) **ISO Bargain-Element & Form 8801 Credit Lifecycle**—calculates maximum AMT-free ISO exercise shares by Dec 31 and models multi-year recovery of Minimum Tax Credit carryforwards. | Phase 4 |
| **PF-31** | **Retirement Contribution Waterfall & Form 8606 Pro-Rata Guard** | Automates annual contribution routing across 401(k) pre-tax/Roth (§402(g) multi-employer collision check + employer match true-up protection), **Mega Backdoor Roth** (§415(c) per-plan limit), HSA, 529, and **Backdoor Roth IRA**—enforcing a hard **Dec 31 Traditional/SEP/SIMPLE/Rollover IRA Zero-Balance Guardrail** so IRC §408(d)(2) pro-rata aggregation never surprises the household, while tracking cumulative Form 8606 basis. | Phase 4 |
| **PF-32** | **Tax-Loss Harvesting Pair Registry & 61-Day Household Wash-Sale Shield** | Upgrades passive wash-sale checking into proactive harvesting: maintains a reviewed **Substitute Pair Catalog** (economically correlated ETFs tracking *distinct* indices, e.g., S&P 500 vs. Russell 1000 / Total US Market, while blocking substantially identical pairs like `SPY`/`IVV`/`VOO`) and enforces a **61-Day Lockout Calendar (`t-30` to `t+30`)** across *all* household accounts, scheduled DRIPs, spouse IRAs, and upcoming RSU vests / ESPP purchase dates. | Phase 3 / 4 |
| **PF-33** | **Charitable Appreciated-Lot & Multi-Year DAF "Bunching" Optimizer** | Ranks long-term (>1 yr) appreciated taxable stock lots by unrealized gain % for in-kind donation (eliminating up to 23.8% Fed + 13.3% CA capital-gains tax while claiming full FMV deduction up to 30% AGI cap with 5-year carryforward). Compares annual cash/stock donations vs. **2- or 3-year Donor-Advised Fund (DAF) bunching** timed to peak income / RSU vest / Roth conversion years. | Phase 4 |
| **PF-34** *(W13)* | **Household ALM Stress-Tester & After-Tax Debt/Refinance Analyzer** | Extends `mortgage_amortization.py` and W9 into full **Household Asset-Liability Management**: simulates correlated tail shocks (*e.g., -35% market drawdown + -50% employer stock + 12-month income loss*), computing **True After-Tax Liquid Runway (months)** via an optimal liquidation waterfall, and evaluates mortgage extra-principal / refinance breakevens incorporating the $750k Fed vs. $1M CA mortgage deduction asymmetry. | Phase 3 / 5 |
| **PF-35** | **Decision Journal, Thesis-Invalidation Watchdog & Counterfactual Audit** | Turns immutable `RunPlan` + `EvidenceEnvelope` records into an institutional **Decision Ledger**: every executed rebalance, single-name buy/sell, tax harvest, or conversion stores its explicit thesis, invalidation triggers (e.g., Phase 2–4 fundamental thresholds from `Analysis/stock_analysis.py`), and `do-nothing` shadow portfolio. Automatically evaluates **90/180/365-day Ex-Post After-Tax Alpha vs. Do-Nothing** to measure whether decisions actually added value. | Phase 2 / 4 |
| **PF-36** *(W14)* | **Pre-Filing Draft Tax Return Diff & CPA Error/Carryforward Auditor** | Extends W10 Document Vault at filing time: compares an uploaded **Draft 1040 + CA 540 PDF** against the year's accepted source docs (W-2, 1099-B/DIV/INT, 3921/3922, Supplemental Stock Plan Statement) and prior-year filed return. Deterministically flags the top costly errors: unadjusted RSU/ESPP basis on Form 8949 (double taxation), dropped capital-loss / AMT-credit / charitable carryforwards, missing Form 8606 continuity, missing CA Treasury interest subtraction, and unexplained >25% YoY line variances. | Phase 3a / 4 |
| **PF-37** | **Early-Retirement Bridge, 5-Year Roth Ladder & Healthcare/IRMAA Planner** | Complements Owl's long-horizon solver with exact **pre-59½ / pre-65 statutory bridge mechanics**: tracks per-conversion **5-Year Roth Aging Clocks**, Rule of 55 / §72(t) SEPP constraints, **ACA Premium Tax Credit MAGI thresholds** before age 65, **Medicare IRMAA 2-year lookback management** starting at age 63, and **Dynamic Spending Guardrails** (Guyton-Klinger / floor-ceiling rules) under sequence-of-returns stress. | Phase 4 / 5 |
| **PF-38** | **Account Titling, Beneficiary & Household Continuity Hygiene Audit** | Operational risk module (explicitly non-legal): audits every enrolled account in `HouseholdSnapshot` for missing/stale primary & contingent beneficiaries, Revocable Living Trust / TOD / POD titling gaps (vital in California to avoid statutory gross-value probate fees), umbrella/property insurance renewal & coverage ratios vs. net worth, and exports an encrypted offline **"In Case of Emergency" Continuity Map** (institutions, account types, advisor/CPA contacts, document vault locations—zero credentials). | Phase 5 |

### Four high-value new workflows enabled by these features

- **W11. Quarterly Safe-Harbor & Withholding Checkup (`PF-27`, `PF-30`):** Triggered 21 days before Apr 15, Jun 15 (CA 40% spike!), Sep 15, and Jan 15, plus after every RSU vest or large realization. Outputs exact Fed + CA voucher vs. W-4 payroll adjustment options.
- **W12. Year-End "Tax Bracket Fill & Cliff Check" (`PF-29`, `PF-31`, `PF-32`, `PF-33`):** Run between Oct 15 and Dec 15; overlays YTD realized income + scheduled Q4 vests/dividends onto the EMTR Cliff Radar to size optimal tax-loss harvests, 0%/15% capital-gain harvesting, Roth conversions, ISO exercises, and DAF appreciated-lot gifts before Dec 31.
- **W13. Household Tail-Risk & Liquidity Fire Drill (`PF-34`):** Stress-tests total household balance sheet + cash burn under severe market + employment shocks, verifying emergency reserve adequacy and tax-optimal cash raising.
- **W14. Pre-Signature Tax Return Audit (`PF-36`, `W10`):** Reconciles CPA/software draft federal + state returns against vault source documents, lot-adjusted basis records, and prior-year carryforwards before the user signs Form 8879.

---

## 5. Roadmap & Sequencing Recommendations

### S1. Split Phase 2 into 2A / 2B to Unlock Tax & Household Value Earlier

In `spec.md` §12, **Phase 2 (3–6 weeks)** requires qualifying all 25 main stories *and* classifying/scheduling all 11 `docs\examples` notebooks before starting **Phase 3 (Household and CA tax foundation)**. Because 8 of the 25 notebooks are `portfolio_yfinance` free-data variants and 9 are `techtrade` chapters, waiting for 100% completion of all 36 notebooks needlessly blocks core personal wealth & tax planning.

**Recommended resequencing:**

1. **Phase 0 (1–2 wks):** Baseline reconciliation + fix the **21/25 notebook source-hash mismatches** + verify LiteLLM/Windows runtime preflight + Physical Persistence Matrix decision.
2. **Phase 1 (2–3 wks):** Hermes WebUI -> Native Hermes -> Policy Adapter -> `portfolio/03` Basket X-Ray vertical slice + Client-Side Metric-Token Hydration (`R1`) proof.
3. **Phase 2A (2–3 wks):** Complete core `portfolio/01–08` stories (including `Analysis/stock_analysis.py` 7-phase deep dive and what-if/attribution) + Decision Journal foundation (`PF-35`).
4. **Phase 3 (4–6 wks, can run immediately after Phase 2A or in parallel with Phase 2B):** Household intake, encrypted private store (`R2`), PolicyEngine US isolated worker, Federal + CA qualified subset (`T1`, `T2`), Safe-Harbor Pacing (`PF-27`), EMTR Cliff Radar (`PF-29`), and Tax-Aware Rebalance (`W3`).
5. **Phase 2B (2–4 wks, parallelizable):** Remaining `techtrade/01–09` stories, `portfolio_yfinance/01–08` fixture parity, and 11 `docs\examples` notebook qualifications.
6. **Phase 3a (2–3 wks):** **Vault-Lite** (`R5`: content-addressed encrypted PDF vault + Docling + SQLite FTS5) + Pre-Filing Return Auditor (`PF-36`); keep Paperless-ngx and Qdrant optional behind explicit gates.
7. **Phase 4 (4–7 wks):** Equity comp & lot engine (`PF-30` RSU withholding gap + ISO/AMT, ESPP `Decimal` migration), Wash-Sale Shield (`PF-32`), Asset Location (`PF-28`), Contribution/8606 Guard (`PF-31`), DAF Optimizer (`PF-33`), and Owl Retirement + Pre-65 Bridge (`PF-37`).
8. **Phase 5 (4–8+ wks):** Pilot states (WA, NY/NYC, TX, MA, NJ), Household ALM Stress-Tester (`PF-34`), Continuity Hygiene (`PF-38`), and bounded scheduled briefings (`W1`, `W11`).

### S2. Define Hardware & Model Qualification Tiers Upfront (Phase 0 Gate)

`spec.md` §11 rightly refuses to promise local-model capability on unmeasured hardware, and notes that *"Private local-model approval/qualification is not included in that [20–37 week] estimate."* Make **Host Resource & Tool-Call Benchmark** a crisp **2-day task inside Phase 0** rather than an unbounded external unknown:
- Measure available Windows GPU VRAM and system RAM.
- Benchmark 2–3 local models via LiteLLM against a 20-prompt synthetic `notebook_guide` structured tool-calling & abstention harness (testing JSON schema adherence, zero hallucinated numbers when fields are opaque IDs, p95 latency, and VRAM ceiling alongside CPU/ONNX embeddings).

---

## 6. Surgical Document-by-Document Update Checklist

When ready to fold selected recommendations into the main proposal files, apply them at these exact locations:

### In `spec.md`
- **§5 Functional Requirements:** Append selected features from `PF-27` through `PF-38` (highest priority: `PF-27` Safe-Harbor Pacing, `PF-28` Asset Location & CA Treasury Yield, `PF-29` EMTR Cliff Radar, `PF-30` RSU Withholding Gap & ISO/AMT Credit, `PF-35` Decision Journal, `PF-36` Draft Return Auditor).
- **§6 User Experience / Agent Interaction:** Specify the **3-Tier Model-Safe Signal rule** (Tier 1 ratios/bps allowed for reasoning; Tier 0 dollar values hydrated client-side via `[[metric:...]]` tokens).
- **§7 Core Workflows:** Add `W11` (Quarterly Safe-Harbor & Withholding Checkup), `W12` (Year-End Bracket Fill & Cliff Check), `W13` (Household Tail-Risk Stress Test), and `W14` (Pre-Signature Return Audit); update `W10` to make **Vault-Lite (Encrypted SHA256 store + Docling + SQLite FTS5)** the default Phase 3a baseline with Paperless-ngx optional.
- **§8.3 California First:** Explicitly add the **30/40/0/30 estimated payment schedule**, **$1M AGI elimination of the 110% prior-year safe harbor**, **uncapped CA SDI payroll tax**, **1% Mental Health Services surcharge**, **≥50% fund threshold for US Treasury state-tax exemption**, and **$1M CA vs. $750k Fed mortgage acquisition-debt nonconformity**.
- **§12 Delivery Roadmap:** Split Phase 2 into **Phase 2A (`portfolio/01–08`)** and **Phase 2B (`techtrade`, `portfolio_yfinance`, `docs\examples`)** so Phase 3 Federal+CA tax work is not blocked behind free-provider and TechTrade workbook parity; fold the 2-day local-model tool-calling benchmark into Phase 0.

### In `plan.md`
- **§1 & §4 Data Planes / Output Separation:** Add the **Physical Persistence Matrix** (MySQL strictly for `fmp_cached` public cache; dedicated encrypted local SQLite/SQLCipher store outside repo for private household/lot/tax data) and the **Client-Side Metric-Token Hydration wire flow**.
- **§3 Reuse Map:** Add `portfolio_snapshot_importer`, `portfolio_export`, `mortgage_amortization.py`, CUSIP/holiday utilities, and the Workspace `/query` (`#1272`) `AGENT_DENIED_WIDGETS` rule for private Household/Tax widgets.
- **§5 Proposed Domain Contracts:** Add `DecisionRecord` (for `PF-35`), `StatutoryLawManifest` (`tax_law_manifest.json`), Form 8949 box/adjustment fields on `TaxLot`, and `schema_version: 2` access literals (`household_meta`, `tax_compute`, `document_evidence`) extending `notebook_guide/contracts.py`.
- **§12 Local Deployment & Operations:** Separate **Resident Core** from **On-Demand Ephemeral Workers** (VRAM arbiter for LLM vs. Docling OCR; idle-timeout subprocess workers for PolicyEngine pandas 3+ and Owl), add the **LiteLLM `hermes_preflight.py` startup invariants**, and specify **read-only `skills/` OS mount + `proposed_skills/` quarantine**.
- **§13 Validation Design:** Add the **Synthetic Tax Return Golden Suite** (worksheet-verified form-line assertions) and CA 30/40/0/30 + $1M cliff + uncapped SDI discriminating test cases.
- **§14 Integration Policy:** Clarify Dev Strategy v4 (`#1277`) decomposition (`#1312` as `tracking:container` epic spawning per-phase `specs/gh-<child>-<slug>/` Spec Kit bundles).

### In `research.md`
- **§2 Existing Product Foundation (R15):** Expand R15 to document `portfolio_snapshot_importer` (`~/.portfolio_importer/positions.db`), `portfolio_export`, `mortgage_amortization.py`, and CUSIP/market-holiday utilities—and explicitly note that `load_espp_plan.py` and `share_cost_basis.py` currently use `float` and MySQL, requiring `Decimal` + private-plane migration.
- **§6 Private Document/Search Additions:** Record **Vault-Lite (Content-addressed encrypted store + Docling + SQLite FTS5)** as the low-ops single-user baseline before full Paperless-ngx + Qdrant container stacks.
- **§8 Official Tax-Source Register:** Add **IRS Form 2210 / Publication 505** (withholding & annualized installments), **IRS Form 6251 / Form 8801** (ISO AMT & Minimum Tax Credit carryforward), **IRS Form 8606** (non-deductible IRA basis & pro-rata aggregation), **FTB Form 540-ES & Form 5805** (CA 30/40/0/30 installments & $1M AGI safe-harbor disqualification), and **CA Rev. & Tax Code § 17145 / FTB Pub 1001** (US Treasury interest subtraction & 50% fund asset threshold).
