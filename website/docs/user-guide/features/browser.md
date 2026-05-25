---
title: Browser Automation
description: Inspect dynamic web sources when search and structured adapters are not enough.
sidebar_label: Browser
sidebar_position: 5
---

# Browser Automation

Superforecasting Agent includes browser tools for source inspection, dynamic pages, form-driven data, authenticated sites, visual verification, and pages that cannot be handled cleanly by `web_search`, `web_extract`, or a structured source adapter.

Browser output is not forecast truth. A page snapshot, screenshot, console log, or extracted table only affects a forecast after it is recorded in the forecast ledger with source, timestamp, reliability, relevance, stance, and reviewer context.

Use browser automation when:

- a source requires clicks, filters, login state, or form input
- a dynamic page hides data from normal extraction
- a visual layout or screenshot matters to the evidence review
- a local dashboard, model output, or data product needs inspection
- a domain adapter is unavailable or too narrow

Prefer structured adapters for repeatable scheduled work. For example, RSS/Atom, GDELT, FRED, BLS, World Bank, IMF DataMapper, SEC EDGAR, arXiv, OpenAlex, Wikipedia, Wikimedia pageviews, GitHub repository metadata/releases/issues/commits/actions, Hacker News, Reddit, Federal Register, NVD, Open-Meteo, USGS, NASA EONET, NWS alerts, OWID, Metaculus, Manifold, Kalshi, Polymarket, URL JSON/HTML, and CSV/JSON imports are usually better than a browser for backtests and scheduled self-checks.

## Backends

| Backend | Typical use |
|---|---|
| Browserbase cloud | Managed cloud browser sessions, anti-bot support, remote public sites |
| Browser Use cloud | Alternative cloud browser provider |
| Firecrawl cloud | Cloud browser plus scraping/extraction support |
| Camofox local | Local Firefox-based anti-detection browsing |
| Chromium-family CDP | Attach to your own Chrome, Brave, Chromium, or Edge via `/browser connect` |
| Local browser mode | Local Chromium driven by the inherited `agent-browser` CLI |

Pages are represented as accessibility-tree snapshots. Interactive elements get refs such as `@e1` and `@e2` for `browser_click` and `browser_type`.

Core capabilities:

- navigate and inspect dynamic pages
- click controls and fill forms
- capture accessibility snapshots
- capture screenshots and vision analysis
- inspect console logs and JavaScript errors
- handle native dialogs on CDP-capable backends
- pass through raw Chrome DevTools Protocol calls when CDP is available

## Forecasting Boundaries

When using browser tools for forecasting:

- Record source URLs, access time, publication time when available, and snapshot paths in the ledger.
- Treat screenshots and accessibility snapshots as evidence candidates, not durable probability state.
- Do not let a browser-derived claim change probability without `forecast update` and citations.
- For backtests, only use browser outputs that were available before the evidence cutoff.
- Avoid long-lived authenticated sessions for sources whose access policy forbids automated collection.

Example ledger flow:

```bash
forecast evidence add <id> \
  --source-url "https://example.com/dashboard" \
  --source-type browser-snapshot \
  --available-at "2026-05-22T10:30:00Z" \
  --reliability medium \
  --relevance high \
  --summary "Browser-inspected claim and why it matters."

forecast update <id> --require-citations
```

## Setup

