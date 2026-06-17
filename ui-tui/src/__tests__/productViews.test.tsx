import { PassThrough } from 'stream'

import React from 'react'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

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
    // bracketed keybinding chip layer (parity with Obsidian)
    expect(text).toContain('[⇥ Category]')
    expect(text).toContain('[q Close]')
  })
})

describe('NewsView', () => {
  // Isolate the subscription store to a fresh temp home so these tests don't
  // read/write the developer's real ~/.superforecasting-agent.
  let prevHome: string | undefined
  let home: string

  beforeAll(async () => {
    const { mkdtempSync } = await import('node:fs')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    home = mkdtempSync(join(tmpdir(), 'news-view-'))
    prevHome = process.env.SUPERFORECASTING_AGENT_HOME
    process.env.SUPERFORECASTING_AGENT_HOME = home
  })

  afterAll(async () => {
    const { rmSync } = await import('node:fs')
    rmSync(home, { force: true, recursive: true })

    if (prevHome === undefined) {
      delete process.env.SUPERFORECASTING_AGENT_HOME
    } else {
      process.env.SUPERFORECASTING_AGENT_HOME = prevHome
    }
  })

  // Render that exposes stdin so we can drive key presses.
  const renderNews = async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ render }, { NewsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/newsView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 40)
    const stdin = writeStream(120, 40, true)

    const instance = render(React.createElement(NewsView, { onClose: () => undefined, t: DARK_THEME }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: stdin.stream,
      stdout: stdout.stream
    })

    await tick(40)

    return {
      cleanup: () => {
        instance.unmount?.()
        instance.cleanup?.()
      },
      press: async (keys: string) => {
        stdin.stream.write(keys)
        await tick(40)
      },
      text: () => normalize(stdout.text(), stripAnsi)
    }
  }

  it('renders the three-pane scaffold and a no-feeds-yet empty state', async () => {
    const n = await renderNews()
    const text = n.text()
    n.cleanup()

    expect(text).toContain('NEWS')
    expect(text).toContain('live RSS feeds')
    expect(text).toContain('SOURCES')
    expect(text).toContain('All feeds')
    expect(text).toContain('READER')
    expect(text).toContain('No feeds yet')
    // bracketed keybinding chip layer
    expect(text).toContain('[a Add feed]')
    expect(text).toContain('[q Close]')
  })

  it('opens the Add-feed modal on "a", shows categories, and searches the catalog', async () => {
    const n = await renderNews()
    await n.press('a')
    const opened = n.text()
    expect(opened).toContain('Add a feed')
    expect(opened).toContain('subscribed')
    expect(opened).toContain('CATEGORIES') // scrollable category rail
    expect(opened).toContain('All') // the 'All' (unfiltered) category
    expect(opened).toContain('[ ]') // unchecked subscription boxes

    // Typing filters the catalog — "hacker" surfaces the Hacker News feed.
    await n.press('hacker')
    const searched = n.text()
    n.cleanup()
    expect(searched).toContain('Hacker News')
  })

  it('subscribes the highlighted feed on Enter and persists it to the store', async () => {
    const { loadSubscribedFeeds, newsFeedsFile } = await import('../lib/newsFeedStore.js')
    expect(loadSubscribedFeeds(newsFeedsFile(home))).toHaveLength(0)

    const n = await renderNews()
    await n.press('a') // open modal
    await n.press('\r') // Enter → toggle the top result
    const after = n.text()
    n.cleanup()

    // The always-rendered header reflects the new subscription count…
    expect(after).toContain('1 subscribed')
    // …and the feed was written through to the store on disk (source of truth).
    const saved = loadSubscribedFeeds(newsFeedsFile(home))
    expect(saved).toHaveLength(1)
    expect(saved[0].url).toMatch(/^https?:\/\//)
  })
})

describe('MessagingView', () => {
  // Isolate to a temp home with no signal config so the view renders its
  // setup-guide state deterministically (not the connected/Signal state).
  let prevHome: string | undefined
  let prevAcct: string | undefined
  let home: string

  beforeAll(async () => {
    const { mkdtempSync } = await import('node:fs')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    home = mkdtempSync(join(tmpdir(), 'msg-view-'))
    prevHome = process.env.SUPERFORECASTING_AGENT_HOME
    prevAcct = process.env.SIGNAL_ACCOUNT
    process.env.SUPERFORECASTING_AGENT_HOME = home
    delete process.env.SIGNAL_ACCOUNT
  })

  afterAll(async () => {
    const { rmSync } = await import('node:fs')
    rmSync(home, { force: true, recursive: true })

    if (prevHome === undefined) {
      delete process.env.SUPERFORECASTING_AGENT_HOME
    } else {
      process.env.SUPERFORECASTING_AGENT_HOME = prevHome
    }

    if (prevAcct !== undefined) {
      process.env.SIGNAL_ACCOUNT = prevAcct
    }
  })

  it('renders the Signal setup guide when no account is configured', async () => {
    const { MessagingView } = await import('../components/messagingView.js')
    const text = await renderComponent(MessagingView)

    expect(text).toContain('MESSAGING')
    expect(text).toContain('Signal')
    expect(text).toContain('Telegram (soon)')
    expect(text).toContain('not connected')
    // setup guide content + footer keys (not a persistent composer)
    expect(text).toContain('signal-cli')
    expect(text).toContain('SIGNAL_ACCOUNT')
    expect(text).toContain('Esc/q close')
    expect(text).not.toContain('start messaging…')
  })
})
