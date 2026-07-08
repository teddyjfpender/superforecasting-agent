import { describe, expect, it } from 'vitest'

import {
  axisLabels,
  bandChart,
  boxWhisker,
  clamp01,
  compactNumber,
  deltaGlyph,
  dotTrack,
  downsampleSeries,
  histogram,
  levelSparkline,
  pct,
  pctDelta,
  shortDate,
  timeAxis,
  windowDelta,
  windowDeltaDetail,
  wrapLines
} from '../lib/forecastCharts.js'

// The finite drawn values of a set of band points (marker + band edges when both
// present), i.e. every artifact bandChart actually paints.
const drawnValues = (points: ReadonlyArray<{ y: number | null; lo?: number | null; hi?: number | null }>): number[] => {
  const out: number[] = []
  for (const p of points) {
    if (typeof p.y === 'number' && Number.isFinite(p.y)) {
      out.push(p.y)
      if (typeof p.lo === 'number' && Number.isFinite(p.lo) && typeof p.hi === 'number' && Number.isFinite(p.hi)) {
        out.push(p.lo, p.hi)
      }
    }
  }
  return out
}

// Every (row, col) a glyph occupies in the plot region of a rendered chart.
const glyphCells = (chart: { rows: string[]; gutterW: number }, glyph: string): Array<{ row: number; col: number }> => {
  const cells: Array<{ row: number; col: number }> = []
  chart.rows.forEach((row, r) => {
    const plot = row.slice(chart.gutterW)
    ;[...plot].forEach((ch, c) => {
      if (ch === glyph) {
        cells.push({ row: r, col: c })
      }
    })
  })
  return cells
}

describe('format helpers', () => {
  it('pct formats probabilities as whole percents', () => {
    expect(pct(0.523)).toBe('52%')
    expect(pct(0.523, 1)).toBe('52.3%')
    expect(pct(1)).toBe('100%')
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
    expect(pct(Number.NaN)).toBe('—')
  })

  it('deltaGlyph reflects direction with a flat dead-zone', () => {
    expect(deltaGlyph(0.03)).toBe('▲')
    expect(deltaGlyph(-0.03)).toBe('▼')
    expect(deltaGlyph(0.001)).toBe('·')
    expect(deltaGlyph(null)).toBe('·')
  })

  it('pctDelta renders signed points with a glyph', () => {
    expect(pctDelta(0.031)).toBe('▲ +3.10pt')
    expect(pctDelta(-0.012)).toBe('▼ -1.20pt')
    expect(pctDelta(0)).toBe('· flat')
    expect(pctDelta(null)).toBe('· flat')
  })

  it('shortDate slices ISO timestamps', () => {
    expect(shortDate('2026-05-29T14:00:00Z')).toBe('2026-05-29')
    expect(shortDate(null)).toBe('—')
  })

  it('clamp01 clamps to the unit interval', () => {
    expect(clamp01(-1)).toBe(0)
    expect(clamp01(2)).toBe(1)
    expect(clamp01(0.4)).toBe(0.4)
  })
})

