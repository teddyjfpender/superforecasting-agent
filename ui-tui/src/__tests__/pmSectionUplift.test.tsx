// MUST be first: forces truecolor so the render emits theme-token SGR under the
// non-TTY test stream (chalk reads FORCE_COLOR at import time).
import { PRIOR_FORCE_COLOR } from './pmForceColor.js'

import { PassThrough } from 'stream'

import React, { useState } from 'react'
import { afterAll, describe, expect, it, vi } from 'vitest'

import { Box, Text } from '@hermes/ink'

import instances from '../../packages/hermes-ink/src/ink/instances.js'
import { dispatchClick } from '../../packages/hermes-ink/src/ink/hit-test.js'
import { nodeCache } from '../../packages/hermes-ink/src/ink/node-cache.js'
import { renderSync } from '../../packages/hermes-ink/src/ink/root.js'
import { PredictionMarketsTable } from '../components/predictionMarketsTable.js'
import { semantics } from '../lib/visualSemantics.js'
import {
  EMPTY_PM_FILTER,
  filterPMSection,
  flattenPMRows,
  isSportsItem,
  parseMoneyShorthand,
  parseProbPercent,
  type PMDisplayRow,
  pmFilterActive,
  pmFilterSummary,
  pmSortValue,
  pmWindow
} from '../lib/pmRows.js'
import { nextByKeyState, sortRows, type TableSortState } from '../lib/tableSort.js'
import { DARK_THEME } from '../theme.js'

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

// Restore the env so FORCE_COLOR doesn't leak coloured frames into sibling suites.
afterAll(() => {
  if (PRIOR_FORCE_COLOR === undefined) {
    delete process.env.FORCE_COLOR
  } else {
    process.env.FORCE_COLOR = PRIOR_FORCE_COLOR
  }
})

// ── fixtures (mirror the wire shapes) ────────────────────────────────────────
const out = (label: string, prob: number | null, id: string, vol = 1000) => ({
  label,
  liquid: true,
  market_id: id,
  prob,
  raw_prob: (prob ?? 0) - 0.02,
  volume: vol,
  yes_ask: prob === null ? null : prob + 0.01,
  yes_bid: prob === null ? null : prob - 0.01
})

const evt = (over: Record<string, unknown> = {}): any => ({
  distribution: {
    binary: false,
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt',
    headline: { close_time: '2099-01-01T00:00:00Z', n: 3, top_label: 'Alpha', top_prob: 0.44, total_volume: 1_500_000 },
    normalized: true,
    notes: [],
    outcomes: [out('Alpha', 0.44, 'm-a'), out('Bravo', 0.33, 'm-b'), out('Charlie', 0.23, 'm-c')],
    overround: 0.03,
    title: 'NBA Champion 2026',
    total_volume: 1_500_000,
    url: 'https://polymarket.com/event/nba',
    venue: 'polymarket',
    ...(over.distribution as object)
  },
  event: {
    category: 'Sports',
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt',
    is_binary: false,
    markets: [],
    mutually_exclusive: true,
    slug: 'nba',
    title: 'NBA Champion 2026',
    url: 'https://polymarket.com/event/nba',
    venue: 'polymarket',
    volume: 1_500_000,
    ...(over.event as object)
  }
})

const binaryEvt = (): any =>
  evt({
    distribution: {
      binary: true,
      event_id: 'FED',
      headline: { close_time: '2099-02-01T00:00:00Z', n: 1, top_label: 'Yes', top_prob: 0.13, total_volume: 50_000 },
      outcomes: [out('Yes', 0.13, 'FED-Y', 50_000)],
      title: 'Fed hikes in July?',
      total_volume: 50_000,
      venue: 'kalshi'
    },
    event: { category: 'Economics', event_id: 'FED', is_binary: true, title: 'Fed hikes in July?', venue: 'kalshi', volume: 50_000 }
  })

