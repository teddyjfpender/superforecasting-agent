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
    import('@hermes/ink'),
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

describe('OutriderHeader', () => {
  it('renders half-block art tinted with truecolor', async () => {
    const text = await render(100, 40)
    // Half-block glyphs (the 2x-vertical-resolution renderer)
    expect(/[▀▄]/.test(text)).toBe(true)
    // 24-bit truecolor foreground escapes (theme-tinted)
    expect(/\x1b\[38;2;\d+;\d+;\d+m/.test(text)).toBe(true)
  })

  it('scales down to a narrow terminal without crashing', async () => {
    const text = await render(46, 22)
    expect(/[▀▄]/.test(text)).toBe(true)
  })
})
