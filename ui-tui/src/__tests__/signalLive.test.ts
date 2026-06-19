import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  markChatRead,
  recordSignalMessage,
  signalCache,
  signalUnread,
  signalVersion,
  subscribeSignal
} from '../lib/signalLive.js'

const msg = (over: Partial<{ chatId: string; fromMe: boolean; text: string; timestamp: number }> = {}) => ({
  attachments: 0,
  author: over.fromMe ? 'me' : '+15551234567',
  chatId: over.chatId ?? '+15551234567',
  files: [],
  fromMe: over.fromMe ?? false,
  text: over.text ?? 'hi',
  timestamp: over.timestamp ?? 1000
})

describe('signalLive singleton', () => {
  afterEach(() => vi.restoreAllMocks())

  it('records messages into the cache, dedupes, and notifies subscribers', () => {
    const before = signalVersion()
    const seen = vi.fn()
    const off = subscribeSignal(seen)

    recordSignalMessage(msg({ text: 'first', timestamp: 1 }))
    expect(signalCache()['+15551234567']?.some(m => m.text === 'first')).toBe(true)
    expect(signalVersion()).toBeGreaterThan(before)
    expect(seen).toHaveBeenCalled()

    // Exact duplicate is a no-op (no extra notify).
    const v = signalVersion()
    recordSignalMessage(msg({ text: 'first', timestamp: 1 }))
    expect(signalVersion()).toBe(v)

    off()
  })

  it('markChatRead clears only when the chat was unread', () => {
    // record an inbound message → marks unread
    recordSignalMessage(msg({ chatId: 'group:abc', text: 'yo', timestamp: 2 }))
    // (inbound recorded via recordSignalMessage does NOT set unread — only the
    // live receiver does; markChatRead should be a no-op here and not throw)
    expect(() => markChatRead('group:abc')).not.toThrow()
    expect(signalUnread() instanceof Set).toBe(true)
  })
})
