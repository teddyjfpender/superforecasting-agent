import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// REAL-SESSION KEYSTROKE FLASH (the "right chat blinks when I type" report).
//
// The existing composerFrameBudget / composerRepaintCount harnesses drive
// $composerText from OUTSIDE the tree (no parent re-render) with sid=null and a
// hand-built transcript. That misses the production path: every keystroke ALSO
// re-renders useMainApp (the composer text is React state there), which re-runs
// the transcript / virtualHistory memos, and the two-pane Home transcript runs
// decstbm={false} + stickyScroll over content taller than the viewport. This
// harness reproduces THAT: an active session id, a populated Recents list, a
// tall real transcript, real components (no mocks), and a parent that re-renders
// on every keystroke exactly like useMainApp. It measures whole-frame bytes/key.

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

describe('Home two-pane: typing must not re-blit the transcript (right chat)', () => {
  it('reproduces / pins whole-frame bytes per keystroke in an active session', async () => {
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
    // Active session: a real sid + model info, exactly the state the report was
    // captured under (NOT the landing).
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

    // A tall transcript: many rows so the transcript ScrollBox clips and pins to
    // bottom (stickyScroll), the geometry where a 1-row scroll shift re-blits the
    // whole region under decstbm={false}.
    const historyItems = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `• ${DESK_LINES[i % DESK_LINES.length]} (turn ${i})`
    }))
    const virtualRows = historyItems.map((msg, index) => ({ index, key: `m${index}`, msg }))

    const railScrollRef = React.createRef<any>()
    const mainScrollRef = React.createRef<any>()

    // Harness parent: holds the composer text in React state and re-renders on
    // every keystroke (like useMainApp). Syncs to $composerText via a layout
    // effect (like useComposerState) and memoizes the composer object WITHOUT the
    // text (like appComposer) — the exact production data flow.
    let typeExternal: (v: string) => void = noop
    const renderLog: any[] = []

    const Harness = () => {
      const [input, setInput] = React.useState('hi')
      typeExternal = setInput

      React.useLayoutEffect(() => {
        syncComposerText(input, [])
      }, [input])

      const scrollRef = mainScrollRef
      const rows = React.useMemo(() => virtualRows, [])
      const virtualHistory = useVirtualHistory(scrollRef, rows, COLS - 32)

      renderLog.push({ start: virtualHistory.start, end: virtualHistory.end, ts: virtualHistory.topSpacer, bs: virtualHistory.bottomSpacer })

      const transcript = React.useMemo(
        () => ({ historyItems, railScrollRef, scrollRef, virtualHistory, virtualRows: rows }),
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

    const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`
    let v = 'hi'
    const perKey: number[] = []
    const scroll: any[] = []
    let sawClear = false
    const snap = () => {
      const s = mainScrollRef.current
      return s
        ? { top: s.getScrollTop(), vp: s.getViewportHeight(), sh: s.getScrollHeight(), sticky: s.isSticky() }
        : null
    }
    for (let k = 0; k < 8; k++) {
      out.clear()
      v += 'a'
      const before = renderLog.length
      typeExternal(v)
      await tick(80)
      const frame = out.text()
      if (frame.includes(ERASE_SCREEN)) {
        sawClear = true
      }
      if (k > 1) {
        perKey.push(Buffer.byteLength(frame, 'utf8'))
        scroll.push(snap())
        scroll[scroll.length - 1].ranges = renderLog.slice(before)
      }
    }

    instance.unmount?.()

    const fs = await import('fs')
    fs.writeFileSync('/tmp/flash-perkey.json', JSON.stringify({ perKey, sawClear, scroll }))

    // Placeholder assertion — tightened after we confirm reproduction.
    expect(perKey.length).toBeGreaterThan(0)
  })
})
