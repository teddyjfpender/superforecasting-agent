import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// SCROLLBAR KEYSTROKE FLASH — "the RIGHT SIDE of historical chats is still
// blinking on every keystroke" (operator, post df8660bcc). That commit fixed the
// transcript BODY (narrowed TranscriptPane's $uiState subscription to computed
// atoms). But the transcript SCROLLBAR (appChrome.TranscriptScrollbar, the col-201
// │/┃ gutter) still repainted per keystroke in a live session.
//
// This harness reproduces the live path the df8660bcc one missed: a benign
// gateway heartbeat that churns a field TranscriptPane STILL subscribes to
// ($uiSections — a new-but-equal object reference each poll, the shape the desk /
// panel sync produces) landing WHILE a composer key is processed. That re-renders
// TranscriptPane → TranscriptScrollbar, and — with geometry UNCHANGED (no wrap, no
// scroll, no content growth) — the scrollbar column must NOT be re-emitted.
//
// Detector: the scrollbar is the ONLY thing that draws │ / ┃ in this transcript
// (the DESK_LINES bullets never do). Counting those glyphs per key is a direct
// col-201 scrollbar-write probe. RED before the fix: every key re-blits the whole
// ~54-row gutter. GREEN after: zero scrollbar cells when geometry is unchanged.

process.env.FORECAST_TUI_INLINE = '1'

const writeStream = (columns: number, rows: number, isTTY = true) => {
  const stream = new PassThrough() as any
  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
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
  answerApproval: noop,
  answerClarify: noop,
  answerSecret: noop,
  answerSudo: noop,
  clearSelection: noop,
  draftCommand: noop,
  onModelSelect: noop,
  resumeById: noop,
  runCommand: noop,
  setStickyPrompt: noop
}

const status: any = {
  cwdLabel: '~/hermes-agent',
  forecastPulseTick: 0,
  sessionStartedAt: null,
  showStickyPrompt: false,
  statusColor: 'white',
  stickyPrompt: '',
  turnStartedAt: null,
  voiceLabel: ''
}

const progress: any = { showProgressArea: false }

const DESK_LINES = [
  'U.S. ground invasion of Iran / regime fall by July 1 — NO',
  'Alexei Navalny killed under narrow description — YES',
  'WTI crude 2026-06-30 — 69.50 USD/bbl, using front-month CL=F as fallback',
  'Fed / Kevin Warsh rate cut by July 2026 — NO',
  'MV Hondius 5+ non-passenger hantavirus cases — NO',
  'Nicki Minaj gold card — NO',
  'SpaceX Starship IFT-12 success — leaning YES',
  'BTC above 100k at end of Q3 — 0.58',
  'UK general election called before 2027 — 0.31',
  'OpenAI announces GPT-6 before September — 0.22'
]

// The scrollbar draws │ (track) and ┃ (thumb). Count them in a frame.
const scrollbarCells = (frame: string) => (frame.match(/[│┃]/g) ?? []).length

