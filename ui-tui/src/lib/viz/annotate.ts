// Annotations — pure, additive overlays for plot charts: horizontal reference /
// threshold lines and a last-value label. Drawn into a CellBuffer only where the
// cell is still blank, so data is never clobbered.

import { stringWidth } from '@superforecasting/ink'

import { compactNumber } from '../forecastCharts.js'

import type { CellBuffer } from './buffer.js'
import type { ChartTheme, StyledRun } from './types.js'

export interface ChartMarker {
  color?: string
  label?: string
  y: number
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

// Draw each marker as a dashed horizontal line across blank cells at its row,
// with a short right-aligned label. `rowOf` maps a y-value to a cell row.
export const overlayMarkers = (
  buf: CellBuffer,
  markers: ChartMarker[] | undefined,
  rowOf: (y: number) => number,
  plotW: number,
  height: number,
  theme: ChartTheme
): void => {
  for (const m of markers ?? []) {
    if (!m || !finite(m.y)) {
      continue
    }

    const r = rowOf(m.y)

    if (r < 0 || r >= height) {
      continue
    }

    const color = m.color ?? theme.muted

    for (let c = 0; c < plotW; c++) {
      if (buf.isBlank(c, r)) {
        buf.set(c, r, '╌', { color, dim: true })
      }
    }

    // Each CellBuffer cell holds ONE glyph, so the label must be width-1 only —
    // drop wide chars (CJK/emoji from an agent label) that would desync the row.
    const label = [...(m.label ?? compactNumber(m.y))].filter(ch => stringWidth(ch) === 1).join('').slice(0, Math.max(0, plotW))

    if (label) {
      const start = Math.max(0, plotW - label.length)

      for (let i = 0; i < label.length; i++) {
        buf.set(start + i, r, label[i]!, { color })
      }
    }
  }
}

// A "▸ <value>" run for a series' latest value (charts append it to a legend).
export const lastValueLabel = (value: number, color: string, unit = ''): StyledRun => ({
  color,
  text: `▸ ${finite(value) ? compactNumber(value) : '—'}${unit}`
})
