import { PassThrough } from 'stream'

import { Box, render, ScrollBox, type ScrollBoxHandle, Text } from '@hermes/ink'
import React, { useRef } from 'react'
import { describe, expect, it } from 'vitest'

import { useVirtualHistory } from '../hooks/useVirtualHistory.js'
import { appendToolShelfMessage } from '../lib/liveProgress.js'
import { appendTranscriptMessage, upsert } from '../lib/messages.js'
import type { Msg } from '../types.js'

// APPEND-PATH HOLD AUDIT (companion to transcriptScrollContract).
//
// The operator's rule: while the user has scrolled UP to read history, an agent
// posting an update must NOT move the viewport and must NOT re-engage follow.
// c41fcfeaa proved this for streaming deltas; this file proves it for every
// OTHER append path, driving each through the REAL mutation function it uses in
// production against the REAL useVirtualHistory + ScrollBox:
//
//   P1 agent message completion / sys() / background-job & subagent-completion
//      notices           → appendTranscriptMessage (new row at the bottom)
//   P2 streaming message REPLACED by its taller final → upsert (last row grows)
//   P3 tool-progress lines merged into the current turn's tool shelf
//                         → appendToolShelfMessage (a bottom row grows)
//   LIVE-TAIL activity / subagent rows → the StreamingAssistant region grows at
//      the very bottom of the ScrollBox (modelled here as a growing tail box)
//   P4 an above-the-viewport row changes height (intro/session-info update)
//      → offset-compensated so the content under the reader holds
//
// Each parks the reader mid-history and asserts: scrollTop holds (or, for an
// above-viewport change, the CONTENT under the reader holds via compensation),
// and isSticky STAYS false (follow never silently re-engages).

const writeStream = (columns: number, rows: number, isTTY = true) => {
  const stream = new PassThrough() as any
  Object.assign(stream, {
    columns, isRaw: false, isTTY, rows,
    ref: () => stream,
    setRawMode: (m: boolean) => (stream.isRaw = m),
    unref: () => stream
  })
  return stream
}

const tick = (ms = 60) => new Promise(r => setTimeout(r, ms))

// Deterministic per-message heights so the geometry is exact. A "FINAL" message
// is taller than the streaming preview it replaces; a tool-trail grows with its
// tool count; the intro grows once session info populates it.
const REAL_H = 3
const heightFor = (m: Msg): number => {
  if (m.kind === 'intro') {
    return m.info ? 6 : 2
  }
  if (m.kind === 'trail' && m.tools?.length) {
    return 1 + m.tools.length
  }
  if (typeof m.text === 'string' && m.text.startsWith('FINAL')) {
    return 8
  }
  return REAL_H
}

type Handle = { current: null | ScrollBoxHandle }
type HeightsRef = { current: null | ReadonlyMap<string, number> }

// Identity keys, exactly like useMainApp's messageId: a msg keeps its key while
// its object identity is stable, and a REPLACED msg (new object) mints a new key
// — which is what makes an above-the-fold replace (intro regrow, streaming→final)
// rebuild the offsets in production. Index keys would falsely stabilize them.
let keySeq = 0
const keyOfMap = new WeakMap<Msg, string>()
const keyOf = (m: Msg): string => {
  let k = keyOfMap.get(m)
  if (!k) {
    k = `k${keySeq++}`
    keyOfMap.set(m, k)
  }
  return k
}

type OffsetsRef = { current: null | ArrayLike<number> }

// The message index + intra-item offset at the viewport top, computed in the
// HOOK's own offset space (its live `offsets`), so there is no virtual-vs-real
// drift: this is exactly where the painted viewport top lands. Holding it
// constant across an append == the reader's content did not move.
const topAt = (handle: Handle, offsetsRef: OffsetsRef): { index: number; intra: number } => {
  const top = handle.current?.getScrollTop() ?? 0
  const offs = offsetsRef.current
  if (!offs) {
    return { index: 0, intra: top }
  }
  for (let i = 0; i + 1 < offs.length; i++) {
    if (offs[i]! <= top && top < offs[i + 1]!) {
      return { index: i, intra: top - offs[i]! }
    }
  }
  return { index: Math.max(0, offs.length - 1), intra: 0 }
}

