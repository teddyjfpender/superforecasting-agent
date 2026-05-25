---
sidebar_position: 17
title: "Extending the Dashboard"
description: "Build dashboard themes, plugin tabs, shell slots, and backend routes for forecast-desk support surfaces."
---

# Extending the Dashboard

The Superforecasting Agent dashboard can be themed and extended without forking the repo. Treat these extensions as support surfaces around the CLI forecasting desk: inspectors, review panels, task widgets, calibration summaries, source-watch views, and admin tools are good fits. A dashboard plugin should not become a separate, unaudited forecast-writing path.

Forecast state still belongs in the forecast ledger. If an extension changes probabilities, imports evidence, records model runs, resolves questions, scores outcomes, or writes calibration lessons, it must route through the same forecast ledger commands or APIs as the CLI.

If you only want to use the dashboard, see [Web Dashboard](./web-dashboard). If you want terminal themes, see [Skins & Themes](./skins).

## Extension Layers

| Layer | Purpose |
|---|---|
| Themes | YAML files that adjust dashboard palette, typography, density, and optional component styles. |
| UI plugins | JavaScript bundles that register tabs, replace pages, or inject widgets into shell/page slots. |
| Backend plugins | Optional FastAPI routers mounted under `/api/plugins/<name>/`. |

All three are runtime extensions. They do not require rebuilding the dashboard bundle.

## Paths

New installs use the forecast-native profile home:

```text
~/.superforecasting-agent/dashboard-themes/
~/.superforecasting-agent/plugins/<name>/dashboard/
```

Migrated installs may still use:

```text
~/.hermes/dashboard-themes/
~/.hermes/plugins/<name>/dashboard/
```

Project-local plugins may also be discovered from:

```text
./.hermes/plugins/<name>/dashboard/
```

Project-local discovery is gated by the `SUPERFORECASTING_AGENT_ENABLE_PROJECT_PLUGINS` runtime flag. `FORECAST_ENABLE_PROJECT_PLUGINS` and inherited `HERMES_ENABLE_PROJECT_PLUGINS` remain accepted aliases.

## Themes

Create a YAML file in the dashboard theme directory:

```bash
mkdir -p ~/.superforecasting-agent/dashboard-themes
```

```yaml
# ~/.superforecasting-agent/dashboard-themes/forecast-desk.yaml
name: forecast-desk
label: Forecast Desk
description: Quiet dashboard theme for dense review surfaces

palette:
  background: "#101418"
  midground: "#d7dde5"
  foreground:
    hex: "#ffffff"
    alpha: 0.92

layout:
  radius: "0.375rem"
  density: compact

typography:
  fontSans: 'Inter, ui-sans-serif, system-ui, sans-serif'
  fontMono: 'ui-monospace, SFMono-Regular, Menlo, monospace'
  baseSize: "14px"
  lineHeight: "1.5"
  letterSpacing: "0"
```

Refresh the dashboard and select the theme from the theme switcher.

Common theme keys:

| Key | Use |
|---|---|
| `palette.background` | Main page background. |
| `palette.midground` | Primary text and accent base. |
| `palette.foreground` | Top-layer highlight. |
| `layout.radius` | Shared border radius token. |
| `layout.density` | `compact`, `comfortable`, or `spacious`. |
| `typography.fontSans` | Body font stack. |
| `typography.fontMono` | Code font stack. |
| `typography.baseSize` | Root font size. |
| `customCSS` | Optional scoped CSS, capped by the runtime. |

Use themes to make review and operations surfaces easier to scan. Avoid turning the dashboard into a marketing page; the CLI remains the main product surface.

## UI Plugins

A dashboard UI plugin is a directory with a manifest and a built JavaScript bundle:

```text
~/.superforecasting-agent/plugins/source-watch/dashboard/
  manifest.json
  dist/index.js
  dist/styles.css
```

Example manifest:

```json
{
  "name": "source-watch",
  "label": "Source Watch",
  "version": "0.1.0",
  "description": "Review watched sources and proposed ledger imports.",
  "entry": "dist/index.js",
  "style": "dist/styles.css",
  "tab": {
    "path": "/source-watch",
    "label": "Source Watch",
    "order": 80
  }
}
```

Example bundle:

```javascript
(function () {
  const SDK = window.__SUPERFORECASTING_AGENT_PLUGIN_SDK__;
  const React = SDK.React;

  function SourceWatchPage() {
    return React.createElement(
      "section",
      { className: "p-4" },
      React.createElement("h1", null, "Source Watch")
    );
  }

  window.__SUPERFORECASTING_AGENT_PLUGINS__.register("source-watch", SourceWatchPage);
})();
```

`window.__SUPERFORECASTING_AGENT_PLUGIN_SDK__` and `window.__SUPERFORECASTING_AGENT_PLUGINS__` are the canonical dashboard extension names. `window.__FORECAST_PLUGIN_SDK__` / `window.__FORECAST_PLUGINS__` are short aliases. The older `window.__HERMES_PLUGIN_SDK__` and `window.__HERMES_PLUGINS__` names remain stable compatibility identifiers for inherited plugins.

