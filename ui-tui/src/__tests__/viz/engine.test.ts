import { describe, expect, it } from 'vitest'

import { capBlitter, CellBuffer, lttb, niceDomain, niceTicks, pickBlitter, quantize, resolveCaps, rgbToAnsi256, tickIncrement } from '../../lib/viz/index.js'
import type { TerminalCaps } from '../../lib/viz/index.js'

describe('scale: niceTicks / niceDomain / tickIncrement', () => {
  it('produces 1/2/5·10^k steps and inclusive nice ticks', () => {
    expect(tickIncrement(0, 100, 5)).toBe(20)
    expect(tickIncrement(0, 1, 5)).toBe(0.2)
    expect(niceTicks(0, 100, 5)).toEqual([0, 20, 40, 60, 80, 100])
    expect(niceTicks(0, 1, 5)[0]).toBe(0)
  })

  it('nices a domain outward to the step grid', () => {
    expect(niceDomain(0.3, 97.6, 5)).toEqual([0, 100])
    expect(niceDomain(5, 5)).toEqual([0, 5])
  })
})

describe('scale: lttb', () => {
  it('returns input when threshold >= length', () => {
    const d: [number, number][] = [[0, 0], [1, 1], [2, 2]]
    expect(lttb(d, 10)).toEqual(d)
  })

  it('downsamples to threshold and keeps endpoints', () => {
    const d: [number, number][] = Array.from({ length: 100 }, (_, i) => [i, Math.sin(i / 5)])
    const out = lttb(d, 20)
    expect(out).toHaveLength(20)
    expect(out[0]).toEqual(d[0])
    expect(out[out.length - 1]).toEqual(d[d.length - 1])
  })
})

describe('color: ansi256 quantization', () => {
  it('maps pure colors into the cube and grays into the ramp', () => {
    expect(rgbToAnsi256([0, 0, 0])).toBe(16)
    expect(rgbToAnsi256([255, 255, 255])).toBe(231)
    expect(rgbToAnsi256([255, 0, 0])).toBe(196)
    expect(rgbToAnsi256([128, 128, 128])).toBeGreaterThanOrEqual(232)
  })

  it('quantize emits ansi256(n) at 256 depth and hex at truecolor', () => {
    expect(quantize('#ff0000', '256')).toMatch(/^ansi256\(\d+\)$/)
    expect(quantize('#ff0000', 'truecolor')).toBe('#ff0000')
  })
})

describe('caps: resolution + blitter selection', () => {
  it('capBlitter returns the safer (lower) rung', () => {
    expect(capBlitter('quad', 'braille')).toBe('quad')
    expect(capBlitter('braille', 'half')).toBe('half')
    expect(capBlitter('braille', 'braille')).toBe('braille')
  })

  it('pickBlitter: heatmap→half (truecolor), 16-color→1x1, fan→braille (when allowed)', () => {
    const tc: TerminalCaps = { blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none' }
    expect(pickBlitter('heatmap', tc)).toBe('half')
    expect(pickBlitter('fan', tc)).toBe('braille')
    expect(pickBlitter('heatmap', { blitterMax: 'quad', colorMode: '16', imageProtocol: 'none' })).toBe('1x1')
    // default ceiling caps fan down to quad
    expect(pickBlitter('fan', { blitterMax: 'quad', colorMode: 'truecolor', imageProtocol: 'none' })).toBe('quad')
  })

  it('resolveCaps honors HERMES_VIZ_BLITTER + COLORTERM (and explicit override)', () => {
    const prev = { ...process.env }

    try {
      delete process.env.NO_COLOR
      delete process.env.FORCE_COLOR
      process.env.COLORTERM = 'truecolor'
      process.env.HERMES_VIZ_BLITTER = 'braille'
      delete process.env.TMUX
      delete process.env.TERM_PROGRAM
      const caps = resolveCaps()
      expect(caps.colorMode).toBe('truecolor')
      expect(caps.blitterMax).toBe('braille')
      // tmux clamps truecolor → 256
      process.env.TMUX = '1'
      expect(resolveCaps().colorMode).toBe('256')
      // explicit override wins
      expect(resolveCaps({ colorMode: '16', blitterMax: '1x1' })).toEqual({ blitterMax: '1x1', colorMode: '16', imageProtocol: 'none' })
    } finally {
      process.env = prev
    }
  })
})

describe('CellBuffer: coalescing', () => {
  it('merges adjacent identical-style cells into one run', () => {
    const buf = new CellBuffer(4, 1)
    buf.setRow(0, [
      { fg: '#f00', t: '█' },
      { fg: '#f00', t: '█' },
      { fg: '#0f0', t: '█' },
      { t: ' ' }
    ])
    const [row] = buf.compile()
    expect(row!.map(r => r.text)).toEqual(['██', '█', ' '])
    expect(row![0]!.color).toBe('#f00')
  })

  it('worst case (all distinct) is bounded at cols runs', () => {
    const buf = new CellBuffer(96, 1)
    buf.setRow(0, Array.from({ length: 96 }, (_, i) => ({ fg: `#0000${(i % 99).toString().padStart(2, '0')}`, t: '▀' })))
    expect(buf.compile()[0]!.length).toBeLessThanOrEqual(96)
  })
})