const App = ({
  handle,
  heightsRef,
  items,
  offsetsRef,
  tailH = 0
}: {
  handle: Handle
  heightsRef: HeightsRef
  items: Msg[]
  offsetsRef: OffsetsRef
  tailH?: number
}) => {
  const ref = useRef<null | ScrollBoxHandle>(null)
  const keyed = items.map(m => ({ key: keyOf(m) }))
  const vh = useVirtualHistory(ref, keyed, 40, {
    estimateHeight: i => heightFor(items[i]!),
    onHeightsChange: h => {
      heightsRef.current = h
    }
  })
  offsetsRef.current = vh.offsets
  const mounted = keyed.slice(vh.start, vh.end)

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
        ...mounted.map((it, i) => {
          const idx = vh.start + i
          return React.createElement(
            Box,
            { flexDirection: 'column', height: heightFor(items[idx]!), key: it.key, ref: vh.measureRef(it.key) },
            React.createElement(Text, null, `R${idx}`)
          )
        }),
        vh.bottomSpacer > 0 ? React.createElement(Box, { height: vh.bottomSpacer, key: 'bot' }) : null,
        // The live tail (StreamingAssistant) — a child at the very bottom of the
        // same ScrollBox. Activity / subagent / streaming rows grow it.
        tailH > 0
          ? React.createElement(Box, { flexDirection: 'column', height: tailH, key: 'tail' },
              React.createElement(Text, null, 'live tail'))
          : null
      )
    )
  )
}

const makeConversation = (turns: number): Msg[] => {
  const out: Msg[] = [{ info: { model: 'm' } as any, kind: 'intro', role: 'system', text: '' }]
  for (let i = 0; i < turns; i++) {
    out.push({ role: 'user', text: `question ${i}` })
    out.push({ role: 'assistant', text: `answer ${i} with a few words of body` })
  }
  return out
}

interface Ctx {
  handle: Handle
  heightsRef: HeightsRef
  instance: any
  offsetsRef: OffsetsRef
  show: (items: Msg[], tailH?: number) => void
}

const mount = async (items: Msg[]): Promise<Ctx> => {
  const handle: Handle = { current: null }
  const heightsRef: HeightsRef = { current: null }
  const offsetsRef: OffsetsRef = { current: null }
  const el = (its: Msg[], tailH = 0) =>
    React.createElement(App, { handle, heightsRef, items: its, offsetsRef, tailH })
  const instance: any = await render(el(items), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: writeStream(40, 24, true),
    stdout: writeStream(40, 24)
  })
  await tick(140)
  return { handle, heightsRef, instance, offsetsRef, show: (its, tailH) => instance.rerender(el(its, tailH)) }
}

// Park the reader at a mid-history reading position (NOT the bottom edge — that
// would legitimately re-engage follow). Returns the parked scrollTop + content.
const parkMidHistory = async (ctx: Ctx) => {
  const vp = ctx.handle.current?.getViewportHeight() ?? 0
  const sh = ctx.handle.current?.getScrollHeight() ?? 0
  expect(vp).toBeGreaterThan(0)
  expect(sh).toBeGreaterThan(vp)
  const target = Math.floor((sh - vp) / 2)
  ctx.handle.current?.scrollTo(target)
  await tick(160)
  expect(ctx.handle.current?.isSticky()).toBe(false)
  return {
    topAtBefore: topAt(ctx.handle, ctx.offsetsRef),
    topBefore: ctx.handle.current?.getScrollTop() ?? -1
  }
}

