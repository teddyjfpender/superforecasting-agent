import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// Companion to railScroll.test.tsx / railComposerStability.test.tsx — renders
// the REAL AppLayout (memoized TranscriptPane included) and pins the scroll
// interaction contract's re-render clause: the transcript's scroll position
// must survive re-renders. Composer keystrokes re-render AppLayout; the
// memoized TranscriptPane must neither re-anchor nor move the viewport.

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

const buildComposer = (input: string, cols: number): any => ({
  cols,
  compIdx: 0,
  completions: [],
  empty: input.length === 0,
  handleTextPaste: async () => null,
  input,
  inputBuf: [],
  pagerPageSize: 10,
  queueEditIdx: null,
  queuedDisplay: [],
  submit: noop,
  updateInput: noop,
  voiceRecordKey: null
})

describe('memoized TranscriptPane: scroll position survives re-renders', () => {
  it('composer keystrokes leave the transcript scroll position untouched', async () => {
    const ROWS = 24
    const COLS = 120

    const [{ AppLayout }, { GatewayProvider }, { Box, render }] = await Promise.all([
      import('../components/appLayout.js'),
      import('../app/gatewayContext.js'),
      import('@hermes/ink')
    ])

    const { resetOverlayState } = await import('../app/overlayStore.js')
    const { resetUiState } = await import('../app/uiStore.js')
    resetOverlayState()
    resetUiState()

    const sessions = Array.from({ length: 10 }, (_, i) => ({
      id: `s${i}`,
      message_count: 1,
      preview: '',
      source: 'tui',
      started_at: 10 - i,
      title: `chat ${i + 1}`
    }))

    const gw: any = {
      off: noop,
      on: noop,
      request: async (m: string) => (m === 'session.list' ? { sessions } : null),
      rpc: async () => null
    }

    // A tall transcript so the ScrollBox actually overflows and scrolls.
    const items = Array.from({ length: 60 }, (_, i) => ({
      role: (i % 2 ? 'assistant' : 'user') as const,
      text: `message number ${i} with several words to force some real height`
    }))

    const scrollRef = React.createRef<any>()

    const transcript: any = {
      historyItems: items,
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

    const gwValue = { gw, rpc: gw.rpc }

    const App = ({ input }: { input: string }) =>
      React.createElement(
        Box,
        { flexDirection: 'column', height: ROWS, width: COLS },
        React.createElement(
          GatewayProvider,
          { value: gwValue },
          React.createElement(AppLayout, {
            actions,
            composer: buildComposer(input, COLS),
            mouseTracking: false,
            progress,
            status,
            transcript
          })
        )
      )

    const instance: any = await render(React.createElement(App, { input: 'hi' }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: writeStream(COLS, ROWS).stream
    })

    await tick(200)

    // A real, overflowing transcript viewport.
    const vp = scrollRef.current?.getViewportHeight() ?? 0
    const sh = scrollRef.current?.getScrollHeight() ?? 0
    expect(vp).toBeGreaterThan(0)
    expect(sh).toBeGreaterThan(vp)

    // Scroll to a mid-history reading position (NOT the bottom edge).
    const target = Math.floor((sh - vp) / 2)
    scrollRef.current?.scrollTo(target)
    await tick(120)
    const before = scrollRef.current?.getScrollTop() ?? -1
    expect(before).toBe(target)
    expect(scrollRef.current?.isSticky()).toBe(false)

    // Type: each keystroke re-renders AppLayout. The memoized TranscriptPane
    // must hold the viewport absolutely still — no re-anchor, no snap-back.
    // (The historical failure: a keystroke commit produced a one-frame
    // transient where the transcript ScrollBox's viewport exploded to the
    // content height — maxScroll cratered to 0, the parked scrollTop was
    // clamped to the TOP of the chat, and the recovery frame then read "grew
    // while at bottom" and yanked the reader to the BOTTOM, restoring sticky.)
    let v = 'hi'

    for (let k = 0; k < 5; k++) {
      v += 'a'
      instance.rerender(React.createElement(App, { input: v }))

      await tick(80)
      expect(scrollRef.current?.getScrollTop()).toBe(before)
      expect(scrollRef.current?.isSticky()).toBe(false)
    }

    instance.unmount?.()
  })
})
