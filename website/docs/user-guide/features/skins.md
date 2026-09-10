---
sidebar_position: 10
title: "Skins & Themes"
description: "Customize the forecast desk CLI with built-in and user-defined skins."
---

# Skins & Themes

Skins control the visual presentation of the Superforecasting Agent CLI: banner colors, spinner faces and verbs, response labels, prompt symbols, status colors, branding text, and tool activity prefixes.

Skins do not change the forecasting protocol, model selection, tool exposure, forecast ledger, or calibration behavior. Treat them as presentation only.

## Change Skins

```bash
/skin                # show the current skin and list available skins
/skin mono           # switch to a built-in skin
/skin mytheme        # switch to a custom skin
```

Or set the default skin:

```yaml
# ~/.superforecasting-agent/config.yaml
display:
  skin: default
```

Legacy `~/.hermes/config.yaml` remains readable during migration.

## Built-In Skins

| Skin | Description | Default branding |
|------|-------------|------------------|
| `default` | Aurora — lavender + rose on near-black | Superforecasting Agent |
| `gold` | Classic forecast gold (the former default) | Superforecasting Agent |
| `mono` | Clean grayscale terminal | Superforecasting Agent |
| `slate` | Cool blue terminal theme | Superforecasting Agent |
| `daylight` | Light theme for bright terminals | Superforecasting Agent |
| `warm-lightmode` | Warm light terminal theme | Superforecasting Agent |
| `ares` | Crimson and bronze palette | Superforecasting Agent |
| `poseidon` | Ocean-blue palette | Superforecasting Agent |
| `sisyphus` | Austere persistence palette | Superforecasting Agent |
| `charizard` | Ember and volcanic palette | Superforecasting Agent |

Built-in skins are visual palette wrappers around the same forecast desk runtime. They keep the fork-native product identity and do not change the agent's forecast protocol or standing style.

## Configurable Keys

### Colors

Color values are hex strings consumed by Rich and terminal renderers.

| Key | Purpose |
|-----|---------|
| `banner_border` | Startup banner border |
| `banner_title` | Banner title text |
| `banner_accent` | Banner section headers |
| `banner_dim` | Muted banner text |
| `banner_text` | Banner body text |
| `ui_accent` | General accent color |
| `ui_label` | Labels and tags |
| `ui_ok` | Success indicators |
| `ui_error` | Error indicators |
| `ui_warn` | Warning indicators |
| `prompt` | Interactive prompt text |
| `input_rule` | Rule above the input area |
| `response_border` | Response box border |
| `status_bar_bg` | TUI status bar background |
| `status_bar_text` | Status bar normal text |
| `status_bar_strong` | Status bar highlighted text |
| `status_bar_dim` | Status bar muted text |
| `status_bar_good` | Healthy status value |
| `status_bar_warn` | Warning status value |
| `status_bar_bad` | Bad status value |
| `status_bar_critical` | Critical status value |
| `session_label` | Session label color |
| `session_border` | Session ID border/dim color |
| `voice_status_bg` | Voice-mode status background |
| `selection_bg` | TUI selection background |
| `completion_menu_bg` | Completion menu background |
| `completion_menu_current_bg` | Active completion row background |
| `completion_menu_meta_bg` | Completion meta column background |
| `completion_menu_meta_current_bg` | Active completion meta background |

### Spinner

| Key | Type | Purpose |
|-----|------|---------|
| `waiting_faces` | list | Faces shown while waiting for a provider response |
| `thinking_faces` | list | Faces shown during model reasoning |
| `thinking_verbs` | list | Verbs shown in spinner messages |
| `wings` | list of pairs | Optional left/right decorations |

### Branding

| Key | Purpose | Forecast default |
|-----|---------|------------------|
| `agent_name` | Banner title and status display | `Superforecasting Agent` |
| `welcome` | Startup message | `Welcome to Superforecasting Agent. Type /forecast to inspect the desk or /help for commands.` |
| `goodbye` | Exit message | `Goodbye.` |
| `response_label` | Response box label | ` Forecast ` |
| `prompt_symbol` | Input prompt symbol | `>` |
| `help_header` | `/help` heading | `Forecast Desk Commands` |

