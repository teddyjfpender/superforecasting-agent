// The static keymap registry behind the global interaction chrome: the Ctrl+G
// view-switch chords, the palette/help global keys, and the per-view key rows
// the `?` cheat-sheet assembles. Views "register" their keys here (one small
// table) so the cheat-sheet stays truthful without every view growing a help
// modal — which only works if every row here matches what actually ships.

// A `Ctrl+G`-then-letter chord: Ctrl+G arms the leader (app/useInputHandlers.ts
// `armChord('g')`), the next letter picks the view. `nav` is the NAV_TABS key it
// routes to (see navRoutes). Letters prefer the tab's initial; collisions are
// resolved by hand (Markets keeps `m`, Messaging is dropped from the chord set
// to avoid stealing it).
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
  ['h / ?', 'help while browsing; ? also opens help in an empty Home composer'],
  ['Ctrl+K', 'command palette — run any / command'],
  ['Ctrl+G then …', 'jump to a view: ' + VIEW_CHORDS.map(c => `${c.key} ${c.label}`).join(' · ')],
  ['click a tab', 'switch views with the mouse (top bar)'],
  ['Alt+M', 'quick message from any view'],
  ['/', 'Home: slash command; other views: their local search/filter']
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
    ['n / i', 'new question interview / revisit selected forecast beliefs'],
    ['U / u', 'update now / re-arm — marked rows (or a lens → all its questions)'],
    ['A / T', 'agent run · task over the selection (or a lens → all its questions)'],
    ['o / O', 'sort column · toggle asc/desc — cycles past the columns to VOI (value-of-information order)'],
    [
      'VOI',
      "Next best actions panel = what to touch next (U update · +src add sources · R resolve); thesis lens shows each member's ⇅±pp swing"
    ],
    ['s / / / r', 'settings · filter · refresh'],
    ['q / Esc', 'clear selection / filter, then close the view']
  ],
  markets: [
    ['↑/↓', 'select a market'],
    ['Tab / ←→', 'switch category'],
    ['p', 'jump to the Prediction section (Polymarket + Kalshi)'],
    ['Space / v / 1·2·3', 'expand outcomes · switch venue · history range (Prediction)'],
    ['f', 'filter prediction markets (venue · volume · probability · hide sports)'],
    ['x', 'remove the saved “+” market under the cursor (a searched find; browse rows stay)'],
    ['Enter', 'open · / search · r refresh'],
    ['o / O', 'sort column · toggle asc/desc (or click a header)'],
    ['M', 'switch Data ↔ Models'],
    ['m', 'message / forward the selected item'],
    ['i', 'data warnings — how to fix blank (missing-key) series'],
    ['q / Esc', 'close the view'],
    // ── Models mode (m toggles into it) ──────────────────────────────────────
    // Registered explicitly, and kept to three rows so the modal's first frame
    // still shows the whole table. These are a DIFFERENT key set from the
    // Data-mode rows above (x deletes a model here, not a saved market), and
    // until now the cheat-sheet could not show them at all.
    ['n / Enter / x', 'Models: new model · open · delete'],
    ['r / R', 'Models: refresh the list · retry a failed build'],
    ['c / w / e / F', 'open model: chat-refine · rewrite · export JSON · spin off a Desk forecast']
  ],
  news: [
    ['↑/↓', 'select a story'],
    ['Tab / ←→', 'next/previous source'],
    ['Enter', 'open story in browser'],
    ['/', 'search headlines'],
    ['a / s', 'add feed / starter feeds'],
    ['PgUp/PgDn', 'scroll the reader'],
    ['m', 'message / forward story'],
    ['r', 'fetch updates without moving the current story'],
    ['u', 'apply fetched updates'],
    ['q / Esc', 'close; Esc clears search first']
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
    ['↑/↓ / j k', 'scroll'],
    ['PgUp/PgDn', 'page'],
    ['g / G', 'top / bottom'],
    ['r', 'refresh'],
    ['q / Esc', 'close']
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
    ['1 / 2', 'Obsidian vault / Overleaf workspace'],
    ['↑/↓', 'select a document'],
    ['Tab / ←→', 'cycle folders'],
    ['/', 'search titles and paths'],
    ['PgUp/PgDn', 'scroll reader'],
    ['e / Ctrl+Enter', 'edit / save in editor'],
    ['R', 'reconcile source and recovered draft'],
    ['n / c', 'new document / connections and sync'],
    ['m', 'message / forward document excerpt'],
    ['q / Esc', 'close; Esc leaves editing/search first']
  ],
  agents: [
    ['↑/↓ / j k', 'select agent; detail: scroll'],
    ['Enter / →', 'open detail'],
    ['← / Esc', 'back from detail'],
    ['s / f', 'cycle sort / filter'],
    ['[ / ]', 'step through history'],
    ['x / X', 'kill agent / subtree when supported'],
    ['p', 'pause / resume delegation when supported'],
    ['q', 'close']
  ],
  hooks: [
    ['↑/↓', 'select a hook; inspector: scroll'],
    ['Tab', 'focus list / inspector'],
    ['c / ←→', 'cycle severity'],
    ['p', 'cycle profile'],
    ['e / d', 'enable / disable selected rule'],
    ['n / E / x', 'new / edit user rule / remove user rule'],
    ['r', 'toggle reference / rules'],
    ['q / Esc', 'back from reference, then close']
  ],
  messaging: [
    ['↑/↓', 'select a chat'],
    ['Tab / [ / ]', 'cycle collections (← previous)'],
    ['Enter / →', 'open chat and focus composer'],
    ['/', 'search chats, names and categories'],
    ['p / x / C', 'pin / archive / assign category'],
    ['f / n', 'find contacts or chats / new chat (Ctrl+B group)'],
    ['c', 'edit saved contact name'],
    ['Ctrl+R', 'in contact picker: request names/groups from phone'],
    ['m', 'quick compose'],
    ['Enter / Shift+Enter', 'in chat: send / newline'],
    ['← / Esc', 'in chat: back at start of draft / back anywhere; keeps draft'],
    ['✓ / ◷ / !', 'message sent / sending / delivery unconfirmed; no read receipt implied'],
    ['PgUp/PgDn', 'in chat: scroll history'],
    ['Ctrl+O', 'in chat: open latest attachment'],
    ['r / R', 'reconnect / restart daemon'],
    ['s', 'set up Signal when disconnected'],
    ['q / Esc', 'list: close; chat: Esc back (q types text)']
  ],
  // Dev-gated (FORECAST_TUI_DEV_DEMO_VIZ) — absent from NAV_TABS unless the flag
  // is on, so the Help modal's "all views" wall (built from NAV_TABS) never shows
  // it to an ordinary operator. The rows stay registered because the view still
  // ships: with the flag on, its help must be as truthful as every other view's.
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
    'Home is the forecasting chat. Enter sends; Shift+Enter inserts a newline. / starts a slash command.',
    'Press ? in an empty composer for this modal. h opens help when focus is on Today rather than the composer. Ctrl+K opens the command palette; Ctrl+G then a letter switches views; Ctrl+T focuses Today.'
  ],
  desk: [
    'Lenses group forecasts by thesis, then All and Operations. Tab or left/right switches lens; arrows select; Enter opens detail.',
    'Updates have three tiers: u re-arms, U updates now, A runs an agent. Space marks rows; Shift+arrows extends selection. T opens a task; with no rows marked, lens actions apply to its questions.',
    'n creates; R resolves; s opens settings. / filters, o sorts and r refreshes. Next best actions ranks the book by value of information.'
  ],
  markets: [
    'Markets has two modes, toggled with M: Data (live quotes by category) and Models (agentic quant-research). Press p to jump to the Prediction section — Polymarket and Kalshi — where v cycles venue, 1·2·3 set the history range, and Space expands outcomes.',
    'Market Models are quant questions the desk researches end to end. Press n to define one, Enter to open it, c to chat/refine, w to rewrite on fresh data, e to export JSON, ←→ for versions, and F to spin off a Desk forecast.',
    'Press d (Add data) to connect a provider; / filters the tape (or deep-searches a ticker in Prediction), o sorts, r refreshes. Blank series usually mean a missing API key — the header [!] flags which; press i for the per-provider fix.'
  ],
  news: [
    'News has sources, headlines and an independently scrolling reader. Tab or left/right switches sources; up/down selects stories. PgUp/PgDn scrolls article text without moving the selection.',
    'Enter opens the source in a browser, / searches, a adds feeds, s selects starter feeds when available, r refreshes and m forwards the selected story.'
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
    'Docs has a library, document list and independently scrolling reader. Press 1 for Obsidian or 2 for Overleaf/LaTeX. Tab cycles folders; arrows select documents; PgUp/PgDn scrolls the reader.',
    'Press e to edit, Ctrl+Enter to save, and Esc to return to preview with the draft retained. R reconciles source changes. n creates a document; c opens connections and explicit sync. m forwards a labelled excerpt.'
  ],
  agents: [
    'The Agents view is the subagent and spawn-tree monitor: every delegated run, its status, and its history. Move the cursor with ↑↓ (j/k); ← steps back and →/l goes forward through the tree; [ and ] step through history. It updates live as agents work.'
  ],
  hooks: [
    'Hooks configures forecasting rules. Tab switches between list and inspector; arrows select or scroll. c cycles severity, p cycles profile, e enables and d disables.',
    'n creates a rule; E edits and x removes a user rule. r switches the reference page. Esc returns from reference before closing.'
  ],
  messaging: [
    'Messaging is a personal Signal client. Tab cycles Inbox, Unread, Pinned, Groups, Archived and named categories. / searches; p pins, x archives and C assigns a category.',
    'Enter opens a chat ready to type; Enter sends and Esc returns with the draft retained. PgUp/PgDn scrolls history. m opens quick compose; Alt+M also works from other views. The header badge counts unread conversations.'
  ],
  // Dev-gated — see the PER_VIEW_KEYS note above.
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