describe('windowDelta', () => {
  const NOW = Date.parse('2026-06-01T00:00:00Z')
  const day = (n: number) => new Date(NOW - n * 86_400_000).toISOString()

  it('returns current minus the last point at or before the cutoff (1W)', () => {
    const history = [
      { as_of: day(30), headline_probability: 0.4 },
      { as_of: day(10), headline_probability: 0.5 }, // ≤ now−7d → the 1W anchor
      { as_of: day(2), headline_probability: 0.58 } // current
    ]
    // 0.58 − 0.5 = +0.08
    expect(windowDelta(history, NOW, 7)).toBeCloseTo(0.08, 6)
  })

  it('returns null when no point falls inside the window', () => {
    const history = [
      { as_of: day(3), headline_probability: 0.5 },
      { as_of: day(1), headline_probability: 0.55 }
    ]
    // No point is ≤ now−7d, so the 1W window has no anchor.
    expect(windowDelta(history, NOW, 7)).toBeNull()
  })

  it('returns null for a one-point (or empty) series', () => {
    expect(windowDelta([{ as_of: day(1), headline_probability: 0.5 }], NOW, 1)).toBeNull()
    expect(windowDelta([], NOW, 1)).toBeNull()
    expect(windowDelta(null, NOW, 1)).toBeNull()
  })

  it('uses as_of (economic date), not array order, to place the anchor', () => {
    // A back-dated re-forecast: created last but speaks to an OLD as_of. The 1D
    // window must anchor on the true 1-day-ago value (0.5), not the latest row.
    const history = [
      { as_of: day(5), headline_probability: 0.5 },
      { as_of: day(0.5), headline_probability: 0.6 } // inside today, NOT ≤ now−1d
    ]
    // current 0.6; the only point ≤ now−1d is the day-5 one → +0.1
    expect(windowDelta(history, NOW, 1)).toBeCloseTo(0.1, 6)
  })

  it('skips non-finite anchors and falls back to the next valid in-window point', () => {
    const history = [
      { as_of: day(20), headline_probability: 0.42 },
      { as_of: day(10), headline_probability: null }, // in-window but non-finite → skip
      { as_of: day(1), headline_probability: 0.55 }
    ]
    // 0.55 − 0.42 = +0.13 (the null day-10 point is skipped)
    expect(windowDelta(history, NOW, 7)).toBeCloseTo(0.13, 6)
  })

  it('works for distribution-unit headlines (Δμ in outcome units, not a percent)', () => {
    const history = [
      { as_of: day(40), headline_probability: 4.1 },
      { as_of: day(10), headline_probability: 4.3 },
      { as_of: day(1), headline_probability: 4.232 }
    ]
    // 4.232 − 4.3 = −0.068 (raw outcome units; caller renders as Δμ)
    expect(windowDelta(history, NOW, 7)).toBeCloseTo(-0.068, 6)
  })

  // ── Regime-aware deltas (thesis health→event series switch) ────────────────
  it('compares WITHIN the current regime — a same-regime anchor renders', () => {
    // Current point is the "event" series; the in-window anchor is also "event".
    const history = [
      { as_of: day(30), headline_probability: 0.51, headline_regime: 'health' },
      { as_of: day(10), headline_probability: 0.35, headline_regime: 'event' }, // 1W anchor (same regime)
      { as_of: day(1), headline_probability: 0.38, headline_regime: 'event' } // current
    ]
    // +0.03 vs the same-regime event point, NOT −0.13 vs the health baseline.
    expect(windowDelta(history, NOW, 7)).toBeCloseTo(0.03, 6)
    expect(windowDeltaDetail(history, NOW, 7)).toEqual({ delta: expect.closeTo(0.03, 6), newSeries: false })
  })

  it('returns null (new series) when the only in-window baseline predates the regime switch', () => {
    // Every event point is recent; the sole in-window (≤ now−7d) anchor is health.
    const history = [
      { as_of: day(30), headline_probability: 0.51, headline_regime: 'health' }, // in 1W window but wrong regime
      { as_of: day(2), headline_probability: 0.35, headline_regime: 'event' },
      { as_of: day(1), headline_probability: 0.36, headline_regime: 'event' } // current (event)
    ]
    // A delta across the health→event switch is a lie → null, flagged newSeries.
    expect(windowDelta(history, NOW, 7)).toBeNull()
    expect(windowDeltaDetail(history, NOW, 7)).toEqual({ delta: null, newSeries: true })
  })

  it('plain null (not newSeries) when there is simply no in-window anchor at all', () => {
    const history = [
      { as_of: day(2), headline_probability: 0.35, headline_regime: 'event' },
      { as_of: day(1), headline_probability: 0.36, headline_regime: 'event' }
    ]
    // No point ≤ now−7d → a bare absence, not a regime boundary.
    expect(windowDeltaDetail(history, NOW, 7)).toEqual({ delta: null, newSeries: false })
  })

  it('regime gate is inert for series without a regime (member rows unchanged)', () => {
    const history = [
      { as_of: day(30), headline_probability: 0.4 },
      { as_of: day(10), headline_probability: 0.5 },
      { as_of: day(2), headline_probability: 0.58 }
    ]
    // Byte-identical to the non-regime path: +0.08, never flagged newSeries.
    expect(windowDeltaDetail(history, NOW, 7)).toEqual({ delta: expect.closeTo(0.08, 6), newSeries: false })
  })
})

describe('levelSparkline', () => {
  it('maps probabilities to fixed-scale ramp characters', () => {
    // 0 → lowest block, 1 → highest block, 0.5 → middle-ish
    const spark = levelSparkline([0, 0.5, 1])
    expect(spark).toHaveLength(3)
    expect(spark[0]).toBe('▁')
    expect(spark[2]).toBe('█')
  })

  it('renders nulls as gaps', () => {
    expect(levelSparkline([0.5, null, 0.5])[1]).toBe(' ')
  })

  it('is fixed-scale, not max-normalized (a flat low series stays low)', () => {
    // All 0.1 — a low block (ramp idx 1), NOT full height '█' which a
    // max-normalized sparkline would wrongly produce for a flat series.
    const spark = levelSparkline([0.1, 0.1, 0.1])
    expect(spark).toBe('▂▂▂')
    expect(spark).not.toContain('█')
  })

  it('returns empty string for empty input', () => {
    expect(levelSparkline([])).toBe('')
  })
})

describe('compactNumber', () => {
  it('abbreviates large magnitudes with k/M/B/T at ~3 sig figs', () => {
    expect(compactNumber(73000)).toBe('73k')
    expect(compactNumber(73500)).toBe('73.5k')
    expect(compactNumber(125)).toBe('125')
    expect(compactNumber(1_234_567)).toBe('1.23M')
    expect(compactNumber(2_500_000_000)).toBe('2.5B')
    expect(compactNumber(3_000_000_000_000)).toBe('3T')
  })

  it('leaves sub-thousand values as the prior 2-decimal trimmed display', () => {
    expect(compactNumber(4.24)).toBe('4.24')
    expect(compactNumber(0.098)).toBe('0.1')
    expect(compactNumber(49.3)).toBe('49.3')
    expect(compactNumber(0)).toBe('0')
  })

  it('handles negatives and nullish', () => {
    expect(compactNumber(-73000)).toBe('-73k')
    expect(compactNumber(null)).toBe('—')
    expect(compactNumber(Number.NaN)).toBe('—')
  })
})