// ── #1 windowing: the cursor is visible on EVERY frame ───────────────────────
describe('pmWindow keeps the selected row on screen (variable-height sub-rows)', () => {
  // Cumulative visual lines from the window start up to and including row i.
  const linesTo = (rows: PMDisplayRow[], start: number, i: number): number => {
    let lines = 0
    for (let k = start; k <= i; k++) {
      const groupStart =
        rows[k]!.kind === 'outcome' &&
        (k === 0 || rows[k - 1]!.kind !== 'outcome' || (rows[k - 1] as any).parentId !== (rows[k] as any).parentId)
      lines += rows[k]!.kind === 'outcome' && (k === start || groupStart) ? 2 : 1
    }
    return lines
  }

  it('every selectable index renders the selected row FULLY inside the viewport', () => {
    // Two expanded categorical events + a binary → interleaved 1- and 2-line rows.
    const items = [evt({ event: { event_id: 'a' }, distribution: { event_id: 'a' } }), binaryEvt(), evt({ event: { event_id: 'c' }, distribution: { event_id: 'c' } })]
    const rows = flattenPMRows(items as any, new Set(['polymarket:a', 'polymarket:c']))
    const viewport = 5

    for (let sel = 0; sel < rows.length; sel++) {
      const { start, end } = pmWindow(rows, sel, viewport)
      // The selection is inside the returned slice…
      expect(sel).toBeGreaterThanOrEqual(start)
      expect(sel).toBeLessThan(end)
      // …and its LAST rendered line fits within the viewport (cursor visible).
      expect(linesTo(rows, start, sel)).toBeLessThanOrEqual(viewport)
      // The whole window never overflows the viewport in visual lines.
      expect(linesTo(rows, start, end - 1)).toBeLessThanOrEqual(viewport)
    }
  })

  it('an empty list is a no-op window', () => {
    expect(pmWindow([], 0, 5)).toEqual({ end: 0, start: 0 })
  })
})

// ── #2 structured filter (pure) ──────────────────────────────────────────────
describe('filterPMSection + parsers', () => {
  it('parseMoneyShorthand: 1m → 1_000_000, 500k, decimals, plain, junk → null', () => {
    expect(parseMoneyShorthand('1m')).toBe(1_000_000)
    expect(parseMoneyShorthand('500k')).toBe(500_000)
    expect(parseMoneyShorthand('2.3m')).toBe(2_300_000)
    expect(parseMoneyShorthand('$1,000')).toBe(1000)
    expect(parseMoneyShorthand('250000')).toBe(250_000)
    expect(parseMoneyShorthand('')).toBeNull()
    expect(parseMoneyShorthand('abc')).toBeNull()
  })

  it('parseProbPercent: percents and fractions, empty/junk → null', () => {
    expect(parseProbPercent('5')).toBe(0.05)
    expect(parseProbPercent('95%')).toBe(0.95)
    expect(parseProbPercent('0.85')).toBe(0.85)
    expect(parseProbPercent('')).toBeNull()
    expect(parseProbPercent('x')).toBeNull()
  })

  it('venue match, min volume, INCLUSIVE prob bounds, topic, and the sports heuristic', () => {
    const items = [evt(), binaryEvt()] as any // NBA (sports, poly, .44, $1.5M) + Fed (econ, kalshi, .13, $50k)

    // venue
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, venue: 'kalshi' }).map(i => i.event.event_id)).toEqual(['FED'])
    // min volume ($1M keeps NBA, drops the $50k Fed)
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, minVolume: 1_000_000 }).map(i => i.event.event_id)).toEqual(['evt'])
    // prob bounds are INCLUSIVE (.13 passes minProb .13; .44 passes maxProb .44)
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, minProb: 0.13 }).map(i => i.event.event_id)).toEqual(['evt', 'FED'])
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, minProb: 0.2 }).map(i => i.event.event_id)).toEqual(['evt'])
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, maxProb: 0.44 }).map(i => i.event.event_id)).toEqual(['evt', 'FED'])
    // topic matches title/category
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, topic: 'fed' }).map(i => i.event.event_id)).toEqual(['FED'])
    // sports heuristic
    expect(isSportsItem(evt() as any)).toBe(true)
    expect(isSportsItem(binaryEvt() as any)).toBe(false)
    expect(filterPMSection(items, { ...EMPTY_PM_FILTER, hideSports: true }).map(i => i.event.event_id)).toEqual(['FED'])
  })

  it('a null-prob item is excluded once any prob bound is set (never fabricated)', () => {
    const zombie = evt({ distribution: { event_id: 'z', headline: { top_prob: null, total_volume: 0 }, title: 'Zombie' }, event: { event_id: 'z' } }) as any
    expect(filterPMSection([zombie], { ...EMPTY_PM_FILTER, minProb: 0.01 })).toHaveLength(0)
  })

  it('pmFilterActive + pmFilterSummary reflect the active fields', () => {
    expect(pmFilterActive(EMPTY_PM_FILTER)).toBe(false)
    const f = { ...EMPTY_PM_FILTER, venue: 'kalshi' as const, minVolume: 1_000_000, minProb: 0.05, maxProb: 0.95, hideSports: true }
    expect(pmFilterActive(f)).toBe(true)
    const s = pmFilterSummary(f)
    expect(s).toContain('venue Kalshi')
    expect(s).toContain('vol ≥ $1.0M')
    expect(s).toContain('p 5-95%')
    expect(s).toContain('no sports')
  })
})