### Other Keys

| Key | Purpose |
|-----|---------|
| `tool_prefix` | Character prefixed to tool output lines |
| `tool_emojis` | Per-tool emoji overrides for spinners and progress |
| `banner_logo` | Rich-markup ASCII logo |
| `banner_hero` | Rich-markup hero art |

## Custom Skins

Create YAML files under `~/.superforecasting-agent/skins/`. User skins inherit missing values from the built-in `default` skin, so you only need to specify the keys you want to change.

Legacy `~/.hermes/skins/` remains readable during migration and via inherited helper tools.

### Minimal Example

```yaml
name: research-green
description: Quiet research terminal

colors:
  banner_border: "#2f6f4e"
  banner_title: "#8fd6a5"
  banner_accent: "#65b985"
  prompt: "#d7eadf"
  response_border: "#65b985"

spinner:
  thinking_verbs:
    - "checking evidence"
    - "updating priors"
    - "reviewing assumptions"

branding:
  agent_name: "Forecast Desk"
  welcome: "Forecast Desk ready. Type /forecast or /help."
  response_label: " Forecast "
  prompt_symbol: ">"

tool_prefix: "|"
```

### Larger Template

```yaml
name: mytheme
description: My forecast desk theme

colors:
  banner_border: "#CD7F32"
  banner_title: "#FFD700"
  banner_accent: "#FFBF00"
  banner_dim: "#B8860B"
  banner_text: "#FFF8DC"
  ui_accent: "#FFBF00"
  ui_label: "#DAA520"
  ui_ok: "#4caf50"
  ui_error: "#ef5350"
  ui_warn: "#ffa726"
  prompt: "#FFF8DC"
  input_rule: "#CD7F32"
  response_border: "#FFD700"
  status_bar_bg: "#1a1a2e"
  status_bar_text: "#C0C0C0"
  status_bar_strong: "#FFD700"
  status_bar_dim: "#8B8682"
  status_bar_good: "#8FBC8F"
  status_bar_warn: "#FFD700"
  status_bar_bad: "#FF8C00"
  status_bar_critical: "#FF6B6B"
  session_label: "#DAA520"
  session_border: "#8B8682"

spinner:
  waiting_faces: ["(.)", "(o)", "(O)"]
  thinking_faces: ["(.)", "(o)", "(O)"]
  thinking_verbs: ["researching", "scoring", "calibrating"]
  wings:
    - ["[", "]"]

branding:
  agent_name: "Forecast Desk"
  welcome: "Forecast Desk ready. Type /forecast or /help."
  goodbye: "Goodbye."
  response_label: " Forecast "
  prompt_symbol: ">"
  help_header: "Forecast Desk Commands"

tool_prefix: "|"

tool_emojis:
  terminal: ">"
  web_search: "?"
  read_file: "#"

banner_logo: ""
banner_hero: ""
```

## Visual Skin Editor

[Hermes Mod](https://github.com/cocktailpeanut/hermes-mod) is an inherited community skin editor. It still uses Hermes naming because it was built for the upstream skin schema, but it can edit the same YAML fields.

What it does:

- lists built-in and custom skins
- edits colors, spinner settings, branding, tool prefix, and tool emojis
- generates `banner_logo` text art
- converts uploaded images into `banner_hero` ASCII art
- saves skin YAML and updates `display.skin`

Install options:

```bash
npx -y hermes-mod
```

```bash
git clone https://github.com/cocktailpeanut/hermes-mod.git
cd hermes-mod/app
npm install
npm start
```

Hermes Mod writes to the inherited skin location by default. Use `HERMES_HOME` to point it at the active forecast profile home when needed.

## Operational Notes

- Built-in skins load from `superforecasting_agent/runtime/skin_engine.py`, which keeps the inherited module name for compatibility.
- Unknown skins fall back to `default`.
- `/skin` updates the active CLI theme immediately for the current session.
- User skins under `~/.superforecasting-agent/skins/` should be preferred for new setups.
- Legacy user skins under `~/.hermes/skins/` remain migration-compatible.
- To make a skin permanent, set `display.skin` in `config.yaml`.
- Rich console markup is supported in `banner_logo` and `banner_hero`.