describe('axisLabels', () => {
  it('shares one decimal count + suffix across all ticks', () => {
    expect(axisLabels([100.08, 100, 99.92])).toEqual(['100.08', '100.00', '99.92'])
    expect(axisLabels([1, 0.5, 0])).toEqual(['1.0', '0.5', '0.0'])
    expect(axisLabels([75000, 73000, 71000])).toEqual(['75k', '73k', '71k'])
    expect(axisLabels([75500, 73000, 71000])).toEqual(['75.5k', '73.0k', '71.0k'])
    expect(axisLabels([0.79, 0.61, 0.43])).toEqual(['0.79', '0.61', '0.43'])
  })
})

describe('bandChart', () => {
  it('produces height rows each with a y-gutter', () => {
    const chart = bandChart([{ y: 0.5 }], { width: 20, height: 5 })
    expect(chart.rows).toHaveLength(5)
    for (const row of chart.rows) {
      expect(row).toContain('│')
    }
    // All three labels share one decimal count (the mid 0.5 forces 1 decimal).
    expect(chart.axis.top).toBe('1.0')
    expect(chart.axis.bottom).toBe('0.0')
  })

  it('gives all three axis labels the same number of decimal places', () => {
    const chart = bandChart([{ y: 100 }], { width: 30, height: 5, yMin: 99.92, yMax: 100.08 })
    const labels = chart.rows.map(row => row.split('│')[0]!.trim()).filter(Boolean)
    expect(labels).toEqual(['100.08', '100.00', '99.92'])
  })

  it('pads axis labels to a uniform width so the plot column never shifts', () => {
    // Large-magnitude values (BTC ~73000) must not push the gutter wider on
    // some rows than others, and must abbreviate with k/M/B/T.
    const chart = bandChart([{ y: 73000 }], { width: 30, height: 5, yMin: 71000, yMax: 75000 })
    const barColumns = chart.rows.map(row => row.indexOf('│'))
    expect(new Set(barColumns).size).toBe(1) // the │ is at the same column in every row
    expect(chart.axis.top).toBe('75k')
    expect(chart.axis.bottom).toBe('71k')
  })

  it('places the marker higher for higher probabilities', () => {
    const low = bandChart([{ y: 0.1 }], { width: 12, height: 7 })
    const high = bandChart([{ y: 0.9 }], { width: 12, height: 7 })
    const markerRow = (rows: string[]) => rows.findIndex(r => r.includes('●'))
    // higher probability → marker nearer the top → smaller row index
    expect(markerRow(high.rows)).toBeLessThan(markerRow(low.rows))
  })

  it('draws a confidence band between lo and hi', () => {
    const chart = bandChart([{ y: 0.5, lo: 0.3, hi: 0.7 }], { width: 12, height: 9 })
    const bandRows = chart.rows.filter(r => r.includes('░'))
    expect(bandRows.length).toBeGreaterThan(0)
    // the marker still appears
    expect(chart.rows.some(r => r.includes('●'))).toBe(true)
  })

  it('spreads multiple points across columns (first left, last right)', () => {
    const chart = bandChart([{ y: 0.2 }, { y: 0.5 }, { y: 0.8 }], { width: 20, height: 7 })
    const plot = chart.rows.map(r => r.split('│')[1] ?? '')
    const markerCols = plot
      .flatMap(row => [...row].map((ch, i) => (ch === '●' ? i : -1)))
      .filter(i => i >= 0)
      .sort((a, b) => a - b)
    expect(markerCols.length).toBe(3)
    expect(markerCols[0]).toBe(0)
    expect(markerCols[markerCols.length - 1]).toBe((plot[0] ?? '').length - 1)
  })

  it('ignores points without a numeric y', () => {
    const chart = bandChart([{ y: null }, { y: 0.5 }], { width: 12, height: 5 })
    const markers = chart.rows.join('').split('●').length - 1
    expect(markers).toBe(1)
  })
})

