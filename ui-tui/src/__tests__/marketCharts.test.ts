import { describe, expect, it } from 'vitest'

import { asciiTable, scatterPlot } from '../lib/marketCharts.js'

describe('scatterPlot', () => {
  it('returns height rows each with a gutter, and renders points + fit line', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 1, y: 1 },
      { x: 2, y: 2 },
      { x: 3, y: 3 }
    ]

    const fit = [
      { x: 0, y: 0 },
      { x: 3, y: 3 }
    ]

    const { rows, axis } = scatterPlot(points, fit, { height: 8, width: 40 })
    expect(rows).toHaveLength(8)

    for (const r of rows) {
      expect(r).toContain('│')
    }

    const joined = rows.join('\n')
    expect(joined).toContain('●') // data points
    expect(joined).toContain('·') // fit line
    expect(axis.bottom).toContain('0')
  })

  it('returns [] for empty input', () => {
    expect(scatterPlot([]).rows).toEqual([])
  })

  it('does not divide by zero on a degenerate (flat) domain', () => {
    const { rows } = scatterPlot([
      { x: 5, y: 5 },
      { x: 5, y: 5 }
    ], undefined, { height: 5, width: 20 })

    expect(rows).toHaveLength(5)
  })
})

describe('asciiTable', () => {
  const cols = [
    { key: 'metric', label: 'Metric' },
    { align: 'right' as const, key: 'value', label: 'Value' }
  ]

  const rows = [
    { metric: 'Total return', value: '12.5%' },
    { metric: 'Sharpe', value: 1.84 }
  ]

  it('renders header + rule + data rows', () => {
    const out = asciiTable(cols, rows, { width: 40 })
    expect(out.length).toBe(2 + rows.length)
    expect(out[0]).toContain('Metric')
    expect(out[1]).toMatch(/─+/)
    expect(out[2]).toContain('Total return')
  })

  it('formats numbers and right-aligns', () => {
    const out = asciiTable(cols, rows, { width: 40 })
    // Sharpe value 1.84 rendered via compactNumber, right-aligned in its column
    expect(out[3]).toMatch(/1\.84\s*$/)
  })

  it('drops the lowest-priority column when too narrow', () => {
    const out = asciiTable(cols, rows, { width: 8 })
    // only the first column survives → no "Value" header
    expect(out[0]).not.toContain('Value')
  })

  it('returns [] with no columns', () => {
    expect(asciiTable([], rows)).toEqual([])
  })
})
