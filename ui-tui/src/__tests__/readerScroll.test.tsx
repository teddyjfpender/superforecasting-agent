import { PassThrough } from 'node:stream'

import { Box, render, ScrollBox, type ScrollBoxHandle, Text } from '@superforecasting/ink'
import React from 'react'
import { expect, it } from 'vitest'

it('keeps manual readers at the top through load and resize, preserving explicit scrolling', async () => {
  const stdout = new PassThrough()
  stdout.resume()
  Object.assign(stdout, { columns: 80, rows: 24, isTTY: true })
  const ref = React.createRef<ScrollBoxHandle>()

  const view = (lines: number, height = 10) => (
    <Box height={24} width={80}>
      <ScrollBox decstbm={false} flexDirection="column" followContent={false} height={height} ref={ref}>
        {Array.from({ length: lines }, (_, i) => (
          <Text key={i}>Article paragraph {i}</Text>
        ))}
      </ScrollBox>
    </Box>
  )

  const app = await render(view(2), { stdout, exitOnCtrlC: false, patchConsole: false })
  const tick = () => new Promise(resolve => setTimeout(resolve, 80))

  try {
    await tick()
    expect(ref.current?.getScrollTop()).toBe(0)
    app.rerender(view(80))
    await tick()
    expect(ref.current?.getScrollTop()).toBe(0)
    app.rerender(view(80, 6))
    await tick()
    expect(ref.current?.getScrollTop()).toBe(0)
    expect(ref.current?.getScrollHeight()).toBe(80)
    expect(ref.current?.getViewportHeight()).toBe(6)
    ref.current?.scrollBy(8)
    await tick()
    expect(ref.current?.getScrollTop()).toBe(8)
    app.rerender(view(100, 6))
    await tick()
    expect(ref.current?.getScrollTop()).toBe(8)
    ref.current?.scrollBy(-8)
    await tick()
    expect(ref.current?.getScrollTop()).toBe(0)
    ref.current?.scrollToBottom()
    await tick()
    expect(ref.current?.getScrollTop()).toBe(94)
    app.rerender(view(120, 5))
    await tick()
    expect(ref.current?.getScrollTop()).toBe(94)
    ref.current?.scrollTo(0)
    await tick()
    expect(ref.current?.getScrollTop()).toBe(0)
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
  }
})