// ── presentational: direction labels + full-row highlight (raw ANSI) ─────────
const hexTrue = (hex: string, layer: 38 | 48): string => {
  const n = parseInt(hex.replace('#', ''), 16)
  return `${layer};2;${(n >> 16) & 255};${(n >> 8) & 255};${n & 255}`
}

const renderRaw = async (windowed: PMDisplayRow[], clampedSel: number, sortState: TableSortState = { dir: 'asc', key: null }) => {
  const stdout = new PassThrough() as any
  let raw = ''
  Object.assign(stdout, { columns: 120, isTTY: false, rows: 40 })
  stdout.on('data', (c: Buffer) => { raw += c.toString() })

  const instance = renderSync(
    React.createElement(
      Box as never,
      { flexDirection: 'column', height: 40, width: 84 } as never,
      React.createElement(PredictionMarketsTable as never, {
        active: false,
        avail: 80,
        clampedSel,
        emptyText: '',
        expanded: new Set(windowed.filter(r => r.kind === 'outcome').map(r => (r as any).parentId)),
        height: 30,
        listStart: 0,
        livePrices: {},
        onSelect: () => undefined,
        onSortByKey: () => undefined,
        rowsLength: windowed.length,
        sem: semantics(DARK_THEME),
        sortState,
        t: DARK_THEME,
        tableWidth: 82,
        windowed
      } as never)
    ),
    { exitOnCtrlC: false, patchConsole: false, stdout: stdout as never }
  )
  await tick(50)
  instance.unmount?.()
  instance.cleanup?.()
  return raw
}

