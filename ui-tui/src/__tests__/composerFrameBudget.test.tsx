import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it, vi } from 'vitest'

import type * as BrandingModule from '../components/branding.js'
import type * as HomeLandingModule from '../components/homeLanding.js'

// WHOLE-FRAME KEYSTROKE BUDGET (the pin for the "typing flashes the TUI" fix).
//
// The composer's live text lives in the $composerText store, NOT in AppLayout's
// props, so a keystroke re-renders only the composer's own input subtree. This
// test renders the REAL AppLayout driven by the REAL useVirtualHistory — the
// production geometry that a hand-built transcript object would falsely stabilize
// — and pins two things across five keystrokes:
//
//   1. WHOLE-FRAME BYTES: each keystroke emits a small localized diff (never a
//      transcript re-blit), and the 5-keystroke total stays under a documented
//      budget. Regression baseline: with the transcript re-rendering per key the
//      active conversation cost ~4,900 B/keystroke (~24 KB / 5 keys); isolated it
//      is ~110 B/keystroke.
//   2. RENDER COUNTS +0: the transcript, the status bar, the NavBar,
//      the hero, the Today panel and the tip re-render ZERO times while typing.
//      The mocked leaves below bump a counter on each render, so +0 == the
//      memoized subtree never re-rendered.
//
// ERASE_SCREEN (CSI 2 J) — the full-repaint "flash" — must never appear.

const counts: Record<string, number> = {}

const bump = (k: string) => {
  counts[k] = (counts[k] ?? 0) + 1

  return null
}

vi.mock('../components/streamingAssistant.js', () => ({
  LiveTodoPanel: () => null,
  StreamingAssistant: () => bump('transcript')
}))
vi.mock('../components/navBar.js', () => ({ NavBar: () => bump('navbar') }))
vi.mock('../components/branding.js', async importOriginal => {
  const actual = await importOriginal<typeof BrandingModule>()

  return { ...actual, HomeHero: () => bump('hero') }
})
vi.mock('../components/homeLanding.js', async importOriginal => {
  const actual = await importOriginal<typeof HomeLandingModule>()

  return { ...actual, HomeStatusBar: () => bump('statusBar'), HomeTip: () => bump('tip') }
})
vi.mock('../components/todayPanel.js', () => ({ TodayPanel: () => bump('today') }))
vi.mock('../components/scheduleStrip.js', () => ({ ScheduleStrip: () => bump('schedule') }))

process.env.FORECAST_TUI_INLINE = '1'

