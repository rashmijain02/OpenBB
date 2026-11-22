# Handoff: portable connector and operator setup

| Field | Value |
|---|---|
| Parent issue | #1273 (portfolio-ux: Add portable connector and operator setup) |
| Program parent | #1264 (portfolio-ux program: Make Portfolio Intelligence a native OpenBB Workspace terminal) |
| Branch | `feat/pi-operator-setup-gh-1273` |
| Base | `portfolio` @ `dff95c67c` |
| HEAD | `dff95c67c` plus uncommitted changes (the lead commits) |
| Worktree | `.worktrees/pi-operator-setup-gh-1273` |
| Executor model | `claude-opus-5.5` |

## Changes

| Path | Change |
|---|---|
| `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/operator_config.py` | New leaf module: CORS origin parsing (`PI_WIDGET_BACKEND_ALLOWED_ORIGINS`), access-log query redaction filter, loopback bind guard, launch preflight, manifest verdict against the debt baseline. |
| `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/serve.py` | New cross-platform launcher: `run`, `start`, `status`, `stop`. |
| `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/_app.py` | CORS origins from configuration; access-log redaction installed at import; report-only startup manifest validation in the lifespan; unauthenticated liveness `/health` and authenticated `/health/details`. |
| `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/README.md` | CORS paragraph corrected; new "Operator setup" section linking the guide. |
| `docs/operations/portfolio-intelligence-operator-setup.md` | New portable operator guide. |
| `openbb_platform/extensions/portfolio_intel/tests/unit/test_operator_setup_1273.py` | 78 tests. |

No manifest (`widgets.json`, `apps.json`), agent, MCP or `third_party/workspace` file changed.

## Evidence

- **New tests:** `pytest tests/unit/test_operator_setup_1273.py` -> 78 passed.
- **Backend regression:** `test_operator_setup_1273.py` + `test_widget_backend.py` -> 193 passed (round 1).
- **Full unit suite:** `pytest openbb_platform/extensions/portfolio_intel/tests/unit -m "not integration"` -> 2111 passed, 1 skipped, 21 deselected (round 3).
- **Launcher Pester tests:** `scripts/tests/Run-WidgetBackend.Tests.ps1` -> 9 passed, 0 failed (PowerShell launcher unchanged).
- **Lint (CI parity, changed non-test files):** codespell, black --check, mypy (`--no-site-packages`), pylint (`.pylintrc`, 10.00/10), ruff -> clean. markdownlint (`.markdownlintrc`) on the new guide -> clean; the README's two findings (bare fence, double blank line) predate this change.
- **Real-path check:** `serve start|status|stop` on 127.0.0.1:6121 in required mode with a throwaway token; log at `.dev-cycle/verify-gh-1273.log` (excerpt below).

Red first: on unmodified code the real uvicorn access line was
`"GET /widgets.json?account_id=SENTINELACCT7731&basket_id=SENTINELBASKET4419 HTTP/1.1" 200`
(leak); the new test module failed at collection (no `operator_config`/`serve`).

Mutation checks (each applied, targeted tests run, file restored):

```text
M1 no access-log filter install: 2 failed
M2 redact_query identity: 2 failed
M3 loopback-dev bind allowed: 6 failed
M4 hardcoded CORS origins: 2 failed
M5 wildcard accepted: 1 failed
M6 no startup validation in lifespan: 1 failed
M7 startup validation silent: 1 failed
M8 stop skips pid check: 1 failed
M9 status ignores manifest verdict: 1 failed
M10 baseline ignored: 1 failed
```

```text
start -> started; manifests: ok - 61 widgets, 3 apps, 5 issue(s), 5 recorded debt
status -> health: ok; auth mode: required; demo mode: only; exit 0
GET /health -> {"status":"ok"}; GET /health/details without token -> 401
status and stop without token -> exit 1, details unauthorized, nothing signalled
GET /pi/xray/sector without token -> 401; with Bearer -> 200
log: "GET /pi/xray/sector?account_id=<redacted>&basket_id=<redacted> HTTP/1.1" 401
start --host 0.0.0.0 in loopback-dev -> exit 2 (refusing to bind)
stop -> stopped; status -> unreachable, exit 1
```

## Review findings

No subagent review was run (the lead coordinates review). Self-review fixes applied (round 1):
startup validation catches any exception so it never stops startup; `/health/details` imports
`_shared` lazily so importing `_app` keeps its earlier contract (caught by
`test_backend_warmup_1957.py`).

## Lead decisions applied (round 2)

- Bind guard is launcher-only (accepted); the guide states "bare uvicorn bypasses the guard; use the launcher". The `loopback-dev` startup WARNING is unchanged.
- `/health` is now bare liveness, `{"status": "ok"}`. Pid, auth mode, demo mode, origins and the manifest verdict moved to `/health/details`.
  It needs the bearer token in `required` mode (401 without it) and in `loopback-dev` mode answers loopback clients only (403 otherwise). `serve status` and `serve stop` call it with the shell's `PI_WIDGET_BACKEND_TOKEN`, sent only as a header. `stop` refuses to signal when the details are refused.
- Red first: 14 tests failed before the change (the old `/health` exposed the fields; `fetch_details` did not exist). Mutations N1 to N6 are all killed (N5 needed a tighter assertion, then failed as expected).
- Provider-cache backup runbook: no change; the lead will file a follow-up issue. The `main.py` docstring is left as is.

## Review fixes (round 3, uncommitted on top of 3a9bce494)

- SECURITY-1: launcher state moved from the shared temp dir to a per-user dir
  (`$XDG_STATE_HOME` or `~/.local/state`, `%LOCALAPPDATA%` on Windows), created
  `0700`; on POSIX the owner and mode are checked and a wrong one is refused.
  Symlinked dirs, logs and state files are refused; files open `O_NOFOLLOW`
  and `0600`. `start` passes a per-launch nonce to the server (popped from the
  server's environment). The launcher sends the token only after an HMAC proof
  over a random challenge (`/health/instance`). `start` and `stop` also require
  the reported pid to descend from the spawned process.
- CODE-1: every `start` failure (timeout, failed proof, pid outside the tree)
  kills the whole spawned tree, children first (Toolhelp on Windows, `/proc`
  or `ps` elsewhere).
- CODE-2: `stop` exits 1 and keeps the record if the backend still answers
  after SIGTERM plus `--timeout`.
- CODE-3: probes are address-family aware (`::1`; `::` probes `::1` and
  `127.0.0.1`).
- Evidence: red 29 failed and 6 errors; green 78 passed; 18 mutations killed
  (R1 to R18); a real grandchild-kill test; real run with a foreign
  `http.server` on 6122, which saw only `GET /health/instance` and never the
  token.

## Not done / follow-ups

- Hosted `pro.openbb.co` connection was not exercised in a browser (Step 10 browser acceptance).