describe('#4 direction labels + #5 precision + #6 full-row highlight', () => {
  it('a binary headline shows a colour-coded "YES" + a 2dp probability', async () => {
    const rows = flattenPMRows([binaryEvt()] as any, new Set())
    const raw = await renderRaw(rows, 0)
    const plain = raw.replace(/\x1b\[[0-9;]*m/g, '')
    expect(plain).toContain('YES 13.00%') // 2dp, contextualised
    // The YES token paints in the success (ok) foreground token.
    expect(raw).toContain(hexTrue(DARK_THEME.color.ok, 38))
  })

  it('the SELECTED headline row highlights across its full width (desk-view bg)', async () => {
    const rows = flattenPMRows([evt()] as any, new Set())
    const selected = await renderRaw(rows, 0)
    expect(selected).toContain(hexTrue(DARK_THEME.color.selectionBg, 48))
  })

  it('a SELECTED outcome sub-row also gets the full-row highlight (cursor never vanishes)', async () => {
    const rows = flattenPMRows([evt()] as any, new Set(['polymarket:evt']))
    // row 0 = headline, row 1 = first outcome sub-row.
    const onSubRow = await renderRaw(rows, 1)
    expect(onSubRow).toContain(hexTrue(DARK_THEME.color.selectionBg, 48))
  })
})

// ── #3 click-sort: a REAL simulated click through the ink hit-test ────────────
// The inline harness cannot deliver an end-to-end SGR mouse click (mouse dispatch
// is gated on altScreenActive, and <AlternateScreen> keys off the REAL
// process.stdout, not the injected test stream — so it never arms). Instead we
// render through the ink SOURCE pipeline (shared nodeCache + instances) and drive
// the SAME hit-test → bubble → onClick path a real click uses. This proves the
// wiring for real — and proves the root cause: <Text onClick> is silently dropped.
const clickable = (node: any, out: { node: any; rect: any }[] = []): { node: any; rect: any }[] => {
  const rect = nodeCache.get(node)
  if (node._eventHandlers?.onClick && rect) out.push({ node, rect })
  for (const c of node.childNodes ?? []) if (c.nodeName !== '#text') clickable(c, out)
  return out
}

describe('#3 header click-sort fires through the real hit-test', () => {
  it('ROOT CAUSE: <Text onClick> is dropped by the ink fork; <Box onClick> fires', async () => {
    const boxSpy = vi.fn()
    const textSpy = vi.fn()
    const stdout = new PassThrough() as any
    Object.assign(stdout, { columns: 40, isTTY: false, rows: 10 })
    stdout.on('data', () => undefined)

    renderSync(
      React.createElement(
        Box as never,
        { flexDirection: 'column', height: 10, width: 40 } as never,
        React.createElement(Box as never, { onClick: boxSpy } as never, React.createElement(Text as never, {}, 'BOX')),
        React.createElement(Text as never, { onClick: textSpy }, 'TXT')
      ),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout as never }
    )
    await tick(50)
    const ink: any = instances.get(stdout)
    const zones = clickable(ink.rootNode)
    expect(zones.length).toBe(1) // ONLY the Box registered a click zone
    dispatchClick(ink.rootNode, zones[0]!.rect.x, zones[0]!.rect.y)
    expect(boxSpy).toHaveBeenCalled()
    expect(textSpy).not.toHaveBeenCalled()
    ink.unmount?.()
  })

  it('clicking the PROB header dispatches onSortByKey("prob"), flips the ▲ and reorders', async () => {
    const items = [evt(), binaryEvt()] as any // NBA (.44) + Fed (.13)
    const stdout = new PassThrough() as any
    let raw = ''
    Object.assign(stdout, { columns: 120, isTTY: false, rows: 40 })
    stdout.on('data', (c: Buffer) => { raw += c.toString() })
    const fired: string[] = []

    // A stateful harness so the click's onSortByKey actually re-sorts + re-renders
    // — the full click → indicator-flip → row-reorder chain, in one render tree.
    function Harness() {
      const [sortState, setSortState] = useState<TableSortState>({ dir: 'asc', key: null })
      const sorted = sortRows(items, sortState.key, sortState.dir, pmSortValue)
      const rows = flattenPMRows(sorted, new Set())
      return React.createElement(
        Box as never,
        { flexDirection: 'column', height: 40, width: 84 } as never,
        React.createElement(PredictionMarketsTable as never, {
          active: true,
          avail: 80,
          clampedSel: 0,
          emptyText: '',
          expanded: new Set(),
          height: 30,
          listStart: 0,
          livePrices: {},
          onSelect: () => undefined,
          onSortByKey: (k: string) => { fired.push(k); setSortState(s => nextByKeyState(s, k)) },
          rowsLength: rows.length,
          sem: semantics(DARK_THEME),
          sortState,
          t: DARK_THEME,
          tableWidth: 82,
          windowed: rows
        } as never)
      )
    }

    renderSync(React.createElement(Harness), { exitOnCtrlC: false, patchConsole: false, stdout: stdout as never })
    await tick(60)
    const ink: any = instances.get(stdout)

    // Header cells are the clickable zones on row y=0, left→right: MARKET, PROB,
    // VOL, CLOSE. Click the 2nd (PROB).
    const headerZones = clickable(ink.rootNode).filter(z => z.rect.y === 0).sort((a, b) => a.rect.x - b.rect.x)
    expect(headerZones.length).toBeGreaterThanOrEqual(2)
    const probZone = headerZones[1]!
    raw = '' // capture only post-click frames
    dispatchClick(ink.rootNode, probZone.rect.x + 1, 0)
    await tick(60)

    // The real handler fired with the PROB key…
    expect(fired).toContain('prob')
    const plain = raw.replace(/\x1b\[[0-9;]*m/g, '').replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '')
    // …the header now carries the ascending indicator…
    expect(plain).toMatch(/PROB\s*▲/)
    // …and the rows reordered: Fed (.13) now sorts above NBA (.44).
    expect(plain.indexOf('Fed hikes')).toBeGreaterThanOrEqual(0)
    expect(plain.indexOf('Fed hikes')).toBeLessThan(plain.indexOf('NBA Champion'))
    ink.unmount?.()
  })
})
