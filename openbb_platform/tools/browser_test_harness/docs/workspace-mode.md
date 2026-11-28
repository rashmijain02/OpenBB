# Workspace mode (Playwright driver)

Workspace mode drives hosted Workspace or the self-hosted UI at
`http://127.0.0.1:1420` via a Playwright-controlled Chromium session with a
persistent user profile.

Tracked in [#541](https://github.com/rashmijain02/OpenBB/issues/541).

## Contract

- **Persistent Chrome profile.** Cookies live under
  `~/.openbb_browser_test_harness/chrome_profile/`. First run opens
  Chromium visibly so the operator can log in to `pro.openbb.co`;
  subsequent runs reuse the session.
- **Managed self-hosted login.** Automation is enabled only when
  `workspace_url` is exactly `http://127.0.0.1:1420` (an optional trailing
  slash is normalized). The driver verifies the live page origin after
  navigation and again before reading or filling the ignored managed
  credential JSON. Redirects, aliases, alternate ports, HTTPS, userinfo, and
  URL-query variants are rejected without reading credentials. A reused
  profile counts as authenticated only on the exact origin's `/app` route
  family. Credential values never enter arguments, logs, screenshots, or
  reports.
- **Development TLS.**
  `ignore_local_self_hosted_https_errors=True` is available only with the exact
  self-hosted URL for a browser context that must load the self-signed loopback
  Portfolio backend. Construction rejects this option for hosted, aliased, or
  otherwise different Workspace URLs.
- **Random ephemeral backend port.** When `backend_url` is not passed,
  `WorkspaceDriver.setup()` calls `_pick_random_port()`
  (`socket.bind((127.0.0.1, 0))`) and spawns
  `uvicorn openbb_portfolio_intel.widget_backend.main:app` on it. The URL
  is appended as a `?backend_url=` query param on the Workspace
  navigation so the UI resolves widget requests against the isolated
  backend.
- **Attach mode.** Passing an explicit `backend_url=` (for example, when
  the operator is already running `openbb.sh api` on a known port)
  skips the spawn — the driver only owns the browser.
- **Teardown owns what it spawned.** The backend uvicorn is terminated
  on teardown only if the driver spawned it; attach-mode processes are
  left alone.

## Finding widgets in self-hosted Workspace (#1274)

Self-hosted Workspace sets `data-widget-id` on each grid item to a
per-instance UUID, not the backend widget id. The driver therefore reads
every rendered grid item (`selectors.RENDERED_WIDGETS_JS`) and maps a
backend widget to it by, in order:

1. the card root class `widget-<backend widget id>`;
2. a `data-widget-id` equal to the backend id (older hosted builds);
3. the exact widget title (`._left-navbar p.font-semibold`, the
   `widgets.json` `name`).

Visible means a non-zero box. Not blank is per type: a chart needs a
mounted Plotly plot (Workspace mounts none for a figure with `data: []`), a
table a grid, markdown and metric body text. A step whose endpoint backs a
widget **fails** when the widget is unseen or blank, whatever the step's
action; it never reports OK for a widget it did not see. With `app_name`
set (the CLI sets it per story), the driver first clicks the tab that holds
the widget in `apps.json`. `tests/fixtures/workspace_dom_selfhosted.html`
is the synthetic DOM the mapping is unit-tested on.

Workspace mounts a card only when its grid item is on screen. The driver
uses a 1600x1200 viewport and scrolls each widget's grid item into view
(and, to find an unmatched widget, every not-yet-mounted item) before it
judges it; a widget still unseen after that fails the step.

Some story widgets are not placed on any app tab and exist only in the
Workspace widget gallery (`selectors.GALLERY_ONLY_WIDGETS`). Their steps are
verified through the backend (status code only) and reported as
`GALLERY-ONLY (API-verified)`, counted apart from OK and FAIL. A test keeps
every story widget either placed in `apps.json` or on that list.

```powershell
python -m openbb_browser_test_harness.run --story techtrade --mode workspace `
  --workspace-url http://127.0.0.1:1420 --backend-url http://127.0.0.1:6120 `
  --headless --profile-dir "$env:TEMP\obb-harness-profile"
```

A browser profile holds a logged-in Workspace session (cookies). Keep it
**outside the repository**: use the default
`~/.openbb_browser_test_harness/chrome_profile/` (omit `--profile-dir`) or a
temporary directory, and delete a temporary profile after the run. Never
point `--profile-dir` inside the checkout, where it could be committed.

`--headed` (the default) shows Chromium; `--app-name` overrides the app
whose tabs are opened; `--dashboard "<visible name>"` opens the dashboard
that holds the app after login (otherwise the caller opens it).

## Why random ports?

The manual dev loop uses `openbb.sh api` bound to port `8000`. Hardcoding
the harness to the same port would collide with a running dev server
(mysterious 401s, mismatched CORS, cross-session state) or with a
concurrent harness invocation. `bind(0)` asks the kernel for a
guaranteed-free ephemeral port per run — no collision surface.

## Local run

```powershell
.\.venv_portfolio\Scripts\Activate.ps1
pip install -e openbb_platform/tools/browser_test_harness/[workspace]
python -m playwright install chromium

# Unit-level tests (no Chromium required)
pytest openbb_platform/tools/browser_test_harness/tests/test_workspace_driver.py -v -m "not integration"

# Live smoke — requires operator login on first run
$env:RUN_WORKSPACE_HARNESS = "1"
pytest openbb_platform/tools/browser_test_harness/tests/test_workspace_driver.py -v
```

## Debugging

Insert `await page.pause()` inside a step and re-run non-headless. This
opens the Playwright Inspector so you can step through selectors and
network traffic interactively.

For CI runs, the `workspace-harness` job in
`.github/workflows/browser-harness.yml` is `workflow_dispatch`-only and
reads the workspace URL from the `OPENBB_WORKSPACE_URL` repo secret;
the secret is **never** written into this file or committed anywhere.

## See also

- Manual guide: [`guides/portfolio-manual-guide.md`](../guides/portfolio-manual-guide.md)
- Standalone driver: `src/openbb_browser_test_harness/drivers/standalone_driver.py`