describe('histogram', () => {
  it('renders one bar per outcome with values', () => {
    const rows = histogram(
      [
        { label: 'lt_3_0', value: 0.25 },
        { label: '3_0_3_2', value: 0.45 },
        { label: 'gt_3_2', value: 0.3 }
      ],
      { width: 10, labelWidth: 8 }
    )
    expect(rows).toHaveLength(3)
    // mode (0.45) fills the whole track
    expect(rows[1]).toContain('██████████')
    expect(rows[1]).toContain('0.45')
  })

  it('truncates long labels with an ellipsis', () => {
    const rows = histogram([{ label: 'an_extremely_long_outcome_label', value: 0.5 }], { labelWidth: 10 })
    expect(rows[0]!.startsWith('an_extrem…')).toBe(true)
  })

  it('returns empty for no usable bars', () => {
    expect(histogram([])).toEqual([])
    expect(histogram([{ label: 'x', value: Number.NaN }])).toEqual([])
  })

  it('appends a [lo–hi] interval suffix when a bar carries one', () => {
    const rows = histogram(
      [
        { label: 'Pappas', value: 72, interval: { lo: 50, hi: 85 } },
        { label: 'Jarvis', value: 6 },
      ],
      { width: 10, labelWidth: 8 }
    )
    expect(rows[0]).toContain('72 [50–85]')
    expect(rows[1]!.includes('[')).toBe(false) // no interval -> no suffix
  })

  it('overlays a per-candidate interval BRACKET (├ p05, ┤ p95) on the bar track', () => {
    const rows = histogram(
      [
        { label: 'Farage', value: 67, interval: { lo: 58, hi: 75.5 } },
        { label: 'Binface', value: 16.5, interval: { lo: 11.5, hi: 22.5 } },
      ],
      { width: 24, labelWidth: 8 }
    )
    // Both bars carry the bracket glyphs on the track and the numeric suffix.
    expect(rows[0]).toContain('├')
    expect(rows[0]).toContain('┤')
    expect(rows[0]).toContain('[58–75.5]')
    expect(rows[1]).toContain('├')
    expect(rows[1]).toContain('┤')
  })

  it('extends the axis to the widest interval so an upper tail never clips', () => {
    // A candidate whose p95 (95) overshoots the largest POINT (60) still lands on-track.
    const rows = histogram(
      [{ label: 'A', value: 60, interval: { lo: 40, hi: 95 } }],
      { width: 20, labelWidth: 4 }
    )
    // ┤ sits at the far right (p95 is the widest artifact), never off the track.
    const cell = rows[0]!.split(' ').find(seg => seg.includes('┤'))
    expect(cell?.endsWith('┤')).toBe(true)
  })
})

describe('boxWhisker', () => {
  it('renders whisker endpoints, an IQR box, and a median tick', () => {
    const line = boxWhisker(
      { min: 0.2, p25: 0.4, median: 0.5, p75: 0.6, max: 0.8 },
      { width: 20 }
    )
    expect(line).toContain('├')
    expect(line).toContain('┤')
    expect(line).toContain('┃')
    expect(line).toContain('▒')
    expect(line).toHaveLength(20)
  })

  it('positions min left of max on the track', () => {
    const line = boxWhisker({ min: 0.1, max: 0.9 }, { width: 20 })
    expect(line.indexOf('├')).toBeLessThan(line.indexOf('┤'))
  })

  it('returns empty when min/max are missing', () => {
    expect(boxWhisker({})).toBe('')
    expect(boxWhisker({ min: 0.2 })).toBe('')
  })
})

describe('dotTrack', () => {
  it('places the value marker and the reference tick on the rail', () => {
    const line = dotTrack(0.25, 0.75, { width: 21 })
    expect(line).toHaveLength(21)
    expect(line).toContain('●')
    expect(line).toContain('┊')
    expect(line.indexOf('●')).toBeLessThan(line.indexOf('┊'))
  })

  it('the value wins when value and reference share a cell', () => {
    const line = dotTrack(0.5, 0.5, { width: 21 })
    expect(line).toContain('●')
    expect(line).not.toContain('┊')
  })

  it('omits the reference tick when the reference is not finite', () => {
    const line = dotTrack(0.5, null, { width: 11 })
    expect(line).toContain('●')
    expect(line).not.toContain('┊')
  })

  it('returns empty for a non-finite value', () => {
    expect(dotTrack(null, 0.5)).toBe('')
    expect(dotTrack(Number.NaN, 0.5)).toBe('')
  })

  it('clamps out-of-range values onto the rail ends', () => {
    expect(dotTrack(1.4, 0.5, { width: 11 }).endsWith('●')).toBe(true)
    expect(dotTrack(-0.4, 0.5, { width: 11 }).startsWith('●')).toBe(true)
  })
})

