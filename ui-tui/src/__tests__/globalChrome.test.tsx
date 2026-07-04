import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { $chordPending, armChord, clearChord } from '../app/chordStore.js'
import { activeNavKey, canOpenGlobalOverlay, navPatchFor, selectNavView } from '../app/navRoutes.js'
import { $overlayState, resetOverlayState } from '../app/overlayStore.js'
import { rankSlashCommands } from '../components/paletteOverlay.js'
import { PER_VIEW_GUIDE, PER_VIEW_KEYS, resolveViewChord, VIEW_CHORDS } from '../content/keymaps.js'

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isRaw?: boolean
    isTTY: boolean
    ref?: () => PassThrough
    rows: number
    setRawMode?: (mode: boolean) => void
    unref?: () => PassThrough
  }

  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (mode: boolean) => {
      stream.isRaw = mode
    },
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// ─────────────────────────────────────────────────────────────────────────
// 1. Command palette — fuzzy rank + type-to-filter + Enter runs a command
// ─────────────────────────────────────────────────────────────────────────

describe('command palette', () => {
  it('rankSlashCommands returns the full catalog for an empty query', () => {
    const all = rankSlashCommands('')

    expect(all.length).toBeGreaterThan(10)
    expect(all.some(c => c.name === 'model')).toBe(true)
    expect(all.some(c => c.name === 'clear')).toBe(true)
  })

  it('rankSlashCommands ranks an exact name match first', () => {
    const ranked = rankSlashCommands('model')

    expect(ranked.length).toBeGreaterThan(0)
    expect(ranked[0]!.name).toBe('model')
  })

  it('opens, filters as you type, and runs the selected command through the composer path', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const ran: string[] = []

    const [{ Box, render }, { PaletteOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/paletteOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 40)
    const stdin = writeStream(120, 40, true)

    const instance = render(
      React.createElement(
        Box,
        { flexDirection: 'column', height: 40, width: 120 },
        React.createElement(PaletteOverlay, {
          cols: 120,
          onClose: () => undefined,
          onRun: (command: string) => {
            ran.push(command)
          },
          rows: 40,
          t: DARK_THEME
        })
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(60)
    expect(stripAnsi(stdout.text())).toContain('Command palette')

    // Type "model" → the list narrows to the model command.
    stdin.stream.write('model')
    await tick(60)
    const filtered = stripAnsi(stdout.text())
    expect(filtered).toContain('/model')

    // Enter runs the top match via the SAME `/name` path the composer uses.
    stdin.stream.write('\r')
    await tick(60)
    expect(ran).toEqual(['/model'])

    instance.unmount?.()
    delete process.env.FORECAST_TUI_INLINE
  })
})

// ─────────────────────────────────────────────────────────────────────────
// 2. Global view chords — resolve, switch, cancel on timeout / other key
// ─────────────────────────────────────────────────────────────────────────

describe('view chords', () => {
  afterEach(() => {
    clearChord()
    resetOverlayState()
  })

  it('every chord letter resolves to a real NAV route', () => {
    for (const chord of VIEW_CHORDS) {
      expect(resolveViewChord(chord.key)).toBe(chord.nav)
      expect(navPatchFor(chord.nav)).not.toBeNull()
    }
  })

  it('an unmapped second key cancels (resolves to null)', () => {
    expect(resolveViewChord('z')).toBeNull()
    expect(resolveViewChord('q')).toBeNull()
  })

  it('g d switches to the Desk view via the shared nav routing', () => {
    expect(activeNavKey($overlayState.get())).toBe('home')

    const nav = resolveViewChord('d')
    expect(nav).toBe('desk')
    selectNavView(nav!)

    expect($overlayState.get().forecasts).toBe(true)
    expect(activeNavKey($overlayState.get())).toBe('desk')
  })

  it('arms then auto-cancels the pending chord after the timeout', async () => {
    armChord('g', 40)
    expect($chordPending.get()).toBe('g')

    await tick(70)
    expect($chordPending.get()).toBeNull()
  })

  it('clearChord cancels an armed chord immediately (the other-key path)', () => {
    armChord('g', 5000)
    expect($chordPending.get()).toBe('g')

    clearChord()
    expect($chordPending.get()).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────
// 3. Help overlay — per-view guide + global keys + the ACTIVE view's rows
// ─────────────────────────────────────────────────────────────────────────

describe('help overlay', () => {
  const renderHelp = async (activeView: string) => {
    const [{ Box, renderSync, Text }, { HelpOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/helpOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const sink = writeStream(120, 40)

    const app = React.createElement(
      Box as never,
      { flexDirection: 'column', height: 40, width: 120 } as never,
      React.createElement(Text as never, { key: 'b' } as never, 'BODY'),
      React.createElement(HelpOverlay as never, {
        activeView,
        cols: 120,
        key: 'm',
        onClose: () => undefined,
        rows: 40,
        t: DARK_THEME
      } as never)
    )

    renderSync(app, { exitOnCtrlC: false, patchConsole: false, stdout: sink.stream } as never)

    return stripAnsi(sink.text())
  }

  it('titles the modal for the active view and shows its guide prose + global + view keys', async () => {
    const text = await renderHelp('desk')

    expect(text).toContain('Desk · Help')
    // Guide prose (spot phrases from the Desk guide).
    expect(text).toContain('Lenses')
    expect(text).toContain('three tiers')
    // Grouped shortcut table.
    expect(text).toContain('Global keys')
    expect(text).toContain('Ctrl+K')
    expect(text).toContain('This view — Desk')
    expect(text).toContain('switch lens')
  })

  it('shows the Warnings guide + rows on the Warnings view (a second view)', async () => {
    const text = await renderHelp('warnings')

    expect(text).toContain('Warnings · Help')
    // Guide prose spot phrase.
    expect(text).toContain('review queue')
    expect(text).toContain('This view — Warnings')
    expect(text).toContain('collapse-all')
    // The contested hand-label keys are registered so the shortcut table stays truthful.
    expect(text).toContain('label contested row')
  })

  it('renders the Markets guide (folded in from the old InfoModal helpItems)', async () => {
    const text = await renderHelp('markets')

    expect(text).toContain('Markets · Help')
    expect(text).toContain('Market Models')
    expect(text).toContain('missing API key')
  })

  it('renders a guide + title for the Calendar view (fourth representative view)', async () => {
    const text = await renderHelp('calendar')

    expect(text).toContain('Calendar · Help')
    expect(text).toContain('market closes')
  })

  it('has a per-view key table AND a guide for every NAV route the chords reach', () => {
    for (const chord of VIEW_CHORDS) {
      expect(PER_VIEW_KEYS[chord.nav]).toBeDefined()
      expect(PER_VIEW_GUIDE[chord.nav]?.length).toBeGreaterThan(0)
    }
  })

  it('defaults to the active view and Tab expands to the full registry', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ Box, render }, { HelpOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/helpOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 40)
    const stdin = writeStream(120, 40, true)

    const instance = render(
      React.createElement(
        Box,
        { flexDirection: 'column', height: 40, width: 120 },
        React.createElement(HelpOverlay, {
          activeView: 'desk',
          cols: 120,
          onClose: () => undefined,
          rows: 40,
          t: DARK_THEME
        })
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(60)
    const before = stripAnsi(stdout.text())
    // Default: Global + the active Desk view only. The footer teaches Tab, and no
    // OTHER view's unique rows leak in (Home's Today-focus row is not shown).
    expect(before).toContain('This view — Desk')
    expect(before).toContain('Tab all views')
    expect(before).not.toContain('focus the Today attention panel')

    // Tab expands to the full registry: every view's rows, so a Home-only row shows.
    stdin.stream.write('\t')
    await tick(60)
    const after = stripAnsi(stdout.text())
    expect(after).toContain('focus the Today attention panel')
    expect(after).toContain('Tab this view')

    instance.unmount?.()
    delete process.env.FORECAST_TUI_INLINE
  })

  it('closes on Esc, h, ? and q — but not on an unrelated key', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ Box, render }, { HelpOverlay }, { DARK_THEME }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/helpOverlay.js'),
      import('../theme.js')
    ])

    for (const closeKey of ['', 'h', '?', 'q']) {
      let closed = 0
      const stdout = writeStream(120, 40)
      const stdin = writeStream(120, 40, true)
      const instance = render(
        React.createElement(
          Box,
          { flexDirection: 'column', height: 40, width: 120 },
          React.createElement(HelpOverlay, {
            activeView: 'desk',
            cols: 120,
            onClose: () => { closed += 1 },
            rows: 40,
            t: DARK_THEME
          })
        ),
        { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
      )

      await tick(40)
      // A benign key does NOT close (the modal traps the keyboard).
      stdin.stream.write('z')
      await tick(30)
      expect(closed).toBe(0)
      // The close key does. A lone Esc ('') is disambiguated from an escape
      // SEQUENCE by Ink, so allow a longer settle than the plain glyph keys.
      stdin.stream.write(closeKey)
      await tick(160)
      expect(closed).toBe(1)

      instance.unmount?.()
    }

    delete process.env.FORECAST_TUI_INLINE
  })
})

// ─────────────────────────────────────────────────────────────────────────
// 4. canOpenGlobalOverlay — suppressed by input-owning overlays only
// ─────────────────────────────────────────────────────────────────────────

describe('canOpenGlobalOverlay', () => {
  afterEach(() => resetOverlayState())

  it('is open on Home and over a plain fullscreen view', () => {
    expect(canOpenGlobalOverlay($overlayState.get())).toBe(true)

    selectNavView('desk')
    expect(canOpenGlobalOverlay($overlayState.get())).toBe(true)
  })

  it('is suppressed while a blocking prompt or floating picker owns the keyboard', () => {
    $overlayState.set({ ...$overlayState.get(), modelPicker: true })
    expect(canOpenGlobalOverlay($overlayState.get())).toBe(false)

    resetOverlayState()
    $overlayState.set({ ...$overlayState.get(), palette: true })
    expect(canOpenGlobalOverlay($overlayState.get())).toBe(false)
  })
})
