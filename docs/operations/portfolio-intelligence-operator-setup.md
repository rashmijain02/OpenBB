# Portfolio Intelligence operator setup

How to run the Portfolio Intelligence Workspace backend and connect it to a
self-hosted or hosted OpenBB Workspace on any operating system. Issue #1273
(portable connector and operator setup); plan Step 9 and Workstream I in
[the Workspace-native terminal plan](../planning/portfolio-intelligence-workspace-native-terminal-plan.md).

All paths below are relative to the repository root. Replace placeholders in
angle brackets (`<token>`, `<backend-url>`, `<workspace-origin>`) with your own
values and keep those values out of commits, issues and logs.

This setup never edits the pinned `third_party/workspace` source, never
enables live order routing, and contains no operator credentials or data.

## 1. Choose a deployment

| Deployment | Auth mode | Bind host | Allowed origins |
|---|---|---|---|
| Local development, one user | `loopback-dev` | `127.0.0.1` | defaults |
| Local, with a bearer token | `required` | `127.0.0.1` | defaults |
| Self-hosted Workspace on another origin | `required` | `127.0.0.1`, or a private host behind TLS | that Workspace origin |
| Hosted Workspace (`https://pro.openbb.co`) calling a loopback backend | `required` (recommended) | `127.0.0.1` | `https://pro.openbb.co` |
| Shared server or container | `required` only | non-loopback, behind a TLS reverse proxy | the Workspace origin(s) you serve |

Workspace runs in the browser, so the browser, not a Workspace server, calls
this backend. A loopback backend is reachable only from the same machine's
browser.

## 2. Configuration

The backend and its launcher read configuration only from environment
variables. Nothing is read from command-line arguments, so a token never
appears in a process listing.

| Variable | Values | Default | Effect |
|---|---|---|---|
| `PI_WIDGET_BACKEND_AUTH_MODE` | `required`, `loopback-dev` | `required` | `required` needs a bearer token on every `/pi/*` call. `loopback-dev` disables auth and may bind only a loopback address. Any other value stops startup. |
| `PI_WIDGET_BACKEND_TOKEN` | secret string | none | Bearer token for `required` mode. Startup fails in `required` mode without it. |
| `PI_DEMO_MODE` | `only`, `fallback`, `off` | `fallback` | Demo versus live data; see section 7. |
| `PI_WIDGET_BACKEND_ALLOWED_ORIGINS` | comma-separated origins | `https://pro.openbb.co,http://127.0.0.1:1420` | CORS origins. Setting it replaces the defaults. |
| `PI_WIDGET_BACKEND_SKIP_WARMUP` | any non-empty value | unset | Skip the provider warmup for fast restarts. |

Set a token without echoing it.

PowerShell:

```powershell
$env:PI_WIDGET_BACKEND_AUTH_MODE = "required"
$env:PI_WIDGET_BACKEND_TOKEN = Read-Host -MaskInput "Backend bearer token"
```

Bash or zsh:

```bash
export PI_WIDGET_BACKEND_AUTH_MODE=required
read -rs -p "Backend bearer token: " PI_WIDGET_BACKEND_TOKEN && export PI_WIDGET_BACKEND_TOKEN
```

Generate a token with a password manager or
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Rotate it by
changing the variable and restarting the backend, then updating the Workspace
connection.

## 3. Start, stop and check status

The supported cross-platform launcher is the
[`serve` module](../../openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/serve.py).
Run it with the project environment's Python
(`.venv_portfolio/Scripts/python.exe` on Windows, `.venv_portfolio/bin/python`
elsewhere; see the repository `CLAUDE.md` for setup):

```bash
python -m openbb_portfolio_intel.widget_backend.serve start    # background, waits for health
python -m openbb_portfolio_intel.widget_backend.serve status   # health, auth, demo mode, manifests
python -m openbb_portfolio_intel.widget_backend.serve stop     # stops the backend that start launched
python -m openbb_portfolio_intel.widget_backend.serve run      # foreground; Ctrl+C stops it
```

Every command accepts `--host` (default `127.0.0.1`) and `--port` (default
`6120`). `run` also accepts `--reload` for source development; `start` accepts
`--timeout` (seconds to wait for health, default 180, because the first start
warms the provider package).

What the launcher guarantees:

- It validates the environment first and exits with code 2 on any problem:
  invalid auth or demo mode, a missing token in `required` mode, an unsafe
  origin, or `loopback-dev` with a non-loopback `--host`.
- It warns when `required` mode binds a non-loopback host.
- Launcher state (the pid record, a per-launch nonce and the backend log) lives
  in a per-user directory: `$XDG_STATE_HOME/openbb-pi-widget-backend` (default
  `~/.local/state/openbb-pi-widget-backend`) on Linux and macOS,
  `%LOCALAPPDATA%\openbb-pi-widget-backend` on Windows, or `--state-dir`. It is
  never the shared temporary directory. The directory is created with mode
  `0700`; on Linux and macOS the launcher refuses it when another user owns it
  or its mode is wider than `0700`. Symlinked state or log files are refused,
  and files are opened without following symlinks where the OS supports it.
