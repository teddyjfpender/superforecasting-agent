import { describe, expect, it } from 'vitest'

import { GROUP_GAP_MS, messageHeaders } from '../components/messagingView.js'

const m = (fromMe: boolean, timestamp: number, author?: string) => ({ author, fromMe, timestamp })

describe('messageHeaders (chat grouping)', () => {
  it('shows a header on the first message', () => {
    expect(messageHeaders([m(true, 0)])).toEqual([true])
  })

  it('groups consecutive same-sender messages within the gap', () => {
    const msgs = [m(false, 0, 'dylan'), m(false, 1000, 'dylan'), m(false, 2000, 'dylan')]
    expect(messageHeaders(msgs)).toEqual([true, false, false])
  })

  it('breaks the group when the sender changes', () => {
    const msgs = [m(false, 0, 'dylan'), m(true, 1000), m(false, 2000, 'dylan')]
    expect(messageHeaders(msgs)).toEqual([true, true, true])
  })

  it('breaks the group after a >5min gap from the same sender', () => {
    const msgs = [m(false, 0, 'dylan'), m(false, GROUP_GAP_MS + 1, 'dylan')]
    expect(messageHeaders(msgs)).toEqual([true, true])
  })

  it('distinguishes different authors in a group chat', () => {
    const msgs = [m(false, 0, 'dylan'), m(false, 1000, 'avihu')]
    expect(messageHeaders(msgs)).toEqual([true, true])
  })

  it('outgoing runs group regardless of author', () => {
    expect(messageHeaders([m(true, 0), m(true, 1000), m(true, 2000)])).toEqual([true, false, false])
  })
})
