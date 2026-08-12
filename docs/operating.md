# Operating the Desk (TUI)

The TUI is the forecasting desk as a live surface: a set of full-screen views over
the same ledger, gateway, and jobs the CLI drives. Launch it with `forecast tui`
(or `superforecasting-agent --tui`; bare `forecast` prints the plain-text desk
dashboard instead). This guide covers navigation, the help
system, the Desk workflow tiers, mass-select, the Operations cockpit, theses,
markets and prediction markets, warnings, the agents chip, and the rest of the
view strip — with the real keys.

> Keys here are code-verified against `ui-tui/src/`. The definitive per-view
> shortcut list is always the in-app help (`h`), which is generated from the same
> keymap the app runs.

## Views and navigation

The top-level views (registry: `ui-tui/src/app/navRoutes.ts`) are **Home, Desk,
Markets, News, Messaging, Calendar, Warnings, Calibration, Docs, Agents, Hooks,
Help** — 12 by default. A 13th, **Demo Vis**, ships behind a dev flag: unless
`FORECAST_TUI_DEV_DEMO_VIZ=1` is set (also honoured:
`SUPERFORECASTING_AGENT_TUI_DEV_DEMO_VIZ` / `HERMES_TUI_DEV_DEMO_VIZ`, with the
usual `1|true|yes|on` values) the route is **absent, not hidden** — it drops out
of `NAV_TABS`, and every entry point (a NavBar click, a `Ctrl+G` chord) dies on
that same one membership check. Three ways to move between the views:

- **Click** a tab in the top view strip.
- **`Ctrl+G` then a letter** — a leader chord (`ui-tui/src/content/keymaps.ts`):
  `h` Home, `d` Desk, `m` Markets, `n` News, `w` Warnings, `c` Calibration, `k`
  Hooks, `a` Agents, `o` Docs. It is `Ctrl+G` (not a bare `g`) so a message
  starting "g…" is never hijacked. Messaging, Calendar, and Help have no chord
  letter (Messaging is deliberately dropped from the chord set; Calendar's `c`
  belongs to Calibration) — reach them by click or `Ctrl+K`.
- **`Ctrl+K`** opens the command palette to run any `/` command from anywhere.

**Do not confuse views with lenses.** `Alt/Option+1..9` (and the portable
`/1..9`) select **forecast lenses** — book, review, alerts, evidence, learning,
schedules, calibration, backtests, all — not the top-level views.

## The help system

Press **`h`** (or **`?`**) on any view to open the shared help modal. It shows a
prose "how to use this view" guide followed by a grouped shortcut table — the
global keys plus that view's keys; press `Tab` to expand every view's keys. When
the composer is focused, a leading "h" types normally instead of opening help.
(The **Help** tab in the strip is a separate, larger full-screen reference; the
`h`/`?` modal is the quick overlay.)

## The Desk

The Desk (`ui-tui/src/components/deskView.tsx`) is the forecast book as an
actionable table. `Enter` opens a row's detail modal; `/` filters, `r` refreshes,
`o`/`O` change and reverse the sort, `n` starts a new question, `R` resolves,
`s` opens settings.

### The action tiers: `u` / `U` / `A` / `T`

These four keys are the heart of the desk, in ascending cost and autonomy:

| Key | Tier | What it does |
| --- | --- | --- |
| `u` | **re-arm** | Cheap and request-based. Marks the review schedule **due now** so the next autonomous cron tick reforecasts it. Does not itself run a forecast. |
| `U` | **update now** | The deterministic re-pool of watched sources, launched as one **detached `refresh` job** — durable and re-attachable, survives leaving the Desk. Reports an honest tally (updated / unchanged / no-sources). No LLM. |
| `A` | **agent run** | Fans the full formal reforecast flow over the selection as a detached job (`forecast.reforecast.start`) — LLM per question, every commit gate applies, quorums start where required. |
| `T` | **task** | Opens a free-text instruction modal over the selected batch and dispatches it (`forecast.desk.task`), riding the same agent-job progress surface. |

