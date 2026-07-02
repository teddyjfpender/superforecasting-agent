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

describe('MarketsView', () => {
  // Isolate to a temp home with no markets config so the view renders its
  // no-providers state deterministically.
  let prevHome: string | undefined
  let home: string

  beforeAll(async () => {
    const { mkdtempSync } = await import('node:fs')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    home = mkdtempSync(join(tmpdir(), 'markets-view-'))
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

  const renderMarkets = async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ render }, { MarketsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/marketsView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 36)
    const stdin = writeStream(120, 36, true)

    const instance = render(React.createElement(MarketsView, { onClose: () => undefined, t: DARK_THEME }), {
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
        await tick(60)
      },
      text: () => normalize(stdout.text(), stripAnsi)
    }
  }

  it('prompts to add data when no providers are configured', async () => {
    const { MarketsView } = await import('../components/marketsView.js')
    const text = await renderComponent(MarketsView)

    expect(text).toContain('MARKETS')
    expect(text).toContain('no providers')
    expect(text).toContain('Press d')
    expect(text).toContain('add providers')
    expect(text).toContain('search')
    // The close affordance now lives only in the FooterChips row (the duplicate
    // prose hint line — which read "… · Esc/q close" — was removed).
    expect(text).toContain('Close')
  })

  it('opens the add-data modal on d', async () => {
    const m = await renderMarkets()
    await m.press('d')
    const text = m.text()
    m.cleanup()

    expect(text).toContain('Add market data')
    expect(text).toContain('PROVIDERS')
    expect(text).toContain('Yahoo Finance')
    expect(text).toContain('CATEGORIES')
  })
})

describe('AddProviderModal', () => {
  const renderModal = async (initial: { categories: string[]; custom: never[]; providers: string[]; watchlist: never[] }) => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ Box, render }, { AddProviderModal }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/addProviderModal.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 32)
    const stdin = writeStream(120, 32, true)

    // The modal renders through ModalOverlay (an absolute box), so it needs a
    // sized ancestor to anchor to — exactly how the real view mounts it.
    const instance = render(
      React.createElement(
        Box as never,
        { flexDirection: 'column', height: 32, width: 120 } as never,
        React.createElement(AddProviderModal, {
          cols: 120,
          initial,
          onCancel: () => undefined,
          onSaved: () => undefined,
          rows: 32,
          t: DARK_THEME
        })
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(50)
    const text = normalize(stdout.text(), stripAnsi)
    instance.unmount?.()
    instance.cleanup?.()

    return text
  }

  it('lists every provider and the full breadth of categories', async () => {
    const text = await renderModal({ categories: [], custom: [], providers: [], watchlist: [] })

    // all providers
    for (const p of ['Yahoo Finance', 'Frankfurter', 'CoinGecko', 'FRED', 'BLS', 'BEA']) {
      expect(text).toContain(p)
    }

    // full category breadth (not just Indices/FX/Crypto/Commodities)
    for (const c of ['Indices', 'Commodities', 'Rates', 'Inflation', 'Employment', 'GDP', 'Trade']) {
      expect(text).toContain(c)
    }

    // keyed providers are flagged
    expect(text).toContain('key')
  })
})

describe('MarketSearchModal', () => {
  it('Enter adds to the item category; Tab adds to the watchlist', async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ Box, render }, { MarketSearchModal }, { DARK_THEME }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/marketSearchModal.js'),
      import('../theme.js')
    ])

    const stdout = writeStream(120, 28)
    const stdin = writeStream(120, 28, true)
    const toCategory: string[] = []
    const toWatch: string[] = []

    // The modal renders through ModalOverlay (an absolute box), so it needs a
    // sized ancestor to anchor to — exactly how the real view mounts it.
    const instance = render(
      React.createElement(
        Box as never,
        { flexDirection: 'column', height: 28, width: 120 } as never,
        React.createElement(MarketSearchModal, {
          cols: 120,
          isAdded: () => false,
          isWatched: () => false,
          onClose: () => undefined,
          onToggleCategory: (s: { symbol: string }) => toCategory.push(s.symbol),
          onToggleWatch: (s: { symbol: string }) => toWatch.push(s.symbol),
          rows: 28,
          t: DARK_THEME
        })
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(30)
    stdin.stream.write('nvda') // catalog match, no network needed
    await tick(40)
    stdin.stream.write('\r') // Enter → category
    await tick(20)
    stdin.stream.write('\t') // Tab → watchlist
    await tick(20)
    instance.unmount?.()
    instance.cleanup?.()

    expect(toCategory).toContain('NVDA')
    expect(toWatch).toContain('NVDA')
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

  // Render that exposes stdin so we can press the `s` setup shortcut.
  const renderMessaging = async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ render }, { MessagingView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/messagingView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 36)
    const stdin = writeStream(120, 36, true)

    const instance = render(React.createElement(MessagingView, { onClose: () => undefined, t: DARK_THEME }), {
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
        await tick(60)
      },
      text: () => normalize(stdout.text(), stripAnsi)
    }
  }

  it('prompts to press s to set up Signal when no account is configured', async () => {
    const { MessagingView } = await import('../components/messagingView.js')
    const text = await renderComponent(MessagingView)

    expect(text).toContain('MESSAGING')
    expect(text).toContain('Signal')
    expect(text).toContain('Telegram (soon)')
    expect(text).toContain('not connected')
    expect(text).toContain('Press s')
    expect(text).toContain('set up Signal')
    // The close affordance lives only in the FooterChips row now (the duplicate
    // prose hint line — which read "s set up Signal · Esc/q close" — was removed).
    expect(text).toContain('[q Close]')
    expect(text).not.toContain('start messaging…')
  })

  it('opens the in-TUI onboarding modal on s with a prerequisites check', async () => {
    const m = await renderMessaging()
    await m.press('s')
    // The setup modal is a tall (30-row) overlay whose lower rows (the register
    // path) paint over a couple of frames plus an async prerequisite probe — let
    // it settle before reading, so the assertion isn't racing the paint.
    await tick(150)
    const text = m.text()
    m.cleanup()

    expect(text).toContain('Connect Signal')
    expect(text).toContain('Prerequisites')
    expect(text).toContain('signal-cli')
    // both onboarding paths are offered
    expect(text).toContain('Link an existing')
    expect(text).toContain('Register a new')
  })
})
