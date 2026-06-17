import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

// Smoke tests for the three "serious product" views — Markets, News, and
// Messaging. They ship without a live data source wired yet, so these assert
// the SCAFFOLD: each renders its title, a connection-status hint, the column /
// rail structure, and an honest "data will populate here" empty state. That
// locks in the shape data slots into once a feed is connected.

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

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

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const renderComponent = async (component: React.ComponentType<{ onClose: () => void; t: unknown }>) => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(110, 40)
  const stdin = writeStream(110, 40, true)

  const instance = render(React.createElement(component, { onClose: () => undefined, t: DARK_THEME }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: stdin.stream,
    stdout: stdout.stream
  })

  await tick(40)
  const text = normalize(stdout.text(), stripAnsi)
  instance.unmount?.()
  instance.cleanup?.()

  return text
}

afterEach(() => {
  delete process.env.FORECAST_TUI_INLINE
})

describe('MarketsView scaffold', () => {
  it('renders the title, category tabs, quote table header, and an awaiting-feed hint', async () => {
    const { MarketsView } = await import('../components/marketsView.js')
    const text = await renderComponent(MarketsView)

    expect(text).toContain('MARKETS')
    expect(text).toContain('live quotes')
    // category tabs
    expect(text).toContain('Watchlist')
    expect(text).toContain('Crypto')
    // quote table column headers
    expect(text).toContain('SYMBOL')
    expect(text).toContain('LAST')
    expect(text).toContain('CHG%')
    // honest empty state + footer keys
    expect(text).toContain('Awaiting market feed')
    expect(text).toContain('Esc/q close')
  })
})

describe('NewsView scaffold', () => {
  it('renders the title, sources rail, and a no-feeds-yet hint', async () => {
    const { NewsView } = await import('../components/newsView.js')
    const text = await renderComponent(NewsView)

    expect(text).toContain('NEWS')
    expect(text).toContain('live RSS feeds')
    // sources rail
    expect(text).toContain('SOURCES')
    expect(text).toContain('All feeds')
    expect(text).toContain('Technology')
    // honest empty state + footer keys
    expect(text).toContain('No feeds configured yet')
    expect(text).toContain('add feed')
  })
})

describe('MessagingView scaffold', () => {
  it('renders the title, channels, chat rail, and a connect hint (no input composer)', async () => {
    const { MessagingView } = await import('../components/messagingView.js')
    const text = await renderComponent(MessagingView)

    expect(text).toContain('MESSAGING')
    expect(text).toContain('Telegram')
    expect(text).toContain('Signal')
    // conversation rail
    expect(text).toContain('CHATS')
    // honest empty state in the thread pane
    expect(text).toContain('Not connected')
    // interaction parity with the other routes: a footer hint, not a typing
    // composer pinned to the bottom like the home route has.
    expect(text).toContain('Esc/q close')
    expect(text).not.toContain('start messaging…')
  })
})
