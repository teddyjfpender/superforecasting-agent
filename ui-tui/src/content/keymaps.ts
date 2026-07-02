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
  ['Ctrl+K', 'command palette — run any / command'],
  ['?', 'this cheat sheet'],
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
    ['Tab / ←→ / h l', 'switch lens'],
    ['Enter', 'open the selected forecast'],
    ['u', 'update · s settings · / filter · r refresh'],
    ['q / Esc', 'close the view']
  ],
  markets: [
    ['↑/↓', 'select a market'],
    ['Tab / ←→', 'switch lens'],
    ['Enter', 'open · / filter · r refresh'],
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
    ['h / ←', 'collapse · l / → expand'],
    ['c / e', 'collapse-all / expand-all'],
    ['1 / 2 / 3', 'label contested row: interesting / uninteresting / irrelevant'],
    ['R / Shift-A', 'free pass · agent pass · x dismiss'],
    ['q / Esc', 'close the view']
  ],
  calibration: [
    ['↑/↓', 'scroll'],
    ['q / Esc', 'close the view']
  ],
  calendar: [
    ['↑/↓', 'scroll'],
    ['q / Esc', 'close the view']
  ],
  obsidian: [
    ['↑/↓', 'navigate the vault'],
    ['Enter', 'open a note'],
    ['q / Esc', 'close the view']
  ],
  agents: [
    ['↑/↓ / j k', 'move the cursor'],
    ['h / ←', 'back · l / → forward'],
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
