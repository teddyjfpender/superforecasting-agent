import {stringWidth} from '@superforecasting/ink'
import {describe, expect, it} from 'vitest'

import {pagerWindow} from '../app/pager.js'

describe('report pager visual lines', () => {
  it('wraps long report rows and wide Unicode without losing text', () => {
    const original = 'outcome evidence 世界 '.repeat(20)
    const view = pagerWindow({lines: [original], offset: 0}, 80, 18)
    expect(view.lines.length).toBeGreaterThan(1)
    expect(view.lines.every(line => stringWidth(line) <= 72)).toBe(true)
    expect(view.lines.join('')).toBe(original)
  })
  it('keeps the final page reachable and clamps a stale offset on resize', () => {
    const pager = {lines: ['x'.repeat(400)], offset: 100}
    const narrow = pagerWindow(pager, 30, 5)
    expect(narrow.offset + 5).toBe(narrow.lines.length)
    const wide = pagerWindow(pager, 150, 5)
    expect(wide.offset).toBe(0)
    expect(wide.lines.join('')).toBe('x'.repeat(400))
  })
})
