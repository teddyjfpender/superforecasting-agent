import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { SignalMessage } from '../lib/signalClient.js'
import {
  appendMessage,
  loadSignalCache,
  resolveSignalConfig,
  saveSignalCache,
  saveSignalConfig,
  type SignalCache,
  signalConfigFile
} from '../lib/signalStore.js'

const tmp = mkdtempSync(join(tmpdir(), 'signal-store-'))
const prevHome = process.env.SUPERFORECASTING_AGENT_HOME
const prevAcct = process.env.SIGNAL_ACCOUNT
const prevUrl = process.env.SIGNAL_HTTP_URL

beforeEach(() => {
  process.env.SUPERFORECASTING_AGENT_HOME = tmp
  delete process.env.SIGNAL_ACCOUNT
  delete process.env.SIGNAL_HTTP_URL
})

afterEach(() => {
  delete process.env.SIGNAL_ACCOUNT
  delete process.env.SIGNAL_HTTP_URL
})

afterAll(() => {
  rmSync(tmp, { force: true, recursive: true })

  if (prevHome === undefined) {
    delete process.env.SUPERFORECASTING_AGENT_HOME
  } else {
    process.env.SUPERFORECASTING_AGENT_HOME = prevHome
  }

  if (prevAcct !== undefined) {
    process.env.SIGNAL_ACCOUNT = prevAcct
  }

  if (prevUrl !== undefined) {
    process.env.SIGNAL_HTTP_URL = prevUrl
  }
})

describe('resolveSignalConfig', () => {
  it('returns null when nothing is configured', () => {
    expect(resolveSignalConfig()).toBeNull()
  })

  it('reads env vars and defaults the daemon URL', () => {
    process.env.SIGNAL_ACCOUNT = '+15550000000'
    expect(resolveSignalConfig()).toEqual({ account: '+15550000000', httpUrl: 'http://127.0.0.1:8080' })
  })

  it('env URL overrides the default and trailing slash is trimmed', () => {
    process.env.SIGNAL_ACCOUNT = '+15550000000'
    process.env.SIGNAL_HTTP_URL = 'http://signal.local:9090/'
    expect(resolveSignalConfig()?.httpUrl).toBe('http://signal.local:9090')
  })

  it('falls back to the signal.json config file', () => {
    saveSignalConfig({ account: '+15551234567', httpUrl: 'http://127.0.0.1:8080' }, signalConfigFile(tmp))
    expect(resolveSignalConfig()).toEqual({ account: '+15551234567', httpUrl: 'http://127.0.0.1:8080' })
  })
})

describe('appendMessage', () => {
  const mk = (ts: number, fromMe: boolean, text: string): SignalMessage => ({
    attachments: 0,
    author: fromMe ? 'me' : '+1555',
    chatId: '+1555',
    fromMe,
    text,
    timestamp: ts
  })

  it('appends and keeps a chat sorted ascending by timestamp', () => {
    let cache: SignalCache = {}
    cache = appendMessage(cache, mk(3, false, 'c'))
    cache = appendMessage(cache, mk(1, false, 'a'))
    cache = appendMessage(cache, mk(2, true, 'b'))
    expect(cache['+1555'].map(m => m.text)).toEqual(['a', 'b', 'c'])
  })

  it('de-duplicates identical (timestamp, fromMe, text) echoes', () => {
    let cache: SignalCache = {}
    cache = appendMessage(cache, mk(5, true, 'hi'))
    const before = cache['+1555']
    cache = appendMessage(cache, mk(5, true, 'hi'))
    expect(cache['+1555']).toBe(before) // unchanged reference → no dupe
    expect(cache['+1555']).toHaveLength(1)
  })
})

describe('cache persistence', () => {
  it('round-trips through disk', () => {
    const file = join(tmp, 'sig_cache.json')

    const cache = appendMessage({}, {
      attachments: 0,
      author: '+1555',
      chatId: '+1555',
      fromMe: false,
      text: 'persisted',
      timestamp: 1
    })

    expect(saveSignalCache(cache, file)).toBe(true)
    expect(loadSignalCache(file)['+1555'][0].text).toBe('persisted')
  })
})