`U`, `A`, and `T` run as background jobs on the [one job runtime](architecture.md#arc-b--one-detached-job-runtime); in-flight rows show a marker in the gutter and you can leave and re-attach.

**Selection scope** cascades: an explicit marked set wins; otherwise, on a
thesis **lens row** the action applies to **all member questions** of that
lens; otherwise it is the single cursor row.

### Mass-select

- **`Space`** marks the cursor row and advances (mutt-style).
- **`Shift+↑/↓`** extends a contiguous range.
- **`Esc`** clears in stages: first the marks, then the filter, then closes.

The header shows a running "· N selected" count, and a tier key then fans out over
every marked row.

### Lens tabs

The Desk groups the book into **lens tabs** (`ui-tui/src/lib/deskGroups.ts`):
one lens per **real thesis** — ordered by member count, so the largest ("major")
thesis leads — then **All**, then **Operations** (the [operations
cockpit](#the-operations-cockpit)). The earlier factor/tag pseudo-lenses and the
separate ◇ Bench lens were removed: ForecastBench backtest replays are still
carved **out** of the All catch-all, they just no longer get a lens of their
own. `Tab` / `→` / `l` move to the next lens, `←` to the previous. On a thesis
lens the top "lens row" opens the aggregate read.

### The Operations cockpit

The last Desk lens is **Operations** — the v0.19.0 "operations cockpit"
(`ui-tui/src/components/operationsCockpit.tsx`), a read-only reliability
dashboard over the desk's autonomous machinery, rendered in place of the
forecast table while its tab is active. It rides the same `forecast.workspace`
payload as the rest of the Desk: the response carries an `operations` block
built by the ledger's `operational_cockpit()` aggregate
(`forecasting/dashboard/core.py`).

What it shows, top to bottom:

- **High-severity line** — open / awaiting-execution / unowned counts, SLA
  breaches, oldest age, human escalations, and assigned owners.
- **Source-event lifecycle** — pending / estimating / stranded / open-failure /
  processed counts, the 24h arrivals-vs-terminal net, oldest and P90 pending
  ages, and per-source low-content-yield warnings.
- **Alert flow and human inbox** — 24h alert arrivals / closures / net, the
  executable share, closure-latency P90, and the awaiting-human queue (each
  item with its age, escalation owner, and available recovery actions).
- **Lane table** — per work lane: backlog, oldest age against its SLO, breach
  count, and today's claims against the daily budget.
- **30-day flow** — arrivals and services sparklines from task history.
- **Measured cost** — spend today and total, model and source call counts, cost
  per material update and per resolution, and the measurement basis.
- **Coverage and capacity** — active questions, service-mode invariant gaps,
  unclassified actives; serviced / monitor-only / resolution-only / resolved /
  archived counts; the active utility model with sample size and concordance.
- **Rate-limit pressure** — shown only when a bucket has denied requests.

It is a status surface, not an action surface: the recovery actions listed on
human-inbox items run through the agent or the CLI, and the primary transcript
is never replaced — the cockpit lives inside the Desk view.

## Theses and event-MC

A **thesis** aggregates tagged member forecasts into a single health-and-score
read. Its detail pane (`ThesisDeskRead` in `forecastsWorkspace.tsx`) shows a trend
block, the aggregate (health %, score /100 with a band, coverage, effective n,
correlation ρ), an analyst note, a per-member contribution table, entities,
triggers, and caveats.

The **health %** is the **event Monte Carlo**: a thesis is modeled as a joint
threshold event — the probability that at least K of its members succeed —
computed by a Gaussian-copula Monte Carlo over the binary members
(`simulate_thesis_event` in `forecasting/thesis.py`). Read health % as "the
probability the thesis is still alive." There is no separate event-MC screen; it
is the engine behind thesis health, and it also surfaces as the macro Thesis Layer
rows in Markets.

## Markets and prediction markets

The Markets view (`ui-tui/src/components/marketsView.tsx`) has two modes, toggled
with **`m`**:

- **Data** — live quotes by category from the [market-data plane](architecture.md#arc-c--server-side-market-data-plane). `Tab` / `←→` switch category, `d` adds a data provider, `i` shows data warnings (e.g. a missing key and how to fix it), `a` asks the agent, `/` filters.
- **Models** — an agentic quant-research workspace: `n` new model, `Enter` open, `c` chat/refine, `w` rewrite on fresh data, `e` export JSON, `←→` browse versions, `F` spin the model off into a Desk forecast leg, `r` refresh, `R` retry a failed build, `x` delete.

**Prediction Markets** is a pseudo-category on the Data tab (Polymarket + Kalshi);
jump to it with **`p`** (`usePmSection.ts`, `predictionMarketsTable.tsx`):

- Each **event row** shows a **de-vigged** top-outcome probability, volume, close,
  and a venue chip. **`→`** or **`Space`** expands it into indented **outcome
  sub-rows** (label, de-vigged probability, bid·ask, volume); **`←`** collapses.
- **`v`** cycles the venue filter (all → polymarket → kalshi); **`f`** opens the
  structured filter modal (venue, topic, volume, probability, hide sports).
- **`1` / `2` / `3`** set the price-history range to 1d / 1w / all; the detail pane
  shows the **order book** and **price history**.
- When a venue key is present the book **streams** live (WebSocket, `pm.tick`
  events); otherwise it re-polls over REST on a bounded interval. Kalshi streaming
  requires a key.
- **`/`** deep-searches the full catalog; **`Enter`** opens a market in the
  browser; **`x`** removes a saved discovered market.

The agent reads the same de-vigged distributions structurally via the
`forecast_ledger` tool's `pm_query` action.

## Warnings (alerts) and automode

The Warnings view (`ui-tui/src/components/alertsView.tsx`) folds the open alert
backlog (via `forecast.warnings.aggregate`) into **action tiers — FREE, AGENT,
MANUAL** — plus a **STALE** sub-view over the AGENT tier. Navigate with `↑↓`/`j k`,
expand/collapse with `Enter` / `Space` / `←` / `→`, move between tiers with `Tab`
/ `]` / `[`, and `c` / `e` collapse or expand all.

**Automode** is the two bulk passes:

- **`R`** runs the **free pass** — the non-LLM, gated automode over the FREE tier.
- **`Shift+A`** runs the **agent pass** — the LLM reforecast pass over the AGENT
  tier; pressing it again while a pass is live **cancels** it.
- **`x`** dismisses an alert (a note is required); on a contested row, **`1`/`2`/`3`**
  label it interesting / uninteresting / irrelevant (this feeds the triage trust
  gate — see [forecasting-methodology.md](forecasting-methodology.md)).

## The agents chip

When background agents are running, the Home status bar shows an **agents chip** —
"✦ N agents running" (`homeLanding.tsx`), fed by the `agents.active.summary`
aggregate. Click it (or `Ctrl+G a`) to open the **Agents** view
(`agentsOverlay.tsx`): the subagent / spawn-tree monitor with delegations, live
status, history, and sort/filter modes. This is where delegated and background
work (the detached jobs the Desk tiers launch, plus any subagents the agent
spawns) is visible and interruptible.

## The rest of the strip

The remaining views, with their real keys (registry: `PER_VIEW_KEYS` /
`PER_VIEW_GUIDE` in `ui-tui/src/content/keymaps.ts` — the same tables the in-app
`h` help renders):

- **News** (`newsView.tsx`) — a headline feed across your configured providers.
  `↑↓` selects, `Enter` opens the story in the browser, `/` filters, `r`
  refreshes.
- **Messaging** (`messagingView.tsx`) — bridges the desk to Signal so alerts and
  chat reach your phone. `↑↓` moves threads, `s` sets up or links an account,
  `r` refreshes; open a thread to read and reply.
- **Calendar** (`calendarView.tsx`) — upcoming market closes and resolutions by
  date. On a wide terminal `Tab` switches month grid ↔ agenda. In the grid,
  arrows move the day focus, `PgUp`/`PgDn` (or `[` `]`) page months, and `t`
  jumps to today; in the agenda, `↑↓` selects, `o`/`O` sorts, `/` filters.
  `Enter` opens the focused day or deep-links into the Desk; `r` refreshes.
- **Calibration** (`calibrationView.tsx`) — the reliability curve, per-bucket
  hit rates, and the signed-bias verdict (over- vs under-confident). `↑↓`
  scrolls, `r` refreshes; `/calibration --visual` reaches it from anywhere.
- **Docs** (`obsidianView.tsx`) — the write-ups and dossiers the desk publishes.
  `1`/`2` switch collections (Markdown vault ↔ LaTeX workspace); `↑↓`/`j k`
  move within a pane, `←→`/`l` cross the list · outline · doc panes. `Enter`
  opens a note or follows the focused wikilink, `Tab` cycles a doc's wikilinks,
  `/` filters, `o`/`O` sort, `s` searches the vault, `e` edits, `a` asks the
  desk about the note, `n` makes a new note, `c` comments on selected lines; in
  the LaTeX workspace `g`/`G`/`P` run git init / GitHub repo / commit-and-push.
- **Demo Vis** (`demoVizView.tsx`, **dev-flag only**) — a gallery of the
  terminal chart engine (candlesticks, fans, depth, heatmaps, scatter,
  sparkgrids), used to eyeball rendering across terminals. Scroll to browse;
  `q`/`Esc` closes. Absent by default — unreachable by click or chord unless
  `FORECAST_TUI_DEV_DEMO_VIZ=1` is set (see the view list above).
- **Hooks** (`hooksView.tsx`) — the saturation and style guardrails that score
  every forecast snapshot. `↑↓` selects, `Enter` opens or toggles a hook, `c`
  (or `←→`) collapses/expands, `r` refreshes; the wizard walks you through
  authoring a new one.

(The Agents view has its own section above. Help is the full-screen reference
tab; `h`/`?` on any view opens the quick help modal instead.)

## Maintenance: ledger backups + integrity

The forecast ledger (`{home}/forecasting/forecasting.db`) is the entire asset —
months of judgment. Back it up and check its integrity from the CLI:

- **`forecast backup run`** — takes an **online** backup (SQLite's page-level
  backup API, safe while the gateway and cron are writing — never a raw file-copy
  of the live WAL db) into `{home}/forecasting/backups/forecast-YYYYMMDD-HHMMSS.db`,
  runs `PRAGMA integrity_check` + `quick_check`, and prunes old snapshots. It runs
  as a durable job, so it also shows on the Agents view and in `forecast backup list`.
- **`forecast backup list`** — the existing backups, newest first.
- **Retention** is automatic and deterministic: the newest **14** snapshots are
  always kept, plus one-per-week for the most recent **8** ISO weeks; everything
  else is pruned after each run.

**Daily cadence.** The first committed forecast auto-arms a daily backup cron
(07:30, half an hour before the 08:00 self-check), gated behind
`forecasting.cron.auto_install` — the same mechanism that arms the nightly
self-check. To arm it explicitly (or on a host where you manage cron by hand),
install the one routine:

```python
from forecasting.scheduler import install_backup_cron
install_backup_cron()  # daily "30 7 * * *"; pass schedule=... to change cadence
```

**`forecast doctor`** reports a **durability** line: the last-backup age (it
**WARNs when the newest backup is over 48h old, or missing entirely**), the
integrity verdict, and a row-count snapshot — so the gap surfaces on the lazy path
even if no cron is installed.
