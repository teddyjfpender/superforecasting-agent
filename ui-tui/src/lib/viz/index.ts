// @hermes/viz — public engine API (pure, no React, no new deps).

export { type ChartMarker, lastValueLabel, overlayMarkers } from './annotate.js'
export { BRAILLE_BIT, BrailleCanvas, brailleChar, eighthBlock, halfBlock } from './blit.js'
export { CellBuffer } from './buffer.js'
export { capBlitter, pickBlitter, probeCaps, type ProbeTransport, resolveCaps } from './caps.js'
export { type Candle, type CandleData, renderCandles } from './charts/candles.js'
export { type DepthData, type DepthLevel, renderDepth } from './charts/depth.js'
export { type DistributionData, type DistributionInterval, renderDistribution } from './charts/distribution.js'
export { type FanBand, type FanData, renderFan } from './charts/fan.js'
export { type HeatmapData, renderHeatmap } from './charts/heatmap.js'
export { renderScatter, type ScatterData, type ScatterPoint } from './charts/scatter.js'
export { renderSparkgrid, type SparkCell, type SparkGridData } from './charts/sparkgrid.js'
export { diverging, intensityGlyph, mix, parseHex, quantize, rgbToAnsi256, sequential, toHex } from './color.js'
export {
  encodeImage,
  encodeITerm2,
  encodeKitty,
  encodePng,
  encodeSixel,
  pickImageProtocol,
  type Raster,
  rasterizeHeatmap
} from './protocol.js'
export { linear, lttb, niceDomain, niceTicks, tickIncrement } from './scale.js'
export type {
  Blitter,
  ChartKind,
  ChartTheme,
  ColorMode,
  ImageProtocol,
  RenderCtx,
  RenderResult,
  StyledRow,
  StyledRun,
  TerminalCaps
} from './types.js'
