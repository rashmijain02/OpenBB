# Issue / PR number map: `prajoria/OpenBB` → `rashmijain02/OpenBB`

Generated 2026-11-02 when this repo became an independent fork. Issue and PR numbers that appear in
docs, commit messages and `gh-NNNN` branch names use the **old `prajoria/OpenBB` numbering**.

- **Open issues** were re-created here (with comments, labels and milestones). Table 1 gives the new number.
- **Closed issues and PRs** were *not* re-created. Tables 2 and 3 are a title-only index so an old number can still be resolved.
- Open PR `#895` (a 2026-07 upstream-sync PR) was not migrated.
- Nothing in this repo links back to `prajoria/*`; old numbers are written as plain text.

## 1. Open issues (old → new)

| Old # | New # | Title |
|---|---|---|
| 18 | #1 | feat(agents): build a Test Harness for golden evals (synthetic + realistic FMP data) |
| 20 | #2 | Consolidate triple-duplicated stock_analysis.py / db.py into a single shared module |
| 54 | #3 | Implement: event-driven engine (zipline-reloaded + Pipeline) |
| 60 | #4 | Implement: optional non-vendored engine adapters |
| 61 | #5 | Implement: test harness, CI jobs & NFR benchmarks |
| 62 | #6 | Implement: hardware acceleration & compute backend (CPU/GPU) |
| 63 | #7 | [Epic] openbb-techtrade — technical-indicator trading engine |
| 87 | #8 | [Epic] P9 (future) — streaming/intraday + live broker |
| 88 | #9 | Dual entry options: market + limit entry price on TradePlan |
| 91 | #10 | Disposition of 3-tier FMP/CBOE historical-data fallback (fork commit prajoria/FinanceToolkit@8b75664) |
| 94 | #11 | Standardize submodule locations under third_party/ (audit copilot-api + pandas-ta-classic outliers) |
| 96 | #12 | 13F resolver follow-up: refresh stale FIGI values (>~18 months) in sec_13f_cusip_map |
| 99 | #13 | SEC Form N-PORT ingest (bulk historical + per-CIK incremental) — un-park #97 T2+T3 |
| 102 | #14 | Epic: openbb-extension-pine — first-class Pine Script compatibility extension |
| 106 | #15 | [pine] Phase 0: Foundation — counsel sign-off, scaffold, submodule pin, wild-corpus baseline |
| 107 | #16 | [pine] Phase 1: MVP — 30 wild-corpus-ranked builtins, FMP + BYO primary series, v5+v6, >=40% wild-corpus coverage |
| 108 | #17 | [pine] Phase 2: Strategies + cross-timeframe — strategy(), FMP-routed request.security, fills, KPIs, >=70% |
| 109 | #18 | [pine] Phase 3: Completeness — libraries, drawings, long-tail builtins, >=90% wild-corpus coverage |
| 110 | #19 | [pine] Phase 4: Polish & Launch — docs, widget pack, perf, MCP coverage, PyPI 1.0.0 |
| 116 | #20 | #pine-P1-P3: MCP tool registration |
| 117 | #21 | #pine-P1-P2: Bollinger Bands Workspace widget |
| 119 | #22 | #pine-P1-S-math.sqrt: square root |
| 120 | #23 | #pine-P1-S-math.pow: exponentiation |
| 121 | #24 | #pine-P1-S-math.round: rounding |
| 122 | #25 | #pine-P1-S-math.min: elementwise min |
| 123 | #26 | #pine-P1-S-math.max: elementwise max |
| 124 | #27 | #pine-P1-S-math.abs: absolute value |
| 125 | #28 | #pine-P1-S-math.sum: rolling sum |
| 126 | #29 | #pine-P1-S-ta.barssince: bars-since-true |
| 127 | #30 | #pine-P1-S-ta.cum: cumulative sum |
| 128 | #31 | #pine-P1-S-ta.percentile_linear_interpolation: percentile with lerp |
| 129 | #32 | #pine-P1-S-ta.median: rolling median |
| 130 | #33 | #pine-P1-S-ta.linreg: linear regression value |
| 131 | #34 | #pine-P1-S-ta.sar: parabolic SAR |
| 132 | #35 | #pine-P1-S-ta.tr: true range |
| 133 | #36 | #pine-P1-S-ta.roc: rate of change |
| 134 | #37 | #pine-P1-S-ta.mom: momentum |
| 135 | #38 | #pine-P1-S-ta.change: bar-over-bar difference |
| 136 | #39 | #pine-P1-S-ta.stdev: rolling stdev (population) |
| 137 | #40 | #pine-P1-S-ta.lowest: rolling min |
| 138 | #41 | #pine-P1-S-ta.highest: rolling max |
| 139 | #42 | #pine-P1-S-ta.crossunder: crossunder detector |
| 140 | #43 | #pine-P1-S-ta.crossover: crossover detector |
| 141 | #44 | #pine-P1-S-ta.vwap: volume-weighted average price |
| 142 | #45 | #pine-P1-S-ta.obv: on-balance volume |
| 143 | #46 | #pine-P1-S-ta.mfi: money flow index |
| 144 | #47 | #pine-P1-S-ta.adx: average directional index |
| 145 | #48 | #pine-P1-S-ta.cci: commodity channel index |
| 146 | #49 | #pine-P1-S-ta.stoch: stochastic %K |
| 147 | #50 | #pine-P1-S-ta.atr: average true range |
| 148 | #51 | #pine-P1-S-ta.bb: Bollinger Bands |
| 149 | #52 | #pine-P1-S-ta.macd: moving average convergence divergence |
| 150 | #53 | #pine-P1-S-ta.rsi: relative strength index |
| 151 | #54 | #pine-P1-S-ta.rma: Wilder's smoothing (RSI's smoothing fn) |
| 152 | #55 | #pine-P1-S-ta.wma: weighted moving average |
| 153 | #56 | #pine-P1-S-ta.ema: exponential moving average |
| 154 | #57 | #pine-P1-S-ta.sma: simple moving average |
| 175 | #58 | #pine-P0-L0.1: Outside counsel sign-off on PRD §2 (clean-room SOP + Appendix A) |
| 176 | #59 | #pine-P4: Polish & Launch — docs, perf, MCP coverage, PyPI 1.0.0 (GH #110) |
| 177 | #60 | #pine-P2: Strategies + cross-TF — strategy(), FMP-routed request.security, >=70% (GH #108) |
| 178 | #61 | #pine-P1: MVP — 30 wild-ranked builtins, FMP + BYO, v5+v6, >=40% wild-corpus (GH #107) |
| 183 | #62 | Pine Extension Epic: openbb-extension-pine (project:pine GH #102) |
| 192 | #63 | #pine-P1-X2: Pine v5 roundtrip integration test |
| 193 | #64 | #pine-P3: Completeness — libraries, drawings, long-tail builtins, >=90% (GH #109) |
| 195 | #65 | #99-T9: docs (per-tool specs + DESIGN.md changelog + #97 un-park) |
| 196 | #66 | #99-T8: Tools/enrich_nport_isin_tickers.py — ISIN→ticker enrichment |
| 197 | #67 | #99-T7: extend openfigi.py for ID_ISIN / ID_SEDOL (Q-E E1) — SEPARATE PR against #93 |
| 198 | #68 | #99-T6: wire real _try_nport in fmp_cached/etf_holdings.py |
| 199 | #69 | #99-T5: Tools/ingest_sec_nport.py — bulk + incremental modes |
| 210 | #70 | #97-T3: nport_index write helpers + Tools/ingest_sec_nport.py |
| 211 | #71 | #97-T2: nport_index.py read helpers + DDL |
| 259 | #72 | #89/#93 R7 follow-up: refresh FIGI for sec_13f_cusip_map rows older than ~18 months |
| 263 | #73 | infra: plumb engine _fetcher seams through to public routers (scan/plan/export/simulate/validate) |
| 264 | #74 | infra: pytest collection collision "No module named 'tests.unit'" when scanning openbb_platform tree |
| 266 | #75 | docs(86): add **kw limitation comment to test_examples_smoke.py fake-obb callables |
| 267 | #76 | docs(86): restore test_submodule_pin.py cross-reference in README For Contributors section |
| 268 | #77 | refactor(83): tighten TuningReport.candidate type (Any → IndicatorConfig as Data subclass) |
| 269 | #78 | style(83): test_tune_router.py:215 E731 lambda → def |
| 270 | #79 | docs(83): update tune() Raises docstring for T7 fail-fast guard |
| 271 | #80 | [epic] Analysis Pipeline Hardening — Expert Review Impl |
| 272 | #81 | Phase G2: Publish pipeline_survivorship_report.md in Analysis/docs/ |
| 273 | #82 | Phase G1: Extend PBO/DSR validation to fundamental signals |
| 274 | #83 | Phase F3: Wire re_evaluate() into monitoring triggers + Handoff structure (P7) |
| 275 | #84 | Phase F1: New re_evaluate(symbol, position, updated_data) → Action function |
| 276 | #85 | Phase F2: Position context object (entry price, current P&L, days held, tranches filled) |
| 277 | #86 | Phase E2: Boost P4 score for below-peer-median stocks with above-median growth |
| 278 | #87 | Phase E1: Add pe_vs_peer_median + ev_ebitda_vs_peer_median to P4 ValuationKPIs |
| 279 | #88 | Phase D3: Feed revision + IV/RV signals into P4 verdict + P7 staged_entry |
| 280 | #89 | Phase D2b: Compute implied_vol_vs_realized signal from cboe ATM IV |
| 281 | #90 | Phase D2a: Add cboe as secondary Analysis provider — options chain only (Q-3) |
| 282 | #91 | Phase D1: Ingest analyst estimate revisions magnitude (3m delta %) |
| 283 | #92 | Phase C4: Preserve magnitude — MACD score = clamp(macd_pct/stdev, -1, +1) (P3) |
| 284 | #93 | Phase C3: Family weights + volume gate on bb_squeeze_breakout (P3) |
| 285 | #94 | Phase C2: Migrate 11 binary signals → IndicatorVote objects (P3) |
| 286 | #95 | Phase C1: Design doc for P3 refactor to direct techtrade.engine.confluence call (Q-2) |
| 287 | #96 | Phase B4: Expose obb.regime.detect() router + REST /api/v1/regime/detect |
| 288 | #97 | Phase B3: Scale staged_entry.tranche_* by regime multiplier |
| 289 | #98 | Phase B2: Wire regime into P7 composite weight adjustment |
| 290 | #99 | Phase B1: MarketRegime enum + detect_market_regime(spy_df, vix_df) in regime/ |
| 291 | #100 | Phase B0: Scaffold openbb_platform/extensions/regime/ (shared per Q-1) |
| 292 | #101 | Phase A8: Cap stop at min(2*ATR, 5% * entry) + trailing stop rules (P7) |
| 293 | #102 | Phase A7: earnings_revision_3m_direction from FMP analyst estimates (P2/P4) |
| 294 | #103 | Phase A6: Add momentum_accel_63d (change in 63d rank over last 63d) to P6 |
| 295 | #104 | Phase A5: Add peg_ratio to P4 ValuationKPIs; integrate into scoring |
| 296 | #105 | Phase A4b: Sector-adjust WACC fallback (tech 9%, healthcare 11%, crypto 15%) |
| 297 | #106 | Phase A4a: Two-stage DCF fade (5Y explicit → 8Y taper → terminal) |
| 298 | #107 | Phase A3: Add vol_63d_trend (expanding/contracting/flat) to P5 |
| 299 | #108 | Phase A2: Report kurtosis + skewness in P5 RiskKPIs |
| 300 | #109 | Phase A1: Add free_float_pct + short_interest_pct to P1 CompanyProfile |
| 301 | #110 | Phase A0: Add AnalysisFeatureFlags dataclass with env-var overrides |
| 303 | #111 | Add short_interest_pct via finra_cached (or fmp_cached extension) — follow-up to A1 |
| 305 | #112 | PR #304 review C2: use_two_stage_dcf + use_sector_wacc combination is untested |
| 306 | #113 | PR #304 review C1: A5 PEG verdict-tightening tests don't actually assert the verdict change |
| 307 | #114 | PR #304 review I1: A5 PEG tightening is unflagged but silently flips gate_passed |
| 308 | #115 | PR #304 iter-2 C2.1: entry_rec ignores PEG-tightened valuation_verdict (coherence bug) |
| 309 | #116 | PR #304 iter-2 I2.2: peg_gate_str displays regardless of use_peg_tightening flag |
| 310 | #117 | PR #304 iter-2 I2.1: use_peg_tightening not covered by 4 flag-plumbing tests |
| 311 | #118 | PR #304 iter-2 I2.3: use_peg_tightening=True + NaN PEG silently does nothing |
| 312 | #119 | [test-coverage] Analysis/tests/test_stock_analysis.py:1972 — test_flag_on_but_nan_peg_surfaces_diagnostic is effectively a no-op |
| 313 | #120 | [correctness] Analysis/stock_analysis.py:1946 — entry_rec refactor silently changes default-off behavior for mos in [-0.05, 0) |
| 314 | #121 | [test-coverage] Analysis/tests/test_stock_analysis.py:1885 — entry_rec verdict x bullish_count matrix under-tested |
| 315 | #122 | OpenBB-QC-pr-304: QC review of PR #304 (Phase A partial — scaffolding + 5 quick wins) |
| 316 | #123 | [docstrings] Analysis/stock_analysis.py:1968 — entry_rec comment claims 'mos + bullish_count still refine wording' but mos is unused |
| 317 | #124 | [test-coverage] Analysis/tests/test_stock_analysis.py:1986 — Dead if-branch in test_flag_on_slightly_negative_mos_flips_to_verdict_keyed (QC-E) |
| 318 | #125 | [test-coverage] Analysis/stock_analysis.py:1999-2012 — Flag-OFF raw-mos cascade: 5 of 6 branches lack explicit parity coverage (QC-G) |
| 319 | #126 | [correctness] Analysis/stock_analysis.py:1982 — use_peg_tightening=True changes entry_rec semantics even when PEG doesn't tighten (QC-F) |
| 320 | #127 | [test-coverage] Analysis/stock_analysis.py:1946-1948 — No test asserts NaN-PEG annotation is absent on non-Fair-Value verdicts (QC-H) |
| 356 | #128 | [Epic] openbb-fmp-trading — intraday day-trading automation |
| 357 | #129 | Phase 0: Prerequisites — FMP + fmp_cached parity + CI guardrails |
| 359 | #130 | Phase 2: Deterministic execution — Tier-1 caching + IntradaySession tick loop + AC-1/5/6 |
| 360 | #131 | Phase 3: Agent turns — [agent] extra + Claude backend + Pre/PostClose + MCP + #85 test |
| 361 | #132 | Phase 4: market_snapshot + AlertManager v1 (NG7-enforced) |
| 362 | #133 | Phase 5: Reporting + polish — report() MD+XLSX+JSON, replay(), README, config examples |
| 363 | #134 | Phase 6: Validation, docs, launch — backtest bridge + live integration + close 4 epics |
| 382 | #135 | [P3.1 [agent] Poetry extra + AgentBackend Protocol] |
| 383 | #136 | [P3.2 claude_backend.py (anthropic SDK) + deterministic.py fallback] |
| 384 | #137 | [P3.3 PreOpenAgentTurn — system prompt + tool set + forced submit_daily_plan] |
| 385 | #138 | [P3.4 PostCloseAgentTurn — 3 submit tools (md, preset_review, next_day_hints)] |
| 387 | #139 | [P3.6 Core-unchanged-when-removed test (fulfills #85 acceptance)] |
| 388 | #140 | [P3.7 Cost-cap tests — max tokens per turn] |
| 389 | #141 | [P4.1 market_snapshot command + MoverRow + MarketSnapshot models] |
| 390 | #142 | [P4.2 AlertManager v1 (3 spec types) + NG7 dual-sink delivery] |
| 391 | #143 | [P4.3 alert.* sub-router + CLI subcommands] |
| 392 | #144 | [P4.4 Alert eval matrix + NG7 delivery invariants] |
| 393 | #145 | [P4.5 NG7 architecture guardrail (AST test) — do FIRST] |
| 394 | #146 | [P5.1 obb.fmp_trading.report() — MD + XLSX + JSON] |
| 395 | #147 | [P5.2 XLSX reuses techtrade + 3 intraday sheets (TickSummary/AlertLog/PositionLedger)] |
| 396 | #148 | [P5.3 replay() command + AC-8 byte-identical golden test] |
| 397 | #149 | [P5.4 README + docs/cli_reference.md + 3 config examples] |
| 398 | #150 | [P5.5 (roll-up) Final Phase-5 acceptance gates] |
| 399 | #151 | [P6.1 Backtest bridge — validate techtrade preset over historical intraday] |
| 400 | #152 | [P6.2 Close 4 target epics with reference to this PRD] |
| 401 | #153 | [P6.3 File post-v1 follow-up issues] |
| 402 | #154 | [P6.4 Integration test suite green against live fmp_cached] |
| 403 | #155 | [P6.5 pyproject.toml final polish + version bumps + CHANGELOG] |
| 408 | #156 | [Epic] openbb-core-journal — shared journaling + replay primitive |
| 413 | #157 | [J5 Retrofit techtrade with journaling + replay] |
| 578 | #158 | #pine-P2.T1b: Tests — 5 conformance_strategy fixture triples (rsi_reversal, sma_crossover, breakout_atr, bb_squeeze, macd_histogram) |
| 580 | #159 | [E3-adapter] list[OHLCV] -> pd.DataFrame conversion at Provider->dispatcher boundary |
| 581 | #160 | [manifest sync] Add strategy.*/request.security to BUILTINS_IMPLEMENTED (bd-0uh promoted FEATURES, missed builtins) |
| 582 | #161 | Migrate remaining src/pyne_compiler/tests/ imports openbb_pine.* → pyne_compiler.* |
| 583 | #162 | [audit] Retroactively verify CCXTProvider + CapitalComProvider pass conformance suite (bd-cko followup) |
| 584 | #163 | #pine-P2.T4: Tests — 3 request.security curated corpus fixtures + 10 misc corpus expansion |
| 586 | #164 | #pine-P2.T2: Tests — 3 v5 strategy roundtrip fixtures (simple, security(), iff() exit) |
| 587 | #165 | #pine-P2.W1: Widgets — 3-5 bundled strategy widgets (RSI Reversal, SMA Crossover, Breakout+ATR Trail) |
| 593 | #166 | [pyne_compiler gap] Position-history builtins: strategy.opentrades / closedtrades / wintrades / losstrades |
| 594 | #167 | [pyne_compiler gap] Support plot.style_histogram + additional color constants (color.gray, etc.) |
| 595 | #168 | [api] pynecore.core.strategy_stats.calculate_strategy_statistics called explicitly by bd-liz because ScriptRunner CSV path bypassed |
| 596 | #169 | [dev-env] Editable install of pyne_compiler points at deleted worktree paths after session churn |
| 597 | #170 | bd recall <key> <content> silently overwrites memory (should read, not write) |
| 599 | #171 | Normalize Signature.kwargs vs. h14 trailing-tuple-kwargs (first post-extraction cleanup) |
| 600 | #172 | C3: inner-type validation for strategy.* signatures |
| 729 | #173 | [EPIC] Pine Script Support |
| 730 | #174 | [EPIC] Pine Phase 1 - Foundation (M1) |
| 731 | #175 | [EPIC] Pine Extraction (E0-E4) - pynecore |
| 732 | #176 | [EPIC] Pine Phase 2 - Strategies + cross-TF |
| 733 | #177 | [EPIC] Pine Phase 3 - Completeness |
| 734 | #178 | [EPIC] Pine Phase 4 - Polish and Launch |
| 735 | #179 | [EPIC] Pine - Unphased backlog |
| 756 | #180 | [coverage-debt] fmp + fmp_cached: 22 fetchers registered but not exercised in test files (follow-up to #754) |
| 759 | #181 | [refactor] fmp_trading: session_id = str(plan.trading_date) causes same-day session collisions |
| 854 | #182 | [sec] SecOwnershipChangesFetcher.transform_data filters all rows to EmptyDataError |
| 911 | #183 | [portfolio] [P1][Data] SSGA parser drops sector column — xray route sector_rollup always '(unknown)' for SPY-derived exposures (follow-up to #541) |
| 912 | #184 | [portfolio] [ops] fmp_cached etf_holdings warns at WARNING level for equity singletons — noisy under xray recursive frontier (follow-up to #541) |
| 915 | #185 | [pine] executor_shell equity_curve should stamp time / cash / exposure per snapshot |
| 930 | #186 | [fmp-cached] Gap: IWM (Russell 2000) + ACWI (MSCI ACWI) index constituents |
| 945 | #187 | [portfolio] Data-layer drift: 5 endpoints need adapter fixes surfaced by #513-#525 runtime audit |
| 965 | #188 | [pine] .venv_pine_support: openbb-fmp 1.6.1 missing aftermarket_trade module → openbb-fmp-cached import fails |
| 976 | #189 | [fmp_cached] add query indexes on company_news / world_news / company_filings for held-symbol + time-window scans (gap for #564) |
| 980 | #190 | Epic: local-ci skill — project-scoped Dockerized CI runner |
| 986 | #191 | local-ci P2: OpenBB CI stack — local-ci.yml + Dockerfile + compose (#980) |
| 987 | #192 | local-ci P3: MySQL sidecar + mysql_restore init + mysql tier (#980) |
| 988 | #193 | local-ci P4: copilot-api CI stack — local-ci.yml + Bun runner (#980) |
| 1002 | #194 | local-ci P6: user guide — ci/README.md (#980) |
| 1003 | #195 | local-ci P7: CI drift check — local-ci.yml vs GH workflow steps (#980) |
| 1013 | #196 | local-ci: schema init handler should use if/then per kind, not oneOf (deferred from PR #1009 review) |
| 1014 | #197 | local-ci: --dry-run 'no side effects' guarantee should be enforced via a compose-adapter shim (deferred from PR #1009 review) |
| 1321 | #198 | [fmp_cached] Baseline test drift: 10 pre-existing failures on portfolio |
| 1330 | #199 | [fmp_cached] plan_limited.py may be stale: EquityActive returned 200 on Starter |
| 1394 | #200 | [bug] portfolio_intel.sentiment router: NameError SentimentRollupResult on load |
| 1395 | #201 | [bug] smart_money.rollup: senate source calls non-existent ROUTER_regulators_sec.senate_trades |
| 1625 | #202 | notebooks(nb03): portfolio construction — target bands + concentration caps + coverage guard |
| 1779 | #203 | [techtrade] Bring nb-01 through nb-06 under smoke-test discipline |
| 1922 | #204 | [portfolio-intel] fmp-cached gap: forward P/E (pe_fwd) for peer-multiples widget |
| 1925 | #205 | [portfolio-intel] Deferred from PR #1924 review: use TTM ratios/metrics for peer-multiples pe_ttm/ps_ttm/ev_ebitda |
| 1928 | #206 | [portfolio-intel] earnings-transcripts blocked: FMP Premium-tier (plan-limited) — full-wiring of #1667 |
| 1929 | #207 | [portfolio-intel] institutional-ownership blocked: holder list is FMP Premium (plan-limited) — full-wiring of #1659 |
| 1930 | #208 | [portfolio-intel] stock-ownership blocked: ownership-split has no fmp_cached source at our tier — full-wiring of #1660 |
| 1932 | #209 | [portfolio-intel] Architecture blocker: data-bearing techtrade widgets need persisted scan-snapshot layer (blocks #1692/#1696/#1697/#1698/#1699) |
| 2195 | #210 | [notebook-agent][PROGRAM] Python MCP Notebook Companion with local vLLM Nemotron |
| 2197 | #211 | [notebook-agent][NE2] Notebook-specific MCP analytical and workflow bridges |
| 2198 | #212 | [notebook-agent][NE3] Python local-model MCP agent and CLI |
| 2199 | #213 | [notebook-agent][NE4] Differential, model and safety qualification |
| 2200 | #214 | [notebook-agent][NE5] Resume, Workspace integration and release |
| 2204 | #215 | [notebook-agent][NF2.2] Artifacts, jobs, paper gates and provider modes |
| 2205 | #216 | [notebook-agent][NF3.1] Local model, MCP sessions and enforced tool execution |
| 2206 | #217 | [notebook-agent][NF3.2] Narrative planner, evidence and developer CLI |
| 2207 | #218 | [notebook-agent][NF4.1] Numerical and full-corpus story parity |
| 2208 | #219 | [notebook-agent][NF4.2] Local Nemotron reliability and safety qualification |
| 2209 | #220 | [notebook-agent][NF5.1] Recoverable runs and shared Workspace agent experience |
| 2210 | #221 | [notebook-agent][NF5.2] Portfolio drift CI and verified showcase release |
| 2219 | #222 | [notebook-agent][N09] Gate Portfolio and TechTrade sandbox paper actions |
| 2220 | #223 | [notebook-agent][N10] Enforce provider variants, recording and truthful cache semantics |
| 2221 | #224 | [notebook-agent][N11] Implement explicit local vLLM model configuration and preflight |
| 2222 | #225 | [notebook-agent][N12] Implement authenticated server-qualified MCP client sessions |
| 2223 | #226 | [notebook-agent][N13] Build bounded schema-validated MCP tool execution loop |
| 2224 | #227 | [notebook-agent][N14] Plan narrative progression and cross-chapter state bindings |
| 2225 | #228 | [notebook-agent][N15] Render evidence-grounded explanations and artifact provenance |
| 2226 | #229 | [notebook-agent][N16] Deliver CLI story inspection, planning and approved execution |
| 2227 | #230 | [notebook-agent][N17] Implement independent numeric and artifact differential tests |
| 2228 | #231 | [notebook-agent][N18] Qualify all 25 notebook stories and narrative handoffs |
| 2229 | #232 | [notebook-agent][N19] Qualify local Nemotron tool use and explainability |
| 2230 | #233 | [notebook-agent][N20] Test denial, prompt injection, approvals and uncertain completion |
| 2231 | #234 | [notebook-agent][N21] Add checkpoint resume, idempotency reconciliation and budgets |
| 2232 | #235 | [notebook-agent][N22] Register a Workspace agent adapter over the same Python runner |
| 2233 | #236 | [notebook-agent][N23] Add Portfolio source, capability and agent regression CI gates |
| 2234 | #237 | [notebook-agent][N24] Release verified notebook-equivalent showcase and runbooks |
| 2334 | #238 | [notebook-agent][N09d] Bind every story:paper stage to the paper tools |

## 2. Closed issues (index only)

