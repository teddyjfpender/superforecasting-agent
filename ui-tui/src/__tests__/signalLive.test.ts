import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import type * as SignalLive from '../lib/signalLive.js'

let signal: typeof SignalLive
let home: string
const previousHome = process.env.SUPERFORECASTING_AGENT_HOME

beforeAll(async () => {
  home = mkdtempSync(join(tmpdir(), 'signal-live-test-'))
  process.env.SUPERFORECASTING_AGENT_HOME = home
  signal = await import('../lib/signalLive.js')
})

afterAll(() => {
  rmSync(home, { recursive: true, force: true })

  if (previousHome === undefined) {delete process.env.SUPERFORECASTING_AGENT_HOME}
  else {process.env.SUPERFORECASTING_AGENT_HOME = previousHome}
})

// Isolate persistence before importing the singleton. A PID is not a unique
// persistent identity: process reuse can otherwise load an old duplicate.
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
    const { recordSignalMessage, signalCache, signalVersion, subscribeSignal } = signal
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