describe('Home: a gateway heartbeat must not re-blit the transcript scrollbar while typing', () => {
  it('writes ZERO scrollbar cells per key when thumb geometry is unchanged', async () => {
    const ROWS = 56
    const COLS = 202

    const [{ AppLayout }, { GatewayProvider }, { Box, render }, { useVirtualHistory }] = await Promise.all([
      import('../components/appLayout.js'),
      import('../app/gatewayContext.js'),
      import('@hermes/ink'),
      import('../hooks/useVirtualHistory.js')
    ])

    const { resetOverlayState } = await import('../app/overlayStore.js')
    const { resetUiState, patchUiState } = await import('../app/uiStore.js')
    const { syncComposerText, resetComposerText } = await import('../app/composerTextStore.js')
    const { setHomePane } = await import('../app/homeFocusStore.js')

    resetOverlayState()
    resetUiState()
    resetComposerText()
    patchUiState({ sid: 'sess-live-1', info: { model: 'gpt-5.3-codex', profile_name: 'desk' } as any })
    setHomePane('conversation')

    const sessions = Array.from({ length: 50 }, (_, i) => ({
      id: `s${i}`,
      message_count: 3,
      preview: `recent desk chat ${i + 1} preview text`,
      source: 'tui',
      started_at: 50 - i,
      title: `recent desk chat ${i + 1}`
    }))

    const gw: any = {
      off: noop,
      on: noop,
      request: async (m: string) => (m === 'session.list' ? { sessions } : null),
      rpc: async () => null
    }

    const gwValue = { gw, rpc: gw.rpc }

    const historyItems = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `• ${DESK_LINES[i % DESK_LINES.length]} (turn ${i})`
    }))

    const virtualRows = historyItems.map((msg, index) => ({ index, key: `m${index}`, msg }))

    const mainScrollRef = React.createRef<any>()

    let typeExternal: (v: string) => void = noop

    const Harness = () => {
      const [input, setInput] = React.useState('hi')
      typeExternal = setInput

      React.useLayoutEffect(() => {
        syncComposerText(input, [])
      }, [input])

      const scrollRef = mainScrollRef
      const rows = React.useMemo(() => virtualRows, [])
      const virtualHistory = useVirtualHistory(scrollRef, rows, COLS - 32)

      const transcript = React.useMemo(
        () => ({ historyItems, scrollRef, virtualHistory, virtualRows: rows }),
        [virtualHistory, rows]
      )

      const composer = React.useMemo(
        () => ({
          cols: COLS,
          compIdx: 0,
          completions: [] as string[],
          empty: false,
          handleTextPaste: async () => null,
          pagerPageSize: 10,
          queueEditIdx: null,
          queuedDisplay: [],
          submit: noop,
          updateInput: setInput,
          voiceRecordKey: null
        }),
        []
      )

      return React.createElement(
        Box,
        { flexDirection: 'column', height: ROWS, width: COLS },
        React.createElement(
          GatewayProvider,
          { value: gwValue },
          React.createElement(AppLayout, {
            actions,
            composer,
            mouseTracking: false,
            progress,
            status,
            transcript
          })
        )
      )
    }

    const out = writeStream(COLS, ROWS)

    const instance: any = await render(React.createElement(Harness), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: out.stream
    })

    await tick(300)

    // Sanity: the scrollbar IS on screen (a settled frame draws the gutter).
    out.clear()
    patchUiState({ status: 'nudge' })
    await tick(80)

    let v = 'hi'
    const perKeyScrollbar: number[] = []
    const perKeyBytes: number[] = []

    for (let k = 0; k < 8; k++) {
      out.clear()
      v += 'a'
      typeExternal(v)
      // A benign gateway heartbeat that churns $uiSections (a NEW-but-equal object
      // — the reference the live desk/panel sync produces every poll). This is a
      // field TranscriptPane still subscribes to, so it re-renders the transcript
      // (and its scrollbar) concurrent with the keystroke. Geometry is unchanged:
      // no wrap, no scroll, no content growth — so the thumb does not move and the
      // scrollbar column must stay put.
      patchUiState({ sections: {} })
      await tick(80)

      if (k > 1) {
        const f = out.text()
        perKeyScrollbar.push(scrollbarCells(f))
        perKeyBytes.push(Buffer.byteLength(f, 'utf8'))
      }
    }

    instance.unmount?.()

    // Every steady keystroke: no scrollbar cell may be (re-)emitted — the thumb
    // did not move, so col 201 must stay untouched. Pre-fix a transient viewport
    // explosion (the box's height constraint lost for one Yoga pass while React
    // re-arranges ancestors) flipped the bar to "not scrollable" and re-blit the
    // whole ~54-row gutter (│/┃ toggling against blank) on every re-render.
    for (const cells of perKeyScrollbar) {
      expect(cells).toBe(0)
    }

    // Bonus: the same explosion collapsed maxScroll and slammed the sticky
    // scrollTop, shifting (and re-blitting) the whole transcript body (~6.1 KB
    // pre-fix). With the viewport held stable the frame stays at composer scale.
    for (const bytes of perKeyBytes) {
      expect(bytes).toBeLessThan(500)
    }
  })
})
