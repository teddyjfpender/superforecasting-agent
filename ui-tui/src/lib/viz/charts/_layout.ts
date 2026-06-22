// Shared y-axis gutter geometry for plot charts (distribution / candles / depth /
// fan). Reuses forecastCharts.axisLabels for shared-precision tick labels so a
// 3-tick gutter aligns vertically. The gutter run is one cheap StyledRun per row.

import { axisLabels } from '../../forecastCharts.js'

export interface YGutter {
  bot: string
  gutterW: number
  labelW: number
  mid: string
  plotW: number
  top: string
}

export const yGutter = (yLo: number, yHi: number, width: number): YGutter => {
  const [top, mid, bot] = axisLabels([yHi, (yHi + yLo) / 2, yLo])
  const labelW = Math.max(4, top!.length, mid!.length, bot!.length)
  const gutterW = labelW + 2 // label + " │"
  const plotW = Math.max(1, width - gutterW)

  return { bot: bot!, gutterW, labelW, mid: mid!, plotW, top: top! }
}

// Right-aligned axis label for a plot row (top / mid / bottom, else blank), then
// the " │" separator — the standard left gutter cell run.
export const gutterText = (r: number, height: number, g: YGutter): string => {
  const label = r === 0 ? g.top : r === height - 1 ? g.bot : r === Math.floor((height - 1) / 2) ? g.mid : ''

  return `${label.padStart(g.labelW)} │`
}
