# Handoff: Release gates: local CI, Workspace performance and reliability

| Field | Value |
|---|---|
| Parent issue | #1264 (Make Portfolio Intelligence a native OpenBB Workspace terminal) |
| Sub-issues | #1274 (Add real Workspace browser and performance acceptance), #1275 (Run quality and local review release gates) |
| Branch | `feat/pi-release-gates-gh-1274` |
| Base | `portfolio` @ `041f292ea` |
| HEAD | `041f292ea` (Part 1 is uncommitted; the lead commits) |
| Worktree | `.worktrees/pi-release-gates-gh-1274` |
| Executor model | `claude-opus-5.5` (Part 1 implementer) |

## Part 1

Scope: plan Step 11 measurement (no backend edits) and a local CI-equivalent gate,
because GitHub Actions is down. Only new files; no existing source changed (PR #1295
still edits the widget backend).

### Changed paths (all new)

| Path | Purpose |
|---|---|
| `scripts/local_ci.py` | Runs the pull-request jobs from `.github/workflows/*.yml` locally |
| `scripts/tests/test_local_ci.py` | 33 tests: selection, path filters, `diff_files`, merged snapshot, closes-syntax, reporting |
| `scripts/benchmark_workspace_endpoints.py` | Hermetic cold/warm p50/p95 and cache-header benchmark |
| `scripts/tests/test_benchmark_workspace_endpoints.py` | 3 tests: percentile, aggregation, findings |
| `openbb_platform/extensions/portfolio_intel/tests/unit/_workspace_perf_probe.py` | Hermetic subprocess probe (reuses the #1266 network/dotenv guards) with a counting provider-tier fake |
| `openbb_platform/extensions/portfolio_intel/tests/unit/test_workspace_performance_1274.py` | 107 tests (a)-(d), 2 strict xfail gaps |

### `scripts/local_ci.py`

- Selection is read from the workflows themselves: `on.pull_request` branches,
  branches-ignore, types (default `opened/synchronize/reopened`), paths with `!`
  negation, paths-ignore, the YAML-1.1 `on: -> True` quirk, simple job `if:`
  (`==`, `!=`, `&&`, `||`, `always()`), and matrix expansion (`job[3.12]`).
- Changed paths for filters use `git diff base...head` (deletions included).
  `diff_files` replicates the workflow's grep pipeline exactly (substring
  `grep -v tests` / `integration`, so `scripts/` and any path containing
  `tests` are **not** linted by CI).
- Jobs run against an LF checkout of the exact commit (temp detached worktree,
  `core.autocrlf=false`). `--include-worktree` snapshots uncommitted files into
  an unreferenced commit; `--merged-with REF` builds an unreferenced merge commit
  (`git merge-tree` + `commit-tree -c user.name/-c user.email`), checks it out
  detached in a temp worktree and removes it. Conflicts fail loudly.
- Local runners: General Code Linting (lint contract test, codespell over the
  tree, then black / mypy `--platform linux` / pylint / ruff on `diff_files`,
  stop at first failure, cached clean Python 3.10 venv from the devtools pins
  under `.dev-cycle/local-ci/v/`), Markdown lint (docker, `--network none`),
  JSON/YAML validity (approximation: duplicate keys, multi-doc YAML, NaN JSON),
  closes-syntax (body passed via env, never shell-expanded; Git Bash, not WSL),
  PR description, auto-close fixtures, dual-MCP lock check, MCP 3.14 rejection,
  replays on 3.12/3.13 (wheels, clean venv, package mode, loopback HTTP replay on a
  free 127.0.0.1 port, profile tests, optional FinancialToolkit), inventory compare
  (base + head venvs, evidence tests, both profiles), Workspace contract
  (submodule at its pinned commit), harness stories and fixture staleness.
- Report: PASS / FAIL / SKIPPED(reason) / NOT-REPRODUCIBLE(reason); exit 1 only on
  a reproducible FAIL. Job env is scrubbed (provider, DB, token, proxy,
  PYTHONPATH), HOME is a temp dir, output is redacted.

### Benchmark (`--cold-runs 3 --warm 10`, fake failing tiers, ASGI in-process)

- 63 targets (61 widgets + 2 manifests), 0 findings. Backend import 0.8 s.
- Manifests: `/widgets.json` cold p95 15.8 ms, warm p95 2.5 ms; `/apps.json`
  cold 2.1 ms, warm 2.0 ms; both `Cache-Control: no-store`, UTF-8.
- Widgets: warm p95 median 1.9 ms, max 7.2 ms (budget 500 ms); cold p95 median
  2.1 ms. Slowest cold: whichever widget first triggers a lazy import
  (`pi_equity_analyst_forecasts` 2.78 s with fake tiers; with real, network-blocked
  tiers `pi_equity_profile_header` 2.63 s for the first `openbb` import), then
  `tt_segment_movers` 105 ms, `pi_brinson_attribution` 17 ms.