describe('edge cases & defect scenarios', () => {
  describe('bandChart edge cases', () => {
    it('handles width <= gutter (plotW becomes 1)', () => {
      const chart = bandChart([{ y: 0.5 }], { width: 3, height: 7 })
      // plotW = Math.max(1, 3 - 5) = 1
      for (const row of chart.rows) {
        const plot = row.split('│')[1] ?? ''
        expect(plot.length).toBeLessThanOrEqual(1)
      }
    })

    it('clamps height to minimum of 3', () => {
      const chart = bandChart([{ y: 0.5 }], { width: 20, height: 1 })
      expect(chart.rows.length).toBe(3)
    })

    it('handles single point without division by zero', () => {
      const chart = bandChart([{ y: 0.5 }], { width: 20, height: 5 })
      const markers = chart.rows.join('').split('●').length - 1
      expect(markers).toBe(1)
    })

    it('handles empty input', () => {
      const chart = bandChart([], { width: 20, height: 5 })
      expect(chart.rows.length).toBe(5)
      const markers = chart.rows.join('').split('●').length - 1
      expect(markers).toBe(0)
    })

    it('handles all null y values', () => {
      const chart = bandChart([{ y: null }, { y: null }], { width: 20, height: 5 })
      const markers = chart.rows.join('').split('●').length - 1
      expect(markers).toBe(0)
    })

    it('handles lo and hi being equal (zero-height band)', () => {
      const chart = bandChart([{ y: 0.5, lo: 0.5, hi: 0.5 }], { width: 20, height: 7 })
      // Band loop: for (let r = rTop; r <= rBot; r += 1) — when rTop == rBot, exactly one row
      const bandRows = chart.rows.filter(r => r.includes('░'))
      expect(bandRows.length).toBeGreaterThanOrEqual(0) // at least doesn't crash
      expect(chart.rows.some(r => r.includes('●'))).toBe(true)
    })

    it('handles yMax == yMin (zero span), defaults to span=1', () => {
      const chart = bandChart([{ y: 0.5 }], { width: 20, height: 7, yMin: 0.5, yMax: 0.5 })
      // span = 0.5 - 0.5 || 1 = 1
      expect(chart.rows.length).toBe(7)
    })

    it('handles negative yMin/yMax (numeric series like CPI)', () => {
      const chart = bandChart([{ y: 2.5 }, { y: 3.5 }], { width: 20, height: 7, yMin: 2, yMax: 4 })
      const low = bandChart([{ y: 2 }], { width: 12, height: 7, yMin: 2, yMax: 4 })
      const high = bandChart([{ y: 4 }], { width: 12, height: 7, yMin: 2, yMax: 4 })
      const markerRow = (rows: string[]) => rows.findIndex(r => r.includes('●'))
      // higher (4) should be higher on chart (smaller row index)
      expect(markerRow(high.rows)).toBeLessThan(markerRow(low.rows))
    })
  })

  describe('histogram edge cases', () => {
    it('returns empty array when all values are NaN', () => {
      const rows = histogram(
        [{ label: 'a', value: Number.NaN }, { label: 'b', value: Number.NaN }],
        { width: 10 }
      )
      expect(rows).toEqual([])
    })

    it('handles negative values (treats as-is for non-probability data)', () => {
      const rows = histogram([{ label: 'delta', value: -0.5 }], { width: 10 })
      expect(rows).toHaveLength(1)
      expect(rows[0]).toContain('-0.50')
    })

    it('returns empty for truly empty input', () => {
      const rows = histogram([], { width: 10 })
      expect(rows).toEqual([])
    })

    it('handles single bar', () => {
      const rows = histogram([{ label: 'only', value: 0.5 }], { width: 10 })
      expect(rows).toHaveLength(1)
      // max is 0.5, so frac = 0.5 / 0.5 = 1.0, fill = 10
      expect(rows[0]).toContain('██████████')
    })

    it('handles all zero values', () => {
      const rows = histogram([{ label: 'a', value: 0 }, { label: 'b', value: 0 }], { width: 10 })
      expect(rows).toHaveLength(2)
      // max = 0, frac = 0, fill = 0 → no bars
      expect(rows[0]).not.toContain('█')
    })

    it('handles Infinity values gracefully', () => {
      // Infinity is not finite, so it is filtered by the usable check — keeping
      // it would make `max` Infinity and zero out every other bar.
      const rows = histogram(
        [{ label: 'normal', value: 0.5 }, { label: 'inf', value: Number.POSITIVE_INFINITY }],
        { width: 10 }
      )
      expect(rows).toHaveLength(1)
      expect(rows[0]).toContain('normal')
    })
  })

  describe('boxWhisker edge cases', () => {
    it('returns empty when only min is provided', () => {
      const line = boxWhisker({ min: 0.2 }, { width: 20 })
      expect(line).toBe('')
    })

    it('returns empty when only max is provided', () => {
      const line = boxWhisker({ max: 0.8 }, { width: 20 })
      expect(line).toBe('')
    })

    it('handles min == max == 0.5 (zero width)', () => {
      const line = boxWhisker({ min: 0.5, max: 0.5 }, { width: 20 })
      // cMin = col(0.5) = 10 (middle)
      // cMax = col(0.5) = 10
      // Loop: for (let i = 10; i <= 10; i++) → exactly one cell
      expect(line).toHaveLength(20)
      expect(line[10]).not.toBeUndefined()
    })

    it('handles p25 > p75 (inverted IQR)', () => {
      const line = boxWhisker(
        { min: 0.2, max: 0.8, p25: 0.7, p75: 0.3 },
        { width: 20 }
      )
      // for (let i = Math.min(p25, p75); i <= Math.max(p25, p75); i++) handles inversion
      expect(line).toContain('▒')
      expect(line.length).toBe(20)
    })

    it('handles width < 3 minimum width constraint', () => {
      const line = boxWhisker({ min: 0.1, max: 0.9 }, { width: 1 })
      // track = Math.max(3, 1) = 3
      expect(line.length).toBe(3)
    })

    it('handles missing p25/p75/median (falls back to min/max)', () => {
      const line = boxWhisker({ min: 0.2, max: 0.8 }, { width: 20 })
      // p25 defaults to cMin, p75 to cMax, median to (cMin + cMax) / 2
      expect(line).toContain('├')
      expect(line).toContain('┤')
      expect(line).toContain('┃')
      expect(line.length).toBe(20)
    })

    it('handles yMin == yMax (zero span), defaults to 1', () => {
      const line = boxWhisker(
        { min: 0.5, max: 0.5 },
        { width: 20, yMin: 0.5, yMax: 0.5 }
      )
      // span = 0.5 - 0.5 || 1 = 1
      // col() will clamp to [0, 19]
      expect(line.length).toBe(20)
    })
  })

  describe('levelSparkline edge cases', () => {
    it('returns empty string for empty input', () => {
      expect(levelSparkline([])).toBe('')
    })

    it('returns empty string when span is <= 0', () => {
      expect(levelSparkline([0.5], { yMin: 0.5, yMax: 0.5 })).toBe('')
      expect(levelSparkline([0.5], { yMin: 1, yMax: 0.5 })).toBe('')
    })

    it('handles all null values as gaps', () => {
      const spark = levelSparkline([null, null, null])
      expect(spark).toBe('   ')
    })

    it('handles mixed null and values', () => {
      const spark = levelSparkline([0.1, null, 0.9])
      expect(spark[0]).not.toBe(' ')
      expect(spark[1]).toBe(' ')
      expect(spark[2]).not.toBe(' ')
    })

    it('handles Infinity values gracefully', () => {
      const spark = levelSparkline([0.5, Number.POSITIVE_INFINITY])
      // finite() check filters infinity to space
      expect(spark[1]).toBe(' ')
    })

    it('handles NaN values as gaps', () => {
      const spark = levelSparkline([0.5, Number.NaN])
      expect(spark[1]).toBe(' ')
    })
  })
})

