---
sidebar_position: 2
title: "TUI"
description: "Run the forecast desk in a rich terminal UI with dashboard panels, lifecycle shortcuts, and non-blocking input."
---

# TUI

The TUI is the rich terminal surface for the Superforecasting Agent forecast
desk. It uses the same Python runtime, sessions, tools, and forecast ledger as
the classic CLI, but adds structured panels, modal pickers, non-blocking input,
and forecast lifecycle shortcuts.

Use it when you want to keep an active forecasting book open while researching,
updating, resolving, scoring, and reviewing questions.

## Launch

```bash
# Launch the TUI
superforecasting-agent tui

# Resume the latest TUI session
superforecasting-agent tui -c
superforecasting-agent tui --continue

# Resume a specific session by ID or title
superforecasting-agent tui -r 20260409_000000_aa11bb
superforecasting-agent tui --resume "macro desk"

# Run source directly for TUI development
superforecasting-agent tui --dev
```

You can also opt in with a forecast-native environment variable:

```bash
export FORECAST_TUI=1
superforecasting-agent
```

`superforecasting-agent --tui` and legacy `hermes --tui` remain accepted. New
docs prefer `superforecasting-agent tui`.

## Forecast Desk Panel

On startup the TUI can render the same forecast dashboard used by the CLI:

- active forecasts with current probability, as-of timestamp, close time, and
  stale-review state
- open alerts and watched-source changes
- review queue and next actions
- calibration health, recent scores, question-type performance, and ensemble
  component contribution
- learning memory, active lessons, and domain/topic error profiles
- recent backtests and baseline comparisons

Use `/forecast` at any time to refresh the panel. Use `/forecast <subcommand>`
to run any forecast CLI command from inside the TUI.

Use `/questions` for the fast forecast-book view: it renders numbered rows with
each question's current probability, delta, as-of freshness, close date,
confidence, evidence count, status, and title. Run `/questions <row>` to open a
structured forecast-detail panel without copying a forecast ID. That panel shows
the current probability, rationale, ledger counts, recent evidence, forecast
history, assumptions/reference classes, model runs, resolution state, and
follow-up actions. The numbered rows also carry that drill-down target in
mouse-enabled TUI terminals. `/questions <words>` and `/find <words>` search
active forecasts and review-queue items by title, topic, domain, latest
rationale, and latest evidence. `/open <row|id|words>` opens one unambiguous
match, `/note <row|words> -- <evidence>` appends evidence after resolving the
forecast, and `/revise <row|words> -- --probability <p> --rationale <why>`
appends an explicit probability update. The forecast book, search, detail, and
focused-action panels expose clickable quick-edit rows that prefill those
commands into the composer, so testers can work from visible rows without
copying forecast IDs. `/book` remains an alias.

Use `/ledger` when you want to browse the forecast store by view instead of by
ID. Supported views include `/ledger book`, `/ledger review`, `/ledger alerts`,
`/ledger evidence`, `/ledger learning`, `/ledger schedules`, `/ledger
calibration`, `/ledger backtests`, `/ledger all`, and `/ledger search <words>`.
Aliases `/desk`, `/store`, and `/state` open the ledger browser.

The TUI keeps those ledger views visible in a persistent `views` strip when
space allows. `Alt/Option+1` through `Alt/Option+9` jump to book, review,
alerts, evidence, learning, schedules, calibration, backtests, and all views.
On macOS, the shortcuts also work in terminals that send Option-number glyphs
instead of Meta chords. `Ctrl+F` starts forecast lookup; if you have typed a
phrase such as `inflation energy`, it converts it into `/find inflation energy`
so you can search the forecast book without remembering IDs.

On wide terminals, the TUI also keeps a compact forecast desk rail beside the
transcript. The rail is refreshed from the same dashboard data and keeps the
active book count, triage queue, at-risk forecasts, evidence-readiness gaps, and
recent backtest provenance visible while you research or update a question. The
watchlist rows keep each at-risk forecast's probability, delta, as-of date, close
date, confidence, status, and title visible; concrete watchlist rows can be
selected in mouse-enabled terminals to open the full forecast details. When
scored ensemble forecasts exist, the rail also shows the top contributing
forecast components. Concrete alert, doctor, and evidence next-action rows are
also selectable when the row contains a safe forecast command.

