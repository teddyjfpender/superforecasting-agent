import { wrapAnsi } from '@superforecasting/ink'

import type { PagerState } from './interfaces.js'

// Page navigation and rendering must count the same visual lines. Raw newline
// counts overflow the terminal when report rows wrap, especially after resize.
export const pagerWindow = (pager: PagerState, columns: number, pageSize: number) => {
  const width = Math.max(1, columns - 8)
  const lines = pager.lines.flatMap(line => wrapAnsi(line, width, {hard: true, trim: false}).split('\n'))
  const offset = Math.min(pager.offset, Math.max(0, lines.length - pageSize))

  return {lines, offset}
}
