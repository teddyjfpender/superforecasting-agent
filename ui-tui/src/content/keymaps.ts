// The static keymap registry behind the global interaction chrome: the g-chord
// view switches, the palette/help global keys, and the per-view key rows the
// `?` cheat-sheet assembles. Views "register" their keys here (one small table)
// so the cheat-sheet stays truthful without every view growing a help modal.

// A g-then-letter chord. `nav` is the NAV_TABS key it routes to (see navRoutes).
// Letters prefer the tab's initial; collisions are resolved by hand (Markets
// keeps `m`, Messaging is dropped from the chord set to avoid stealing it).
export type ViewChord = { key: string; label: string; nav: string }

export const VIEW_CHORDS: ViewChord[] = [
  { key: 'h', label: 'Home', nav: 'home' },
  { key: 'd', label: 'Desk', nav: 'desk' },
  { key: 'm', label: 'Markets', nav: 'markets' },
  { key: 'n', label: 'News', nav: 'news' },
  { key: 'w', label: 'Warnings', nav: 'warnings' },
  { key: 'c', label: 'Calibration', nav: 'calibration' },
  { key: 'k', label: 'Hooks', nav: 'hooks' },
  { key: 'a', label: 'Agents', nav: 'agents' },
  { key: 'o', label: 'Docs', nav: 'obsidian' }
]

const CHORD_BY_KEY = new Map(VIEW_CHORDS.map(c => [c.key, c] as const))

// Resolve a chord's second key to the NAV route it selects, or null when the
// key isn't a bound view chord (which cancels the pending chord).
export const resolveViewChord = (letter: string): null | string => CHORD_BY_KEY.get(letter.toLowerCase())?.nav ?? null

// Rows for the cheat-sheet's global section.
export const GLOBAL_KEYS: [string, string][] = [
  ['h / ?', 'this help — the guide + shortcuts for the current view'],
  ['Ctrl+K', 'command palette — run any / command'],
  ['Ctrl+G then …', 'jump to a view: ' + VIEW_CHORDS.map(c => `${c.key} ${c.label}`).join(' · ')],
  ['click a tab', 'switch views with the mouse (top bar)'],
  ['/', 'type a slash command directly']
]