- Widget endpoints send no `Cache-Control` header at all (observation, not a gap).

### Gap tests (strict xfail, backend change after #1295)

1. `test_identical_refresh_makes_no_new_provider_calls`: no result/negative cache in
   front of the chain; every identical refresh re-walks every tier. Needs a
   short-TTL result + failure cache in `providers.retrofit.route_through_chain`.
2. `test_explicit_demo_selection_makes_no_provider_calls`: 14 book widgets default
   to `account_id=demo` yet walk the provider chain before serving the labelled
   synthetic book. Needs `with_chain` / `route_through_chain` to short-circuit when
   `provenance.explicit_demo(params)`.

Measured and passing: manifests `no-store`; per tab at most one chain walk per widget
and no duplicate `(family, tier, kwargs)`; refreshes linear (never compounding);
provider-health probes each tier once per 60 s TTL across all tabs and refreshes;
total outage with demo off gives no 5xx on any widget, `unavailable` wherever a
provider was attempted, and a synthetic non-demo account is `unavailable` (or 403
`forbidden` for the unknown basket on `pi_basket_analyst_consensus`).

## Evidence

Python: main checkout `.venv_portfolio`, PYTHONPATH = portfolio_intel, techtrade,
portfolio, mcp_server extension dirs. Full log: `.dev-cycle/verify-gh-1274.log`.

```text
red:   scripts/tests/test_local_ci.py -> ModuleNotFoundError: No module named 'local_ci'
red:   test_workspace_performance_1274.py -> FileNotFoundError (probe missing)
mutation: _PROVIDER_HEALTH_TTL_S = -1 -> test_provider_health_probes_once_per_ttl FAILED (reverted)
first green run surfaced: no-duplicate test XPASS(strict) -> made a normal test;
  14 outage failures = explicit demo default -> split into variant check + xfail gap 2
green: test_local_ci + test_benchmark + test_workspace_performance_1274
       + test_workspace_endpoint_contracts -> 267 passed, 2 xfailed in 40.7s
lint (devtools py3.10 venv, CI flags): black, ruff, mypy --platform linux, pylint 10.00, codespell -> clean
local_ci branch (--include-worktree): code-linting PASS (diff_files=0), json-yaml PASS (972 files),
  closes-syntax PASS, pr-description PASS, markdown NOT-REPRODUCIBLE (docker), labels NOT-REPRODUCIBLE; exit 0
local_ci base (head=origin/portfolio): same, closes-syntax out of scope; exit 0
local_ci --merged-with origin/feat/pi-techtrade-native-gh-1271: 14 jobs triggered;
  code-linting PASS (diff_files=3, black/mypy/pylint/ruff ran), json-yaml PASS,
  reject-unsupported-interpreter PASS; temp worktrees removed
bad PR body ("Closes #1274. Refs #1275."): closes-syntax FAIL, exit 1
```

Not run (heavy, host memory): MCP replays 3.12/3.13, inventory compare, Workspace
contract, harness stories, fixture drift. Their runners are implemented but unexercised.

The `/code-review` and `/security-review` gates were not run in Part 1.

## Open questions for the owner

- The lead's brief says `scripts/` is in `diff_files`; the workflow's regex
  `^(openbb_platform|cli)/` says it is not. The new files are lint-clean either way.
- Should the two xfail gaps become backend issues now, or after #1295 merges?

## Not done / follow-ups

- Part 2: real-browser Workspace acceptance (plan Step 10) and the Step 12 review gate.
- The heavy local_ci runners need one real run each when the host has memory to spare.

### Part 1 follow-up: local_ci fidelity fixes

- Harness jobs (`standalone-harness[*]`, `fixture-drift-check`) and
  `verify-workspace-contract` replay the workflow's own `run:` steps in
  `python:<setup-python version>` when docker is up. The tree is mounted read-only
  and copied to `/work`. The container starts with `--network none`, joins `bridge`
  only for the leading install steps, has 4 GB of memory, and is always removed.
  Without docker, a host harness failure caused only by the readiness timeout is
  reported as NOT-REPRODUCIBLE.
- `third_party/workspace` is populated at the pinned commit with
  `git clone --shared --no-checkout` from the main checkout's `.git/modules`.
  No network is used and the main checkout is not written. The previous FAIL was
  MAX_PATH in the poetry venv path. The host fallback now uses a short temp venv root.
- `compare-portfolio-inventories` translates the workflow's environment loop
  command by command, so `fmp_trading[agent]` installs after `pi_install.py`.
  The old runner pulled it into the first editable install.
- Six new tests (39 total). Rerun on #1295: harness x3, code-linting, workspace
  contract and inventory compare all PASS, exit 0.
