import { PassThrough } from 'stream'

import { Box, render, ScrollBox, type ScrollBoxHandle, Text } from '@hermes/ink'
import React, { useRef } from 'react'
import { describe, expect, it } from 'vitest'

import { useVirtualHistory } from '../hooks/useVirtualHistory.js'

// The transcript scroll interaction contract:
//
//   1. Scroll steps move the viewport by LINES — never snapping to message
//      boundaries. The historical mechanism for the snap: older messages mount
//      with ESTIMATED heights while scrolling up; the measurement pass then
//      corrects the height cache, offsets above the viewport shift, and the
//      same scrollTop suddenly shows different content — the view visually
//      re-anchors near a message top ("sticky" scroll). The fix is offset
//      compensation: when a measured correction lands fully above the viewport
//      top, scrollTop is adjusted by the same delta so the content under the
//      reader's eyes holds still.
//   2. While scrolled up, appends below (streaming) must not move the
//      viewport at all.
//   3. Returning to the bottom resumes follow mode (stick-to-bottom).
//   4. Position survives re-renders (no re-anchoring on memo breaks).

const writeStream = (columns: number, rows: number, isTTY = true) => {
  const stream = new PassThrough() as any
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (m: boolean) => (stream.isRaw = m),
    unref: () => stream
  })

  return stream
}

const tick = (ms = 50) => new Promise(r => setTimeout(r, ms))

// Every message is REALLY this many rows tall…
const REAL_H = 3
// …but the estimator thinks messages are 1 row tall, like the app's estimator
// being wrong about old, never-mounted messages in a resumed session.
const WRONG_ESTIMATE = 1

type Handle = { current: null | ScrollBoxHandle }
type HeightsRef = { current: null | ReadonlyMap<string, number> }

const makeItems = (count: number) => Array.from({ length: count }, (_, i) => ({ key: `m${i}` }))

const App = ({
  count,
  handle,
  heightsRef,
  version = 0
}: {
  count: number
  handle: Handle
  heightsRef: HeightsRef
  version?: number
}) => {
  const ref = useRef<null | ScrollBoxHandle>(null)
  const items = makeItems(count)
  const vh = useVirtualHistory(ref, items, 40, {
    estimate: WRONG_ESTIMATE,
    onHeightsChange: h => {
      heightsRef.current = h
    }
  })

  const mounted = items.slice(vh.start, vh.end)

  return React.createElement(
    Box,
    { flexDirection: 'column', height: 24 },
    React.createElement(
      ScrollBox,
      {
        flexDirection: 'column',
        flexGrow: 1,
        flexShrink: 1,
        ref: (el: ScrollBoxHandle | null) => {
          ref.current = el
          handle.current = el
        },
        stickyScroll: true
      },
      React.createElement(
        Box,
        { flexDirection: 'column' },
        vh.topSpacer > 0 ? React.createElement(Box, { height: vh.topSpacer, key: 'top' }) : null,
        ...mounted.map((it, i) =>
          React.createElement(
            Box,
            { flexDirection: 'column', height: REAL_H, key: it.key, ref: vh.measureRef(it.key) },
            React.createElement(Text, null, `R${vh.start + i}Q v${version}`)
          )
        ),
        vh.bottomSpacer > 0 ? React.createElement(Box, { height: vh.bottomSpacer, key: 'bot' }) : null
      )
    )
  )
}

const mount = async (count: number) => {
  const handle: Handle = { current: null }
  const heightsRef: HeightsRef = { current: null }

  const instance: any = await render(React.createElement(App, { count, handle, heightsRef }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: writeStream(40, 24, true),
    stdout: writeStream(40, 24)
  })
  await tick(120)

  return { handle, heightsRef, instance }
}

// True content-space position of the viewport top. scrollTop lives in the
// MIXED offset space (measured + estimated heights); the painted frame uses
// the same space, so mapping scrollTop -> (item, intra-item offset) and then
// re-expressing in real heights gives the content row the user actually sees.
const contentTopRow = (handle: Handle, heightsRef: HeightsRef, count: number): number => {
  const top = handle.current?.getScrollTop() ?? 0
  const h = heightsRef.current
  let off = 0

  for (let i = 0; i < count; i++) {
    const hi = h?.get(`m${i}`) ?? WRONG_ESTIMATE

    if (off + hi > top) {
      return i * REAL_H + (top - off)
    }

    off += hi
  }

  return count * REAL_H
}