The composer also keeps a one-line `desk actions` strip derived from the same
triage state. It stays visible on narrower terminals where the side rail cannot
fit, and prioritizes alert review, stale-forecast review, benchmark-readiness
gaps, lesson review, self-checks, and backtest commands. Concrete commands in
the header, side rail, and action strip are selectable; placeholder examples
remain display-only until filled in.

Examples:

```text
/forecast
/forecast review --stale
/sources --question <id>
/forecast sources --question <id> --apply-watch
/forecast sources --question <id> --search-watched
/forecast sources --question <id> --search-watched --capture-candidates
/forecast import news <rss-or-atom-url> --question <id> --keyword <term>
/forecast import fivethirtyeight president --state PA --question <id>
/forecast import imf NGDP_RPCH/USA --question <id>
/forecast import census "2023/acs/acs5?get=NAME,B01003_001E&for=state:*" --question <id>
/forecast import socrata data.cdc.gov/abcd-1234 --question <id>
/forecast import ckan data.gov/energy --question <id>
/forecast import stooq AAPL.US --question <id>
/forecast import yahoo AAPL --question <id>
/forecast import coingecko bitcoin --question <id>
/forecast import secfacts 0000320193/Revenues --question <id>
/forecast import crossref "forecasting calibration" --question <id>
/forecast import githubrepo owner/repo --question <id>
/forecast import githubissues owner/repo --question <id>
/forecast import githubcommits owner/repo --question <id>
/forecast import githubactions owner/repo --question <id>
/forecast import pypi package-name --question <id>
/forecast import npm package-name --question <id>
/forecast import hackernews "product query" --question <id>
/forecast import reddit "topic query" --question <id>
/forecast import reliefweb "humanitarian query" --question <id>
/forecast import cisakev CVE-2026-0001 --question <id>
/forecast import clinicaltrials NCT01234567 --question <id>
/forecast import openfda BLA125514 --question <id>
/forecast import pubmed "forecasting calibration" --question <id>
/forecast backtest --benchmarks
/forecast schedule list
```

Use `--apply-watch` only after reviewing the source plan. It adds concrete
watched sources and skips placeholders that still need a feed, market,
repository, or company identifier. Use `--search-watched` after watches exist to
scan configured RSS/Atom streams for question-relevant candidate evidence;
adding `--capture-candidates` promotes matches into evidence without changing
the forecast probability.

## Forecast Shortcuts

Common desk workflows have direct slash commands:

| Command | Runs |
|---------|------|
| `/questions` | Show numbered current forecast questions, search with words, and drill into a row |
| `/ledger` | Browse forecast ledger views, search, and jump to review/evidence/learning/schedule state |
| `/find` | Search active forecasts and review queue by title, topic, or domain |
| `/open` | Open a forecast by row number, id, short id, or search words |
| `/note` | Append evidence after resolving a row/search phrase; quick-edit rows can prefill the draft |
| `/revise` | Append a probability update after resolving a row/search phrase; quick-edit rows can prefill the draft |
| `/update` | With arguments, append a forecast update by row, id, or search phrase; without arguments, update the app |
| `/new-forecast` | Create a scoreable question |
| `/ingest` | Stage a URL or file as a forecast candidate |
| `/evidence` | Add or inspect timestamped evidence |
| `/research` | Collect evidence without moving probability |
| `/base-rate` | Propose, add, or inspect reference-class work |
| `/model-run` | Inspect or record a quantitative forecast model run |
| `/trend-model` | Record a deterministic trend projection model run |
| `/update-forecast` | Inspect or append a probability snapshot; accepts row/search references |
| `/resolve` | Record a resolution |
| `/score` | Score a resolved question |
| `/postmortem` | Write structured error analysis |
| `/review` | Inspect stale or active forecasts |
| `/alerts` | List or acknowledge forecast alerts |
| `/sources` | List adapters, plan question-specific sources, or search watched RSS/Atom streams with `--search-watched` |
| `/calibration` | Show calibration summaries |
| `/lessons` | Review calibration lessons |
| `/errors` | Inspect domain/topic error profiles |
| `/backtest` | Run or inspect historical replay datasets |
| `/schedule` | List or manage scheduled self-checks |
| `/autopilot` | Manage autonomous forecast maintenance policies and proposals |
| `/self-check` | Create review alerts for stale or changed forecasts |
| `/performance` | Summarize recent backtest performance |
| `/readiness` | Inspect claim-readiness gaps |
| `/doctor` | Run combined pilot/readiness/operator checks |
| `/pilot-report` | Check tester pilot artifact coverage |
| `/pilot-cohort` | Seed prospective live pilot questions |
| `/export-packet` | Export an auditable forecast packet |
| `/import-packet` | Restore an exported forecast packet |
| `/pilot-aggregate` | Aggregate tester export packets |

