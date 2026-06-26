import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

const mk = (cols: number, rows: number) => {
  const s = new PassThrough()
  Object.assign(s, { columns: cols, rows, isTTY: false })
  let out = ''
  s.on('data', (c) => {
    out += String(c)
  })
  return { s, text: () => out }
}

describe('ModalOverlay', () => {
  it('paints an absolute box with a title + content + footer over a body', async () => {
    const [{ Box, renderSync, Text }, { ModalOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/modalOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js'),
    ])
    const sink = mk(120, 40)
    // Mount like a real view: a sized body container with the overlay stacked last.
    const app = React.createElement(
      Box as never,
      { flexDirection: 'column', height: 40, width: 120 } as never,
      React.createElement(Text as never, { key: 'b' } as never, 'BODY ROW behind the modal'),
      React.createElement(
        ModalOverlay as never,
        { cols: 120, footerHint: 'Esc cancel', key: 'm', maxHeight: 12, rows: 40, t: DARK_THEME, title: 'Add data provider' } as never,
        React.createElement(Text as never, {} as never, 'a form field'),
      ),
    )
    renderSync(app, { exitOnCtrlC: false, patchConsole: false, stdout: sink.s } as never)
    const text = stripAnsi(sink.text())
    expect(text).toContain('BODY ROW behind the modal') // body stays visible
    expect(text).toContain('Add data provider')
    expect(text).toContain('a form field')
    expect(text).toContain('Esc cancel')
    expect(text).toMatch(/[╭╰]/) // the round border
  })
})