Plugins should use the SDK's React copy and shared UI helpers instead of bundling another React instance.

## Slot Plugins

Slot-only plugins can inject compact widgets without adding a tab. Set `tab.hidden` in the manifest and call `registerSlot`.

```json
{
  "name": "calibration-banner",
  "label": "Calibration Banner",
  "version": "0.1.0",
  "entry": "dist/index.js",
  "tab": { "hidden": true }
}
```

```javascript
(function () {
  const SDK = window.__SUPERFORECASTING_AGENT_PLUGIN_SDK__;
  const React = SDK.React;

  function Banner() {
    return React.createElement("div", null, "Calibration review due");
  }

  window.__SUPERFORECASTING_AGENT_PLUGINS__.register("calibration-banner", function () {
    return null;
  });
  window.__SUPERFORECASTING_AGENT_PLUGINS__.registerSlot(
    "calibration-banner",
    "pre-main",
    Banner
  );
})();
```

Useful slot patterns for the forecast fork:

| Slot pattern | Good use |
|---|---|
| `pre-main` | Domain-health notices and stale-forecast alerts above the active page. |
| `header-banner` | Compact global warning strip below the top navigation. |
| `sessions:top` | Session-level reminders or profile context. |
| `cron:top` | Scheduled self-check status. |
| `logs:top` | Importer or model-run failure notices. |
| `analytics:top` | Calibration and score summary widgets. |
| `forecast-desk:top` | Compact forecast-desk notices above the embedded terminal. |
| `forecast-desk:bottom` | Audit, export, or handoff widgets below the embedded terminal. |
| `plugins:top` | Plugin setup notices. |

Slot names are runtime-defined. Check the dashboard registry if a slot does not render. The inherited `chat:top` and `chat:bottom` names still render as compatibility aliases, but new forecast plugins should use `forecast-desk:top` and `forecast-desk:bottom`.

## Backend Routes

A plugin can add backend routes with `plugin_api.py`:

```text
~/.superforecasting-agent/plugins/source-watch/dashboard/plugin_api.py
```

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True}
```

The route mounts under:

```text
/api/plugins/source-watch/health
```

Backend routes run inside the dashboard process. Keep them small, authenticated through the dashboard's existing auth path, and careful about ledger writes. Prefer calling existing forecast services instead of duplicating ledger mutation logic in the plugin.

Inherited module names such as `hermes_cli` and `hermes_state` may still appear in imports while the fork preserves compatibility with upstream internals.

## Discovery and Reload

Discovery priority:

| Priority | Path | Scope |
|---|---|---|
| 1 | `~/.superforecasting-agent/plugins/<name>/dashboard/` | User profile |
| 2 | `plugins/<name>/dashboard/` | Bundled repo plugin |
| 3 | `./.hermes/plugins/<name>/dashboard/` | Project-local compatibility path |
| 4 | `~/.hermes/plugins/<name>/dashboard/` | Legacy profile path |

UI bundles can be rescanned from the dashboard. Backend routes are mounted at dashboard startup, so restart the dashboard after adding or changing `plugin_api.py`:

```bash
superforecasting-agent dashboard
```

The inherited `hermes dashboard` command remains a compatibility alias.

## Design Guidance

Good dashboard extensions for the forecast fork:

- active-forecast inspectors
- stale forecast and close-date monitors
- source-watch review queues
- model-run comparison panels
- calibration curves and score breakdowns
- postmortem review queues
- Kanban blocked-task summaries
- cron self-check status panels

Poor fits:

- a second chat product
- unaudited forecast update forms
- evidence importers that skip timestamping and source capture
- generic lifestyle widgets unrelated to forecasting quality
- plugin-local memory stores that bypass the forecast ledger

The primary workflow should stay: CLI forecast workflow first, dashboard support second, ledger as the source of truth.

## Troubleshooting

**Theme does not appear**: check the YAML file is under `~/.superforecasting-agent/dashboard-themes/` or the legacy theme directory, then refresh the dashboard.

**Plugin tab does not appear**: confirm `manifest.json` lives under `<profile-home>/plugins/<name>/dashboard/`, the `entry` path exists, and the bundle calls `window.__SUPERFORECASTING_AGENT_PLUGINS__.register(...)` with the same plugin name.

**Slot does not render**: verify the slot name exists in the dashboard registry and the plugin is not hidden by a theme or route condition.

**Backend route returns 404**: restart `superforecasting-agent dashboard`; plugin API routes are mounted at startup.

**Compatibility names look wrong**: `window.__HERMES_PLUGIN_SDK__`, `window.__HERMES_PLUGINS__`, `HERMES_ENABLE_PROJECT_PLUGINS`, and some `hermes_cli` module paths are inherited runtime identifiers. Prefer the forecast-native aliases for new plugins and document inherited names as compatibility support, not product identity.