- `start` gives the server it launches a fresh per-launch nonce through the
  environment (the server removes it from its own environment at import).
  `start`, `status` and `stop` send the bearer token only after the server on
  the port proves that nonce with an HMAC over a random challenge
  (`GET /health/instance`), so a process that bound the port first never
  receives the token. A port answered by any other process is refused.
- `start` checks that the pid the backend reports belongs to the process tree
  it spawned. On a timeout or any failed check it stops the whole launched
  process tree; on Windows the virtual environment's `python.exe` is a
  redirector and the real server is a grandchild, which is stopped too.
- `status` prints health, the server's auth mode, demo mode, allowed origins
  and manifest verdict, read from the authenticated `/health/details` with
  the `PI_WIDGET_BACKEND_TOKEN` of your shell (sent only as a bearer
  header). It reports only whether the token is set, never its value. Exit
  code 0 means healthy with valid manifests; a refused token is reported as
  `health details: unauthorized`. For a backend this launcher did not start,
  `status` checks liveness only and does not query details or send the token.
- `stop` signals only a pid that the proven backend reports on
  `/health/details`, that matches the record and that descends from the
  process `start` spawned, so it needs the same token. Otherwise it refuses.
  If the backend no longer answers, it removes the stale record without
  signalling anything. If the backend still answers `--timeout` seconds after
  SIGTERM, `stop` exits 1 and keeps the record.
- IPv6 binds work: `--host ::1` is probed on `::1`, and `--host ::` is probed
  on both `::1` and `127.0.0.1` because it may be dual-stack.
On Windows, `.\scripts\run_widget_backend.ps1` remains a supported foreground
launcher (always `127.0.0.1`, with `-AuthMode` and `-Token`); see
[local Workspace development](workspace-local-development.md).

**Limitation: bare uvicorn bypasses the guard; use the launcher.** The bind
check lives in the launcher because the app cannot see the address it is bound
to. `uvicorn openbb_portfolio_intel.widget_backend.main:app --host 0.0.0.0`
in `loopback-dev` mode starts an unauthenticated backend on every interface.
The backend still logs a loud WARNING at startup in `loopback-dev` mode.

## 4. Connect Workspace

1. Start the backend and confirm `status` exits 0.
2. In Workspace, open the backend connection dialog (**Connections → Connect
   Backend** on a self-hosted Workspace, **Data connectors → Custom backend**
   on hosted Workspace).
3. Name: `Portfolio Intelligence`. URL: `<backend-url>`, for example
   `http://127.0.0.1:6120` or the HTTPS URL of your reverse proxy.
4. In `required` mode, add a request header named `Authorization` with the
   value `Bearer <token>`. The backend accepts the token only in this header,
   never in the query string.
5. Save. Workspace reads `/widgets.json` and `/apps.json` (unauthenticated by
   contract) and lists the Portfolio Intelligence widgets and apps.

A page served over HTTPS must call an HTTPS backend unless the backend is on
loopback. Put any non-loopback backend behind TLS.

## 5. CORS origins

The backend allows credentials, so it only accepts exact origins:
`scheme://host[:port]`, with no path, query, wildcard or `null`. An unsafe
value stops startup with an error naming `PI_WIDGET_BACKEND_ALLOWED_ORIGINS`.

```bash
# Self-hosted Workspace on another port, plus hosted Workspace:
export PI_WIDGET_BACKEND_ALLOWED_ORIGINS="http://127.0.0.1:1420,https://pro.openbb.co"
# Only a private Workspace origin:
export PI_WIDGET_BACKEND_ALLOWED_ORIGINS="<workspace-origin>"
```

Include every origin a browser will load Workspace from. `localhost` and
`127.0.0.1` are different origins. CORS is not authentication; the bearer
token is.

## 6. Health and manifest validation

`GET /health` is an unauthenticated liveness probe and returns only:

```json
{"status": "ok"}
```

`GET /health/details` returns deployment detail and needs the normal
authentication: `Authorization: Bearer <token>` in `required` mode (401
without it). In `loopback-dev` mode it answers loopback clients only (403
otherwise). It never returns the token:

```json
{
  "status": "ok",
  "service": "portfolio-intel-widget-backend",
  "pid": 12345,
  "auth_mode": "required",
  "demo_mode": "fallback",
  "allowed_origins": ["https://pro.openbb.co"],
  "manifest": {"ok": true, "widgets": 61, "apps": 3, "issues": 5, "recorded_debt": 5, "new": [], "stale_baseline": []}
}
```

