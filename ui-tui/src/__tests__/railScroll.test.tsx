import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// Companion to railComposerStability.test.tsx. That test pins the rail's
// viewport height as the composer grows; these pin the two operator-facing
// behaviours that regressed after the composer moved into the right column:
//
//   1. The Recents rail must still SCROLL — moving the rail's scroll position
//      changes which conversations are visible (the ScrollBox still culls to a
//      bounded viewport in the full-height two-pane layout).
//   2. Typing in the composer must NOT full-repaint the screen. The transcript
//      subtree is memoised against composer keystrokes, so each keystroke emits
//      a small localized diff — never a full-screen clear (the "flash").
//
// Both render the REAL AppLayout so the height chain (rail ScrollBox viewport,
// transcript ScrollBox viewport) is the production one.

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
  cwdLabel: '~/x',
  forecastPulseTick: 0,
  sessionStartedAt: null,
  showStickyPrompt: false,
  statusColor: 'white',
  stickyPrompt: '',
  turnStartedAt: null,
  voiceLabel: ''
}

const progress: any = { showProgressArea: false }

const buildComposer = (cols: number): any => ({
  cols,
  compIdx: 0,
  completions: [],
  empty: false,
  handleTextPaste: async () => null,
  pagerPageSize: 10,
  queueEditIdx: null,
  queuedDisplay: [],
  submit: noop,
  updateInput: noop,
  voiceRecordKey: null
})

const stripEsc = (raw: string) => raw.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, 'g'), '')

const setup = async () => {
  const [{ AppLayout }, { GatewayProvider }, { Box, render }] = await Promise.all([
    import('../components/appLayout.js'),
    import('../app/gatewayContext.js'),
    import('@hermes/ink')
  ])

  const { resetOverlayState } = await import('../app/overlayStore.js')
  const { resetUiState } = await import('../app/uiStore.js')
  const { $composerText, setComposerInput } = await import('../app/composerTextStore.js')
  resetOverlayState()
  resetUiState()
  $composerText.set({ input: 'hi', inputBuf: [] })

  return { AppLayout, Box, GatewayProvider, render, setComposerInput }
}

