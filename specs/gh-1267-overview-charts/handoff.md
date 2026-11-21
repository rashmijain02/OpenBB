# Handoff: Repair Portfolio Overview chart contracts

| Field | Value |
|---|---|
| Parent issue | #1264 ([portfolio-ux][PROGRAM] Make Portfolio Intelligence a native OpenBB Workspace terminal) |
| Sub-issues | #1267 ([portfolio-ux] Repair Portfolio Overview chart contracts) |
| Branch | `feat/pi-overview-charts-gh-1267` |
| Base | `portfolio` @ `5650a0126` |
| HEAD | `5650a0126` (changes uncommitted; the lead commits) |
| Worktree | `.worktrees/pi-overview-charts-gh-1267` |
| Executor model | `claude-opus-5.5` (implementer subagent; route mode, plan Step 4 Overview subset) |

## What changed

- `pi_xray_sector` (`/pi/xray/sector`) and `pi_brinson_attribution` (`/pi/attribution`) now return a
  Plotly figure `{"data": [...], "layout": {...}}` by default. `raw=true` returns the previous rows
  unchanged. No new financial math: `widget_backend/overview_charts.py` only re-shapes rows.
  - X-Ray: one `pie` trace (labels = sectors, values = weights). Demo account: title
    "Sector Weights - Demo portfolio (synthetic)", `layout.meta.state = "demo"`. Any other account:
    no traces, title "... - Unavailable", annotation "No sector data: account resolver not wired for
    this account.", `meta.state = "unavailable"`. Raw mode keeps the old marker row.
  - Brinson: allocation/selection/interaction as stacked `bar` traces (`barmode: relative`), total
    active return as `scatter` markers, x = sector, y = percentage points (identical to the raw rows).
    Title names the demo book, window and benchmark; annotation says the book is synthetic. Each
    trace has `meta.glossaryKey`, and its hover text carries the glossary summary. Empty rows give
    a trace-free figure with `meta.state = "empty"` and a message.
- `widgets.json`: removed the non-schema `data.chart` (both) and `data.metricGlossary` (Brinson).
  `raw: true` is kept because both endpoints now support `raw=true`. The Brinson effect definitions
  and units moved into `description`.
- `workspace_contract_debt.json`: removed the five #1267 entries. No other entries were changed.

## Consumers found and how they keep working

