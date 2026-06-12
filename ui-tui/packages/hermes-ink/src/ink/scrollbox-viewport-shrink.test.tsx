/**
 * Viewport-shrink follow: when a sibling below the ScrollBox grows (the chat
 * composer gaining a wrapped line, a status rule appearing), the scroll
 * viewport shrinks. If the content's bottom line was visible before the
 * shrink, it must STAY visible — previously the follow logic only re-pinned
 * on content growth, so the composer slid over the last transcript lines.
 */
import { EventEmitter } from 'events'
import React, { useRef } from 'react'
import { describe, expect, it } from 'vitest'

import Box from './components/Box.js'
import ScrollBox, { type ScrollBoxHandle } from './components/ScrollBox.js'
import Text from './components/Text.js'
import Ink from './ink.js'

class FakeTty extends EventEmitter {
  chunks: string[] = []
  columns = 40
  rows = 10
  isTTY = true

  write(chunk: string | Uint8Array, cb?: (err?: Error | null) => void): boolean {
    this.chunks.push(typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8'))
    cb?.()
    return true
  }
}

const tick = () => new Promise<void>(resolve => queueMicrotask(resolve))

const LINES = Array.from({ length: 20 }, (_, i) => `line-${i + 1}`)

const App = ({
  composerHeight,
  handle
}: {
  composerHeight: number
  handle: { current: null | ScrollBoxHandle }
}) => {
  const ref = useRef<null | ScrollBoxHandle>(null)
  handle.current = ref.current

  return (
    <Box flexDirection="column" height={10}>
      <ScrollBox flexDirection="column" flexGrow={1} flexShrink={1} ref={el => {
        ref.current = el
        handle.current = el
      }}>
        <Box flexDirection="column">
          {LINES.map(line => (
            <Text key={line}>{line}</Text>
          ))}
        </Box>
      </ScrollBox>
      <Box flexDirection="column" flexShrink={0} height={composerHeight}>
        <Text>composer</Text>
      </Box>
    </Box>
  )
}

const makeInk = () => {
  const stdout = new FakeTty()
  const stdin = new FakeTty()
  const stderr = new FakeTty()
  const ink = new Ink({
    exitOnCtrlC: false,
    patchConsole: false,
    stderr: stderr as unknown as NodeJS.WriteStream,
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream
  })

  ink.setAltScreenActive(true)
  return { ink, stdout }
}

describe('ScrollBox viewport-shrink follow', () => {
  it('keeps the bottom line visible when the composer grows (non-sticky, at bottom)', async () => {
    const { ink, stdout } = makeInk()
    const handle: { current: null | ScrollBoxHandle } = { current: null }

    ink.render(<App composerHeight={2} handle={handle} />)
    ink.onRender()
    await tick()

    // Land one line shy of the bottom via an imperative scroll — this breaks
    // the sticky flag without triggering the at-exact-bottom sticky restore,
    // putting us on the path that previously ignored viewport shrink.
    const beforeViewport = handle.current?.getViewportHeight() ?? 0
    const maxBefore = 20 - beforeViewport
    handle.current?.scrollTo(maxBefore - 1)
    ink.onRender()
    await tick()

    const beforeTop = handle.current?.getScrollTop() ?? -1
    expect(handle.current?.isSticky()).toBe(false)
    const bottomLineBefore = beforeTop + beforeViewport // last visible row index
    expect(bottomLineBefore).toBe(19) // line-19 is the bottom edge

    stdout.chunks = []
    ink.render(<App composerHeight={4} handle={handle} />)
    ink.onRender()
    await tick()

    const afterTop = handle.current?.getScrollTop() ?? -1
    const afterViewport = handle.current?.getViewportHeight() ?? 0
    expect(afterViewport).toBeLessThan(beforeViewport)
    // Bottom-stable: the same line stays at the bottom edge. (The painted
    // chunks are diff-optimized — only changed cells repaint — so the scroll
    // handle math is the assertion, not the output text.)
    expect(afterTop + afterViewport).toBe(bottomLineBefore)

    ink.unmount()
  })

  it('keeps the top stable when reading older history (bottom not visible)', async () => {
    const { ink } = makeInk()
    const handle: { current: null | ScrollBoxHandle } = { current: null }

    ink.render(<App composerHeight={2} handle={handle} />)
    ink.onRender()
    await tick()

    handle.current?.scrollTo(3) // mid-history; bottom (line-20) not visible
    ink.onRender()
    await tick()

    ink.render(<App composerHeight={4} handle={handle} />)
    ink.onRender()
    await tick()

    expect(handle.current?.getScrollTop()).toBe(3)

    ink.unmount()
  })
})