describe('Home two-pane: Recents rail scrolls; composer keystrokes never flash', () => {
  it('scrolling the rail moves the visible window of conversations', async () => {
    const ROWS = 24
    const COLS = 120
    const { AppLayout, Box, GatewayProvider, render } = await setup()

    // Distinctive, greppable titles so the visible window is observable in the
    // captured frame. Many more rows than fit the viewport, so the list
    // overflows and scrolls.
    const label = (i: number) => `ZZ${i}zz`

    const sessions = Array.from({ length: 40 }, (_, i) => ({
      id: `s${i}`,
      message_count: 1,
      preview: '',
      source: 'tui',
      started_at: 40 - i,
      title: label(i)
    }))

    const gw: any = {
      off: noop,
      on: noop,
      request: async (m: string) => (m === 'session.list' ? { sessions } : null),
      rpc: async () => null
    }

    const railScrollRef = React.createRef<any>()
    const scrollRef = React.createRef<any>()
    const msg = { role: 'user' as const, text: 'hello world' }

    const transcript: any = {
      historyItems: [msg],
      railScrollRef,
      scrollRef,
      virtualHistory: { bottomSpacer: 0, end: 1, measureRef: () => () => {}, offsets: [0], start: 0, topSpacer: 0 },
      virtualRows: [{ index: 0, key: 'm0', msg }]
    }

    const gwValue = { gw, rpc: gw.rpc }

    const App = ({ cols }: { cols: number }) =>
      React.createElement(
        Box,
        { flexDirection: 'column', height: ROWS, width: cols },
        React.createElement(
          GatewayProvider,
          { value: gwValue },
          React.createElement(AppLayout, {
            actions,
            composer: buildComposer(cols),
            mouseTracking: false,
            progress,
            status,
            transcript
          })
        )
      )

    const out = writeStream(COLS, ROWS)

    const instance: any = await render(React.createElement(App, { cols: COLS }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: out.stream
    })

    await tick(200)

    // The rail is a real, bounded, overflowing ScrollBox (content > viewport).
    const viewport = railScrollRef.current?.getViewportHeight() ?? 0
    const scrollHeight = railScrollRef.current?.getScrollHeight() ?? 0
    expect(viewport).toBeGreaterThan(0)
    expect(scrollHeight).toBeGreaterThan(viewport)

    // The initial full frame shows the top of the list; a conversation past the
    // viewport is not yet visible.
    const deepIndex = viewport + 8 // comfortably past the first window
    const before = stripEsc(out.text()).replace(/\s+/g, '')
    expect(before).toContain(label(0))
    expect(before).not.toContain(label(deepIndex))
    const topBefore = railScrollRef.current?.getScrollTop() ?? -1

    // Scroll the rail down past the first viewport.
    railScrollRef.current?.scrollTo(deepIndex)
    await tick(120)
    const topAfter = railScrollRef.current?.getScrollTop() ?? -1

    // Force a clean full frame (a bare scroll writes only a partial diff, which
    // reuses cells shared with the row's previous occupant): a width change
    // repaints the whole viewport so the scrolled rail window renders in full.
    out.clear()
    out.stream.columns = COLS - 1
    out.stream.emit('resize')
    instance.rerender(React.createElement(App, { cols: COLS - 1 }))
    await tick(150)
    const after = stripEsc(out.text()).replace(/\s+/g, '')

    // The scroll position advanced...
    expect(topAfter).toBeGreaterThan(topBefore)
    // ...and the visible window moved: a previously-hidden, deeper conversation
    // scrolled into view and the first row scrolled out.
    expect(after).toContain(label(deepIndex))
    expect(after).not.toContain(label(0))

    instance.unmount?.()
  })

  it('a composer keystroke emits no full-screen clear and only a small diff', async () => {
    const ROWS = 30
    const COLS = 120
    const { AppLayout, Box, GatewayProvider, render, setComposerInput } = await setup()

    // A tall transcript: if a keystroke re-blitted the transcript region, the
    // per-keystroke byte count would balloon and/or a full clear would fire.
    const items = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `message number ${i} with several words to force some real height here`
    }))

    const sessions = Array.from({ length: 40 }, (_, i) => ({
      id: `s${i}`,
      message_count: 1,
      preview: '',
      source: 'tui',
      started_at: 40 - i,
      title: `chat ${i + 1}`
    }))

    const gw: any = {
      off: noop,
      on: noop,
      request: async (m: string) => (m === 'session.list' ? { sessions } : null),
      rpc: async () => null
    }

    const railScrollRef = React.createRef<any>()
    const scrollRef = React.createRef<any>()

    const transcript: any = {
      historyItems: items,
      railScrollRef,
      scrollRef,
      virtualHistory: {
        bottomSpacer: 0,
        end: items.length,
        measureRef: () => () => {},
        offsets: items.map((_, i) => i),
        start: 0,
        topSpacer: 0
      },
      virtualRows: items.map((m, i) => ({ index: i, key: `m${i}`, msg: m }))
    }

    // Stable gateway value, exactly like the app's useMemo'd gateway — an
    // unstable context value would re-render every consumer through memo.
    const gwValue = { gw, rpc: gw.rpc }

    // Typing writes to $composerText (as production does); the transcript region
    // must not re-blit under it.
    const setInput = (s: string) => setComposerInput(s)
    const composer = buildComposer(COLS)

    const App = () =>
      React.createElement(
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

    const out = writeStream(COLS, ROWS)

    const instance: any = await render(React.createElement(App), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: out.stream
    })

    await tick(250)

    // ERASE_SCREEN (CSI 2 J) is the full-repaint "flash" signal.
    const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`
    const steadyBytes: number[] = []
    let v = 'hi'

    // First keystroke pays a one-time layout settle; measure the steady state
    // over the following keystrokes.
    for (let k = 0; k < 6; k++) {
      out.clear()
      v += 'a'
      setInput(v)
      await tick(90)
      const frame = out.text()
      expect(frame).not.toContain(ERASE_SCREEN)

      if (k > 0) {
        steadyBytes.push(frame.length)
      }
    }

    // A localized composer diff is a few hundred bytes at most; a full re-blit
    // of this transcript is >1500. Guard well below the flash regime.
    for (const b of steadyBytes) {
      expect(b).toBeLessThan(600)
    }

    instance.unmount?.()
  })
})
