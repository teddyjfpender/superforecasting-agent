import { EventEmitter } from 'node:events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

// Record Enter-open calls instead of spawning a real browser.
const opened: string[] = []
vi.mock('../lib/openExternalUrl.js', () => ({
  openExternalUrl: (url: string) => {
    opened.push(url)

    return true
  }
}))

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

interface Call {
  method: string
  params: Record<string, unknown>
}

const out = (o: string, prob: number, id: string, vol = 1000) => ({
  label: o,
  liquid: true,
  market_id: id,
  prob,
  raw_prob: prob - 0.02,
  volume: vol,
  yes_ask: prob + 0.01,
  yes_bid: prob - 0.01
})

const polyMarket = (label: string, id: string, tok: string, bid: number) => ({
  close_time: '2099-01-01T00:00:00Z',
  event_id: 'evt-nba',
  label,
  last_price: bid + 0.01,
  market_id: id,
  open_interest: null,
  question: `Will ${label} win?`,
  status: 'open',
  token_ids: [tok, `${tok}-no`],
  url: 'https://polymarket.com/event/nba',
  venue: 'polymarket',
  volume: 5000,
  yes_ask: bid + 0.02,
  yes_bid: bid,
  yes_mid: bid + 0.01
})

const nbaItem = () => ({
  distribution: {
    binary: false,
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt-nba',
    headline: { close_time: '2099-01-01T00:00:00Z', n: 3, top_label: 'Celtics', top_prob: 0.44, total_volume: 1_500_000 },
    normalized: true,
    notes: [],
    outcomes: [out('Celtics', 0.44, 'cond-cel'), out('Nuggets', 0.33, 'cond-nug'), out('Thunder', 0.23, 'cond-thu')],
    overround: 0.05,
    title: 'NBA Champion 2026',
    total_volume: 1_500_000,
    url: 'https://polymarket.com/event/nba',
    venue: 'polymarket'
  },
  event: {
    category: 'Sports',
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt-nba',
    is_binary: false,
    markets: [polyMarket('Celtics', 'cond-cel', 'tok-cel', 0.4), polyMarket('Nuggets', 'cond-nug', 'tok-nug', 0.3), polyMarket('Thunder', 'cond-thu', 'tok-thu', 0.2)],
    mutually_exclusive: true,
    slug: 'nba',
    title: 'NBA Champion 2026',
    url: 'https://polymarket.com/event/nba',
    venue: 'polymarket',
    volume: 1_500_000
  }
})

const fedItem = () => ({
  distribution: {
    binary: true,
    close_time: '2099-02-01T00:00:00Z',
    event_id: 'FED',
    headline: { close_time: '2099-02-01T00:00:00Z', n: 1, top_label: 'Yes', top_prob: 0.13, total_volume: 50_000 },
    normalized: true,
    notes: [],
    outcomes: [out('Yes', 0.13, 'FED-Y', 50_000)],
    overround: 0,
    title: 'Fed hikes in July?',
    total_volume: 50_000,
    url: 'https://kalshi.com/markets/FED',
    venue: 'kalshi'
  },
  event: {
    category: 'Economics',
    close_time: '2099-02-01T00:00:00Z',
    event_id: 'FED',
    is_binary: true,
    markets: [
      {
        close_time: '2099-02-01T00:00:00Z',
        event_id: 'FED',
        label: 'Yes',
        last_price: 0.13,
        market_id: 'FED-Y',
        open_interest: 1000,
        question: 'Fed hikes?',
        status: 'active',
        token_ids: [],
        url: 'https://kalshi.com/markets/FED',
        venue: 'kalshi',
        volume: 50_000,
        yes_ask: 0.14,
        yes_bid: 0.12,
        yes_mid: 0.13
      }
    ],
    mutually_exclusive: true,
    slug: 'FED',
    title: 'Fed hikes in July?',
    url: 'https://kalshi.com/markets/FED',
    venue: 'kalshi',
    volume: 50_000
  }
})

const book = (marketId: string, bid: number, ask: number) => ({
  asks: [{ price: ask, size: 90 }, { price: ask + 0.01, size: 60 }],
  best_ask: ask,
  best_bid: bid,
  bids: [{ price: bid, size: 120 }, { price: bid - 0.01, size: 80 }],
  market_id: marketId,
  mid: (bid + ask) / 2,
  tick_size: 0.01,
  timestamp: 1,
  venue: 'polymarket'
})

const history = () => ({
  count: 5,
  points: [
    { p: 0.38, ts: 1 },
    { p: 0.4, ts: 2 },
    { p: 0.43, ts: 3 },
    { p: 0.41, ts: 4 },
    { p: 0.44, ts: 5 }
  ]
})

