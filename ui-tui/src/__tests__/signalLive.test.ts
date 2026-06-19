import { describe, expect, it } from 'vitest'

import { recordSignalMessage, signalCache, signalVersion, subscribeSignal } from '../lib/signalLive.js'

// The receiver is a module-level singleton, so use a chatId unique to this run
// to stay isolated from any other test that touches the same store.
const CHAT = `test:signal-live:${process.pid}`

const msg = (text: string, timestamp: number) => ({
  attachments: 0,
  author: '+15550000000',
  chatId: CHAT,
  files: [],
  fromMe: false,
  text,
  timestamp
})

describe('signalLive singleton', () => {
  it('records messages, dedupes exact repeats, and notifies subscribers', () => {
    const before = signalVersion()
    const seen: number[] = []
    const off = subscribeSignal(() => seen.push(signalVersion()))

    recordSignalMessage(msg('first', 1))
    const chat = () => signalCache()[CHAT] ?? []
    expect(chat().some(m => m.text === 'first')).toBe(true)
    expect(signalVersion()).toBeGreaterThan(before)
    expect(seen.length).toBeGreaterThan(0)

    // Exact duplicate does not grow the chat (deduped).
    const len = chat().length
    recordSignalMessage(msg('first', 1))
    expect(chat().length).toBe(len)

    // A genuinely new message does append.
    recordSignalMessage(msg('second', 2))
    expect(chat().length).toBe(len + 1)

    off()
  })
})