:::tip Nous Subscribers
Paid [Nous Portal](https://portal.nousresearch.com) subscriptions can route browser automation through the [Tool Gateway](./tool-gateway) without separate Browserbase, Browser Use, or Firecrawl keys. Enable it with `superforecasting-agent model` or `superforecasting-agent tools`.
:::

### Browserbase Cloud Mode

Add credentials:

```bash
# ~/.superforecasting-agent/.env
BROWSERBASE_API_KEY=***
BROWSERBASE_PROJECT_ID=your-project-id-here
```

Get credentials at [browserbase.com](https://browserbase.com).

### Browser Use Cloud Mode

Add:

```bash
# ~/.superforecasting-agent/.env
BROWSER_USE_API_KEY=***
```

Get the API key at [browser-use.com](https://browser-use.com). If both Browserbase and Browser Use credentials are configured, Browserbase takes priority.

### Firecrawl Cloud Mode

Add:

```bash
# ~/.superforecasting-agent/.env
FIRECRAWL_API_KEY=fc-***
```

Then select Firecrawl as the browser provider:

```bash
superforecasting-agent setup tools
```

Open **Browser Automation** and select **Firecrawl**.

Optional settings:

```bash
# Self-hosted Firecrawl instance
FIRECRAWL_API_URL=http://localhost:3002

# Session TTL in seconds
FIRECRAWL_BROWSER_TTL=600
```

### Hybrid Routing For Private URLs

When a cloud provider is configured, the runtime auto-spawns a local Chromium sidecar for private, loopback, LAN, `.local`, `.lan`, and `.internal` URLs. Public URLs continue to use the cloud provider in the same session.

This keeps a cloud provider from seeing private URLs while still letting you inspect a local dashboard or data product.

The feature is on by default. Disable it with:

```yaml
# ~/.superforecasting-agent/config.yaml
browser:
  cloud_provider: browserbase
  auto_local_for_private_urls: false
```

With auto-routing disabled, private URLs are rejected unless `browser.allow_private_urls: true` is also set. Cloud providers usually cannot reach your private network even when that guard is disabled.

The sidecar uses the same inherited `agent-browser` CLI as local browser mode. Install it through:

```bash
superforecasting-agent setup tools
```

Post-navigation redirects from public URLs to private addresses remain blocked.

### Camofox Local Mode

[Camofox](https://github.com/jo-inc/camofox-browser) is a self-hosted Node.js server wrapping Camoufox, a Firefox fork with fingerprint spoofing. It provides local anti-detection browsing without cloud dependencies.

```bash
git clone https://github.com/jo-inc/camofox-browser
cd camofox-browser
make up
```

Useful maintenance commands:

```bash
make down
make reset
make fetch
make up ARCH=x86_64
make up VERSION=135.0.1 RELEASE=beta.24
```

For a custom persistent container:

```bash
make build
mkdir -p ~/.camofox-docker
docker run -d \
  --name camofox-browser \
  --restart unless-stopped \
  -p 9377:9377 \
  -p 6080:6080 \
  -p 5901:5900 \
  -e CAMOFOX_PORT=9377 \
  -e ENABLE_VNC=1 \
  -e VNC_BIND=0.0.0.0 \
  -e VNC_RESOLUTION=1920x1080 \
  -e MAX_OLD_SPACE_SIZE=2048 \
  -v ~/.camofox-docker:/root/.camofox \
  camofox-browser:135.0.1-aarch64
```

With VNC enabled, watch the browser at `http://localhost:6080` or connect a VNC client to `localhost:5901`.

Configure:

```bash
# ~/.superforecasting-agent/.env
CAMOFOX_URL=http://localhost:9377
```

Or use:

```bash
superforecasting-agent tools
```

When `CAMOFOX_URL` is set, browser tools route through Camofox instead of Browserbase or local `agent-browser`.

#### Persistent Browser Sessions

By default, each Camofox session gets a random identity. Cookies and logins do not survive across restarts. Enable profile-scoped persistence:

```yaml
# ~/.superforecasting-agent/config.yaml
browser:
  camofox:
    managed_persistence: true
```

Restart Superforecasting Agent after changing the config.

:::warning Nested path matters
The runtime reads `browser.camofox.managed_persistence`, not a top-level `managed_persistence`.

```yaml
# Wrong: ignored
managed_persistence: true
```
:::

What the runtime does:

- Sends a deterministic profile-scoped `userId` to Camofox.
- Skips server-side context destruction on cleanup.
- Scopes the `userId` to the active profile for profile isolation.

What it does not do:

- It does not force persistence on the Camofox server.
- It cannot preserve sessions if the Camofox server always creates ephemeral contexts.

Verify persistence:

1. Start Superforecasting Agent and your Camofox server.
2. Open a login site in a browser task and sign in manually.
3. End the browser task.
4. Start a new browser task.
5. Open the same site and confirm you are still signed in.

State used to derive the stable `userId` lives under `~/.superforecasting-agent/browser_auth/camofox/` or the profile-specific `$HERMES_HOME` equivalent. The actual browser profile lives on the Camofox server side.

Legacy `~/.hermes/browser_auth/camofox/` remains migration-compatible.

#### Externally Managed Camofox Sessions

When another app drives the visible Camofox browser, configure Superforecasting Agent to operate inside that same identity instead of spawning an isolated profile.

| Setting | Env var | Effect |
|---|---|---|
| `browser.camofox.user_id` | `CAMOFOX_USER_ID` | Camofox `userId` used when creating tabs |
| `browser.camofox.session_key` | `CAMOFOX_SESSION_KEY` | `sessionKey` sent on tab creation and adoption |
| `browser.camofox.adopt_existing_tab` | `CAMOFOX_ADOPT_EXISTING_TAB` | Reuse an existing tab before creating a new one |

Config form:

```yaml
browser:
  camofox:
    user_id: shared-camofox
    session_key: visible-tab
    adopt_existing_tab: true
```

Env var form:

```bash
CAMOFOX_USER_ID=shared-camofox
CAMOFOX_SESSION_KEY=visible-tab
CAMOFOX_ADOPT_EXISTING_TAB=true
```

When enabled, the runtime skips destructive cleanup at task end. Coordinate ownership if another app and Superforecasting Agent can drive the same Camofox `userId` simultaneously.

### Local Chromium-family Browser Via CDP (`/browser connect`)

Attach browser tools to a running Chrome, Brave, Chromium, or Edge instance via Chrome DevTools Protocol (CDP). This is useful when you need your own cookies, want to watch the session, or need a local/private source.

`/browser connect` is an interactive CLI slash command. It is not dispatched by the gateway. Run it in a terminal session:

```text
/browser connect
/browser connect ws://host:port
/browser status
/browser disconnect
```

If no browser is already running with remote debugging, the CLI attempts to auto-launch a supported Chromium-family browser on `http://127.0.0.1:9222`.

To start manually with CDP enabled, use a dedicated profile directory:

```bash
# Linux - Brave
brave-browser \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/sfa-brave-cdp \
  --no-first-run \
  --no-default-browser-check &

# macOS - Google Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/sfa-chrome-cdp \
  --no-first-run \
  --no-default-browser-check &
```

Then launch the CLI and run `/browser connect`.

When connected via CDP, browser tools operate on your live browser instance rather than a cloud or local `agent-browser` session.

### WSL2 + Windows Chrome: Prefer MCP Over `/browser connect`

If Superforecasting Agent runs inside WSL2 but the Chrome window runs on the Windows host, `/browser connect` is often not the best path.

- Windows Chrome usually needs to launch with remote debugging from Windows.
- WSL2 must reach the Windows host CDP port.
- A Windows-side browser MCP server can attach to Chrome and expose a cleaner bridge.

For that setup, prefer `chrome-devtools-mcp` through MCP support.

See:

- [Use MCP with Superforecasting Agent](../../guides/use-mcp-with-superforecasting-agent.md#wsl2-bridge-superforecasting-agent-in-wsl-to-windows-chrome)
- [MCP](./mcp)

### Local Browser Mode

If no cloud credentials are configured and you do not use `/browser connect`, browser tools can run through a local Chromium installation driven by the inherited `agent-browser` CLI.

Install:

```bash
npm install -g agent-browser
```

Then enable browser tooling through:

```bash
superforecasting-agent tools
```

## Tools

For simple information retrieval, prefer `web_search` or `web_extract`. Use browser tools when interaction, visual context, login state, or dynamic content matters.

### `browser_navigate`

Navigate to a URL. This initializes a browser session.

```text
browser_navigate(url="https://example.com")
```

### `browser_snapshot`

Return the current page accessibility tree. Interactive elements are referenced by IDs like `@e1`.

```text
browser_snapshot(full=true)
```

### `browser_click`

Click an element by ref:

```text
browser_click(ref="@e5")
```

### `browser_type`

Type into an input:

```text
browser_type(ref="@e3", text="forecast source query")
```

### `browser_scroll`

Scroll the page:

```text
browser_scroll(direction="down")
```

### `browser_press`

Press a key:

```text
browser_press(key="Enter")
```

### `browser_back`

Navigate back in browser history.

### `browser_get_images`

List image URLs from the current page.

### `browser_vision`

Take a screenshot and analyze it with a vision model. Use this when the accessibility snapshot misses important visual information, chart structure, or layout state.

Screenshots are stored under `~/.superforecasting-agent/cache/screenshots/` and cleaned up automatically. Legacy `~/.hermes/cache/screenshots/` remains migration-compatible.

### `browser_console`

Read console output and uncaught JavaScript exceptions. This is useful when a page silently fails or a local forecast dashboard needs debugging.

```text
browser_console()
browser_console(expression="document.querySelector('h1').textContent")
```

### `browser_cdp`

Raw Chrome DevTools Protocol passthrough for operations not covered by other tools.

Available when a CDP endpoint is reachable at session start: `/browser connect`, `browser.cdp_url`, or a CDP-capable backend.

Examples:

```text
browser_cdp(method="Target.getTargets")
browser_cdp(method="Network.getAllCookies")
```

Browser-level methods such as `Target.*`, `Browser.*`, and `Storage.*` omit `target_id`. Page-level methods such as `Page.*`, `Runtime.*`, `DOM.*`, and `Emulation.*` require a `target_id` from `Target.getTargets`.

### `browser_dialog`

Respond to native JavaScript dialogs:

```text
browser_dialog(action="accept")
browser_dialog(action="dismiss")
browser_dialog(action="accept", prompt_text="value")
```

Dialog policy is configured in `config.yaml`:

```yaml
browser:
  dialog_policy: must_respond
  dialog_timeout_s: 300
```

`must_respond` captures dialogs and waits for explicit action. `auto_dismiss` dismisses immediately while retaining dialog history.

## Session Recording

Record browser sessions as WebM files:

```yaml
browser:
  record_sessions: true
```

Recordings save under `~/.superforecasting-agent/browser_recordings/` when a session closes and are cleaned up automatically. Legacy `~/.hermes/browser_recordings/` remains migration-compatible.

For forecast work, record only when it helps audit source inspection or reproduce a decision. Recording can capture sensitive data.

## Safety And Limitations

- Browser tools are slower and less reproducible than structured source adapters.
- Accessibility snapshots can omit visual information.
- Large pages can be truncated or summarized.
- Cloud browser sessions consume provider credits and may have provider timeouts.
- Some providers or plans may not support proxies, keep-alive, CDP, or recordings.
- Downloads are not a default browser-tool workflow.
- Authenticated pages can create compliance and privacy obligations; record source provenance and reviewer decisions carefully.

For repeatable forecast maintenance, prefer watched sources, scheduled self-checks, and domain adapters. Use browser automation as the manual or semi-automated inspection layer around those systems.
