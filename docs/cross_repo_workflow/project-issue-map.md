# MCP and notebook-agent GitHub work map

**Read-back verified (UTC):** `2026-10-04T05:52:02.059259+00:00`  
**Repository:** `rashmijain02/OpenBB`  
**Project:** [Portfolio Intelligence Engine #4, Board](https://github.com/users/rashmijain02/projects/1/views/1)  
**Integration target:** `portfolio`

## Result

- **113 logical items:** 112 newly created issues and one reused existing issue.
- **15 epics:** two program roots and 13 delivery epics; **30 features**; **68 tasks**.
- Base MCP program: 73 items (44 tasks); notebook-agent program: 40 items (24 tasks).
- Every item is in Project 1 with Status **Todo**, and the planned Type, Phase and Lane.
- All newly created issues are unassigned and carry program, area, type and priority labels.
- Native sub-issue parents and blocking relationships were read back from GitHub.
- Every notebook implementation task is directly blocked by the base MCP release task.
- Issue creation is not implementation, acceptance, deployment or permission for live data/trading.

## Program entry points

- [Base MCP capability parity - #725](https://github.com/rashmijain02/OpenBB/issues/725)
- [Python Notebook MCP Companion - #210](https://github.com/rashmijain02/OpenBB/issues/210)
- [Prerequisite base MCP release gate - #1257](https://github.com/rashmijain02/OpenBB/issues/1257)
- [Final notebook-agent release gate - #237](https://github.com/rashmijain02/OpenBB/issues/237)

## Preserved existing work

MCP:T31 reuses [#241 (Daytrade MCP tool server)](https://github.com/rashmijain02/OpenBB/issues/241).
Its original body, labels, assignees and unparented domain ownership were preserved.
A scoped planning comment and Project membership were added. F6.1 cross-links it
and is natively blocked by it; it was not silently reparented into the new hierarchy.
The map's parent for that row is a **logical planning relationship**, not a native parent.
Its pre-existing priority labels are retained; new Project fields follow this plan.

## Document authority

- [Base MCP plan](../superpowers/plans/2026-10-03-portfolio-mcp-capability-parity.md)
- [Notebook-agent plan](../superpowers/plans/2026-10-03-notebook-mcp-agent.md)
- [Notebook requirements](../Specs/notebook-mcp-agent/requirements.md)
- [Notebook engineering design](../designs/notebook-mcp-agent-design.md)
- [Notebook source coverage](notebook-mcp-story-coverage.md)
- [Machine-readable issue map](project-issue-map.json)

Issue bodies include standalone task contracts and acceptance criteria because
these local documents have not been committed/pushed by this planning work.
The JSON map records source-plan hashes and verification scope. Counts describe
this program set, not all pre-existing items in the project.

## Complete hierarchy

### Base MCP program

| Plan ID | Type | Issue | Parent / relationship | Blocking plan IDs |
| --- | --- | --- | --- | --- |
| MCP:ROOT | Epic | [#2123 - [mcp-parity][PROGRAM] Portfolio capability coverage and trusted MCP delivery](https://github.com/rashmijain02/OpenBB/issues/725) | Program root | None |
| MCP:E1 | Epic | [#2124 - [mcp-parity][E1] Capability inventory and exposure policy](https://github.com/rashmijain02/OpenBB/issues/1166) | MCP:ROOT | None |
| MCP:E2 | Epic | [#2125 - [mcp-parity][E2] Reproducible Portfolio runtime profiles](https://github.com/rashmijain02/OpenBB/issues/1167) | MCP:ROOT | None |
| MCP:E3 | Epic | [#2126 - [mcp-parity][E3] FMP Cached model-to-command parity](https://github.com/rashmijain02/OpenBB/issues/1168) | MCP:ROOT | None |
| MCP:E4 | Epic | [#2127 - [mcp-parity][E4] Portfolio and Intelligence application parity](https://github.com/rashmijain02/OpenBB/issues/1169) | MCP:ROOT | None |
| MCP:E5 | Epic | [#2128 - [mcp-parity][E5] Cache observability and controlled operations](https://github.com/rashmijain02/OpenBB/issues/1170) | MCP:ROOT | None |
| MCP:E6 | Epic | [#2129 - [mcp-parity][E6] Specialist MCP correctness](https://github.com/rashmijain02/OpenBB/issues/1171) | MCP:ROOT | None |
| MCP:E7 | Epic | [#2130 - [mcp-parity][E7] Truthful prompts, client configuration, and unified discovery](https://github.com/rashmijain02/OpenBB/issues/1172) | MCP:ROOT | None |
| MCP:E8 | Epic | [#2131 - [mcp-parity][E8] CI, live acceptance, and release rollout](https://github.com/rashmijain02/OpenBB/issues/1173) | MCP:ROOT | None |
| MCP:F1.1 | Feature | [#2132 - [mcp-parity][F1.1] Versioned source/API/MCP inventory](https://github.com/rashmijain02/OpenBB/issues/1186) | MCP:E1 | None |
| MCP:F1.2 | Feature | [#2133 - [mcp-parity][F1.2] Reviewed exposure and invocation policy](https://github.com/rashmijain02/OpenBB/issues/1187) | MCP:E1 | None |
| MCP:F1.3 | Feature | [#2134 - [mcp-parity][F1.3] Portfolio lineage and recent-work traceability](https://github.com/rashmijain02/OpenBB/issues/1188) | MCP:E1 | None |
| MCP:F2.1 | Feature | [#2135 - [mcp-parity][F2.1] Deterministic package and profile resolution](https://github.com/rashmijain02/OpenBB/issues/1189) | MCP:E2 | None |
| MCP:F2.2 | Feature | [#2136 - [mcp-parity][F2.2] Profile-aware launcher and readiness](https://github.com/rashmijain02/OpenBB/issues/1190) | MCP:E2 | None |
| MCP:F3.1 | Feature | [#2137 - [mcp-parity][F3.1] Typed provider route framework and complete regression gate](https://github.com/rashmijain02/OpenBB/issues/1191) | MCP:E3 | None |
| MCP:F3.2 | Feature | [#2138 - [mcp-parity][F3.2] Reference, search, price and intraday coverage](https://github.com/rashmijain02/OpenBB/issues/1192) | MCP:E3 | None |
| MCP:F3.3 | Feature | [#2139 - [mcp-parity][F3.3] Analyst, sector and statement coverage](https://github.com/rashmijain02/OpenBB/issues/1193) | MCP:E3 | None |
| MCP:F3.4 | Feature | [#2140 - [mcp-parity][F3.4] Corporate, government, news and COT coverage](https://github.com/rashmijain02/OpenBB/issues/1194) | MCP:E3 | None |
| MCP:F4.1 | Feature | [#2141 - [mcp-parity][F4.1] Reviewed custom Portfolio API adapter](https://github.com/rashmijain02/OpenBB/issues/1195) | MCP:E4 | None |
| MCP:F4.2 | Feature | [#2142 - [mcp-parity][F4.2] Reviewed Intelligence and Trading Desk adapter](https://github.com/rashmijain02/OpenBB/issues/1196) | MCP:E4 | None |
| MCP:F4.3 | Feature | [#2143 - [mcp-parity][F4.3] Analytics optional-package contract](https://github.com/rashmijain02/OpenBB/issues/1197) | MCP:E4 | None |
| MCP:F5.1 | Feature | [#2144 - [mcp-parity][F5.1] Cache observability and truthful persistence](https://github.com/rashmijain02/OpenBB/issues/1198) | MCP:E5 | None |
| MCP:F5.2 | Feature | [#2145 - [mcp-parity][F5.2] Authenticated job-backed maintenance](https://github.com/rashmijain02/OpenBB/issues/1199) | MCP:E5 | None |
| MCP:F6.1 | Feature | [#2146 - [mcp-parity][F6.1] Callable read-only Daytrade MCP](https://github.com/rashmijain02/OpenBB/issues/1200) | MCP:E6 | MCP:T31 |
| MCP:F6.2 | Feature | [#2147 - [mcp-parity][F6.2] Accurate and verified Agents MCP](https://github.com/rashmijain02/OpenBB/issues/1201) | MCP:E6 | None |
| MCP:F7.1 | Feature | [#2148 - [mcp-parity][F7.1] Prompt and skills dependency integrity](https://github.com/rashmijain02/OpenBB/issues/1202) | MCP:E7 | None |
| MCP:F7.2 | Feature | [#2149 - [mcp-parity][F7.2] Unified catalog and client/operator guidance](https://github.com/rashmijain02/OpenBB/issues/1203) | MCP:E7 | None |
| MCP:F8.1 | Feature | [#2150 - [mcp-parity][F8.1] Offline protocol and Portfolio drift gates](https://github.com/rashmijain02/OpenBB/issues/1204) | MCP:E8 | None |
| MCP:F8.2 | Feature | [#2151 - [mcp-parity][F8.2] Live acceptance and staged release](https://github.com/rashmijain02/OpenBB/issues/1205) | MCP:E8 | None |
| MCP:T01 | Task | [#2152 - [mcp-parity][T01] Define capability contracts and immutable audit fixtures](https://github.com/rashmijain02/OpenBB/issues/1215) | MCP:F1.1 | None |
| MCP:T02 | Task | [#2153 - [mcp-parity][T02] Build the metadata-only inventory CLI](https://github.com/rashmijain02/OpenBB/issues/1216) | MCP:F1.1 | MCP:T01 |
| MCP:T03 | Task | [#2154 - [mcp-parity][T03] Classify every capability and publish profile policy](https://github.com/rashmijain02/OpenBB/issues/1217) | MCP:F1.2 | MCP:T02 |
| MCP:T04 | Task | [#2155 - [mcp-parity][T04] Enforce policy at discovery and invocation](https://github.com/rashmijain02/OpenBB/issues/1218) | MCP:F1.2 | MCP:T03 |
| MCP:T05 | Task | [#2156 - [mcp-parity][T05] Automate Portfolio lineage and baseline comparison](https://github.com/rashmijain02/OpenBB/issues/1219) | MCP:F1.3 | MCP:T02 |
| MCP:T06 | Task | [#2157 - [mcp-parity][T06] Map recent work and exceptions to accountable capabilities](https://github.com/rashmijain02/OpenBB/issues/1220) | MCP:F1.3 | MCP:T03, MCP:T05 |
| MCP:T07 | Task | [#2158 - [mcp-parity][T07] Define the install/profile manifests](https://github.com/rashmijain02/OpenBB/issues/1221) | MCP:F2.1 | MCP:T03 |
| MCP:T08 | Task | [#2159 - [mcp-parity][T08] Establish clean-install and import-provenance checks](https://github.com/rashmijain02/OpenBB/issues/1222) | MCP:F2.1 | MCP:T07 |
| MCP:T09 | Task | [#2160 - [mcp-parity][T09] Add explicit launcher profile selection and safe lifecycle behavior](https://github.com/rashmijain02/OpenBB/issues/1223) | MCP:F2.2 | MCP:T04, MCP:T08 |
| MCP:T10 | Task | [#2161 - [mcp-parity][T10] Make readiness assert the effective capability contract](https://github.com/rashmijain02/OpenBB/issues/1224) | MCP:F2.2 | MCP:T02, MCP:T09 |
| MCP:T11 | Task | [#2162 - [mcp-parity][T11] Introduce typed provider-owned route assembly](https://github.com/rashmijain02/OpenBB/issues/1225) | MCP:F3.1 | MCP:T04, MCP:T07 |
| MCP:T12 | Task | [#2163 - [mcp-parity][T12] Route static directories, lists and references](https://github.com/rashmijain02/OpenBB/issues/1226) | MCP:F3.2 | MCP:T11 |
| MCP:T13 | Task | [#2164 - [mcp-parity][T13] Route historical reference and identifier search](https://github.com/rashmijain02/OpenBB/issues/1227) | MCP:F3.2 | MCP:T11 |
| MCP:T14 | Task | [#2165 - [mcp-parity][T14] Route batch quotes, market cap and stock-price extras](https://github.com/rashmijain02/OpenBB/issues/1228) | MCP:F3.2 | MCP:T11 |
| MCP:T15 | Task | [#2166 - [mcp-parity][T15] Route intraday, aftermarket, hours and single-parameter extras](https://github.com/rashmijain02/OpenBB/issues/1229) | MCP:F3.2 | MCP:T11 |
| MCP:T16 | Task | [#2167 - [mcp-parity][T16] Route analyst and sector/industry families](https://github.com/rashmijain02/OpenBB/issues/1230) | MCP:F3.3 | MCP:T11 |
| MCP:T17 | Task | [#2168 - [mcp-parity][T17] Route statement extras, TTM, DCF and as-reported data](https://github.com/rashmijain02/OpenBB/issues/1231) | MCP:F3.3 | MCP:T11 |
| MCP:T18 | Task | [#2169 - [mcp-parity][T18] Route corporate, SEC and fundraising extras](https://github.com/rashmijain02/OpenBB/issues/1232) | MCP:F3.4 | MCP:T11 |
| MCP:T19 | Task | [#2170 - [mcp-parity][T19] Route government, news and COT extras](https://github.com/rashmijain02/OpenBB/issues/1233) | MCP:F3.4 | MCP:T11 |
| MCP:T20 | Task | [#2171 - [mcp-parity][T20] Prove full FMP routing and persistence-descriptor regression](https://github.com/rashmijain02/OpenBB/issues/1234) | MCP:F3.1 | MCP:T12, MCP:T13, MCP:T14, MCP:T15, MCP:T16, MCP:T17, MCP:T18, MCP:T19 |
| MCP:T21 | Task | [#2172 - [mcp-parity][T21] Implement the custom Portfolio composition seam](https://github.com/rashmijain02/OpenBB/issues/1235) | MCP:F4.1 | MCP:T04, MCP:T07 |
| MCP:T22 | Task | [#2173 - [mcp-parity][T22] Verify all 19 Portfolio operations and private-data boundaries](https://github.com/rashmijain02/OpenBB/issues/1236) | MCP:F4.1 | MCP:T06, MCP:T21 |
| MCP:T23 | Task | [#2174 - [mcp-parity][T23] Map Intelligence, provenance, snapshots and Trading Desk effects](https://github.com/rashmijain02/OpenBB/issues/1237) | MCP:F4.2 | MCP:T03, MCP:T06 |
| MCP:T24 | Task | [#2175 - [mcp-parity][T24] Add approved Intelligence adapters and contract parity tests](https://github.com/rashmijain02/OpenBB/issues/1238) | MCP:F4.2 | MCP:T21, MCP:T23 |
| MCP:T25 | Task | [#2176 - [mcp-parity][T25] Lock analytical extension coverage and behavior](https://github.com/rashmijain02/OpenBB/issues/1239) | MCP:F4.3 | MCP:T04, MCP:T08 |
| MCP:T26 | Task | [#2177 - [mcp-parity][T26] Reconcile FinancialToolkit router assembly](https://github.com/rashmijain02/OpenBB/issues/1240) | MCP:F4.3 | MCP:T04, MCP:T08 |
| MCP:T27 | Task | [#2178 - [mcp-parity][T27] Expose sanitized cache health and coverage](https://github.com/rashmijain02/OpenBB/issues/1241) | MCP:F5.1 | MCP:T04, MCP:T11 |
| MCP:T28 | Task | [#2179 - [mcp-parity][T28] Verify persistence semantics and prioritize conversion gaps](https://github.com/rashmijain02/OpenBB/issues/1242) | MCP:F5.1 | MCP:T20, MCP:T27 |
| MCP:T29 | Task | [#2180 - [mcp-parity][T29] Wire operator tools to existing job definitions](https://github.com/rashmijain02/OpenBB/issues/1243) | MCP:F5.2 | MCP:T04, MCP:T27 |
| MCP:T30 | Task | [#2181 - [mcp-parity][T30] Prove maintenance isolation and recovery](https://github.com/rashmijain02/OpenBB/issues/1244) | MCP:F5.2 | MCP:T29 |
| MCP:T31 | Task | [#386 - [P3.5 MCP tool server (openbb-daytrade mcp-serve)]](https://github.com/rashmijain02/OpenBB/issues/241) | MCP:F6.1 (cross-link only) | MCP:T03 |
| MCP:T32 | Task | [#2182 - [mcp-parity][T32] Verify Daytrade over an actual stdio connection](https://github.com/rashmijain02/OpenBB/issues/1245) | MCP:F6.1 | MCP:T31 |
| MCP:T33 | Task | [#2183 - [mcp-parity][T33] Align Agents scope, schemas and documentation](https://github.com/rashmijain02/OpenBB/issues/1246) | MCP:F6.2 | MCP:T02, MCP:T03 |
| MCP:T34 | Task | [#2184 - [mcp-parity][T34] Validate Agents transport and sanitized portfolio access](https://github.com/rashmijain02/OpenBB/issues/1247) | MCP:F6.2 | MCP:T33 |
| MCP:T35 | Task | [#2185 - [mcp-parity][T35] Add structured prompt dependencies and readiness checks](https://github.com/rashmijain02/OpenBB/issues/1248) | MCP:F7.1 | MCP:T02, MCP:T07 |
| MCP:T36 | Task | [#2186 - [mcp-parity][T36] Correct cache, stock and FinancialToolkit instructions](https://github.com/rashmijain02/OpenBB/issues/1249) | MCP:F7.1 | MCP:T20, MCP:T22, MCP:T26, MCP:T28, MCP:T35 |
| MCP:T37 | Task | [#2187 - [mcp-parity][T37] Publish a unified capability resource and client examples](https://github.com/rashmijain02/OpenBB/issues/1250) | MCP:F7.2 | MCP:T10, MCP:T24, MCP:T25, MCP:T32, MCP:T34, MCP:T36 |
| MCP:T38 | Task | [#2188 - [mcp-parity][T38] Write operator setup, maintenance and rollback runbooks](https://github.com/rashmijain02/OpenBB/issues/1251) | MCP:F7.2 | MCP:T30, MCP:T37 |
| MCP:T39 | Task | [#2189 - [mcp-parity][T39] Build a shared real-protocol regression matrix](https://github.com/rashmijain02/OpenBB/issues/1252) | MCP:F8.1 | MCP:T04, MCP:T07 |
| MCP:T40 | Task | [#2190 - [mcp-parity][T40] Add Portfolio-based capability and prompt drift CI](https://github.com/rashmijain02/OpenBB/issues/1253) | MCP:F8.1 | MCP:T06, MCP:T20, MCP:T22, MCP:T24, MCP:T25, MCP:T26, MCP:T35, MCP:T39 |
| MCP:T41 | Task | [#2191 - [mcp-parity][T41] Certify package and interpreter replay](https://github.com/rashmijain02/OpenBB/issues/1254) | MCP:F8.1 | MCP:T10, MCP:T39 |
| MCP:T42 | Task | [#2192 - [mcp-parity][T42] Revalidate integrated Workspace and registered backend parity](https://github.com/rashmijain02/OpenBB/issues/1255) | MCP:F8.2 | MCP:T24, MCP:T37, MCP:T39 |
| MCP:T43 | Task | [#2193 - [mcp-parity][T43] Validate controlled data and operator workflows](https://github.com/rashmijain02/OpenBB/issues/1256) | MCP:F8.2 | MCP:T28, MCP:T30, MCP:T32, MCP:T34, MCP:T41 |
| MCP:T44 | Task | [#2194 - [mcp-parity][T44] Release, update coverage evidence, and prove rollback](https://github.com/rashmijain02/OpenBB/issues/1257) | MCP:F8.2 | MCP:T38, MCP:T40, MCP:T41, MCP:T42, MCP:T43 |

### Notebook-agent program

| Plan ID | Type | Issue | Parent / relationship | Blocking plan IDs |
| --- | --- | --- | --- | --- |
| NB:ROOT | Epic | [#2195 - [notebook-agent][PROGRAM] Python MCP Notebook Companion with local vLLM Nemotron](https://github.com/rashmijain02/OpenBB/issues/210) | Program root | MCP:T44 |
| NB:NE1 | Epic | [#2196 - [notebook-agent][NE1] Source story contracts and independent fixture readiness](https://github.com/rashmijain02/OpenBB/issues/726) | NB:ROOT | None |
| NB:NE2 | Epic | [#2197 - [notebook-agent][NE2] Notebook-specific MCP analytical and workflow bridges](https://github.com/rashmijain02/OpenBB/issues/211) | NB:ROOT | None |
| NB:NE3 | Epic | [#2198 - [notebook-agent][NE3] Python local-model MCP agent and CLI](https://github.com/rashmijain02/OpenBB/issues/212) | NB:ROOT | None |
| NB:NE4 | Epic | [#2199 - [notebook-agent][NE4] Differential, model and safety qualification](https://github.com/rashmijain02/OpenBB/issues/213) | NB:ROOT | None |
| NB:NE5 | Epic | [#2200 - [notebook-agent][NE5] Resume, Workspace integration and release](https://github.com/rashmijain02/OpenBB/issues/214) | NB:ROOT | None |
| NB:NF1.1 | Feature | [#2201 - [notebook-agent][NF1.1] Source inventory and versioned narrative contracts](https://github.com/rashmijain02/OpenBB/issues/1174) | NB:NE1 | None |
| NB:NF1.2 | Feature | [#2202 - [notebook-agent][NF1.2] Independent fixtures and capability readiness](https://github.com/rashmijain02/OpenBB/issues/1175) | NB:NE1 | None |
| NB:NF2.1 | Feature | [#2203 - [notebook-agent][NF2.1] Deterministic analytics and managed story state](https://github.com/rashmijain02/OpenBB/issues/727) | NB:NE2 | None |
| NB:NF2.2 | Feature | [#2204 - [notebook-agent][NF2.2] Artifacts, jobs, paper gates and provider modes](https://github.com/rashmijain02/OpenBB/issues/215) | NB:NE2 | None |
| NB:NF3.1 | Feature | [#2205 - [notebook-agent][NF3.1] Local model, MCP sessions and enforced tool execution](https://github.com/rashmijain02/OpenBB/issues/216) | NB:NE3 | None |
| NB:NF3.2 | Feature | [#2206 - [notebook-agent][NF3.2] Narrative planner, evidence and developer CLI](https://github.com/rashmijain02/OpenBB/issues/217) | NB:NE3 | None |
| NB:NF4.1 | Feature | [#2207 - [notebook-agent][NF4.1] Numerical and full-corpus story parity](https://github.com/rashmijain02/OpenBB/issues/218) | NB:NE4 | None |
| NB:NF4.2 | Feature | [#2208 - [notebook-agent][NF4.2] Local Nemotron reliability and safety qualification](https://github.com/rashmijain02/OpenBB/issues/219) | NB:NE4 | None |
| NB:NF5.1 | Feature | [#2209 - [notebook-agent][NF5.1] Recoverable runs and shared Workspace agent experience](https://github.com/rashmijain02/OpenBB/issues/220) | NB:NE5 | None |
| NB:NF5.2 | Feature | [#2210 - [notebook-agent][NF5.2] Portfolio drift CI and verified showcase release](https://github.com/rashmijain02/OpenBB/issues/221) | NB:NE5 | None |
| NB:N01 | Task | [#2211 - [notebook-agent][N01] Inventory source-only notebook stories and Portfolio lineage](https://github.com/rashmijain02/OpenBB/issues/1206) | NB:NF1.1 | MCP:T44 |
| NB:N02 | Task | [#2212 - [notebook-agent][N02] Define typed story manifests, stage DAGs and state handoffs](https://github.com/rashmijain02/OpenBB/issues/1207) | NB:NF1.1 | MCP:T44, NB:N01 |
| NB:N03 | Task | [#2213 - [notebook-agent][N03] Build independent synthetic scenarios and parity expectations](https://github.com/rashmijain02/OpenBB/issues/1208) | NB:NF1.2 | MCP:T44, NB:N02 |
| NB:N04 | Task | [#2214 - [notebook-agent][N04] Bind story outcomes to real MCP capability readiness](https://github.com/rashmijain02/OpenBB/issues/1209) | NB:NF1.2 | MCP:T44, NB:N02 |
| NB:N05 | Task | [#2215 - [notebook-agent][N05] Expose missing notebook analytics through owned engine adapters](https://github.com/rashmijain02/OpenBB/issues/1176) | NB:NF2.1 | MCP:T44, NB:N03, NB:N04 |
| NB:N06 | Task | [#2216 - [notebook-agent][N06] Add story catalog, run registry and typed state management tools](https://github.com/rashmijain02/OpenBB/issues/1177) | NB:NF2.1 | MCP:T44, NB:N02, NB:N04 |
| NB:N07 | Task | [#2217 - [notebook-agent][N07] Produce bounded chart, table, report and XLSX artifacts](https://github.com/rashmijain02/OpenBB/issues/728) | NB:NF2.2 | MCP:T44, NB:N03, NB:N05, NB:N06 |
| NB:N08 | Task | [#2218 - [notebook-agent][N08] Bridge backtest, tuning and replay into existing durable jobs](https://github.com/rashmijain02/OpenBB/issues/729) | NB:NF2.2 | MCP:T44, NB:N05, NB:N06, NB:N07 |
| NB:N09 | Task | [#2219 - [notebook-agent][N09] Gate Portfolio and TechTrade sandbox paper actions](https://github.com/rashmijain02/OpenBB/issues/222) | NB:NF2.2 | MCP:T44, NB:N05, NB:N06, NB:N07 |
| NB:N10 | Task | [#2220 - [notebook-agent][N10] Enforce provider variants, recording and truthful cache semantics](https://github.com/rashmijain02/OpenBB/issues/223) | NB:NF2.2 | MCP:T44, NB:N03, NB:N04, NB:N08 |
| NB:N11 | Task | [#2221 - [notebook-agent][N11] Implement explicit local vLLM model configuration and preflight](https://github.com/rashmijain02/OpenBB/issues/224) | NB:NF3.1 | MCP:T44, NB:N04 |
| NB:N12 | Task | [#2222 - [notebook-agent][N12] Implement authenticated server-qualified MCP client sessions](https://github.com/rashmijain02/OpenBB/issues/225) | NB:NF3.1 | MCP:T44, NB:N04 |
| NB:N13 | Task | [#2223 - [notebook-agent][N13] Build bounded schema-validated MCP tool execution loop](https://github.com/rashmijain02/OpenBB/issues/226) | NB:NF3.1 | MCP:T44, NB:N05, NB:N06, NB:N07, NB:N08, NB:N09, NB:N10, NB:N11, NB:N12 |
| NB:N14 | Task | [#2224 - [notebook-agent][N14] Plan narrative progression and cross-chapter state bindings](https://github.com/rashmijain02/OpenBB/issues/227) | NB:NF3.2 | MCP:T44, NB:N02, NB:N04, NB:N13 |
| NB:N15 | Task | [#2225 - [notebook-agent][N15] Render evidence-grounded explanations and artifact provenance](https://github.com/rashmijain02/OpenBB/issues/228) | NB:NF3.2 | MCP:T44, NB:N07, NB:N13, NB:N14 |
| NB:N16 | Task | [#2226 - [notebook-agent][N16] Deliver CLI story inspection, planning and approved execution](https://github.com/rashmijain02/OpenBB/issues/229) | NB:NF3.2 | MCP:T44, NB:N11, NB:N12, NB:N14, NB:N15 |
| NB:N17 | Task | [#2227 - [notebook-agent][N17] Implement independent numeric and artifact differential tests](https://github.com/rashmijain02/OpenBB/issues/230) | NB:NF4.1 | MCP:T44, NB:N03, NB:N05, NB:N07, NB:N09, NB:N10, NB:N16 |
| NB:N18 | Task | [#2228 - [notebook-agent][N18] Qualify all 25 notebook stories and narrative handoffs](https://github.com/rashmijain02/OpenBB/issues/231) | NB:NF4.1 | MCP:T44, NB:N14, NB:N16, NB:N17 |
| NB:N19 | Task | [#2229 - [notebook-agent][N19] Qualify local Nemotron tool use and explainability](https://github.com/rashmijain02/OpenBB/issues/232) | NB:NF4.2 | MCP:T44, NB:N11, NB:N15, NB:N18 |
| NB:N20 | Task | [#2230 - [notebook-agent][N20] Test denial, prompt injection, approvals and uncertain completion](https://github.com/rashmijain02/OpenBB/issues/233) | NB:NF4.2 | MCP:T44, NB:N09, NB:N12, NB:N13, NB:N16 |
| NB:N21 | Task | [#2231 - [notebook-agent][N21] Add checkpoint resume, idempotency reconciliation and budgets](https://github.com/rashmijain02/OpenBB/issues/234) | NB:NF5.1 | MCP:T44, NB:N06, NB:N08, NB:N13, NB:N16, NB:N20 |
| NB:N22 | Task | [#2232 - [notebook-agent][N22] Register a Workspace agent adapter over the same Python runner](https://github.com/rashmijain02/OpenBB/issues/235) | NB:NF5.1 | MCP:T44, NB:N15, NB:N16, NB:N20, NB:N21 |
| NB:N23 | Task | [#2233 - [notebook-agent][N23] Add Portfolio source, capability and agent regression CI gates](https://github.com/rashmijain02/OpenBB/issues/236) | NB:NF5.2 | MCP:T44, NB:N01, NB:N18, NB:N19, NB:N20, NB:N21, NB:N22 |
| NB:N24 | Task | [#2234 - [notebook-agent][N24] Release verified notebook-equivalent showcase and runbooks](https://github.com/rashmijain02/OpenBB/issues/237) | NB:NF5.2 | MCP:T44, NB:N18, NB:N19, NB:N20, NB:N21, NB:N22, NB:N23 |

## Verification boundary

This is GitHub metadata and planning verification. No original notebook was
executed, no provider/paper call was made, and no Python product agent was
implemented. Source coverage, numeric parity and model reliability remain
separate gates in the linked specifications.
