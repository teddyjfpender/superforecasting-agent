import { stringWidth } from '@superforecasting/ink'
import { describe, expect, it } from 'vitest'

import {
  CellBuffer,
  type ChartMarker,
  type ChartTheme,
  diverging,
  encodeImage,
  encodeITerm2,
  encodeKitty,
  encodePng,
  encodeSixel,
  lastValueLabel,
  overlayMarkers,
  probeCaps,
  type ProbeTransport,
  type Raster,
  rasterizeHeatmap,
  renderCandles,
  renderFan,
  resolveCaps,
  sequential
} from '../../lib/viz/index.js'

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  gain: '#00cc66',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  loss: '#ff3344',
  muted: '#888888',
  up: '#ff0000'
}

const withEnv = (patch: Record<string, string | undefined>, fn: () => void): void => {
  const prev = { ...process.env }

  try {
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) {
        delete process.env[k]
      } else {
        process.env[k] = v
      }
    }

    fn()
  } finally {
    process.env = prev
  }
}

const smallRaster = (): Raster => ({
  height: 2,
  rgba: Uint8Array.from([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 0, 255]),
  width: 2
})

describe('caps: image-protocol detection (flag-gated)', () => {
  it('returns none unless HERMES_PIXEL_IMAGES is set', () => {
    withEnv({ HERMES_PIXEL_IMAGES: undefined, KITTY_WINDOW_ID: '1' }, () => {
      expect(resolveCaps().imageProtocol).toBe('none')
    })
  })

  it('detects kitty / iterm2 / sixel by env when enabled', () => {
    withEnv({ HERMES_PIXEL_IMAGES: '1', KITTY_WINDOW_ID: '1', ITERM_SESSION_ID: undefined, TERM: 'xterm-kitty', TERM_PROGRAM: undefined }, () =>
      expect(resolveCaps().imageProtocol).toBe('kitty')
    )
    withEnv({ HERMES_PIXEL_IMAGES: '1', KITTY_WINDOW_ID: undefined, TERM: 'xterm-256color', TERM_PROGRAM: 'iTerm.app' }, () =>
      expect(resolveCaps().imageProtocol).toBe('iterm2')
    )
    withEnv(
      { GHOSTTY_RESOURCES_DIR: undefined, HERMES_PIXEL_IMAGES: '1', ITERM_SESSION_ID: undefined, KITTY_WINDOW_ID: undefined, TERM: 'foot', TERM_PROGRAM: undefined },
      () => expect(resolveCaps().imageProtocol).toBe('sixel')
    )
  })

  it('does NOT assume plain xterm supports sixel (false-positive guard)', () => {
    withEnv(
      { GHOSTTY_RESOURCES_DIR: undefined, HERMES_PIXEL_IMAGES: '1', ITERM_SESSION_ID: undefined, KITTY_WINDOW_ID: undefined, TERM: 'xterm-256color', TERM_PROGRAM: undefined },
      () => expect(resolveCaps().imageProtocol).toBe('none')
    )
  })
})

describe('caps: async probeCaps (pure, mock transport)', () => {
  const mk = (resp: string): ProbeTransport => ({ read: async () => resp, write: () => undefined })

  it('parses DA1 sixel attribute and promotes blitter', async () => {
    await withEnvAsync({ HERMES_PIXEL_IMAGES: '1' }, async () => {
      const caps = await probeCaps(mk('\x1b[?62;4;9c'), 50)
      expect(caps.imageProtocol).toBe('sixel')
      expect(caps.blitterMax).toBe('braille')
    })
  })

  it('returns {} on timeout / no response', async () => {
    expect(await probeCaps(mk(''), 50)).toEqual({})
  })

  it('does NOT set sixel when HERMES_PIXEL_IMAGES is unset (gating holds)', async () => {
    await withEnvAsync({ HERMES_PIXEL_IMAGES: undefined }, async () => {
      expect(await probeCaps(mk('\x1b[?62;4;9c'), 50)).toEqual({})
    })
  })

  it('matches a zero-padded sixel attribute (04)', async () => {
    await withEnvAsync({ HERMES_PIXEL_IMAGES: '1' }, async () => {
      expect((await probeCaps(mk('\x1b[?62;04;9c'), 50)).imageProtocol).toBe('sixel')
    })
  })
})

// async env helper
async function withEnvAsync(patch: Record<string, string | undefined>, fn: () => Promise<void>): Promise<void> {
  const prev = { ...process.env }

  try {
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) {
        delete process.env[k]
      } else {
        process.env[k] = v
      }
    }

    await fn()
  } finally {
    process.env = prev
  }
}