| Old # | Closed | Title |
|---|---|---|
| 1 | 2026-06-24 | feat: Google ADK agents extension on top of OpenBB |
| 2 | 2026-06-04 | chore: resolve Phase A open questions before implementation |
| 3 | 2026-06-04 | feat(agents): Phase A-1 — extension skeleton and LiteLLM config |
| 4 | 2026-06-04 | feat(agents): Phase A-2 — PII redaction guardrails callback |
| 5 | 2026-06-04 | feat(agents): Phase A-3 — portfolio tools layer (get_positions, get_sector_exposure) |
| 6 | 2026-06-04 | feat(agents): Phase A-4 — portfolio_qa LlmAgent with guardrails |
| 7 | 2026-06-04 | feat(agents): Phase A-5 — stdio MCP server |
| 8 | 2026-06-04 | chore(agents): Phase A-6 — IDE MCP registration for Claude Code and VS Code |
| 9 | 2026-06-10 | test(agents): Phase A-7 — golden eval harness for Phase A |
| 19 | 2026-06-27 | financialtoolkit: converge FinanceToolkit dependency onto upstream/PyPI (remove fork + path dep) |
| 21 | 2026-06-10 | Resolve openbb-portfolio package-name shadowing with published PyPI package |
| 22 | 2026-06-27 | Re-add OpenBB example notebooks/demos under docs/examples with stripped outputs |
| 23 | 2026-06-10 | Consider an openbb_core standard model for XBRL company-concept retrieval |
| 24 | 2026-06-24 | [Epic] Detailed design for OpenBB backtesting engine |
| 25 | 2026-06-04 | [Epic] Detailed design for OpenBB backtesting engine |
| 26 | 2026-06-04 | Backtest extension scaffolding and package layout |
| 27 | 2026-06-04 | Core Pydantic data models and interface contracts |
| 28 | 2026-06-04 | fmp_cached data bundle and data layer design |
| 29 | 2026-06-04 | Vectorized in-house backtest engine (NumPy/Numba) design |
| 30 | 2026-06-04 | Event-driven engine integration (zipline-reloaded + Pipeline) |
| 31 | 2026-06-04 | Execution realism model (slippage, commissions, fills) |
| 32 | 2026-06-04 | Performance analytics and reporting design |
| 33 | 2026-06-04 | Anti-overfitting validation framework (WFO/CPCV/PBO/DSR) |
| 34 | 2026-06-04 | obb.backtest.* router and public API surface design |
| 35 | 2026-06-04 | Strategy library design |
| 36 | 2026-06-04 | Optional non-vendored engine adapters (vectorbt/pybroker extras) |
| 37 | 2026-06-04 | Testing strategy, CI, and non-functional requirements |
| 38 | 2026-06-04 | Backtest extension scaffolding and package layout |
| 39 | 2026-06-04 | Core Pydantic data models and interface contracts |
| 40 | 2026-06-04 | fmp_cached data bundle and data layer design |
| 41 | 2026-06-04 | Vectorized in-house backtest engine (NumPy/Numba) design |
| 42 | 2026-06-04 | Event-driven engine integration (zipline-reloaded + Pipeline) |
| 43 | 2026-06-04 | Execution realism model (slippage, commissions, fills) |
| 44 | 2026-06-04 | Performance analytics and reporting design |
| 45 | 2026-06-04 | Anti-overfitting validation framework (WFO/CPCV/PBO/DSR) |
| 46 | 2026-06-04 | obb.backtest.* router and public API surface design |
| 47 | 2026-06-04 | Strategy library design |
| 48 | 2026-06-04 | Optional non-vendored engine adapters (vectorbt/pybroker extras) |
| 49 | 2026-06-04 | Testing strategy, CI, and non-functional requirements |
| 50 | 2026-06-04 | Implement: backtest extension scaffolding & package layout |
| 51 | 2026-06-04 | Implement: core data models & interface protocols |
| 52 | 2026-06-11 | Implement: fmp_cached data bundle & data layer |
| 53 | 2026-06-11 | Implement: vectorized in-house engine (NumPy/Numba) |
| 55 | 2026-06-04 | Implement: execution realism model (slippage/commission/fills) |
| 56 | 2026-06-24 | Implement: performance analytics & reporting |
| 57 | 2026-06-24 | Implement: anti-overfitting validation (WFO/CPCV/PBO/DSR) |
| 58 | 2026-06-24 | Implement: obb.backtest.* router & public API surface |
| 59 | 2026-06-24 | Implement: strategy library & plugin mechanism |
| 64 | 2026-06-13 | Decisions: resolve open questions Q1-Q9 |
| 65 | 2026-06-13 | Scaffold techtrade extension + entry point + green build |
| 66 | 2026-06-13 | Define core Data models (models.py) |
| 67 | 2026-06-13 | Vendor pandas-ta-classic submodule (pinned, editable) |
| 68 | 2026-06-13 | GICS segment map + segments command |
| 69 | 2026-06-13 | Universe resolver (etf_holdings / constituents / screener) |
| 70 | 2026-06-13 | Top-mover ranking + movers command |
| 71 | 2026-06-13 | CI harness: golden-file tests + lint/type + submodule-pin check |
| 72 | 2026-06-13 | pandas-ta-classic adapter + IndicatorPanel builder |
| 73 | 2026-06-24 | OpenBB technical adapter + reuse-first selector + parity oracle + bulk Strategy |
| 74 | 2026-06-24 | Weighted confluence voting -> score + IndicatorVote attribution |
| 75 | 2026-06-24 | signals command + 3 presets + golden-score test |
| 76 | 2026-06-24 | EntryExitRule + risk-based sizing (ATR stop / R-target / time-stop) |
| 77 | 2026-06-24 | Order generation + plan/orders -> TradePlan |
| 78 | 2026-06-24 | PaperBroker fill sim (BrokerInterface, next-bar-open) + simulate + no-look-ahead test |
| 79 | 2026-06-24 | scan command - all sectors -> ranked TradePlans |
| 80 | 2026-06-24 | Recommendation builder (levels / stop-gaps / R:R / conviction / reasoning) |
| 81 | 2026-06-24 | Excel export (6 sheets + conditional formatting + disclaimer) + export + golden xlsx |
| 82 | 2026-06-21 | backtest_bridge + validate + attach ValidationReport |
| 83 | 2026-06-24 | tuneta adapter + tune command, gated by validation |
| 84 | 2026-07-11 | Narrator (deterministic briefing) |
| 85 | 2026-07-11 | MCP tool exposure + core-unchanged-when-removed test |
| 86 | 2026-06-24 | README + usage docs + worked examples |
| 89 | 2026-06-25 | SEC bulk 13F + CUSIP index (reverse institutional ownership) |
| 93 | 2026-06-26 | 13F resolver: broad ticker->CUSIP coverage via OpenFIGI (deterministic FIGI bridge) |
| 97 | 2026-06-27 | ETF holdings: free fallback tier (issuer-file + SEC N-PORT) for fmp_cached etf.holdings |
| 103 | 2026-06-29 | [pine] D1: Compiler architecture design — lexer, parser, IR, codegen, security boundary |
| 104 | 2026-06-29 | [pine] D2: Runtime + OHLCV bridge design — PyneCore adapter, FMP/fmp_cached provider, BYO data |
| 105 | 2026-06-29 | [pine] D3: OpenBB Platform integration design — router, REST surface, Workspace widgets, MCP, attribution |
| 111 | 2026-07-01 | #pine-P1-X1: Conformance harness — auto-discover .pine + .csv pairs |
| 112 | 2026-07-01 | #pine-P1-P7: No-side-effect CI tests (PRD §16.5 enforcement) |
| 113 | 2026-07-01 | #pine-P1-P6: 4 attribution surfaces CI test (PRD §2.6 enforcement) |
| 114 | 2026-07-01 | #pine-P1-P4: openbb pine doctor CLI |
| 115 | 2026-07-01 | #pine-P1-P5: about() + PineAbout typed model — expand from L0.2 scaffold |
| 118 | 2026-07-01 | #pine-P1-P1: 6 REST endpoints scaffolded |
| 155 | 2026-07-01 | #pine-P1-R6: FMP retry budget — 5 attempts + exp backoff + jitter (D2 §9) |
| 156 | 2026-07-01 | #pine-P1-R7: Result emission — OBBject.results + .extra keys |
| 157 | 2026-07-01 | #pine-P1-R5: ExecLimits — timeout + RLIMIT_AS + bar cap (PRD §5.2 T2) |
| 158 | 2026-07-01 | #pine-P1-R4: RestrictedExec namespace (PRD §5.2 T3) |
| 159 | 2026-07-01 | #pine-P1-R3: Provider precedence + non-FMP fast-fail (PRD §13.8 enforcement) |
| 160 | 2026-07-01 | #pine-P1-R2: BYODataProvider — primary-series-only schema validation |
| 161 | 2026-07-01 | #pine-P1-R1: FMPOHLCVProvider — single concrete class + asset-class dispatch |
| 162 | 2026-07-01 | #pine-P1-C8: Error model — PineError hierarchy + diagnostics + tracking_url |
| 163 | 2026-07-01 | #pine-P1-C7: v5->v6 auto-migration shim |
| 164 | 2026-07-01 | #pine-P1-C6: Compile cache — blake2b key + atomic write |
| 165 | 2026-07-01 | #pine-P1-C5: Codegen — tree-walk + closed allowlist gate (T1 mitigation) |
| 166 | 2026-07-01 | #pine-P1-C4: IR dataclasses per D1 §2 |
| 167 | 2026-07-01 | #pine-P1-C2: Parser — lark Earley grammar (pinned ==1.2.2) |
| 168 | 2026-07-01 | #pine-P1-C3: Type checker — (qualifier, inner) lattice + 8 non-trivial rules |
| 169 | 2026-07-01 | #pine-P1-C1: Lexer — hand-rolled DFA + //@version= pragma + INDENT/DEDENT |
| 170 | 2026-07-01 | #pine-P0-L0.6: File Phase 1 sub-beads with concrete M1 acceptance criteria |
| 171 | 2026-07-01 | #pine-P0-L0.4: Crawl wild-corpus baseline (top-1000 community Pine scripts) |
| 172 | 2026-07-01 | #pine-P0-L0.5: wild-corpus-coverage CI job |
| 173 | 2026-07-01 | #pine-P0-L0.2: Scaffold openbb_platform/extensions/pine/ per D3 |
| 174 | 2026-07-01 | #pine-P0-L0.3: Pin PyneCore submodule + license-SHA CI check |
| 179 | 2026-07-01 | #pine-P0: Foundation — counsel, scaffold, submodule pin, wild-corpus baseline (GH #106) |
| 180 | 2026-07-01 | #pine-D3: OpenBB Platform integration design (GH #105) |
| 181 | 2026-07-01 | #pine-D2: Runtime + OHLCV bridge design — FMP-only (GH #104) |
| 182 | 2026-07-01 | #pine-D1: Compiler architecture design (GH #103) |
| 184 | 2026-07-01 | bug: backtest.discovery.resolve() doesn't lazy-load entry-point plugins (techtrade_confluence registers as None) |
| 185 | 2026-07-01 | [bug] build: financialtoolkit intrinsic_value APIEx missing description (>3 params) breaks openbb.build() |
| 186 | 2026-07-01 | verify: build + pytest after side-branch consolidation |
| 187 | 2026-07-01 | merge step 3: wip/89-sec-13f-cusip-index -> trading_technicals |
| 188 | 2026-07-01 | merge step 2: chore/19-financialtoolkit-pypi -> trading_technicals |
| 189 | 2026-07-01 | merge step 1: docs/22-examples-relocation -> trading_technicals |
| 190 | 2026-07-01 | merge: consolidate side branches into trading_technicals (docs/22, chore/19, wip/89) |
| 191 | 2026-07-01 | 13F index: data spike - inspect one real quarter INFOTABLE before locking schema |
| 194 | 2026-07-01 | docs(notebooks): enhance 01 directly + drop builder + Investopedia links |
| 200 | 2026-07-01 | #99-T4: bulk_url_discovery.py — Q-A A1 with raise-loudly guard |
| 201 | 2026-07-01 | #99-T3: nport_parser.py + 5 fixtures + G4 content-derived holding-key |
| 202 | 2026-07-01 | #99-T2: nport_index.py — 4-table schema + read helpers + SPDR seed |
| 203 | 2026-07-01 | #99-T1: sec_http.py chokepoint — L2 User-Agent enforcement |
| 204 | 2026-07-13 | #99 parent: SEC N-PORT ingest (bulk historical + per-CIK incremental) — un-park #97 T2+T3 |
| 205 | 2026-07-01 | #99 design refinement: fold §6.2 G1-G6 + Q-D 2026-regime verification |
| 206 | 2026-07-01 | #97-T7: per-tool spec + DESIGN.md changelog + status update |
| 207 | 2026-07-01 | #97-T6: rebuild + integration smoke + scan regression |
| 208 | 2026-07-01 | #97-T5: wire cache→FMP→issuer→N-PORT chain into FMPCachedEtfHoldingsFetcher |
| 209 | 2026-07-01 | #97-T4: etf_holdings_issuer.py — SSGA tier with 11 SPDRs |
| 212 | 2026-07-01 | #97-T1: spike — confirm SSGA URL/layout + N-PORT TSV columns |
| 213 | 2026-07-01 | refresh-etf-holdings-cache T4: smoke + integrate + PR + merge |
| 214 | 2026-07-01 | refresh-etf-holdings-cache T3: docs + scheduler |
| 215 | 2026-07-01 | refresh-etf-holdings-cache T2: 13 unit tests (offline) |
| 216 | 2026-07-01 | refresh-etf-holdings-cache T1: tool module + universe + provider call |
| 217 | 2026-07-01 | Design: extend Tools/fetch_position_history.py to refresh ETF holdings cache too |
| 218 | 2026-07-01 | ETF holdings free fallback tier (SEC N-PORT + issuer-file) for fmp_cached etf.holdings |
| 219 | 2026-07-01 | #93-T3: per-tool spec + Tools/docs/DESIGN.md changelog |
| 220 | 2026-07-01 | #93-T4: end-to-end verification (bounded live run + long-tail resolve_cusip) |
| 221 | 2026-07-01 | #93-T2: Tools/enrich_cusip_figi.py batch CLI |
| 222 | 2026-07-01 | #93-T1: openfigi.py client + select_match() + openfigi_map_cache (R9) |
| 223 | 2026-07-01 | 13F index: Tools/populate_cusip_map.py - offline batch loader for ticker->CUSIP cache (S&P 500) |
| 224 | 2026-07-01 | 13F ingest writes to openbb_fmp_cache_test, not openbb_fmp_cache (design L3) |
| 225 | 2026-07-01 | gh-19: Verify acceptance criteria + open PR + close GH issue |
| 226 | 2026-07-01 | gh-19: Update extension README + audit docs for stale submodule references |
| 227 | 2026-07-01 | gh-19: Remove FinanceToolkit submodule (untrack, keep working tree) |
| 228 | 2026-07-01 | gh-19: Run pytest openbb_platform/extensions/financialtoolkit against PyPI dep |
| 229 | 2026-07-01 | gh-19: Smoke-install financetoolkit 2.1.2 from PyPI in .venv_win and verify Toolkit signature |
| 230 | 2026-07-01 | gh-19: Update pyproject.toml to use PyPI financetoolkit ^2.1.2 |
| 231 | 2026-07-11 | Design specs for #84 Narrator + #85 MCP tool exposure |
| 232 | 2026-07-01 | gh-22: Open PR linking to #22 and close the GitHub issue |
| 233 | 2026-07-01 | gh-22: Strip outputs + update docs/examples/README.md and content.json |
| 234 | 2026-07-01 | gh-22: Verify acceptance criteria (pre-commit, history, sizes) |
| 235 | 2026-07-01 | gh-22: Delete dropped notebooks + orphan .webp from examples/ |
| 236 | 2026-07-01 | gh-22: Pure-rename commit — git mv kept notebooks + companions to docs/examples/ |
| 237 | 2026-07-01 | gh-22: Triage openbbPlatformAsLLMTools.ipynb (conditional drop if stripped >500 KB) |
| 238 | 2026-07-01 | gh-22: Add nbstripout to .pre-commit-config.yaml and verify install |
| 239 | 2026-07-01 | Audit open GitHub issues for already-implemented work |
| 240 | 2026-07-01 | 13F index: tests (parser/resolver/read-helper/tier + e2e) |
| 241 | 2026-07-01 | 13F index: rewire _try_sec_13f in fmp_cached to use the CUSIP index |
| 242 | 2026-07-01 | 13F index: resolve_cusip + holders_for_cusip read helpers (providers/sec/utils/thirteen_f_index.py) |
| 243 | 2026-07-01 | 13F index: Tools/ingest_sec_13f.py (bulk download -> parse INFOTABLE -> load MySQL) |
| 244 | 2026-07-01 | 13F index: schema DDL + database wiring (sec_13f_holdings, sec_13f_cusip_map) |
| 245 | 2026-07-01 | 86-T3: README rewrite |
| 246 | 2026-07-01 | 86-T2: examples drift-guard smoke (3 tests) |
| 247 | 2026-07-01 | 86-T1: examples package + 3 runnable scripts |
| 248 | 2026-07-01 | notebooks: "A Developer Guide to Disciplined Trading" — POC notebook #1 shipped |
| 249 | 2026-07-01 | 83-T7: integration test + extend #82 degradation truth table |
| 250 | 2026-07-01 | 83-T6: engine.indicators — L9 auto-load tuned configs by symbol→segment |
| 251 | 2026-07-01 | 83-T5: tune_router + register sub-router |
| 252 | 2026-07-01 | 83-T4: tuning.tuneta_adapter (lazy tuneta import + knob table + column parser) |
| 253 | 2026-07-01 | 83-T3: tuning.sector_ohlcv (pool segment OHLCV + forward returns) |
| 254 | 2026-07-01 | 83-T2: tuning.tuned_defaults (JSON + mtime cache + contextvar override) |
| 255 | 2026-07-01 | 83-T1: bootstrap (pyproject [tuneta] extra + TuningReport model) |
| 256 | 2026-07-01 | 83-T1: bootstrap (pyproject [tuneta] extra + TuningReport model) |
| 257 | 2026-07-01 | 86: README + usage docs + worked examples |
| 258 | 2026-07-01 | 82: backtest_bridge + validate + attach ValidationReport |
| 260 | 2026-07-01 | gh-19: File follow-up bd for 3-tier fallback disposition |
| 261 | 2026-07-01 | 13F index: broad ticker->CUSIP coverage (deferred follow-up) |
| 262 | 2026-07-01 | 13F index: notebook 01 verification cell + Tools/docs/DESIGN.md changelog |
| 265 | 2026-07-01 | 83: tuneta adapter + tune command, gated by validation |
| 302 | 2026-07-13 | Phase A0: Add AnalysisFeatureFlags dataclass with env-var overrides |
| 358 | 2026-07-09 | Phase 1: Foundations — Scaffold + Models + RiskManager + Journal + Bandwidth + Doctor |
| 364 | 2026-07-09 | [P0.1 File 6 new fetchers in openbb_fmp (tier-2 initial)] |
| 365 | 2026-07-09 | [P0.2 Register 6 fetchers in openbb_fmp_cached via create_fallback_fetcher_class] |
| 366 | 2026-07-09 | [P0.3 CI parity test — set(fmp) ⊂ set(fmp_cached)] |
| 367 | 2026-07-09 | [P0.4 CI provider-purity grep test] |
| 368 | 2026-07-09 | [P0.5 #91 disposition — 3-tier FMP/CBOE fallback code] |
| 369 | 2026-07-09 | [P1.1 Extension scaffold openbb_platform/extensions/fmp_trading/] |
| 370 | 2026-07-09 | [P1.2 Core data models (§6) + Pydantic round-trip tests] |
| 371 | 2026-07-09 | [P1.3 RiskManager with 8 gates + one test per gate] |
| 372 | 2026-07-09 | [P1.4 SessionJournal NDJSON writer + reader/replay foundation] |
| 373 | 2026-07-09 | [P1.5 BandwidthMeter + monthly persistence + conservation-mode test] |
| 374 | 2026-07-09 | [P1.6 obb.fmp_trading.doctor() + openbb-daytrade doctor CLI] |
| 375 | 2026-07-10 | [P2.1 Upgrade EquityIntradayHistorical + AftermarketQuote to TIER-1] |
| 376 | 2026-07-10 | [P2.2 Add create_ttl_wrapper_class to base_cached.py; migrate ExchangeMarketHours] |
| 377 | 2026-07-10 | [P2.3 IntradaySession tick loop skeleton — quote polling + journal writes] |
| 378 | 2026-07-10 | [P2.4 Wire techtrade signals→plan→orders→PaperBroker into tick loop] |
| 379 | 2026-07-10 | [P2.5 Flat-by-close state machine + AC-6 test] |
| 380 | 2026-07-10 | [P2.6 No-look-ahead golden test (AC-5)] |
| 381 | 2026-07-10 | [P2.7 End-to-end integration test with mock FMP → 6.5h simulated session (AC-1)] |
| 386 | 2026-10-05 | [P3.5 MCP tool server (openbb-daytrade mcp-serve)] |
| 409 | 2026-07-09 | [J1 Scaffold openbb-core-journal] |
| 410 | 2026-07-09 | [J2 Writer + reader + base event] |
| 411 | 2026-07-09 | [J3 Replay skeleton + determinism golden] |
| 412 | 2026-07-09 | [J4 Retrofit fmp-trading Phase 1 P1.4] |
| 443 | 2026-07-11 | P3.0 state_store MySQL persistence (Phase 3 / D6) |
| 444 | 2026-07-11 | P3.1 PreOpenAgentTurn + backend + tool_registry + all P0/P1 defenses |
| 445 | 2026-07-11 | P3.2 PostCloseAgentTurn + narrator (#84) + EndOfDayReport |
| 446 | 2026-07-11 | P3.3 stdio MCP server + core-unchanged tests + AC-1-ext E2E |
| 450 | 2026-07-11 | P5.0 reporting.journal_reader + shared metrics helper (Phase 5) |
| 451 | 2026-07-11 | P5.1 report(md/json/all) — MD + JSON + orchestrator |
| 452 | 2026-07-11 | P5.2 xlsx_builder — techtrade base + 3 intraday sheets |
| 453 | 2026-07-11 | P5.3 replay() + StubbedDataProvider + AC-P5-5/6/7 |
| 454 | 2026-07-11 | P5.4 CLI subcommands + README + config examples |
| 488 | 2026-07-13 | [bd] Dolt dep-schema missing depends_on_id column (blocks all bd link) |
| 491 | 2026-07-21 | [portfolio] [EPIC] Portfolio Intelligence Engine (openbb-portfolio-intel) |
| 492 | 2026-07-21 | [portfolio] [PHASE M0] Kickoff & Scaffolds (Wk 0-1) |
| 493 | 2026-07-21 | [portfolio] [PHASE P0] Data-Layer Gap Fill (Wk 1-3) |
| 494 | 2026-07-21 | [portfolio] [PHASE P1] X-Ray + Events + Risk + Smart-Money (Wk 4-8) |
| 495 | 2026-07-21 | [portfolio] [PHASE P2] What-If + Attribution + Paper Trading (Wk 9-13) |
| 496 | 2026-07-21 | [portfolio] [PHASE P3] Alerts + Sentiment + Backtest Handoff + develop Merge (Wk 14-16) |
| 497 | 2026-07-19 | [portfolio] [M0] Cut portfolio branch + branch protection (portfolio & develop) |
| 498 | 2026-07-18 | [portfolio] [M0] DECISION: Resolve PRD Q8 (paper fill model source) |
| 499 | 2026-07-21 | [portfolio] [M0] Book M1/M2/M3/M4 gate reviews (60 min each) |
| 500 | 2026-07-16 | [portfolio] [M0][bd-BUG] Dolt dep-schema missing depends_on_id column (blocks all bd link) |
| 501 | 2026-07-13 | [portfolio] [M0][repo-BUG] dev_install.py -e fails: openbb-techtrade python constraint incompatible |
| 502 | 2026-07-13 | [portfolio] [M0][repo-BUG] openbb_fmp_cached import fails: aftermarket_trade missing in openbb-fmp 1.6.1 |
| 503 | 2026-07-13 | [portfolio] [M0][repo-BUG] fmp_cached cache_schema.py: create_aftermarket_quote_table used before defined (NameError) |
| 504 | 2026-07-16 | [portfolio] [M0] PR template + CI rule: feat/pi-* must target portfolio |
| 505 | 2026-07-21 | [portfolio] [M0] Session-boundary portfolio<-develop absorb cadence (Nadia owned) |
| 506 | 2026-07-16 | [portfolio] [M0] Scaffold portfolio_intel extension skeleton (CI green) |
| 507 | 2026-07-16 | [portfolio] [M0] Draft paper_* migration file (reviewed by E1+E3) |
| 508 | 2026-07-21 | [portfolio] [M0] Recorded-fixture harness for FMP (tests/fixtures/fmp/) |
| 509 | 2026-07-16 | [portfolio] [M0] Playwright E2E harness + widget scaffolds |
| 510 | 2026-07-16 | [portfolio] [M0] QA: author cross-account isolation test spec (pending) |
| 511 | 2026-07-16 | [portfolio] [M0] Shared .env smoke test green from every worktree |
| 512 | 2026-07-19 | [portfolio] [P0][Data] EtfHoldings model (etf/holdings) — PRIORITY, unblocks Lane B |
| 513 | 2026-07-20 | [portfolio] [P0][Data] Economics (Calendar + Treasury Rates + Indicators) |
| 514 | 2026-07-20 | [portfolio] [P0][Data] Market Performance (Sector + Industry + Gainers/Losers) |
| 515 | 2026-07-20 | [portfolio] [P0][Data] Technical Indicators endpoints (per-holding strip) |
| 516 | 2026-07-20 | [portfolio] [P0][Data] Derived-analytics cache table (portfolio_intel_cache) |
| 517 | 2026-07-20 | [portfolio] [P0][Data] Cache warmers for common ETFs + S&P500 constituents |
| 518 | 2026-07-20 | [portfolio] [P0][Data] EtfInfo + EtfSectorWeightings + EtfCountryWeightings |
| 519 | 2026-07-20 | [portfolio] [P0][Data] Calendars: Earnings + Dividends + Splits + IPOs |
| 520 | 2026-07-20 | [portfolio] [P0][Data] Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades |
| 521 | 2026-07-20 | [portfolio] [P0][Data] InsiderTrades (Latest + Search + Statistics) |
| 522 | 2026-07-20 | [portfolio] [P0][Data] Form 13F (Extract + Holder Performance Summary) |
| 523 | 2026-07-20 | [portfolio] [P0][Data] Senate Disclosures (Latest + Trading) |
| 524 | 2026-07-20 | [portfolio] [P0][Data] SEC Filings (Search + Company Search + 8-K) |
| 525 | 2026-07-20 | [portfolio] [P0][Data] News (Stock + Press Releases + General Latest) |
| 526 | 2026-07-19 | [portfolio] [P1][Analytics] X-Ray look-through algorithm (recursive unwrap) |
| 527 | 2026-07-20 | [portfolio] [P1][App] /portfolio/intel/smart_money route (rollup) |
| 528 | 2026-07-20 | [portfolio] [P1][App] /portfolio/intel/risk + /concentration routes |
| 529 | 2026-07-21 | [portfolio] [P1][Widgets] X-Ray Sector + Country pie widgets |
| 530 | 2026-07-21 | [portfolio] [P1][Widgets] Look-Through Top-25 table + Concentration gauge |
| 531 | 2026-07-21 | [portfolio] [P1][Widgets] Event Calendar timeline widget |
| 532 | 2026-07-21 | [portfolio] [P1][Widgets] Smart-Money ribbon + SHARED PAPER-badge component |
| 533 | 2026-07-21 | [portfolio] [P1][Widgets] Risk Dashboard widget (number-grid + vol chart) |
| 534 | 2026-07-21 | [portfolio] [P1][Demo] M2 build + recorded demo cut |
| 535 | 2026-07-19 | [portfolio] [P1][Analytics] X-Ray rollups (sector/country/mcap/overlap) |
| 536 | 2026-07-19 | [portfolio] [P1][Analytics] Concentration + HHI endpoint |
| 537 | 2026-07-19 | [portfolio] [P1][Analytics] Event Calendar merge algorithm |
| 538 | 2026-07-19 | [portfolio] [P1][Analytics] Smart-Money aggregator (insider+13F+senate) |
| 539 | 2026-07-19 | [portfolio] [P1][Analytics] Portfolio risk metrics (shared math with Analysis/) |
| 540 | 2026-07-19 | [portfolio] [P1][Analytics] Contribution-to-risk (marginal + component VaR) |
| 541 | 2026-07-19 | [portfolio] [P1][App] /portfolio/intel/xray route + portfolio_basket join |
| 542 | 2026-07-20 | [portfolio] [P1][App] /portfolio/intel/events route (timeline shape) |
| 543 | 2026-07-20 | [portfolio] [P2][Data] Index-constituent history (SPY/QQQ/IWM/ACWI) |
| 544 | 2026-07-20 | [portfolio] [P2][Paper][Fills v1] Stop / Stop-Limit / Trailing-Stop + partials |
| 545 | 2026-07-20 | [portfolio] [P2][Paper] Ledger + replay endpoint (append-only journal) |
| 546 | 2026-07-20 | [portfolio] [P2][Paper] Cross-account ISOLATION enforcement + tests (SEV-1) |
| 547 | 2026-07-20 | [portfolio] [P2][Paper] Fill-engine hardening: races + lock ordering |
| 548 | 2026-07-20 | [portfolio] [P2][Paper] Shared cost-basis/P&L math with real service |
| 549 | 2026-07-21 | [portfolio] [P2][Widgets] Paper Order Ticket widget (form + 2-step confirm) |
| 550 | 2026-07-21 | [portfolio] [P2][Widgets] Paper Blotter widget (order table) |
| 551 | 2026-07-21 | [portfolio] [P2][Widgets] Paper Performance widget (equity curve + KPIs) |
| 552 | 2026-07-21 | [portfolio] [P2][Widgets] What-If diff card widget (interactive) |
| 553 | 2026-07-21 | [portfolio] [P2][Widgets] Brinson Attribution waterfall widget |
| 554 | 2026-07-21 | [portfolio] [P2][Data] Corporate-action reconciler (nightly job) |
| 555 | 2026-07-21 | [portfolio] [P2][UX] PAPER badge + separate account-selector group |
| 556 | 2026-07-21 | [portfolio] [P2][Demo] M3 build + gate demo (paper order round-trip) |
| 557 | 2026-07-21 | [portfolio] [P2][Data/QA] Brinson reference fixtures (Bloomberg + spreadsheet) |
| 558 | 2026-07-19 | [portfolio] [P2][Analytics] What-If diff engine (stateless) |
| 559 | 2026-07-21 | [portfolio] [P2][Analytics] Brinson-Fachler attribution (allocation vs selection) |
| 560 | 2026-07-20 | [portfolio] [P2][Analytics] Attribution waterfall response shape |
| 561 | 2026-07-20 | [portfolio] [P2][Analytics] Backtest hand-off contract (paper.account.export_backtest) |
| 562 | 2026-07-20 | [portfolio] [P2][Paper] Apply paper_* migration + account CRUD |
| 563 | 2026-07-20 | [portfolio] [P2][Paper][Fills v0] Market + Limit orders; TIF day/gtc |
| 564 | 2026-07-21 | [portfolio] [P3][Data] News/8-K query index tuning + alert indices |
| 565 | 2026-07-21 | [portfolio] [M4] Nightly CI green on portfolio for 3 consecutive nights |
| 566 | 2026-07-21 | [portfolio] [M4] Documentation + release notes + APIEx/PythonEx complete |
| 567 | 2026-07-21 | [portfolio] [M4] Rebase portfolio onto develop + cut pi-rc-1 tag |
| 568 | 2026-07-21 | [portfolio] [M4] SINGLE portfolio->develop integration PR (merge-commit) |
| 569 | 2026-07-21 | [portfolio] [M4] Launch demo + retro + bd remember shipped state |
| 570 | 2026-07-20 | [portfolio] [P3][Analytics] Sentiment rollup (weighted analyst + PT upside) |
| 571 | 2026-07-20 | [portfolio] [P3][Analytics] Alert-rule engine (6 trigger types) |
| 572 | 2026-07-20 | [portfolio] [P3][App] /portfolio/intel/news + /sentiment routes |
| 573 | 2026-07-20 | [portfolio] [P3][App] Backtest hand-off wire-up (obb.backtest.portfolio) |
| 574 | 2026-07-20 | [portfolio] [P3][App] Paper-trading alert wiring (fills, stops, TIF, BP) |
| 575 | 2026-07-21 | [portfolio] [P3][Widgets] News + Sentiment widgets |
| 576 | 2026-07-21 | [portfolio] [P3][Widgets] Alert panel component (pinned in existing widgets) |
| 577 | 2026-07-21 | [portfolio] [P3][Widgets] One-click Backtest-this-portfolio button |
| 579 | 2026-07-13 | [E0.1] Split errors.py into compiler_errors.py + provider errors.py |
| 585 | 2026-07-20 | #pine-P2.T3: Tests — openbb-backtest integration test (skipif-not-installed guard) |
| 588 | 2026-07-19 | #pine-P2.P3: Platform — /pine/strategies/list new endpoint (mirror of /pine/indicators/list for bundled strategies) |
| 589 | 2026-07-19 | #pine-P2.R5b: openbb-backtest bridge — shape adapter (TradeSummary→TradeList, equity_df→EquityCurve, stats→BacktestResult.summary) |
| 590 | 2026-07-19 | #pine-P2.R5a: openbb-backtest bridge — maybe_export_to_backtest soft-dep import + warning path |
| 591 | 2026-07-18 | #pine-P2.R3b: Runtime — SecondarySeriesCache disk storage under ~/.openbb/pine_cache/secondary/ + TTL policy |
| 592 | 2026-07-19 | #pine-P2.C7: v5 migration shim — strategy.exit positional-vs-keyword differences + verify security() rewrite still works for strategies |
| 598 | 2026-07-22 | Hook: block-protected-branch-push false-positives on --force-with-lease for non-protected feature branches |
| 601 | 2026-07-13 | [ph0-p2 tier-1a] Add bars.csv support to conformance_strategy harness (per-fixture bar override) |
| 602 | 2026-07-13 | [ph0-p2 tier-1b] Visual TV Strategy Tester walkthrough (README + rsi_reversal pilot guide) |
| 603 | 2026-07-13 | [measurement] measure_wild_corpus_coverage.py reports 0/49 (0%) despite plot/indicator/input.int being implemented — measurement broken post-extraction |
| 604 | 2026-07-13 | [alpha-blocker] Author PINE_ALPHA_QUICKSTART.md + PINE_SUPPORTED_FEATURES.md for alpha testers |
| 605 | 2026-07-13 | [pyne_compiler gap] Support 'var' typed declarations in strategy body (var float x = na) |
| 606 | 2026-07-13 | [post-Wave-20] Retire stale PF010-negative strategy tests in test_type_checker_strategy.py (~20 tests) |
| 607 | 2026-07-13 | [extraction close-out] Reduce openbb-fork's openbb_pine/compiler/*.py to PEP 562 shims (delete fat copies) |
| 608 | 2026-07-13 | [E2/E3 gap] Migrate pyne_compiler internal openbb_pine.* → pyne_compiler.* imports (14 files, ~35 imports) |
| 609 | 2026-07-13 | [E4.2] Update wild-corpus coverage manifest + PRD amendments + bead qj7/7a8 path fixups |
| 610 | 2026-07-13 | [E4.1] Unfreeze 9 P1 sub-beads + rescope DESIGN to pyne_compiler.* + update freeze memory |
| 611 | 2026-07-13 | [E3.4] Rewrite openbb_pine.compiler.* + runtime imports → pyne_compiler.* + delete _data_provider_stub.py |
| 612 | 2026-07-13 | [E3.5] Install deprecation shims per spec §13.5 + M1 smoke test + close-out |
| 613 | 2026-07-13 | [E3.3] Refactor byo_provider.py to inherit pynecore.providers.Provider (mode-1) |
| 614 | 2026-07-13 | [E3.2] Refactor fmp_provider.py to inherit pynecore.providers.Provider (mode-2) |
| 615 | 2026-07-13 | [E3.1] Bump third_party/pynecore submodule pointer to post-E2 HEAD |
| 616 | 2026-07-13 | [E2.4] Post-merge verification + spot-check trailers on 5 commits (incl E0-split) |
| 617 | 2026-07-13 | [E2.3] Merge rewritten history to pynecore main + delete _data_provider_stub.py + open PR |
| 618 | 2026-07-13 | [E2.2] Run git filter-repo with curated --path and --path-rename lists |
| 619 | 2026-07-13 | [E2.1] Prepare scratch clone + tag pre-extraction pynecore HEAD |
| 620 | 2026-07-13 | [hotfix] test_bridge_is_idempotent: clean baseline before assertion (bd-lef followup) |
| 621 | 2026-07-13 | [E1.5] pyne_compiler package placeholder + pyproject verification |
| 622 | 2026-07-13 | [E1.4] Behavioral conformance suite |
| 623 | 2026-07-13 | [E1.2] CSV reference provider |
| 624 | 2026-07-13 | [E1.3] SQLite reference provider |
| 625 | 2026-07-13 | [E1.1] Extend Provider base class with stream() and fetch() concrete methods |
| 626 | 2026-07-13 | [E0.7] Grep-gate verification (E0 completion criterion) |
| 627 | 2026-07-13 | [E0.6] Split test files along the extraction boundary |
| 628 | 2026-07-13 | [E0.4] Abstract telemetry behind TelemetrySink injection point |
| 629 | 2026-07-13 | [E0.5] Extract pynecore sys.path bridge into pynecore_bridge.py |
| 630 | 2026-07-13 | [E0.3] Split executor.py into executor_core.py (moves) + executor_shell.py (stays) |
| 631 | 2026-07-13 | [E0.2] Refactor security_dispatcher to consume abstract Provider (via _data_provider_stub.py) |
| 632 | 2026-07-13 | Pine Extraction to prajoria/pynecore (parent epic) |
| 633 | 2026-07-13 | #pine-P2.T5: Tests — coverage-manifest updates: strategy + request.security + strategy.* builtins → BUILTINS_IMPLEMENTED/FEATURES_IMPLEMENTED |
| 634 | 2026-07-13 | #pine-P2.T1a: Tests — conformance_strategy harness (per-triple fixture discovery + equity/trades/stats parity asserts) |
| 635 | 2026-07-13 | #pine-P2.P2: Platform — strategies_router.run_byo new endpoint (records instead of provider, mirrors bead 0e9.11 pattern) |
| 636 | 2026-07-13 | #pine-P2.P1: Platform — strategies_router.run flip from 501 to real (bead 0e9.11 facade-split pattern) |
| 637 | 2026-07-13 | #pine-P2.R4: Runtime — run_compiled() strategy branch in executor.py |
| 638 | 2026-07-13 | #pine-P2.R3c: Runtime — _install_secondaries_hook monkey-patch of pynecore.lib.request.security |
| 639 | 2026-07-13 | #pine-P2.R3a: Runtime — prefetch_security_contexts + SecondarySeriesCache |
| 640 | 2026-07-13 | #pine-P2.R2b: Runtime — StrategyStatistics → .extra['stats'] dict serializer + per-bar equity snapshot capture |
| 641 | 2026-07-13 | #pine-P2.R2a: Runtime — TradeSummary + OpenPositionSummary dataclasses + PyneCore Trade/SimPosition → wire serializer |
| 642 | 2026-07-13 | #pine-P2.R1: Runtime — CompiledModule.script_type: Literal['indicator','strategy','library'] field addition |
| 643 | 2026-07-13 | #pine-P2.C5b: Codegen — request.security(sym, tf, expr) call site → runtime helper reading prefetched-secondaries dict + __security_contexts__ module constant |
| 644 | 2026-07-13 | #pine-P2.C5a: Codegen — @script.strategy(...) decorator emission from strategy(...) directive |
| 645 | 2026-07-13 | #pine-P2.C3b: Signatures — request.security(sym, tf, expression, gaps=?, lookahead=?) + SecurityContext population in C3 |
| 646 | 2026-07-13 | #pine-P2.C3a: Signatures — strategy.entry/exit/close/close_all/cancel/cancel_all + strategy.long/short + strategy.fixed/cash/percent_of_equity |
| 647 | 2026-07-13 | #pine-P2.C2: Grammar — strategy(...) top-level decl + strategy.entry/exit/close/close_all/cancel/cancel_all + strategy.long/short attribute access |
| 648 | 2026-07-13 | #pine-D5: Strategy engine + request.security runtime design (Phase 2 foundation) |
| 649 | 2026-07-13 | #pine-P1-curated-corpus: Build 30-script curated corpus to unblock M1 gate (f) |
| 650 | 2026-07-13 | #pine-P1-docs: M1 README + cookbook + doctor guide |
| 651 | 2026-07-13 | #pine-P1-facade-byo-split: Split /pine/run into provider + run_byo endpoints (facade fix) |
| 652 | 2026-07-13 | #pine-smoke: M1 real-world smoke test (existing OpenBB user path) |
| 653 | 2026-07-13 | #pine-P1-P1b: Flip /pine/run from 503 stub to real (bead 0e9.5.52 follow-up) |
| 654 | 2026-07-13 | #pine-P1-X1: Conformance harness — auto-discover .pine + .csv pairs |
| 655 | 2026-07-13 | #pine-P1-P7: No-side-effect CI tests (PRD §16.5 enforcement) |
| 656 | 2026-07-13 | #pine-P1-P6: 4 attribution surfaces CI test (PRD §2.6 enforcement) |
| 657 | 2026-07-13 | #pine-P1-P4: openbb pine doctor CLI |
| 658 | 2026-07-13 | #pine-P1-P5: about() + PineAbout typed model — expand from L0.2 scaffold |
| 659 | 2026-07-13 | #pine-P1-P3: MCP tool registration |
| 660 | 2026-07-13 | #pine-P1-P2: Bollinger Bands Workspace widget |
| 661 | 2026-07-13 | #pine-P1-P1: 6 REST endpoints scaffolded |
| 662 | 2026-07-13 | #pine-P1-S-math.sqrt: square root |
| 663 | 2026-07-13 | #pine-P1-S-math.pow: exponentiation |
| 664 | 2026-07-13 | #pine-P1-S-math.round: rounding |
| 665 | 2026-07-13 | #pine-P1-S-math.min: elementwise min |
| 666 | 2026-07-13 | #pine-P1-S-math.max: elementwise max |
| 667 | 2026-07-13 | #pine-P1-S-math.abs: absolute value |
| 668 | 2026-07-13 | #pine-P1-S-math.sum: rolling sum |
| 669 | 2026-07-13 | #pine-P1-S-ta.barssince: bars-since-true |
| 670 | 2026-07-13 | #pine-P1-S-ta.cum: cumulative sum |
| 671 | 2026-07-13 | #pine-P1-S-ta.percentile_linear_interpolation: percentile with lerp |
| 672 | 2026-07-13 | #pine-P1-S-ta.median: rolling median |
| 673 | 2026-07-13 | #pine-P1-S-ta.linreg: linear regression value |
| 674 | 2026-07-13 | #pine-P1-S-ta.sar: parabolic SAR |
| 675 | 2026-07-13 | #pine-P1-S-ta.tr: true range |
| 676 | 2026-07-13 | #pine-P1-S-ta.roc: rate of change |
| 677 | 2026-07-13 | #pine-P1-S-ta.mom: momentum |
| 678 | 2026-07-13 | #pine-P1-S-ta.change: bar-over-bar difference |
| 679 | 2026-07-13 | #pine-P1-S-ta.stdev: rolling stdev (population) |
| 680 | 2026-07-13 | #pine-P1-S-ta.lowest: rolling min |
| 681 | 2026-07-13 | #pine-P1-S-ta.highest: rolling max |
| 682 | 2026-07-13 | #pine-P1-S-ta.crossunder: crossunder detector |
| 683 | 2026-07-13 | #pine-P1-S-ta.crossover: crossover detector |
| 684 | 2026-07-13 | #pine-P1-S-ta.vwap: volume-weighted average price |
| 685 | 2026-07-13 | #pine-P1-S-ta.obv: on-balance volume |
| 686 | 2026-07-13 | #pine-P1-S-ta.mfi: money flow index |
| 687 | 2026-07-13 | #pine-P1-S-ta.adx: average directional index |
| 688 | 2026-07-13 | #pine-P1-S-ta.cci: commodity channel index |
| 689 | 2026-07-13 | #pine-P1-S-ta.stoch: stochastic %K |
| 690 | 2026-07-13 | #pine-P1-S-ta.atr: average true range |
| 691 | 2026-07-13 | #pine-P1-S-ta.bb: Bollinger Bands |
| 692 | 2026-07-13 | #pine-P1-S-ta.macd: moving average convergence divergence |
| 693 | 2026-07-13 | #pine-P1-S-ta.rsi: relative strength index |
| 694 | 2026-07-13 | #pine-P1-S-ta.rma: Wilder's smoothing (RSI's smoothing fn) |
| 695 | 2026-07-13 | #pine-P1-S-ta.wma: weighted moving average |
| 696 | 2026-07-13 | #pine-P1-S-ta.ema: exponential moving average |
| 697 | 2026-07-13 | #pine-P1-S-ta.sma: simple moving average |
| 698 | 2026-07-13 | #pine-P1-R6: FMP retry budget — 5 attempts + exp backoff + jitter (D2 §9) |
| 699 | 2026-07-13 | #pine-P1-R7: Result emission — OBBject.results + .extra keys |
| 700 | 2026-07-13 | #pine-P1-R5: ExecLimits — timeout + RLIMIT_AS + bar cap (PRD §5.2 T2) |
| 701 | 2026-07-13 | #pine-P1-R4: RestrictedExec namespace (PRD §5.2 T3) |
| 702 | 2026-07-13 | #pine-P1-R3: Provider precedence + non-FMP fast-fail (PRD §13.8 enforcement) |
| 703 | 2026-07-13 | #pine-P1-R2: BYODataProvider — primary-series-only schema validation |
| 704 | 2026-07-13 | #pine-P1-R1: FMPOHLCVProvider — single concrete class + asset-class dispatch |
| 705 | 2026-07-13 | #pine-P1-C8: Error model — PineError hierarchy + diagnostics + tracking_url |
| 706 | 2026-07-13 | #pine-P1-C7: v5->v6 auto-migration shim |
| 707 | 2026-07-13 | #pine-P1-C6: Compile cache — blake2b key + atomic write |
| 708 | 2026-07-13 | #pine-P1-C5: Codegen — tree-walk + closed allowlist gate (T1 mitigation) |
| 709 | 2026-07-13 | #pine-P1-C4: IR dataclasses per D1 §2 |
| 710 | 2026-07-13 | #pine-P1-C2: Parser — lark Earley grammar (pinned ==1.2.2) |
| 711 | 2026-07-13 | #pine-P1-C3: Type checker — (qualifier, inner) lattice + 8 non-trivial rules |
| 712 | 2026-07-13 | #pine-P1-C1: Lexer — hand-rolled DFA + //@version= pragma + INDENT/DEDENT |
| 713 | 2026-07-13 | #pine-P0-L0.6: File Phase 1 sub-beads with concrete M1 acceptance criteria |
| 714 | 2026-07-13 | #pine-P0-L0.4: Crawl wild-corpus baseline (top-1000 community Pine scripts) |
| 715 | 2026-07-13 | #pine-P0-L0.5: wild-corpus-coverage CI job |
| 716 | 2026-07-13 | #pine-P0-L0.2: Scaffold openbb_platform/extensions/pine/ per D3 |
| 717 | 2026-07-13 | #pine-P0-L0.3: Pin PyneCore submodule + license-SHA CI check |
| 718 | 2026-07-13 | #pine-P0-L0.1: Outside counsel sign-off on PRD §2 (clean-room SOP + Appendix A) |
| 719 | 2026-07-13 | #pine-P1: MVP — 30 wild-ranked builtins, FMP + BYO, v5+v6, >=40% wild-corpus (GH #107) |
| 720 | 2026-07-13 | #pine-P0: Foundation — counsel, scaffold, submodule pin, wild-corpus baseline (GH #106) |
| 721 | 2026-07-13 | #pine-D3: OpenBB Platform integration design (GH #105) |
| 722 | 2026-07-13 | #pine-D2: Runtime + OHLCV bridge design — FMP-only (GH #104) |
| 723 | 2026-07-13 | #pine-D1: Compiler architecture design (GH #103) |
| 724 | 2026-07-13 | [pyne_compiler gap] Support strategy.position_size read (position introspection) |
| 725 | 2026-07-13 | #pine-P1-static-facade: obb.pine.* facade broken by static package builder (obb.* env-wide issue) |
| 726 | 2026-07-13 | #pine-P1-L0.4b: Wild-corpus expansion strategy — unblock M1 gate (f) |
| 727 | 2026-07-13 | #pine-P1-X2: Pine v5 roundtrip integration test |
| 728 | 2026-07-13 | 82: backtest_bridge + validate + attach ValidationReport |
| 738 | 2026-07-15 | [tech-debt] Pydantic v2 forward-ref TypeError in fmp_trading blocks 100+ tests |
| 739 | 2026-07-15 | [tech-debt] pytest 'tests' namespace collision across extensions (~55 collection errors) |
| 740 | 2026-07-15 | [tech-debt] dev_install.py installs into Poetry venv, not project .venv_win |
| 741 | 2026-07-19 | [portfolio] [bug] Scaffold _include_subrouters leaks ModuleNotFoundError when routers/ dir absent |
| 743 | 2026-07-18 | [test-failure] Epic: post-merge test failures on trading_technicals (2026-07-13) |
| 744 | 2026-07-15 | [test-failure] fmp_trading: DailyConfig.date field annotation fails collection (5 errors) |
| 745 | 2026-07-18 | [test-failure] mcp_server: 7 test failures (168 pass, 7 fail) |
| 746 | 2026-07-18 | [test-failure] platform_api: 3 test failures (68 pass, 3 fail) |
| 747 | 2026-07-18 | [test-failure] agents: 4 test failures (46 pass, 4 fail) |
| 748 | 2026-07-18 | [test-failure] extensions/tests: 7 test failures (8 pass, 7 fail) |
| 749 | 2026-07-18 | [test-failure] core: 1 test failure (999 pass, 1 fail) |
| 750 | 2026-07-15 | [test-failure] backtest: 1 test failure (459 pass, 1 fail) |
| 751 | 2026-07-18 | [test-failure] fmp provider: 1 test failure (66 pass, 1 fail) |
| 752 | 2026-07-15 | [test-failure] fmp_cached: 4 collection errors |
| 753 | 2026-07-18 | [test-failure] sec provider: 5 collection errors (335 pass otherwise) |
| 754 | 2026-07-14 | [test-failure] providers/tests: 81 failures out of 83 (cross-provider smoke) |
| 755 | 2026-07-15 | [test-failure] openbb_platform/tests (top-level): 3 failures out of 9 |
| 757 | 2026-07-18 | [test-failure] fmp_trading: 54 tests fail after collection fix (follow-up to #744) |
| 763 | 2026-07-15 | [tech-debt] quantitative + technical tests: ModuleNotFoundError: 'extensions' |
| 764 | 2026-07-15 | [tech-debt] techtrade tests: cross-extension 'tests.fixtures' import collision (4 files) |
| 765 | 2026-07-15 | [tech-debt] fmp_cached tests: 'tests.test_config' collides with agents' test_config |
| 767 | 2026-07-15 | [tech-debt] fmp_trading unit tests: 41 failures from stale TickEvent/Quote fixtures |
| 771 | 2026-07-18 | [test-failure] fmp_cached: 88 fails + 6 errors require MySQL localhost (not marked integration) |
| 774 | 2026-07-15 | fmp_cached: SQL syntax error on empty symbols list in aftermarket_quote._fetch_fresh_rows |
| 775 | 2026-07-15 | fmp_cached: setup_database.py awaits sync init_database/create_all_tables |
| 776 | 2026-07-15 | fmp_cached: financial_ratios ADD UNIQUE KEY logs ERROR before catch |
| 780 | 2026-07-20 | [portfolio] Verify TradingView 31-indicator coverage across portfolio_basket tickers |
| 781 | 2026-07-21 | [portfolio] Single Equity Profile Dashboard — PRD + data-coverage + section-by-section implementation |
| 782 | 2026-07-15 | fmp_cached: 3 integration test files missing @pytest.mark.integration marker |
| 783 | 2026-07-15 | fmp_cached: test_institutional_ownership_cached uses stale _get_cached_institutional signature (7 fails) |
| 784 | 2026-07-18 | fmp_cached: tests reference module attributes that no longer exist (execute_many, get_cache_manager, CACHE_TTL, get_ttl_for_endpoint) |
| 785 | 2026-07-17 | fmp_cached: 4 test_fmp_cached_fetchers tests missing recorded VCR cassettes |
| 790 | 2026-07-18 | PR #762 re-verify: 82 fails + 6 errors across 1690 tests after fresh venv + #758/#761/#766/#768/#769 |
| 792 | 2026-07-18 | fmp_cached: 15 fails in test_institutional_ownership_cached — _get_cached_institutional() signature drift |
| 793 | 2026-07-16 | fmp_cached: 4 fails in test_ttl_wrapper — closure captures pre-patch execute_query reference |
| 794 | 2026-07-18 | fmp_cached: 12 fails in test_real_integration — datetime.date not coerced before MySQL driver call |
| 795 | 2026-07-18 | fmp_cached: 6 errors in test_fmp_cached_fetchers — missing VCR cassettes + Fetcher subclass contract |
| 796 | 2026-07-16 | extensions/tests: 16 fork routes missing examples= + integration tests |
| 802 | 2026-07-18 | [portfolio] portfolio_intel: entry-point references missing router module → breaks 'from openbb import obb' |
| 803 | 2026-07-16 | [backtest] add examples= + integration tests for backtest.about |
| 804 | 2026-07-16 | [fmp_trading] add examples= + integration tests for 3 routes (doctor / replay / report) |
| 805 | 2026-07-16 | [regime] add examples= + integration tests for regime.about / regime.detect |
| 806 | 2026-07-16 | [techtrade] add examples= + integration tests for 11 routes across 6 router modules |
| 807 | 2026-07-16 | [extensions/tests] provider allowlist regressions — fmp_cached + fmp_trading not registered |
| 813 | 2026-07-18 | [financialtoolkit] 25 routes missing integration tests (pre-existing on develop) |
| 816 | 2026-07-17 | [develop_test_issues] 185 test failures uncovered by 2026-07-16 CI collection fix (umbrella) |
| 817 | 2026-07-16 | [techtrade] ~30 tests fail — pandas_ta_classic not installed on CI |
| 818 | 2026-07-17 | [agents] ~8 tests fail — google.adk not installed on CI (litellm needs Rust toolchain) |
| 819 | 2026-07-17 | [backtest] test_analytics_common — empyrical not installed on CI |
| 820 | 2026-07-16 | [fmp_cached] ~20 tests require live MySQL DB — no CI DB container |
| 821 | 2026-07-16 | [fmp_trading] ~55 real regressions — TickData / session_status / registry / model drift |
| 822 | 2026-07-17 | [mcp_server] 3 test files fail — prompt/skills/tool-execution regressions |
| 823 | 2026-07-17 | [techtrade] test_scaffolding — real regression beyond pandas_ta_classic |
| 824 | 2026-07-17 | [core] test_openapi — OBBject[BacktestResult] forward-ref never rebuilt (pydantic strictness) |
| 825 | 2026-07-17 | [platform_api] test_get_apps_json_* — apps.json handling regression |
| 826 | 2026-07-18 | [portfolio] [ops] CI: reject PRs whose Closes clause doesn't cite a real #NN |
| 827 | 2026-07-20 | [portfolio] [M1-preflight] fmp_cached endpoint audit for P0 data-layer clusters |
| 838 | 2026-07-19 | [portfolio] [ops] codespell false-positive on SME in PRD.md — pre-existing lint debt on portfolio |
| 844 | 2026-07-22 | [fmp] [EPIC] FMP Cached Full API Coverage (openbb-fmp-cached) |
| 847 | 2026-07-19 | [portfolio] [ops] CI: auto-close #NN cited in feat/pi-* PR bodies on portfolio-merge |
| 849 | 2026-07-19 | [portfolio] portfolio_intel: generated package uses ExtensionAbout without importing it |
| 851 | 2026-07-18 | [portfolio] [ops] closes-syntax check false-positive on prose 'Fixes <backticked-identifier>' |
| 856 | 2026-07-18 | [portfolio] [ops] add openbb-backtest to dev_install default sweep |
| 859 | 2026-07-18 | rest_api.py imports non-existent openbb_core.api.app_loader — REST API cannot start |
| 860 | 2026-07-18 | pytest unit collection: 2 broken imports in fmp_trading + fmp_cached test modules |
| 861 | 2026-07-18 | fmp_trading doctor imports non-existent ping_cache — silently reports mysql_cache_ok: false |
| 865 | 2026-07-18 | [portfolio] [ops] dev_install.py poetry flow doesn't populate fresh pip venvs |
| 867 | 2026-07-18 | pytest: 4 fmp_cached tests skip with 'async def not natively supported' (missing asyncio marker) |
| 868 | 2026-07-18 | fmp_trading reporting: OutputPathEscapesJail exception missing — 4 security-hardening tests fail |
| 869 | 2026-07-18 | backtest registry: 4 scaffolding tests cross-contaminate — 'unit_demo_strategy already registered' |
| 870 | 2026-07-18 | fmp_trading architecture test: pip install fails because openbb-techtrade not on PyPI |
| 871 | 2026-07-18 | fmp_trading agent submodules import when [agent] extra should be hidden — guard broken or bypassed |
| 872 | 2026-07-18 | pyproject: openbb-portfolio-custom version mismatch (main has empty, extension has 1.0.0) |
| 873 | 2026-07-18 | agents mcp_server: test_end_to_end_mcp_call_tool_wraps_isError_and_payload fails on py3.12 with 'no current event loop' |
| 874 | 2026-07-18 | cftc provider fires live HTTP during FastAPI startup — 503 from upstream kills entire REST API |
| 875 | 2026-07-20 | [pine] Clean up pre-existing pylint warnings in strategies_router.py (deferred from #848) |
| 876 | 2026-07-19 | [portfolio] [ops] add 4 fork-only extensions to dev_install.py LOCAL_DEPS (regime, fmp_cached, fmp_trading, financialtoolkit) |
| 886 | 2026-07-19 | [portfolio] [ops] vendor portfolio-export into openbb_platform/tools/portfolio_export |
| 888 | 2026-07-19 | [portfolio] [tools] add test-data generator to portfolio_export as pe-testdata module |
| 892 | 2026-07-19 | [portfolio] [P2][Paper] SimpleFillModel adapter scaffold — implements openbb_backtest Broker Protocol, Market fills only |
| 894 | 2026-07-19 | openbb_core_journal missing from PyPI wheel — architecture test collection fails without [agent] extra |
| 896 | 2026-07-19 | Follow-up to #868: 2 symlink-hardening tests still 'DID NOT RAISE' — writer path missing check on target file itself |
| 902 | 2026-07-19 | cftc build_choices: crashes API on startup when any record has null subcategory (post-#882 downstream) |
| 903 | 2026-07-20 | [portfolio] [P2][Analytics] What-If: cash line + funding-model support (follow-up to #558) |
| 904 | 2026-07-20 | [portfolio] [P2][Analytics] What-If: short-position support with signed rollups (follow-up to #558) |
| 909 | 2026-07-20 | [portfolio] [ops] fmp_cached mypy debt: 13 pre-existing errors across 4 files |
| 935 | 2026-07-21 | [portfolio] [P2][Testing] Brinson-Fachler synthetic test-data generator & fixture oracle (enables #559) |
| 951 | 2026-07-22 | [pine] Extend reshape_tv_trades.py with structural validation + metadata capture (D2.1/D2.2) |
| 953 | 2026-07-21 | [portfolio] [ops] Enforce Project #4 Status=In Progress on issue claim (pi_claim.py helper + CLAUDE.md rule) |
| 955 | 2026-07-22 | [portfolio] [P2][Data] Expand fmp_cached fixture coverage — 65 uncovered endpoints (follow-up to #508) |
| 957 | 2026-07-22 | [pine] Promote hybrid-fixture-suite brainstorm to formal design spec |
| 959 | 2026-07-21 | [portfolio] [P2][Data] fmp_cached fixture drain batch 1 (14 endpoints) — closes-syntax tracker |
| 961 | 2026-07-21 | [portfolio] [P2][Data] fmp_cached fixture drain batch 2 (8 endpoints) — closes-syntax tracker |
| 963 | 2026-07-21 | [portfolio] [ops] fmp_api_key leaks in FMP-error exception URLs — needs scrubbing |
| 964 | 2026-07-21 | [portfolio] [P2][Data] fmp_cached fixture drain batch 3 (9 endpoints) — closes-syntax tracker |
| 967 | 2026-07-22 | [pine] Implementation Session 1: D2.3 capture_bars_provenance + canonical_bars module |
| 968 | 2026-07-21 | [portfolio] [P2][Data] fmp_cached fixture drain batch 4 (7 endpoints) — closes-syntax tracker |
| 973 | 2026-07-22 | [pine] CLAUDE.md: claim + heartbeat protocol for autonomous cycles on Project #5 |
| 981 | 2026-07-21 | [portfolio] [P1][Tooling] Widget host + canvas: mount point for portfolio-intel dashboard widgets (blocks #529-#577) |
| 982 | 2026-07-21 | [portfolio] [P1][Tooling] Portfolio-intel widget SDK: shared React components + typed backend client + fixture-preview harness |
| 983 | 2026-07-21 | [portfolio] [P1][Tooling] Frontend CI: lint + typecheck + vitest job on the pi widget subtree |
| 984 | 2026-07-21 | local-ci P0: land formal spec + resolve open decisions (#980) |
| 985 | 2026-09-06 | local-ci P1: deterministic CLI + YAML schema (ci/local-ci) (#980) |
| 989 | 2026-09-06 | local-ci P5: agent skill wrapper — thin shell-out to CLI (#980) |
| 990 | 2026-07-21 | [portfolio] Equity Profile §1 — Header & multi-feed live price ticker |
| 991 | 2026-07-21 | [portfolio] Equity Profile §2 — Key stats grid + earnings milestone + employee efficiency |
| 992 | 2026-07-21 | [portfolio] Equity Profile §3 — Financial statement charts (3 modules) |
| 993 | 2026-07-21 | [portfolio] Equity Profile §4 — Technicals + pivot matrix + ATM IV term structure |
| 994 | 2026-07-21 | [portfolio] Equity Profile §5 — Analyst forecasts + surprise engine |
| 995 | 2026-07-21 | [portfolio] Equity Profile §6 — ETF exposure + highest-yielding debt ladder |
| 996 | 2026-07-21 | [portfolio] Equity Profile §7 — Competitor comparison strip |
| 997 | 2026-07-22 | [fmp_cached-gap] Rating split per analyst (Strong Buy / Buy / Hold / Sell / Strong Sell counts, past N days) |
| 998 | 2026-07-22 | [fmp_cached-gap] Historical quarterly revenue estimate snapshotting (blocks Equity Profile §5C) |
| 999 | 2026-07-22 | [provider-gap] Options chain + ATM IV term structure (blocks Equity Profile §4B) |
| 1000 | 2026-07-22 | [provider-gap] Corporate-bond issuance + YTM (blocks Equity Profile §6B) |
| 1007 | 2026-07-21 | [portfolio] [P1][Tooling] OpenBB Workspace backend for portfolio-intel widgets (widgets.json + FastAPI) |
| 1021 | 2026-07-22 | [fmp_cached] #997.1 — Spike: inspect existing surface for rating count fields |
| 1022 | 2026-07-22 | [fmp_cached] #997.2 — Implement FMPCachedAnalystRecommendationsFetcher |
| 1023 | 2026-07-22 | [widget] #997.3 — Wire pi_equity_analyst_forecasts widget to real rating data |
| 1024 | 2026-07-22 | [fmp_cached] #998.1 — Design: analyst_estimates append-vs-overwrite semantics |
| 1025 | 2026-07-22 | [fmp_cached] #998.2 — Implement historical estimate snapshotting |
| 1026 | 2026-07-22 | [widget] #998.3 — Wire pi_equity_analyst_forecasts widget to real surprise data |
| 1028 | 2026-07-22 | [fmp] [WAVE 0] Inventory + harness (audit, templates, migration) |
| 1029 | 2026-07-22 | [fmp] [WAVE 1] Fundamentals completion (Arc C: statements/DCF/metrics) |
| 1030 | 2026-07-22 | [fmp] [WAVE 2] Quotes & snapshots (Arc D) |
| 1031 | 2026-07-22 | [fmp] [WAVE 3] Time-series completion (Arc B) |
| 1032 | 2026-07-22 | [fmp] [WAVE 4] Reference / directory (Arc A) |
| 1033 | 2026-07-22 | [fmp] [WAVE 5] Event feeds: filings & governance (Arc E) |
| 1034 | 2026-07-22 | [fmp] [WAVE 6] Event feeds: news, calendars, transcripts, fundraisers, ESG (Arc E) |
| 1035 | 2026-07-22 | [fmp] [WAVE 7] Analyst & market-performance remainder |
| 1036 | 2026-07-22 | [fmp] [WAVE 8] Bulk (Arc F) + Partners/COT/TipRanks (Arc G) |
| 1037 | 2026-07-22 | [fmp] [WAVE 9] Hardening & docs |
| 1038 | 2026-07-22 | [fmp] [W4][Search] Stock Symbol Search (search-symbol) |
| 1039 | 2026-07-22 | [fmp] [W4][Search] Company Name Search (search-name) |
| 1040 | 2026-07-22 | [fmp] [W4][Search] Search Cik (search-cik) |
| 1041 | 2026-07-22 | [fmp] [W4][Search] CUSIP (search-cusip) |
| 1042 | 2026-07-22 | [fmp] [W4][Search] Search Isin (search-isin) |
| 1043 | 2026-07-22 | [fmp] [W4][Search] Stock Screener (company-screener) |
| 1044 | 2026-07-22 | [fmp] [W4][Search] Exchange Variants (search-exchange-variants) |
| 1045 | 2026-07-22 | [fmp] [W4][Directory] Company Symbols List (stock-list) |
| 1046 | 2026-07-22 | [fmp] [W4][Directory] Financial Statement Symbols List (financial-statement-symbol-list) |
| 1047 | 2026-07-22 | [fmp] [W4][Directory] CIK List (cik-list) |
| 1048 | 2026-07-22 | [fmp] [W5][Directory] Symbol Changes List (symbol-change) |
| 1049 | 2026-07-22 | [fmp] [W4][Directory] ETF Symbol Search (etf-list) |
| 1050 | 2026-07-22 | [fmp] [W4][Directory] Actively Trading List (actively-trading-list) |
| 1051 | 2026-07-22 | [fmp] [W4][Directory] Earnings Transcript List (earnings-transcript-list) |
| 1052 | 2026-07-22 | [fmp] [W4][Directory] Available Exchanges (available-exchanges) |
| 1053 | 2026-07-22 | [fmp] [W4][Directory] Available Sectors (available-sectors) |
| 1054 | 2026-07-22 | [fmp] [W4][Directory] Available Industries (available-industries) |
| 1055 | 2026-07-22 | [fmp] [W4][Directory] Available Countries (available-countries) |
| 1056 | 2026-07-22 | [fmp] [W1][Analyst] Financial Estimates (analyst-estimates) |
| 1057 | 2026-07-22 | [fmp] [W7][Analyst] Ratings Snapshot (ratings-snapshot) |
| 1058 | 2026-07-22 | [fmp] [W7][Analyst] Historical Ratings (ratings-historical) |
| 1059 | 2026-07-22 | [fmp] [W7][Analyst] Price Target Summary (price-target-summary) |
| 1060 | 2026-07-22 | [fmp] [W7][Analyst] Price Target Consensus (price-target-consensus) |
| 1061 | 2026-07-22 | [fmp] [W7][Analyst] Stock Grades (grades) |
| 1062 | 2026-07-22 | [fmp] [W7][Analyst] Historical Stock Grades (grades-historical) |
| 1063 | 2026-07-22 | [fmp] [W7][Analyst] Stock Grades Summary (grades-consensus) |
| 1064 | 2026-07-22 | [fmp] [W6][Calendar] Dividends Company (dividends) |
| 1065 | 2026-07-22 | [fmp] [W6][Calendar] Dividends Calendar (dividends-calendar) |
| 1066 | 2026-07-22 | [fmp] [W6][Calendar] Earnings Report (earnings) |
| 1067 | 2026-07-22 | [fmp] [W6][Calendar] Earnings Calendar (earnings-calendar) |
| 1068 | 2026-07-22 | [fmp] [W6][Calendar] IPOs Calendar (ipos-calendar) |
| 1069 | 2026-07-22 | [fmp] [W6][Calendar] IPOs Disclosure (ipos-disclosure) |
| 1070 | 2026-07-22 | [fmp] [W6][Calendar] IPOs Prospectus (ipos-prospectus) |
| 1071 | 2026-07-22 | [fmp] [W6][Calendar] Stock Split Details (splits) |
| 1072 | 2026-07-22 | [fmp] [W6][Calendar] Stock Splits Calendar (splits-calendar) |
| 1073 | 2026-07-22 | [fmp] [W3][Chart] Stock Chart Light (historical-price-eod/light) |
| 1074 | 2026-07-22 | [fmp] [W3][Chart] Stock Price and Volume Data (historical-price-eod/full) |
| 1075 | 2026-07-22 | [fmp] [W3][Chart] Unadjusted Stock Price (historical-price-eod/non-split-adjusted) |
| 1076 | 2026-07-22 | [fmp] [W3][Chart] Dividend Adjusted Price Chart (historical-price-eod/dividend-adjusted) |
| 1077 | 2026-07-22 | [fmp] [W3][Chart] 1 Min Interval Stock Chart (historical-chart/1min) |
| 1078 | 2026-07-22 | [fmp] [W3][Chart] 5 Min Interval Stock Chart (historical-chart/5min) |
| 1079 | 2026-07-22 | [fmp] [W3][Chart] 15 Min Interval Stock Chart (historical-chart/15min) |
| 1080 | 2026-07-22 | [fmp] [W3][Chart] 30 Min Interval Stock Chart (historical-chart/30min) |
| 1081 | 2026-07-22 | [fmp] [W3][Chart] 1 Hour Interval Stock Chart (historical-chart/1hour) |
| 1082 | 2026-07-22 | [fmp] [W3][Chart] 4 Hour Interval Stock Chart (historical-chart/4hour) |
| 1083 | 2026-07-22 | [fmp] [W1][Company] Company Profile Data (profile) |
| 1084 | 2026-07-22 | [fmp] [W1][Company] Company Profile by CIK (profile-cik) |
| 1085 | 2026-07-22 | [fmp] [W4][Company] Company Notes (company-notes) |
| 1086 | 2026-07-22 | [fmp] [W4][Company] Stock Peer Comparison (stock-peers) |
| 1087 | 2026-07-22 | [fmp] [W5][Company] Delisted Companies (delisted-companies) |
| 1088 | 2026-07-22 | [fmp] [W1][Company] Company Employee Count (employee-count) |
| 1089 | 2026-07-22 | [fmp] [W3][Company] Company Historical Employee Count (historical-employee-count) |
| 1090 | 2026-07-22 | [fmp] [W2][Company] Company Market Cap (market-capitalization) |
| 1091 | 2026-07-22 | [fmp] [W2][Company] Batch Market Cap (market-capitalization-batch) |
| 1092 | 2026-07-22 | [fmp] [W3][Company] Historical Market Cap (historical-market-capitalization) |
| 1093 | 2026-07-22 | [fmp] [W2][Company] Company Share Float & Liquidity (shares-float) |
| 1094 | 2026-07-22 | [fmp] [W4][Company] All Shares Float (shares-float-all) |
| 1095 | 2026-07-22 | [fmp] [W5][Company] Latest Mergers & Acquisitions (mergers-acquisitions-latest) |
| 1096 | 2026-07-22 | [fmp] [W5][Company] Search Mergers & Acquisitions (mergers-acquisitions-search) |
| 1097 | 2026-07-22 | [fmp] [W1][Company] Company Executives (key-executives) |
| 1098 | 2026-07-22 | [fmp] [W1][Company] Executive Compensation (governance-executive-compensation) |
| 1099 | 2026-07-22 | [fmp] [W4][Company] Executive Compensation Benchmark (executive-compensation-benchmark) |
| 1100 | 2026-07-22 | [fmp] [W8][CommitmentOfTraders] COT Report (commitment-of-traders-report) |
| 1101 | 2026-07-22 | [fmp] [W8][CommitmentOfTraders] COT Analysis By Dates (commitment-of-traders-analysis) |
| 1102 | 2026-07-22 | [fmp] [W4][CommitmentOfTraders] COT Report List (commitment-of-traders-list) |
| 1103 | 2026-07-22 | [fmp] [W1][DiscountedCashFlow] DCF Valuation (discounted-cash-flow) |
| 1104 | 2026-07-22 | [fmp] [W1][DiscountedCashFlow] Levered DCF (levered-discounted-cash-flow) |
| 1105 | 2026-07-22 | [fmp] [W1][DiscountedCashFlow] Custom DCF Advanced (custom-discounted-cash-flow) |
| 1106 | 2026-07-22 | [fmp] [W1][DiscountedCashFlow] Custom DCF Levered (custom-levered-discounted-cash-flow) |
| 1107 | 2026-07-22 | [fmp] [W3][Economics] Treasury Rates (treasury-rates) |
| 1108 | 2026-07-22 | [fmp] [W3][Economics] Economics Indicators (economic-indicators) |
| 1109 | 2026-07-22 | [fmp] [W5][Economics] Economic Data Releases Calendar (economic-calendar) |
| 1110 | 2026-07-22 | [fmp] [W4][Economics] Market Risk Premium (market-risk-premium) |
| 1111 | 2026-07-22 | [fmp] [W6][ESG] ESG Investment Search (esg-disclosures) |
| 1112 | 2026-07-22 | [fmp] [W6][ESG] ESG Ratings (esg-ratings) |
| 1113 | 2026-07-22 | [fmp] [W8][ESG] ESG Benchmark Comparison (esg-benchmark) |
| 1114 | 2026-07-22 | [fmp] [W1][EtfAndMutualFunds] ETF & Fund Holdings (etf/holdings) |
| 1115 | 2026-07-22 | [fmp] [W4][EtfAndMutualFunds] ETF & Mutual Fund Information (etf/info) |
| 1116 | 2026-07-22 | [fmp] [W4][EtfAndMutualFunds] ETF & Fund Country Allocation (etf/country-weightings) |
| 1117 | 2026-07-22 | [fmp] [W4][EtfAndMutualFunds] ETF Asset Exposure (etf/asset-exposure) |
| 1118 | 2026-07-22 | [fmp] [W4][EtfAndMutualFunds] ETF Sector Weighting (etf/sector-weightings) |
| 1119 | 2026-07-22 | [fmp] [W5][EtfAndMutualFunds] Mutual Fund & ETF Disclosure (funds/disclosure-holders-latest) |
| 1120 | 2026-07-22 | [fmp] [W5][EtfAndMutualFunds] Mutual Fund Disclosures (funds/disclosure) |
| 1121 | 2026-07-22 | [fmp] [W5][EtfAndMutualFunds] Mutual Fund & ETF Disclosure Name Search (funds/disclosure-holders-search) |
| 1122 | 2026-07-22 | [fmp] [W5][EtfAndMutualFunds] Fund & ETF Disclosures by Date (funds/disclosure-dates) |
| 1123 | 2026-07-22 | [fmp] [W1][Statements] Income Statement (income-statement) |
| 1124 | 2026-07-22 | [fmp] [W1][Statements] Balance Sheet Statement (balance-sheet-statement) |
| 1125 | 2026-07-22 | [fmp] [W1][Statements] Cash Flow Statement (cash-flow-statement) |
| 1126 | 2026-07-22 | [fmp] [W1][Statements] Latest Financial Statements (latest-financial-statements) |
| 1127 | 2026-07-22 | [fmp] [W1][Statements] Income Statements TTM (income-statement-ttm) |
| 1128 | 2026-07-22 | [fmp] [W1][Statements] Balance Sheet Statements TTM (balance-sheet-statement-ttm) |
| 1129 | 2026-07-22 | [fmp] [W1][Statements] Cashflow Statements TTM (cash-flow-statement-ttm) |
| 1130 | 2026-07-22 | [fmp] [W1][Statements] Key Metrics (key-metrics) |
| 1131 | 2026-07-22 | [fmp] [W1][Statements] Financial Ratios (ratios) |
| 1132 | 2026-07-22 | [fmp] [W1][Statements] Key Metrics TTM (key-metrics-ttm) |
| 1133 | 2026-07-22 | [fmp] [W1][Statements] Financial Ratios TTM (ratios-ttm) |
| 1134 | 2026-07-22 | [fmp] [W1][Statements] Financial Scores (financial-scores) |
| 1135 | 2026-07-22 | [fmp] [W1][Statements] Owner Earnings (owner-earnings) |
| 1136 | 2026-07-22 | [fmp] [W1][Statements] Enterprise Values (enterprise-values) |
| 1137 | 2026-07-22 | [fmp] [W1][Statements] Income Statement Growth (income-statement-growth) |
| 1138 | 2026-07-22 | [fmp] [W1][Statements] Balance Sheet Statement Growth (balance-sheet-statement-growth) |
| 1139 | 2026-07-22 | [fmp] [W1][Statements] Cashflow Statement Growth (cash-flow-statement-growth) |
| 1140 | 2026-07-22 | [fmp] [W1][Statements] Financial Statement Growth (financial-growth) |
| 1141 | 2026-07-22 | [fmp] [W1][Statements] Financial Reports Dates (financial-reports-dates) |
| 1142 | 2026-07-22 | [fmp] [W1][Statements] Financial Reports Form 10-K JSON (financial-reports-json) |
| 1143 | 2026-07-22 | [fmp] [W1][Statements] Financial Reports Form 10-K XLSX (financial-reports-xlsx) |
| 1144 | 2026-07-22 | [fmp] [W1][Statements] Revenue Product Segmentation (revenue-product-segmentation) |
| 1145 | 2026-07-22 | [fmp] [W1][Statements] Revenue Geographic Segments (revenue-geographic-segmentation) |
| 1146 | 2026-07-22 | [fmp] [W1][Statements] As Reported Income Statements (income-statement-as-reported) |
| 1147 | 2026-07-22 | [fmp] [W1][Statements] As Reported Balance Statements (balance-sheet-statement-as-reported) |
| 1148 | 2026-07-22 | [fmp] [W1][Statements] As Reported Cashflow Statements (cash-flow-statement-as-reported) |
| 1149 | 2026-07-22 | [fmp] [W1][Statements] As Reported Financial Statements (financial-statement-full-as-reported) |
| 1150 | 2026-07-22 | [fmp] [W5][Form13F] Institutional Ownership Filings (institutional-ownership/latest) |
| 1151 | 2026-07-22 | [fmp] [W5][Form13F] Filings Extract (institutional-ownership/extract) |
| 1152 | 2026-07-22 | [fmp] [W5][Form13F] Form 13F Filings Dates (institutional-ownership/dates) |
| 1153 | 2026-07-22 | [fmp] [W5][Form13F] Filings Extract With Analytics By Holder (institutional-ownership/extract-analytics/holder) |
| 1154 | 2026-07-22 | [fmp] [W5][Form13F] Holder Performance Summary (institutional-ownership/holder-performance-summary) |
| 1155 | 2026-07-22 | [fmp] [W5][Form13F] Holders Industry Breakdown (institutional-ownership/holder-industry-breakdown) |
| 1156 | 2026-07-22 | [fmp] [W5][Form13F] Positions Summary (institutional-ownership/symbol-positions-summary) |
| 1157 | 2026-07-22 | [fmp] [W5][Form13F] Industry Performance Summary (institutional-ownership/industry-summary) |
| 1158 | 2026-07-22 | [fmp] [W4][Indexes] Stock Market Indexes List (index-list) |
| 1159 | 2026-07-22 | [fmp] [W2][Indexes] Index Quote (quote) |
| 1160 | 2026-07-22 | [fmp] [W2][Indexes] Index Short Quote (quote-short) |
| 1161 | 2026-07-22 | [fmp] [W2][Indexes] All Index Quotes (batch-index-quotes) |
| 1162 | 2026-07-22 | [fmp] [W3][Indexes] Historical Index Light Chart (historical-price-eod/light) |
| 1163 | 2026-07-22 | [fmp] [W3][Indexes] Historical Index Full Chart (historical-price-eod/full) |
| 1164 | 2026-07-22 | [fmp] [W3][Indexes] 1-Minute Interval Index Price (historical-chart/1min) |
| 1165 | 2026-07-22 | [fmp] [W3][Indexes] 5-Minute Interval Index Price (historical-chart/5min) |
| 1166 | 2026-07-22 | [fmp] [W3][Indexes] 1-Hour Interval Index Price (historical-chart/1hour) |
| 1167 | 2026-07-22 | [fmp] [W4][Indexes] S&P 500 Index (sp500-constituent) |
| 1168 | 2026-07-22 | [fmp] [W4][Indexes] Nasdaq Index (nasdaq-constituent) |
| 1169 | 2026-07-22 | [fmp] [W4][Indexes] Dow Jones (dowjones-constituent) |
| 1170 | 2026-07-22 | [fmp] [W4][Indexes] Historical S&P 500 (historical-sp500-constituent) |
| 1171 | 2026-07-22 | [fmp] [W4][Indexes] Historical Nasdaq (historical-nasdaq-constituent) |
| 1172 | 2026-07-22 | [fmp] [W4][Indexes] Historical Dow Jones (historical-dowjones-constituent) |
| 1173 | 2026-07-22 | [fmp] [W4][Commodity] Commodities List (commodities-list) |
| 1174 | 2026-07-22 | [fmp] [W2][Commodity] Commodities Quote (quote) |
| 1175 | 2026-07-22 | [fmp] [W2][Commodity] Commodities Quote Short (quote-short) |
| 1176 | 2026-07-22 | [fmp] [W2][Commodity] All Commodities Quotes (batch-commodity-quotes) |
| 1177 | 2026-07-22 | [fmp] [W3][Commodity] Light Chart (historical-price-eod/light) |
| 1178 | 2026-07-22 | [fmp] [W3][Commodity] Full Chart (historical-price-eod/full) |
| 1179 | 2026-07-22 | [fmp] [W3][Commodity] 1-Minute Interval Commodities Chart (historical-chart/1min) |
| 1180 | 2026-07-22 | [fmp] [W3][Commodity] 5-Minute Interval Commodities Chart (historical-chart/5min) |
| 1181 | 2026-07-22 | [fmp] [W3][Commodity] 1-Hour Interval Commodities Chart (historical-chart/1hour) |
| 1182 | 2026-07-22 | [fmp] [W4][Crypto] Cryptocurrency List (cryptocurrency-list) |
| 1183 | 2026-07-22 | [fmp] [W2][Crypto] Full Cryptocurrency Quote (quote) |
| 1184 | 2026-07-22 | [fmp] [W2][Crypto] Cryptocurrency Quote Short (quote-short) |
| 1185 | 2026-07-22 | [fmp] [W2][Crypto] All Cryptocurrencies Quotes (batch-crypto-quotes) |
| 1186 | 2026-07-22 | [fmp] [W3][Crypto] Historical Cryptocurrency Light Chart (historical-price-eod/light) |
| 1187 | 2026-07-22 | [fmp] [W3][Crypto] Historical Cryptocurrency Full Chart (historical-price-eod/full) |
| 1188 | 2026-07-22 | [fmp] [W3][Crypto] 1-Minute Interval Cryptocurrency Data (historical-chart/1min) |
| 1189 | 2026-07-22 | [fmp] [W3][Crypto] 5-Minute Interval Cryptocurrency Data (historical-chart/5min) |
| 1190 | 2026-07-22 | [fmp] [W3][Crypto] 1-Hour Interval Cryptocurrency Data (historical-chart/1hour) |
| 1191 | 2026-07-22 | [fmp] [W6][Fundraisers] Latest Crowdfunding Campaigns (crowdfunding-offerings-latest) |
| 1192 | 2026-07-22 | [fmp] [W6][Fundraisers] Crowdfunding Campaign Search (crowdfunding-offerings-search) |
| 1193 | 2026-07-22 | [fmp] [W6][Fundraisers] Crowdfunding By CIK (crowdfunding-offerings) |
| 1194 | 2026-07-22 | [fmp] [W6][Fundraisers] Equity Offering Updates (fundraising-latest) |
| 1195 | 2026-07-22 | [fmp] [W6][Fundraisers] Equity Offering Search (fundraising-search) |
| 1196 | 2026-07-22 | [fmp] [W6][Fundraisers] Equity Offering By CIK (fundraising) |
| 1197 | 2026-07-22 | [fmp] [W4][Forex] Forex Currency Pairs (forex-list) |
| 1198 | 2026-07-22 | [fmp] [W2][Forex] Forex Quote (quote) |
| 1199 | 2026-07-22 | [fmp] [W2][Forex] Forex Short Quote (quote-short) |
| 1200 | 2026-07-22 | [fmp] [W2][Forex] Batch Forex Quotes (batch-forex-quotes) |
| 1201 | 2026-07-22 | [fmp] [W3][Forex] Historical Forex Light Chart (historical-price-eod/light) |
| 1202 | 2026-07-22 | [fmp] [W3][Forex] Historical Forex Full Chart (historical-price-eod/full) |
| 1203 | 2026-07-22 | [fmp] [W3][Forex] 1-Minute Interval Forex Chart (historical-chart/1min) |
| 1204 | 2026-07-22 | [fmp] [W3][Forex] 5-Minute Interval Forex Chart (historical-chart/5min) |
| 1205 | 2026-07-22 | [fmp] [W3][Forex] 1-Hour Interval Forex Chart (historical-chart/1hour) |
| 1206 | 2026-07-22 | [fmp] [W5][InsiderTrades] Latest Insider Trading (insider-trading/latest) |
| 1207 | 2026-07-22 | [fmp] [W5][InsiderTrades] Search Insider Trades (insider-trading/search) |
| 1208 | 2026-07-22 | [fmp] [W5][InsiderTrades] Search Insider Trades by Reporting Name (insider-trading/reporting-name) |
| 1209 | 2026-07-22 | [fmp] [W5][InsiderTrades] All Insider Transaction Types (insider-trading-transaction-type) |
| 1210 | 2026-07-22 | [fmp] [W5][InsiderTrades] Insider Trade Statistics (insider-trading/statistics) |
| 1211 | 2026-07-22 | [fmp] [W5][InsiderTrades] Acquisition Ownership (acquisition-of-beneficial-ownership) |
| 1212 | 2026-07-22 | [fmp] [W7][MarketPerformance] Market Sector Performance Snapshot (sector-performance-snapshot) |
| 1213 | 2026-07-22 | [fmp] [W7][MarketPerformance] Industry Performance Snapshot (industry-performance-snapshot) |
| 1214 | 2026-07-22 | [fmp] [W7][MarketPerformance] Historical Market Sector Performance (historical-sector-performance) |
| 1215 | 2026-07-22 | [fmp] [W7][MarketPerformance] Historical Industry Performance (historical-industry-performance) |
| 1216 | 2026-07-22 | [fmp] [W7][MarketPerformance] Sector Pe Snapshot (sector-pe-snapshot) |
| 1217 | 2026-07-22 | [fmp] [W7][MarketPerformance] Industry Pe Snapshot (industry-pe-snapshot) |
| 1218 | 2026-07-22 | [fmp] [W7][MarketPerformance] Historical Sector PE (historical-sector-pe) |
| 1219 | 2026-07-22 | [fmp] [W7][MarketPerformance] Historical Industry PE (historical-industry-pe) |
| 1220 | 2026-07-22 | [fmp] [W7][MarketPerformance] Biggest Stock Gainers (biggest-gainers) |
| 1221 | 2026-07-22 | [fmp] [W7][MarketPerformance] Biggest Stock Losers (biggest-losers) |
| 1222 | 2026-07-22 | [fmp] [W7][MarketPerformance] Top Traded Stocks (most-actives) |
| 1223 | 2026-07-22 | [fmp] [W2][MarketHours] Global Exchange Market Hours (exchange-market-hours) |
| 1224 | 2026-07-22 | [fmp] [W4][MarketHours] Holidays By Exchange (holidays-by-exchange) |
| 1225 | 2026-07-22 | [fmp] [W2][MarketHours] All Exchange Market Hours (all-exchange-market-hours) |
| 1226 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Simple Moving Average (technical-indicators/sma) |
| 1227 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Exponential Moving Average (technical-indicators/ema) |
| 1228 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Weighted Moving Average (technical-indicators/wma) |
| 1229 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Double Exponential Moving Average (technical-indicators/dema) |
| 1230 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Triple Exponential Moving Average (technical-indicators/tema) |
| 1231 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Relative Strength Index (technical-indicators/rsi) |
| 1232 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Standard Deviation (technical-indicators/standarddeviation) |
| 1233 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Williams (technical-indicators/williams) |
| 1234 | 2026-07-22 | [fmp] [W3][TechnicalIndicators] Average Directional Index (technical-indicators/adx) |
| 1235 | 2026-07-22 | [fmp] [W6][News] FMP Articles (fmp-articles) |
| 1236 | 2026-07-22 | [fmp] [W6][News] General News (news/general-latest) |
| 1237 | 2026-07-22 | [fmp] [W6][News] Press Releases (news/press-releases-latest) |
| 1238 | 2026-07-22 | [fmp] [W6][News] Stock News (news/stock-latest) |
| 1239 | 2026-07-22 | [fmp] [W6][News] Crypto News (news/crypto-latest) |
| 1240 | 2026-07-22 | [fmp] [W6][News] Forex News (news/forex-latest) |
| 1241 | 2026-07-22 | [fmp] [W6][News] Search Press Releases (news/press-releases) |
| 1242 | 2026-07-22 | [fmp] [W6][News] Search Stock News (news/stock) |
| 1243 | 2026-07-22 | [fmp] [W6][News] Search Crypto News (news/crypto) |
| 1244 | 2026-07-22 | [fmp] [W6][News] Search Forex News (news/forex) |
| 1245 | 2026-07-22 | [fmp] [W2][Quote] Stock Quote (quote) |
| 1246 | 2026-07-22 | [fmp] [W2][Quote] Stock Quote Short (quote-short) |
| 1247 | 2026-07-22 | [fmp] [W2][Quote] Aftermarket Trade (aftermarket-trade) |
| 1248 | 2026-07-22 | [fmp] [W2][Quote] Aftermarket Quote (aftermarket-quote) |
| 1249 | 2026-07-22 | [fmp] [W2][Quote] Stock Price Change (stock-price-change) |
| 1250 | 2026-07-22 | [fmp] [W2][Quote] Stock Batch Quote (batch-quote) |
| 1251 | 2026-07-22 | [fmp] [W2][Quote] Stock Batch Quote Short (batch-quote-short) |
| 1252 | 2026-07-22 | [fmp] [W2][Quote] Batch Aftermarket Trade (batch-aftermarket-trade) |
| 1253 | 2026-07-22 | [fmp] [W2][Quote] Batch Aftermarket Quote (batch-aftermarket-quote) |
| 1254 | 2026-07-22 | [fmp] [W2][Quote] Exchange Stock Quotes (batch-exchange-quote) |
| 1255 | 2026-07-22 | [fmp] [W2][Quote] Mutual Fund Price Quotes (batch-mutualfund-quotes) |
| 1256 | 2026-07-22 | [fmp] [W2][Quote] ETF Price Quotes (batch-etf-quotes) |
| 1257 | 2026-07-22 | [fmp] [W2][Quote] Full Commodities Quotes (batch-commodity-quotes) |
| 1258 | 2026-07-22 | [fmp] [W2][Quote] Full Cryptocurrency Quotes (batch-crypto-quotes) |
| 1259 | 2026-07-22 | [fmp] [W2][Quote] Full Forex Quote (batch-forex-quotes) |
| 1260 | 2026-07-22 | [fmp] [W2][Quote] Full Index Quotes (batch-index-quotes) |
| 1261 | 2026-07-22 | [fmp] [W5][SecFilings] Latest 8-K SEC Filings (sec-filings-8k) |
| 1262 | 2026-07-22 | [fmp] [W5][SecFilings] Latest SEC Filings (sec-filings-financials) |
| 1263 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings By Form Type (sec-filings-search/form-type) |
| 1264 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings By Symbol (sec-filings-search/symbol) |
| 1265 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings By CIK (sec-filings-search/cik) |
| 1266 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings By Name (sec-filings-company-search/name) |
| 1267 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings Company Search By Symbol (sec-filings-company-search/symbol) |
| 1268 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Filings Company Search By CIK (sec-filings-company-search/cik) |
| 1269 | 2026-07-22 | [fmp] [W5][SecFilings] SEC Company Full Profile (sec-profile) |
| 1270 | 2026-07-22 | [fmp] [W5][SecFilings] Industry Classification List (standard-industrial-classification-list) |
| 1271 | 2026-07-22 | [fmp] [W5][SecFilings] Industry Classification Search (industry-classification-search) |
| 1272 | 2026-07-22 | [fmp] [W5][SecFilings] All Industry Classification (all-industry-classification) |
| 1273 | 2026-07-22 | [fmp] [W6][EarningsTranscript] Latest Earning Transcripts (earning-call-transcript-latest) |
| 1274 | 2026-07-22 | [fmp] [W6][EarningsTranscript] Earnings Transcript (earning-call-transcript) |
| 1275 | 2026-07-22 | [fmp] [W6][EarningsTranscript] Transcripts Dates By Symbol (earning-call-transcript-dates) |
| 1276 | 2026-07-22 | [fmp] [W6][EarningsTranscript] Available Transcript Symbols (earnings-transcript-list) |
| 1277 | 2026-07-22 | [fmp] [W5][Senate] Latest Senate Financial Disclosures (senate-latest) |
| 1278 | 2026-07-22 | [fmp] [W5][Senate] Latest House Financial Disclosures (house-latest) |
| 1279 | 2026-07-22 | [fmp] [W5][Senate] Senate Trading Activity (senate-trades) |
| 1280 | 2026-07-22 | [fmp] [W5][Senate] Senate Trades By Name (senate-trades-by-name) |
| 1281 | 2026-07-22 | [fmp] [W5][Senate] Senate Trades By ID (senate-trades-by-id) |
| 1282 | 2026-07-22 | [fmp] [W5][Senate] U.S. House Trades (house-trades) |
| 1283 | 2026-07-22 | [fmp] [W5][Senate] House Trades By Name (house-trades-by-name) |
| 1284 | 2026-07-22 | [fmp] [W5][Senate] House Trades By ID (house-trades-by-id) |
| 1285 | 2026-07-22 | [fmp] [W5][Senate] Senate Profiles (senate-profile) |
| 1286 | 2026-07-22 | [fmp] [W5][Senate] Senate Positions (senate-positions) |
| 1287 | 2026-07-22 | [fmp] [W5][Senate] Senate Net Worth (senate-net-worth) |
| 1288 | 2026-07-22 | [fmp] [W5][Senate] Senate Net Worth Aggregated (senate-net-worth-aggregated) |
| 1289 | 2026-07-22 | [fmp] [W8][Bulk] Company Profile Bulk (profile-bulk) |
| 1290 | 2026-07-22 | [fmp] [W8][Bulk] Stock Rating Bulk (rating-bulk) |
| 1291 | 2026-07-22 | [fmp] [W8][Bulk] DCF Valuations Bulk (dcf-bulk) |
| 1292 | 2026-07-22 | [fmp] [W8][Bulk] Financial Scores Bulk (scores-bulk) |
| 1293 | 2026-07-22 | [fmp] [W8][Bulk] Price Target Summary Bulk (price-target-summary-bulk) |
| 1294 | 2026-07-22 | [fmp] [W8][Bulk] ETF Holder Bulk (etf-holder-bulk) |
| 1295 | 2026-07-22 | [fmp] [W8][Bulk] Upgrades Downgrades Consensus Bulk (upgrades-downgrades-consensus-bulk) |
| 1296 | 2026-07-22 | [fmp] [W8][Bulk] Key Metrics TTM Bulk (key-metrics-ttm-bulk) |
| 1297 | 2026-07-22 | [fmp] [W8][Bulk] Ratios TTM Bulk (ratios-ttm-bulk) |
| 1298 | 2026-07-22 | [fmp] [W8][Bulk] Stock Peers Bulk (peers-bulk) |
| 1299 | 2026-07-22 | [fmp] [W8][Bulk] Earnings Surprises Bulk (earnings-surprises-bulk) |
| 1300 | 2026-07-22 | [fmp] [W8][Bulk] Income Statement Bulk (income-statement-bulk) |
| 1301 | 2026-07-22 | [fmp] [W8][Bulk] Income Statement Growth Bulk (income-statement-growth-bulk) |
| 1302 | 2026-07-22 | [fmp] [W8][Bulk] Balance Sheet Statement Bulk (balance-sheet-statement-bulk) |
| 1303 | 2026-07-22 | [fmp] [W8][Bulk] Balance Sheet Statement Growth Bulk (balance-sheet-statement-growth-bulk) |
| 1304 | 2026-07-22 | [fmp] [W8][Bulk] Cash Flow Statement Bulk (cash-flow-statement-bulk) |
| 1305 | 2026-07-22 | [fmp] [W8][Bulk] Cash Flow Statement Growth Bulk (cash-flow-statement-growth-bulk) |
| 1306 | 2026-07-22 | [fmp] [W8][Bulk] Eod Bulk (eod-bulk) |
| 1307 | 2026-07-22 | [fmp] [W8][Partners] Analyst Ratings Search (tipranks-search) |
| 1308 | 2026-07-22 | [fmp] [W8][Partners] Point in time Ratings by Symbol (tipranks-pit-symbol) |
| 1309 | 2026-07-22 | [fmp] [W8][Partners] Point in time Ratings by Analyst (tipranks-pit-analyst) |
| 1310 | 2026-07-22 | [fmp] [W8][Partners] Ratings Summary by Symbol (tipranks-symbol-summary) |
| 1311 | 2026-07-22 | [fmp] [W8][Partners] Ratings Summary by Analyst (tipranks-analyst-summary) |
| 1312 | 2026-07-22 | [fmp] [W8][Partners] Ratings Summary by Firm (tipranks-firm-summary) |
| 1313 | 2026-07-22 | [fmp] [W8][Partners] Analyst Directory Lookup (tipranks-analysts) |
| 1314 | 2026-07-22 | [fmp] W0.A1 — Extend coverage-gate to audit both providers |
| 1315 | 2026-07-22 | [fmp] W0.A2 — Endpoint playbook doc using AnalystRecommendations as canonical example |
| 1316 | 2026-07-22 | [fmp] W0.A3 — _PLAN_LIMITED allowlist seeded from #955 findings |
| 1317 | 2026-07-22 | [fmp] W0.A4 — schema_version table + record_migration helper |
| 1345 | 2026-07-22 | [scrape-record] EPIC: record/replay/correct framework for offline provider snapshots |
| 1346 | 2026-07-22 | [scrape-record] PR 1: framework skeleton + first Yahoo options recording |
| 1347 | 2026-07-22 | [scrape-record] PR 2: YFinanceRecordedOptionsChainsFetcher (#999) |
| 1348 | 2026-07-22 | [scrape-record] PR 3: Bond-ladder proxy via ETF holdings (#1000) |
| 1352 | 2026-07-25 | [docs] Portfolio Intelligence Engine — User Guide Notebook Series (epic) |
| 1353 | 2026-07-23 | [docs] NB Series Phase 0 — Story bible: persona, arc, cross-link map |
| 1354 | 2026-07-23 | [docs] NB Series Phase A / NB01 — Narrative skeleton: Getting Started + Providers |
| 1355 | 2026-07-23 | [docs] NB Series Phase A / NB02 — Narrative skeleton: Single-Name Deep Dive |
| 1356 | 2026-07-23 | [docs] NB Series Phase A / NB03 — Narrative skeleton: Basket X-Ray + Risk |
| 1357 | 2026-07-23 | [docs] NB Series Phase A / NB04 — Narrative skeleton: Events + Smart Money |
| 1358 | 2026-07-23 | [docs] NB Series Phase A / NB05 — Narrative skeleton: What-If + Attribution + Paper |
| 1359 | 2026-07-23 | [docs] NB Series Phase A / NB06 — Narrative skeleton: Backtest + Validation |
| 1360 | 2026-07-23 | [docs] NB Series Phase A / NB07 — Narrative skeleton: Offline Recording + End-to-End |
| 1361 | 2026-07-23 | [docs] NB Series Phase A / Index — README.md for notebooks/portfolio/ |
| 1362 | 2026-07-23 | [docs] NB Series Phase A gate — Full-series narrative review before any code lands |
| 1363 | 2026-07-25 | [docs] NB Series Phase B / NB01 — Code fulfillment: Getting Started + Providers |
| 1364 | 2026-07-25 | [docs] NB Series Phase B / NB02 — Code fulfillment: Single-Name Deep Dive |
| 1365 | 2026-07-25 | [docs] NB Series Phase B / NB03 — Code fulfillment: Basket X-Ray + Risk |
| 1366 | 2026-07-25 | [docs] NB Series Phase B / NB04 — Code fulfillment: Events + Smart Money |
| 1367 | 2026-07-25 | [docs] NB Series Phase B / NB05 — Code fulfillment: What-If + Attribution + Paper |
| 1368 | 2026-07-25 | [docs] NB Series Phase B / NB06 — Code fulfillment: Backtest + Validation |
| 1369 | 2026-07-25 | [docs] NB Series Phase B / NB07 — Code fulfillment: Offline Recording + End-to-End |
| 1370 | 2026-07-25 | [docs] NB Series Phase B gate — CI smoke + end-to-end product review |
| 1373 | 2026-07-25 | [docs] NB Series Phase B blocked — yfinance live endpoints returning 401 Invalid Crumb |
| 1374 | 2026-07-25 | [docs/infra] Extend scrape_record for 3 core yfinance endpoints — universe-wide snapshot coverage (sub-epic) |
| 1375 | 2026-07-24 | [docs/infra] Sub-epic 1374 / PR-1 — Framework fetchers + extractors + unit tests (no live recording) |
| 1376 | 2026-07-24 | [docs/infra] Sub-epic 1374 / PR-2 — Recording scripts (Playwright capture logic, no snapshots) |
| 1377 | 2026-07-24 | [docs/infra] Sub-epic 1374 / PR-3 — Sweep script + universe list (operator-run by Daisy) |
| 1378 | 2026-07-25 | [docs/infra] Sub-epic 1374 / PR-4 — Ingest snapshots + register fetchers + round-trip tests |
| 1379 | 2026-07-24 | [docs/infra] Sub-epic 1374 / PR-5 — Nightly drift-check CI + doc updates + close blocker |
| 1384 | 2026-07-25 | [docs/infra] Migrate 3 recorded yfinance fetchers to layered fast+fallback (sub-epic) |
| 1385 | 2026-07-25 | [docs/infra] Sub-epic 1384 / PR-A — Rewrite 3 recordings with layered fast+fallback + regenerate fixtures + update extractors |
| 1386 | 2026-07-25 | [docs/infra] Sub-epic 1384 / PR-B — Ingest snapshots + close blocker (operator-run sweep + ingest) |
| 1389 | 2026-07-29 | [bug] HistoricalDividends fmp_cached: rejects datetime.date start_date |
| 1390 | 2026-07-29 | [bug] InstitutionalOwnership fmp_cached: pydantic float_type validation on null percent fields |
| 1400 | 2026-07-25 | [docs] NB04: complete smart-money rollup section + land Act-4 promised reveal (STORY_BIBLE 3.3) |
| 1401 | 2026-07-25 | [docs] NB05: wire STORY_BIBLE fallback fixture when smart_money.rollup is empty |
| 1402 | 2026-07-25 | [docs] NB07: execute end-to-end offline run + measure wall-clock to back the '45-min plane' claim |
| 1403 | 2026-07-25 | [docs] NB03: fixture-lock the 38%->55% Tech look-through numbers per Rule 10 |
| 1404 | 2026-07-25 | [docs] NB04: add 'What is NOT in this notebook' closer for parity |
| 1405 | 2026-07-25 | [docs] NB02/NB06: convert defensive try/except around tearsheet/bundle to loud-empty warnings per Testing Rule 3 |
| 1409 | 2026-07-25 | [docs] Portfolio NB Series — Teaching-depth enhancement (Phase C epic) |
| 1410 | 2026-07-25 | [docs] NB01 teaching depth — providers/quote/OHLCV/ETF primer + 10+ Investopedia links |
| 1411 | 2026-07-25 | [docs] NB02 teaching depth — fundamental analysis/DCF/EV/ATR/regime + 15+ Investopedia links |
| 1412 | 2026-07-25 | [docs] NB03 teaching depth — diversification/HHI/Sharpe/MaxDD/look-through + 12+ links |
| 1413 | 2026-07-25 | [docs] NB04 teaching depth — earnings calendar/13F/insider/STOCK Act + 10+ links |
| 1414 | 2026-07-25 | [docs] NB05 teaching depth — Brinson/allocation vs selection/paper-trading + 12+ links |
| 1415 | 2026-07-25 | [docs] NB06 teaching depth — walk-forward/PBO/Deflated Sharpe/factor investing + 15+ links |
| 1416 | 2026-07-25 | [docs] NB07 teaching depth — reproducibility + review cadence + 8+ links |
| 1425 | 2026-07-26 | Store offline provider snapshots in a user-local DB, not committed JSON (avoid redistributing Yahoo-shaped data) |
| 1426 | 2026-07-26 | Migrate portfolio notebooks' ETF/bond look-through from Yahoo snapshots to SEC N-PORT (sec provider) |
| 1428 | 2026-07-26 | [Epic] Authoritative data-source migration for portfolio notebooks (fmp -> cboe -> sec; yfinance last resort) + free-only portfolio_yfinance track |
| 1429 | 2026-07-26 | [NB01][Track A] Getting Started + Providers: adopt authoritative provider chain, demote yfinance |
| 1430 | 2026-07-26 | [NB02][Track A] Single-Name Deep-Dive: adopt authoritative provider chain, demote yfinance |
| 1431 | 2026-07-26 | [NB03][Track A] Basket X-Ray & Risk (the pivot): adopt authoritative provider chain, demote yfinance |
| 1432 | 2026-07-26 | [NB04][Track A] Events & Smart Money: adopt authoritative provider chain, demote yfinance |
| 1433 | 2026-07-26 | [NB05][Track A] What-If, Attribution & Paper: adopt authoritative provider chain, demote yfinance |
| 1434 | 2026-07-26 | [NB06][Track A] Backtest & Validation: adopt authoritative provider chain, demote yfinance |
| 1435 | 2026-07-26 | [NB07][Track A] Offline Recording & End-to-End: adopt authoritative provider chain, demote yfinance |
| 1436 | 2026-07-26 | [NB08][Track A] Analyst Recommendations - Basket: adopt authoritative provider chain, demote yfinance |
| 1437 | 2026-07-26 | [NB01][Track B] Free-only equivalent in portfolio_yfinance/: Getting Started + Providers |
| 1438 | 2026-07-26 | [NB02][Track B] Free-only equivalent in portfolio_yfinance/: Single-Name Deep-Dive |
| 1439 | 2026-07-26 | [NB03][Track B] Free-only equivalent in portfolio_yfinance/: Basket X-Ray & Risk (the pivot) |
| 1440 | 2026-07-26 | [NB04][Track B] Free-only equivalent in portfolio_yfinance/: Events & Smart Money |
| 1441 | 2026-07-26 | [NB05][Track B] Free-only equivalent in portfolio_yfinance/: What-If, Attribution & Paper |
| 1442 | 2026-07-26 | [NB06][Track B] Free-only equivalent in portfolio_yfinance/: Backtest & Validation |
| 1443 | 2026-07-26 | [NB07][Track B] Free-only equivalent in portfolio_yfinance/: Offline Recording & End-to-End |
| 1444 | 2026-07-26 | [NB08][Track B] Free-only equivalent in portfolio_yfinance/: Analyst Recommendations - Basket |
| 1459 | 2026-07-29 | [bug] obb.etf.holdings(fmp_cached) returns empty for QQQ while direct SEC N-PORT returns 102 rows (NB01 §3) |
| 1460 | 2026-07-29 | [bug] NB01 §6 bridge-preview cell prints real portfolio positions + usernames into notebook output (PII leak on commit) |
| 1461 | 2026-07-29 | [docs] Convert bare #NNN issue refs in notebooks/portfolio/* to full GitHub URLs (100 refs, 19 files) |
| 1463 | 2026-07-29 | Phase 4 valuation quality overlays (Altman, Piotroski, ROIC-WACC, PEG) return NaN — Phase 2 does not fetch source endpoints |
| 1464 | 2026-07-29 | Phase 4 summary renders gate_notes one character per line (str iterated as sequence) |
| 1465 | 2026-07-29 | Reverse-DCF implied_growth returns NaN for extreme overvaluation (brentq bracket) |
| 1466 | 2026-07-29 | [bug] FMP institutional_ownership returns 0 rows for MSFT when derived percent fields are null |
| 1467 | 2026-07-29 | [fmp] SearchSymbol fetcher |
| 1468 | 2026-07-29 | [fmp] SearchName fetcher |
| 1469 | 2026-07-29 | [fmp] SearchCik fetcher |
| 1470 | 2026-07-29 | [fmp] SearchCusip fetcher |
| 1471 | 2026-07-29 | [fmp] SearchIsin fetcher |
| 1472 | 2026-07-29 | [fmp] SearchExchangeVariants fetcher |
| 1473 | 2026-07-29 | [fmp] CikList fetcher |
| 1474 | 2026-07-29 | [fmp] ProfileCik fetcher |
| 1475 | 2026-07-29 | [fmp] SymbolChange fetcher |
| 1476 | 2026-07-29 | [fmp] FinancialStatementSymbolList fetcher |
| 1477 | 2026-07-29 | [fmp] AvailableCountries fetcher |
| 1478 | 2026-07-29 | [fmp] AvailableExchanges fetcher |
| 1479 | 2026-07-29 | [fmp] AvailableIndustries fetcher |
| 1480 | 2026-07-29 | [fmp] AvailableSectors fetcher |
| 1481 | 2026-07-29 | [fmp] AnalystRecommendations fetcher |
| 1482 | 2026-07-29 | [fmp] Grades fetcher |
| 1483 | 2026-07-29 | [fmp] GradesConsensus fetcher |
| 1484 | 2026-07-29 | [fmp] GradesHistorical fetcher |
| 1485 | 2026-07-29 | [fmp] PriceTargetSummary fetcher |
| 1486 | 2026-07-29 | [fmp] RatingsHistorical fetcher |
| 1487 | 2026-07-29 | [fmp] RatingsSnapshot fetcher |
| 1488 | 2026-07-29 | [fmp] EnterpriseValues fetcher |
| 1489 | 2026-07-29 | [fmp] FinancialGrowth fetcher |
| 1490 | 2026-07-29 | [fmp] FinancialScores fetcher |
| 1491 | 2026-07-29 | [fmp] KeyMetricsTtm fetcher |
| 1492 | 2026-07-29 | [fmp] OwnerEarnings fetcher |
| 1493 | 2026-07-29 | [fmp] RatiosTtm fetcher |
| 1494 | 2026-07-29 | [fmp] IncomeStatementAsReported fetcher |
| 1495 | 2026-07-29 | [fmp] BalanceSheetStatementAsReported fetcher |
| 1496 | 2026-07-29 | [fmp] CashFlowStatementAsReported fetcher |
| 1497 | 2026-07-29 | [fmp] FinancialStatementFullAsReported fetcher |
| 1498 | 2026-07-29 | [fmp] FinancialReportsDates fetcher |
| 1499 | 2026-07-29 | [fmp] FinancialReportsJson fetcher |
| 1500 | 2026-07-30 | [fmp] CompanyNotes fetcher |
| 1501 | 2026-07-30 | [fmp] DelistedCompanies fetcher |
| 1502 | 2026-07-30 | [fmp] SharesFloat fetcher |
| 1503 | 2026-07-30 | [fmp] SharesFloatAll fetcher |
| 1504 | 2026-07-30 | [fmp] AcquisitionOfBeneficialOwnership fetcher |
| 1505 | 2026-07-30 | [fmp] ExecutiveCompensationBenchmark fetcher |
| 1506 | 2026-07-29 | [fmp] BatchQuote fetcher |
| 1507 | 2026-07-29 | [fmp] BatchQuoteShort fetcher |
| 1508 | 2026-07-29 | [fmp] BatchAftermarketQuote fetcher |
| 1509 | 2026-07-29 | [fmp] BatchAftermarketTrade fetcher |
| 1510 | 2026-07-29 | [fmp] StockQuote fetcher |
| 1511 | 2026-07-29 | [fmp] StockQuoteShort fetcher |
| 1512 | 2026-07-29 | [fmp] StockPriceChange fetcher |
| 1513 | 2026-07-29 | [fmp] MarketCap fetcher |
| 1514 | 2026-07-29 | [fmp] MarketCapBatch fetcher |
| 1515 | 2026-07-29 | [fmp] DowjonesConstituent fetcher |
| 1516 | 2026-07-29 | [fmp] HistoricalDowjonesConstituent fetcher |
| 1517 | 2026-07-29 | [fmp] Sp500Constituent fetcher |
| 1518 | 2026-07-29 | [fmp] HistoricalSp500Constituent fetcher |
| 1519 | 2026-07-29 | [fmp] NasdaqConstituent fetcher |
| 1520 | 2026-07-29 | [fmp] HistoricalNasdaqConstituent fetcher |
| 1521 | 2026-07-29 | [fmp] SectorPerformanceSnapshot fetcher |
| 1522 | 2026-07-29 | [fmp] HistoricalSectorPerformance fetcher |
| 1523 | 2026-07-29 | [fmp] SectorPeSnapshot fetcher |
| 1524 | 2026-07-29 | [fmp] HistoricalSectorPe fetcher |
| 1525 | 2026-07-29 | [fmp] IndustryPerformanceSnapshot fetcher |
| 1526 | 2026-07-29 | [fmp] HistoricalIndustryPerformance fetcher |
| 1527 | 2026-07-29 | [fmp] IndustryPeSnapshot fetcher |
| 1528 | 2026-07-29 | [fmp] HistoricalIndustryPe fetcher |
| 1529 | 2026-07-29 | [fmp] EconomicIndicators fetcher |
| 1530 | 2026-07-29 | [fmp] MarketRiskPremium fetcher |
| 1531 | 2026-07-29 | [fmp] CommitmentOfTradersAnalysis fetcher |
| 1532 | 2026-07-29 | [fmp] CommitmentOfTradersList fetcher |
| 1533 | 2026-07-29 | [fmp] CommitmentOfTradersReport fetcher |
| 1534 | 2026-07-29 | [fmp] Fundraising fetcher |
| 1535 | 2026-07-29 | [fmp] FundraisingLatest fetcher |
| 1536 | 2026-07-29 | [fmp] FundraisingSearch fetcher |
| 1537 | 2026-07-29 | [fmp] CrowdfundingOfferings fetcher |
| 1538 | 2026-07-29 | [fmp] CrowdfundingOfferingsLatest fetcher |
| 1539 | 2026-07-29 | [fmp] CrowdfundingOfferingsSearch fetcher |
| 1540 | 2026-07-29 | [fmp] MergersAcquisitionsLatest fetcher |
| 1541 | 2026-07-29 | [fmp] MergersAcquisitionsSearch fetcher |
| 1542 | 2026-07-29 | [fmp] IposDisclosure fetcher |
| 1543 | 2026-07-29 | [fmp] IposProspectus fetcher |
| 1544 | 2026-07-29 | [fmp] NewsCrypto fetcher |
| 1545 | 2026-07-29 | [fmp] NewsCryptoLatest fetcher |
| 1546 | 2026-07-29 | [fmp] NewsForex fetcher |
| 1547 | 2026-07-29 | [fmp] NewsForexLatest fetcher |
| 1548 | 2026-07-29 | [fmp] FmpArticles fetcher |
| 1549 | 2026-07-29 | [fmp] SecFilings8K fetcher |
| 1550 | 2026-07-29 | [fmp] SecProfile fetcher |
| 1551 | 2026-07-29 | [fmp] StandardIndustrialClassificationList fetcher |
| 1552 | 2026-07-29 | [fmp] AllIndustryClassification fetcher |
| 1553 | 2026-07-29 | [fmp] IndustryClassificationSearch fetcher |
| 1554 | 2026-07-29 | [fmp] HouseLatest fetcher |
| 1555 | 2026-07-29 | [fmp] SenateLatest fetcher |
| 1556 | 2026-07-29 | [fmp] SenateNetWorth fetcher |
| 1557 | 2026-07-29 | [fmp] SenateNetWorthAggregated fetcher |
| 1558 | 2026-07-29 | [fmp] SenatePositions fetcher |
| 1559 | 2026-07-29 | [fmp] SenateProfile fetcher |
| 1560 | 2026-07-29 | [fmp] DiscountedCashFlow fetcher |
| 1561 | 2026-07-29 | [fmp] LeveredDiscountedCashFlow fetcher |
| 1562 | 2026-07-29 | [fmp] CustomDiscountedCashFlow fetcher |
| 1563 | 2026-07-29 | [fmp] CustomLeveredDiscountedCashFlow fetcher |
| 1564 | 2026-07-29 | [fmp] StockList fetcher |
| 1565 | 2026-07-29 | [fmp] EtfList fetcher |
| 1566 | 2026-07-29 | [fmp] IndexList fetcher |
| 1567 | 2026-07-29 | [fmp] CommoditiesList fetcher |
| 1568 | 2026-07-29 | [fmp] ForexList fetcher |
| 1569 | 2026-07-29 | [fmp] CryptocurrencyList fetcher |
| 1570 | 2026-07-29 | [fmp] ActivelyTradingList fetcher |
| 1571 | 2026-07-29 | [fmp] AllExchangeMarketHours fetcher |
| 1572 | 2026-07-29 | [fmp] HolidaysByExchange fetcher |
| 1573 | 2026-07-30 | [fmp][E2E] Search & Directory endpoints - integration suite |
| 1574 | 2026-07-30 | [fmp][E2E] Analyst, Ratings & Grades - integration suite |
| 1575 | 2026-07-30 | [fmp][E2E] Statements extras (TTM / AsReported / Analysis / Growth / Reports) - integration suite |
| 1576 | 2026-07-30 | [fmp][E2E] Company, Ownership, Float & Compensation - integration suite |
| 1577 | 2026-07-30 | [fmp][E2E] Quotes, Market Cap & Batch - integration suite |
| 1578 | 2026-07-30 | [fmp][E2E] Index & Sector/Industry Performance - integration suite |
| 1579 | 2026-07-30 | [fmp][E2E] Economics, COT & Risk - integration suite |
| 1580 | 2026-07-30 | [fmp][E2E] Fundraising, M&A & Crowdfunding - integration suite |
| 1581 | 2026-07-30 | [fmp][E2E] News & Articles - integration suite |
| 1582 | 2026-07-30 | [fmp][E2E] SEC Filings & Classification - integration suite |
| 1583 | 2026-07-30 | [fmp][E2E] Government / Senate / House Trades - integration suite |
| 1584 | 2026-07-30 | [fmp][E2E] DCF & Valuation - integration suite |
| 1585 | 2026-07-30 | [fmp][E2E] Reference Symbol Lists - integration suite |
| 1586 | 2026-07-30 | [fmp][E2E] Market Hours & Exchange Reference - integration suite |
| 1587 | 2026-07-30 | [fmp][integration] Register all new fetchers in openbb_fmp/__init__.py |
| 1588 | 2026-07-30 | [fmp][integration] openbb.build() static-package rebuild + provider Literal parity |
| 1589 | 2026-07-30 | [fmp][integration] Provider-map parity test (fmp vs fmp_cached vs docs) |
| 1590 | 2026-07-30 | [fmp][integration] Credential + status-appropriate error-type parity |
| 1591 | 2026-07-30 | [fmp][E2E] Full-provider smoke across all new fetchers |
| 1592 | 2026-07-29 | [fmp][Feature] Search & Directory endpoints |
| 1593 | 2026-07-29 | [fmp][Feature] Analyst, Ratings & Grades |
| 1594 | 2026-07-29 | [fmp][Feature] Statements extras (TTM / AsReported / Analysis / Growth / Reports) |
| 1595 | 2026-07-30 | [fmp][Feature] Company, Ownership, Float & Compensation |
| 1596 | 2026-07-29 | [fmp][Feature] Quotes, Market Cap & Batch |
| 1597 | 2026-07-29 | [fmp][Feature] Index & Sector/Industry Performance |
| 1598 | 2026-07-29 | [fmp][Feature] Economics, COT & Risk |
| 1599 | 2026-07-29 | [fmp][Feature] Fundraising, M&A & Crowdfunding |
| 1600 | 2026-07-29 | [fmp][Feature] News & Articles |
| 1601 | 2026-07-29 | [fmp][Feature] SEC Filings & Classification |
| 1602 | 2026-07-29 | [fmp][Feature] Government / Senate / House Trades |
| 1603 | 2026-07-29 | [fmp][Feature] DCF & Valuation |
| 1604 | 2026-07-29 | [fmp][Feature] Reference Symbol Lists |
| 1605 | 2026-07-29 | [fmp][Feature] Market Hours & Exchange Reference |
| 1606 | 2026-07-29 | [fmp][Feature] Provider Integration & Registration (cross-cutting) |
| 1607 | 2026-07-30 | [fmp][Epic] Full documented-endpoint parity for the fmp provider |
| 1626 | 2026-07-30 | notebooks(nb03): portfolio construction - target bands + concentration caps + coverage guard |
| 1628 | 2026-07-30 | chore(tools): reconcile top-level Tools/ and openbb_platform/tools/ into single canonical tree |
| 1629 | 2026-07-30 | Reconcile or delete portfolio_app/ — standardize on the recent importer+notebook path (Project #4) |
| 1632 | 2026-07-30 | fix(widget-backend): widget/app titles show mojibake (`â€"`) — JSON responses lack charset=utf-8 |
| 1633 | 2026-07-30 | fix(widget-backend): X-Ray sector/country pie widgets render empty in Workspace |
| 1634 | 2026-07-31 | EPIC: Portfolio Intelligence Terminal (Sandbox clone + persona surface) |
| 1635 | 2026-07-31 | F0: App shell, contexts & shared chrome |
| 1636 | 2026-07-31 | T0.1: Define eleven-tab app entry in apps.json (symbol + book contexts) |
| 1637 | 2026-07-30 | T0.2: Fix #1632 (charset) and #1633 (chart pie/label mapping) as clone prerequisites |
| 1638 | 2026-07-31 | T0.3: Symbol context bar widget (ticker param, allowlisted, shared by tabs 1-7) |
| 1639 | 2026-07-31 | T0.4: Book context bar widget (account_id param, shared by tabs 8-11) |
| 1640 | 2026-07-31 | T0.5: Default-layout + default-params pass for all eleven tabs |
| 1641 | 2026-07-31 | T0.6: Playwright layout smoke test (each tab renders N widgets, 0 blank) |
| 1642 | 2026-08-02 | F1: Overview tab (analyst) |
| 1643 | 2026-07-31 | T1.1: EXTEND pi_equity_profile_header -> Ticker Information (price/day-change row) |
| 1644 | 2026-07-31 | T1.2: REUSE pi_equity_profile_header -> Ticker Profile placement |
| 1645 | 2026-07-31 | T1.3: BUILD Price Performance widget (price + shares-outstanding) |
| 1646 | 2026-07-31 | T1.4: REUSE pi_equity_key_stats -> Key Metrics placement |
| 1647 | 2026-07-31 | T1.5: EXTEND Share Statistics (float, short interest, insider %) |
| 1648 | 2026-07-31 | T1.6: BUILD Management Team widget (FMP key-executives) |
| 1649 | 2026-07-31 | T1.7: BUILD Revenue Per Geography widget (FMP revenue-geographic-segmentation) |
| 1650 | 2026-07-31 | T1.8: BUILD Revenue Per Business Line widget (FMP revenue-product-segmentation) |
| 1651 | 2026-07-31 | T1.9: EXTEND Valuation Multiples (trailing + forward P/E, EV/EBITDA, P/S) |
| 1652 | 2026-07-31 | F2: Financials tab (analyst) |
| 1653 | 2026-07-31 | T2.1: BUILD Financial Statements table (income/balance/cash-flow, period toggle) |
| 1654 | 2026-07-31 | F3: Technical Analysis tab (trader/analyst) |
| 1655 | 2026-07-31 | T3.1: EXTEND pi_equity_technicals -> Charting (OHLC + indicator overlays, window enum) |
| 1656 | 2026-07-31 | F4: Comparison Analysis tab (analyst) |
| 1657 | 2026-07-31 | T4.1: EXTEND pi_equity_competitors -> peer multiples matrix table |
| 1658 | 2026-07-31 | F5: Ownership tab (analyst/PM) |
| 1659 | 2026-07-31 | T5.1: BUILD Institutional Ownership (13F holders table) |
| 1660 | 2026-07-31 | T5.2: BUILD Stock Ownership breakdown (pie/table) |
| 1661 | 2026-07-31 | T5.3: BUILD Insider Trading table (FMP insider-trading) |
| 1662 | 2026-07-31 | F6: Company Calendar tab (analyst/trader) |
| 1663 | 2026-07-31 | T6.1: BUILD Earnings History (EPS actual vs. estimate) |
| 1664 | 2026-07-31 | T6.2: BUILD Stock Splits table |
| 1665 | 2026-07-31 | T6.3: BUILD Dividend Payment table |
| 1666 | 2026-07-31 | T6.4: BUILD Company Filings table (FMP sec_filings) |
| 1667 | 2026-07-31 | T6.5: BUILD Earnings Transcripts (FMP earning_call_transcript) |
| 1668 | 2026-07-31 | F7: Estimates tab (analyst) |
| 1669 | 2026-07-31 | T7.1: EXTEND pi_equity_analyst_forecasts -> Price Target vs. close time series |
| 1670 | 2026-07-31 | F8: Portfolio X-Ray tab (PM) - composition only |
| 1671 | 2026-07-31 | T8.1: Lay out pi_xray_sector, pi_xray_country, pi_lookthrough_top25, pi_concentration_gauge |
| 1672 | 2026-07-31 | F9: Risk & Attribution tab (PM) - composition only |
| 1673 | 2026-07-31 | T9.1: Lay out pi_risk_dashboard, pi_risk_vol_chart, pi_brinson_attribution, pi_whatif_card, pi_whatif_diff |
| 1674 | 2026-07-31 | F10: Paper Trading Desk tab (trader) - composition only |
| 1675 | 2026-07-31 | T10.1: Lay out pi_paper_ticket, pi_paper_blotter, pi_paper_performance, pi_paper_perf_kpis, pi_backtest_button |
| 1676 | 2026-07-31 | F11: Alerts & Catalysts tab (trader) - composition only |
| 1677 | 2026-07-31 | T11.1: Lay out pi_event_calendar, pi_smart_money_ribbon, pi_news_ribbon, pi_sentiment_gauge, pi_alerts_panel |
| 1678 | 2026-07-31 | [F12] Portfolio-management workflow flow (notebook-aligned W0-W9) (#1634) |
| 1679 | 2026-07-30 | chore(notebooks): move 6 root-level techtrade notebooks into notebooks/techtrade/ |
| 1680 | 2026-07-30 | [T12.1] BUILD provider-health strip widget (W0) (#1678) |
| 1681 | 2026-07-30 | [T12.2] BUILD Morning Review composed one-pager layout (W8) (#1678) |
| 1682 | 2026-07-30 | [T12.3] EXTEND pi_equity_analyst_forecasts to basket/consensus mode (W9) (#1678) |
| 1683 | 2026-07-30 | [T12.4] Add Portfolio Sunday Routine guided-tour manifest to apps.json (W0-W9) (#1678) |
| 1684 | 2026-07-30 | [T12.5] Playwright flow smoke test for the W0-W9 tour (#1678) |
| 1685 | 2026-07-31 | [T12.1] BUILD provider-health strip widget (W0) (#1678) |
| 1686 | 2026-07-31 | [T12.2] BUILD Morning Review composed one-pager layout (W8) (#1678) |
| 1687 | 2026-07-31 | [T12.3] EXTEND pi_equity_analyst_forecasts to basket/consensus mode (W9) (#1678) |
| 1688 | 2026-07-31 | [T12.4] Add Portfolio Sunday Routine guided-tour manifest to apps.json (W0-W9) (#1678) |
| 1689 | 2026-07-31 | [T12.5] Playwright flow smoke test for the W0-W9 tour (#1678) |
| 1691 | 2026-08-02 | F13: Techtrade Trading-Desk surface (systematic-trader) — PRD §6B |
| 1692 | 2026-07-31 | T13.1: BUILD Morning Scan tab (T1) — tt_segment_movers, tt_scan_table, tt_export_button |
| 1693 | 2026-07-30 | T13.2: BUILD Position Workbench deep-dive (T2) — tt_signal_card, tt_plan_card, tt_order_legs, tt_simulate_result |
| 1694 | 2026-07-30 | T13.3: BUILD tt_validation_verdict (T3) — PBO/DSR/OOS Sharpe + verdict badge |
| 1695 | 2026-07-30 | T13.4: BUILD tt_tuning_report (T4) — tuneta proposal + validate-gate + persist |
| 1696 | 2026-08-02 | T13.2: BUILD Position Workbench deep-dive (T2) — tt_signal_card, tt_plan_card, tt_order_legs, tt_simulate_result |
| 1697 | 2026-08-02 | T13.3: BUILD tt_validation_verdict (T3) — PBO/DSR/OOS Sharpe + verdict badge |
| 1698 | 2026-08-02 | T13.4: BUILD tt_tuning_report (T4) — tuneta proposal + validate-gate + persist |
| 1699 | 2026-08-02 | T13.5: BUILD tt_audit_journal (T6) — replay vs forward bars, journal + deviation log |
| 1700 | 2026-08-02 | T13.6: BUILD tt_engine_status + Trading Desk tab-group layout (tabs 12-14) + T5 execute bridge |
| 1701 | 2026-08-02 | T13.7: Playwright cadence smoke test — step T1->T6, verdict gates execute bridge |
| 1702 | 2026-07-30 | feat(widgets): add candlestick chart type + line↔candle toggle across pi price widgets |
| 1713 | 2026-08-02 | [portfolio-intel] Real Playwright + Workspace-in-CI (T0.6 / T12.5 gap) |
| 1714 | 2026-08-02 | [portfolio-intel] Basket-mode input design: basket_id + positions.db integration |
| 1715 | 2026-08-02 | [portfolio-intel] Real 5-tier chain fallback in provider-health strip |
| 1716 | 2026-08-02 | [portfolio-intel] Pre-existing test_p3_routes failure: news_timeline severity=info returns 0 items |
| 1719 | 2026-09-12 | [techtrade] Real T5 execute bridge: paper/live broker adapter |
| 1721 | 2026-08-02 | EPIC: Browser Test Harness — dual-mode (manual + Playwright) for terminal apps |
| 1722 | 2026-08-02 | [browser-harness] B0: Package scaffold + Story data model + Driver Protocol |
| 1723 | 2026-08-02 | [browser-harness] B1: Standalone HTTP driver (subprocess-safe, port-safe, auth-safe) |
| 1724 | 2026-08-02 | [browser-harness] B2: Portfolio story (16 steps, W0-W9 mapped to NB01-NB08) |
| 1725 | 2026-08-02 | [browser-harness] B3: Techtrade story (12 steps, T1-T6 mapped to NB01-NB06) |
| 1726 | 2026-08-02 | [browser-harness] B4: Fixture capture + staleness enforcement |
| 1727 | 2026-08-02 | [browser-harness] B5: Manual guide generator with per-step screenshots |
| 1728 | 2026-08-02 | [browser-harness] B6: Playwright workspace driver (persistent-context + CDP attach) |
| 1729 | 2026-08-02 | [browser-harness] B7: CI integration + close-out of #1713 |
| 1733 | 2026-08-02 | [browser-harness] B8: Widget-completeness sweep — cover all 59 widgets |
| 1734 | 2026-08-02 | [browser-harness] B9: Deep invariant sweep — loud-empty + XSS rejection + enum params |
| 1735 | 2026-08-02 | [browser-harness] B10: Workspace selector graph — real UI-render assertions |
| 1744 | 2026-08-02 | [portfolio-intel] Use existing MySQL as canonical positions store - stop drift to a separate SQLite positions.db |
| 1750 | 2026-08-03 | [techtrade] T5 OrderSink P1 — closes-syntax tracker (#1719) |
| 1751 | 2026-08-03 | [techtrade] T5 OrderSink P2 — closes-syntax tracker (#1719) |
| 1753 | 2026-09-06 | [portfolio-intel] ingest.py: accept BOTH old + current Fidelity positions CSV header sets |
| 1754 | 2026-08-03 | [techtrade] T5 P3.a paper engine — closes-syntax tracker (#1719) |
| 1756 | 2026-08-03 | [techtrade] T5 E2E test guide + Fidelity CSV schema doc — closes-syntax tracker (#1719) |
| 1758 | 2026-08-03 | [techtrade] Notebook: T5 execute-with-paper-trading walkthrough (#1719) |
| 1759 | 2026-08-03 | [techtrade] NB-07: T5 OrderBatch + XLSX workbook walkthrough (#1719) |
| 1760 | 2026-08-03 | [techtrade] NB-08: T5 paper trading engine walkthrough (#1719) |
| 1761 | 2026-08-03 | [techtrade] NB-09: T5 end-to-end plan → XLSX → fills flow (#1719) |
| 1762 | 2026-09-06 | [techtrade] Add test_notebooks_techtrade_smoke.py mirroring the portfolio version |
| 1766 | 2026-09-06 | [techtrade] T5 P3.b: unrealized P&L via ChainedFetcher live prices (#1719) |
| 1767 | 2026-09-06 | [techtrade] T5 P3.c: reconciliation vs. Fidelity positions snapshot (#1719) |
| 1768 | 2026-09-06 | [techtrade] T5 P4: tt_execute_bridge widget rewrite with write-batch button (#1719) |
| 1769 | 2026-09-06 | [techtrade] T5 P5: Activity CSV parser for bulk-import of fills (#1719) |
| 1770 | 2026-08-03 | [techtrade] T5 P3.b closes-syntax tracker (#1719) |
| 1772 | 2026-08-03 | [techtrade] T5 P3.c closes-syntax tracker (#1719) |
| 1774 | 2026-08-03 | [techtrade] T5 P5 closes-syntax tracker (#1719) |
| 1776 | 2026-08-03 | [techtrade] T5 P4 backend endpoints — closes-syntax tracker (#1719) |
| 1777 | 2026-09-12 | [techtrade] T5 P4b: Frontend widget rewrite for tt_execute_bridge (#1719) |
| 1780 | 2026-08-03 | [techtrade] #1762 closes-syntax tracker |
| 1782 | 2026-08-03 | [techtrade] #1753 closes-syntax tracker |
| 1784 | 2026-08-03 | [techtrade] #1777 closes-syntax tracker |
| 1786 | 2026-08-03 | Portfolio Overview app — Stock Analysis widgets fail to load (ERR_CONNECTION_REFUSED against https://127.0.0.1:6902; portfolio backend has no run script/certs) |
| 1788 | 2026-08-03 | portfolio backend crashes at app.openapi() -- OBBject not fully defined under pydantic 2.13.4 (blocks widget render) |
| 1789 | 2026-08-05 | [browser-harness] Playwright workspace-mode harness with random-port isolation |
| 1790 | 2026-09-06 | [techtrade] T5 P3.a paper engine: SQLite -> MySQL (canonical store parity) |
| 1792 | 2026-08-03 | [techtrade] T5 P3.a MySQL migration — closes-syntax tracker (#1790) |
| 1794 | 2026-08-03 | [portfolio] Custom-copilot backend fronting the 4141 Copilot proxy for OpenBB Workspace |
| 1796 | 2026-08-03 | [portfolio-intel] Default stock_analysis tab symbol to MSFT (was CLS) |
| 1798 | 2026-08-03 | [portfolio] Local Workspace Viewer — offline dashboard + copilot chat pane |
| 1799 | 2026-08-03 | [portfolio] Local viewer step 1: backend route + HTML shell + launch.py mount |
| 1800 | 2026-08-03 | [portfolio] Local viewer step 2: render apps.json tabs + widgets.json tables + params |
| 1801 | 2026-08-03 | [portfolio] Local viewer step 3: chat pane wired to copilot /query SSE |
| 1804 | 2026-08-04 | [docs] VS Code Trading Terminal Extension PRD (openbb-terminal-vscode) |
| 1805 | 2026-08-04 | [portfolio] Self-hosted dashboard: extend Local Workspace Viewer to the portfolio_intel (6120) apps + chart/markdown/metric renderers |
| 1806 | 2026-08-05 | [EPIC] VS Code Trading Terminal Extension (openbb-terminal-vscode) |
| 1807 | 2026-08-04 | [Feature] VSCode Terminal Phase 0 — Backend contract + rendering-model decision |
| 1808 | 2026-08-04 | [docs] ADR: canonical backend spawn + readiness endpoint for VS Code terminal |
| 1809 | 2026-08-04 | [spike] CORS + token webview auth against widget backend |
| 1810 | 2026-08-04 | [docs] ADR: Path A widgets.json renderer vs Path B bespoke React components |
| 1811 | 2026-08-04 | [docs] Widget-registry drift guard — Appendix A generator + verification |
| 1812 | 2026-08-04 | [Feature] VSCode Terminal Phase 1 — Extension scaffold + webview shell + widget canvas |
| 1813 | 2026-08-04 | [vscode-terminal] Scaffold apps/vscode-terminal-extension/ package + activation |
| 1814 | 2026-08-04 | [vscode-terminal] Webview host: loads shared canvas bundle + postMessage bridge |
| 1815 | 2026-08-04 | [vscode-terminal] VS Code theme token bridge (dark theme first) |
| 1816 | 2026-08-04 | [vscode-terminal] Ship two fixture-mode layouts (Portfolio Overview + Equity Deep-Dive) |
| 1817 | 2026-08-04 | [vscode-terminal] CSP: allow style-src 'unsafe-inline' for chart libraries |
| 1818 | 2026-08-04 | [Feature] VSCode Terminal Phase 2 — Live data + backend lifecycle + all 5 layouts |
| 1819 | 2026-08-04 | [vscode-terminal] Backend lifecycle: spawn + health poll + status-bar |
| 1820 | 2026-08-04 | [vscode-terminal] Live-data mode: switch fixture → real fetches with token injection |
| 1821 | 2026-08-04 | [vscode-terminal] Ship all five built-in layouts (Portfolio Risk, Trading Desk, Chart Focus) |
| 1822 | 2026-08-04 | [vscode-terminal] Command Palette + default keybindings (full §12.1 surface) |
| 1823 | 2026-08-04 | [vscode-terminal] Symbol context v1 — widget selector broadcasts to all panels |
| 1824 | 2026-08-04 | [Feature] VSCode Terminal Phase 3 — Editor integration (hover, notebook, selection) |
| 1825 | 2026-08-04 | [vscode-terminal] Symbol hover provider (Python + Notebook) with tightened regex |
| 1826 | 2026-08-04 | [vscode-terminal] Notebook variable watcher — source-text heuristic (not runtime kernel) |
| 1827 | 2026-08-04 | [vscode-terminal] Editor selection → symbol context |
| 1828 | 2026-08-04 | [vscode-terminal] openbb.runAnalysis command opens 7-phase Analysis notebook |
| 1829 | 2026-08-05 | [Feature] VSCode Terminal Phase 4 — Widget parity + layout management (tent-pole) |
| 1830 | 2026-08-04 | [vscode-terminal] Widget Browser tree-view (drag-to-layout, prefix grouping) |
| 1831 | 2026-08-05 | [vscode-terminal] User-defined layouts: create / rename / duplicate / delete |
| 1832 | 2026-08-04 | [vscode-terminal] openbb.previewWidget command (reuse existing preview route) |
| 1833 | 2026-08-04 | [vscode-terminal] Ship 3–5 golden layouts to the repo (versioned + shareable) |
| 1834 | 2026-08-05 | [Feature] VSCode Terminal Phase 5 — Paper trading hotkeys + polish + NFR gate |
| 1835 | 2026-08-04 | [vscode-terminal] Paper buy/sell keybindings for active symbol |
| 1836 | 2026-08-05 | [vscode-terminal] openbb.setApiKey guided quick-pick over user_settings.json |
| 1837 | 2026-08-05 | [vscode-terminal] High-contrast + light theme parity for widgets and charts |
| 1838 | 2026-08-05 | [vscode-terminal] Auto-start + auto-restart backend (configurable) |
| 1839 | 2026-08-05 | [vscode-terminal] Performance gate: hit all §17.1 NFR targets |
| 1840 | 2026-08-05 | [vscode-terminal] Testing strategy: webview snapshots + extension test runner + fixture harness |
| 1856 | 2026-08-05 | [vscode-terminal] Workspace-trust hardening — validate pythonPath + apiBaseUrl + machine scope |
| 1871 | 2026-09-12 | provider_health strip always 'unknown' under async server (asyncio.run in event loop; _probe_track coroutine leak) |
| 1872 | 2026-09-12 | provider-health strip always 'unknown' — no production code registers probers (_PROBER_REGISTRY empty) |
| 1881 | 2026-09-12 | [portfolio-intel] Local viewer chat 404s: copilot router not mounted on portfolio_intel 6130 backend |
| 1885 | 2026-09-12 | [portfolio-intel] Local viewer: candle mode collapses OHLC+volume onto one shared y-axis (no candlestick renderer) |
| 1886 | 2026-09-12 | [portfolio-intel] Local viewer: params with inline options render as free-text input, not a dropdown |
| 1887 | 2026-09-12 | [portfolio-intel] Local viewer: y-axis numeric labels clip past the chart left edge |
| 1888 | 2026-09-12 | [portfolio-intel] Local viewer: mixed-unit multi-series line charts crush small-scale series (revenue_b vs net_margin_pct) |
| 1890 | 2026-09-12 | [self-hosted-openbb] Local Workspace Viewer: move app-switcher combo into a collapsible left sidebar |
| 1891 | 2026-09-12 | [self-hosted-openbb] Viewer: independent per-widget scroll containers |
| 1892 | 2026-09-12 | [self-hosted-openbb] Viewer: resizable widget windows (grid-snapped, persisted) |
| 1893 | 2026-09-12 | [self-hosted-openbb] Viewer: floating draggable grid layout to rearrange widgets |
| 1896 | 2026-08-05 | [docs] VS Code Terminal Extension — user guide + refreshed README (v0.0.33) |
| 1898 | 2026-09-06 | [portfolio-intel] Fully wire pi_equity_price_history to fmp_cached (full-wiring of #1702) |
| 1900 | 2026-08-10 | [portfolio-intel] Fully wire pi_price_performance to fmp_cached (full-wiring of #1645) |
| 1902 | 2026-08-10 | [portfolio-intel] Fully wire pi_management_team to fmp_cached (full-wiring of #1648) |
| 1904 | 2026-08-10 | [portfolio-intel] Fully wire pi_revenue_geography to fmp_cached (full-wiring of #1649) |
| 1906 | 2026-08-10 | [portfolio-intel] Fully wire pi_revenue_business_line to fmp_cached (full-wiring of #1650) |
| 1908 | 2026-08-10 | [portfolio-intel] Fully wire pi_dividend_payment to fmp_cached (full-wiring of #1665) |
| 1910 | 2026-08-10 | [portfolio-intel] Fully wire pi_insider_trading to fmp_cached (full-wiring of #1661) |
| 1912 | 2026-08-10 | [portfolio-intel] Fully wire pi_earnings_history to fmp_cached (full-wiring of #1663) |
| 1914 | 2026-08-10 | [portfolio-intel] Fully wire pi_company_filings to fmp_cached (full-wiring of #1666) |
| 1916 | 2026-08-10 | [portfolio-intel] Fully wire pi_stock_splits to fmp_cached (full-wiring of #1664) |
| 1918 | 2026-08-10 | [portfolio-intel] Fully wire equity charting/technicals widget to fmp_cached (full-wiring of #1655) |
| 1920 | 2026-08-10 | [portfolio-intel] Fully wire equity financials/statements widget to fmp_cached (full-wiring of #1653) |
| 1923 | 2026-08-10 | [portfolio-intel] Fully wire equity peer-multiples/competitors widget to fmp_cached (full-wiring of #1657) |
| 1926 | 2026-08-10 | [portfolio-intel] Fully wire price-target-history to fmp_cached (full-wiring of #1669) |
| 1931 | 2026-08-10 | [portfolio-intel] Fully wire tt_engine_status to observable openbb_techtrade state (full-wiring of #1700) |
| 1934 | 2026-09-12 | [portfolio-intel] FRS: Async scan + ScanSnapshotStore persistence layer (unblocks tt_* data widgets) |
| 1935 | 2026-08-10 | [portfolio-intel] Bug: pi_company_filings stub/test shape drift vs live fmp_cached tier (#1914) |
| 1936 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase A1 — DDL + schema (tt_scan_snapshot table) |
| 1937 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase A2 — Protocol + Mysql/Sqlite impls + factory + migration CLI |
| 1938 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase A3 — recorded fixtures + realistic-shape tests for 3 scan_kinds |
| 1939 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase B1 — scan_runner CLI (run_scan + `python -m` entry) |
| 1940 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase B2 — POST /tt/scan/trigger endpoint (2 modes: dev-sync + prod-detached) |
| 1941 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase C — wire tt_movers + tt_scan + tt_scan_export widgets (batch, closes #1692) |
| 1942 | 2026-10-02 | [techtrade] ScanSnapshotStore Phase C — wire tt_signals + tt_plan + tt_orders + tt_simulate widgets (batch, closes #1696) |
| 1943 | 2026-10-02 | [techtrade] ScanSnapshotStore Phase C — wire tt_validate widget (closes #1697) |
| 1944 | 2026-10-02 | [techtrade] ScanSnapshotStore Phase C — wire tt_tune widget (closes #1698) |
| 1945 | 2026-10-02 | [techtrade] ScanSnapshotStore Phase C — wire tt_audit widget (closes #1699) |
| 1946 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase D — retention worker + snapshot pruning verification |
| 1947 | 2026-09-07 | [techtrade] ScanSnapshotStore Phase D — cron / Task Scheduler cadence docs + example config |
| 1948 | 2026-09-12 | [portfolio-intel] VS Code-style hide/show toggles for BOTH viewer side panels (Copilot hidden by default) |
| 1949 | 2026-09-12 | [portfolio-intel] Wire viewer time-series charts to TradingView Lightweight Charts (+ SVG x-axis dates) |
| 1950 | 2026-08-10 | [portfolio-intel] pi_equity_price_history: add time-range control + trend-realistic series |
| 1951 | 2026-08-10 | [portfolio-intel] Add '?' help affordance to Local Viewer widgets (how-to-read popover) |
| 1952 | 2026-08-10 | [portfolio-intel] Demo price-history: volume bars near-flat + uniform candles (not meaningful) |
| 1953 | 2026-08-07 | [portfolio-intel] Surface live-vs-demo data provenance on widgets (X-PI-Data-Source badge) |
| 1954 | 2026-08-08 | [portfolio-intel] Terminal: single shared Symbol context drives all 11 tabs (not per-widget) |
| 1955 | 2026-08-08 | [portfolio-intel] F2 Financials serves stub — wire equity/financials to live fmp_cached income |
| 1956 | 2026-08-09 | [portfolio-intel] Provider Health strip never populates — probe budget too tight (always cold-cache) |
| 1957 | 2026-08-09 | [portfolio-intel] Backend serves stub for all live-wired widgets on cold boot — warm openbb at startup |
| 1958 | 2026-08-09 | [portfolio-intel] Wire equity/header + equity/key-stats to live fmp_cached (F2 last stubs) |
| 1959 | 2026-09-12 | [portfolio-intel] area:fmp-cached-gap — key-stats fields with no fmp_cached source (forward P/E, short interest, insider ownership, shares float) |
| 1960 | 2026-08-09 | [portfolio-intel] Provider Health strip: cboe shows unknown_error in one track, healthy in other (misclassified timeout + double-probe) |
| 1961 | 2026-08-09 | [portfolio-intel] Provider Health strip: render Track A only (drop Track B row) for test-verification clarity |
| 1962 | 2026-08-09 | F2 widgets serve stub on fresh backend: cold-boot warmup build fails on worker thread (signal only works in main thread) |
| 1963 | 2026-09-07 | [portfolio-intel] EOD snapshot store skeleton — SnapshotStore Protocol + MySQL/SQLite impl + staging→validate→promote + keep-last-good |
| 1964 | 2026-09-12 | [portfolio-intel] LIVE-view reconciliation & provenance columns — live_pointer, engine_version, payload_schema_version, snapshot_job_error |
| 1965 | 2026-09-12 | [portfolio-intel] PII boundary for account-scoped snapshot datasets — outside-repo guard; never persist holdings in shared store |
| 1966 | 2026-09-12 | [portfolio-intel] EOD snapshot semantics — session-date as_of, session-granularity staleness badge, EOD-not-intraday disclaimer |
| 1967 | 2026-09-12 | [portfolio-intel] EOD snapshot job orchestration — post-close scheduled process + single-flight + snapshot_job bookkeeping + targeted retry |
| 1968 | 2026-10-02 | [portfolio-intel] Phase 2 — techtrade movers EOD snapshot (unblocks #1692): job → store; tt_segment_movers read-only + validation gate + keep-last-good |
| 1969 | 2026-10-02 | [portfolio-intel] Phase 3 fan-out — scan/signals/plan/validate/tune/audit EOD snapshots; event-risk invalidation; survivorship gate |
| 1971 | 2026-08-10 | [portfolio-intel] Phase A1 — declare openbb-techtrade dep in portfolio_intel/pyproject.toml (path/develop, no version pin) |
| 1972 | 2026-09-12 | [portfolio-intel] Phase A2 — centralize PI_* config in openbb_techtrade/config.py (typed getters) |
| 1973 | 2026-09-12 | [portfolio-intel] Follow-up from #1971: pip install -e portfolio_intel clobbers editable techtrade install |
| 1975 | 2026-10-26 | [portfolio-intel] auto-close-on-merge workflow doesn't parse Closes clauses from PR body (only from commit trailers) |
| 1976 | 2026-09-05 | [portfolio-intel] F2 Financials redesign: provider-health table + data-provenance strip + full fundamentals layout |
| 1978 | 2026-09-05 | [portfolio-intel] F2 financial-statement chart: 3 series on one axis — needs dual-axis combo (bars + line) |
| 1980 | 2026-09-05 | [portfolio-intel] Integrate Bug Context feedback widget into Local Workspace Viewer |
| 1982 | 2026-09-05 | [portfolio-intel] F2 financial chart: recolor combo + fix 'Value is null' from LWC datetime/dup-day (BugContext) |
| 1984 | 2026-09-05 | feat(portfolio): add F2 metric glossary help |
| 1986 | 2026-09-06 | feat(backtest): test top-50 S&P intraday drift theory |
| 1987 | 2026-09-05 | feat(portfolio): audit Terminal financial terminology and help |
| 1988 | 2026-09-12 | feat(portfolio): pi_equity_key_stats — complete key-stats glossary coverage |
| 1989 | 2026-09-12 | feat(portfolio): pi_financial_statements — label financial statement periods and terms |
| 1990 | 2026-09-12 | feat(portfolio): pi_peer_multiples — label peer valuation multiples |
| 1991 | 2026-09-06 | feat(portfolio): pi_earnings_history — label earnings history measures |
| 1992 | 2026-09-12 | feat(portfolio): pi_price_target_history — label price target chart series |
| 1993 | 2026-09-12 | feat(portfolio): pi_equity_technicals — clarify pivot and implied volatility terms |
| 1994 | 2026-09-12 | feat(portfolio): pi_equity_competitors — label competitor performance columns |
| 1995 | 2026-09-12 | feat(portfolio): pi_equity_complementary — label complementary asset fields |
| 1996 | 2026-09-06 | feat(portfolio): pi_equity_analyst_forecasts — standardize analyst forecast terminology |
| 1997 | 2026-09-12 | feat(portfolio): pi_basket_analyst_consensus — label basket analyst consensus columns |
| 1998 | 2026-09-06 | feat(portfolio): pi_lookthrough_top25 — label look-through holding weights |
| 1999 | 2026-09-12 | feat(portfolio): pi_concentration_gauge — clarify HHI concentration metric |
| 2000 | 2026-09-06 | feat(portfolio): pi_risk_dashboard — label portfolio risk metrics |
| 2001 | 2026-09-06 | feat(portfolio): pi_risk_vol_chart — label rolling volatility horizons |
| 2002 | 2026-09-06 | feat(portfolio): pi_brinson_attribution — explain Brinson attribution effects |
| 2003 | 2026-09-12 | feat(portfolio): pi_whatif_card — label what-if portfolio impact metrics |
| 2004 | 2026-09-12 | feat(portfolio): pi_paper_perf_kpis — label paper performance KPIs |
| 2005 | 2026-09-12 | feat(portfolio): pi_paper_performance — label paper portfolio equity series |
| 2006 | 2026-09-12 | feat(portfolio): pi_paper_blotter — label paper blotter execution fields |
| 2007 | 2026-09-12 | feat(portfolio): pi_smart_money_ribbon — label smart-money activity fields |
| 2008 | 2026-09-12 | feat(portfolio): extend glossary help to table headers and metric cards |
| 2009 | 2026-09-12 | feat(portfolio): pi_dividend_payment — label dividend fields |
| 2010 | 2026-09-06 | feat(portfolio): pi_equity_key_stats — label key-stat table headers |
| 2011 | 2026-09-06 | feat(portfolio): pi_equity_technicals — label technical indicator table headers |
| 2012 | 2026-09-06 | feat(portfolio): pi_event_calendar — label calendar fields and event types |
| 2013 | 2026-09-06 | feat(portfolio): pi_equity_analyst_forecasts — label analyst forecast table headers |
| 2014 | 2026-09-12 | feat(portfolio): pi_whatif_card — label what-if comparison headers |
| 2015 | 2026-09-12 | feat(portfolio): pi_alerts_panel — label alert fields and categories |
| 2016 | 2026-09-12 | feat(portfolio): pi_news_ribbon — label held-symbol news fields |
| 2017 | 2026-09-12 | feat(portfolio): pi_sentiment_gauge — clarify news sentiment score |
| 2019 | 2026-09-05 | fix(portfolio): use F2 pie-chart space effectively |
| 2021 | 2026-09-05 | chore(core): refresh generated API reference |
| 2022 | 2026-09-05 | docs(workflow): enforce portfolio validation integration gate |
| 2023 | 2026-09-05 | test(validation): absorb known-noise harness fixes |
| 2025 | 2026-09-06 | fix(vscode-terminal): normalize snapshot line endings |
| 2027 | 2026-09-12 | test(portfolio): make live SPY concentration assertion data-resilient |
| 2028 | 2026-09-06 | chore(pine): verify and retire merged feature branches |
| 2029 | 2026-09-06 | chore(ci): drain local-CI stacked feature branches |
| 2030 | 2026-09-06 | fix(ci): post-merge review corrections for local-CI harness (PR #948) |
| 2033 | 2026-09-06 | docs(workflow): codify validation promotion and branch-hygiene process |
| 2035 | 2026-09-06 | docs(workflow): expand branch-hygiene plan to full remote inventory |
| 2037 | 2026-09-06 | chore(pine): reconcile and retire remaining non-trunk branches |
| 2038 | 2026-09-06 | chore(portfolio): reconcile and retire remaining non-trunk branches |
| 2039 | 2026-09-06 | chore(workflow): audit permanent and quarantined branches |
| 2041 | 2026-09-06 | chore(repo): protect permanent integration branches from deletion |
| 2042 | 2026-09-06 | chore(portfolio): promote validated integration state to portfolio |
| 2045 | 2026-09-06 | fix(portfolio): make stale-claim audit cover all Project #4 items |
| 2046 | 2026-09-07 | [EPIC] OpenBB Portfolio Windows Service Host |
| 2047 | 2026-09-07 | [service-host] Native Windows host configuration and supervision |
| 2048 | 2026-09-07 | [service-host] OpenBB health, logging, and runtime integration |
| 2049 | 2026-09-07 | [service-host] Secure Windows install, update, rollback, and uninstall |
| 2050 | 2026-09-07 | [service-host] Windows acceptance harness and operator runbook |
| 2051 | 2026-09-12 | [portfolio-utils] Database override does not reach fmp_cached provider writes |
| 2052 | 2026-09-07 | [jobs] Durable core service, worker, discovery, and control API |
| 2053 | 2026-09-07 | [jobs] Portfolio history and ETF cache-warmer adapters |
| 2059 | 2026-09-12 | fix(techtrade): align MysqlPaperEngine with shared PyMySQL pool contract |
| 2063 | 2026-09-08 | fix(techtrade): harden snapshot single-LIVE schema verification |
| 2065 | 2026-09-08 | chore: standardize repository agents on GPT-5.6 Sol |
| 2067 | 2026-09-08 | fix(techtrade): close MySQL snapshot guard gaps after PR #2064 |
| 2072 | 2026-09-12 | [portfolio-intel] Align paper engine status widget with typed config |
| 2075 | 2026-09-12 | [portfolio-intel] Clarify source-dependent key-stats fallback contract |
| 2077 | 2026-09-12 | test(portfolio): verify concentration weight normalization |
| 2078 | 2026-09-12 | test(techtrade): restore extended indicator and Ichimoku regressions |
| 2079 | 2026-09-12 | test(techtrade): repair live segment provider model compatibility |
| 2080 | 2026-09-12 | test(techtrade): isolate default snapshot path from user database |
| 2086 | 2026-10-02 | [techtrade] Make snapshot as_of badges exchange-calendar aware |
| 2088 | 2026-09-15 | [devex] Proposal: one-command OpenLLM/Qwen local development environment |
| 2092 | 2026-09-15 | chore(browser-harness): refresh fixture snapshots |
| 2094 | 2026-10-27 | [browser-harness] Live fixture staleness: 12 portfolio-story fixtures drift with market data |
| 2095 | 2026-10-04 | [ci] General Code Linting job fails with exit 127 (linters not installed) |
| 2096 | 2026-10-02 | [EPIC] Local OpenBB Workspace development environment |
| 2097 | 2026-10-02 | [workspace-dev] Pin reference repositories and execution plan |
| 2098 | 2026-10-02 | [workspace-dev] Add idempotent Windows setup preflight |
| 2099 | 2026-10-02 | [workspace-dev] Add Portfolio Intelligence launcher |
| 2100 | 2026-10-02 | [workspace-dev] Add privacy-safe smoke checks and operator runbook |
| 2101 | 2026-10-02 | [workspace-dev] Validate self-hosted Workspace and browser harness |
| 2102 | 2026-10-02 | [workspace-dev] Certify Workspace Bench against self-hosted MCP |
| 2103 | 2026-10-02 | [workspace-dev] Validate Portfolio Copilot in self-hosted Workspace |
| 2108 | 2026-10-02 | [workspace-dev] Pin and audit self-hosted Workspace source |
| 2110 | 2026-10-02 | [workspace-dev] Deploy self-hosted Workspace development stack |
| 2111 | 2026-10-02 | [workspace-dev] Add self-hosted Workspace replay skill and report |
| 2115 | 2026-10-02 | [workspace-dev] Fix empty authenticated self-hosted app shell |
| 2120 | 2026-10-02 | [workspace-dev] Suppress managed admin bootstrap output |
| 2123 | 2026-10-27 | [mcp-parity][PROGRAM] Portfolio capability coverage and trusted MCP delivery |
| 2124 | 2026-10-25 | [mcp-parity][E1] Capability inventory and exposure policy |
| 2125 | 2026-10-27 | [mcp-parity][E2] Reproducible Portfolio runtime profiles |
| 2126 | 2026-10-25 | [mcp-parity][E3] FMP Cached model-to-command parity |
| 2127 | 2026-10-25 | [mcp-parity][E4] Portfolio and Intelligence application parity |
| 2128 | 2026-10-25 | [mcp-parity][E5] Cache observability and controlled operations |
| 2129 | 2026-10-25 | [mcp-parity][E6] Specialist MCP correctness |
| 2130 | 2026-10-25 | [mcp-parity][E7] Truthful prompts, client configuration, and unified discovery |
| 2131 | 2026-10-27 | [mcp-parity][E8] CI, live acceptance, and release rollout |
| 2132 | 2026-10-25 | [mcp-parity][F1.1] Versioned source/API/MCP inventory |
| 2133 | 2026-10-25 | [mcp-parity][F1.2] Reviewed exposure and invocation policy |
| 2134 | 2026-10-25 | [mcp-parity][F1.3] Portfolio lineage and recent-work traceability |
| 2135 | 2026-10-27 | [mcp-parity][F2.1] Deterministic package and profile resolution |
| 2136 | 2026-10-25 | [mcp-parity][F2.2] Profile-aware launcher and readiness |
| 2137 | 2026-10-25 | [mcp-parity][F3.1] Typed provider route framework and complete regression gate |
| 2138 | 2026-10-25 | [mcp-parity][F3.2] Reference, search, price and intraday coverage |
| 2139 | 2026-10-25 | [mcp-parity][F3.3] Analyst, sector and statement coverage |
| 2140 | 2026-10-25 | [mcp-parity][F3.4] Corporate, government, news and COT coverage |
| 2141 | 2026-10-25 | [mcp-parity][F4.1] Reviewed custom Portfolio API adapter |
| 2142 | 2026-10-25 | [mcp-parity][F4.2] Reviewed Intelligence and Trading Desk adapter |
| 2143 | 2026-10-25 | [mcp-parity][F4.3] Analytics optional-package contract |
| 2144 | 2026-10-25 | [mcp-parity][F5.1] Cache observability and truthful persistence |
| 2145 | 2026-10-25 | [mcp-parity][F5.2] Authenticated job-backed maintenance |
| 2146 | 2026-10-25 | [mcp-parity][F6.1] Callable read-only Daytrade MCP |
| 2147 | 2026-10-25 | [mcp-parity][F6.2] Accurate and verified Agents MCP |
| 2148 | 2026-10-25 | [mcp-parity][F7.1] Prompt and skills dependency integrity |
| 2149 | 2026-10-25 | [mcp-parity][F7.2] Unified catalog and client/operator guidance |
| 2150 | 2026-10-25 | [mcp-parity][F8.1] Offline protocol and Portfolio drift gates |
| 2151 | 2026-10-27 | [mcp-parity][F8.2] Live acceptance and staged release |
| 2152 | 2026-10-04 | [mcp-parity][T01] Define capability contracts and immutable audit fixtures |
| 2153 | 2026-10-04 | [mcp-parity][T02] Build the metadata-only inventory CLI |
| 2154 | 2026-10-04 | [mcp-parity][T03] Classify every capability and publish profile policy |
| 2155 | 2026-10-04 | [mcp-parity][T04] Enforce policy at discovery and invocation |
| 2156 | 2026-10-04 | [mcp-parity][T05] Automate Portfolio lineage and baseline comparison |
| 2157 | 2026-10-04 | [mcp-parity][T06] Map recent work and exceptions to accountable capabilities |
| 2158 | 2026-10-04 | [mcp-parity][T07] Define the install/profile manifests |
| 2159 | 2026-10-04 | [mcp-parity][T08] Establish clean-install and import-provenance checks |
| 2160 | 2026-10-04 | [mcp-parity][T09] Add explicit launcher profile selection and safe lifecycle behavior |
| 2161 | 2026-10-04 | [mcp-parity][T10] Make readiness assert the effective capability contract |
| 2162 | 2026-10-04 | [mcp-parity][T11] Introduce typed provider-owned route assembly |
| 2163 | 2026-10-04 | [mcp-parity][T12] Route static directories, lists and references |
| 2164 | 2026-10-04 | [mcp-parity][T13] Route historical reference and identifier search |
| 2165 | 2026-10-04 | [mcp-parity][T14] Route batch quotes, market cap and stock-price extras |
| 2166 | 2026-10-04 | [mcp-parity][T15] Route intraday, aftermarket, hours and single-parameter extras |
| 2167 | 2026-10-04 | [mcp-parity][T16] Route analyst and sector/industry families |
| 2168 | 2026-10-05 | [mcp-parity][T17] Route statement extras, TTM, DCF and as-reported data |
| 2169 | 2026-10-05 | [mcp-parity][T18] Route corporate, SEC and fundraising extras |
| 2170 | 2026-10-05 | [mcp-parity][T19] Route government, news and COT extras |
| 2171 | 2026-10-05 | [mcp-parity][T20] Prove full FMP routing and persistence-descriptor regression |
| 2172 | 2026-10-05 | [mcp-parity][T21] Implement the custom Portfolio composition seam |
| 2173 | 2026-10-05 | [mcp-parity][T22] Verify all 19 Portfolio operations and private-data boundaries |
| 2174 | 2026-10-05 | [mcp-parity][T23] Map Intelligence, provenance, snapshots and Trading Desk effects |
| 2175 | 2026-10-05 | [mcp-parity][T24] Add approved Intelligence adapters and contract parity tests |
| 2176 | 2026-10-05 | [mcp-parity][T25] Lock analytical extension coverage and behavior |
| 2177 | 2026-10-05 | [mcp-parity][T26] Reconcile FinancialToolkit router assembly |
| 2178 | 2026-10-05 | [mcp-parity][T27] Expose sanitized cache health and coverage |
| 2179 | 2026-10-05 | [mcp-parity][T28] Verify persistence semantics and prioritize conversion gaps |
| 2180 | 2026-10-05 | [mcp-parity][T29] Wire operator tools to existing job definitions |
| 2181 | 2026-10-05 | [mcp-parity][T30] Prove maintenance isolation and recovery |
| 2182 | 2026-10-05 | [mcp-parity][T32] Verify Daytrade over an actual stdio connection |
| 2183 | 2026-10-05 | [mcp-parity][T33] Align Agents scope, schemas and documentation |
| 2184 | 2026-10-05 | [mcp-parity][T34] Validate Agents transport and sanitized portfolio access |
| 2185 | 2026-10-05 | [mcp-parity][T35] Add structured prompt dependencies and readiness checks |
| 2186 | 2026-10-05 | [mcp-parity][T36] Correct cache, stock and FinancialToolkit instructions |
| 2187 | 2026-10-05 | [mcp-parity][T37] Publish a unified capability resource and client examples |
| 2188 | 2026-10-05 | [mcp-parity][T38] Write operator setup, maintenance and rollback runbooks |
| 2189 | 2026-10-05 | [mcp-parity][T39] Build a shared real-protocol regression matrix |
| 2190 | 2026-10-05 | [mcp-parity][T40] Add Portfolio-based capability and prompt drift CI |
| 2191 | 2026-10-06 | [mcp-parity][T41] Certify package and interpreter replay |
| 2192 | 2026-10-06 | [mcp-parity][T42] Revalidate integrated Workspace and registered backend parity |
| 2193 | 2026-10-06 | [mcp-parity][T43] Validate controlled data and operator workflows |
| 2194 | 2026-10-27 | [mcp-parity][T44] Release, update coverage evidence, and prove rollback |
| 2196 | 2026-10-27 | [notebook-agent][NE1] Source story contracts and independent fixture readiness |
| 2201 | 2026-10-27 | [notebook-agent][NF1.1] Source inventory and versioned narrative contracts |
| 2202 | 2026-10-27 | [notebook-agent][NF1.2] Independent fixtures and capability readiness |
| 2203 | 2026-10-27 | [notebook-agent][NF2.1] Deterministic analytics and managed story state |
| 2211 | 2026-10-27 | [notebook-agent][N01] Inventory source-only notebook stories and Portfolio lineage |
| 2212 | 2026-10-27 | [notebook-agent][N02] Define typed story manifests, stage DAGs and state handoffs |
| 2213 | 2026-10-27 | [notebook-agent][N03] Build independent synthetic scenarios and parity expectations |
| 2214 | 2026-10-27 | [notebook-agent][N04] Bind story outcomes to real MCP capability readiness |
| 2215 | 2026-10-27 | [notebook-agent][N05] Expose missing notebook analytics through owned engine adapters |
| 2216 | 2026-10-27 | [notebook-agent][N06] Add story catalog, run registry and typed state management tools |
| 2217 | 2026-10-28 | [notebook-agent][N07] Produce bounded chart, table, report and XLSX artifacts |
| 2218 | 2026-10-28 | [notebook-agent][N08] Bridge backtest, tuning and replay into existing durable jobs |
| 2235 | 2026-10-27 | [bug] Retired Beads Git hooks still run during Portfolio commits |
| 2242 | 2026-10-26 | [security] Harden caller-controlled document URL fetchers before MCP exposure |
| 2245 | 2026-10-26 | [mcp-parity] Lock complete dual-MCP transitive dependency graphs |
| 2282 | 2026-10-26 | [mcp-parity] Enforce dependency-lock artifact hashes at dual-MCP launch |
| 2284 | 2026-10-26 | [docs] Pause handoff record for Portfolio MCP work (2026-10-26) |
| 2290 | 2026-10-27 | [mcp-parity] Admit SSRF-hardened document URL fetchers to MCP profiles |
| 2292 | 2026-10-27 | [ci] Auto-close-on-merge drops runs when several PRs merge into portfolio back to back |
| 2296 | 2026-10-27 | [docs] Check in the MCP-parity and Notebook Companion plan documents from the local stash |
| 2298 | 2026-10-27 | [mcp-parity] Capability inventory mislabels the ExchangeMarketHours TTL fetcher as non-persistent |
| 2300 | 2026-10-27 | [mcp-parity] Bundled MCP prompts require tool names that no profile emits |
| 2302 | 2026-10-27 | [mcp-parity] Offline MCP invocation evidence for the 70 legacy FMP Cached mappings |
| 2308 | 2026-10-27 | [docs] Record 2026-10-27 Portfolio session state and resume plan |
| 2313 | 2026-10-27 | [notebook-agent][N05a] Basket look-through, sector roll-up and concentration analytics over MCP |
| 2314 | 2026-10-27 | [notebook-agent][N05b] Seven-phase single-name analysis pipeline over MCP |
| 2315 | 2026-10-27 | [notebook-agent][N05c] Event timeline, Brinson attribution and recommendation-basket analytics over MCP |
| 2316 | 2026-10-27 | [notebook-agent][N05d] TechTrade validation-gate and indicator analytics over MCP |
| 2321 | 2026-10-27 | [notebook-agent][N05e] Review the remaining story:analytics stages and bind delivered run-state tools |
| 2323 | 2026-10-27 | docs(handoff): record N05 completion and Notebook Companion resume state |
| 2326 | 2026-10-28 | Record N07 completion and Notebook Companion resume state |
| 2329 | 2026-10-28 | Record N08 completion and Notebook Companion resume state |
| 2331 | 2026-10-28 | [notebook-agent][N09a] Human approval gate and isolated paper sandboxes (TechTrade engine) |
| 2332 | 2026-10-28 | [notebook-agent][N09b] TechTrade order tickets, batches and paper-sink artifacts |
| 2333 | 2026-10-28 | [notebook-agent][N09c] Portfolio paper blotter and low-buying-power alert in a durable sandbox |

## 3. Pull requests (index only)

| Old # | State | Head → Base | Title |
|---|---|---|---|
| 10 | merged | `docs/context-rules` → `develop` | docs: add collaboration rules, context, and copilot instructions |
| 11 | merged | `chore/devtools` → `develop` | chore: add local dev tooling and ignore rules |
| 12 | merged | `feat/fmp-cache` → `develop` | feat(fmp_cached): add MySQL-backed caching provider |
| 13 | merged | `feat/broker-import` → `develop` | feat(tools): add brokerage import and position-history utilities |
| 14 | merged | `feat/fintoolkit` → `develop` | feat(financialtoolkit): add FinanceToolkit extension |
| 15 | merged | `feat/portfolio` → `develop` | feat(portfolio): add portfolio app and OpenBB portfolio extension |
| 16 | merged | `feat/stock-analysis` → `develop` | feat(analysis): add 7-phase single-stock analysis pipeline |
| 17 | merged | `feat/agents` → `develop` | feat(agents): add OpenBB agents extension and MCP server profiles |
| 90 | merged | `docs/22-examples-relocation` → `trading_technicals` | docs(#22): re-add example notebooks under docs/examples/ with stripped outputs |
| 92 | merged | `chore/19-financialtoolkit-pypi` → `trading_technicals` | build(#19): converge openbb-financialtoolkit on financetoolkit PyPI ^2.1.2 |
| 95 | merged | `feat/93-openfigi-ticker-cusip-resolver` → `trading_technicals` | feat(#93): broad ticker→CUSIP resolver via OpenFIGI /v3/mapping |
| 98 | merged | `feat/refresh-etf-holdings-cache` → `trading_technicals` | feat(tools): refresh_etf_holdings_cache.py — daily etf_holdings cache warmer |
| 100 | merged | `feat/97-etf-holdings-free-fallback-tier` → `trading_technicals` | feat(#97): ETF holdings free fallback tier — SSGA half (v1) |
| 101 | merged | `trading_technicals` → `develop` | Merge trading_technicals fork into develop (153 commits across #65-#99) |
| 304 | closed | `analysis-hardening-pr` → `develop` | feat(analysis): Phase A partial — scaffolding + 5 quick wins (A0-A5) |
| 321 | merged | `feature/pine-wxz-trade-position-summary` → `openbb_pine_support` | feat(pine): TradeSummary + OpenPositionSummary + PyneCore serializer (bead 0e9.6.wxz) |
| 322 | merged | `feature/pine-y86-request-security-signature` → `openbb_pine_support` | feat(pine): request.security signature + SecurityContext population (bead 0e9.6.y86) |
| 323 | merged | `feature/pine-n6j-secondaries-hook` → `openbb_pine_support` | feat(pine): _install_secondaries_hook — monkey-patch pynecore.lib.request.security (bead n6j) |
| 324 | merged | `feature/pine-h14-strategy-signatures` → `openbb_pine_support` | feat(pine): strategy.* signatures (bead 0e9.6.h14) |
| 325 | closed | `feat/movers-z7f-ri3-90e` → `trading_technicals` | fix(techtrade): movers sector-scan + testing R7 rules (bd-z7f + ri3 + 90e) |
| 326 | merged | `feat/qc-core-helpers` → `develop` | feat(qc): add safe_join + parse_currency Tier-0 helpers |
| 327 | merged | `fix/qc-path-traversal` → `develop` | fix(qc): sandbox 3 path-traversal sites with safe_join |
| 328 | merged | `design/pine-extraction-to-pynecore` → `openbb_pine_support` | design(pine): extraction of Pine compiler + core runtime to prajoria/pynecore |
| 329 | merged | `fix/qc-api-key-in-url` → `develop` | fix(qc): route FMP apikey via params= not URL f-string |
| 330 | merged | `fix/qc-git-argv-injection` → `develop` | fix(qc): harden quant-scraper git argv against flag-injection + hangs |
| 331 | merged | `feat/analysis-a6-momentum-accel` → `trading_technicals` | feat(analysis): momentum_accel_63d on Phase6Result — A6 (bd-0h2.9) |
| 332 | merged | `fix/qc-mcp-exception-leak` → `develop` | fix(qc): sanitize MCP tool exceptions before returning to LLM |
| 333 | merged | `fix/qc-mcp-tool-allowlist` → `develop` | fix(qc): require explicit @mcp_tool decorator to expose MCP tools |
| 334 | merged | `fix/qc-fmp-cached-interval-routing` → `develop` | fix(qc): validate + fully-cover interval/adjustment routing in fmp_cached |
| 335 | merged | `docs/r7-mutation-testing-rules` → `trading_technicals` | docs(rules): codify R7.7-R7.11 — mutation testing + AST wiring + caplog patterns |
| 336 | merged | `test/zuw-mock-loud-defaults` → `trading_technicals` | test(analysis): _make_mock_p6 loud NaN defaults for unused scalars (bd-zuw) |
| 337 | merged | `feat/analysis-a7-earnings-revision` → `trading_technicals` | feat(analysis): earnings_revision_3m_direction on Phase1Result — A7 (bd-0h2.10) |
| 338 | merged | `fix/qc-analysis-config-raise` → `develop` | fix(analysis): raise on non-fmp_cached provider instead of warn (bd-omi) |
| 339 | merged | `fix/qc-run-router-config-engine` → `develop` | fix(backtest): honor config.engine when run(engine=) defaults to 'auto' (bd-q7u5) |
| 340 | merged | `fix/qc-confluence-volume-weight` → `develop` | fix(techtrade): raise on non-locked ConfluenceWeights.volume override (bd-qu2h + bd-c2fr) |
| 341 | merged | `fix/qc-refresh-etf-api-key-flag` → `develop` | fix(tools): honor refresh_etf_holdings_cache --api-key at runtime (bd-2k86) |
| 342 | merged | `fix/qc-fmp-cached-query-copy-drop-kwargs` → `develop` | fix(fmp_cached): rebuild fetch_query via query.model_copy across 9 wrapper models (bd-t7p2) |
| 343 | merged | `feat/analysis-a8-stop-cap-trailing` → `trading_technicals` | feat(analysis): stop cap + trailing stop rules on Phase7Result — A8 (bd-0h2.11) |
| 344 | merged | `fix/qc-cache-schema-ddl-raise` → `develop` | fix(fmp_cached): raise on DDL failure in create_all_flattened_tables + use logger (bd-jt4r) |
| 345 | merged | `fix/qc-institutional-ownership-validate-warn` → `develop` | fix(fmp_cached): raise-on-all-dropped + WARNING log in institutional_ownership.transform_data (bd-0bp1) |
| 346 | merged | `test/zuw-widen-mock-p2-p5` → `trading_technicals` | test(analysis): widen bd-zuw NaN-default treatment to _make_mock_p2/p3/p4/p5 |
| 347 | merged | `plan/pine-extraction` → `design/pine-extraction-to-pynecore` | plan(pine): Pine extraction implementation plan — Phase 2A (E0 + E1) |
| 348 | merged | `fix/qc-intraday-cache-density-check` → `develop` | fix(fmp_cached): add intraday cache density guard to _detect_missing_ranges (bd-isvv) |
| 349 | merged | `feat/regime-b0-b1-scaffold-detector` → `trading_technicals` | feat(regime): scaffold openbb-regime extension + MarketRegime detector (Phase B0+B1, bd-0h2.12/13) |
| 350 | merged | `feat/e05-pynecore-bridge` → `openbb_pine_support` | feat(pine): E0.5 extract pynecore sys.path bridge (bd-lef) |
| 351 | merged | `feat/e01-split-errors` → `openbb_pine_support` | feat(pine): E0.1 split errors.py into compiler_errors + provider errors (bd-3cf) |
| 352 | merged | `fix/qc-partial-gap-fill-warn-loudly` → `develop` | fix(fmp_cached): severity-scaled logging for partial gap-fill (bd-lyzk) |
| 353 | merged | `feat/e04-telemetry-injection` → `openbb_pine_support` | feat(pine): E0.4 abstract telemetry behind TelemetrySink injection (bd-gzf) |
| 354 | merged | `fix/qc-index-constituents-fetch-raise` → `develop` | fix(fmp_cached): raise on unexpected _fetch_from_fmp_api response shape (bd-wwvk) |
| 355 | merged | `fix/qc-financial-ratios-refresh-bypass` → `develop` | fix(fmp_cached): add refresh=True cache-bypass for financial_ratios (bd-ygoh) |
| 404 | merged | `feat/regime-b2-b3-p7-wiring` → `trading_technicals` | feat(analysis): wire MarketRegime into P7 composite + tranches (B2+B3, bd-0h2.14/15) |
| 405 | merged | `feat/regime-b4-router-rest-widget` → `trading_technicals` | feat(regime): obb.regime.detect router + REST + Workspace widget (B4, bd-0h2.16) |
| 406 | merged | `fix/29n-weekly-trend-preserves-caps` → `trading_technicals` | fix(analysis): weekly-trend recompute preserves hard-override composite caps (bd-29n) |
| 407 | merged | `fix/lw3-movers-pct-change-volume` → `trading_technicals` | fix(techtrade): movers pct_change/volume 3-defect regression (bd-lw3) |
| 414 | merged | `feat/qc-db-helpers` → `develop` | feat(fmp_cached): add Tier-0 db-helpers safe_identifier + replace_rows (bd-kh08) |
| 415 | merged | `fix/e05-bridge-idempotency-test` → `openbb_pine_support` | fix(pine): test_bridge_is_idempotent — clean baseline before assertion (bd-3qo) |
| 416 | merged | `fix/qc-ddl-injection` → `develop` | fix(qc): close DDL-injection cluster with safe_identifier (bd-9loj) |
| 417 | merged | `feat/e02-dispatcher-abstract-provider` → `openbb_pine_support` | feat(pine): E0.2 refactor security_dispatcher to consume abstract Provider (bd-r9m) |
| 418 | merged | `fix/qc-cache-replace-atomic` → `develop` | fix(fmp_cached): route 8 DELETE+INSERT sites through replace_rows (bd-n3sf) |
| 419 | merged | `feat/bd-7ct-confluence-foundation` → `trading_technicals` | feat(techtrade): confluence panel expansion foundation (bd-7ct) |
| 420 | merged | `feat/e03-executor-split` → `openbb_pine_support` | feat(pine): E0.3 split executor.py into executor_core + executor_shell (bd-9zb) |
| 421 | merged | `fix/bd-o4q-build-signals-golden` → `trading_technicals` | test(techtrade): build_signals-layer classic-path golden invariance (bd-o4q) |
| 422 | merged | `fix/qc-tools-parse-fidelity-autocommit` → `develop` | fix(tools): autocommit=False + explicit txn wrap for Fidelity persist (bd-2650) |
| 423 | merged | `feat/e06-test-split` → `openbb_pine_support` | feat(pine): E0.6 test-file split audit + refactor gray-zone tests (bd-209) |
| 424 | merged | `fix/qc-credential-helper-except` → `develop` | fix(fmp_cached): narrow credential-helper except from Exception to (JSON/OS/Unicode) (bd-gv1e) |
| 425 | merged | `feat/e07-grep-gate` → `openbb_pine_support` | feat(pine): E0.7 grep-gate verification (Phase 2A complete) (bd-dt1) |
| 426 | merged | `fix/qc-uolr-cache-year-quarter` → `develop` | fix(fmp_cached): filter institutional_ownership cache reads by year/quarter (bd-uolr) |
| 427 | merged | `fix/qc-hyzu-financial-ratios-unique` → `develop` | fix(fmp_cached): add UNIQUE(symbol,date,period) to financial_ratios (bd-hyzu) |
| 428 | merged | `fix/qc-e3v8-aextract-store-wrap` → `develop` | fix(fmp_cached): wrap 6 aextract_data _store calls in try/except (bd-e3v8) |
| 429 | merged | `plan/pine-extraction-2b` → `openbb_pine_support` | plan(pine): Phase 2B implementation plan — Pine extraction to pynecore |
| 430 | merged | `feat/e21-scratch-clone-and-tag` → `openbb_pine_support` | feat(pine): E2.1 pre-extraction M1 digest + scratch clone prep (bd-fis) |
| 431 | merged | `feat/e22-filter-repo-run` → `openbb_pine_support` | feat(pine): E2.2 git filter-repo extraction to scratch clone (bd-8tl) |
| 432 | merged | `chore/e24-verify-report` → `openbb_pine_support` | chore(pine): E2.4 post-merge verification report (bd-sqf) |
| 433 | merged | `feat/e31-submodule-bump` → `openbb_pine_support` | chore(pine): bump third_party/pynecore submodule to post-extraction HEAD (bd-kpg) |
| 434 | merged | `feat/e33-byo-provider-refactor` → `openbb_pine_support` | feat(pine-runtime): byo_provider inherits pynecore Provider base (bd-tzm) |
| 435 | merged | `feat/e32-fmp-provider-refactor` → `openbb_pine_support` | feat(pine-runtime): fmp_provider inherits pynecore Provider base (bd-3ch) |
| 436 | merged | `feat/bd-luy-trend-family` → `trading_technicals` | feat(techtrade): trend-family expansion — Aroon + Ichimoku (bd-luy) |
| 437 | merged | `feat/e34-import-rewrite` → `openbb_pine_support` | refactor(pine): rewrite compiler/runtime imports to pyne_compiler.* + delete _data_provider_stub (bd-8sq / E3.4) |
| 438 | merged | `feat/movers-z7f-supplemental` → `trading_technicals` | feat(techtrade): movers R7 rules + recorded fixtures (supersedes #325 post bd-lw3 merge) |
| 439 | merged | `feat/e35-shims-and-m1` → `openbb_pine_support` | feat(pine): install §13.5 deprecation shims + M1 smoke (bd-ijq / E3.5) |
| 440 | merged | `chore/e41-unfreeze-rescope` → `openbb_pine_support` | docs(pine): rescope DESIGN + unfreeze 9 P1 beads (bd-8j9 / E4.1) |
| 441 | merged | `feat/analysis-qc-3xq-sweep` → `trading_technicals` | fix(analysis): entry_rec ladder + tests — bd-3xq QC sweep (5 sub-beads + epic close) |
| 442 | merged | `docs/e42-manifest-prd-fixups` → `openbb_pine_support` | docs(pine): E4.2 coverage manifest + PRD amendments + bead fixups (bd-or5) |
| 447 | merged | `feat/provider-silent-failure-fixes` → `trading_technicals` | fix(providers,techtrade): silent-failure fixes — bd-3ka + bd-5in + bd-udq |
| 448 | merged | `fmp_trading` → `develop` | fmp-trading Phase 0–3: deterministic core + agentic discovery + MCP server |
| 449 | merged | `feat/bd-hpxh-configurable-extended-votes` → `trading_technicals` | feat(techtrade): configurable extended-vote allowlist — resolves bd-hpxh |
| 455 | merged | `feat/579-shim-reduction` → `openbb_pine_support` | refactor(pine): submodule bump + final shim reduction (bd-579) |
| 456 | merged | `feat/leaf-sweep-vwl-85w-tnz` → `trading_technicals` | chore/feat: leaf-bead sweep — bd-vwl + bd-85w + bd-tnz |
| 457 | merged | `feat/bd-znw-docs-refresh` → `trading_technicals` | docs(techtrade): confluence-panel-expansion Phase 4 docs (bd-znw) |
| 458 | closed | `chore/bump-pynecore-p2-wave1` → `openbb_pine_support` | chore(pine): bump third_party/pynecore submodule to 9cf7108 (Pine P2 Wave 1) |
| 459 | merged | `feat/nb01-panel-refresh` → `trading_technicals` | docs(notebooks): refresh nb01 §4 techtrade engine for bd-luy + bd-hpxh state |
| 460 | merged | `chore/bump-pynecore-p2-wave1-v2` → `openbb_pine_support` | chore(pine): bump third_party/pynecore to 9cf7108 + retire stale PF010 tests (Wave 1 + bd-kbtx) |
| 461 | merged | `feat/liz-executor-strategy` → `openbb_pine_support` | feat(runtime): executor strategy branch (bd-liz) |
| 462 | merged | `feat/4d0-strategies-run-flip` → `openbb_pine_support` | feat(pine-platform): /pine/strategies/run 501->real (bd-4d0) |
| 463 | merged | `feat/250-strategies-run-byo` → `openbb_pine_support` | feat(pine-platform): /pine/strategies/run_byo endpoint (bd-250) |
| 464 | merged | `fix/fmp-cached-import-breakage` → `develop` | fix(fmp_cached): FLATTENED_TABLES forward-ref + TTL wrapper Generic (bd-c4h) |
| 465 | merged | `feat/cht-conformance-strategy` → `openbb_pine_support` | test(pine): conformance_strategy harness + placeholder fixture (bd-cht) |
| 466 | merged | `feat/pi-router/scaffold` → `portfolio` | feat(portfolio-intel): scaffold openbb-portfolio-intel extension (bd-qy83.1.4) |
| 467 | merged | `feat/pi-app/paper-migration` → `portfolio` | feat(portfolio-intel): draft paper_* migration + structural tests (bd-qy83.1.5) |
| 468 | merged | `feat/pi-widgets/playwright-harness` → `portfolio` | feat(portfolio-intel): Playwright E2E harness for widget tests (bd-qy83.1.7) |
| 469 | merged | `feat/ph0-conformance-strategy-fixtures` → `openbb_pine_support` | test(pine): 5 conformance strategy .pine sources + TV-export docs (bd-ph0 phase 1) |
| 470 | merged | `pr/develop/sync-trading_technicals` → `develop` | sync: merge trading_technicals → develop (41 commits, 79 files, ~6 months of feature work) |
| 471 | merged | `feat/pi-ops/pr-template-ci-guard` → `portfolio` | ci(portfolio-intel): PR template + base-branch guard for feat/pi-* (bd-qy83.1.2) |
| 472 | merged | `feat/0uh-coverage-manifest` → `openbb_pine_support` | test(pine): coverage manifest — Phase 2 graduations (bd-0uh) |
| 473 | merged | `feat/pi-qa/isolation-spec` → `portfolio` | test(portfolio-intel): QA SEV-1 cross-account isolation spec (pending) (bd-qy83.1.8) |
| 474 | merged | `feat/pi-env/venv-smoke` → `portfolio` | feat(portfolio-intel): shared .env smoke test (bd-qy83.1.9) |
| 475 | merged | `fix/6atb-coverage-tool` → `openbb_pine_support` | fix(pine-tools): measure_wild_corpus_coverage.py post-extraction fix (bd-6atb) |
| 476 | merged | `fix/report-toctou-hardening-9nd.8` → `develop` | fix(fmp_trading): TOCTOU + symlink hardening for report writes (bd-9nd.8) |
| 477 | merged | `chore/pre-open-and-metrics-cleanups-9nd.10-11` → `develop` | chore(fmp_trading): aggregate clamp events + WARN on Decimal parse (bd-9nd.10, bd-9nd.11) |
| 478 | merged | `refactor/tick-loop-dataprovider-9nd.9` → `develop` | refactor(fmp_trading): tick_loop accepts injected DataProvider (bd-9nd.9) |
| 479 | merged | `feat/tickevent-quotes-9nd.12` → `develop` | feat(fmp_trading): widen TickEvent.payload to carry quotes (bd-9nd.12) |
| 480 | merged | `chore/bump-pynecore-alpha-27v7-9cae` → `openbb_pine_support` | chore(pine): bump third_party/pynecore submodule to e74c237 (alpha-blockers) |
| 481 | closed | `fix/techtrade-python-constraint` → `develop` | fix(platform): narrow python range to <3.14 to unblock dev_install.py -e (bd-qy83.1.13) |
| 482 | merged | `docs/bl57-alpha-quickstart-supported` → `openbb_pine_support` | docs(pine): alpha quickstart + supported features (bd-bl57) |
| 483 | merged | `fix/dev-install-python-constraint` → `develop` | fix(platform): narrow python range to <3.14 to unblock dev_install.py -e |
| 484 | merged | `fix/fmp-cached-schema-nameerror` → `develop` | test(fmp_cached): regression tests for cache_schema module import |
| 485 | merged | `feat/0ru2-bars-csv-support` → `openbb_pine_support` | test(pine): bars.csv support in conformance_strategy harness (bd-0ru2) |
| 486 | merged | `docs/dyhr-tv-walkthrough` → `openbb_pine_support` | docs(pine): TV Strategy Tester walkthrough - rsi_reversal pilot (bd-dyhr) |
| 487 | merged | `fix/cache-schema-order-on-portfolio` → `portfolio` | fix(fmp_cached): resolve cache_schema.py used-before-defined NameError on portfolio |
| 489 | merged | `chore/bd-gh-migration-plan` → `develop` | docs(hygiene): bd → GitHub Issues migration plan (v3) |
| 490 | merged | `chore/openbb-dev-cycle-gh-primary` → `develop` | chore(dev-cycle): make GitHub Issues the primary task tracker |
| 736 | merged | `docs/openbb-dev-cycle-v3-user-scope` → `develop` | docs(skills): update openbb-dev-cycle to v3 (GitHub Issues as primary tracker) |
| 737 | merged | `chore/beads-hygiene-phase-c` → `develop` | docs(hygiene): Phase C — codify gh-primary coordination protocol |
| 742 | closed | `fix/tech-debt-to-develop` → `develop` | fix(tech-debt): unblock 141 collection errors on develop (#738 + #739) |
| 758 | merged | `fix/test-failures-743` → `develop` | fix(tests): resolve #754 + #744 + review fixes (aliases, guards, comments) |
| 760 | merged | `fix/copilot-api-ascii-proxy` → `develop` | fix(copilot-api): ASCII proxy banner + retry; harden proxy launcher |
| 761 | merged | `fix/pytest-importlib-739` → `develop` | test(infra): --import-mode=importlib to fix tests-namespace collisions (#739) |
| 762 | closed | `chore/absorb-develop-into-portfolio` → `portfolio` | chore(portfolio): merge origin/develop — verify baseline (DRAFT) |
| 766 | merged | `fix/env-consistency-bootstrap` → `develop` | fix(pyproject): declare 7 fork-specific extensions + guard test (env consistency root cause) |
| 768 | merged | `fix/763-quantitative-technical-imports` → `develop` | fix(tests): correct broken `extensions.X` imports in helpers tests (closes #763) |
| 769 | merged | `fix/766-review-followups` → `develop` | fix(pyproject): PR #766 review follow-ups — alpha sort + path-existence guard |
| 770 | merged | `fix/tradingeconomics-bad-import` → `develop` | fix(tests): tradingeconomics bad providers.X import (same class as #763) |
| 772 | merged | `docs/fmp-cached-mysql-setup` → `develop` | docs(fmp_cached): add MySQL setup guide + troubleshooting (refs #771) |
| 773 | merged | `docs/claude-md-gh-issues-only` → `develop` | docs(claude-md): retire bd, use GitHub Issues only across all branches |
| 777 | merged | `fix/aftermarket-empty-symbols-gh-774` → `develop` | fix(fmp_cached): guard empty-symbols in aftermarket_quote._fetch_fresh_rows (#774) |
| 778 | merged | `fix/setup-database-sync-gh-775` → `develop` | fix(fmp_cached): setup_database create_cache_tables is sync, not async (#775) |
| 779 | merged | `fix/financial-ratios-migration-log-gh-776` → `develop` | fix(fmp_cached): pre-check financial_ratios UNIQUE index to eliminate 1061 ERROR log noise (#776) |
| 786 | merged | `fix/mark-integration-tests-gh-782` → `develop` | test(fmp_cached): mark 3 integration test files with pytestmark = pytest.mark.integration (#782) |
| 787 | merged | `fix/institutional-signature-gh-783` → `develop` | test(fmp_cached): update _get_cached_institutional call sites for year/quarter kwargs (#783) |
| 788 | merged | `fix/mock-drift-gh-784` → `develop` | test(fmp_cached): repair mock drift in dedicated_persistence + institutional_ownership (#784, partial) |
| 789 | merged | `fix/isolate-fmp-cached-fetchers-gh-785` → `develop` | test(fmp_cached): mark test_fmp_cached_fetchers as integration to stop cross-test pollution (#785) |
| 791 | merged | `fix/762-reverify-fixes` → `develop` | fix(dev-env): Poetry 2.x compat + Windows encoding + decorator guard (unblock fresh venv) |
| 797 | merged | `fix/793-ttl-wrapper-closure` → `develop` | fix(fmp_cached): route TTL wrapper DB calls through module namespace (closes #793) |
| 798 | merged | `fix/cat1-fmp-cached-closures` → `develop` | fix(fmp_cached tests): stop purging sys.modules in import-regression test (retires 36 fails) |
| 799 | merged | `fix/cat5-flattened-cache-method-rename` → `develop` | fix(fmp_cached tests): skip test_flattened_cache — manual demo, not a real test |
| 800 | merged | `fix/cat4-intraday-sql-formatting` → `develop` | fix(fmp_cached tests): lowercase expected substring in intraday SQL assertion |
| 801 | merged | `fix/cat3-ttlwrapper-generic-mro` → `develop` | fix(fmp_cached tests): satisfy Fetcher subclass contract in TTLWrapper Generic tests |
| 808 | merged | `fix/803-backtest-examples-integration` → `develop` | feat(backtest): add examples= + integration tests for all 11 routes (closes #803) |
| 809 | merged | `fix/805-regime-examples-integration` → `develop` | feat(regime): add examples= for about + integration tests for both routes (closes #805) |
| 810 | merged | `fix/804-fmp-trading-examples-integration` → `develop` | feat(fmp_trading): add examples= + integration tests for 3 routes (closes #804) |
| 811 | merged | `fix/806-techtrade-examples-integration` → `develop` | feat(techtrade): add examples= + integration tests for 11 routes across 6 router files (closes #806) |
| 812 | merged | `fix/807-allowlist-fmp-providers` → `develop` | fix(extensions/tests): exempt fmp_cached from provider allowlist gate (closes #807) |
| 814 | merged | `fix/techtrade-test-fixture-imports` → `develop` | fix(techtrade tests): use relative imports for tests.fixtures — restore CI signal |
| 815 | merged | `fix/ci-restore-vendored-exclude` → `develop` | fix(ci): restore Unit test Platform CI — exclude vendored external + fix fixture imports |
| 828 | merged | `fix/817-techtrade-pandas-ta-classic-dep` → `develop` | fix(techtrade): declare pandas-ta-classic as runtime dep (closes #817) |
| 829 | merged | `fix/821-fmp-trading-c-tickdata-quote-optional` → `develop` | fix(fmp_trading): make Quote trade-tape fields + TickData.session_status optional (#821 cluster C) |
| 830 | merged | `fix/821-fmp-trading-b-models-errors-import` → `develop` | fix(fmp_trading): 5 clusters — models.errors, PathTraversal, missing imports, tz-guard (#821) |
| 831 | merged | `fix/821-fmp-trading-rt-replay-divergence` → `develop` | fix(fmp_trading): replay wire-protocol event_type + TestRunTick fixture stubs (#821) |
| 832 | merged | `fix/821-fmp-trading-v-signal-wiring-stubs` → `develop` | fix(fmp_trading): V + T-partial — signal wiring stubs + strict-mode edge cases (#821) |
| 833 | merged | `fix/821-fmp-trading-misc-cleanups` → `develop` | fix(fmp_trading): risk_clamp payload shape + xlsx_builder .tmp extension (#821) |
| 834 | merged | `docs/821-fmp-trading-design-questions` → `develop` | docs(design-questions): 4 open decisions for remaining fmp_trading tests (#821) |
| 835 | merged | `fix/821-final-4-design-decisions` → `develop` | fix(fmp_trading): implement all 4 design decisions — closes #821 (0 fails) |
| 836 | merged | `fix/820-fmp-cached-mysql-marker-sweep` → `develop` | fix(fmp_cached): use obb.equity in import regression test — closes #820 (0 fails) |
| 837 | merged | `feat/pi-ops/enforce-closes-syntax-gh-826` → `portfolio` | ci(portfolio-intel): enforce Closes #NN syntax on feat/pi-* PRs (#826) |
| 839 | merged | `fix/824-core-openapi-forward-ref` → `develop` | fix(core): remove deferred annotations from routers — restore app.openapi() (#824) |
| 840 | merged | `fix/819-backtest-empyrical` → `develop` | fix(backtest): importorskip empyrical in optional-import test (closes #819) |
| 841 | merged | `fix/825-platform-api-apps-json` → `develop` | fix(platform_api): use PurePosixPath in unix-absolute-path test (closes #825) |
| 842 | merged | `fix/822-mcp-server-regressions` → `develop` | fix(mcp_server): update tests for bundled system_prompt + server_prompts.json (closes #822) |
| 843 | merged | `fix/818-agents-marker-sweep` → `develop` | fix(agents): mark ADK-dependent tests requires_agents (closes #818) |
| 845 | merged | `fix/785-fmp-cached-cassettes-gh` → `develop` | fix(fmp_cached): record VCR cassettes + fix date-in-URL bug (closes #785) |
| 846 | merged | `fix/784-fmp-cached-stale-symbols-gh` → `develop` | fix(fmp_cached): realign test_fmp_cached_fetchers with current API (closes #784) |
| 848 | merged | `feat/pine-strategies-list-endpoint-gh-588` → `openbb_pine_support` | feat(pine/strategies): add GET /pine/strategies/catalog endpoint (#588) |
| 850 | merged | `feat/pi-ops/portfolio-intel-entry-point-gh-802` → `portfolio` | fix(portfolio-intel): accept ancestor-missing in _include_subrouters guard (#802) |
| 852 | merged | `fix/751-fmp-etf-holdings-cassette-gh` → `develop` | fix(fmp): re-record test_fmp_etf_holdings_fetcher cassette (closes #751) |
| 853 | merged | `fix/753-sec-cassettes-gh` → `develop` | fix(sec): record 4 missing VCR cassettes; skip broken ownership_changes (closes #753) |
| 855 | merged | `fix/813-financialtoolkit-integration-tests-gh` → `develop` | test(financialtoolkit): add integration tests for 25 uncovered routes (closes #813) |
| 857 | merged | `feat/pi-ops/closes-syntax-tighten-prose-gh-851` → `portfolio` | ci(portfolio-intel): tighten closes-syntax heuristic on backticked prose (#851) |
| 858 | merged | `feat/pi-ops/add-openbb-backtest-to-devinstall-gh-856` → `portfolio` | fix(portfolio-intel): declare openbb-backtest as runtime dep (#856) |
| 862 | merged | `fix/859-core-api-init-gh` → `develop` | fix(core): add missing __init__.py to api/ + api/auth/ (closes #859) |
| 863 | merged | `fix/860-broken-test-imports-gh` → `develop` | fix(tests): repair 2 broken imports under --import-mode=importlib (closes #860) |
| 864 | merged | `fix/861-doctor-ping-cache-gh` → `develop` | fix(fmp_trading): doctor pings surviving cache helper, not ghost ping_cache (closes #861) |
| 866 | merged | `feat/pi-ops/dev-install-pip-based-gh-865` → `portfolio` | fix(dev-install): rewrite as pip-based to actually populate fresh venvs (#865) |
| 877 | merged | `fix/872-portfolio-custom-version-gh` → `develop` | fix(tests): skip path-based deps in extension version-match check (closes #872) |
| 878 | merged | `fix/867-async-marker-gh` → `develop` | fix(fmp_cached): add pytest.mark.asyncio module marker to 2 test files (closes #867) |
| 879 | merged | `fix/869-backtest-registry-cleanup-gh` → `develop` | fix(backtest): autouse fixture to clean up test-registered strategies (closes #869) |
| 880 | merged | `fix/873-asyncio-get-event-loop-gh` → `develop` | fix(agents): swap asyncio.get_event_loop() for asyncio.run() on Py3.12 (closes #873) |
| 881 | merged | `fix/868-output-path-escapes-jail-gh` → `develop` | fix(fmp_trading): re-export OutputPathEscapesJail from reporting.errors (closes #868) |
| 882 | merged | `fix/874-cftc-startup-http-gh` → `develop` | fix(cftc): degrade build_choices on upstream failure so API boots (closes #874) |
| 883 | merged | `fix/870-architecture-test-pip-install-gh` → `develop` | fix(fmp_trading): pre-install in-tree deps in architecture test (closes #870) |
| 884 | merged | `fix/871-agent-import-guard-gh` → `develop` | fix(fmp_trading): accept lazy-import as valid for agent guard (closes #871) |
| 885 | merged | `feat/pi-app/fix-extension-about-nameerror-gh-849` → `portfolio` | fix(portfolio-intel): drop 'from __future__ import annotations' to unbreak about() codegen (#849) |
| 887 | merged | `feat/pi-ops/vendor-portfolio-export-gh-886` → `portfolio` | feat(tools): vendor portfolio_export into openbb_platform/tools/ (#886) |
| 889 | merged | `feat/pi-tools/testdata-generator-in-pe-gh-888` → `portfolio` | feat(portfolio_export): add pe-testdata generator + round-trip smoke tests (#888) |
| 890 | merged | `feat/pi-ops/auto-close-on-portfolio-merge-gh-847` → `portfolio` | ci(portfolio-intel): auto-close #NN cited in merge commits on portfolio push (#847) |
| 891 | merged | `feat/pi-ops/local-deps-fork-extensions-gh-876` → `portfolio` | chore(dev-install): add 4 fork-only extensions to LOCAL_DEPS (#876) |
| 893 | merged | `feat/pi-app/simple-fill-model-broker-protocol-gh-892` → `portfolio` | feat(portfolio-intel): SimpleFillModel implementing openbb_backtest Broker Protocol (#892) |
| 895 | open | `sync/upstream-openbb-2026-07-19` → `develop` | chore: sync upstream OpenBB-finance/OpenBB develop (10 commits, 2 conflicts resolved) |
| 897 | merged | `feat/pi-app/xray-lookthrough-rollups-hhi-gh-526` → `portfolio` | feat(portfolio-intel): X-Ray look-through + rollups + HHI concentration (#526 #535 #536) |
| 898 | merged | `fix/894-openbb-core-journal-preinstall-gh` → `develop` | fix(fmp_trading): also pre-install openbb-core from local tree (closes #894) |
| 899 | merged | `feat/pi-app/events-smartmoney-analytics-gh-537` → `portfolio` | feat(portfolio-intel): Event Calendar merge + Smart-Money aggregator (#537 #538) |
| 900 | merged | `fix/896-symlink-writer-check-gh` → `develop` | fix(fmp_trading): refuse symlink at write target before unlink (closes #896) |
| 901 | merged | `feat/pi-app/risk-metrics-var-contribution-gh-539` → `portfolio` | feat(portfolio-intel): risk metrics + VaR contribution (#539 #540) |
| 905 | merged | `feat/pi-app/whatif-diff-engine-gh-558` → `portfolio` | feat(portfolio-intel): stateless What-If diff engine (#558) |
| 906 | merged | `feat/pine-592/strategy-exit-v5-shim` → `openbb_pine_support` | feat(pine/v5): shim strategy.*(when=…) removed in v6 (#592) |
| 907 | merged | `fix/902-cftc-null-subcategory-gh` → `develop` | fix(cftc): null-safe record parsing in build_choices (closes #902) |
| 908 | merged | `feat/pi-data/etf-holdings-gh-512` → `portfolio` | feat(portfolio-intel): unblock EtfHoldings for SPY + DIA + fix double-normalize bug (#512) |
| 910 | merged | `feat/pine-590/backtest-soft-dep-import` → `openbb_pine_support` | feat(pine/backtest): add maybe_export_to_backtest soft-dep bridge (#590) |
| 913 | merged | `feat/pi-app/xray-route-gh-541` → `portfolio` | feat(portfolio-intel): /portfolio_intel/xray route + basket look-through (#541) |
| 914 | merged | `fix/known-noise-tests-gh` → `develop` | test: convert 4 known-noise env-induced fails to clean skips (harness green) |
| 916 | merged | `feat/pi-app/risk-concentration-routes-gh-528` → `portfolio` | feat(portfolio-intel): /portfolio_intel/risk.metrics + .concentration routes (#528) |
| 917 | merged | `feat/pine-589/backtest-shape-adapter` → `openbb_pine_support` | feat(pine/analytics): Pine strategy -> openbb-backtest shape adapter (#589) |
| 918 | merged | `feat/pi-app/events-route-gh-542` → `portfolio` | feat(portfolio-intel): /portfolio_intel/events.timeline route (#542) |
| 919 | merged | `feat/pine-585/backtest-integration-test` → `openbb_pine_support` | test(pine/backtest): end-to-end integration test for #590+#589 chain (#585) |
| 920 | merged | `feat/pi-app/smart-money-route-gh-527` → `portfolio` | feat(portfolio-intel): /portfolio_intel/smart_money.rollup route (#527) |
| 921 | merged | `docs/pine-claude-md-merge-rule-learnings` → `openbb_pine_support` | docs(pine): document 2026-07-19 session learnings in CLAUDE.md |
| 922 | merged | `chore/tv-indicator-audit-gh-780` → `portfolio` | chore(audit): TradingView 31-indicator coverage on portfolio_basket (#780) |
| 923 | merged | `feat/pine-875/pylint-cleanup` → `openbb_pine_support` | docs(pine): upgrade pylint suppression justifications (#875) |
| 924 | merged | `chore/fmp-cached-mypy-cleanup-gh-909` → `portfolio` | chore(fmp_cached): mypy hygiene pass — first-order type-ignores (#909) |
| 925 | merged | `chore/fmp-cached-coverage-audit-gh-827` → `portfolio` | chore(audit): fmp_cached coverage for P0 Data-Layer clusters (#827) |
| 926 | merged | `feat/pi-analytics/whatif-cash-line-gh-903` → `portfolio` | feat(pi/whatif): cash line + funding-mode support (#903) |
| 927 | merged | `feat/pi-analytics/whatif-shorts-gh-904` → `portfolio` | feat(pi/whatif): short-position support + signed rollups (#904) |
| 928 | merged | `feat/pi-analytics/attribution-waterfall-shape-gh-560` → `portfolio` | feat(pi/attribution): waterfall response shape + sum invariant (#560) |
| 929 | merged | `feat/pi-analytics/backtest-handoff-gh-561` → `portfolio` | feat(pi/handoff): backtest export contract (#561) |
| 931 | merged | `feat/pi-data/index-constituents-history-gh-543` → `portfolio` | feat(pi/data): index-constituent history refresh + point-in-time (#543) |
| 932 | merged | `feat/pi-analytics/brinson-fachler-math-gh-559` → `portfolio` | feat(pi/attribution): Brinson-Fachler compute — partial ship (#559) |
| 933 | merged | `feat/pi-paper/account-model-gh-562` → `portfolio` | feat(pi/paper): AccountStore + InMemoryAccountStore (#562) |
| 934 | merged | `feat/pi-paper/cost-basis-pnl-gh-548` → `portfolio` | feat(pi/paper): shared cost-basis + P&L math (#548) |
| 936 | merged | `feat/pi-paper/fills-v0-gh-563` → `portfolio` | feat(pi/paper): v0 fill engine — market + limit + slippage + freshness (#563) |
| 937 | merged | `feat/pi-paper/ledger-replay-gh-545` → `portfolio` | feat(pi/paper): append-only ledger + deterministic replay (#545) |
| 938 | merged | `fix/pi-paper/init-conflict-markers` → `portfolio` | fix(pi/paper): remove conflict markers from __init__.py — EMERGENCY |
| 939 | merged | `fix/pi-paper/security-hardening-post-563` → `portfolio` | fix(pi/paper): security hardening — update_cash primitive + unstamped-quote reject |
| 940 | merged | `feat/pi-paper/isolation-audit-gh-546` → `portfolio` | test(pi/paper): cross-account isolation audit — SEV-1 gate (#546) |
| 941 | merged | `feat/pi-paper/race-hardening-gh-547` → `portfolio` | feat(pi/paper): per-account single-writer lock + race stress tests (#547) |
| 942 | merged | `feat/pi-paper/fills-v1-gh-544` → `portfolio` | feat(pi/paper): fills v1 wire types — stop/stop_limit/trailing_stop + IOC/FOK (#544) |
| 943 | merged | `feat/pi-testing/brinson-synthetic-fixtures-gh-935` → `portfolio_validations` | feat(pi/testing): Brinson-Fachler synthetic fixtures + oracle (#935 + closes #559) |
| 944 | merged | `chore/p0-data-runtime-audit-gh-513-525` → `portfolio` | chore(pi/data): P0 data-layer runtime audit — closes #513-#525 |
| 946 | merged | `docs/pine-fixture-prep-guide` → `openbb_pine_support` | docs(pine): step-by-step TV fixture prep + export guide |
| 947 | merged | `feat/pi-analytics/sentiment-gh-570` → `portfolio` | feat(pi/analytics): sentiment rollup — weighted analyst + PT upside (#570) |
| 948 | merged | `test/develop-e2e-docker-stack` → `develop` | feat(docker/e2e): develop-branch stability harness (5 green cycles) |
| 949 | merged | `feat/pi-analytics/alerts-gh-571` → `portfolio` | feat(pi/analytics): alert-rule engine — 6 trigger types (#571) |
| 950 | merged | `feat/pi-app/p3-routes-gh-572-574` → `portfolio` | feat(pi/app): P3 app routes — news/sentiment/backtest/paper-alerts (#572-#574) |
| 952 | closed | `feat/pine-578/reshape-validation-metadata` → `docs/pine-fixture-prep-guide` | feat(pine/tools): D2.1 structural validation + D2.2 metadata capture on reshape_tv_trades (#951) |
| 954 | merged | `feat/pi-ops/status-tracking-gh-953` → `portfolio` | ops(portfolio-intel): enforce Project #4 Status=In Progress on claim (#953) |
| 956 | merged | `feat/pi-data/fmp-fixture-harness-gh-508` → `portfolio` | feat(fmp_cached): FMP fixture-record harness + coverage gate (#508) |
| 958 | merged | `feat/pi-data/fmp-fixture-drain-batch1-gh-955` → `portfolio` | feat(fmp_cached): fixture drain batch 1 — 14 new cassettes (#955) |
| 960 | closed | `feat/pine-hybrid-fixture-spec-gh-957` → `openbb_pine_support` | docs(pine/spec): promote hybrid-fixture-suite brainstorm to formal design spec (#957) |
| 962 | merged | `feat/pi-data/fmp-fixture-drain-batch2-gh-955` → `portfolio` | feat(fmp_cached): fixture drain batch 2 — 8 new cassettes (#955) |
| 966 | merged | `feat/pi-data/fmp-fixture-drain-batch3-gh-955` → `portfolio` | feat(fmp_cached): fixture drain batch 3 — 9 new cassettes (#955) |
| 969 | merged | `feat/pi-data/fmp-fixture-drain-batch4-gh-955` → `portfolio` | feat(fmp_cached): fixture drain batch 4 — 7 new cassettes (#955) |
| 970 | closed | `feat/pine-canonical-bars-and-capture-gh-967` → `openbb_pine_support` | feat(pine/hybrid-fixtures): D2.3 capture_bars_provenance + canonical_bars module (#967) |
| 971 | merged | `docs/claude-md-closes-syntax-rule` → `portfolio` | docs(claude-md): document Closes-syntax check grammar (hit twice this session) |
| 972 | merged | `fix/pi-ops/fmp-apikey-scrub-gh-963` → `portfolio` | fix(fmp_cached): scrub apikey= from log records at package boundary (#963) |
| 974 | merged | `docs/pine-claim-heartbeat-rule-gh-973` → `openbb_pine_support` | docs(pine/claude-md): claim + heartbeat protocol for autonomous cycles on Project #5 (#973) |
| 975 | merged | `feat/pi-paper/corp-action-reconciler-gh-554` → `portfolio` | feat(paper): corporate-action reconciler (#554) |
| 977 | merged | `fix/pine-hook-force-push-tests-gh-598` → `openbb_pine_support` | test(pine/hooks): 52-test regression suite for block-protected-branch-push (#598) |
| 978 | merged | `feat/pi-attribution/brinson-oracle-gh-935` → `portfolio` | feat(analytics): Brinson-Fachler synthetic test-data generator + oracle (#935) |
| 979 | merged | `feat/pi-attribution/engine-gh-559` → `portfolio` | feat(analytics): Brinson-Fachler attribution engine (#559) |
| 1001 | merged | `docs/pi-equity-profile-prd-gh-781` → `portfolio` | docs(pi): equity profile data-coverage audit (#781) |
| 1004 | merged | `feat/pi-widgets/host-canvas-gh-981` → `portfolio` | feat(desktop): portfolio-intel widget host + SDK (#981, #982) |
| 1005 | merged | `ci/pi-desktop-frontend-gh-983` → `portfolio` | ci(desktop): frontend lint + typecheck + vitest for portfolio-branch PRs (#983) |
| 1006 | merged | `feat/pi-brinson-external-fixtures-gh-557` → `portfolio` | feat(analytics): Brinson external reference fixtures + seed script (#557) |
| 1008 | merged | `feat/pi-workspace-backend-gh-1007` → `portfolio` | feat(portfolio_intel): OpenBB Workspace backend for widgets (#1007) |
| 1009 | merged | `feat/local-ci-cli-gh-985` → `test/develop-e2e-docker-stack` | feat(ci): local-ci deterministic CLI + YAML schema (#985) |
| 1010 | merged | `feat/pi-widgets/xray-pies-gh-529` → `portfolio` | feat(widget_backend): P1/P2/P3 widget batch (#529-#577) |
| 1011 | merged | `feat/pi-widgets/equity-profile-gh-990` → `portfolio` | feat(widget_backend): Equity Profile section widgets (#990-#996) |
| 1012 | merged | `docs/pi-release-notes-gh-566` → `portfolio` | docs(pi): release notes for pi-rc-1 (#566) |
| 1015 | merged | `feat/local-ci-skill-gh-989` → `feat/local-ci-cli-gh-985` | feat(skill): local-ci agent skill wrapper (#989) |
| 1016 | merged | `feat/fmp-cached/drain-955` → `portfolio` | feat(fmp_cached): drain 13 date-coercion endpoints from #955 allowlist |
| 1017 | closed | `feat/pine-578/reshape-validation-metadata` → `openbb_pine_support` | feat(pine/tools): D2.1 structural validation + D2.2 metadata capture on reshape_tv_trades (#951) |
| 1018 | merged | `feat/pine-reshape-d21-d22-gh-951-v2` → `openbb_pine_support` | feat(pine/tools): D2.1 structural validation + D2.2 metadata capture on reshape_tv_trades (#951) |
| 1019 | merged | `feat/pine-hybrid-fixture-spec-gh-957-v2` → `openbb_pine_support` | docs(pine/spec): promote hybrid-fixture-suite brainstorm to formal design spec (#957) |
| 1020 | merged | `feat/pine-canonical-bars-and-capture-gh-967-v2` → `openbb_pine_support` | feat(pine/hybrid-fixtures): D2.3 capture_bars_provenance + canonical_bars module (#967) |
| 1027 | merged | `feat/fmp-cached/analyst-recommendations-gh-1022` → `portfolio` | feat(fmp_cached + widget): analyst recommendations + estimate history (#997, #998) |
| 1318 | merged | `feat/fmp-cached/wave0-inventory-harness-gh-1028` → `portfolio` | feat(fmp_cached): Wave 0 inventory + harness (#1028) |
| 1319 | merged | `docs/memories-wave0-shipped` → `portfolio` | docs(memories): Wave 0 shipped + correct bd-retirement slip |
| 1320 | merged | `feat/fmp-cached/w4-directory-available-lists-gh-1052` → `portfolio` | feat(fmp_cached): W4 Directory drain — 4 available-* endpoints (#1052-#1055) |
| 1322 | merged | `feat/fmp-cached/w4-directory-symbol-lists-gh-1045` → `portfolio` | feat(fmp_cached): W4 Directory drain batch 2 — 5 symbol-list endpoints (#1045-#1050) |
| 1323 | merged | `feat/fmp-cached/w4-directory-batch3-gh-1158` → `portfolio` | feat(fmp_cached): W4 Directory drain batch 3 — 4 market-reference lists (#1158 #1173 #1182 #1197) |
| 1324 | merged | `feat/fmp-cached/w4-directory-batch4-gh-1167` → `portfolio` | feat(fmp_cached): W4 Directory drain batch 4 — 5 reference lists (#1102 #1110 #1167 #1168 #1169) |
| 1325 | merged | `feat/fmp-cached/w4-directory-batch5-gh-1170` → `portfolio` | feat(fmp_cached): W4 Directory drain batch 5 — historical + change (#1048 #1094 #1170-#1172) + plan-limit #1051 |
| 1326 | merged | `feat/fmp-cached/w4-search-batch6-gh-1038` → `portfolio` | feat(fmp_cached): W4 Search drain — 6 query-parameterized endpoints (#1038-#1042 #1044) |
| 1327 | merged | `feat/fmp-cached/w4-final-batch7-gh-1085` → `portfolio` | feat(fmp_cached): W4 finish — 3 single-param fetchers (#1085 #1099 #1224) |
| 1328 | merged | `docs/memories-w4-drain-shipped` → `portfolio` | docs(memories): W4 drain shipped 2026-07-21 |
| 1329 | merged | `feat/fmp-cached/w7-analyst-batch8-gh-1057` → `portfolio` | feat(fmp_cached): W7 Analyst drain — 6 symbol-parameterized rating fetchers (#1057-#1063) |
| 1331 | merged | `feat/fmp-cached/w7-sector-batch10-gh-1212` → `portfolio` | feat(fmp_cached): W7 MarketPerformance drain — 8 sector/industry endpoints (#1212-#1219) |
| 1332 | merged | `docs/memories-2026-07-21-final` → `portfolio` | docs(memories): 2026-07-21 final drain state |
| 1333 | merged | `feat/fmp-cached/w2-quote-batch11-gh-1090` → `portfolio` | feat(fmp_cached): W2 Quote drain — 11 quote-family endpoints (#1090 #1091 #1093 #1225 #1245-#1253) |
| 1334 | merged | `feat/fmp-cached/w2-batch-quotes-plan-limited-gh-1161` → `portfolio` | docs(plan_limited): W2 batch-*-quotes marked Premium (#1161 #1176 #1185 #1200 #1254-#1260) |
| 1335 | merged | `feat/fmp-cached/w1-statements-batch13-gh-1132` → `portfolio` | feat(fmp_cached): W1 Statements drain — 12 statement-family fetchers (#1084 #1103-#1106 #1132-#1141) |
| 1336 | merged | `feat/fmp-cached/w1-ttm-plan-limited-gh-1126` → `portfolio` | docs(plan_limited): W1 TTM statements marked Premium (#1126-#1129) |
| 1337 | merged | `feat/fmp-cached/w1-as-reported-batch14-gh-1146` → `portfolio` | feat(fmp_cached): W1 as-reported + financial-reports-json (#1142 #1146-#1149) |
| 1338 | merged | `feat/fmp-cached/w3-economic-indicators-gh-1108` → `portfolio` | feat(fmp_cached): W3 EconomicIndicators (#1108) |
| 1339 | merged | `docs/memories-2026-07-22` → `portfolio` | docs(memories): 2026-07-22 drain continuation |
| 1340 | merged | `feat/fmp-cached/plan-limited-bulk-batch-partners-gh-1119` → `portfolio` | docs(plan_limited): 30 W5/W6/W8 Premium endpoints (#1113 #1119-#1122 #1289-#1313) |
| 1341 | merged | `feat/fmp-cached/w5-w6-w8-free-batch15-gh-1087` → `portfolio` | feat(fmp_cached): W5/W6/W8 free-tier drain — 30 fetchers (#1069-#1288) |
| 1342 | merged | `docs/memories-w-all-drained` → `portfolio` | docs(memories): FMP cached drain complete — W1-W8 all closed |
| 1343 | merged | `feat/fmp-cached/w4-final-coverage-fill-gh-955` → `portfolio` | test(fmp_cached): add EquityScreener cassette — closes #955 fixture coverage |
| 1344 | merged | `docs/memories-project4-drain-endgame` → `portfolio` | docs(memories): project4 drain endgame — 3 open (out-of-scope) |
| 1349 | merged | `feat/scrape-record/framework-gh-1346` → `portfolio` | feat(scrape_record): new record/replay framework for offline provider snapshots (#1346) |
| 1350 | merged | `feat/yfinance/recorded-options-fetcher-gh-1347` → `portfolio` | feat(yfinance): snapshot-backed options fetchers via scrape_record (closes #999) |
| 1351 | merged | `feat/scrape-record/bond-etf-holdings-gh-1348` → `portfolio` | feat(yfinance): bond-ladder fetcher via scrape_record + path-traversal hardening (closes #1000) |
| 1371 | merged | `docs/nb-series-gh-1353` → `portfolio` | docs(nb-series): Story Bible + tracking rule hardening (#1353) |
| 1372 | merged | `docs/nb-series-phase-a-gh-1354` → `portfolio` | docs(nb-series): Phase A narrative skeletons for all 7 notebooks + README (#1354-#1361) |
| 1380 | merged | `docs/scrape-record-3-endpoints-pr1-gh-1375` → `portfolio` | feat(yfinance,scrape_record): 3 recorded fetchers + extractors + tests — sub-epic #1374 PR-1 (#1375) |
| 1381 | merged | `docs/scrape-record-3-endpoints-pr2-gh-1376` → `portfolio` | feat(scrape_record): Playwright recording scripts for 3 yfinance endpoints — sub-epic #1374 PR-2 (#1376) |
| 1382 | merged | `docs/scrape-record-3-endpoints-pr3-gh-1377` → `portfolio` | feat(scripts): sweep script + universe list for scrape_record — sub-epic #1374 PR-3 (#1377) |
| 1383 | merged | `docs/scrape-record-drift-ci-gh-1379` → `portfolio` | ci(scrape_record): nightly drift-check workflow + doc updates for 3 new fetchers (#1379) |
| 1387 | merged | `docs/yahoo-layered-fastfallback-gh-1385` → `portfolio` | feat(scrape_record): layered query1+DOM fast-path for 3 yfinance recordings — sub-epic #1384 PR-A (#1385) |
| 1388 | merged | `docs/yahoo-ingest-snapshots-gh-1386` → `portfolio` | feat(scrape_record): ingest 115 real universe snapshots + round-trip suite — sub-epic #1384 PR-B (#1386, closes #1373) |
| 1391 | merged | `docs/nb01-code-fulfillment-gh-1363` → `portfolio` | docs(nb-series): NB01 Phase B code fulfillment — fmp_cached primary + snapshot fallback (#1363) |
| 1392 | merged | `docs/nb02-code-fulfillment-gh-1364` → `portfolio` | docs(nb-series): NB02 Phase B code fulfillment — 7-phase MSFT deep-dive (#1364) |
| 1393 | merged | `docs/nb03-code-fulfillment-gh-1365` → `portfolio` | docs(nb-series): NB03 Phase B code fulfillment — basket x-ray + risk (#1365) |
| 1396 | merged | `docs/nb04-code-fulfillment-gh-1366` → `portfolio` | docs(nb-series): NB04 Phase B code fulfillment — events + smart-money (#1366) |
| 1397 | merged | `docs/nb05-code-fulfillment-gh-1367` → `portfolio` | docs(nb-series): NB05 Phase B code fulfillment — what-if + Brinson + paper (#1367) |
| 1398 | merged | `docs/nb06-code-fulfillment-gh-1368` → `portfolio` | docs(nb-series): NB06 Phase B code fulfillment — backtest + validation (#1368) |
| 1399 | merged | `docs/nb07-code-fulfillment-gh-1369` → `portfolio` | docs(nb-series): NB07 Phase B code fulfillment — offline recording + end-to-end (#1369) |
| 1406 | merged | `docs/nb-series-phase-b-gate-gh-1370` → `portfolio` | docs(nb-series): Phase B gate — smoke tests + product review + follow-ups (#1370, closes epic #1352) |
| 1407 | merged | `docs/nb-followups-1403-1404` → `portfolio` | docs(nb-series): STORY_BIBLE fixture-lock to real Phase B run (#1403) |
| 1408 | merged | `docs/nb-phase-b-followups-final` → `portfolio` | docs(nb-series): Phase B follow-ups — smart-money fixture + timing + loud-empty (#1400 #1401 #1402 #1405) |
| 1417 | merged | `docs/nb-teaching-depth-batch1` → `portfolio` | docs(nb-series): Phase C batch 1 — NB01+NB02 teaching depth + STORY_BIBLE §10 + README learning path (#1410 #1411) |
| 1418 | merged | `docs/nb-teaching-depth-batch2` → `portfolio` | docs(nb-series): Phase C batch 2 — NB03+NB04+NB05 teaching depth (#1412 #1413 #1414) |
| 1419 | merged | `docs/nb-teaching-depth-batch3` → `portfolio` | docs(nb-series): Phase C batch 3 — NB06+NB07 teaching depth, closes epic #1409 (#1415 #1416) |
| 1420 | merged | `feat/portfolio-snapshot-importer` → `portfolio` | feat(portfolio_snapshot_importer): read-only Fidelity CSV → SQLite ingest with append-only history |
| 1421 | closed | `feat/nb-basket-bridge-and-hygiene` → `feat/portfolio-snapshot-importer` | feat: basket bridge (importer → NB) + notebook check-in hygiene rule |
| 1422 | merged | `feat/nb-basket-bridge-and-hygiene` → `portfolio` | feat: basket bridge (importer → NB) + notebook check-in hygiene rule |
| 1423 | merged | `docs/nb-analyst-recommendations-basket` → `portfolio` | docs(nb-series): NB08 analyst-recommendations basket — 16-ETF Dalio+Bogle+Faber synthesis |
| 1424 | merged | `docs/nb08-low-cost-self-maintained` → `portfolio` | docs(nb-series): NB08 §10 low-cost self-maintained variant (RECOMMENDED) |
| 1427 | merged | `feat/scrape-record-local-db-gh-1425` → `portfolio` | feat(scrape_record): user-local SQLite snapshot store, remove committed Yahoo JSON (#1425) |
| 1445 | merged | `feat/notebooks-sec-nport-migration-gh-1426` → `portfolio` | feat(nb): migrate ETF/bond look-through Yahoo→SEC N-PORT (#1426) |
| 1446 | merged | `feat/nb01-authoritative-provider-chain-gh-1429` → `portfolio` | docs(nb01): adopt 5-tier authoritative provider chain (#1429) |
| 1447 | merged | `feat/nb02-authoritative-provider-chain-gh-1430` → `portfolio` | docs(nb02): document 5-tier provider chain + SEC XBRL point-in-time caveat (#1430) |
| 1448 | merged | `feat/nb03-authoritative-provider-chain-gh-1431` → `portfolio` | docs(nb03): document 5-tier provider chain overlay (#1431) |
| 1449 | merged | `feat/nb04-08-authoritative-chain-overlay` → `portfolio` | docs(nb04-08): 5-tier provider chain overlay across NB04-NB08 (#1432 #1433 #1434 #1435 #1436) |
| 1450 | merged | `feat/nb01-portfolio-yfinance-gh-1437` → `portfolio` | docs(nb01-yfinance): Track B free-only NB01 (#1437) |
| 1451 | merged | `feat/nb02-portfolio-yfinance-gh-1438` → `portfolio` | docs(nb02-yfinance): Track B free-only NB02 single-name deep dive (#1438) |
| 1452 | merged | `feat/nb03-portfolio-yfinance-gh-1439` → `portfolio` | docs(nb03-yfinance): Track B free-only NB03 basket x-ray + risk (#1439) |
| 1453 | merged | `feat/nb04-portfolio-yfinance-gh-1440` → `portfolio` | docs(nb04-yfinance): Track B free-only NB04 events + smart money (#1440) |
| 1454 | merged | `feat/nb05-portfolio-yfinance-gh-1441` → `portfolio` | docs(nb05-yfinance): Track B free-only NB05 what-if + Brinson + paper (#1441) |
| 1455 | merged | `feat/nb06-portfolio-yfinance-gh-1442` → `portfolio` | docs(nb06-yfinance): Track B free-only NB06 backtest + validation (#1442) |
| 1456 | merged | `feat/nb07-portfolio-yfinance-gh-1443` → `portfolio` | docs(nb07-yfinance): Track B free-only NB07 offline + end-to-end (#1443) |
| 1457 | merged | `feat/nb08-portfolio-yfinance-gh-1444` → `portfolio` | docs(nb08-yfinance): Track B free-only NB08 analyst basket + Variant B (#1444) — FINAL Track B |
| 1458 | merged | `portfolio_validations` → `portfolio` | docs+scripts: validation-branch snapshot (docs, FMP coverage helpers, PI migration) |
| 1462 | merged | `portfolio_validations` → `portfolio` | validation iter 1: linkify notebook refs, wire N-PORT tier, redact NB01 PII (#1459 #1460 #1461) |
| 1608 | merged | `fix/dividend-date-coerce-gh-1389` → `portfolio` | fix(fmp_cached): coerce date to ISO string in dividend sub-fetch (#1389) |
| 1609 | merged | `fix/institutional-null-percent-gh-1390` → `portfolio` | fix(fmp_cached): tolerate null derived-percent in institutional_ownership (#1390) |
| 1610 | merged | `fix/phase-quality-bugs-iter3` → `portfolio` | fix(analysis): phase-quality bugs + FMP tier marker rule (#1463 #1464 #1465) |
| 1611 | merged | `feat/fmp-analyst-domain-iter4` → `portfolio` | feat(fmp): analyst/ratings/grades domain — 6-fetcher Tier-A parity port (#1482-#1487) |
| 1612 | merged | `feat/fmp-statements-domain-iter5` → `portfolio` | feat(fmp): port statements-extras 12 endpoints (#1488-#1499) |
| 1613 | merged | `feat/fmp-quotes-domain-iter6` → `portfolio` | feat(fmp): port quotes-extras 9 endpoints (#1506-#1514) |
| 1614 | merged | `feat/fmp-indexes-domain-iter7` → `portfolio` | feat(fmp): port indexes-extras 14 endpoints (#1515-#1528) |
| 1615 | merged | `feat/fmp-economics-domain-iter8` → `portfolio` | feat(fmp): port economics-extras 5 endpoints (#1529-#1533) |
| 1616 | merged | `feat/fmp-fundraising-domain-iter9` → `portfolio` | feat(fmp): port fundraising-extras 10 endpoints (#1534-#1543) |
| 1617 | merged | `feat/fmp-news-domain-iter10` → `portfolio` | feat(fmp): port news-extras 5 endpoints (#1544-#1548) |
| 1618 | merged | `feat/fmp-sec-domain-iter11` → `portfolio` | feat(fmp): port sec-extras 5 endpoints (#1549-#1553) |
| 1619 | merged | `feat/fmp-government-domain-iter12` → `portfolio` | feat(fmp): port government-extras 6 endpoints (#1554-#1559) |
| 1620 | merged | `feat/fmp-dcf-reference-domains-iter13` → `portfolio` | feat(fmp): port DCF + reference-list 11 endpoints (#1560-#1570) |
| 1621 | merged | `feat/fmp-market-hours-search-domains-iter14` → `portfolio` | feat(fmp): port market-hours + search 13 endpoints (#1571-#1572, #1467-#1477) |
| 1622 | merged | `feat/fmp-available-lists-iter15` → `portfolio` | feat(fmp): port available-lists 3 endpoints (#1478-#1480) — completes A-parity |
| 1623 | merged | `feat/fmp-company-domain-iter16` → `portfolio` | feat(fmp): port company-extras 6 endpoints (#1500-#1505) — completes A-parity |
| 1624 | merged | `feat/fmp-e2e-integration-suites-iter17` → `portfolio` | test(fmp): add 105-endpoint live E2E integration suite (#1573-#1591) |
| 1627 | merged | `portfolio_validations` → `portfolio` | notebooks(nb03): portfolio construction - target bands + concentration caps + coverage guard (#1626) |
| 1630 | merged | `chore/reconcile-tools-gh-1628` → `portfolio` | chore(tools): reconcile Tools/ into openbb_platform/tools/portfolio_utils/ (closes #1628) |
| 1631 | merged | `chore/delete-portfolio-app-gh-1629` → `portfolio` | chore(portfolio_app): delete standalone service — standardize on importer+notebooks (closes #1629) |
| 1690 | merged | `chore/move-techtrade-notebooks-gh-1679` → `portfolio` | chore(notebooks): move 6 techtrade notebooks into notebooks/techtrade/ (closes #1679) |
| 1703 | merged | `feat/pi-widgets/candlestick-toggle-gh-1702` → `portfolio` | feat(pi/widgets): add candlestick chart type + line/candle toggle (closes #1702) |
| 1704 | merged | `feat/pi-terminal-f0-shell-gh-1635` → `portfolio` | feat(pi/terminal): F0 shell — 11-tab terminal app + charset fix + X-Ray pie mapping |
| 1705 | merged | `fix/pi-terminal-apps-json-gh-1635` → `portfolio` | fix(pi/terminal): ship apps.json terminal entry that F0 tests require (#1635, #1636) |
| 1706 | merged | `feat/pi-terminal-t0-context-bars-gh-1638` → `portfolio` | feat(pi/terminal): T0.3-T0.6 context bars + default layout + smoke test (#1638-#1641) |
| 1707 | merged | `feat/pi-f1-overview-batch-a-gh-1642` → `portfolio` | feat(pi/terminal): F1 Batch A — EXTEND header + key_stats + Overview REUSE (#1643-#1651) |
| 1708 | merged | `feat/pi-f1-overview-batch-b-gh-1642` → `portfolio` | feat(pi/terminal): F1 Batch B — 4 BUILD widgets over fmp_cached (#1645, #1648, #1649, #1650) |
| 1709 | merged | `feat/pi-tier1-f5-f6-f7-gh-1658` → `portfolio` | feat(pi/terminal): Tier 1 — F5 Ownership + F6 Calendar + F7 Estimates (9 widgets) |
| 1710 | merged | `feat/pi-tier2-f2-f3-f4-f8-gh-1652` → `portfolio` | feat(pi/terminal): F2 Financials + F3 Technicals + F4 Comparison + F8 X-Ray (#1653, #1655, #1657, #1671) |
| 1711 | merged | `feat/pi-f9-f10-f11-tab-layouts-gh-1672` → `portfolio` | feat(pi/terminal): F9 Risk + F10 Paper + F11 Alerts tab layouts (#1673, #1675, #1677) |
| 1712 | merged | `feat/tt-t13-1-morning-scan-gh-1692` → `portfolio` | feat(pi/terminal): Techtrade Morning Scan tab (T13.1, #1692) |
| 1717 | merged | `feat/pi-f12-portfolio-workflow-gh-1678` → `portfolio` | feat(pi/terminal): F12 Portfolio-management workflow (Approach C, 5 sub-tasks) |
| 1718 | merged | `feat/tt-t13-2-position-workbench-gh-1696` → `portfolio` | feat(pi/terminal): Techtrade Position Workbench T13.2 (#1696) |
| 1720 | merged | `feat/tt-t13-3-through-7-gh-1691` → `portfolio` | feat(pi/terminal): Techtrade T13.3-T13.7 close-out (#1697-#1701) |
| 1730 | merged | `feat/browser-harness-b0-b4-gh-1721` → `portfolio` | feat(browser-harness): B0-B4 package + standalone driver + both stories (EPIC #1721) |
| 1731 | merged | `feat/browser-harness-b4-b5-b6-gh-1721` → `portfolio` | feat(browser-harness): B4 fixtures + B5 guide generator + B6 workspace driver (EPIC #1721) |
| 1732 | closed | `feat/browser-harness-b7-gh-1729` → `feat/browser-harness-b4-b5-b6-gh-1721` | ci(browser-harness): B7 GitHub Actions workflow — closes EPIC #1721 and #1713 |
| 1736 | closed | `feat/browser-harness-b8-widget-completeness-gh-1733` → `feat/browser-harness-b7-gh-1729` | feat(browser-harness): B8 widget-completeness sweep — 100% coverage (EPIC #1721) |
| 1737 | closed | `feat/browser-harness-b9-invariant-sweep-gh-1734` → `feat/browser-harness-b8-widget-completeness-gh-1733` | feat(browser-harness): B9 deep invariant sweep — XSS + enum + range guards (EPIC #1721) |
| 1738 | closed | `feat/browser-harness-b10-selector-graph-gh-1735` → `feat/browser-harness-b9-invariant-sweep-gh-1734` | feat(browser-harness): B10 workspace selector graph — real UI-render assertions (EPIC #1721) |
| 1739 | merged | `feat/browser-harness-b7-gh-1729` → `portfolio` | feat(browser-harness): B7 CI workflow (EPIC #1721) |
| 1740 | merged | `feat/browser-harness-b8-widget-completeness-gh-1733` → `portfolio` | feat(browser-harness): B8 widget-completeness sweep — 100% coverage (EPIC #1721) |
| 1741 | merged | `feat/browser-harness-b9-invariant-sweep-gh-1734` → `portfolio` | feat(browser-harness): B9 deep invariant sweep — XSS + enum + range guards (EPIC #1721) |
| 1742 | merged | `feat/browser-harness-b10-selector-graph-gh-1735` → `portfolio` | feat(browser-harness): B10 workspace selector graph — real UI-render assertions (EPIC #1721) |
| 1743 | merged | `fix/portfolio-intel-news-timeline-now-seam-gh-1716` → `portfolio` | fix(portfolio-intel): inject _now() seam so news_timeline days_back respects pinned test time (#1716) |
| 1745 | merged | `feat/portfolio-intel-provider-chain-gh-1715` → `portfolio` | feat(portfolio-intel): real 5-tier provider fallback chain machinery (#1715) |
| 1746 | merged | `feat/portfolio-intel-retrofit-non-basket-gh-1715` → `portfolio` | feat(portfolio-intel): Phase 2A retrofit — 24 non-basket endpoints route through ChainedFetcher (#1715) |
| 1747 | merged | `feat/portfolio-intel-mysql-positions-store-gh-1744` → `portfolio` | feat(portfolio-intel): MySQL positions store (canonical) + PortfolioStore Protocol (#1744) |
| 1748 | merged | `feat/portfolio-intel-phase-2b-basket-consumers-gh-1714` → `portfolio` | feat(portfolio-intel): Phase 2B — 16 basket-consuming endpoints + basket resolver (#1714 + #1715) |
| 1749 | merged | `feat/pi-techtrade/t5-order-sink-gh-1719` → `portfolio` | feat(techtrade): T5 OrderSink Protocol + PaperOrderSink (P1) (#1719) |
| 1752 | merged | `feat/pi-techtrade/t5-xlsx-sheets-gh-1719-p2` → `portfolio` | feat(techtrade): T5 XLSX 6-sheet workbook + charts (P2) (#1719) |
| 1755 | merged | `feat/pi-techtrade/t5-paper-engine-gh-1719-p3a` → `portfolio` | feat(techtrade): T5 paper trading engine (P3.a) (#1719) |
| 1757 | merged | `docs/pi-techtrade-t5-test-guide-gh-1719` → `portfolio` | docs(techtrade): T5 E2E test guide + Fidelity CSV schema (#1719) |
| 1763 | merged | `feat/pi-techtrade/nb07-t5-orderbatch-xlsx-gh-1759` → `portfolio` | docs(techtrade): NB-07 T5 OrderBatch + XLSX workbook walkthrough (#1759) |
| 1764 | merged | `feat/pi-techtrade/nb08-t5-paper-engine-gh-1760` → `portfolio` | docs(techtrade): NB-08 T5 paper trading engine walkthrough (#1760) |
| 1765 | merged | `feat/pi-techtrade/nb09-t5-e2e-plan-to-fills-gh-1761` → `portfolio` | docs(techtrade): NB-09 T5 end-to-end plan → XLSX → fills flow (#1761) |
| 1771 | merged | `feat/pi-techtrade/t5-p3b-unrealized-pl-gh-1766` → `portfolio` | feat(techtrade): T5 P3.b unrealized P&L (#1766) |
| 1773 | merged | `feat/pi-techtrade/t5-p3c-reconciliation-gh-1767` → `portfolio` | feat(techtrade): T5 P3.c reconciliation vs. Fidelity positions (#1767) |
| 1775 | merged | `feat/pi-techtrade/t5-p5-activity-csv-parser-gh-1769` → `portfolio` | feat(techtrade): T5 P5 Activity CSV parser + bulk-import (#1769) |
| 1778 | merged | `feat/pi-techtrade/t5-p4-widget-rewrite-gh-1768` → `portfolio` | feat(portfolio-intel): T5 P4 widget backend endpoints (#1768) |
| 1781 | merged | `feat/pi-techtrade/notebook-smoke-test-gh-1762` → `portfolio` | test(techtrade): notebook smoke test (#1762) |
| 1783 | merged | `feat/pi-techtrade/ingest-header-alignment-gh-1753` → `portfolio` | feat(portfolio-intel): Fidelity Positions CSV old + current header alignment (#1753) |
| 1785 | merged | `feat/pi-techtrade/execute-widget-frontend-gh-1777` → `portfolio` | feat(portfolio-intel): T5 widget frontend rewrite (#1777) |
| 1787 | merged | `fix/pi-portfolio-backend-run-gh-1786` → `portfolio` | fix(portfolio): run script + self-signed cert bootstrap for Workspace backend (#1786) |
| 1791 | merged | `fix/pi-portfolio-intel-obbject-openapi-gh-1788` → `portfolio` | fix(portfolio-intel): resolve OBBject response_model forward ref for openapi (#1788) |
| 1793 | merged | `feat/pi-techtrade/mysql-paper-engine-gh-1790` → `portfolio` | feat(techtrade): T5 paper engine MySQL backend + isolation columns (#1790) |
| 1795 | merged | `feat/pi-copilot-proxy-gh-1794` → `portfolio` | feat(portfolio-intel): local custom-copilot backend fronting copilot-api proxy (#1794) |
| 1797 | merged | `feat/pi-stock-analysis-msft-default-gh-1796` → `portfolio` | feat(portfolio-intel): default stock_analysis tab symbol to MSFT (#1796) |
| 1802 | merged | `feat/pi-local-viewer-gh-1798` → `portfolio` | feat(portfolio): local Workspace viewer — offline dashboard + copilot chat (#1798) |
| 1803 | closed | `copilot/create-vs-code-extension-spec` → `portfolio` | docs(specs): add VS Code Trading Terminal Extension PRD |
| 1841 | merged | `feat/pi-self-hosted-viewer-gh-1805` → `portfolio` | feat(portfolio): render chart/markdown/metric + multi-app switcher in local viewer (#1805) |
| 1842 | merged | `docs/pi-specs/vscode-terminal-prd-gh-1804` → `portfolio` | docs(specs): VS Code Trading Terminal Extension PRD + plan tree (#1804) |
| 1843 | merged | `docs/pi-specs/adr-vscode-rendering-gh-1810` → `portfolio` | docs(adr): Path A widgets.json renderer vs Path B bespoke React components (#1810) |
| 1844 | merged | `docs/pi-specs/adr-vscode-backend-gh-1808` → `portfolio` | docs(adr): canonical backend spawn + readiness endpoint for VS Code terminal (#1808) |
| 1845 | merged | `chore/pi-specs/widget-matrix-generator-gh-1811` → `portfolio` | chore(scripts): widget-registry drift guard for VS Code terminal PRD (#1811) |
| 1846 | merged | `chore/pi-claim/resync-project-items-2026-08-04` → `portfolio` | chore(pi-claim): re-sync pi_project_items.json (121 new Project #4 items) |
| 1847 | merged | `docs/pi-specs/adr-vscode-webview-auth-gh-1809` → `portfolio` | docs(adr): VS Code terminal webview auth — no token, loopback primary (#1809) |
| 1848 | merged | `feat/pi-vscode-terminal/scaffold-gh-1813` → `portfolio` | feat(vscode-terminal): scaffold apps/vscode-terminal-extension/ package + activation (#1813) |
| 1849 | merged | `feat/pi-vscode-terminal/webview-host-gh-1814` → `portfolio` | feat(vscode-terminal): webview host + postMessage bridge (#1814) |
| 1850 | merged | `feat/pi-vscode-terminal/fixture-layouts-gh-1816` → `portfolio` | feat(vscode-terminal): fixture-mode layouts + Path-A renderer (#1816) |
| 1851 | merged | `feat/pi-vscode-terminal/theme-bridge-gh-1815` → `portfolio` | feat(vscode-terminal): VS Code theme token bridge (dark theme first) (#1815) |
| 1852 | merged | `feat/pi-vscode-terminal/csp-hardening-gh-1817` → `portfolio` | feat(vscode-terminal): CSP hardening + auth invariant guards (#1817) |
| 1853 | closed | `feat/pi-vscode-terminal/command-palette-gh-1822` → `portfolio` | feat(vscode-terminal): command palette + default keybindings (#1822) |
| 1854 | merged | `feat/pi-vscode-terminal/symbol-context-gh-1823` → `portfolio` | feat(vscode-terminal): symbol context v1 + validator (#1823) |
| 1855 | merged | `feat/pi-vscode-terminal/backend-lifecycle-gh-1819` → `portfolio` | feat(vscode-terminal): backend lifecycle + status bar (#1819) |
| 1857 | merged | `feat/pi-vscode-terminal/command-palette-gh-1822-v2` → `portfolio` | feat(vscode-terminal): command palette + default keybindings (#1822) [restored] |
| 1858 | merged | `feat/pi-vscode-terminal/all-layouts-gh-1821` → `portfolio` | feat(vscode-terminal): complete built-in layout set — Portfolio Risk, Trading Desk, Chart Focus (#1821) |
| 1859 | merged | `feat/pi-vscode-terminal/live-data-mode-gh-1820` → `portfolio` | feat(vscode-terminal): live-data mode + widget fetcher (#1820) |
| 1860 | merged | `feat/pi-vscode-terminal/editor-selection-gh-1827` → `portfolio` | feat(vscode-terminal): editor selection ticker CodeAction (#1827) |
| 1861 | merged | `feat/pi-vscode-terminal/run-analysis-gh-1828` → `portfolio` | feat(vscode-terminal): openbb.runAnalysis command → 7-phase pipeline (#1828) |
| 1862 | merged | `feat/pi-vscode-terminal/notebook-watcher-gh-1826` → `portfolio` | feat(vscode-terminal): notebook symbol watcher — source-text heuristic (#1826) |
| 1863 | closed | `feat/pi-vscode-terminal/hover-provider-gh-1825` → `portfolio` | feat(vscode-terminal): symbol hover provider (Python + Notebook) (#1825) |
| 1864 | merged | `feat/pi-vscode-terminal/hover-provider-gh-1825-v2` → `portfolio` | feat(vscode-terminal): symbol hover provider (Python + Notebook) (#1825) [restored] |
| 1865 | merged | `portfolio_validations` → `portfolio` | docs(skills): add portfolio-validation workflow skill |
| 1866 | merged | `feat/pi-vscode-terminal/golden-layouts-gh-1833` → `portfolio` | feat(vscode-terminal): golden layouts library + load command (#1833) |
| 1867 | merged | `feat/pi-vscode-terminal/preview-widget-gh-1832` → `portfolio` | feat(vscode-terminal): openbb.previewWidget single-widget panel (#1832) |
| 1868 | closed | `feat/pi-vscode-terminal/widget-browser-gh-1830` → `portfolio` | feat(vscode-terminal): Widget Browser tree-view + drag support (#1830) |
| 1869 | closed | `feat/pi-vscode-terminal/layout-crud-gh-1831` → `portfolio` | feat(vscode-terminal): user-defined layouts CRUD + workspace export (#1831) |
| 1870 | merged | `feat/pi-vscode-terminal/widget-browser-gh-1830-v2` → `portfolio` | feat(vscode-terminal): Widget Browser tree-view + drag support (#1830) [restored] |
| 1873 | merged | `feat/pi-vscode-terminal/paper-hotkeys-gh-1835` → `portfolio` | feat(vscode-terminal): paper buy/sell command handlers (#1835) |
| 1874 | closed | `feat/pi-vscode-terminal/set-api-key-gh-1836` → `portfolio` | feat(vscode-terminal): guided setApiKey quick-pick + editor (#1836) |
| 1875 | closed | `feat/pi-vscode-terminal/auto-restart-gh-1838` → `portfolio` | feat(vscode-terminal): backend auto-restart controller + auto-start config (#1838) |
| 1876 | closed | `feat/pi-vscode-terminal/layout-crud-gh-1831-fresh` → `portfolio` | feat(vscode-terminal): user-defined layouts CRUD + workspace export (#1831) [fresh] |
| 1877 | merged | `feat/pi-vscode-terminal/theme-parity-gh-1837` → `portfolio` | feat(vscode-terminal): light + high-contrast theme parity + audit (#1837) |
| 1878 | merged | `portfolio_validations` → `portfolio` | fix(portfolio-viewer): provider_health async (#1871) + copilot chat + chart/param + OpenBB-Workspace layout |
| 1879 | merged | `feat/pi-vscode-terminal/perf-gate-gh-1839` → `portfolio` | feat(vscode-terminal): performance NFR gate + budget harness (#1839) |
| 1880 | closed | `feat/pi-vscode-terminal/testing-strategy-gh-1840` → `portfolio` | feat(vscode-terminal): testing strategy scaffold — 4 test tiers + QA matrix (#1840) |
| 1882 | merged | `feat/pi-vscode-terminal/testing-strategy-gh-1840-v2` → `portfolio` | feat(vscode-terminal): testing strategy scaffold — 4 test tiers + QA matrix (#1840) [restored] |
| 1883 | merged | `feat/pi-vscode-terminal/set-api-key-gh-1836-v2` → `portfolio` | feat(vscode-terminal): guided setApiKey quick-pick + editor (#1836) [restored] |
| 1884 | merged | `feat/pi-vscode-terminal/auto-restart-gh-1838-v2` → `portfolio` | feat(vscode-terminal): backend auto-restart controller + auto-start config (#1838) [restored] |
| 1889 | merged | `feat/pi-vscode-terminal/workspace-trust-gh-1856` → `portfolio` | feat(vscode-terminal): workspace-trust hardening + credential-file perms (#1856) |
| 1894 | merged | `feat/pi-vscode-terminal/layout-crud-gh-1831-take3` → `portfolio` | feat(vscode-terminal): user-defined layouts CRUD + workspace export (#1831) |
| 1895 | merged | `feat/pi-tools/playwright-workspace-mode-gh-1789` → `portfolio` | feat(browser-harness): Playwright workspace-mode driver + random-port isolation (#1789) |
| 1897 | merged | `docs/pi-vscode-terminal/user-guide-gh-1896` → `portfolio` | docs(vscode-terminal): user guide + refreshed README (#1896) |
| 1899 | closed | `feat/pi-wire-price-history-gh-1898` → `portfolio` | feat(portfolio-intel): wire pi_equity_price_history to live fmp_cached (#1898) |
| 1901 | closed | `feat/pi-wire-price-performance-gh-1900` → `feat/pi-wire-price-history-gh-1898` | feat(portfolio-intel): wire pi_price_performance to live fmp_cached (#1900) |
| 1903 | closed | `feat/pi-wire-management-team-gh-1902` → `feat/pi-wire-price-performance-gh-1900` | feat(portfolio-intel): wire pi_management_team to fmp_cached (#1902) |
| 1905 | closed | `feat/pi-wire-revenue-geography-gh-1904` → `feat/pi-wire-management-team-gh-1902` | feat(portfolio-intel): wire pi_revenue_geography to fmp_cached (#1904) |
| 1907 | closed | `feat/pi-wire-revenue-business-line-gh-1906` → `feat/pi-wire-revenue-geography-gh-1904` | feat(portfolio-intel): wire pi_revenue_business_line to fmp_cached (#1906) |
| 1909 | closed | `feat/pi-wire-dividend-payment-gh-1908` → `feat/pi-wire-revenue-business-line-gh-1906` | feat(portfolio-intel): wire pi_dividend_payment to fmp_cached (#1908) |
| 1911 | closed | `feat/pi-wire-insider-trading-gh-1910` → `feat/pi-wire-dividend-payment-gh-1908` | feat(portfolio-intel): wire pi_insider_trading to fmp_cached (#1910) |
| 1913 | closed | `feat/pi-wire-earnings-history-gh-1912` → `feat/pi-wire-insider-trading-gh-1910` | feat(pi): wire earnings-history widget to fmp_cached (#1912) |
| 1915 | closed | `feat/pi-wire-company-filings-gh-1914` → `feat/pi-wire-earnings-history-gh-1912` | feat(pi): wire company-filings widget to fmp_cached (#1914) |
| 1917 | closed | `feat/pi-wire-stock-splits-gh-1916` → `feat/pi-wire-company-filings-gh-1914` | feat(portfolio-intel): fully wire stock-splits widget to fmp_cached (#1916) |
| 1919 | closed | `feat/pi-wire-charting-gh-1918` → `feat/pi-wire-stock-splits-gh-1916` | feat(portfolio-intel): fully wire charting/technicals widget to fmp_cached (#1918) |
| 1921 | closed | `feat/pi-wire-statements-gh-1920` → `feat/pi-wire-charting-gh-1918` | feat(portfolio-intel): wire equity financials/statements widget to fmp_cached (#1920) |
| 1924 | closed | `feat/pi-wire-peer-multiples-gh-1923` → `feat/pi-wire-statements-gh-1920` | feat(portfolio-intel): wire equity peer-multiples/competitors widget to fmp_cached (#1923) |
| 1927 | closed | `feat/pi-wire-price-target-history-gh-1926` → `feat/pi-wire-peer-multiples-gh-1923` | feat(portfolio-intel): wire price-target-history widget to fmp_cached (#1926) |
| 1933 | closed | `feat/pi-wire-tt-engine-status-gh-1931` → `feat/pi-wire-price-target-history-gh-1926` | feat(portfolio-intel): wire tt_engine_status to observable engine state (#1931) |
| 1970 | merged | `docs/pi-asof-snapshot-spec-gh-1932` → `portfolio` | docs(pi): as-of EOD snapshot cache + techtrade/portfolio_intel alignment spec (#1932) |
| 1974 | merged | `feat/pi-techtrade-dep-gh-1971` → `portfolio` | build(portfolio-intel): declare openbb-techtrade dep (#1971) |
| 1977 | merged | `feat/pi-f2-financials-redesign-gh-1976` → `portfolio_validations` | feat(portfolio-intel): F2 Financials redesign — provider-health table + provenance strip (#1976) |
| 1979 | merged | `feat/pi-f2-financial-combo-chart-gh-1978` → `portfolio_validations` | feat(portfolio-viewer): dual-axis combo chart for F2 financial statements (#1978) |
| 1981 | merged | `feat/pi-viewer-bugcontext-widget-gh-1980` → `portfolio_validations` | feat(portfolio-viewer): embed Bug Context feedback widget in Local Workspace Viewer (#1980) |
| 1983 | merged | `fix/pi-viewer-combo-recolor-lwc-nulls-gh-1982` → `portfolio_validations` | fix(portfolio-viewer): recolor F2 combo chart + fix 'Value is null' LWC datetime/dup-day (#1982) |
| 1985 | merged | `feat/pi-f2-metric-help-gh-1984` → `portfolio_validations` | feat(portfolio): add F2 metric glossary help (#1984) |
| 2018 | merged | `feat/pi-terminal-terminology-audit-gh-1987` → `portfolio_validations` | feat(portfolio): standardize Terminal financial terminology and help (#1987) |
| 2020 | merged | `fix/pi-f2-pie-layout-gh-2019` → `portfolio_validations` | fix(portfolio): resolve Terminal UX feedback (#2019) |
| 2024 | merged | `fix/pi-known-noise-tests-gh-2023` → `portfolio_validations` | test(validation): absorb known-noise harness fixes (#2023) |
| 2026 | merged | `fix/pi-vscode-snapshot-line-endings-gh-2025` → `portfolio_validations` | fix(vscode-terminal): normalize snapshot line endings (#2025) |
| 2031 | merged | `fix/local-ci-post-merge-review-gh-2030` → `develop` | fix(ci): post-merge review corrections for local-CI harness (#2030) |
| 2032 | merged | `feat/top50-intraday-gh-1986` → `portfolio_validations` | feat(backtest): test top-50 S&P intraday drift theory (#1986) |
| 2034 | merged | `docs/validation-branch-hygiene-gh-2033` → `portfolio_validations` | docs(workflow): codify validation promotion and branch-hygiene process (#2033) |
| 2036 | merged | `docs/full-branch-hygiene-gh-2035` → `portfolio_validations` | docs(workflow): inventory all remaining branches (#2035) |
| 2040 | merged | `chore/pi-full-branch-hygiene-clean-gh-2038` → `portfolio_validations` | chore(hygiene): complete full branch cleanup (#2038) |
| 2043 | merged | `portfolio` → `portfolio_validations` | chore(portfolio): absorb latest portfolio change (#2042) |
| 2044 | merged | `portfolio_validations` → `portfolio` | chore(portfolio): promote validated integration state (#2042) |
| 2054 | merged | `feat/windows-service-host-gh-2047` → `feat/pi-jobs-service-gh-1934` | feat(service-host): add native process supervisor (#2047) |
| 2055 | merged | `feat/windows-service-integration-gh-2048` → `feat/pi-jobs-service-gh-1934` | feat(service-host): integrate OpenBB health and logging (#2048) |
| 2056 | merged | `feat/windows-service-deploy-gh-2049` → `feat/pi-jobs-service-gh-1934` | feat(service-host): add secure deployment lifecycle (#2049) |
| 2057 | merged | `feat/windows-service-verify-gh-2050` → `feat/pi-jobs-service-gh-1934` | docs(service-host): add Windows acceptance and operations (#2050) |
| 2058 | merged | `feat/techtrade-morning-scan-gh-1941` → `feat/pi-jobs-service-gh-1934` | feat(portfolio-intel): serve persisted Morning Scan (#1941) |
| 2060 | merged | `docs/jobs-operations-gh-1947` → `feat/pi-jobs-service-gh-1934` | docs(jobs): add operational wrappers and runbook (#1947) |
| 2061 | merged | `feat/pi-jobs-service-gh-1934` → `portfolio` | feat: add durable jobs and Windows service hosting (#1934) |
| 2062 | merged | `feat/pi-eod-snapshot-store-gh-1963` → `portfolio` | feat(techtrade): add EOD snapshot store foundation (#1963) |
| 2064 | merged | `feat/pi-eod-snapshot-store-gh-1963` → `portfolio` | fix(techtrade): harden snapshot schema verification (#2063) |
| 2066 | merged | `chore/gpt-sol-agent-policy` → `portfolio` | agents: require GPT-5.6 Sol execution |
| 2068 | merged | `fix/pi-snapshot-guard-gaps-gh-2067` → `portfolio` | fix(techtrade): close MySQL snapshot guard gaps (#2067) |
| 2069 | merged | `fix/pi-execution-foundation-gh-2059` → `portfolio` | fix(techtrade): honor shared PyMySQL pool contract (#2059) |
| 2070 | merged | `fix/pi-fmp-tooling-gh-2051` → `portfolio` | fix(fmp-cached): propagate warmer database overrides (#2051) |
| 2071 | merged | `feat/pi-config-packaging-gh-1972` → `portfolio` | feat(pi): centralize config and editable installs (#1972) |
| 2073 | merged | `fix/pi-key-stats-sources-gh-1959` → `portfolio` | fix(portfolio-intel): source missing key stats (#1959) |
| 2074 | merged | `fix/pi-risk-test-gh-2027` → `portfolio` | test(portfolio): make SPY concentration check resilient (#2027) |
| 2076 | merged | `feat/pi-live-execution-gh-1719` → `portfolio` | feat(techtrade): add safe paper/live execution gateway (#1719) |
| 2081 | merged | `fix/pi-techtrade-indicators-gh-2078` → `portfolio` | fix(techtrade): restore extended indicator fallbacks (#2078) |
| 2082 | merged | `fix/pi-provider-compat-gh-2079` → `portfolio` | fix(core): export generated provider models (#2079) |
| 2083 | merged | `feat/pi-snapshot-core-gh-1964` → `portfolio` | feat(techtrade): harden EOD snapshot core (#1964) |
| 2084 | merged | `fix/pi-snapshot-default-gh-2080` → `portfolio` | test(techtrade): isolate default snapshot path (#2080) |
| 2085 | merged | `fix/pi-key-stats-fallback-gh-2075` → `portfolio` | fix(portfolio-intel): clarify key-stats fallback (#2075) |
| 2087 | merged | `feat/pi-snapshot-consumers-gh-1968` → `portfolio` | feat(techtrade): ship EOD snapshot consumers (#1968) |
| 2089 | merged | `docs/local-llm-plan-gh-2088` → `portfolio` | feat(devex): add local LLM bootstrap preflight |
| 2090 | merged | `feat/local-llm-bootstrap-gh-2088` → `portfolio` | feat: bootstrap local Ollama development models |
| 2091 | merged | `docs/local-llm-guide-gh-2088` → `portfolio` | docs(devex): document native Ollama VS Code setup (#2088) |
| 2093 | merged | `chore/browser-harness-fixtures-gh-2092` → `portfolio` | chore(browser-harness): refresh fixture snapshots (#2092) |
| 2104 | merged | `chore/workspace-dev-foundation-gh-2097` → `portfolio` | chore: add Workspace development foundations |
| 2105 | merged | `build/workspace-dev-setup-gh-2098` → `portfolio` | build: add Workspace development setup preflight |
| 2106 | merged | `feat/workspace-intel-launcher-gh-2099` → `portfolio` | feat: add Portfolio Intelligence launcher |
| 2107 | merged | `docs/workspace-dev-runbook-gh-2100` → `portfolio` | docs: add Workspace local development runbook |
| 2109 | merged | `chore/self-hosted-workspace-source-gh-2108` → `portfolio` | chore(workspace): pin and audit self-host source |
| 2112 | merged | `feat/self-hosted-workspace-deploy-gh-2110` → `portfolio` | feat(workspace): deploy self-hosted development stack |
| 2113 | merged | `feat/workspace-replay-skill-gh-2111` → `portfolio` | feat(workspace): add durable local replay verifier |
| 2114 | merged | `test/self-hosted-workspace-browser-gh-2101` → `portfolio` | test(workspace): automate self-hosted browser login |
| 2116 | merged | `test/self-hosted-workspace-browser-gh-2101` → `portfolio` | fix(workspace): update source pin for on-prem shell |
| 2117 | merged | `test/workspace-connectors-gh-2101` → `portfolio` | test(workspace): validate self-hosted connectors and apps |
| 2118 | merged | `test/self-hosted-workspace-mcp-gh-2102` → `portfolio` | test(workspace): certify self-hosted MCP parity |
| 2119 | merged | `test/self-hosted-workspace-copilot-gh-2103` → `portfolio` | test(workspace): validate local Portfolio Copilot |
| 2121 | merged | `fix/workspace-bootstrap-privacy-gh-2120` → `portfolio` | fix(workspace): suppress admin bootstrap output |
| 2122 | merged | `feature/dual-mcp-launcher` → `portfolio` | feat(mcp): add hardened dual server launcher |
| 2236 | merged | `feat/mcp-capability-contracts-gh-2152` → `portfolio` | feat(mcp): add capability inventory contracts (#2152) |
| 2237 | merged | `fix/general-linting-tools-gh-2095` → `portfolio` | fix(ci): install repository lint toolchain (#2095) |
| 2238 | merged | `feat/mcp-capability-inventory-gh-2153` → `portfolio` | feat(mcp): add metadata capability inventory (#2153) |
| 2239 | merged | `feat/mcp-exposure-policy-gh-2154` → `portfolio` | feat(mcp): add reviewed exposure policy (#2154) |
| 2240 | merged | `feat/mcp-policy-enforcement-gh-2155` → `portfolio` | feat(mcp): enforce capability policy (#2155) |
| 2241 | merged | `feat/mcp-lineage-gh-2156` → `portfolio` | feat(mcp): add reproducible Portfolio lineage (#2156) |
| 2243 | merged | `feat/mcp-traceability-gh-2157` → `portfolio` | feat(mcp): add capability work traceability (#2157) |
| 2244 | merged | `feat/mcp-runtime-profiles-gh-2158` → `portfolio` | feat(mcp): add runtime profile manifests |
| 2246 | merged | `feat/mcp-provenance-gh-2159` → `portfolio` | feat(mcp): verify clean runtime provenance (#2159) |
| 2247 | merged | `feat/mcp-launcher-profiles-gh-2160` → `portfolio` | feat(mcp): select launcher runtime profiles (#2160) |
| 2248 | merged | `feat/mcp-readiness-gh-2161` → `portfolio` | feat(mcp): verify effective readiness contract (#2161) |
| 2249 | merged | `feat/fmp-router-gh-2162` → `portfolio` | feat(fmp-cached): add typed StockList route (#2162) |
| 2250 | merged | `feat/fmp-reference-gh-2163` → `portfolio` | feat(fmp-cached): route reference data batch (#2163) |
| 2251 | merged | `feat/fmp-search-gh-2164` → `portfolio` | feat(fmp-cached): route search and history references (#2164) |
| 2252 | merged | `feat/fmp-quotes-gh-2165` → `portfolio` | feat(fmp-cached): route quote and market extras (#2165) |
| 2253 | merged | `feat/fmp-intraday-gh-2166` → `portfolio` | feat(fmp-cached): route intraday and session extras (#2166) |
| 2254 | merged | `feat/fmp-analyst-gh-2167` → `portfolio` | feat(fmp-cached): route analyst and market performance (#2167) |
| 2255 | merged | `feat/fmp-statements-gh-2168` → `portfolio` | feat(fmp-cached): route statement extras (#2168) |
| 2256 | merged | `feat/fmp-corporate-gh-2169` → `portfolio` | feat(fmp-cached): route corporate and SEC extras (#2169) |
| 2257 | merged | `feat/fmp-government-gh-2170` → `portfolio` | feat(fmp-cached): route government and news extras (#2170) |
| 2258 | merged | `test/fmp-regression-gh-2171` → `portfolio` | test(mcp): prove complete FMP Cached routing |
| 2259 | merged | `feat/portfolio-adapter-gh-2172` → `portfolio` | feat(mcp): compose Portfolio business routes (#2172) |
| 2260 | merged | `test/portfolio-boundaries-gh-2173` → `portfolio` | feat(mcp): enforce Portfolio data boundaries (#2173) |
| 2261 | merged | `test/intelligence-dispositions-gh-2174` → `portfolio` | test(mcp): map Intelligence operation effects (#2174) |
| 2262 | merged | `feat/intelligence-adapter-gh-2175` → `portfolio` | feat(mcp): bridge reviewed Intelligence routes (#2175) |
| 2263 | merged | `test/analytics-profiles-gh-2176` → `portfolio` | test(mcp): lock analytical profile contracts (#2176) |
| 2264 | merged | `fix/financialtoolkit-router-gh-2177` → `portfolio` | feat(mcp): reconcile FinancialToolkit routers (#2177) |
| 2265 | merged | `feat/cache-observability-gh-2178` → `portfolio` | feat(mcp): expose sanitized cache observability (#2178) |
| 2266 | merged | `test/persistence-contract-gh-2179` → `portfolio` | test(fmp-cached): verify persistence contracts (#2179) |
| 2267 | merged | `feat/cache-jobs-gh-2180` → `portfolio` | feat(mcp): expose allowlisted cache jobs (#2180) |
| 2268 | merged | `test/maintenance-isolation-gh-2181` → `portfolio` | test(mcp): prove maintenance isolation recovery (#2181) |
| 2269 | merged | `feat/daytrade-mcp-gh-386` → `portfolio` | feat(daytrade): register read-only MCP handlers (#386) |
| 2270 | merged | `test/daytrade-stdio-gh-2182` → `portfolio` | test(daytrade): verify real MCP stdio transport (#2182) |
| 2271 | merged | `docs/agents-scope-gh-2183` → `portfolio` | docs(agents): align MCP scope and schemas (#2183) |
| 2272 | merged | `test/agents-stdio-gh-2184` → `portfolio` | test(agents): validate sanitized MCP stdio (#2184) |
| 2273 | merged | `feat/prompt-dependencies-gh-2185` → `portfolio` | feat(mcp): add structured prompt readiness (#2185) |
| 2274 | merged | `fix/prompt-corrections-gh-2186` → `portfolio` | fix(mcp): correct portfolio prompt contracts |
| 2275 | merged | `feat/unified-capability-resource-gh-2187` → `portfolio` | feat(mcp): publish unified capability resource |
| 2276 | merged | `docs/portfolio-mcp-runbook-gh-2188` → `portfolio` | docs(mcp): add Portfolio operator runbook |
| 2277 | merged | `test/profile-protocol-matrix-gh-2189` → `portfolio` | test(mcp): add real profile protocol matrix |
| 2278 | merged | `ci/portfolio-mcp-drift-gh-2190` → `portfolio` | ci(mcp): guard Portfolio capability drift |
| 2279 | merged | `ci/mcp-runtime-replay-gh-2191` → `portfolio` | ci(mcp): certify clean runtime replay |
| 2280 | merged | `test/workspace-parity-gh-2192` → `portfolio` | test(mcp): revalidate Workspace parity |
| 2281 | merged | `test/operator-fixtures-gh-2193` → `portfolio` | test(mcp): validate controlled operator workflows |
| 2283 | merged | `feat/dual-mcp-lock-gh-2245` → `portfolio` | build(mcp): lock dual-MCP transitive dependency graphs (#2245) |
| 2285 | merged | `docs/pause-handoff-gh-2284` → `portfolio` | docs(handoff): record Portfolio pause state and resume plan (#2284) |
| 2286 | merged | `fix/retire-beads-hooks-gh-2235` → `portfolio` | fix(dev-env): retire Beads Git hooks from Portfolio checkouts (#2235) |
| 2287 | merged | `fix/auto-close-pr-body-gh-1975` → `portfolio` | fix(ci): auto-close issues cited in merged PR bodies (#1975) |
| 2288 | merged | `fix/url-fetch-ssrf-gh-2242` → `portfolio` | fix(security): harden caller-controlled document URL fetchers (#2242) |
| 2289 | merged | `feat/mcp-lock-hashes-gh-2282` → `portfolio` | build(mcp): enforce dependency-lock artifact hashes at dual-MCP launch (#2282) |
| 2291 | merged | `fix/retire-beads-stub-copy-gh-2235` → `portfolio` | fix(dev-env): never copy retired Beads stubs into .git/hooks (#2235) |
| 2293 | merged | `fix/auto-close-concurrency-gh-2292` → `portfolio` | fix(ci): stop auto-close runs cancelling each other on fast merges (#2292) |
| 2294 | merged | `feat/admit-url-fetchers-gh-2290` → `portfolio` | feat(mcp): admit SSRF-hardened document URL fetchers to MCP profiles (#2290) |
| 2295 | merged | `fix/harness-live-fixtures-gh-2094` → `portfolio` | test(harness): stop diffing live-served Equity Profile fixtures (#2094) |
| 2297 | merged | `docs/program-plan-docs-gh-2296` → `portfolio` | docs(program): check in MCP-parity and Notebook Companion plan documents (#2296) |
| 2299 | merged | `fix/inventory-persistence-gh-2298` → `portfolio` | fix(mcp): classify fmp_cached persistence from the reviewed descriptor (#2298) |
| 2301 | merged | `fix/prompt-tool-names-gh-2300` → `portfolio` | fix(mcp): bundled prompts require only tools and providers that exist (#2300) |
| 2303 | merged | `test/legacy-fmp-invocation-gh-2302` → `portfolio` | test(mcp): invoke the 70 legacy FMP Cached mappings through MCP (#2302) |
| 2304 | merged | `release/mcp-parity-gh-2194-r2` → `portfolio` | release(mcp): parity release record, metadata probe and rollback proof (#2194) |
| 2305 | merged | `feat/notebook-inventory-gh-2211` → `portfolio` | feat(notebook-agent): source-only notebook story inventory and drift check (#2211) |
| 2306 | closed | `feat/notebook-manifests-gh-2212` → `feat/notebook-inventory-gh-2211` | feat(notebook-agent): typed story manifests, stage graphs and capability catalog (#2212) |
| 2307 | merged | `feat/notebook-manifests-gh-2212` → `portfolio` | feat(notebook-agent): typed story manifests, stage graphs and capability catalog (#2212) |
| 2309 | merged | `docs/resume-state-gh-2308` → `portfolio` | docs(handoff): record 2026-10-27 Portfolio session state and resume plan (#2308) |
| 2310 | merged | `feat/notebook-readiness-gh-2214` → `portfolio` | feat(notebook-agent): story readiness against server-qualified capabilities (#2214) |
| 2311 | merged | `test/notebook-scenarios-gh-2213` → `portfolio` | test(notebook-agent): frozen synthetic scenarios and independent parity oracles (#2213) |
| 2312 | merged | `feat/notebook-registry-gh-2216` → `portfolio` | feat(notebook-agent): story catalog, run registry and typed run state (#2216) |
| 2317 | merged | `feat/basket-analytics-gh-2313` → `portfolio` | feat(notebook-agent): basket look-through, sector view and concentration over MCP (#2313) |
| 2318 | merged | `feat/single-name-analysis-gh-2314` → `portfolio` | feat(notebook-agent): seven-phase single-name analysis over MCP (#2314) |
| 2319 | merged | `feat/attribution-whatif-gh-2315` → `portfolio` | feat(notebook-agent): Brinson attribution, what-if diff and candidate trades over MCP (#2315) |
| 2320 | merged | `feat/techtrade-analytics-gh-2316` → `portfolio` | feat(notebook-agent): TechTrade story analytics over MCP (#2316) |
| 2322 | merged | `feat/story-binding-review-gh-2321` → `portfolio` | feat(notebook-agent): drain N05 and bind run state to the N06 tools (#2321) |
| 2324 | merged | `docs/n05-resume-state-gh-2323` → `portfolio` | docs(handoff): record N05 completion and Notebook Companion resume state (#2323) |
| 2325 | merged | `feat/notebook-artifacts-gh-2217` → `portfolio` | feat(notebook-agent): bounded, run-scoped story artifacts over MCP (#2217) |
| 2327 | merged | `docs/n07-record-gh-2326` → `portfolio` | docs(handoff): record N07 completion and Notebook Companion resume state (#2326) |
| 2328 | merged | `feat/notebook-jobs-gh-2218` → `portfolio` | feat(notebook-agent): story jobs on the durable jobs service (#2218) |
| 2330 | merged | `docs/n08-record-gh-2329` → `portfolio` | docs(handoff): record N08 completion and Notebook Companion resume state (#2329) |
| 2335 | merged | `feat/notebook-paper-gate-gh-2331` → `portfolio` | feat(notebook-agent): human-approved paper actions in isolated sandboxes (#2331) |
| 2336 | merged | `feat/notebook-paper-batch-gh-2332` → `portfolio` | feat(notebook-agent): TechTrade order batches and paper-sink artifacts over MCP (#2332) |
| 2337 | merged | `feat/notebook-paper-blotter-gh-2333` → `portfolio` | feat(notebook-agent): Portfolio paper blotter and low-buying-power alert in a durable sandbox (#2333) |
