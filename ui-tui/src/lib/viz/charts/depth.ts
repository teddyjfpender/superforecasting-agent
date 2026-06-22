// Order-book depth — cumulative bid (gain) and ask (loss) size as mirrored
// step-area curves meeting at the spread, with a mid-price marker. The classic
// CLOB depth view for market-microstructure reads.

import { CellBuffer } from '../buffer.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

import { gutterText, yGutter } from './_layout.js'

export interface DepthLevel {
  price: number
  size: number
}

export interface DepthData {
  asks: DepthLevel[]
  bids: DepthLevel[]
  mid?: number
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

const clean = (levels: DepthLevel[] | undefined): DepthLevel[] =>
  (levels ?? []).filter(l => l && finite(l.price) && finite(l.size) && l.size >= 0)

// Cumulative array (running sum) over an ordered level list.
const cumulate = (levels: DepthLevel[]): number[] => {
  let s = 0

  return levels.map(l => (s += l.size))
}

export const renderDepth = (data: DepthData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const height = Math.max(4, ctx.height ?? 9)

  // Bids: best (highest price) first; cumulative grows toward lower prices.
  const bids = clean(data.bids).sort((a, b) => b.price - a.price)
  // Asks: best (lowest price) first; cumulative grows toward higher prices.
  const asks = clean(data.asks).sort((a, b) => a.price - b.price)

  if (!bids.length && !asks.length) {
    return { rows: [] }
  }

  const cumB = cumulate(bids)
  const cumA = cumulate(asks)
  const prices = [...bids, ...asks].map(l => l.price)
  const xLo = Math.min(...prices)
  const xHi = Math.max(...prices)
  const xSpan = xHi - xLo || 1
  const yHi = Math.max(cumB[cumB.length - 1] ?? 0, cumA[cumA.length - 1] ?? 0, 1)

  const mid =
    finite(data.mid) ? data.mid : bids.length && asks.length ? (bids[0]!.price + asks[0]!.price) / 2 : (bids[0]?.price ?? asks[0]?.price ?? 0)

  const g = yGutter(0, yHi, width)
  const colToPrice = (c: number): number => xLo + (g.plotW <= 1 ? 0 : (c / (g.plotW - 1)) * xSpan)
  const rowOf = (cum: number): number => Math.max(0, Math.min(height - 1, Math.round((1 - cum / yHi) * (height - 1))))

  // Step lookup: cumulative bid size at price p = Σ sizes with price ≥ p.
  const bidCumAt = (p: number): number => {
    let cum = 0

    for (let i = 0; i < bids.length; i++) {
      if (bids[i]!.price >= p) {
        cum = cumB[i]!
      } else {
        break
      }
    }

    return cum
  }

  // Cumulative ask size at price p = Σ sizes with price ≤ p.
  const askCumAt = (p: number): number => {
    let cum = 0

    for (let i = 0; i < asks.length; i++) {
      if (asks[i]!.price <= p) {
        cum = cumA[i]!
      } else {
        break
      }
    }

    return cum
  }

  const midCol = Math.max(0, Math.min(g.plotW - 1, Math.round(((mid - xLo) / xSpan) * (g.plotW - 1))))
  const buf = new CellBuffer(g.plotW, height)

  for (let c = 0; c < g.plotW; c++) {
    const price = colToPrice(c)
    const isBid = price <= mid
    const cum = isBid ? bidCumAt(price) : askCumAt(price)

    if (cum > 0) {
      const top = rowOf(cum)
      const color = isBid ? theme.gain : theme.loss

      for (let r = top; r < height; r++) {
        buf.set(c, r, '█', { color })
      }
    }
  }

  // Mid marker: a thin vertical line over the spread (drawn last so it shows).
  for (let r = 0; r < height; r++) {
    buf.set(midCol, r, '┊', { color: theme.muted })
  }

  const rows: StyledRow[] = buf.compile().map((runs, r) => [{ color: theme.muted, text: gutterText(r, height, g) }, ...runs])
  const fmt = (v: number): string => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))

  const legend: StyledRow[] = [
    [
      { color: theme.gain, text: '█ bids' },
      { color: theme.muted, text: `   mid ${fmt(mid)}   ` },
      { color: theme.loss, text: 'asks █' }
    ]
  ]

  return { legend, rows }
}