describe('bandChart gutter/plot metrics', () => {
  it('reports the gutter width (label + " │") and the plot width so the x-axis lines up', () => {
    const chart = bandChart([{ y: 0.5 }], { width: 30, height: 5 })
    // rows are "<label> │<cells>": the │ sits at gutterW - 1 and cells start at gutterW.
    const row = chart.rows[0]!
    expect(row[chart.gutterW - 1]).toBe('│')
    expect(row.length).toBe(chart.gutterW + chart.plotW)
    expect(chart.plotW).toBeGreaterThan(0)
  })
})

describe('timeAxis', () => {
  const countOf = (haystack: string, needle: string): number => haystack.split(needle).length - 1

  it('spreads 3-5 deduped date labels across a multi-snapshot range, anchoring both ends', () => {
    const axis = timeAxis(['2026-05-01T00:00:00Z', '2026-05-15T00:00:00Z', '2026-05-29T00:00:00Z'], {
      gutterW: 6,
      plotW: 48
    })!
    expect(axis).not.toBeNull()
    // Both endpoints are labelled...
    expect(axis.labels).toContain('2026-05-01')
    expect(axis.labels).toContain('2026-05-29')
    // ...each date appears exactly once (deduped, non-overlapping).
    expect(countOf(axis.labels, '2026-05-01')).toBe(1)
    expect(countOf(axis.labels, '2026-05-29')).toBe(1)
    // The base rule carries real tick marks + a y-axis corner.
    expect(axis.ticks).toContain('┬')
    expect(axis.ticks).toContain('└')
  })

  it('dedupes when a short range would print the same day twice', () => {
    // A range under a handful of days: several interpolated ticks collapse to the
    // same calendar day — each day must still be printed only once.
    const axis = timeAxis(['2026-06-22T00:00:00Z', '2026-06-23T00:00:00Z'], { gutterW: 6, plotW: 40 })!
    expect(countOf(axis.labels, '2026-06-22')).toBe(1)
    expect(countOf(axis.labels, '2026-06-23')).toBe(1)
  })

  it('labels a degenerate single-date range ONCE, centered', () => {
    const axis = timeAxis(['2026-06-22T00:00:00Z', '2026-06-22T00:00:00Z'], { gutterW: 6, plotW: 40 })!
    expect(countOf(axis.labels, '2026-06-22')).toBe(1)
    // centered: leading run of spaces before the label, trailing run after it.
    const start = axis.labels.indexOf('2026-06-22')
    expect(start).toBeGreaterThan(6) // past the gutter, indented into the plot
  })

  it('gutter-prefixes both lines so they drop under the plot cells', () => {
    const axis = timeAxis(['2026-05-01T00:00:00Z', '2026-05-29T00:00:00Z'], { gutterW: 8, plotW: 40 })!
    // corner sits at gutterW - 1; labels begin at gutterW.
    expect(axis.ticks[7]).toBe('└')
    expect(axis.labels.slice(0, 8)).toBe(' '.repeat(8))
  })

  it('returns null when no date parses', () => {
    expect(timeAxis([null, undefined, 'not-a-date'], { gutterW: 6, plotW: 40 })).toBeNull()
  })
})

describe('wrapLines', () => {
  it('word-wraps within the width', () => {
    const lines = wrapLines('the quick brown fox jumps', 10, 3)
    expect(lines.every(line => line.length <= 10)).toBe(true)
    expect(lines.join(' ')).toBe('the quick brown fox jumps')
  })

  it('caps at maxLines and tail-truncates the overflow with a single ellipsis', () => {
    const lines = wrapLines('one two three four five six seven eight nine ten eleven', 8, 3)
    expect(lines.length).toBe(3)
    expect(lines[2]!.endsWith('…')).toBe(true)
    expect(lines[2]!.length).toBeLessThanOrEqual(8)
    // only the capped last line carries the ellipsis
    expect(lines.filter(line => line.includes('…')).length).toBe(1)
  })

  it('hard-breaks a single word longer than the width', () => {
    const lines = wrapLines('supercalifragilistic', 6, 3)
    expect(lines[0]!.length).toBe(6)
  })

  it('returns [] for empty/blank text', () => {
    expect(wrapLines('', 10)).toEqual([])
    expect(wrapLines('   ', 10)).toEqual([])
  })
})

