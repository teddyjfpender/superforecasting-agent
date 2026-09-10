import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

const writeStream = (columns: number, rows: number) => {
  const s = new PassThrough() as PassThrough & { columns: number; isTTY: boolean; rows: number }
  let out = ''
  Object.assign(s, { columns, isTTY: false, rows })
  s.on('data', c => (out += c.toString()))

  return { s, text: () => out }
}

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const render = async (cols: number, rows: number) => {
  process.env.FORCE_COLOR = '3' // emit 24-bit color in the headless test harness

  const [{ render: inkRender }, { OutriderHeader }, { DARK_THEME }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/outriderHeader.js'),
    import('../theme.js')
  ])

  const stdout = writeStream(cols, rows)
  const stdin = writeStream(cols, rows)

  const inst = inkRender(React.createElement(OutriderHeader, { t: DARK_THEME }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: stdin.s,
    stdout: stdout.s
  })

  await tick(40)
  const text = stdout.text()
  inst.unmount?.()
  inst.cleanup?.()

  return text
}

// Any block-element / sub-cell glyph: classic blocks, sextants (U+1FB00), the
// quarter-band blocks (U+1FB82/85), and Unicode-16 octants (U+1CD00…).
const BLOCK_GLYPH = /[▀-▟\u{1fb00}-\u{1fb3b}\u{1fb82}\u{1fb85}\u{1cd00}-\u{1cdeb}]/u
// Built via constructor so the ESC byte isn't a control char in a regex literal.
const TRUECOLOR = new RegExp(`${String.fromCharCode(27)}\\[38;2;\\d+;\\d+;\\d+m`)

describe('OutriderHeader', () => {
  it('renders sub-cell block art tinted with truecolor', async () => {
    const text = await render(100, 40)
    expect(BLOCK_GLYPH.test(text)).toBe(true)
    // 24-bit truecolor foreground escapes (theme-tinted)
    expect(TRUECOLOR.test(text)).toBe(true)
  })

  it('uses sextant glyphs at the default density', async () => {
    const text = await render(100, 40)
    // Default family is sextant (compat-first) — at least some cells should
    // land on a glyph in the U+1FB00 sextant range.
    expect(/[\u{1fb00}-\u{1fb3b}]/u.test(text)).toBe(true)
  })

  it('scales down to a narrow terminal without crashing', async () => {
    const text = await render(46, 22)
    expect(BLOCK_GLYPH.test(text)).toBe(true)
  })
})
