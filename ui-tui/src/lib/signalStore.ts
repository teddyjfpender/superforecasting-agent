import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import type { SignalConfig, SignalMessage } from './signalClient.js'

// Config + persisted message cache for the personal Signal client.
//
// Config resolution order (shared with the gateway's Signal adapter):
//   1. SIGNAL_HTTP_URL / SIGNAL_ACCOUNT environment variables
//   2. ~/.superforecasting-agent/signal.json  ({ "httpUrl": "...", "account": "..." })
// signal-cli only streams messages from the moment we connect (no historical
// backfill), so we persist what we see + send to build conversation history
// across sessions.

const firstEnv = (names: string[]): string => {
  for (const name of names) {
    const v = process.env[name]?.trim()

    if (v) {
      return v
    }
  }

  return ''
}

export const signalConfigFile = (dir = forecastHomeDir()) => join(dir, 'signal.json')

export const resolveSignalConfig = (): null | SignalConfig => {
  let httpUrl = firstEnv(['SIGNAL_HTTP_URL', 'SUPERFORECASTING_AGENT_SIGNAL_HTTP_URL'])
  let account = firstEnv(['SIGNAL_ACCOUNT', 'SUPERFORECASTING_AGENT_SIGNAL_ACCOUNT'])

  if (!httpUrl || !account) {
    try {
      const data = JSON.parse(readFileSync(signalConfigFile(), 'utf8')) as Record<string, unknown>
      httpUrl = httpUrl || (typeof data.httpUrl === 'string' ? data.httpUrl : '')
      account = account || (typeof data.account === 'string' ? data.account : '')
    } catch {
      /* no config file */
    }
  }

  // Default the daemon URL to the conventional local port; the account (your
  // Signal number) is the only truly required value.
  httpUrl = httpUrl || 'http://127.0.0.1:8080'

  return account ? { account, httpUrl: httpUrl.replace(/\/+$/, '') } : null
}

export const saveSignalConfig = (cfg: SignalConfig, file = signalConfigFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, `${JSON.stringify(cfg, null, 2)}\n`, { mode: 0o600 })

    return true
  } catch {
    return false
  }
}

// Message cache: { [chatId]: SignalMessage[] } sorted ascending by timestamp.
export type SignalCache = Record<string, SignalMessage[]>

const MAX_PER_CHAT = 500
const cacheFile = (dir = forecastHomeDir()) => join(dir, 'signal_cache.json')

export const loadSignalCache = (file = cacheFile()): SignalCache => {
  try {
    const data: unknown = JSON.parse(readFileSync(file, 'utf8'))

    return data && typeof data === 'object' ? (data as SignalCache) : {}
  } catch {
    return {}
  }
}

export const saveSignalCache = (cache: SignalCache, file = cacheFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    const trimmed: SignalCache = {}

    for (const [chatId, msgs] of Object.entries(cache)) {
      trimmed[chatId] = msgs.slice(-MAX_PER_CHAT)
    }

    writeFileSync(file, JSON.stringify(trimmed), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}

// Append a message into the cache, de-duplicating on (timestamp, fromMe) so SSE
// echoes of our own sends don't double-up. Returns a new cache object.
export const appendMessage = (cache: SignalCache, msg: SignalMessage): SignalCache => {
  const existing = cache[msg.chatId] ?? []

  if (existing.some(m => m.timestamp === msg.timestamp && m.fromMe === msg.fromMe && m.text === msg.text)) {
    return cache
  }

  const next = [...existing, msg].sort((a, b) => a.timestamp - b.timestamp)

  return { ...cache, [msg.chatId]: next }
}
