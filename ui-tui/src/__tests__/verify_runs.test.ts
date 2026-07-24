import { describe, expect, it } from 'vitest'

import { diverging, renderHeatmap } from '../lib/viz/index.js'
import type { ChartTheme, RenderCtx } from '../lib/viz/index.js'

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  muted: '#888888',
  up: '#ff0000'
}

describe('actual run counts for 120-column heatmap', () => {
  it('should measure actual run counts', () => {
    // Correlation-like matrix: smooth variation but many distinct values
    const matrix = Array.from({ length: 40 }, (_, i) =>
      Array.from({ length: 120 }, (_, j) => 
        Math.sin(i * 0.1) * Math.cos(j * 0.1)
      )
    )

    const ctx: RenderCtx = {
      caps: { blitterMax: 'braille', colorMode: 'truecolor' },
      height: 40,
      theme: THEME,
      width: 120
    }

    const r = renderHeatmap({ diverging: true, matrix }, ctx)
    
    console.log(`\nRendered ${r.rows.length} rows`)
    
    const runCounts = r.rows.map(row => row.length)
    const maxRuns = Math.max(...runCounts)
    const minRuns = Math.min(...runCounts)
    const avgRuns = (runCounts.reduce((a, b) => a + b, 0) / runCounts.length).toFixed(1)
    
    console.log(`Run counts: min=${minRuns}, max=${maxRuns}, avg=${avgRuns}`)
    console.log(`First 5 rows: ${runCounts.slice(0, 5).join(', ')}`)
    console.log(`Last 5 rows: ${runCounts.slice(-5).join(', ')}`)
    
    // The finding claims we should see many runs (120 or close to it)
    // if coalescing is poor
    console.log(`\nExpected by finding: max runs close to 120 (poor coalescing)`)
    console.log(`Actual max runs: ${maxRuns}`)
    
    expect(r.rows.length).toBeGreaterThan(0)
  })
})