// ── FIX 1: the y-domain must include every drawn artifact ─────────────────────
// THE LAW: bandChart must never silently clamp a drawn value onto the axis
// boundary. Whatever domain the caller passes, the chart expands it so every
// marker + band edge lands honestly inside the plot — a dot must never sit past
// the drawn axis bound.
describe('bandChart domain containment (dots never escape the axis)', () => {
  it('reports the effective [yMin, yMax] it actually drew against', () => {
    const chart = bandChart([{ y: 0.5 }], { width: 20, height: 7 })
    expect(typeof chart.yMin).toBe('number')
    expect(typeof chart.yMax).toBe('number')
    expect(chart.yMin).toBeLessThan(chart.yMax)
  })

  it('expands a subset domain UP to include a point above the supplied bound', () => {
    // Caller under-scoped the axis (yMax 0.5) but a real point sits at 0.9. The
    // old code clamped 0.9 onto row 0 — a dot welded to the top rule. The chart
    // must instead expand so 0.9 is genuinely inside the domain.
    const chart = bandChart([{ y: 0.9 }, { y: 0.5 }], { width: 24, height: 9, yMin: 0, yMax: 0.5 })
    expect(chart.yMax).toBeGreaterThanOrEqual(0.9)
    // Two distinct values must render in two distinct rows — not both pinned to
    // the boundary.
    const markerRows = new Set(glyphCells(chart, '●').map(cell => cell.row))
    expect(markerRows.size).toBe(2)
  })

  it('expands DOWN to include a point below the supplied bound', () => {
    const chart = bandChart([{ y: -0.3 }, { y: 0.4 }], { width: 24, height: 9, yMin: 0, yMax: 1 })
    expect(chart.yMin).toBeLessThanOrEqual(-0.3)
  })

  it('expands to include band edges that exceed the supplied domain', () => {
    // The marker is inside [0,1] but its band reaches 1.0 — the band edge is a
    // drawn artifact too and must be strictly inside the axis (so the guard lifts
    // the domain top past the edge value, never clamping it).
    const chart = bandChart([{ y: 0.95, lo: 0.9, hi: 1.0 }], { width: 24, height: 9, yMin: 0, yMax: 1 })
    expect(chart.yMax).toBeGreaterThan(1.0)
  })

  it('contains a probability extreme (100%) honestly instead of clamping it', () => {
    // A 100% dot correctly sits at the axis top — but the domain must genuinely
    // CONTAIN it (yMax strictly above 1 via the guard), so the placement is an
    // honest projection, not clamp01 masking an out-of-range value.
    const chart = bandChart([{ y: 1 }, { y: 0.4 }], { width: 24, height: 9, yMin: 0, yMax: 1 })
    expect(chart.yMax).toBeGreaterThan(1)
    // The two distinct values still land in two distinct rows.
    const markerRows = new Set(glyphCells(chart, '●').map(cell => cell.row))
    expect(markerRows.size).toBe(2)
  })

  it('never shrinks a domain that already contains the data with room', () => {
    // Interior data (a real event band): the caller-supplied zoom is respected
    // byte-for-byte, so honest tight zooms are not blown open.
    const chart = bandChart([{ y: 0.352, lo: 0.31, hi: 0.4 }], { width: 30, height: 7, yMin: 0.28, yMax: 0.44 })
    expect(chart.yMin).toBe(0.28)
    expect(chart.yMax).toBe(0.44)
  })

  it('handles a degenerate supplied domain (min == max) without collapsing', () => {
    const chart = bandChart([{ y: 0.4 }, { y: 0.6 }], { width: 20, height: 7, yMin: 0.5, yMax: 0.5 })
    expect(chart.yMax).toBeGreaterThan(chart.yMin)
    expect(chart.yMin).toBeLessThanOrEqual(0.4)
    expect(chart.yMax).toBeGreaterThanOrEqual(0.6)
  })

  it('PROPERTY: for arbitrary series + bands + domains, every glyph stays inside the axis', () => {
    // A deterministic LCG so the property is reproducible.
    let seed = 0x2545f491
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff
      return seed / 0x7fffffff
    }
    const span = (a: number, b: number) => a + rnd() * (b - a)

    for (let trial = 0; trial < 300; trial += 1) {
      const n = 1 + Math.floor(rnd() * 12)
      const points = Array.from({ length: n }, () => {
        if (rnd() < 0.15) {
          return { y: null as number | null }
        }
        const y = span(-2, 3)
        if (rnd() < 0.5) {
          const half = rnd() * 0.8
          return { y, lo: y - half, hi: y + half }
        }
        return { y }
      })
      const h = 3 + Math.floor(rnd() * 8)
      // Sometimes an adversarial (subset / degenerate / inverted) domain.
      const a = span(-1, 2)
      const b = span(-1, 2)
      const chart = bandChart(points, { width: 8 + Math.floor(rnd() * 40), height: h, yMin: Math.min(a, b), yMax: Math.max(a, b) })

      const values = drawnValues(points)
      // 1) Containment: the reported domain includes every drawn artifact.
      for (const v of values) {
        expect(v).toBeGreaterThanOrEqual(chart.yMin)
        expect(v).toBeLessThanOrEqual(chart.yMax)
      }
      // 2) Every glyph occupies a real axis row: 0..rows.length-1, and the honest
      //    (un-clamped) projection of each drawn value lands in that range too.
      const rowCount = chart.rows.length
      const dsp = chart.yMax - chart.yMin || 1
      for (const v of values) {
        const honestRow = Math.round((1 - (v - chart.yMin) / dsp) * (rowCount - 1))
        expect(honestRow).toBeGreaterThanOrEqual(0)
        expect(honestRow).toBeLessThanOrEqual(rowCount - 1)
      }
      for (const glyph of ['●', '░']) {
        for (const cell of glyphCells(chart, glyph)) {
          expect(cell.row).toBeGreaterThanOrEqual(0)
          expect(cell.row).toBeLessThanOrEqual(rowCount - 1)
        }
      }
    }
  })
})

