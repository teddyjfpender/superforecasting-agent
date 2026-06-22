// CellBuffer: an offscreen grid of styled cells that compiles to StyledRow[],
// coalescing runs of identical style so a heatmap row becomes ONE <Text> instead
// of one-per-cell (the Risk-2 perf guard). The color plane is lazy: monochrome
// charts never allocate it.

import type { StyledRow, StyledRun } from './types.js'

interface CellStyle {
  backgroundColor?: string
  bold?: boolean
  color?: string
  dim?: boolean
}

const sameStyle = (a: CellStyle | undefined, b: CellStyle | undefined): boolean =>
  (a?.color ?? '') === (b?.color ?? '') &&
  (a?.backgroundColor ?? '') === (b?.backgroundColor ?? '') &&
  Boolean(a?.bold) === Boolean(b?.bold) &&
  Boolean(a?.dim) === Boolean(b?.dim)

export class CellBuffer {
  private readonly glyphs: string[][]
  private readonly styles: (CellStyle | undefined)[][]

  constructor(readonly cols: number, readonly rows: number) {
    this.glyphs = Array.from({ length: rows }, () => Array.from({ length: cols }, () => ' '))
    this.styles = Array.from({ length: rows }, () => new Array<CellStyle | undefined>(cols).fill(undefined))
  }

  // True when the cell still holds its blank default (used by overlays so an
  // annotation never clobbers plotted data).
  isBlank(col: number, row: number): boolean {
    if (col < 0 || row < 0 || col >= this.cols || row >= this.rows) {
      return false
    }

    return this.glyphs[row]![col] === ' '
  }

  set(col: number, row: number, glyph: string, style?: CellStyle): void {
    if (col < 0 || row < 0 || col >= this.cols || row >= this.rows) {
      return
    }

    this.glyphs[row]![col] = glyph

    if (style) {
      this.styles[row]![col] = style
    }
  }

  // Fast path: fill a whole row from per-cell {t, fg, bg}. Used by the heatmap so
  // an N-color row still coalesces correctly at compile().
  setRow(row: number, cells: ReadonlyArray<{ bg?: string; fg?: string; t: string }>): void {
    if (row < 0 || row >= this.rows) {
      return
    }

    for (let c = 0; c < this.cols && c < cells.length; c++) {
      const cell = cells[c]!
      this.glyphs[row]![c] = cell.t
      this.styles[row]![c] = cell.fg || cell.bg ? { backgroundColor: cell.bg, color: cell.fg } : undefined
    }
  }

  // Coalesce each row's cells into runs of identical style.
  compile(): StyledRow[] {
    return this.glyphs.map((rowGlyphs, r) => {
      const rowStyles = this.styles[r]!
      const runs: StyledRun[] = []

      for (let c = 0; c < this.cols; c++) {
        const st = rowStyles[c]
        const last = runs[runs.length - 1]

        if (last && sameStyle(last, st)) {
          last.text += rowGlyphs[c]!
        } else {
          runs.push({ ...st, text: rowGlyphs[c]! })
        }
      }

      return runs
    })
  }
}