describe('transcript scroll contract', () => {
  it('scroll-up steps move the viewport by the step size in content space (no boundary snap)', async () => {
    const COUNT = 120
    const { handle, heightsRef, instance } = await mount(COUNT)

    // Start pinned to the bottom (follow mode), like a live conversation.
    expect(handle.current?.isSticky()).toBe(true)

    // One wheel tick at a time (3 lines — the operator's wheel cadence).
    // Collect the visible content row at the viewport top after each step.
    // Enough steps to scroll PAST the initially-mounted (measured) tail into
    // history that only has estimated heights — that's where corrections fire.
    const STEP = 3
    const positions: number[] = [contentTopRow(handle, heightsRef, COUNT)]

    for (let i = 0; i < 40; i++) {
      handle.current?.scrollBy(-STEP)
      // eslint-disable-next-line no-await-in-loop
      await tick(60)
      positions.push(contentTopRow(handle, heightsRef, COUNT))
    }

    const deltas = positions.slice(1).map((p, i) => positions[i]! - p)

    // Every step moves the content under the viewport top UP by exactly the
    // step size. Without offset compensation the measured corrections of
    // freshly-mounted messages above shift the content back down, so steps
    // land short (or negative) and the view feels glued to message tops.
    expect(deltas).toEqual(Array(deltas.length).fill(STEP))

    instance.unmount?.()
  })

  it('holds the viewport absolutely still when messages are appended below', async () => {
    const COUNT = 100
    const { handle, heightsRef, instance } = await mount(COUNT)

    // Read somewhere in the middle (well inside the scroll range, so this
    // does NOT land at the bottom edge — landing at the bottom re-engages
    // follow mode by design).
    handle.current?.scrollTo(60)
    await tick(200)
    const before = contentTopRow(handle, heightsRef, COUNT)
    const topBefore = handle.current?.getScrollTop() ?? -1
    expect(handle.current?.isSticky()).toBe(false)

    // Stream in 30 more messages below.
    instance.rerender(
      React.createElement(App, {
        count: COUNT + 30,
        handle,
        heightsRef: heightsRef as HeightsRef
      })
    )
    await tick(150)

    expect(handle.current?.getScrollTop()).toBe(topBefore)
    expect(contentTopRow(handle, heightsRef, COUNT + 30)).toBe(before)

    instance.unmount?.()
  })

  it('returning to the bottom resumes follow mode for subsequent appends', async () => {
    const COUNT = 100
    const { handle, heightsRef, instance } = await mount(COUNT)

    handle.current?.scrollTo(120)
    await tick(100)
    expect(handle.current?.isSticky()).toBe(false)

    // Return to bottom.
    handle.current?.scrollToBottom()
    await tick(100)
    expect(handle.current?.isSticky()).toBe(true)

    // Appends now follow: scrollTop tracks the new max.
    instance.rerender(React.createElement(App, { count: COUNT + 20, handle, heightsRef: heightsRef as HeightsRef }))
    await tick(150)

    const vp = handle.current?.getViewportHeight() ?? 0
    const sh = handle.current?.getScrollHeight() ?? 0
    expect(handle.current?.isSticky()).toBe(true)
    expect(handle.current?.getScrollTop()).toBe(Math.max(0, sh - vp))

    instance.unmount?.()
  })

  it('scroll position survives re-renders (no re-anchoring on memo breaks)', async () => {
    const COUNT = 100
    const { handle, heightsRef, instance } = await mount(COUNT)

    handle.current?.scrollTo(150)
    await tick(100)
    const before = handle.current?.getScrollTop() ?? -1
    const contentBefore = contentTopRow(handle, heightsRef, COUNT)

    // Re-render the SAME content with a changed prop (memo break: every row's
    // text changes, forcing a full subtree re-render).
    for (let v = 1; v <= 3; v++) {
      instance.rerender(
        React.createElement(App, { count: COUNT, handle, heightsRef: heightsRef as HeightsRef, version: v })
      )
      // eslint-disable-next-line no-await-in-loop
      await tick(80)
    }

    expect(handle.current?.getScrollTop()).toBe(before)
    expect(contentTopRow(handle, heightsRef, COUNT)).toBe(contentBefore)

    instance.unmount?.()
  })
})
