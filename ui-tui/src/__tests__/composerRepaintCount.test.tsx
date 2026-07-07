import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it, vi } from 'vitest'

// The composer moved into the right column of the Home two-pane (commit
// ae97fe508). Regression: because the transcript pane received the whole
// `composer` object — a fresh identity on every keystroke — it re-rendered on
// each keypress, re-blitting the transcript region and full-repainting the
// screen (the "flash"). The rail pane was already memo-safe.
//
// This pins BOTH subtrees: after the fix (transcript keyed on `cols`, a stable
// number), typing 5 characters must re-render NEITHER the Recents rail NOR the
// transcript. Counting proxies: the mocked leaf components below are called
// once per render of their memoised parent pane, so a stable count == the pane
// did not re-render.

let railRenders = 0
let streamRenders = 0

vi.mock('../components/conversationsRail.js', () => ({
  ConversationsRail: (_props: any) => {
    railRenders++

    return null
  }
}))

vi.mock('../components/streamingAssistant.js', () => ({
  LiveTodoPanel: () => null,
  StreamingAssistant: (_props: any) => {
    streamRenders++

    return null
  }
}))

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

describe('Home two-pane: composer keystrokes do not re-render the rail or transcript', () => {
  it('typing 5 characters re-renders neither subtree', async () => {
    const ROWS = 24
    const COLS = 120

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
    const msg = { role: 'user' as const, text: 'hello world' }
    const transcript: any = {
      historyItems: [msg],
      railScrollRef,
      scrollRef,
      virtualHistory: { bottomSpacer: 0, end: 1, measureRef: () => () => {}, offsets: [0], start: 0, topSpacer: 0 },
      virtualRows: [{ index: 0, key: 'm0', msg }]
    }

    // Stable gateway value — exactly like the app's useMemo'd gateway. An
    // unstable context value would re-render every consumer through memo, so a
    // faithful reproduction must hold it fixed across keystrokes.
    const gwValue = { gw, rpc: gw.rpc }

    // Typing writes to $composerText (as useComposerState does), NOT to a prop —
    // so `composer` is a stable object and only store subscribers re-render.
    const setInput = (s: string) => setComposerInput(s)
    const composer: any = {
      cols: COLS,
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
    }

    const App = () => {
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
    const instance: any = await render(React.createElement(App), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: writeStream(COLS, ROWS, true).stream,
      stdout: out.stream
    })
    await tick(200)

    const railBaseline = railRenders
    const streamBaseline = streamRenders

    let v = 'hi'
    for (const ch of ['a', 'b', 'c', 'd', 'e']) {
      v += ch
      setInput(v)
      await tick(70)
    }

    // Zero additional renders of either memoised subtree.
    expect(railRenders - railBaseline).toBe(0)
    expect(streamRenders - streamBaseline).toBe(0)

    instance.unmount?.()
  })
})
