import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// REAL-SESSION KEYSTROKE FLASH — "the right chat blinks when I type" (operator
// capture /tmp/tui-capture-1783499859.raw: kitty 202x56, ~7.3 KB written to the
// TRANSCRIPT region on every keystroke in an idle "ready" session).
//
// The existing composerFrameBudget / composerRepaintCount harnesses miss it:
// they drive $composerText from OUTSIDE the tree, sid=null, a hand-built
// transcript, AND they MOCK the transcript leaf. This one reproduces the live
// path — active sid, populated Recents, a tall real transcript over the two-pane
// Home (decstbm={false} + stickyScroll), REAL components — and, critically, a
// benign $uiState notify (a config-sync poll / usage / status heartbeat — fields
// the transcript does NOT render) landing WHILE a composer key is processed.
//
// Root cause: TranscriptPane subscribed to the whole $uiState, so any such
// background notify re-rendered it; concurrent with the keystroke that re-render
// walked the virtualized window through a transient FULL-HISTORY mount
// ([9,40] → [0,40] → [9,40]) and re-blitted the entire transcript region. Fix:
// narrow the subscription to the display slice ($uiTheme/$uiSessionId/$uiCompact/
// $uiDetailsMode/$uiDetailsCommandOverride/$uiSections) — same fix as the rail.
//
// Pins: whole-frame bytes/key stay at the composer-diff scale (pre-fix ~6.1 KB),
// the virtual window NEVER transiently full-mounts, and no ERASE_SCREEN.

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

// The composer diff is ~130-170 B/key. Pre-fix the transcript re-blit made this
// ~6.1 KB. 500 sits an order of magnitude below the regression and above the
// legitimate composer-line diff + cursor moves (matches keystroke-flash.test).
const PER_KEYSTROKE_CEILING = 500

describe('Home: a background $uiState notify must not re-blit the transcript while typing', () => {
  it('keeps the transcript window stable and the frame at composer scale', async () => {
    const ROWS = 56
    const COLS = 202

    const [{ AppLayout }, { GatewayProvider }, { Box, render }, { useVirtualHistory }] = await Promise.all([
      import('../components/appLayout.js'),
      import('../app/gatewayContext.js'),
      import('@superforecasting/ink'),
      import('../hooks/useVirtualHistory.js')
    ])

    const { resetOverlayState } = await import('../app/overlayStore.js')
    const { resetUiState, patchUiState, getUiState } = await import('../app/uiStore.js')
    const { syncComposerText, resetComposerText } = await import('../app/composerTextStore.js')
    const { setHomePane } = await import('../app/homeFocusStore.js')

    resetOverlayState()
    resetUiState()
    resetComposerText()
    // Active session — a real sid + model info, the state the report was under.
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
    // bottom (stickyScroll) — the geometry where a window shift re-blits the
    // whole region under decstbm={false}.
    const historyItems = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `• ${DESK_LINES[i % DESK_LINES.length]} (turn ${i})`
    }))

    const virtualRows = historyItems.map((msg, index) => ({ index, key: `m${index}`, msg }))

    const mainScrollRef = React.createRef<any>()

    // Harness parent: composer text in React state, re-rendered on every key
    // (like useMainApp). Syncs to $composerText via a layout effect (like
    // useComposerState) and memoizes the composer WITHOUT the text (like
    // appComposer) — the exact production data flow. Records the transcript's
    // virtual window on every render so we can pin it against the full-mount.
    let typeExternal: (v: string) => void = noop
    const windows: { start: number; ts: number }[] = []

    const Harness = () => {
      const [input, setInput] = React.useState('hi')
      typeExternal = setInput

      React.useLayoutEffect(() => {
        syncComposerText(input, [])
      }, [input])

      const scrollRef = mainScrollRef
      const rows = React.useMemo(() => virtualRows, [])
      const virtualHistory = useVirtualHistory(scrollRef, rows, COLS - 32)

      windows.push({ start: virtualHistory.start, ts: virtualHistory.topSpacer })

      const transcript = React.useMemo(
        () => ({ historyItems, scrollRef, virtualHistory, virtualRows: rows }),
        [rows, scrollRef, virtualHistory]
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

    // Baseline the settled window (steady state before typing).
    const baseWindow = windows[windows.length - 1]!
    expect(baseWindow.ts).toBeGreaterThan(0) // transcript is virtualized (clipped)

    const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`
    let v = 'hi'
    const perKey: number[] = []
    let sawClear = false

    for (let k = 0; k < 8; k++) {
      out.clear()
      v += 'a'
      const before = windows.length
      typeExternal(v)
      // A benign $uiState heartbeat (fields the transcript never renders) landing
      // while the composer key is processed — the live-session trigger.
      patchUiState({ status: `ready ${k}`, usage: { ...getUiState().usage, total: k } as any })
      await tick(80)

      const frame = out.text()

      if (frame.includes(ERASE_SCREEN)) {
        sawClear = true
      }

      // Drop the first two keystrokes (one-time settle); pin the steady state.
      if (k > 1) {
        perKey.push(Buffer.byteLength(frame, 'utf8'))

        // No render during this key may transiently mount the full history. The
        // transcript is virtualized (baseWindow.ts > 0), so the window top must
        // stay OFF the head — pre-fix a concurrent notify collapsed it to
        // start=0 / topSpacer=0 (full mount) and re-blitted the whole region.
        for (const w of windows.slice(before)) {
          expect(w.start).toBeGreaterThan(0)
          expect(w.ts).toBeGreaterThan(0)
        }
      }
    }

    instance.unmount?.()

    // The full-repaint erase must never appear per key.
    expect(sawClear).toBe(false)

    // Every steady keystroke stays at composer-diff scale — no transcript re-blit.
    for (const bytes of perKey) {
      expect(bytes).toBeLessThan(PER_KEYSTROKE_CEILING)
    }
  })
})
