import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

// Render smoke test: the <Chart> React layer mounts a heatmap + a fan to a real
// Ink frame without crashing, emits the expected glyphs, and (the bleed guard)
// resets SGR after colored runs so background colors don't leak down the screen.

const ESC = String.fromCharCode(27)

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & Record<string, unknown>
  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (m: boolean) => {
      stream.isRaw = m
    },
    unref: () => stream
  })
  stream.on('data', c => {
    output += c.toString()
  })

  return { stream, text: () => output }
}

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const renderChart = async (props: Record<string, unknown>) => {
  process.env.FORECAST_TUI_INLINE = '1'
  process.env.HERMES_VIZ_BLITTER = 'braille'

  const [{ render }, { DARK_THEME }, { Chart }] = await Promise.all([
    import('@hermes/ink'),
    import('../../theme.js'),
    import('../../components/viz/Chart.js')
  ])

  const stdout = writeStream(110, 40)
  const stdin = writeStream(110, 40, true)

  const instance = render(React.createElement(Chart, { t: DARK_THEME, ...props } as never), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: stdin.stream,
    stdout: stdout.stream
  })

  await tick(40)
  const raw = stdout.text()
  instance.unmount?.()

  return raw
}

afterEach(() => {
  delete process.env.FORECAST_TUI_INLINE
  delete process.env.HERMES_VIZ_BLITTER
})

describe('Chart render (Ink)', () => {
  it('heatmap mounts, emits half-blocks, and resets SGR (no color bleed)', async () => {
    const matrix = [
      [1, -0.5, 0.2],
      [-0.5, 1, -0.3],
      [0.2, -0.3, 1]
    ]

    const raw = await renderChart({ data: { diverging: true, matrix, type: 'heatmap' }, kind: 'heatmap', width: 60 })
    expect(raw).toContain('▀') // half-block flagship glyph

    // Background color set (CSI 48;...) must be accompanied by a reset (CSI 0m / 49m)
    if (raw.includes('48;')) {
      expect(raw.includes(`${ESC}[0m`) || raw.includes(`${ESC}[49m`) || raw.includes(`${ESC}[39;49m`)).toBe(true)
    }
  })

  it('fan with paths mounts and emits braille', async () => {
    const median = Array.from({ length: 20 }, (_, i) => 0.5 + 0.2 * Math.sin(i / 4))
    const paths = Array.from({ length: 6 }, (_, k) => median.map((m, i) => m + (k - 3) * 0.02 * (i + 1)))
    const bands = [{ lower: median.map(m => m - 0.1), upper: median.map(m => m + 0.1) }]
    const raw = await renderChart({ data: { bands, median, paths, type: 'fan' }, height: 8, kind: 'fan', width: 60 })
    expect([...raw].some(c => c.codePointAt(0)! >= 0x2800 && c.codePointAt(0)! <= 0x28ff)).toBe(true)
  })
})
