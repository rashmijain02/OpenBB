# Plan: HFP-P38 scoped public knowledge and source-grounded Q&A (#1378)

Status: **design draft, not committed.** Base `origin/portfolio` @ `5321c620c` (contains #1338, #1339, #1340,
#1341); branch `feat/hfp-public-knowledge-gh-1378`. Parent #1328 (HFP-F06). Requirements PF-15 (primary), PF-04.
Design sources: `docs/Specs/gh-1312-hermes-financial-planning/` plan.md §11.1, §11.3, §11.4, §6, §7;
spec.md PF-15/PF-04; research.md §5 (docs groups), §8 (official tax-source register T01-T12);
github-plan/plan.md HFP-P38, OPTIONAL-SEMANTIC, SOURCES-PINNED. Synthetic and public data only; no services,
no network, no private files. Semantic/vector retrieval is **out of scope** (OPTIONAL-SEMANTIC is owner-gated).

## 1. Existing assets (reused, not rebuilt)

| Asset | File / symbol | Use here |
|---|---|---|
| Server-side gate | `openbb_agents/hermes_integration/access.py`: `PolicyGate.decide`, `Capability`, `ToolBinding`, `TOOL_BINDINGS`, `KNOWN_SCOPES`, `HERMES_FINANCE_POLICY`, `ToolGate.decide_tool` (ignores model arguments; unbound tools deny `unknown_operation`), `build_tool_gate` | New tools get a `ToolBinding` + one `hermes_runtime` grant; nothing else widens. |
| Agents MCP server | `openbb_agents/mcp_server.py`: `_TOOL_MODULES=[portfolio_tools]`, `collect_tools`, `@mcp_tool` (`_mcp_tool.py`), `_serve(policy_profile, principal)` calls `gate.decide_tool` before any tool body; `--policy-profile hermes-finance --principal` | The "same Hermes coordinator": Hermes calls these MCP tools; no agent loop or model call inside OpenBB. |
| Default-mode invariants | `tests/hermes_integration/test_mcp_policy_gate.py`: `test_default_profile_tool_list_unchanged`, `test_default_mode_does_not_import_policy_module`, `test_stdio_gate_*` | Must stay green: knowledge tools are served only under a policy profile (Q5). |
| Scanner / sentinels | `hermes_integration/projection.py`: `scan_text`, `SENTINELS`, `--scan-stdin`; closed vocabularies `FINDING_CODES`; `tests/hermes_integration/conftest.py` `SENTINELS`, network deny, tmp HOME | Build-time content scan, output scans, finding-code style. |
| Egress guard | `hermes_integration/egress_guard.py`: `egress_guard(refuse_live_ports=True)` | Wrap index build, search and probe: zero non-loopback lookups/connects. |
| Route policy | `hermes_integration/litellm_config.py`: `evaluate_gateway`, `select_private_aliases`; `hermes_preflight.py` `_check_route`; #1338 live steps L2/L3 | Only model call is Hermes's own turn on the admitted local finance alias; no new route code. |
| Git facts | `hermes_integration/provenance.py`: `_git` hardening (`core.fsmonitor=false`, `GIT_NO_LAZY_FETCH`, `GIT_TERMINAL_PROMPT=0`), `GitFacts` | Same flags for `git cat-file`/`ls-tree` reads of pinned blobs. |
| Workflow vocabulary | `hermes_integration/workflow.py`: `ACCESS_OPERATIONS["metadata"] -> public_metadata`, `document_evidence` (private, evidence projection) | Public knowledge is `public_metadata`; it never uses `document_evidence` (that is the private plan §11.2 corpus). |
| Skills admission | `hermes_integration/skills_admission.py` (hash-pinned read-only skills, quarantined proposals) | Optional answer-contract skill only via this path (Q8). |
| Probe pattern | `hermes_integration/policy_probe.py --synthetic [--projection]` | Template for the knowledge real-path probe. |
| Live steps | `specs/gh-1338-hfp-runtime-privacy-admission/live-acceptance.md` L2-L5 | New owner-run step L6 appended. |
| Corpus facts | 261 tracked `docs/**/*.md`; only ~41 carry a free-text `Status:` line (inconsistent); `docs/examples/` has 11 `.ipynb` (tracked copies have 0 outputs, 0 attachments today); `.gitignore` has `notebooks_local/`, `**/.notebook_state/`, `*.env` | Status comes from a reviewed register, never from document prose. |
| Retrieval code | None found (`fts5`/`bm25`/`retrieval` grep over extensions, scripts, Analysis: no index). `.venv_portfolio` CPython 3.12.15, sqlite 3.53.1 with FTS5 | In-memory SQLite FTS5 + exact identifier table; no new dependency. |

## 2. Design

**Package** `openbb_platform/extensions/agents/openbb_agents/hermes_integration/knowledge/` (imported only under a
policy profile, so default-mode import hygiene holds):

```
knowledge/__init__.py        # empty
knowledge/register.py        # T01: PublicSource/Register models, validate(), --check CLI
knowledge/public_sources.json# T01: reviewed allowlist register (committed, hash-pinned blobs)
knowledge/corpus.py          # T01: pinned-blob reader, Markdown sectioner, ipynb markdown-only reader, exclusions
knowledge/index.py           # T02: in-memory FTS5 + exact identifier index, bounded search()
knowledge/grounding.py       # T02: answer contract + check_answer() validator
knowledge/tools.py           # T02: @mcp_tool knowledge_search, knowledge_get_section
knowledge/probe.py           # T02/T03: real-path probe (--synthetic | --register)
tests/hermes_integration/knowledge/{conftest.py, fixtures/, test_register.py, test_corpus_exclusions.py,
  test_index.py, test_grounding.py, test_tools_gate.py, test_injection.py, test_probe.py}
```

**Register entry (T01)**, `extra="forbid", frozen=True, strict=True` like `workflow._Contract`:
`source_id` (`^[a-z0-9][a-z0-9_.-]*$`), `path` (repo-relative POSIX, tracked), `blob_sha` (40-hex git object id,
the reviewed revision), `kind` (`requirement_spec|implementation_plan|design|platform_doc|example_notebook|
tax_source_pointer`), `authority` (`official_primary|repo_requirement|repo_plan|repo_design|repo_reference|
historical`), `status` (`implemented|proposed|historical|superseded|unknown`, plan §11.1), `status_evidence`
(`pr:<n>|issue:<n>|commit:<sha>|none`), `supersedes`/`superseded_by` (source IDs), `effective` (`tax_year`,
`provider_version`, `as_of`, optional), `privacy_class: Literal["public_reference"]`,
`model_context: Literal["allowed"]`, optional `sections` allowlist of anchors, optional `notebook_role`
(`analytics|explanation|setup_only|template`, PF-04). Optional per-section status overrides
(`section_status: {anchor: status}`) cover documents that mix implemented and proposed parts (e.g. plan.md §6
operations are proposed). Tax pointers (research.md §8 T01-T12) are rows whose content is **the reviewed
research.md §8 row at its pinned blob**, with `authority: official_primary` describing the cited source and
`content: pointer_only`; official pages are never fetched (Q3).

**Eligibility** = allowlist AND not denylist; the denylist wins even if a row lists a path.
Allowlist roots (v1, Q1): `docs/Specs/**.md`, `specs/gh-*/plan.md`, `docs/designs/**.md`,
`docs/OpenBBPlatform/**.md`, `docs/examples/*.md`, `docs/examples/*.ipynb` (markdown cells only).
Denylist (always): `notebooks_local/**`, `**/.notebook_state/**`, `notebooks/**` (v1, Q2), `docs/handoff/**`,
`docs/archive/**`, `docs/prompts/**`, `docs/superpowers/**`, agent-instruction files (`CLAUDE.md`, `AGENTS.md`,
`GEMINI.md`, `.claude/**`, `.agents/**`, `.codex/**`, `.github/skills/**`, `rules/**`, `context/**`), `**/*.env*`,
`**/handoff.md`, `.dev-cycle/**`, `.worktrees/**`; any path with a drive letter, `..`, backslash, leading `/`,
`~`, or that is a symlink/gitlink. Content is read **only** by `git cat-file blob <blob_sha>` after
`git ls-tree <commit> -- <path>` proves the path is tracked, so untracked, ignored and working-tree edits can
never enter. Notebook reader parses JSON and keeps `cell_type=="markdown"` `source` only; `outputs`,
`attachments`, `metadata` and code cells are never read into text. Sections whose text hits `projection.scan_text`
(sentinels/secret shapes) or a user-path regex (`[A-Za-z]:\\Users\\`, `/home/<x>/`, `/Users/<x>/`, `\\\\host\\`)
are dropped with a fixed code (`private_path_excluded`, `secret_shape_excluded`); `--check` exits 1 naming
`source_id#anchor` only, never text.

**Revision pinning.** Citation key `[[doc:<source_id>@<blob_sha[:12]>#<anchor>]]`. Anchor = GitHub-style
heading slug with `-N` duplicate suffix; a section runs to the next heading of equal or higher level and carries
`section_sha256` of its normalised text. HEAD drift (tracked blob at HEAD != `blob_sha`): the pinned blob is still
served, flagged `head_drift: true`; `register --check` fails on drift so CI forces a re-review (Q4).

**Bounded exact retrieval (T02).** `search(query, limit<=5, status_filter)`: query <=256 chars, <=12 tokens,
tokens normalised and each **quoted** before FTS5 `MATCH` (model text cannot inject FTS operators). Stages, first
non-empty wins: (1) exact identifier table (`PF-15`, `HFP-P38`, `T01`, `documents.search`, heading text);
(2) FTS5 phrase; (3) FTS5 all-tokens AND ranked by bm25 — no OR, prefix, fuzzy or embeddings. Filters
(status, kind, authority) apply in SQL before ranking (plan §11.3 item 2). Ties: non-superseded first, then
authority order. Superseded hits are returned only alongside their successor (`superseded_by` resolved). Results:
`result` `evidence|no_evidence|ambiguous` (ambiguous = equal-authority non-superseded hits with conflicting
status); per hit `cite`, `path`, `section`, `revision{blob_sha, head_drift}`, `authority`, `status`,
`superseded_by`, `match` (`identifier|phrase|all_terms`), `flags` (closed vocabulary incl.
`INSTRUCTION_LIKE_TEXT`), `excerpt{untrusted: true, text}` <=800 chars, total payload <=4000 chars.
Excerpts are normalised: control and zero-width characters removed, HTML comments stripped, URLs kept as plain
text (no fetch). Index is built once at server start from the register, in memory, under `egress_guard`; nothing
is persisted (no index file to protect or revoke).

**MCP tools** (`knowledge/tools.py`, `@mcp_tool`): `knowledge_search(query: str, limit: int = 5,
status: str = "any")` and `knowledge_get_section(cite: str)` (must be a key the index holds; no path argument).
No path, directory, policy, principal, route or model argument exists. `mcp_server._serve` appends
`_GATED_TOOL_MODULES` (knowledge tools) only when `policy_profile` is set (Q5); `access.py` adds scope
`knowledge.public_reference`, `TOOL_BINDINGS` for both tools (operation `public_metadata`, fields = hit fields)
and one `Capability(principal="hermes_runtime", ...)`. `hermes_scheduler` gets none (Q6 of #1339 style).
The register file is chosen by the launcher (`--knowledge-register`, default the committed file), never by the model.

**Source-grounded synthesis contract (T02).** Synthesis is Hermes's own turn; OpenBB supplies evidence and a
deterministic validator. `grounding.check_answer(answer, hits) -> GroundingVerdict` (codes, closed vocabulary):
`ok`, `uncited_claim` (a sentence/bullet with no cite), `unknown_cite` (cite not in this turn's hits, wrong
blob prefix or anchor = wrong-revision near match), `status_mislabel` (answer says implemented/available for a
`proposed`/`historical`/`unknown` section or vice versa), `superseded_without_successor`, `authority_missing`,
`abstain_required` (result was `no_evidence`/`ambiguous` but the answer asserts content), `abstain_ok`.
Required answer shape: each claim ends with a cite and an inline label `(status, authority)`; abstention is the
literal `[[abstain:no_evidence]]` or `[[abstain:ambiguous]]` plus the searched scope. Tool payloads carry
`answer_contract_version: 1`. Runtime enforcement inside Hermes is not assumed (only `pre_tool_call` is a
verified hook, `hermes_plugin/plugin.yaml`); the validator grades CODE-ONLY scripted answers and LIVE L6 answers.

**Prompt injection.** Retrieved text is data: (a) the gate decides on the launch-bound principal only
(`ToolGate.decide_tool` drops arguments), so text cannot grant tools, change profile, route or destination;
(b) the knowledge tools take no argument that names a path, server, policy or model; (c) instruction-like
patterns (role prefixes, "ignore previous", tool-call JSON, install/curl/pip, "change policy/profile/model")
add the `INSTRUCTION_LIKE_TEXT` flag but the text is never rewritten into instructions or executed;
(d) agent-instruction files are denylisted outright; (e) no network during search (`egress_guard`). The guarantee
rests on (a), (b), (e); (c) is a label, not a defence (see R1).

## 3. Common commands (PowerShell 7, worktree root)

```powershell
$py = Join-Path (Split-Path (git rev-parse --path-format=absolute --git-common-dir)) '.venv_portfolio\Scripts\python.exe'
$env:PYTHONPATH = @((Resolve-Path openbb_platform\extensions\agents).Path,
                    (Resolve-Path openbb_platform\extensions\mcp_server).Path) -join ';'
$K = 'openbb_platform/extensions/agents/tests/hermes_integration/knowledge'
& $py -m pytest $K -q                                                       # focused
& $py -m pytest openbb_platform/extensions/agents/tests/hermes_integration -q   # regression (#1338-#1341)
& $py -m black --check <changed>; & $py -m ruff check <changed>; uvx codespell@2.4.1 <changed docs>
```

Fixtures: `conftest.py` builds a **synthetic git repo in tmp_path** (`git -c user.name=t -c user.email=t@invalid
init/commit`), so blob pins, untracked and ignored files are real git states; parent conftest keeps network deny
and tmp HOME. Real-path evidence: `.dev-cycle/verify-gh-1378.log` (git-ignored) and the handoff.

## 4. Tasks

### T01: allowlisted public-source register with status/supersession metadata (CODE-ONLY)

Goal: a reviewed, revision-pinned register and a corpus reader that can only admit public, tracked, allowlisted
text. Files: `knowledge/register.py`, `knowledge/corpus.py`, `knowledge/public_sources.json` (initial rows per Q1,
statuses set by reviewer with `status_evidence`), `tests/.../knowledge/test_register.py`,
`test_corpus_exclusions.py`, `fixtures/`.
Red-first tests (acceptance bullet in brackets):
- [A1] `test_status_and_authority_come_from_register_not_prose`: fixture doc says "Status: implemented";
  register says `proposed` -> indexed status `proposed`.
- [A1] `test_supersession_symmetric_acyclic_and_resolvable`; `test_superseded_requires_successor`;
  `test_unknown_status_literal_rejected`; `test_extra_field_rejected` (strict, no coercion).
- [A1] `test_blob_pin_reads_reviewed_revision_not_worktree` (edit file after commit -> pinned text served,
  `head_drift` true; `register --check` exit 1 `revision_drift`).
- [A1] `test_section_anchors_and_section_sha_stable` (duplicate headings, setext/ATX, code fences not headings).
- [A2] `test_untracked_and_ignored_paths_rejected` (`docs/untracked.md`, `notebooks_local/x.md`):
  `not_tracked`; `test_denylist_beats_allowlist` (`docs/handoff/h.md`, `CLAUDE.md`, `.claude/skills/x.md`,
  `docs/archive/a.md`, `.env`); `test_path_shapes_rejected` (drive letter, `..`, backslash, absolute, symlink).
- [A2] `test_notebook_outputs_attachments_code_never_read`: fixture `.ipynb` whose outputs, attachments,
  metadata and code cells hold every conftest `SENTINELS` value -> index text `scan_text == []`; markdown kept.
- [A2] `test_private_path_and_secret_shaped_sections_dropped` (`C:\Users\someone\...`, `api_key=...`):
  section dropped with code; `--check` output names `source_id#anchor` only, no text.
- [A1] `test_tax_pointer_rows_are_pointer_only` (T01-T12 rows: no fetch, `egress_guard` records none).
- `test_committed_register_validates` against the worktree repo (guards the real file).
Focused: `& $py -m pytest $K/test_register.py $K/test_corpus_exclusions.py -q`.
Real path (replaces "Not yet qualified"): `& $py -m openbb_agents.hermes_integration.knowledge.register --check`
-> exit 0, one line per count `status=<s> authority=<a> n=<k>`, `excluded=<code>:<n>`, piped through
`projection --scan-stdin` -> `hits=0`. Classification: **CODE-ONLY**.

### T02: bounded exact retrieval and source-grounded synthesis via the same Hermes coordinator (CODE-ONLY + LIVE)

Goal: two gated MCP tools on `openbb_agents.mcp_server` under `hermes-finance`, plus the answer validator.
Files: `knowledge/index.py`, `knowledge/grounding.py`, `knowledge/tools.py`, `knowledge/probe.py`;
`mcp_server.py` (`_GATED_TOOL_MODULES`, `--knowledge-register`); `access.py` (scope, two `TOOL_BINDINGS`, one
grant); tests `test_index.py`, `test_grounding.py`, `test_tools_gate.py`, `test_probe.py`; append L6 to
`specs/gh-1338-hfp-runtime-privacy-admission/live-acceptance.md`.
Red-first tests:
- [A1] `test_identifier_exact_before_fulltext` (`PF-15` returns spec row, not a prose mention);
  `test_no_or_prefix_fuzzy_matching`; `test_fts_operators_in_query_are_literal` (`"a" OR b*`, `NEAR(`);
  `test_limits_enforced` (limit>5, 257-char query, payload <=4000, excerpt <=800).
- [A1] `test_wrong_revision_near_match`: fixture `spec_v1` (superseded) and `spec_v2` differ by one number;
  default search returns v2 with `superseded_by` link; validator flags an answer citing v1's blob as
  `unknown_cite`/`superseded_without_successor`.
- [A1] `test_proposed_vs_implemented_distinguished`: section_status mix; validator `status_mislabel` on
  "X is implemented" for a proposed anchor; `ok` when labelled `(proposed, repo_plan)`.
- [A1] `test_every_hit_has_cite_path_section_revision_authority_status`.
- [A2] `test_absent_evidence_returns_no_evidence_and_requires_abstention`; `test_conflict_returns_ambiguous`.
- `test_knowledge_tools_absent_in_default_mode` (snapshot `_DEFAULT_TOOLS` unchanged, policy module not
  imported); `test_knowledge_tools_require_grant` (no principal / `hermes_scheduler` -> `capability_denied`
  before body); `test_tool_schema_has_no_path_policy_or_model_args` (schema pinned by hash);
  `test_get_section_rejects_unindexed_cite`.
- `test_stdio_gated_server_answers_synthetic_question` (real stdio child, as `test_stdio_gate_*`).
Focused: `& $py -m pytest $K/test_index.py $K/test_grounding.py $K/test_tools_gate.py -q` plus
`tests/hermes_integration/test_mcp_policy_gate.py`.
Real path: `& $py -m openbb_agents.hermes_integration.knowledge.probe --synthetic` (spawns the gated stdio server,
tmp HOME, DB on a closed loopback port, `egress_guard`, scripted coordinator replays fixed questions: hit,
wrong-revision, proposed-vs-implemented, absent) -> exit 0, `checks=<n> failed=0 egress=0`, output scans `hits=0`;
then `probe --register` (committed register, read-only fixed public questions, e.g. "Is documents.search
implemented?" -> plan.md §6 cite, `proposed`) -> exit 0.
Classification: tools, validator, probe **CODE-ONLY**; one real Hermes Q&A turn **LIVE** (step L6, after
#1338 L2/L3 and #1339 L4/L5): owner runs three fixed questions (answerable, proposed-vs-implemented, absent) through
the admitted local finance alias in `<qual-home>`, pastes only the answers' cite keys into
`knowledge.probe --grade-stdin` (validator; exit 0 = every verdict `ok`/`abstain_ok`), and the #1339 L5 count-only
check shows zero hosted-alias requests. Never paste prompts or responses beyond cite keys and codes.

### T03: injection, ignored instructions, private-path exclusion, abstention (CODE-ONLY)

Goal: adversarial fixtures proving acceptance bullet 2 end to end over the real stdio server. Files:
`tests/.../knowledge/test_injection.py`, `fixtures/injection/*.md` (synthetic, public-shaped), `probe.py --adversarial`.
Red-first tests:
- [A2] `test_injected_instruction_is_returned_as_flagged_data` (role prefix, "ignore previous instructions",
  tool-call JSON, HTML-comment and zero-width hidden text): `excerpt.untrusted`, flag `INSTRUCTION_LIKE_TEXT`,
  hidden text stripped, payload schema unchanged.
- [A2] `test_obedient_coordinator_cannot_escalate`: scripted coordinator that follows the excerpt (calls
  `get_positions` with "approved" claims, asks for another principal/profile, passes a path to
  `knowledge_get_section`) -> each denied with `capability_denied`/`unknown_cite`; tool bodies not run.
- [A2] `test_injection_cannot_change_route_or_destination`: excerpt with URL and "use model X" -> no lookup or
  connect under `egress_guard`; no knowledge tool argument can carry a model/route.
- [A2] `test_instruction_files_never_indexed` (fixture `AGENTS.md`/`.claude/skills` with injection).
- [A2] `test_private_paths_and_notebook_outputs_absent_from_every_tool_output` (all T01 exclusion fixtures served,
  every response scanned with `scan_text` + user-path regex -> no hits).
- [A2] `test_absent_evidence_after_exclusion_abstains` (question answerable only from an excluded file ->
  `no_evidence`; validator requires `[[abstain:no_evidence]]`).
Focused: `& $py -m pytest $K/test_injection.py -q`.
Real path: `& $py -m openbb_agents.hermes_integration.knowledge.probe --synthetic --adversarial` -> exit 0,
`denied=<n> escalations=0 egress=0`, scanned `hits=0`. Classification: **CODE-ONLY**.

## 5. PR batching (OM5)

One branch/PR for T01-T03 (estimate M, shared fixtures; splitting would ship a register without its exclusion
tests). Per-task cheap gates; local code/security/privacy reviews on the PR diff vs `portfolio`;
`scripts/local_ci.py --merged-with origin/portfolio` once. L6 text lands in the same PR; the owner runs it after
merge (as #1339 L5). Security review is mandatory: new LLM-exposed tools and a widened `HERMES_FINANCE_POLICY`.

## 6. Risks and open questions

| ID | Item | Recommended answer |
|---|---|---|
| R1 | Injection detection is heuristic; a model may still follow text. | Safety rests on server-side gate, argument-free tools and egress guard; the flag only aids grading. Test the obedient-coordinator case, not detector recall. |
| R2 | Repo docs carry internal ops detail or old issue numbers (prajoria numbering). | v1 excludes operations/handoff/archive/superpowers; register reviewer marks `historical`. |
| R3 | Status rots as PRs merge. | `status_evidence` required for `implemented`; `--check` fails on HEAD drift; register refresh is a reviewed diff. |
| R4 | FTS5 tokenizer misses identifiers like `documents.search`. | Separate exact identifier table built by regex over headings/IDs; tested. |
| R5 | Payload size vs Hermes context. | Hard caps (5 hits, 800/4000 chars); `knowledge_get_section` for one bounded section. |
| Q1 | Initial allowlist rows? | **NEEDS-OWNER-DECISION**: recommend gh-1312 bundle, merged HFP plans (`specs/gh-1338..1345`), `docs/designs`, `docs/OpenBBPlatform`, `docs/examples` (11 notebooks, markdown only, `notebook_role` per PF-04). |
| Q2 | Markdown cells of `notebooks/portfolio/*.ipynb`? | Exclude in v1 (PII-adjacent tree, CLAUDE.md notebook rules); revisit with a privacy review. |
| Q3 | Fetch and pin official tax pages? | No: pointer-only rows from research.md §8; fetching needs SOURCES-PINNED/TAX-YEAR. **NEEDS-OWNER-DECISION** to change. |
| Q4 | HEAD drift: serve pinned blob or exclude? | Serve pinned blob flagged `head_drift`, fail `--check`. |
| Q5 | Knowledge tools in ungated default mode? | No: only under `--policy-profile`; keeps #1339 default-mode invariants. |
| Q6 | Semantic/hybrid index? | Not planned; OPTIONAL-SEMANTIC, owner-gated, requires frozen exact-only baseline first (plan §11.4). |
| Q7 | Close #1378 on CODE-ONLY evidence or after L6? | **NEEDS-OWNER-DECISION** (lead may decide under D15): recommend merge on CODE-ONLY, close after L6 passes, since acceptance says "answers cite". |
| Q8 | Ship an answer-contract Hermes skill? | Not in v1; if wanted, hash-pinned via `skills_admission` in L6. |
| Q9 | Runtime enforcement of the answer contract inside Hermes? | Out of scope; only `pre_tool_call` is verified. Validator grades CODE-ONLY and L6. |

## Lead decisions (2026-11-28, under the owner's delegation)

- **Q1:** the initial allowlist is as recommended:
  - the gh-1312 bundle;
  - the merged HFP plans `specs/gh-1338..1345`;
  - `docs/designs` and `docs/OpenBBPlatform`;
  - `docs/examples`, markdown only, with `notebook_role`.

  Everything is repo-tracked and pinned by blob SHA, and the register itself is reviewed in the PR. The owner can narrow it later.
- **Q3:** official tax sources are pointer-only rows from research.md §8, with no fetching. Fetching needs SOURCES-PINNED and TAX-YEAR.
- **Drift gate:** HEAD drift is enforced by running `python -m openbb_agents.hermes_integration.knowledge.register --check` (with drift, no `--no-drift`) as a local-CI merge-gate step on any PR that touches registered docs or the register. The unit suite uses `--no-drift`, so it never fails on unrelated commits.
- **Q7:** merge on CODE-ONLY evidence with `Refs`, and close #1378 after the owner's L6 passes.
- **Q2, Q4–Q6, Q8–Q9:** accepted as recommended. There is no semantic index; that stays behind the OPTIONAL-SEMANTIC owner gate.
