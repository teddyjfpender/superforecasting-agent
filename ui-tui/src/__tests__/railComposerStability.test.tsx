import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// The Home two-pane conversation view keeps a recent-conversations rail on the
// left and the transcript + composer on the right. Typing a multi-line message
// grows the composer — that growth must shrink the TRANSCRIPT, never the rail.
// A regression once let the composer ride a footer row spanning the full width
// below the rail+transcript row, so every new composer line stole a row from the
// rail's ScrollBox and scrolled the Recents list. This test pins the rail's
// measured viewport height so it stays invariant as the composer grows.
//
// Shell=Fragment (INLINE) + an explicit height box gives a tree that is clamped
// to the terminal rows (the reliable constraint the ink viewport tests use), so
// the rail ScrollBox measures a real, bounded viewport.
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

  return { stream, text: () => output }
}

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const noop = () => {}

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

describe('Home two-pane: Recent rail height is independent of composer growth', () => {
  it('keeps the rail ScrollBox viewport constant as the composer gains lines', async () => {
    const ROWS = 24
    const COLS = 120

    const [{ AppLayout }, { GatewayProvider }, { Box, render }] = await Promise.all([
      import('../components/appLayout.js'),
      import('../app/gatewayContext.js'),
      import('@hermes/ink')
    ])

    const { resetOverlayState } = await import('../app/overlayStore.js')
    const { resetUiState } = await import('../app/uiStore.js')
    const { $composerText } = await import('../app/composerTextStore.js')
    resetOverlayState()
    resetUiState()
    $composerText.set({ input: 'hi', inputBuf: [] })

    const sessions = Array.from({ length: 30 }, (_, i) => ({
      id: `s${i}`,
      message_count: 1,
      preview: '',
      source: 'tui',
      started_at: 30 - i,
      title: `recent chat number ${i + 1}`
    }))

    const gw: any = {
      request: async (m: string) => (m === 'session.list' ? { sessions } : null),
      rpc: async () => null,
      on: noop,
      off: noop
    }

    const railScrollRef = React.createRef<any>()
    const scrollRef = React.createRef<any>()

    // A non-empty history makes this an ACTIVE conversation (not the landing),
    // so the transcript + composer render on the right of the rail.
    const msg = { role: 'user' as const, text: 'hello world' }

    const transcript: any = {
      historyItems: [msg],
      railScrollRef,
      scrollRef,
      virtualHistory: {
        bottomSpacer: 0,
        end: 1,
        measureRef: () => () => {},
        offsets: [0],
        start: 0,
        topSpacer: 0
      },
      virtualRows: [{ index: 0, key: 'm0', msg }]
    }

    // The composer text lives in $composerText now; growing it there is what
    // grows the input box (exactly like typing does in production).
    const composer = buildComposer(COLS)

    const App = () =>
      React.createElement(
        Box,
        { flexDirection: 'column', height: ROWS, width: COLS },
        React.createElement(
          GatewayProvider,
          { value: { gw, rpc: gw.rpc } },
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

    const instance: any = await render(React.createElement(App), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: writeStream(COLS, ROWS).stream
    })

    await tick(160)

    const viewportFor = async (input: string) => {
      $composerText.set({ input, inputBuf: [] })
      await tick(120)

      return railScrollRef.current?.getViewportHeight() ?? -1
    }

    // Single-line baseline, then progressively taller multi-line composer input.
    const base = await viewportFor('hi')

    const grown = [
      await viewportFor('a\nb'),
      await viewportFor('a\nb\nc'),
      await viewportFor('a\nb\nc\nd'),
      await viewportFor('a\nb\nc\nd\ne')
    ]

    instance.unmount?.()

    // The rail must have a real, bounded viewport (harness properly constrained).
    expect(base).toBeGreaterThan(0)

    // Every taller composer leaves the rail's viewport untouched.
    for (const vp of grown) {
      expect(vp).toBe(base)
    }
  })
})
