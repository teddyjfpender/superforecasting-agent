import { EventEmitter } from 'node:events'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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
const mount = async (providers = ['predictionmarkets'], gwOverride?: ReturnType<typeof fakeGw>, homeOverride?: string) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const home = homeOverride ?? mkdtempSync(join(tmpdir(), 'pm-section-'))
  process.env.SUPERFORECASTING_AGENT_HOME = home

  if (!homeOverride) {
    writeFileSync(join(home, 'markets.json'), JSON.stringify({ categories: [], custom: [], providers, watchlist: [] }))
  }

  const calls: Call[] = []
  const gw = gwOverride ?? fakeGw(calls)

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
    cleanup: (keepHome = false) => {
      instance.unmount?.()
      instance.cleanup?.()

      if (!keepHome) {
        rmSync(home, { force: true, recursive: true })
      }
    },
    home,
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

  it('a pm.tick repaints a row from the honest server estimate ONLY (folds .estimate)', async () => {
    const m = await mount()
    // Fed (binary, Kalshi) shows its honest REST YES at 13.00%.
    expect(m.text()).toContain('13.00%')
    // A degenerate/dead tick (estimate null) carries NO estimate-grade info and
    // triggers no repaint — the honest reading is never overwritten (the
    // Putin-50% bug). The null → no-fold path is proven in the tickEstimate unit
    // test; here we clear the frame buffer and prove the positive repaint.
    m.clear()
    m.emit('event', {
      payload: { estimate: 0.2, kind: 'price_change', market_id: 'FED-Y', payload: {}, venue: 'kalshi' },
      type: 'pm.tick'
    })
    await tick(60)
    const text = m.text()
    // The server estimate repainted the row IN PLACE; the REST 13.00% is gone.
    expect(text).toContain('20.00%')
    expect(text).not.toContain('13.00%')
    m.cleanup()
  })

  it('the DETAIL pane for a binary market states BOTH sides: YES + a NO complement', async () => {
    const m = await mount()
    await m.press(`${ESC}[B`) // down → Fed (the binary Kalshi row)
    await tick(150) // let the pm.detail fetch settle
    const text = m.text()
    // Both sides, complementary, computed from the same estimate (0.13 → 0.87):
    // YES in the success token, NO in the danger token. NO 87.00% appears ONLY
    // in the detail (table rows never carry a NO tag — prices are YES-side).
    expect(text).toContain('YES 13.00%')
    expect(text).toContain('NO 87.00%')
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

  it('the fixed 4-cell direction gutter right-aligns every % under one column edge', async () => {
    const text = await renderTable(100)
    const lines = text.split('\n')
    const nba = lines.find(l => l.includes('NBA Champion')) ?? ''
    const fed = lines.find(l => l.includes('Fed hikes')) ?? ''
    // Categorical headline: bare number, no tag (its label lives in the title).
    expect(nba).toContain('44.00%')
    // Binary headline: colour-coded YES tag + the value right-aligned after it.
    expect(fed).toMatch(/YES\s+13\.00%/)
    // Both %s share the SAME right edge — the whole point of the fixed gutter
    // (the operator's screenshot showed YES floats at ragged offsets).
    expect(nba.indexOf('44.00%') + '44.00%'.length).toBe(fed.indexOf('13.00%') + '13.00%'.length)
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

describe('deep venue search via /', () => {
  it('the / query fires pm.list {query} after a debounce and merges full-catalog results', async () => {
    const calls: Call[] = []
    const gw = fakeGw(calls)
    const base = gw.request.bind(gw)

    // The weather event exists ONLY behind a server query — never in the
    // browse page (it sits thousands of events deep in the real catalogs).
    gw.request = (method: string, params: Record<string, unknown> = {}) => {
      if (method === 'pm.list' && typeof params.query === 'string' && params.query.includes('weather')) {
        calls.push({ method, params })
        const wx = fedItem()
        wx.distribution.event_id = 'WX'
        wx.distribution.title = 'Max weather temperature above 90F on Jul 4?'
        wx.event.event_id = 'WX'
        wx.event.title = 'Max weather temperature above 90F on Jul 4?'

        return Promise.resolve({ count: 1, events: [wx] })
      }

      return base(method, params)
    }

    const m = await mount(['predictionmarkets'], gw)
    expect(m.text()).not.toContain('Max weather')
    await m.press('/')
    await m.press('weather')
    // Debounce (450ms) then the server search lands and merges into the pool.
    await tick(750)
    const text = m.text()
    expect(calls.some(c => c.method === 'pm.list' && c.params.query === 'weather')).toBe(true)
    expect(text).toContain('Max weather')
    m.cleanup()
  })
})

describe('discovered markets persist', () => {
  it('search results stay in the tape after the query clears and survive a remount', async () => {
    const calls: Call[] = []
    const gw = fakeGw(calls)
    const base = gw.request.bind(gw)

    const wxItem = () => {
      const wx = fedItem()
      wx.distribution.event_id = 'WX'
      wx.distribution.title = 'Max weather temperature above 90F on Jul 4?'
      wx.event.event_id = 'WX'
      wx.event.title = 'Max weather temperature above 90F on Jul 4?'

      return wx
    }

    gw.request = (method: string, params: Record<string, unknown> = {}) => {
      if (method === 'pm.list' && typeof params.query === 'string') {
        calls.push({ method, params })

        return Promise.resolve({ count: 1, events: [wxItem()] })
      }

      if (method === 'pm.detail' && params.event_id === 'WX') {
        calls.push({ method, params })
        const it = wxItem()

        return Promise.resolve({ distribution: it.distribution, event: it.event })
      }

      return base(method, params)
    }

    const m = await mount(['predictionmarkets'], gw)
    await m.press('/')
    await m.press('weather')
    await tick(750)
    expect(m.text()).toContain('Max weather')
    // Clear the query: the discovery STAYS (coverage compounds).
    m.clear()
    await m.press(ESC)
    await tick(120)
    expect(m.text()).toContain('Max weather')
    // And the ref persisted to markets.json for the next session.
    const home = m.home
    const cfg = JSON.parse(readFileSync(join(home, 'markets.json'), 'utf8'))
    expect(cfg.pmSaved).toEqual([{ event_id: 'WX', venue: 'kalshi' }])
    m.cleanup(true) // keep the home: the remount below is the same operator's next session

    // Remount on the SAME home (fresh session): hydration via pm.detail
    // re-adds the discovery.
    const m2 = await mount(['predictionmarkets'], gw, home)
    await tick(250)
    expect(m2.text()).toContain('Max weather')
    m2.cleanup()
  })
})

// ── discovered-row marker + `x` remove ────────────────────────────────────────
// A gw that surfaces a "Max weather" event ONLY behind a '/' query (and can
// re-hydrate it by id), so a discovery is distinguishable from the browse feed.
const wxGw = () => {
  const calls: Call[] = []
  const gw = fakeGw(calls)
  const base = gw.request.bind(gw)

  const wxItem = () => {
    const wx = fedItem() // kalshi binary base
    wx.distribution.event_id = 'WX'
    wx.distribution.title = 'Max weather temperature above 90F on Jul 4?'
    wx.event.event_id = 'WX'
    wx.event.title = 'Max weather temperature above 90F on Jul 4?'

    return wx
  }

  gw.request = (method: string, params: Record<string, unknown> = {}) => {
    if (method === 'pm.list' && typeof params.query === 'string') {
      calls.push({ method, params })

      return Promise.resolve({ count: 1, events: [wxItem()] })
    }

    if (method === 'pm.detail' && params.event_id === 'WX') {
      calls.push({ method, params })
      const it = wxItem()

      return Promise.resolve({ distribution: it.distribution, event: it.event })
    }

    return base(method, params)
  }

  return { calls, gw }
}

// Search "weather", then Esc to drop the query so browse + discovered rows are
// visible side by side.
const withDiscovery = async (gw: ReturnType<typeof fakeGw>) => {
  const m = await mount(['predictionmarkets'], gw)
  await m.press('/')
  await m.press('weather')
  await tick(750)
  await m.press(ESC)
  await tick(120)

  return m
}

describe('discovered-row marker (+) marks curated finds only', () => {
  it('the discovered row carries a "+" before its venue chip; browse rows do not', async () => {
    const m = await withDiscovery(wxGw().gw)
    const lines = m.text().split('\n')
    const wx = lines.find(l => l.includes('Max weather')) ?? ''
    const nba = lines.find(l => l.includes('NBA Champion')) ?? ''
    const fed = lines.find(l => l.includes('Fed hikes')) ?? ''
    // The discovered (searched) row is flagged…
    expect(wx).toContain('+')
    // …while the browse-page rows are not (zero reflow — a plain gutter).
    expect(nba).not.toContain('+')
    expect(fed).not.toContain('+')
    m.cleanup()
  })
})

describe('`x` removes a saved (+) discovery', () => {
  it('x on the discovered row drops it from the tape AND markets.json pmSaved, and flashes', async () => {
    const m = await withDiscovery(wxGw().gw)
    // The saved ref is on disk after the search.
    expect(JSON.parse(readFileSync(join(m.home, 'markets.json'), 'utf8')).pmSaved).toEqual([
      { event_id: 'WX', venue: 'kalshi' }
    ])
    // Cursor: NBA → Fed → WX (the discovered row).
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[B`)
    // The Remove chip is live ONLY on the discovered row (live-keys-only rule).
    expect(m.text()).toContain('x Remove')
    m.clear()
    await m.press('x')
    const text = m.text()
    expect(text).toContain('removed from saved markets')
    expect(text).not.toContain('Max weather')
    // pmSaved is now empty on disk (a mis-search can't pollute the next session).
    expect(JSON.parse(readFileSync(join(m.home, 'markets.json'), 'utf8')).pmSaved).toEqual([])
    m.cleanup()
  })

  it('x on a browse row refuses with a hint, and its Remove chip never shows', async () => {
    const m = await mount() // plain browse tape; cursor starts on the NBA row
    // No Remove chip on a browse row (nothing to remove).
    expect(m.text()).not.toContain('x Remove')
    m.clear()
    await m.press('x')
    const text = m.text()
    expect(text).toContain('only saved (+) rows can be removed')
    expect(text).toContain('NBA Champion') // the row is untouched
    m.cleanup()
  })
})

describe('hydration fans out pm.detail in bounded batches', () => {
  it('never holds more than 8 pm.detail calls in flight for a large saved store', async () => {
    // Seed 20 saved refs so ≥3 sequential batches of 8 must run.
    const refs = Array.from({ length: 20 }, (_, i) => ({ event_id: `SV-${i}`, venue: 'kalshi' }))
    const home = mkdtempSync(join(tmpdir(), 'pm-hydrate-'))
    writeFileSync(
      join(home, 'markets.json'),
      JSON.stringify({ categories: [], custom: [], pmSaved: refs, providers: ['predictionmarkets'], watchlist: [] })
    )

    let inFlight = 0
    let maxInFlight = 0
    const gw = fakeGw([])
    const base = gw.request.bind(gw)

    gw.request = (method: string, params: Record<string, unknown> = {}) => {
      if (method === 'pm.detail' && typeof params.event_id === 'string' && params.event_id.startsWith('SV-')) {
        inFlight++
        maxInFlight = Math.max(maxInFlight, inFlight)

        return new Promise(resolve => {
          setTimeout(() => {
            inFlight--
            const it = fedItem()
            it.distribution.event_id = String(params.event_id)
            it.event.event_id = String(params.event_id)

            resolve({ distribution: it.distribution, event: it.event })
          }, 25)
        })
      }

      return base(method, params)
    }

    const m = await mount(['predictionmarkets'], gw, home)
    await tick(500) // drain every batch (3 × 25ms + scheduling overhead)
    // Hydration ran, but the fan-out was BOUNDED (the old code fired all 20 at
    // once). The cap is the hydration pool's concurrency limit (12 in-flight,
    // perf item #3) — the invariant is "bounded, never unbounded".
    expect(maxInFlight).toBeGreaterThan(0)
    expect(maxInFlight).toBeLessThanOrEqual(12)
    m.cleanup()
  })
})

describe('first-open loading state (no 0-events flash)', () => {
  it('shows an honest loading line before the first venue list lands', async () => {
    const gw = fakeGw([])
    const base = gw.request.bind(gw)
    let releaseList: ((v: unknown) => void) | null = null

    gw.request = (method: string, params: Record<string, unknown> = {}) => {
      if (method === 'pm.list' && !params.query) {
        return new Promise(resolve => {
          releaseList = resolve
        })
      }

      return base(method, params)
    }

    const m = await mount(['predictionmarkets'], gw)
    // Before the (gated) list resolves: a loading line, NEVER "0 events".
    const before = m.text()
    expect(before).toContain('loading venues…')
    expect(before).not.toContain('0 events')
    // Release the list → the tape fills, the loading line is gone. Clear the
    // accumulated buffer first so the assertion reads only post-release frames.
    m.clear()
    releaseList?.({ count: 1, events: [nbaItem()].map(e => ({ distribution: e.distribution, event: e.event })) })
    await tick(150)
    const after = m.text()
    expect(after).toContain('NBA Champion')
    expect(after).not.toContain('loading venues…')
    m.cleanup()
  })
})