// Per-view key rows, keyed by the NAV_TABS key of the active view. Assembled
// into the cheat-sheet's "This view" section. Keep these in sync with each
// view's own useInput handler.
export const PER_VIEW_KEYS: Record<string, [string, string][]> = {
  home: [
    ['Enter', 'send / run a slash command'],
    ['↑/↓', 'history · queued-note edit · completions'],
    ['Ctrl+T', 'focus the Today attention panel (landing)'],
    ['Ctrl+C', 'interrupt / clear draft / exit']
  ],
  desk: [
    ['↑/↓', 'select a forecast'],
    ['Space', 'mark the row (advances) · Shift+↑/↓ extend the selection'],
    ['Tab / ←→ / l', 'switch lens (h is Help)'],
    ['Enter', 'open the selected forecast'],
    ['U / u', 'update now / re-arm — marked rows (or a lens → all its questions)'],
    ['A / T', 'agent run · task over the selection (or a lens → all its questions)'],
    ['o / O', 'sort column · toggle asc/desc — cycles past the columns to VOI (value-of-information order)'],
    ['VOI', 'Next best actions panel = what to touch next (U update · +src add sources · R resolve); thesis lens shows each member\'s ⇅±pp swing'],
    ['s / / / r', 'settings · filter · refresh'],
    ['q / Esc', 'clear selection / filter, then close the view']
  ],
  markets: [
    ['↑/↓', 'select a market'],
    ['Tab / ←→', 'switch category'],
    ['p', 'jump to the Prediction section (Polymarket + Kalshi)'],
    ['→ / v / 1·2·3', 'expand outcomes · switch venue · history range (Prediction)'],
    ['f', 'filter prediction markets (venue · volume · probability · hide sports)'],
    ['x', 'remove the saved “+” market under the cursor (a searched find; browse rows stay)'],
    ['Enter', 'open · / search · r refresh'],
    ['o / O', 'sort column · toggle asc/desc (or click a header)'],
    ['m', 'switch Data ↔ Models'],
    ['i', 'data warnings — how to fix blank (missing-key) series'],
    ['q / Esc', 'close the view']
  ],
  news: [
    ['↑/↓', 'select a story'],
    ['Enter', 'open · / filter · r refresh'],
    ['q / Esc', 'close the view']
  ],
  warnings: [
    ['↑/↓ / j k', 'move the cursor'],
    ['Enter / Space', 'expand / collapse'],
    ['←', 'collapse · l / → expand (h is Help)'],
    ['Tab / ] / [', 'jump to next / previous tier'],
    ['c / e', 'collapse-all / expand-all'],
    ['1 / 2 / 3', 'label contested row: interesting / uninteresting / irrelevant'],
    ['R / Shift-A', 'free pass · agent pass · x dismiss'],
    ['r', 'refresh · q / Esc close the view']
  ],
  calibration: [
    ['↑/↓', 'scroll'],
    ['q / Esc', 'close the view']
  ],
  calendar: [
    ['Tab', 'switch month-grid ↔ agenda (wide terminals)'],
    ['←→ ↑↓', 'move the day focus (grid)'],
    ['PgUp/PgDn · [ ]', 'previous / next month (grid)'],
    ['t', 'jump to today (grid)'],
    ['↑/↓ · j k', 'select an event (agenda)'],
    ['o / O', 'sort column · toggle asc/desc (agenda)'],
    ['/', 'filter the agenda'],
    ['Enter', 'open the focused day / deep-link to the Desk'],
    ['r', 'refresh · q / Esc close the view']
  ],
  obsidian: [
    ['1 / 2', 'switch collection: Markdown vault ↔ LaTeX workspace'],
    ['↑↓ / j k', 'navigate the focused pane'],
    ['←→ / l', 'move across panes: list · outline · doc (h is Help)'],
    ['Enter', 'open a note / doc · follow the focused wikilink'],
    ['Tab', 'cycle the wikilinks in the doc (Markdown)'],
    ['/', 'filter the list · o / O sort (name / modified)'],
    ['s', 'search the vault (Markdown) · e edit · a ask the desk'],
    ['n / c', 'new note · comment on the selected lines (Markdown)'],
    ['g / G / P', 'git init · GitHub repo · commit + push (LaTeX)'],
    ['q / Esc', 'clear selection / filter, then close the view']
  ],
  agents: [
    ['↑/↓ / j k', 'move the cursor'],
    ['←', 'back · l / → forward (h is Help)'],
    ['q / Esc', 'close the view']
  ],
  hooks: [
    ['↑/↓', 'select'],
    ['Enter', 'open / toggle'],
    ['q / Esc', 'close the view']
  ],
  messaging: [
    ['↑/↓', 'select a thread'],
    ['q / Esc', 'close the view']
  ],
  demoViz: [['q / Esc', 'close the view']],
  help: [['↑↓/jk', 'scroll · PgUp/PgDn page · g/G top/bottom · Esc/q close']]
}