These commands route to the forecast CLI and refresh desk counters when they
complete.

For autonomous maintenance, use `forecast autopilot enable <id>` or `/autopilot
enable <id>` with `--source` for optional feeds and `--required-source` for
critical feeds. If a required source fails, the run records a high-severity
alert and blocks refresh proposals until the source recovers.

## Why Use The TUI

- The forecast dashboard stays visible while you work.
- Input is non-blocking, so you can queue the next research or update command
  while a tool is still running.
- Model, session, approval, and clarification flows render as modal panels.
- Tool calls, reasoning, and results can stay expanded without flooding the
  scrollback.
- Slash command completion shows command descriptions and arguments.
- The status bar tracks active forecast workload, alerts, review pressure,
  open and stale reference classes, calibration samples, and learned lessons.

The TUI is not a second product surface. It is the terminal interface for the
same ledger and CLI workflows.

## Requirements

- Node.js 20 or newer
- An interactive TTY
- A configured model provider

`superforecasting-agent doctor` checks the local prerequisites. On first launch
the TUI installs Node dependencies into `ui-tui/node_modules` if needed. Packaged
installs may ship a prebuilt bundle.

### External Prebuild

```bash
export FORECAST_TUI_DIR=/path/to/prebuilt/ui-tui
superforecasting-agent tui
```

The directory must contain `dist/entry.js`.

## Keybindings

Keybindings mostly match the classic CLI:

- `Cmd+V` / `Ctrl+V` paste text, then fall back to clipboard/image attachment
  handling when supported.
- Slash autocompletion opens as a floating panel.
- `Ctrl+X` deletes a highlighted queued message.
- `Esc` cancels editing and unhighlights without deleting.
- `Ctrl+G` / `Ctrl+X Ctrl+E` open the current input buffer in `$EDITOR` for
  long prompt composition.
- `/terminal-setup` installs local VS Code, Cursor, or Windsurf terminal
  bindings for better `Cmd+Enter` and undo/redo behavior on macOS.

## Slash Commands

Forecast shortcuts are listed above. TUI-owned runtime commands render richer
output or overlays:

| Command | TUI behavior |
|---------|--------------|
| `/help` | Overlay with categorized commands |
| `/sessions` | Modal session picker with previews and token totals |
| `/model` | Modal model picker grouped by provider |
| `/skin` | Live theme preview |
| `/details` | Toggle reasoning/tool/subagent/activity panels |
| `/usage` | Token, cost, and context panel |
| `/agents` or `/tasks` | Live subagent and background-task overlay |
| `/reload` | Re-read the active profile `.env` without restarting |
| `/mouse` | Toggle mouse tracking and persist the setting |

Installed skills, quick commands, forecast-style overlays, and inherited
runtime slash commands continue to work. See [Slash Commands Reference](../reference/slash-commands.md).

## Status Line

The status line tracks both runtime state and forecast workload:

