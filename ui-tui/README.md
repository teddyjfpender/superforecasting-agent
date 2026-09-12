# Superforecasting Agent TUI

React + Ink terminal UI for the forecast desk. TypeScript owns the screen. Python owns sessions, tools, model calls, and most command logic.

```bash
superforecasting-agent tui
```

## What runs

The client entrypoint is `src/entry.tsx`. It exits early if `stdin` is not a TTY, starts `GatewayClient`, then renders `App`.

`GatewayClient` spawns:

```text
python -m tui_gateway.entry
```

Interpreter resolution order is: `SUPERFORECASTING_AGENT_PYTHON` → `FORECAST_PYTHON` → `HERMES_PYTHON` → `PYTHON` → `$VIRTUAL_ENV/bin/python` → `./.venv/bin/python` → `./venv/bin/python` → `python3` (or `python` on Windows).

The transport is newline-delimited JSON-RPC over stdio:

```text
ui-tui/src                  tui_gateway/
-----------                 -------------
entry.tsx                   entry.py
  -> GatewayClient            -> request loop
  -> App                      -> server.py RPC handlers

stdin/stdout: JSON-RPC requests, responses, events
stderr: captured into an in-memory log ring
```

Malformed stdout lines are treated as protocol noise and surfaced as `gateway.protocol_error`. Stderr lines become `gateway.stderr`. Neither writes directly into the terminal.

## Running it

From the repo root, the normal path is:

```bash
superforecasting-agent tui
```

The CLI expects `ui-tui/dist/entry.js` to exist, or the whole source code available in which to run `npm install` and `npm run dev`.
`superforecasting-agent --tui` and legacy compatibility entrypoints may still
route into the same client, but new usage and troubleshooting should use the
forecast-native `superforecasting-agent tui` command.

```bash
cd ui-tui
npm install
```

Local package commands:

```bash
npm run dev
npm start
npm run build
npm run lint
npm run fmt
npm run fix
```

Tests use vitest:

```bash
npm test         # single run
npm run test:watch
```

## App model

`src/app.tsx` is the center of the UI. Heavy logic is split into `src/app/`:

- `createGatewayEventHandler.ts` — maps gateway events to state updates
- `createSlashHandler.ts` — local slash command dispatch
- `navRoutes.ts` — the nav-tab registry: routes, overlay patches, active-view derivation (single source of truth for the top bar and the `Ctrl+G` view chords)
- `useComposerState.ts` — draft, multiline buffer, queue editing
- `useInputHandlers.ts` — keypress routing
- `useTurnState.ts` — agent turn lifecycle
- `overlayStore.ts` / `uiStore.ts` — nanostores for overlay and UI state
- `gatewayContext.tsx` — React context for the gateway client
- `constants.ts`, `helpers.ts`, `interfaces.ts`

The top-level `app.tsx` composes these into the Ink tree with forecast desk panels, `Static` transcript output, a live forecaster response row, prompt overlays, queue preview, status rule, input line, and completion list.

State managed at the top level includes:

- transcript and streaming state
- queued messages and input history
- session lifecycle
- tool progress and reasoning text
- prompt flows for approval, clarify, sudo, and secret input
- slash command routing
- tab completion and path completion
- theme state from gateway skin data

The UI renders as a normal Ink tree with `Static` transcript output, persistent forecast desk state, a live forecaster response row, prompt overlays, queue preview, status rule, input line, and completion list.

The intro panel is driven by `session.info` and rendered through `branding.tsx`.

## Hotkeys and interactions

Current input behavior is split across `src/app/useInputHandlers.ts` (global
routing, the `Ctrl+G` view chords, the `Ctrl+K` palette), `components/textInput.tsx`,
the full-screen views' own `useInput` handlers, and the prompt/picker components.
The static shortcut registry the in-app help and cheat-sheet render is
`src/content/keymaps.ts`.

### Forecast composer

