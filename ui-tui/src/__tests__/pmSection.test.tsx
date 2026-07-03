import { EventEmitter } from 'node:events'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

// The Prediction Markets SECTION now rides the Data-mode tape (there is no
// standalone 'pm' mode). Two layers of coverage:
//   1. INTEGRATION through the real MarketsView — the section is a Data tab,
//      driven by the parent's ONE keyboard (jump, expand, '/' trap, sort, open,
//      detail parity). The inline test harness reports no stdout, so the view
//      falls back to ~80 cols → its narrow priority-drop leaves MARKET|PROB|CLOSE.
//   2. COMPONENT contract of PredictionMarketsTable at a wide, DETERMINISTIC
//      `avail` (props, not useStdout) — the full MARKET|PROB|VOL|CLOSE|VENUE
//      header, whole venue chips, aligned outcome sub-cells, None→"—", and the
//      VENUE-then-VOL drop order — plus pure unit tests of the pack machinery.

const opened: string[] = []
vi.mock('../lib/openExternalUrl.js', () => ({
  openExternalUrl: (url: string) => {
    opened.push(url)

    return true
  }
}))

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const DASH = '—' // the "—" no-value glyph fmtProb renders
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

// A DEGENERATE book: nobody quoting, so every outcome + the headline carry a
// null prob. The tape must render "—", NEVER a fabricated 50% (the operator's
// bug). Distinct title so a `/` filter can isolate it.
const zombieItem = () => ({
  distribution: {
    binary: false,
    close_time: '2099-03-01T00:00:00Z',
    event_id: 'ZOMBIE',
    headline: { close_time: '2099-03-01T00:00:00Z', n: 2, top_label: 'Ballot A', top_prob: null, total_volume: 0 },
    normalized: false,
    notes: ['book incomplete — outcomes may be missing'],
    outcomes: [
      { label: 'Ballot A', liquid: false, market_id: 'ZB-A', prob: null, raw_prob: 0, volume: 0, yes_ask: null, yes_bid: null },
      { label: 'Ballot B', liquid: false, market_id: 'ZB-B', prob: null, raw_prob: 0, volume: 0, yes_ask: null, yes_bid: null }
    ],
    overround: 0,
    title: 'Zombie Ballot 2030',
    total_volume: 0,
    url: 'https://polymarket.com/event/zombie',
    venue: 'polymarket'
  },
  event: {
    category: 'Test',
    close_time: '2099-03-01T00:00:00Z',
    event_id: 'ZOMBIE',
    is_binary: false,
    markets: [],
    mutually_exclusive: true,
    slug: 'zombie',
    title: 'Zombie Ballot 2030',
    url: 'https://polymarket.com/event/zombie',
    venue: 'polymarket',
    volume: 0
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

const fakeGw = (calls: Call[]) => {
  const gw = new EventEmitter() as EventEmitter & {
    request: (method: string, params?: Record<string, unknown>) => Promise<unknown>
  }

  gw.setMaxListeners(50)

  gw.request = (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })

    if (method === 'pm.list') {
      const venue = params.venue

      const events = [nbaItem(), zombieItem(), fedItem()]
        .filter(e => !venue || e.event.venue === venue)
        .map(e => ({ distribution: e.distribution, event: e.event }))

      return Promise.resolve({ count: events.length, events })
    }

    if (method === 'pm.detail') {
      const item = params.event_id === 'FED' ? fedItem() : params.event_id === 'ZOMBIE' ? zombieItem() : nbaItem()

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

// Mount MarketsView in its own temp home, seeded so the predictionmarkets
// provider is the ONLY one enabled → the Prediction tab is the active Data tab
// on first paint (no `p` keypress needed for the common case).
const mount = async (providers = ['predictionmarkets']) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const home = mkdtempSync(join(tmpdir(), 'pm-section-'))
  process.env.SUPERFORECASTING_AGENT_HOME = home
  writeFileSync(join(home, 'markets.json'), JSON.stringify({ categories: [], custom: [], providers, watchlist: [] }))

  const calls: Call[] = []
  const gw = fakeGw(calls)

  const [{ render }, { MarketsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/marketsView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 40)
  const stdin = writeStream(120, 40, true)

  const instance = render(
    React.createElement(MarketsView, { gw: gw as never, onAsk: () => undefined, onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(120)

  return {
    calls,
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
      rmSync(home, { force: true, recursive: true })
    },
    clear: () => stdout.reset(),
    emit: (event: string, payload: unknown) => gw.emit(event, payload),
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(70)
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

afterEach(() => {
  opened.length = 0
  delete process.env.FORECAST_TUI_INLINE
  delete process.env.SUPERFORECASTING_AGENT_HOME
})

describe('Prediction section inside the Data tape', () => {
  it('renders the Prediction tab + PM header in the Data tape (no [Prediction] mode chip)', async () => {
    const m = await mount()
    const text = m.text()
    // Native: the two-mode header strip survives; there is NO Prediction mode.
    expect(text).toContain('[Data]')
    expect(text).not.toContain('[Prediction]')
    // The tape gained a Prediction category tab and its aligned PM header row.
    expect(text).toContain('Prediction')
    expect(text).toContain('MARKET')
    expect(text).toContain('PROB')
    expect(text).toContain('CLOSE')
    // Headline rows from both venues (titles truncate at the harness width).
    expect(text).toContain('NBA Champion')
    expect(text).toContain('Fed hikes')
    // ONE list fetch drove it.
    expect(m.calls.filter(c => c.method === 'pm.list')).toHaveLength(1)
    m.cleanup()
  })

  it('detail parity: distribution bars + de-vig note + order book + history', async () => {
    const m = await mount()
    const text = m.text()
    expect(text).toContain('Distribution')
    expect(text).toContain('de-vigged')
    expect(text).toContain('Order book')
    expect(text).toContain('History')
    // honest raw-vs-devig labelling as one muted line
    expect(text).toContain('raw YES mids sum')
    m.cleanup()
  })

  it('→ expands a categorical event; sub-rows sit under an OUTCOME / BID·ASK header line', async () => {
    const m = await mount()
    // The '└' glyph + the BID·ASK header are unique to the EXPANDED outcome list.
    expect(m.text()).not.toContain('└')
    m.clear()
    await m.press(`${ESC}[C`) // right arrow → expand the (first) NBA row
    const text = m.text()
    expect(text).toContain('└')
    // Every sub-value sits under a header that NAMES it — the operator caught
    // bid/ask under VOL and volume under CLOSE; the outcome header line fixes it.
    expect(text).toContain('OUTCOME')
    expect(text).toContain('BID·ASK')
    expect(text).toContain('Nuggets')
    expect(text).toContain('Thunder')
    m.clear()
    await m.press(`${ESC}[D`) // left arrow → collapse
    expect(m.text()).not.toContain('└')
    m.cleanup()
  })

  it('dead events (no estimate, $0 volume) are HIDDEN by default', async () => {
    const m = await mount()
    // The zombie event has no estimate and zero volume: the default hideDead
    // filter drops it from the tape entirely (the operator: "don't spam the
    // TUI with useless rows") — searching for it finds nothing.
    expect(m.text()).not.toContain('Zombie Ballo')
    await m.press('/')
    await m.press('zombi')
    m.clear()
    await m.press('e')
    expect(m.text()).toContain('0 matches')
    m.cleanup()
  })

  it('o cycles the PM sort column and shows the ▲ indicator on the active header', async () => {
    const m = await mount()
    await m.press('o') // → sort by title (first PM_SORT_KEY) ascending
    const text = m.text()
    expect(text).toContain('NBA Champion')
    expect(text).toContain('Fed hikes')
    expect(text).toMatch(/MARKET\s*▲/)
    m.cleanup()
  })

  it('Enter opens the selected market page in the browser', async () => {
    const m = await mount()
    await m.press('\r')
    expect(opened).toContain('https://polymarket.com/event/nba')
    m.cleanup()
  })

  it("the '/' focus trap holds across PM rows: a shortcut letter lands in the query, no action fires", async () => {
    const m = await mount()
    await m.press('/')
    // 'v' is the venue-cycle shortcut OUTSIDE the filter. Inside it, it must be
    // a literal query char — no venue switch, no expand, nothing but text.
    await m.press('v')
    const text = m.text()
    // The keystroke is echoed into the filter bar (the query shows 'v')…
    expect(text).toMatch(/⌕\s*v/)
    // …and NO action fired: venue stays 'All' (v did NOT cycle) and nothing expanded.
    expect(text).toContain('Venue: All')
    expect(text).not.toContain('└')
    m.cleanup()
  })

  it('selecting the keyless Kalshi event surfaces the exact /api-key command in the detail pane', async () => {
    const m = await mount()
    // Down twice: NBA → Zombie → Fed (the Kalshi binary). Let the debounced
    // stream (re)subscription settle so the keyless-degrade reason arrives.
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[B`)
    await tick(320)
    const text = m.text()
    expect(text).toContain('api-key set kalshi')
    expect(text).toContain('Kalshi streaming needs a key')
    m.cleanup()
  })

  it('p from a fresh (provider-off) config enables predictionmarkets and jumps to the section', async () => {
    const m = await mount(['yahoo'])
    // Yahoo-only: the Prediction tab + its PROB column do NOT exist yet.
    expect(m.text()).not.toContain('Prediction')
    expect(m.text()).not.toContain('PROB')
    m.clear()
    await m.press('p') // enable the provider + land on the Prediction section
    await tick(120)
    const text = m.text()
    expect(text).toContain('Prediction')
    expect(text).toContain('PROB')
    expect(text).toContain('NBA Champion')
    m.cleanup()
  })
})

// ── the presentational column contract (deterministic, wide `avail`) ──────────
describe('PredictionMarketsTable column contract', () => {
  const renderTable = async (avail: number, expanded: string[] = []) => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ Box, render }, { PredictionMarketsTable }, { flattenPMRows }, { semantics }, { DARK_THEME }, { stripAnsi }] =
      await Promise.all([
        import('@hermes/ink'),
        import('../components/predictionMarketsTable.js'),
        import('../lib/pmRows.js'),
        import('../lib/visualSemantics.js'),
        import('../theme.js'),
        import('../lib/text.js')
      ])

    const items = [nbaItem(), zombieItem(), fedItem()] as never[]
    const windowed = flattenPMRows(items, new Set(expanded))
    const tableWidth = avail + 2
    const stdout = writeStream(tableWidth + 4, 40)
    const stdin = writeStream(tableWidth + 4, 40, true)

    const instance = render(
      React.createElement(
        Box as never,
        { flexDirection: 'column', height: 40, width: tableWidth + 4 } as never,
        React.createElement(PredictionMarketsTable as never, {
          active: false,
          avail,
          clampedSel: 0,
          emptyText: '',
          expanded: new Set(expanded),
          height: 30,
          listStart: 0,
          livePrices: {},
          onSelect: () => undefined,
          onSortByKey: () => undefined,
          rowsLength: windowed.length,
          sem: semantics(DARK_THEME),
          sortState: { dir: 'asc', key: null },
          t: DARK_THEME,
          tableWidth,
          windowed
        } as never)
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(50)
    const text = normalize(stdout.text(), stripAnsi)
    instance.unmount?.()
    instance.cleanup?.()

    return text
  }

  afterEach(() => delete process.env.FORECAST_TUI_INLINE)

  it('renders the full MARKET | PROB | VOL | CLOSE | VENUE header with WHOLE venue chips', async () => {
    const text = await renderTable(100)

    for (const h of ['MARKET', 'PROB', 'VOL', 'CLOSE', 'VENUE']) {
      expect(text).toContain(h)
    }

    // venue chips are never truncated mid-word
    expect(text).toContain('poly')
    expect(text).toContain('kalshi')
    // full titles fit at this width
    expect(text).toContain('NBA Champion 2026')
    expect(text).toContain('Fed hikes in July?')
  })

  it('expanded outcome sub-rows put bid/ask under BID·ASK and volume under VOL', async () => {
    const text = await renderTable(100, ['polymarket:evt-nba'])
    expect(text).toContain('OUTCOME')
    expect(text).toContain('BID·ASK')
    // Nuggets: yes_bid 0.32 / yes_ask 0.34 → "32/34" (integer cents), under BID·ASK.
    expect(text).toContain('32/34')
    // and its $1K volume under VOL (a value the OLD tape mis-filed under CLOSE).
    expect(text).toContain('$1K')
  })

  it('a null (degenerate) headline prob renders "—", never 50%', async () => {
    const text = await renderTable(100)
    expect(text).toContain('Zombie Ballot 2030')
    expect(text).toContain(DASH)
    expect(text).not.toContain('50%')
  })

  it('narrow priority-drop sheds VENUE first, then VOL', async () => {
    // Mid width: VENUE gone, VOL survives (PROB is now 11 wide for the YES reading,
    // so the thresholds sit a little higher than the old 6-wide PROB).
    const mid = await renderTable(48)
    expect(mid).toContain('VOL')
    expect(mid).not.toContain('VENUE')
    // Tighter: VOL gone too, PROB + CLOSE remain (the sacred columns).
    const tight = await renderTable(30)
    expect(tight).toContain('PROB')
    expect(tight).not.toContain('VOL')
    expect(tight).not.toContain('VENUE')
  })
})

// ── the pure pack machinery (no render) ───────────────────────────────────────
describe('packPmHead / packPmOutcome', () => {
  it('keeps all five columns wide, and drops VENUE then VOL as width shrinks', async () => {
    const { packPmHead } = await import('../lib/pmRows.js')
    expect(packPmHead(100).cols.map(c => c.key)).toEqual(['prob', 'vol', 'close', 'venue'])
    expect(packPmHead(48).cols.map(c => c.key)).toEqual(['prob', 'vol', 'close']) // VENUE first out
    expect(packPmHead(30).cols.map(c => c.key)).toEqual(['prob', 'close']) // then VOL
    // MARKET never starves below its minimum.
    expect(packPmHead(100).marketW).toBeGreaterThanOrEqual(12)
    expect(packPmHead(24).marketW).toBeGreaterThanOrEqual(12)
  })

  it('enforces a 2-space gutter — packed width never exceeds avail when columns fit', async () => {
    const { packPmHead } = await import('../lib/pmRows.js')
    const { cols, marketW } = packPmHead(100)
    const packed = 2 /* marker */ + marketW + cols.reduce((a, c) => a + 2 /* gutter */ + c.w, 0)
    expect(packed).toBeLessThanOrEqual(100)
  })

  it('outcome schema always keeps PROB | BID·ASK | VOL and floors the label width', async () => {
    const { packPmOutcome } = await import('../lib/pmRows.js')
    expect(packPmOutcome(100).cols.map(c => c.key)).toEqual(['prob', 'ba', 'vol'])
    expect(packPmOutcome(20).labelW).toBeGreaterThanOrEqual(6)
  })
})