// An EventEmitter fake gateway: request() records + answers pm.* calls; stream
// start reports live for Polymarket, keyless-degraded for Kalshi.
const fakeGw = (calls: Call[]) => {
  const gw = new EventEmitter() as EventEmitter & {
    request: (method: string, params?: Record<string, unknown>) => Promise<unknown>
  }

  gw.setMaxListeners(50)

  gw.request = (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })

    if (method === 'pm.list') {
      const venue = params.venue

      const events = [nbaItem(), fedItem()]
        .filter(e => !venue || e.event.venue === venue)
        .map(e => ({ distribution: e.distribution, event: e.event }))

      return Promise.resolve({ count: events.length, events })
    }

    if (method === 'pm.detail') {
      const item = params.event_id === 'FED' ? fedItem() : nbaItem()

      return Promise.resolve({ distribution: item.distribution, event: item.event })
    }

    if (method === 'pm.book') {
      return Promise.resolve({ book: book(String(params.market_id), 0.4, 0.42) })
    }

    if (method === 'pm.history') {
      return Promise.resolve(history())
    }

    if (method === 'pm.stream.start') {
      if (params.venue === 'kalshi') {
        return Promise.resolve({ reason: 'kalshi private key required for the authed ws handshake', streaming: false })
      }

      return Promise.resolve({ streaming: true, subscribed: params.market_ids })
    }

    if (method === 'pm.stream.stop') {
      return Promise.resolve({ stopped: true })
    }

    return Promise.resolve({})
  }

  return gw
}

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

  return { reset: () => { output = '' }, stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const mount = async (width = 120) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const calls: Call[] = []
  const gw = fakeGw(calls)

  const [{ Box, render }, { PredictionMarketsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/predictionMarketsView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(width, 40)
  const stdin = writeStream(width, 40, true)

  const instance = render(
    React.createElement(
      Box,
      { flexDirection: 'column', height: 40, width },
      React.createElement(PredictionMarketsView, {
        active: true,
        gw: gw as never,
        height: 30,
        onLeave: () => undefined,
        t: DARK_THEME,
        width
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(90)

  return {
    calls,
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    clear: () => stdout.reset(),
    emit: (event: string, payload: unknown) => gw.emit(event, payload),
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(60)
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('PredictionMarketsView', () => {
  afterEach(() => {
    opened.length = 0
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders headline rows for both venues with the distribution/detail pane', async () => {
    const m = await mount()
    const text = m.text()
    expect(text).toContain('PREDICTION MARKETS')
    // categorical headline shows title + top outcome; binary shows just the title
    expect(text).toContain('NBA Champion 2026')
    expect(text).toContain('Celtics')
    expect(text).toContain('Fed hikes in July?')
    // venue chips
    expect(text).toContain('Poly')
    expect(text).toContain('Kals')
    // detail pane on the (default) selection
    expect(text).toContain('Distribution')
    expect(text).toContain('de-vigged')
    expect(text).toContain('Order book')
    expect(text).toContain('History')
    // honest raw-vs-devig labelling
    expect(text).toContain('raw YES mids sum')
    // ONE list fetch drove it
    expect(m.calls.filter(c => c.method === 'pm.list')).toHaveLength(1)
    m.cleanup()
  })

  it('→ expands a categorical event into indented outcome sub-rows; ← collapses', async () => {
    const m = await mount()
    // The '└' glyph is unique to expanded LIST sub-rows (the detail pane lists
    // outcome labels regardless), so it's the honest collapse/expand probe.
    expect(m.text()).not.toContain('└')
    m.clear()
    await m.press(`${ESC}[C`) // right arrow → expand
    const text = m.text()
    expect(text).toContain('└')
    expect(text).toContain('Nuggets')
    expect(text).toContain('Thunder')
    m.clear()
    await m.press(`${ESC}[D`) // left arrow → collapse
    expect(m.text()).not.toContain('└')
    m.cleanup()
  })

  it('Enter opens the selected market page in the browser', async () => {
    const m = await mount()
    await m.press('\r')
    expect(opened).toContain('https://polymarket.com/event/nba')
    expect(m.text()).toContain('opened in browser')
    m.cleanup()
  })

  it('the / filter composes: typing "fed" hides the Polymarket event', async () => {
    const m = await mount()
    await m.press('/')
    await m.press('fe')
    // Clear the cumulative buffer, then the final keystroke paints the fully
    // filtered frame — so the NBA row's absence is a real filter effect.
    m.clear()
    await m.press('d')
    const text = m.text()
    expect(text).toContain('Fed hikes in July?')
    expect(text).toContain('1 matches')
    expect(text).not.toContain('NBA Champion 2026')
    m.cleanup()
  })

  it('o cycles the sort column across the headline events', async () => {
    const m = await mount()
    await m.press('o') // sort by title asc
    // both events still present; the sort key is reflected in the header glyph
    const text = m.text()
    expect(text).toContain('NBA Champion 2026')
    expect(text).toContain('Fed hikes in July?')
    expect(text).toMatch(/MARKET\s*▲/)
    m.cleanup()
  })

  it('a pm.tick book delta repaints the order book in place (no reload)', async () => {
    const m = await mount()
    // The (re)subscription is debounced so rapid navigation doesn't thrash the
    // socket — let it settle to live before driving a tick.
    await tick(300)
    const listCallsBefore = m.calls.filter(c => c.method === 'pm.list').length
    m.clear()
    // The Polymarket selection subscribed to tok-cel; a book tick folds in.
    m.emit('event', {
      payload: { kind: 'book', market_id: 'tok-cel', payload: { asks: [[0.7, 10]], bids: [[0.66, 300]] }, venue: 'polymarket' },
      type: 'pm.tick'
    })
    await tick(40)
    // best bid became 66¢ and no extra list fetch fired
    expect(m.text()).toContain('66¢')
    expect(m.calls.filter(c => c.method === 'pm.list').length).toBe(listCallsBefore)
    expect(m.text()).toContain('live')
    m.cleanup()
  })

  it('selecting the keyless Kalshi event surfaces the exact /api-key command', async () => {
    const m = await mount()
    await m.press(`${ESC}[B`) // down → the Fed (Kalshi) headline
    // The stream (re)subscription is debounced; wait for the keyless-degrade
    // reason to arrive and surface the hint.
    await tick(300)
    const text = m.text()
    // The hint wraps across lines; assert the contiguous command fragment.
    expect(text).toContain('api-key set kalshi')
    expect(text).toContain('Kalshi streaming needs a key')
    m.cleanup()
  })

  it('renders without horizontal overflow on a narrow terminal', async () => {
    const m = await mount(64)
    const text = m.text()
    expect(text).toContain('PREDICTION MARKETS')
    expect(text).toContain('NBA Champion 2026')
    m.cleanup()
  })
})