| Key                             | Behavior                                                                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Enter`                         | Submit the current draft                                                                                                                                |
| empty `Enter` twice             | If queued messages exist and the agent is busy, interrupt the current run. If queued messages exist and the agent is idle, send the next queued message |
| `Shift+Enter` / `Alt+Enter`     | Insert a newline in the current draft                                                                                                                   |
| `\` + `Enter`                   | Append the line to the multiline buffer (fallback for terminals without modifier support)                                                               |
| `Ctrl+C`                        | Interrupt active run, or clear the current draft, or exit if nothing is pending                                                                         |
| `Ctrl+D`                        | Exit                                                                                                                                                    |
| `Cmd/Ctrl+G` / `Alt+G`          | Open `$EDITOR` with the current draft (use `Alt+G` in VSCode/Cursor — they bind the primary keystroke to Find Next)                                     |
| `Ctrl+L`                        | New session (same as `/clear`)                                                                                                                          |
| `Ctrl+V` / `Alt+V`              | Paste text first, then fall back to image/path attachment when applicable                                                                               |
| `Tab`                           | Apply the active completion                                                                                                                             |
| `Up/Down`                       | Cycle completions if the completion list is open; otherwise edit queued messages first, then walk input history                                         |
| `Left/Right`                    | Move the cursor                                                                                                                                         |
| modified `Left/Right`           | Move by word when the terminal sends `Ctrl` or `Meta` with the arrow key                                                                                |
| `Home` / `Ctrl+A`               | Start of line                                                                                                                                           |
| `End` / `Ctrl+E`                | End of line                                                                                                                                             |
| `Backspace`                     | Delete the character to the left of the cursor                                                                                                          |
| `Delete`                        | Delete the character to the right of the cursor                                                                                                         |
| modified `Backspace`            | Delete the previous word                                                                                                                                |
| modified `Delete`               | Delete the next word                                                                                                                                    |
| `Ctrl+W`                        | Delete the previous word                                                                                                                                |
| `Ctrl+U`                        | Delete from the cursor back to the start of the line                                                                                                    |
| `Ctrl+K`                        | Delete from the cursor to the end of the line                                                                                                           |
| `Meta+B` / `Meta+F`             | Move by word                                                                                                                                            |
| `!cmd`                          | Run a shell command through the gateway                                                                                                                 |
| `{!cmd}`                        | Inline shell interpolation before send; queued drafts keep the raw text until they are sent                                                            |

Notes:

- `Tab` only applies completions when completions are present and you are not in multiline mode.
- Queue/history navigation only applies when you are not in multiline mode.
- `PgUp` / `PgDn` are left to the terminal emulator; the TUI does not handle them.

### Prompt and picker modes

| Context                     | Keys                | Behavior                                          |
| --------------------------- | ------------------- | ------------------------------------------------- |
| approval prompt             | `Up/Down`, `Enter`  | Move and confirm the selected approval choice     |
| approval prompt             | `o`, `s`, `a`, `d`  | Quick-pick `once`, `session`, `always`, `deny`    |
| approval prompt             | `Esc`, `Ctrl+C`     | Deny                                              |
| clarify prompt with choices | `Up/Down`, `Enter`  | Move and confirm the selected choice              |
| clarify prompt with choices | single-digit number | Quick-pick the matching numbered choice           |
| clarify prompt with choices | `Enter` on "Other"  | Switch into free-text entry                       |
| clarify free-text mode      | `Enter`             | Submit typed answer                               |
| sudo / secret prompt        | `Enter`             | Submit typed value                                |
| sudo / secret prompt        | `Ctrl+C`            | Cancel by sending an empty response               |
| resume picker               | `Up/Down`, `Enter`  | Move and resume the selected session              |
| resume picker               | `1-9`               | Quick-pick one of the first nine visible sessions |
| resume picker               | `Esc`, `Ctrl+C`     | Close the picker                                  |

Notes:

- Clarify free-text mode and masked prompts use `ink-text-input`, so text editing there follows the library's default bindings rather than `components/textInput.tsx`.
- When a blocking prompt is open, the forecast composer hotkeys are suspended.
- Clarify mode has no dedicated cancel shortcut in the current client. Sudo and secret prompts only expose `Ctrl+C` cancellation from the app-level blocked handler.

### Interaction rules

- Plain text entered while the agent is busy is queued instead of sent immediately.
- Slash commands and `!cmd` do not queue; they execute immediately even while a run is active.
- Queue auto-drains after each forecaster response, unless a queued item is currently being edited.
- `Up/Down` prioritizes queued-message editing over history. History only activates when there is no queue to edit.
- Queued drafts keep their original `!cmd` and `{!cmd}` text while you edit them. Shell commands and interpolation run when the queued item is actually sent.
- If you load a queued item into the input and resubmit plain text, that queue item is replaced, removed from the queue preview, and promoted to send next. If the agent is still busy, the edited item is moved to the front of the queue and sent after the current run completes.
- Completion requests are debounced by 60 ms. Input starting with `/` uses `complete.slash`. A trailing token that starts with `./`, `../`, `~/`, `/`, or `@` uses `complete.path`.
- Text pastes are inserted inline directly into the draft. Nothing is newline-flattened.
- `Cmd/Ctrl+G` (or `Alt+G` in VSCode/Cursor, which intercept the primary keystroke for Find Next) writes the current draft, including any multiline buffer, to a temp file, suspends Ink, launches `$EDITOR`, then restores the TUI and submits the saved text if the editor exits cleanly.
- Input history is stored under the active forecast home, preferring `SUPERFORECASTING_AGENT_HOME` or `FORECAST_HOME` and falling back to compatibility home aliases.

## Rendering

Forecaster output is rendered in one of two ways:

- if the payload already contains ANSI, `messageLine.tsx` prints it directly
- otherwise `components/markdown.tsx` renders a small Markdown subset into Ink components

The Markdown renderer handles headings, lists, block quotes, tables, fenced code blocks, diff coloring, inline code, emphasis, links, and plain URLs.

Tool/status activity is shown in a live activity lane. Transcript rows stay focused on the operator's prompts and forecast-desk responses.

## Prompt flows

The Python gateway can pause the main loop and request structured input:

- `approval.request`: allow once, allow for session, allow always, or deny
- `clarify.request`: pick from choices or type a custom answer
- `sudo.request`: masked password entry
- `secret.request`: masked value entry for a named env var
- `session.list`: used by `SessionPicker` for `/resume`

These are stateful UI branches in `app.tsx`, not separate screens.

## Commands

The local slash handler covers the built-ins that need direct client behavior:

- `/help`
- `/quit`, `/exit`, `/q`
- `/clear`
- `/new`
- `/compact`
- `/resume`
- `/copy`
- `/paste`
- `/details`
- `/logs`
- `/statusbar`, `/sb`
- `/queue`
- `/undo`
- `/retry`

Notes:

- `/copy` sends the selected forecaster response through OSC 52.
- `/paste` with no args asks the gateway to attach a clipboard image.
- Text paste remains inline-only; `Cmd+V` / `Ctrl+V` handle layered text/OSC52/image fallback before `/paste` is needed.
- `/details [hidden|collapsed|expanded|cycle]` controls thinking/tool-detail visibility.
- `/statusbar` toggles the status rule on/off.

Anything else falls through to:

1. `slash.exec`
2. `command.dispatch`

That lets Python own aliases, plugins, skills, and registry-backed commands without duplicating the logic in the TUI.

## Event surface

Primary event types the client handles today:

| Event                    | Payload                                         |
| ------------------------ | ----------------------------------------------- |
| `gateway.ready`          | `{ skin? }`                                     |
| `session.info`           | session metadata for banner + tool/skill panels |
| `message.start`          | start forecaster response streaming             |
| `message.delta`          | `{ text, rendered? }`                           |
| `message.complete`       | `{ text, rendered?, usage, status }`            |
| `thinking.delta`         | `{ text }`                                      |
| `reasoning.delta`        | `{ text }`                                      |
| `reasoning.available`    | `{ text }`                                      |
| `status.update`          | `{ kind, text }`                                |
| `tool.start`             | `{ tool_id, name, context? }`                   |
| `tool.progress`          | `{ name, preview }`                             |
| `tool.complete`          | `{ tool_id, name }`                             |
| `clarify.request`        | `{ question, choices?, request_id }`            |
| `approval.request`       | `{ command, description }`                      |
| `sudo.request`           | `{ request_id }`                                |
| `secret.request`         | `{ prompt, env_var, request_id }`               |
| `background.complete`    | `{ task_id, text }`                             |
| `error`                  | `{ message }`                                   |
| `gateway.stderr`         | synthesized from child stderr                   |
| `gateway.protocol_error` | synthesized from malformed stdout               |

## Theme model

The client starts with `DEFAULT_THEME` from `theme.ts`, then merges in gateway skin data from `gateway.ready`.

Current branding overrides:

- agent name
- prompt symbol
- welcome text
- goodbye text

Current color overrides:

- banner title, accent, border, body, dim
- label, ok, error, warn

`branding.tsx` uses those values for the logo, session panel, and update notice.

## File map

```text
ui-tui/
  packages/forecast-ink/   forked Ink renderer (local dep)
  src/
    entry.tsx            TTY gate + render()
    app.tsx              top-level Ink tree, composes src/app/*
    gatewayClient.ts     child process + JSON-RPC bridge
    theme.ts             default palette + skin merge
    constants.ts         display constants, hotkeys, tool labels
    types.ts             shared client-side types
    banner.ts            ASCII art data

    app/
      createGatewayEventHandler.ts  event → state mapping
      createSlashHandler.ts         local slash dispatch
      navRoutes.ts                  nav-tab registry + overlay patches (routes)
      useComposerState.ts           draft + multiline + queue editing
      useInputHandlers.ts           keypress routing + Ctrl+G view chords
      useTurnState.ts               agent turn lifecycle
      overlayStore.ts               nanostores for overlays
      uiStore.ts                    nanostores for UI flags
      gatewayContext.tsx             React context for gateway client
      constants.ts                  app-level constants
      helpers.ts                    pure helpers
      interfaces.ts                 internal interfaces

    content/
      keymaps.ts         static shortcut + per-view guide registry (the
                         cheat-sheet / in-app help source of truth)
      hotkeys.ts, marketProviders.ts, newsFeedCatalog.ts, …  static content

    components/
      # chrome + chat spine
      appChrome.tsx      status bar, input row, completions
      appLayout.tsx      top-level layout composition + the per-view panes
      appOverlays.tsx    overlay routing (pickers, prompts)
      navBar.tsx         clickable top view strip (routes via app/navRoutes.ts)
      branding.tsx       banner + session summary
      markdown.tsx       Markdown-to-Ink renderer
      maskedPrompt.tsx   masked input for sudo / secrets
      messageLine.tsx    transcript rows
      modelPicker.tsx    model switch picker
      prompts.tsx        approval + clarify flows
      queuedMessages.tsx queued input preview
      sessionPicker.tsx  session resume picker
      textInput.tsx      custom line editor
      thinking.tsx       spinner, reasoning, tool activity
      paletteOverlay.tsx Ctrl+K command palette
      helpOverlay.tsx    the h / ? quick-help modal (renders content/keymaps.ts)

      # full-screen views (one per nav tab — see app/navRoutes.ts)
      homeLanding.tsx        Home landing + the agents chip
      deskView.tsx           the live Desk (redesigned forecast workspace)
      deskTabs.tsx           the Desk lens-tab strip (built by lib/deskGroups.ts)
      forecastsWorkspace.tsx exported Desk building blocks (ThesisDeskRead,
                             panel/chart helpers) that deskView imports; its
                             old full-view orchestrator is no longer rendered —
                             deskView IS the Desk
      operationsCockpit.tsx  the Operations lens (v0.19.0 operations cockpit)
      marketsView.tsx        Markets: data tape, Models mode, prediction markets
      newsView.tsx           News headline feed
      messagingView.tsx      Signal messaging bridge
      calendarView.tsx       market-close / resolution calendar
      alertsView.tsx         Warnings: tiered alert queue + automode passes
      calibrationView.tsx    calibration report
      obsidianView.tsx       Docs: Markdown vault + LaTeX workspace
      agentsOverlay.tsx      subagent / spawn-tree monitor
      demoVizView.tsx        chart-engine demo gallery (dev-flag only:
                             FORECAST_TUI_DEV_DEMO_VIZ=1)
      hooksView.tsx          forecast hooks browser (+ hooksWizard.tsx)
      helpView.tsx           full-screen Help reference
      …plus view-specific modals/panes (prediction-market tables + detail,
      model chat/list modals, feed + provider modals, LaTeX docs shell, desk/
      and forecast/ subdirectories, and more)

    hooks/
      useCompletion.ts   tab completion (slash + path)
      useInputHistory.ts persistent history navigation
      useQueue.ts        queued message management
      useVirtualHistory.ts in-memory history for pickers

    lib/
      history.ts         persistent input history
      messages.ts        message formatting helpers
      osc52.ts           OSC 52 clipboard copy
      rpc.ts             JSON-RPC type helpers
      text.ts            text helpers, ANSI detection, previews
      deskGroups.ts      Desk lens-tab builder (thesis lenses → All → Operations)
      …plus many view-support modules (market data/charts, prediction-market
      stores, news feeds, Signal client, LaTeX rendering, viz engine, etc.)

    types/
      forecast-ink.d.ts    type declarations for the local @superforecasting/ink renderer

    __tests__/           vitest suite
```

Related Python side:

```text
tui_gateway/
  entry.py               stdio entrypoint
  server.py              RPC handlers and session logic
  render.py              optional rich/ANSI bridge
  commands_rpc.py        native command dispatch
  command_routes.py      backend/terminal command ownership
```
