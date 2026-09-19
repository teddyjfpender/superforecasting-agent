import { PassThrough } from 'stream'

import type { ScrollBoxHandle } from '@superforecasting/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

const mk = (cols: number, rows: number) => {
  const s = new PassThrough()
  Object.assign(s, { columns: cols, rows, isTTY: false })
  let out = ''
  s.on('data', c => {
    out += String(c)
  })

  return { s, text: () => out }
}

describe('ModalOverlay', () => {
  it('paints an absolute box with a title + content + footer over a body', async () => {
    const [{ Box, renderSync, Text }, { ModalOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/modalOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const sink = mk(120, 40)

    // Mount like a real view: a sized body container with the overlay stacked last.
    const app = (
      <Box flexDirection="column" height={40} width={120}>
        <Text>BODY ROW behind the modal</Text>
        <ModalOverlay
          cols={120}
          footerHint="Esc cancel"
          maxHeight={12}
          rows={40}
          t={DARK_THEME}
          title="Add data provider"
        >
          <Text>a form field</Text>
        </ModalOverlay>
      </Box>
    )

    renderSync(app, { exitOnCtrlC: false, patchConsole: false, stdout: sink.s })
    const text = stripAnsi(sink.text())
    expect(text).toContain('BODY ROW behind the modal') // body stays visible
    expect(text).toContain('Add data provider')
    expect(text).toContain('a form field')
    expect(text).toContain('Esc cancel')
    expect(text).toMatch(/[╭╰]/) // the round border
  })
})

it('bounds the scroll viewport and scrollbar after overscroll and content shrink', async () => {
  const [{ Box, render, Text }, { ModalOverlay }, { DARK_THEME }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/modalOverlay.js'),
    import('../theme.js')
  ])

  const sink = mk(100, 30)
  const scrollRef = React.createRef<ScrollBoxHandle>()

  const view = (count: number, tick: number) => (
    <Box height={30} width={100}>
      <ModalOverlay
        cols={100}
        footerHint="Esc close"
        maxHeight={12}
        rows={30}
        scrollRef={scrollRef}
        t={DARK_THEME}
        tick={tick}
        title="Help"
      >
        {Array.from({ length: count }, (_, i) => (
          <Text key={i}>Help row {i}</Text>
        ))}
      </ModalOverlay>
    </Box>
  )

  const app = await render(view(60, 0), { stdout: sink.s, patchConsole: false, exitOnCtrlC: false })
  const wait = () => new Promise(resolve => setTimeout(resolve, 80))

  try {
    await wait()
    expect(scrollRef.current?.getViewportHeight()).toBe(5)
    scrollRef.current?.scrollBy(10000)
    app.rerender(view(60, 1))
    await wait()
    expect(scrollRef.current?.getScrollTop()).toBeLessThanOrEqual(55)
    app.rerender(view(2, 2))
    await wait()
    expect(scrollRef.current?.getViewportHeight()).toBe(5)
    expect(scrollRef.current?.getScrollTop()).toBe(0)
  } finally {
    app.unmount()
    app.cleanup()
    sink.s.destroy()
  }
})

it.each([
  [80, 24],
  [120, 36],
  [180, 50],
  [40, 10],
  [24, 5],
  [16, 3]
])('keeps the exit hint visible within %s×%s with wide title text', async (cols, rows) => {
  const [{ Box, render, Text, stringWidth }, { ModalOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/modalOverlay.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const sink = mk(cols, rows)

  const app = await render(
    <Box height={rows} width={cols}>
      <ModalOverlay
        cols={cols}
        footerHint="Esc close"
        rows={rows}
        t={DARK_THEME}
        title={'市場資料 · é · 👩🏽‍💻 '.repeat(10)}
      >
        <Text>{'Long content '.repeat(50)}</Text>
      </ModalOverlay>
    </Box>,
    { stdout: sink.s, patchConsole: false, exitOnCtrlC: false }
  )

  try {
    await new Promise(resolve => setTimeout(resolve, 80))
    const output = stripAnsi(sink.text())
    expect(output).toContain('Esc close')
    expect(output).not.toContain('\uFFFD')
    expect(output.trimEnd().split('\n').length).toBeLessThanOrEqual(rows)

    for (const line of output.split('\n')) {
      expect(stringWidth(line)).toBeLessThanOrEqual(cols)
    }
  } finally {
    app.unmount()
    app.cleanup()
    sink.s.destroy()
  }
})