// Documented budget: a localized composer diff is a couple hundred bytes; five of
// them plus cursor moves stay well under this. The pre-fix flash regime was
// >24,000 B for the same five keystrokes, so this guards the whole gap.
const FIVE_KEYSTROKE_BUDGET = 1400
const PER_KEYSTROKE_CEILING = 600
const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`

const writeStream = (columns: number, rows: number, isTTY = true) => {
  const stream = new PassThrough() as any
  let output = ''
  Object.assign(stream, {
    columns, isRaw: false, isTTY, rows,
    ref: () => stream,
    setRawMode: (m: boolean) => (stream.isRaw = m),
    unref: () => stream
  })
  stream.on('data', (c: Buffer) => (output += c.toString()))

  return { clear: () => (output = ''), stream, text: () => output }
}

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const noop = () => {}

const actions: any = {
  answerApproval: noop, answerClarify: noop, answerSecret: noop, answerSudo: noop,
  clearSelection: noop, draftCommand: noop, onModelSelect: noop, resumeById: noop,
  runCommand: noop, setStickyPrompt: noop
}

const status: any = {
  cwdLabel: '~/x', forecastPulseTick: 0, sessionStartedAt: null, showStickyPrompt: false,
  statusColor: 'white', stickyPrompt: '', turnStartedAt: null, voiceLabel: ''
}

const progress: any = { showProgressArea: false }

const buildComposer = (cols: number): any => ({
  cols, compIdx: 0, completions: [], empty: false,
  handleTextPaste: async () => null, pagerPageSize: 10,
  queueEditIdx: null, queuedDisplay: [], submit: noop, updateInput: noop, voiceRecordKey: null
})

const setup = async () => {
  const [{ AppLayout }, { GatewayProvider }, { Box, render }, { useVirtualHistory }] = await Promise.all([
    import('../components/appLayout.js'),
    import('../app/gatewayContext.js'),
    import('@hermes/ink'),
    import('../hooks/useVirtualHistory.js')
  ])

  const { resetOverlayState } = await import('../app/overlayStore.js')
  const { resetUiState } = await import('../app/uiStore.js')
  const store = await import('../app/composerTextStore.js')
  resetOverlayState()
  resetUiState()
  store.resetComposerText()

  return { AppLayout, Box, GatewayProvider, render, store, useVirtualHistory }
}

const runBudget = async (historyItems: any[], virtualRows: any[]) => {
  for (const k of Object.keys(counts)) {
    delete counts[k]
  }

  const ROWS = 30
  const COLS = 120
  const { AppLayout, Box, GatewayProvider, render, store, useVirtualHistory } = await setup()
  store.$composerText.set({ input: 'hi', inputBuf: [] })

  const gw: any = {
    off: noop, on: noop,
    request: async () => null,
    rpc: async () => null
  }

  const gwValue = { gw, rpc: gw.rpc }
  const composer = buildComposer(COLS)

  const App = () => {
    // Drive the REAL useVirtualHistory, exactly like useMainApp — every render
    // re-runs the hook, so this catches any transcript-identity churn.
    const scrollRef = React.useRef<any>(null)
    const rows = React.useMemo(() => virtualRows, [])
    const virtualHistory = useVirtualHistory(scrollRef, rows, COLS)

    const transcript = React.useMemo(
      () => ({ historyItems, scrollRef, virtualHistory, virtualRows: rows }),
      [virtualHistory, rows]
    )

    return React.createElement(Box, { flexDirection: 'column', height: ROWS, width: COLS },
      React.createElement(GatewayProvider, { value: gwValue },
        React.createElement(AppLayout, {
          actions, composer, mouseTracking: false, progress, status, transcript
        })))
  }

  const out = writeStream(COLS, ROWS)

  const instance: any = await render(React.createElement(App), {
    exitOnCtrlC: false, patchConsole: false, stdin: writeStream(COLS, ROWS, true).stream, stdout: out.stream
  })

  await tick(250)

  // Baseline the render counters AFTER the initial settle; measure only typing.
  for (const k of Object.keys(counts)) {
    delete counts[k]
  }

  let total = 0
  let v = 'hi'
  const perKey: number[] = []

  for (let k = 0; k < 6; k++) {
    out.clear()
    v += 'a'
    store.setComposerInput(v)
    await tick(90)
    const frame = out.text()
    expect(frame).not.toContain(ERASE_SCREEN)

    // Drop the first (one-time layout settle); budget the five steady keystrokes.
    if (k > 0) {
      perKey.push(frame.length)
      total += frame.length
    }
  }

  instance.unmount?.()

  return { counts: { ...counts }, perKey, total }
}

describe('Home composer: whole-frame keystroke budget', () => {
  it('active conversation — 5 keystrokes under budget, chrome renders +0', async () => {
    const items = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `message number ${i} with several words to force some real height here`
    }))

    const { counts: c, perKey, total } = await runBudget(
      items,
      items.map((m, i) => ({ index: i, key: `m${i}`, msg: m }))
    )

    // The pinned invariant: nothing above the composer re-renders while typing.
    expect(c.transcript ?? 0).toBe(0)
    expect(c.statusBar ?? 0).toBe(0)
    expect(c.navbar ?? 0).toBe(0)

    for (const b of perKey) {
      expect(b).toBeLessThan(PER_KEYSTROKE_CEILING)
    }

    expect(total).toBeLessThan(FIVE_KEYSTROKE_BUDGET)
  })

  it('landing (hero visible) — 5 keystrokes under budget, chrome renders +0', async () => {
    const { counts: c, perKey, total } = await runBudget([{ kind: 'intro', role: 'system', text: '' }], [])

    expect(c.transcript ?? 0).toBe(0)
    expect(c.statusBar ?? 0).toBe(0)
    expect(c.navbar ?? 0).toBe(0)
    // Landing-only chrome (the ASCII hero, Today panel, tip) must also hold.
    expect(c.hero ?? 0).toBe(0)
    expect(c.today ?? 0).toBe(0)
    expect(c.tip ?? 0).toBe(0)

    for (const b of perKey) {
      expect(b).toBeLessThan(PER_KEYSTROKE_CEILING)
    }

    expect(total).toBeLessThan(FIVE_KEYSTROKE_BUDGET)
  })
})