// ── FIX 2: cap the dot preview at ~15 meaningful dots ─────────────────────────
describe('downsampleSeries (change-aware dot-plot thinning)', () => {
  it('returns every point untouched at or under the cap', () => {
    const values = [0.1, 0.2, 0.3, 0.4]
    const ds = downsampleSeries(values, { cap: 15 })
    expect(ds.downsampled).toBe(false)
    expect(ds.keptIndices).toEqual([0, 1, 2, 3])
    expect(ds.shown).toBe(4)
    expect(ds.total).toBe(4)
    expect(ds.note).toBe('')
  })

  it('caps at the requested number of dots and ALWAYS keeps first + last', () => {
    const values = Array.from({ length: 84 }, (_, i) => i / 84)
    const ds = downsampleSeries(values, { cap: 15 })
    expect(ds.downsampled).toBe(true)
    expect(ds.shown).toBe(15)
    expect(ds.keptIndices).toHaveLength(15)
    expect(ds.keptIndices[0]).toBe(0)
    expect(ds.keptIndices[ds.keptIndices.length - 1]).toBe(83)
    // strictly increasing (chronological order preserved)
    for (let i = 1; i < ds.keptIndices.length; i += 1) {
      expect(ds.keptIndices[i]!).toBeGreaterThan(ds.keptIndices[i - 1]!)
    }
  })

  it('keeps the points with the largest |delta| (material moves), not evenly-spaced ones', () => {
    // A flat series with two sharp jumps in the middle. Those two indices MUST be
    // kept over any of the flat neighbours.
    const values = [0.5, 0.5, 0.5, 0.9, 0.9, 0.9, 0.2, 0.2, 0.2, 0.2, 0.2]
    const ds = downsampleSeries(values, { cap: 4 })
    expect(ds.downsampled).toBe(true)
    expect(ds.keptIndices).toContain(3) // the +0.4 jump
    expect(ds.keptIndices).toContain(6) // the −0.7 jump
    expect(ds.keptIndices[0]).toBe(0)
    expect(ds.keptIndices[ds.keptIndices.length - 1]).toBe(10)
  })

  it('breaks ties by recency (the later change wins)', () => {
    // Two equal-magnitude jumps; with a budget of exactly one interior slot the
    // MORE RECENT one is kept.
    const values = [0.5, 0.7, 0.7, 0.7, 0.9, 0.9]
    const ds = downsampleSeries(values, { cap: 3 })
    expect(ds.keptIndices[0]).toBe(0)
    expect(ds.keptIndices[ds.keptIndices.length - 1]).toBe(5)
    expect(ds.keptIndices).toContain(4) // the later +0.2, not the earlier index 1
    expect(ds.keptIndices).not.toContain(1)
  })

  it('emits an honest caption only when it actually dropped points', () => {
    const many = downsampleSeries(Array.from({ length: 84 }, (_, i) => i / 84), { cap: 15, unit: 'snapshots' })
    expect(many.note).toBe('15 of 84 snapshots shown · largest moves')
    const few = downsampleSeries([0.1, 0.2], { cap: 15, unit: 'snapshots' })
    expect(few.note).toBe('')
  })

  it('counts only drawable (finite) points and never selects gaps', () => {
    const values = [0.1, null, 0.9, null, 0.2, 0.8, null, 0.3]
    const ds = downsampleSeries(values, { cap: 3 })
    // total counts the 5 finite points, not the 8 slots.
    expect(ds.total).toBe(5)
    // Every kept index points at a finite value.
    for (const i of ds.keptIndices) {
      expect(Number.isFinite(values[i])).toBe(true)
    }
    // first/last kept are the first/last FINITE indices.
    expect(ds.keptIndices[0]).toBe(0)
    expect(ds.keptIndices[ds.keptIndices.length - 1]).toBe(7)
  })

  it('degrades gracefully for a tiny cap (keeps first + last only)', () => {
    const ds = downsampleSeries([0.1, 0.4, 0.2, 0.9, 0.3], { cap: 2 })
    expect(ds.keptIndices).toEqual([0, 4])
    expect(ds.downsampled).toBe(true)
  })
})
