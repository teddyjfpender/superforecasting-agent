import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { DEV_GATED_NAV_KEYS, NAV_TABS } from '../app/navRoutes.js'
import { GLOBAL_KEYS, PER_VIEW_GUIDE, PER_VIEW_KEYS, VIEW_CHORDS } from '../content/keymaps.js'
import { buildDeskTabs } from '../lib/deskGroups.js'

// ── The help registry must describe what actually ships ──────────────────────
//
// `content/keymaps.ts` exists so the cheat-sheet stays truthful without every
// view growing its own help modal — which only works if something checks it
// against the implementation. Three real drifts motivated this file: the Desk
// guide omitted the Operations lens, the header called the leader a bare
// "g-chord" when it is Ctrl+G, and Models mode registered no key rows at all.

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel: string) => readFileSync(resolve(SRC, rel), 'utf8')

const flat = (rows: [string, string][]) => rows.map(([k, v]) => `${k} ${v}`).join('\n')

describe('desk guide names every lens the desk actually builds', () => {
  it('includes the Operations lens, which buildDeskTabs always appends', () => {
    // The real builder, not a description of it.
    const tabs = buildDeskTabs({ forecasts: [], theses: [] } as never)
    const kinds = tabs.map(t => t.kind)

    expect(kinds).toContain('all')
    expect(kinds).toContain('operations')

    const guide = (PER_VIEW_GUIDE.desk ?? []).join(' ')

    for (const label of tabs.map(t => t.label)) {
      expect(guide).toContain(label)
    }
  })

  it('does not claim the lens set ends at All', () => {
    const guide = (PER_VIEW_GUIDE.desk ?? []).join(' ')

    expect(guide).not.toMatch(/single All catch-all/)
  })
})

describe('guide prose fits the modal without pushing the keys below the fold', () => {
  // The Help modal renders the guide ABOVE the shortcut table inside a fixed
  // maxHeight. Every extra wrapped line of prose costs one row of the key table
  // in the first frame — which is the part an operator actually came for. This
  // caught a one-line overrun that silently hid the Desk's own shortcuts.
  const MODAL_TEXT_COLS = 76
  // Empirically calibrated, not guessed: the Desk guide (the longest) wraps to
  // exactly 13 lines and its shortcut rows are still reachable in the first
  // frame; at 14 the rows vanished and globalChrome.test.tsx went red. This is
  // the cheap early signal with the REASON attached — that test is the proof.
  const GUIDE_LINE_BUDGET = 13

  const wrappedLines = (text: string): number => {
    let lines = 1
    let len = 0

    for (const word of text.split(' ')) {
      if (len && len + 1 + word.length > MODAL_TEXT_COLS) {
        lines += 1
        len = word.length
      } else {
        len = len ? len + 1 + word.length : word.length
      }
    }

    return lines
  }

  for (const [view, paragraphs] of Object.entries(PER_VIEW_GUIDE)) {
    it(`${view} guide stays within the budget`, () => {
      const total = paragraphs.reduce((sum, p) => sum + wrappedLines(p), 0)

      expect(total, `${view} guide wraps to ${total} lines (budget ${GUIDE_LINE_BUDGET})`).toBeLessThanOrEqual(
        GUIDE_LINE_BUDGET
      )
    })
  }
})