// Per-view "how to use this" prose, keyed by the same NAV route key as
// PER_VIEW_KEYS. 2-4 short paragraphs the Help modal renders ABOVE the shortcut
// table: what the view is for, its core workflow, and the tips a chip row can't
// carry. Keep each honest to what the view actually implements — these are read
// aloud in tests, so a phrase drifting from reality fails loudly. `h` (and the
// `?` alias) opens this same modal on every view.
export const PER_VIEW_GUIDE: Record<string, string[]> = {
  home: [
    'Home is the forecasting desk itself — a chat. Ask a question in plain language to start a forecast, or press / for a slash command. Enter sends; Shift+Enter inserts a newline.',
    'Ctrl+K opens the command palette (every action, one search) and Ctrl+G then a letter jumps to any view. Ctrl+T focuses the Today attention panel so you can act without leaving Home.',
    'Press h (or ?) any time — including here once you have stepped off the composer — for this help.'
  ],
  desk: [
    'The Desk is your forecasts workspace. Lenses (Tab, or ←→) regroup the same book: Book, Review, Thesis, Factor, and a read-only Bench scoreboard. Move with ↑↓ and press Enter to open a forecast in detail.',
    'Updating has three tiers: u re-arms the review schedule, U runs a real update now, and A hands the question to an agent for autonomous reforecasting. Mark rows with Space (⇧↑↓ extends the selection) to run a tier across many at once — with nothing marked, a lens applies the action to all of its questions.',
    'T opens a task over the selection; n creates a new question; R resolves one; s opens settings. The SRC / RDY columns flag readiness (evidence sourced, ready to score). Next best actions (top of the summary panel) ranks the book by value-of-information — what to touch next. Press / to filter, o to sort, and r to refresh.'
  ],
  markets: [
    'Markets has two modes, toggled with m: Data (live quotes by category) and Models (agentic quant-research). Press p to jump to the Prediction section — Polymarket and Kalshi — where v cycles venue, 1·2·3 set the history range, and → expands outcomes.',
    'Market Models are quant questions the desk researches end to end. Press n to define one, Enter to open it, c to chat/refine, w to rewrite on fresh data, e to export JSON, ←→ for versions, and F to spin off a Desk forecast.',
    'Press d (Add data) to connect a provider; / filters the tape (or deep-searches a ticker in Prediction), o sorts, r refreshes. Blank series usually mean a missing API key — the header [!] flags which; press i for the per-provider fix.'
  ],
  news: [
    'News is a headline feed across your configured providers. Move with ↑↓, press Enter to open a story in the browser, / to filter the feed, and r to refresh.'
  ],
  warnings: [
    'Warnings is the desk’s alert and review queue — open alerts, stale forecasts, readiness gaps, and items awaiting judgment, grouped into tiers. Move with ↑↓ (or j/k); Enter or Space expands a row; ← collapses and → expands; Tab jumps between tiers.',
    'Two bulk passes clear a tier: R is a free (non-LLM) pass and Shift-A hands it to an agent to reforecast (press again to cancel a running pass); x dismisses. When a row is contested, label it 1 interesting, 2 uninteresting, or 3 irrelevant to teach the triage. Press r to refresh.'
  ],
  calibration: [
    'Calibration shows how well your forecasts track reality: a reliability curve, per-bucket hit rates, and a signed-bias verdict — whether you run over- or under-confident. Scroll with ↑↓ and press r to refresh. Run /calibration --visual to reach this from anywhere.'
  ],
  calendar: [
    'The Calendar lays out upcoming market closes and resolutions by date. On a wide terminal Tab switches between the month grid and an agenda list.',
    'In the grid, arrows move the day focus, PgUp/PgDn (or [ ]) page months, and t jumps to today. In the agenda, ↑↓ select an event and o/O sort. Enter opens the focused day or deep-links into the Desk; / filters the agenda; r refreshes.'
  ],
  obsidian: [
    'Docs browses the write-ups and dossiers the desk publishes. Press 1 for the Markdown vault and 2 for the LaTeX workspace. Move within a pane with ↑↓ (j/k); ←→ (l for right) crosses the three panes — list, outline, doc. Enter opens a note or follows the focused wikilink; Tab cycles the wikilinks in a Markdown doc.',
    'Press / to filter and o/O to sort. s searches the vault, e edits, a asks the desk about the note, n makes a new note, and c comments on selected lines. In the LaTeX workspace, g / G / P handle git init, GitHub repo, and commit-and-push.'
  ],
  agents: [
    'The Agents view is the subagent and spawn-tree monitor: every delegated run, its status, and its history. Move the cursor with ↑↓ (j/k); ← steps back and →/l goes forward through the tree; [ and ] step through history. It updates live as agents work.'
  ],
  hooks: [
    'Hooks are the desk’s saturation and style guardrails that score every forecast snapshot. Move with ↑↓, press Enter to open or toggle a hook, c (or ←→) to collapse/expand, and r to refresh. The wizard walks you through authoring a new one.'
  ],
  messaging: [
    'Messaging bridges the desk to Signal so alerts and chat reach your phone. Move threads with ↑↓, press s to set up or link an account, and r to refresh. Open a thread to read and reply.'
  ],
  demoViz: [
    'A gallery of the terminal chart engine — candlesticks, fans, depth, heatmaps, scatter, and sparkgrids — used to eyeball rendering across terminals. Scroll to browse; press q or Esc to close.'
  ],
  help: [
    'This is the full Help view — a navigable reference for views, commands, and hotkeys. Press h (or ?) anywhere for this same help as a quick modal, / for commands, and click the tabs up top to move between views.'
  ]
}

// The guide paragraphs for a view, falling back to a minimal one-liner so a view
// without registered prose still gets an honest header instead of a blank modal.
export const guideFor = (view: string): string[] =>
  PER_VIEW_GUIDE[view] ?? ['Press h or ? on any view for its shortcuts and a short guide. Esc closes.']