describe('protocol: image encoders (pure)', () => {
  const r = smallRaster()

  it('encodeKitty frames raw RGBA with APC + dims', () => {
    const s = encodeKitty(r)
    expect(s.startsWith('\x1b_G')).toBe(true)
    expect(s).toContain('a=T,f=32,s=2,v=2')
    expect(s.endsWith('\x1b\\')).toBe(true)
  })

  it('encodeSixel frames a DCS with raster dims, palette, and ST', () => {
    const s = encodeSixel(r)
    expect(s.startsWith('\x1bP')).toBe(true)
    expect(s).toContain('"1;1;2;2')
    expect(s).toContain('#') // palette definitions
    expect(s.endsWith('\x1b\\')).toBe(true)
  })

  it('encodeITerm2 emits OSC 1337 with a real PNG payload', () => {
    const s = encodeITerm2(r)
    expect(s.startsWith('\x1b]1337;File=inline=1')).toBe(true)
    expect(s.endsWith('\x07')).toBe(true)
    const b64 = s.slice(s.indexOf(':') + 1, -1)
    const png = Buffer.from(b64, 'base64')
    expect([...png.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]) // PNG signature
  })

  it('encodePng produces a valid signature + IHDR-sized header', () => {
    const png = encodePng(r)
    expect([...png.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10])
    expect(png.length).toBeGreaterThan(33)
  })

  it('encodeImage dispatches and returns "" for none', () => {
    expect(encodeImage(r, 'kitty').startsWith('\x1b_G')).toBe(true)
    expect(encodeImage(r, 'none')).toBe('')
  })

  it('rasterizeHeatmap maps cells to colormap pixels', () => {
    const raster = rasterizeHeatmap([[0, 1]], sequential('#000000', '#ffffff'), { cellPx: 2 })
    expect(raster.width).toBe(4)
    expect(raster.height).toBe(2)
    expect(raster.rgba.length).toBe(4 * 2 * 4)
    expect([raster.rgba[0], raster.rgba[1], raster.rgba[2]]).toEqual([0, 0, 0]) // cell 0 → black
    const x2 = (0 * 4 + 2) * 4 // first pixel of cell 1
    expect([raster.rgba[x2], raster.rgba[x2 + 1], raster.rgba[x2 + 2]]).toEqual([255, 255, 255]) // cell 1 → white
  })
})

describe('annotate: overlayMarkers + lastValueLabel', () => {
  it('draws a dashed line + label on blank cells only, never clobbering data', () => {
    const buf = new CellBuffer(10, 5)
    buf.set(0, 2, '█', { color: '#fff' }) // pre-existing data on the marker row
    const markers: ChartMarker[] = [{ label: 'TGT', y: 50 }]
    overlayMarkers(buf, markers, () => 2, 10, 5, THEME)
    const row = buf.compile()[2]!.map(run => run.text).join('')
    expect(row[0]).toBe('█') // data preserved
    expect(row).toContain('╌') // dashed marker drawn
    expect(row).toContain('TGT') // right-aligned label
  })

  it('skips out-of-range markers', () => {
    const buf = new CellBuffer(10, 5)
    overlayMarkers(buf, [{ y: 1 }], () => 99, 10, 5, THEME)
    expect(buf.compile().every(r => r.every(run => !run.text.includes('╌')))).toBe(true)
  })

  it('wide-char label stays width-safe (drops width-2 glyphs, no desync)', () => {
    const buf = new CellBuffer(8, 3)
    overlayMarkers(buf, [{ label: '中文Test', y: 50 }], () => 1, 8, 3, THEME)
    const row = buf.compile()[1]!.map(run => run.text).join('')
    expect(stringWidth(row)).toBe(8) // exactly the plot width, no overflow/desync
    expect(stringWidth(row)).toBe([...row].length) // every cell width-1
  })

  it('lastValueLabel formats compactly', () => {
    expect(lastValueLabel(67000, '#fff').text).toBe('▸ 67k')
  })
})

describe('annotate: wired into charts', () => {
  it('fan renders threshold markers', () => {
    const median = Array.from({ length: 12 }, (_, i) => 0.4 + 0.2 * Math.sin(i / 3))
    const paths = [median.map(m => m + 0.05), median.map(m => m - 0.05)]
    const r = renderFan({ markers: [{ label: 'p50', y: 0.5 }], median, paths }, { caps: { blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none' }, height: 8, theme: THEME, width: 60 })
    expect(r.rows.map(row => row.map(x => x.text).join('')).join('\n')).toContain('╌')
  })

  it('candles renders a price reference line', () => {
    const candles = Array.from({ length: 16 }, (_, i) => {
      const o = 100 + Math.sin(i / 2) * 4
      const c = o + (i % 2 ? 1 : -1)

      return { c, h: Math.max(o, c) + 1, l: Math.min(o, c) - 1, o }
    })

    const r = renderCandles({ candles, markers: [{ label: 'support', y: 98 }] }, { caps: { blitterMax: 'quad', colorMode: 'truecolor', imageProtocol: 'none' }, height: 12, theme: THEME, width: 60 })
    expect(r.rows.map(row => row.map(x => x.text).join('')).join('\n')).toContain('╌')
  })
})