describe('append-path hold: a parked reader is never moved by an agent update', () => {
  it('P1 — appendTranscriptMessage (agent completion / sys / job & subagent notices) holds', async () => {
    const items = makeConversation(30)
    const ctx = await mount(items)
    const { topBefore, topAtBefore } = await parkMidHistory(ctx)

    // The agent finishes: its final message appends at the bottom. Also fire a
    // background-job sys() notice the same way — both use appendTranscriptMessage.
    let next = appendTranscriptMessage(items, { role: 'assistant', text: 'the final assistant answer arrives' })
    next = appendTranscriptMessage(next, { role: 'system', text: 'market model ready · open Markets' })
    ctx.show(next)
    await tick(150)

    expect(ctx.handle.current?.getScrollTop()).toBe(topBefore)
    expect(topAt(ctx.handle, ctx.offsetsRef)).toEqual(topAtBefore)
    expect(ctx.handle.current?.isSticky()).toBe(false)
    ctx.instance.unmount?.()
  })

  it('P2 — a streaming message REPLACED by its taller final (upsert) holds', async () => {
    const items = makeConversation(30)
    const ctx = await mount(items)
    const { topBefore, topAtBefore } = await parkMidHistory(ctx)

    // The last assistant row was a short streaming preview; it is replaced in
    // place by the taller final text (height grows at the bottom).
    const next = upsert(items, 'assistant', 'FINAL the complete assistant answer, several lines tall now')
    ctx.show(next)
    await tick(150)

    expect(ctx.handle.current?.getScrollTop()).toBe(topBefore)
    expect(topAt(ctx.handle, ctx.offsetsRef)).toEqual(topAtBefore)
    expect(ctx.handle.current?.isSticky()).toBe(false)
    ctx.instance.unmount?.()
  })

  it('P3 — tool-progress lines merged into the current turn shelf (appendToolShelfMessage) holds', async () => {
    // Seed a current-turn tool shelf at the bottom (a trail carrying one tool).
    const items = [
      ...makeConversation(30),
      { kind: 'trail', role: 'system', text: '', tools: [{ label: 'read', line: 'read a.ts' }] } as any
    ]
    const ctx = await mount(items)
    const { topBefore, topAtBefore } = await parkMidHistory(ctx)

    // More tool activity streams into the same shelf — the bottom trail grows.
    const shelf = { kind: 'trail', role: 'system', text: '', tools: [{ label: 'edit', line: 'edit a.ts' }] } as Msg
    const next = appendToolShelfMessage(items, shelf)
    // The merge must have grown the existing trail in place (not appended a row).
    expect(next.length).toBe(items.length)
    ctx.show(next)
    await tick(150)

    expect(ctx.handle.current?.getScrollTop()).toBe(topBefore)
    expect(topAt(ctx.handle, ctx.offsetsRef)).toEqual(topAtBefore)
    expect(ctx.handle.current?.isSticky()).toBe(false)
    ctx.instance.unmount?.()
  })

  it('LIVE-TAIL — activity / subagent / streaming rows grow the tail without moving the reader', async () => {
    const items = makeConversation(30)
    const ctx = await mount(items)
    const { topBefore, topAtBefore } = await parkMidHistory(ctx)

    // pushActivity / upsertSubagent / streaming deltas all render in the
    // StreamingAssistant region at the very bottom of the ScrollBox. Grow it.
    for (const h of [2, 5, 9]) {
      ctx.show(items, h)
      // eslint-disable-next-line no-await-in-loop
      await tick(120)
      expect(ctx.handle.current?.getScrollTop()).toBe(topBefore)
      expect(topAt(ctx.handle, ctx.offsetsRef)).toEqual(topAtBefore)
      expect(ctx.handle.current?.isSticky()).toBe(false)
    }
    ctx.instance.unmount?.()
  })

  it('P4 — an ABOVE-viewport row changing height is offset-compensated (content holds)', async () => {
    // A short intro (height 2). Scroll to the TOP first so the intro is mounted
    // and MEASURED (its key enters the height cache) — the production reality
    // where the intro rendered at least once. Then park deep in history and let
    // SESSION_INFO replace the intro with a taller one (height 6): the new object
    // mints a new key (useMainApp's messageId parity) and GC of the old, cached
    // key bumps the offset version, so the offsets ABOVE the parked reader
    // genuinely rebuild taller. Without the anchor compensation the reader shifts.
    const items: Msg[] = makeConversation(30)
    items[0] = { kind: 'intro', role: 'system', text: '' }
    const ctx = await mount(items)

    ctx.handle.current?.scrollTo(0)
    await tick(140)
    const { topAtBefore } = await parkMidHistory(ctx)

    const next = items.map(m => (m.kind === 'intro' ? { ...m, info: { model: 'm' } as any } : m))
    ctx.show(next)
    await tick(120)
    // Production parity: SESSION_INFO also patches $uiState, which re-renders
    // useMainApp a beat later — the render on which the GC-bumped offset version
    // actually rebuilds the offsets with the intro's new (taller) estimate. That
    // is the frame that would drag the reader without the anchor compensation.
    ctx.show(next)
    await tick(150)

    // The content under the reader holds absolutely still (scrollTop shifts by
    // the above-viewport delta; the item at the viewport top does not), and
    // follow does not re-engage.
    expect(topAt(ctx.handle, ctx.offsetsRef)).toEqual(topAtBefore)
    expect(ctx.handle.current?.isSticky()).toBe(false)
    ctx.instance.unmount?.()
  })
})