At startup the backend validates `widgets.json` and `apps.json` against the
pinned Workspace contract and the recorded debt baseline. A passing check is
logged at INFO; any new issue, stale baseline entry or unreadable manifest is
logged as a WARNING that names each problem. Startup continues so recorded
debt does not block local work; `status` exits 1 when the manifests are
invalid.

For the full report (CI uses the same command):

```bash
python scripts/validate_portfolio_workspace_manifests.py          # fails on issues beyond recorded debt
python scripts/validate_portfolio_workspace_manifests.py --strict # fails on any issue
```

Provider reachability is a separate, authenticated widget endpoint:
`/pi/health/providers`.

## 7. Demo mode and live mode

Every widget states its data state (`live`, `cached`, `demo`, `stale`,
`partial`, `unavailable`, `forbidden`) in its body and in `X-PI-Data-*`
headers; see the [backend README](../../openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/README.md).

| Goal | Setting | Result |
|---|---|---|
| Clean demo (onboarding, screenshots, tests) | `PI_DEMO_MODE=only` | Providers are never called; every widget serves labelled synthetic data. No credentials needed. |
| Live with a visible fallback | `PI_DEMO_MODE=fallback` (default) | Live or cached data when a provider answers, otherwise labelled demo data. |
| Live only (opt-in) | `PI_DEMO_MODE=off` | No synthetic fallback; a widget without data shows `unavailable` with a reason. Selecting the `demo` account stays explicit. |

Live data needs provider credentials in your own OpenBB user settings
(`~/.openbb_platform/user_settings.json`), never in this repository. Provider
order is `fmp_cached` first, then `fmp`.

## 8. Limits and missing entitlements

- **Provider entitlements.** Some FMP endpoints need a higher subscription
  tier. Those widgets show `unavailable` or `partial` with a reason instead
  of placeholder numbers. The tier registry is
  `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/plan_limited.py`.
- **One shared token.** `required` mode has a single bearer token; there are
  no per-user accounts or roles on widget routes. Use a reverse proxy with
  its own identity layer for shared deployments.
- **Read-only and paper only.** No widget routes live orders. Live trading
  endpoints need a server-side principal resolver that is not configured by
  default and answer 403 without one.
- **Hosted Workspace reach.** Hosted Workspace can reach only what the
  user's browser can reach; it does not proxy to a private backend.
- **Unauthenticated discovery.** `/`, `/widgets.json` and `/apps.json`
  are public by the Workspace contract, and `/health` is bare liveness. They
  contain no account data or deployment detail.
- **Agent surface.** The Workspace agent contract is separate from widgets
  and is configured on its own.

## 9. Logs and privacy

- Access logs keep the path and query keys but replace every query value
  with `<redacted>`, so `account_id`, `basket_id` or a query credential never
  reach the log. This applies to any uvicorn server running the app.
- `start` writes the backend log to the state directory. Treat it as local
  data: do not attach it to issues without reading it first.
- Responses never echo a non-demo account identifier, credential or home path.

## 10. Backups and provider-cache runbooks

The backend itself holds no durable state. Data it serves comes from:

| Store | Runbook |
|---|---|
| `fmp_cached` provider cache (MySQL) | [database configuration](../../openbb_platform/providers/fmp_cached/docs/DATABASE_CONFIGURATION.md) and [setup guide](../../openbb_platform/providers/fmp_cached/docs/SETUP_GUIDE.md) |
| End-of-day snapshots | [EOD snapshot refresh](eod-snapshot-refresh.md) |
| Cache jobs run through MCP | [MCP cache jobs](mcp-cache-jobs.md) |

The provider cache can be rebuilt from the provider, so a backup saves time
and API quota rather than unique data. Back it up with your database's own
tool (for example `mysqldump --single-transaction <database>` to a location
outside the repository), and never commit a dump. Restore by loading the dump
into an empty database configured as in the database configuration guide,
then restart the backend and confirm `status`.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| `status` says `health details: unauthorized` | Set `PI_WIDGET_BACKEND_TOKEN` in this shell to the backend's token, or in `loopback-dev` query from the same machine. |
| `status` says `health: unreachable` | The backend is not running on that host and port, or is still warming up; read the log in the state directory. |
| Launcher exits with code 2 | Read the `error:` lines; each names the variable to fix. |
| Workspace cannot load `/widgets.json` | The Workspace origin is missing from `PI_WIDGET_BACKEND_ALLOWED_ORIGINS`, or an HTTPS page is calling a non-loopback HTTP backend. |
| Widgets return 401 | The `Authorization: Bearer <token>` header is missing on the connection or the token differs from `PI_WIDGET_BACKEND_TOKEN`. |
| Every widget shows `demo` | `PI_DEMO_MODE=only` is set, or no provider answered under `fallback`; check `/pi/health/providers`. |
| `status` reports manifests `INVALID` | Run `python scripts/validate_portfolio_workspace_manifests.py` and fix each named issue. |
| `stop` refuses to signal | Another process owns the port; stop it where it was started. |