| Consumer | Change |
|---|---|
| Local Viewer `portfolio/assets/local_viewer/index.html` (renders chart rows with `data.chart` + `metricGlossary`) | Added `isPlotlyFigure` / `plotlyFigureModel` / `renderPlotlyFigure`: pie traces map to the pie model, bar/scatter traces to the series model, `meta.glossaryKey` feeds legend help, trace-free figures show their title + annotation as a state message. |
| `viewer_render.test.mjs` Brinson test (read `data.chart` / `metricGlossary`) | Rewritten against a figure fixture; added pie and unavailable-state tests. |
| `test_widget_backend.py` row tests (3) | Now call `raw=true` (the row contract they guard). |
| `test_pi_terminal_f0.py::test_xray_sector_declares_pie_chart_mapping` | Replaced by `test_xray_sector_returns_plotly_pie_figure` (the file's own "Contract B"). `pi_xray_country` untouched (#1268). |
| `test_pi_terminal_terminology_1987.py` Brinson label/glossary case | Moved to `test_brinson_figure_carries_exact_labels_and_glossary_keys` (trace names, x-axis title, `meta.glossaryKey`, viewer glossary records exist). |
| `native_workspace_matrix.json` | Regenerated with `scripts/build_portfolio_workspace_matrix.py`; only the `pi_xray_sector.chart` mapping fields change to null. |
| Browser harness W3/W4 fixtures, story `human_expected`, manual guide, `test_brinson_fixture_uses_percentage_points` | Fixtures re-recorded from the worktree backend (same params); test reads the figure traces; expected text describes the chart. |
| `widget_backend/README.md` | Contract column updated. |
| MCP `story_adapters/attribution.py`, notebook-guide stories, capability policy, VS Code extension sample fixtures | No dependency on these response shapes (MCP uses the Brinson oracle directly; policy matches path prefixes; VS Code uses its own static copy). Unchanged. |

## Evidence

- **Red first:** new `test_overview_chart_contracts_1267.py` before the fix → `9 failed, 2 passed`
  (the 2 passing are the `raw=true` regression guards, which pass on old code because rows were the
  default). Log: `.dev-cycle/red-gh-1267.log`.
- **Mutation/revert (backend)**, each run against the new test file, each restored:
  Brinson ignores `raw` → 2 failed; unavailable X-Ray returns rows → 1 failed; demo X-Ray returns
  rows (pre-fix behaviour) → 1 failed; drop `meta.state` → 4 failed; drop `meta.glossaryKey` →
  1 failed; dummy trace in state figure → 2 failed; hover without glossary summary → 1 failed.
- **Mutation/revert (viewer)**: original `index.html` → suite fails (new helpers missing); glossary
  mapping disabled → Brinson test fails; empty-state message removed → trace-free test fails.
- **Targeted suites:** contracts, endpoint contracts, widget_backend, f0, terminology, tier2,
  f9/f10/f11, matrix, generate_widget_matrix, MCP attribution → all pass (429 passed together with
  the agents tests below).
- **Viewer:** `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/*.mjs` →
  106 passed, 0 failed.
- **Harness (non-live):** `pytest openbb_platform/tools/browser_test_harness/tests` → 45 passed,
  3 skipped (live tests need `BROWSER_HARNESS_LIVE=1`).
- **Full unit suite:** `python -m pytest openbb_platform/extensions/portfolio_intel/tests/unit -q -p no:cacheprovider`
  → `1652 passed, 2 skipped in 841.51s`, exit 0. Log: `.dev-cycle/verify-gh-1267.log`.
- **Real-path check:** the hermetic endpoint probe (real FastAPI app in a subprocess with scrubbed
  HOME, dotenv disabled, network blocked) → both widgets 200, Plotly figure, 0 contract issues:

```text
pi_xray_sector status 200 | keys ['data', 'layout'] | traces [('pie', 'Sector Weight')] | state demo | title Sector Weights - Demo portfolio (synthetic) | contract issues []
pi_brinson_attribution status 200 | keys ['data', 'layout'] | traces [('bar', 'Allocation Effect (%)'), ('bar', 'Selection Effect (%)'), ('bar', 'Interaction Effect (%)'), ('scatter', 'Total Active Return (%)')] | state demo | title Brinson-Fachler Attribution - Demo book, 1Y vs SPY | contract issues []
```

- **Lint:** `black --check` (88) clean on changed Python; `ruff check` clean on `main.py`,
  `overview_charts.py` and the new test; `pylint --rcfile=.pylintrc --disable=C0328` 10.00/10;
  `mypy --explicit-package-bases --ignore-missing-imports` → 0 errors in changed files (5 existing
  errors in imported `widgets_endpoints.py` / `_app.py`); `codespell` clean.
- **Claude review gate:** not run by the implementer; the lead owns it.

## Open questions for the owner

- Unavailable/empty figures have `data: []` plus a title/annotation, so no trace pretends to be
  data. The plan also says a Plotly widget must return non-empty `data`; this state is the
  exception. Keep it, or return a non-200 status for the unavailable state instead?
- `layout.meta.state` (`demo` / `unavailable` / `empty`) and trace `meta.glossaryKey` are standard
  Plotly `meta` fields that Workspace ignores. Step 6 (provenance) may want to standardize them.

## Not done / follow-ups

- Not verified in a real self-hosted Workspace browser render (plan Step 4.5); needs the lead's
  environment.
- `scripts/build_portfolio_workspace_matrix.py` still classifies chart widgets only by the removed
  `data.chart` mapping, so `pi_brinson_attribution` stays `contract-repair` in the matrix. It should
  learn Plotly-figure charts when the rest of Step 4 lands (no issue filed).
- `agents/tests/notebook_guide/test_manifests.py` fails 3 tests in this checkout because every
  notebook hash reads as stale (CRLF working tree under `core.autocrlf=true`); no notebook or agents
  file is changed here.
- Live harness drift check (`BROWSER_HARNESS_LIVE=1`) not run.