| Status | Meaning |
|--------|---------|
| `starting forecast desk...` | Session exists; tools and skills are still initializing |
| `ready` | Agent is idle and accepting input |
| `thinking...` / `running...` | The current turn is reasoning or running a tool |
| `interrupted` | The current turn was cancelled |
| `resuming...` | The TUI is attaching to a prior session |

The desk counters show active forecasts, open alerts, review queue size,
calibration sample counts, and learned lessons when available. The forecast desk
panel shows calibration component contribution when saved ensemble snapshots
have been scored. Its focused-action block keeps the top review question close
to the full research loop: show context, research, update, add base-rate work,
run a trend model, and resolve when criteria are met.

Other status-line fields include working directory, git branch, elapsed turn
time, session duration, context compression count, background task count, and a
visible warning when auto-approval/YOLO mode is active.

## Details Panels

The TUI uses details panels instead of long inline dumps:

```yaml
display:
  details_mode: collapsed
  sections:
    thinking: expanded
    tools: expanded
    subagents: collapsed
    activity: hidden
```

Runtime toggles:

```text
/details
/details tools collapsed
/details thinking expanded
/details activity hidden
```

Defaults are chosen for forecast work: reasoning and tools are visible, ambient
activity stays quiet, and subagent detail stays collapsed until used.

## Configuration

The TUI uses the standard active profile. There is no separate TUI config file.

```yaml
display:
  skin: forecast
  tui_status_indicator: unicode
  mouse_tracking: true
```

Relevant environment variables:

| Variable | Purpose |
|----------|---------|
| `SUPERFORECASTING_AGENT_TUI` / `FORECAST_TUI` / `HERMES_TUI` | Launch TUI mode when set to `1` |
| `SUPERFORECASTING_AGENT_TUI_RESUME` / `FORECAST_TUI_RESUME` / `HERMES_TUI_RESUME` | Resume the latest or a specific TUI session |
| `SUPERFORECASTING_AGENT_TUI_INLINE` / `FORECAST_TUI_INLINE` / `HERMES_TUI_INLINE` | Force primary-buffer rendering on or off |
| `SUPERFORECASTING_AGENT_TUI_THEME` / `FORECAST_TUI_THEME` / `HERMES_TUI_THEME` | Force `light`, `dark`, or a background hex color |
| `SUPERFORECASTING_AGENT_TUI_DIR` / `FORECAST_TUI_DIR` / `HERMES_TUI_DIR` | Use a prebuilt TUI bundle |
| `SUPERFORECASTING_AGENT_TUI_GATEWAY_URL` / `FORECAST_TUI_GATEWAY_URL` / `HERMES_TUI_GATEWAY_URL` | Attach to an existing gateway websocket |

Legacy `HERMES_TUI_*` names remain accepted for compatibility with the inherited runtime.

## Forecast Sessions

TUI and classic CLI sessions share the same session store under the active
agent home. You can start in one surface and resume in the other.

Forecast learning state is separate from interactive session transcripts. Questions,
evidence, reference classes, snapshots, scores, postmortems, backtests, alerts,
and lessons live in the forecast ledger.

See [Forecast Sessions](sessions.md) for session lifecycle, search, compression, and
export.

## Attaching To A Running Gateway

By default the TUI spawns its own local gateway process. To attach to an
existing gateway:

```bash
export FORECAST_TUI_GATEWAY_URL="ws://localhost:8765/api/ws?token=<auth-token>"
superforecasting-agent tui
```

When set, the TUI becomes a client of that gateway. This is the same channel the
web dashboard uses for the embedded terminal experience.

## Reverting To The Classic CLI

Unset `FORECAST_TUI` / `SUPERFORECASTING_AGENT_TUI` / `HERMES_TUI`, or launch the normal CLI command without `--tui`.

If the TUI cannot launch because Node, the bundle, or a TTY is unavailable, the
runtime prints a diagnostic and falls back instead of leaving the session
unusable.

## See Also

- [CLI Interface](cli.md)
- [Configuration](configuration.md)
- [Forecast Tools](features/tools.md)
- [Scheduled Self-Checks](features/cron.md)
- [Web Dashboard](features/web-dashboard.md)
