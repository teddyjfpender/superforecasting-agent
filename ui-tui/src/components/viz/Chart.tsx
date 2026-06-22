import { useMemo } from 'react'

import {
  type CandleData,
  type ChartKind,
  type DepthData,
  type DistributionData,
  type FanData,
  type HeatmapData,
  renderCandles,
  type RenderCtx,
  renderDepth,
  renderDistribution,
  renderFan,
  renderHeatmap,
  type RenderResult,
  renderScatter,
  renderSparkgrid,
  type ScatterData,
  type SparkGridData
} from '../../lib/viz/index.js'
import type { Theme } from '../../theme.js'

import { CellCanvas } from './Canvas.js'
import { themeToChartTheme } from './chartTheme.js'
import { useViewportCaps } from './useViewportCaps.js'

interface ChartProps {
  data: unknown
  height?: number
  kind: ChartKind
  t: Theme
  width: number
}

const render = (kind: ChartKind, data: unknown, ctx: RenderCtx): RenderResult => {
  switch (kind) {
    case 'heatmap':
      return renderHeatmap(data as HeatmapData, ctx)

    case 'fan':
      return renderFan(data as FanData, ctx)

    case 'distribution':
      return renderDistribution(data as DistributionData, ctx)

    case 'candles':
      return renderCandles(data as CandleData, ctx)

    case 'depth':
      return renderDepth(data as DepthData, ctx)

    case 'sparkgrid':
      return renderSparkgrid(data as SparkGridData, ctx)

    case 'scatter':
      return renderScatter(data as ScatterData, ctx)

    default:
      return { rows: [] }
  }
}

// Renders ONCE per [kind, data, width, height, caps, theme]; no per-pixel React.
export function Chart({ data, height, kind, t, width }: ChartProps) {
  const caps = useViewportCaps()
  const theme = useMemo(() => themeToChartTheme(t), [t])

  const result = useMemo(
    () => render(kind, data, { caps, height, theme, width: Math.max(8, width) }),
    [kind, data, width, height, caps, theme]
  )

  return <CellCanvas result={result} />
}