describe('the view-switch chord is described as Ctrl+G everywhere', () => {
  it('names Ctrl+G in the global key rows', () => {
    expect(flat(GLOBAL_KEYS)).toContain('Ctrl+G')
  })

  it('is Ctrl+G in the implementation too', () => {
    // useInputHandlers arms the leader on Ctrl+G; a bare `g` would eat typing.
    expect(read('app/useInputHandlers.ts')).toContain("armChord('g')")
  })

  it('never calls the leader a bare "g-chord" in the registry prose', () => {
    const source = read('content/keymaps.ts')
    // `Ctrl+G`-prefixed mentions are fine; a bare "g-chord"/"g-then-letter" is
    // the wording that misled readers about which key to press.
    expect(source).not.toMatch(/(?<!Ctrl\+G[\s`]{0,3})\bg-chord\b/)
    expect(source).not.toMatch(/(?<!`)\bg-then-letter\b/)
  })

  it('every chord letter routes to a view that has registered key rows', () => {
    for (const chord of VIEW_CHORDS) {
      expect(PER_VIEW_KEYS[chord.nav], `no key rows registered for '${chord.nav}'`).toBeTruthy()
    }
  })
})

describe('the registry documents exactly the routes that exist', () => {
  // Help rows for a view NAV_TABS does not offer are help for a place nobody can
  // reach — the same class of drift this file exists to catch. The ONE legitimate
  // exception is a DEV-GATED route: it still ships (behind an env flag), so its
  // rows must stay registered and truthful for when the flag is on. But it has to
  // be DECLARED gated in navRoutes rather than merely orphaned here, which is what
  // keeps "hidden behind a flag" from becoming a hiding place for dead entries.
  const shipped = new Set(NAV_TABS.map(tab => tab.key))
  const gated = new Set(DEV_GATED_NAV_KEYS)

  const describeView = (view: string) =>
    `'${view}' is registered but is neither a NAV_TABS route nor a declared dev-gated one`

  it('every registered key set belongs to a shipped or declared dev-gated route', () => {
    for (const view of Object.keys(PER_VIEW_KEYS)) {
      expect(shipped.has(view) || gated.has(view), describeView(view)).toBe(true)
    }
  })

  it('every registered guide belongs to a shipped or declared dev-gated route', () => {
    for (const view of Object.keys(PER_VIEW_GUIDE)) {
      expect(shipped.has(view) || gated.has(view), describeView(view)).toBe(true)
    }
  })

  it('a dev-gated route that IS shipping is documented like any other', () => {
    // When the flag is on the route joins NAV_TABS, and the Help modal will then
    // render it — so it owes the operator the same rows + prose every other tab has.
    for (const view of gated) {
      if (shipped.has(view)) {
        expect(PER_VIEW_KEYS[view]?.length, `dev-gated '${view}' ships with no key rows`).toBeGreaterThan(0)
        expect(PER_VIEW_GUIDE[view]?.length, `dev-gated '${view}' ships with no guide`).toBeGreaterThan(0)
      }
    }
  })
})

describe('Markets registers its Models-mode keys', () => {
  // The footer chips ARE the shipped affordances, so extract them from the
  // source and require the cheat-sheet to cover the same keys.
  const marketsSource = read('components/marketsView.tsx')

  const chipKeys = (arrayName: string): string[] => {
    const start = marketsSource.indexOf(`const ${arrayName}`)

    expect(start, `${arrayName} not found — the extractor needs updating`).toBeGreaterThan(-1)

    const body = marketsSource.slice(start, marketsSource.indexOf('\n  ]', start))

    return [...body.matchAll(/\{\s*k:\s*'([^']+)'/g)].map(m => m[1]!)
  }

  // Keys that are global chrome or navigation, documented in GLOBAL_KEYS / the
  // shared rows rather than per-mode.
  const AMBIENT = new Set(['↑↓', '⏎', 'h', 'q', 'i', 'Esc', '←→'])

  // The registered KEY tokens only — never the description text. Matching
  // against the prose would let a stray letter in a sentence ("x" in "expand")
  // pass for a documented binding, which is exactly the kind of false green
  // that let Models mode ship undocumented.
  const registeredKeys = (view: string): Set<string> => {
    const tokens = new Set<string>()

    for (const [key] of PER_VIEW_KEYS[view] ?? []) {
      for (const part of key.split(/\s*[/·]\s*/)) {
        const token = part.trim()

        if (token) {
          tokens.add(token)
        }
      }
    }

    return tokens
  }

  it('covers every Models-list chip', () => {
    const keys = registeredKeys('markets')

    for (const key of chipKeys('modelsListChips').filter(k => !AMBIENT.has(k))) {
      expect([...keys], `Models-list key '${key}' is missing from the cheat-sheet`).toContain(key)
    }
  })

  it('covers every open-model chip', () => {
    const keys = registeredKeys('markets')

    for (const key of chipKeys('modelOpenChips').filter(k => !AMBIENT.has(k))) {
      expect([...keys], `open-model key '${key}' is missing from the cheat-sheet`).toContain(key)
    }
  })

  it('documents r (refresh) and R (retry) as the distinct keys they are', () => {
    const rows = flat(PER_VIEW_KEYS.markets ?? [])

    expect(rows).toMatch(/r \/ R/)
    expect(rows).toMatch(/retry/i)
    // Both really are bound in the models handler.
    expect(marketsSource).toContain('refreshModels()')
    expect(marketsSource).toContain('retryModel(')
  })
})
