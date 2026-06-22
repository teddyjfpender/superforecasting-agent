// @hermes/viz — the terminal-native chart engine ("SVG of the terminal").
//
// The engine is pure (no React, no Ink, no deps): a chart function takes typed
// data + a RenderCtx and returns a RenderResult of StyledRow[] — rows of
// width-1 styled cell runs that the <CellCanvas> React layer mounts as <Text>.
// Cell-glyph backends (braille / half-block / blocks) compose with the existing
// renderer as plain width-1 strings, so this tier needs ZERO Ink-fork changes.

// One run of adjacent cells sharing a style. The atomic output unit; a row is a
// list of runs (mirrors the proven span model in outriderHeader.tsx).
export interface StyledRun {
  backgroundColor?: string // hex '#RRGGBB' | 'ansi256(n)' | undefined
  bold?: boolean
  color?: string
  dim?: boolean
  text: string // one or more WIDTH-1 glyphs (braille/blocks/ascii)
}

export type StyledRow = StyledRun[]

export interface RenderResult {
  axisBottom?: StyledRow
  legend?: StyledRow[]
  rows: StyledRow[]
}

// Blitter ladder (notcurses-style). Default ceiling is 'quad' (ubiquitous Block
// Elements); 'braille'/'sextant' are opt-in; 'octant' is defined elsewhere but
// NEVER auto-selected (Unicode 16, font-tofu risk).
export type Blitter = '1x1' | 'braille' | 'half' | 'quad' | 'sextant'

export type ColorMode = '16' | '256' | 'truecolor'

// Pixel/image escape protocols (Tier B, opt-in via HERMES_PIXEL_IMAGES). 'none'
// means use the cell-glyph tier (the universal default).
export type ImageProtocol = 'iterm2' | 'kitty' | 'none' | 'sixel'

export interface TerminalCaps {
  blitterMax: Blitter
  colorMode: ColorMode
  imageProtocol: ImageProtocol
}

export type ChartKind = 'candles' | 'depth' | 'distribution' | 'fan' | 'heatmap' | 'scatter' | 'sparkgrid'

// Resolved theme for charts (mapped from the app Theme by chartTheme.ts).
export interface ChartTheme {
  bands: string[] // faint→stronger band fill ramp
  down: string // diverging/correlation negative (used by heatmap sign)
  fg: string
  gain: string // price up / bid side (green)
  grid: string
  // colormap: t in [0,1] → hex. Diverging maps t=0.5 to the neutral midpoint.
  heat: (t: number) => string
  loss: string // price down / ask side (red)
  muted: string
  up: string // diverging/correlation positive
}

export interface RenderCtx {
  caps: TerminalCaps
  height?: number
  theme: ChartTheme
  width: number // clamped columns budget (cells)
}
