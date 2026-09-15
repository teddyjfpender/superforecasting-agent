// App-level Signal receiver — a single always-on subscription that owns the
// message cache and unread set for the whole TUI.
//
// Why a singleton: signal-cli's daemon delivers each received message over the
// SSE stream to whoever is connected AT THAT MOMENT, then ACKs it to the server
// (so it is never re-sent). If the only SSE consumer lived inside the Messaging
// view, every message that arrived while you were on another screen — or while
// the view was remounting — would be emitted to no one and lost forever. So the
// receiver is hoisted here, started once at app startup, and runs for the life
// of the TUI regardless of the active view. The Messaging view reads from this
// store and subscribes for re-renders; it no longer opens its own stream (which
// also removes a cache write-race between two owners).

import { $chatState, $messagingStorageError, updateChatState } from './messagingState.js'
import { openReceiveStream, type SignalConfig, type SignalMessage } from './signalClient.js'
import { appendMessage, loadSignalCache, saveSignalCache, type SignalCache } from './signalStore.js'

type Listener = () => void

let cache: SignalCache = loadSignalCache()
let version = 0

let unread = new Set(
  Object.entries($chatState.get())
    .filter(([, state]) => state.unread)
    .map(([id]) => id)
)

let connected = false
let stop: null | (() => void) = null
let currentUrl = ''
let receiverGeneration = 0
const listeners = new Set<Listener>()

const notify = (): void => {
  version += 1

  for (const listener of listeners) {
    listener()
  }
}

export const signalCache = (): SignalCache => cache
export const signalVersion = (): number => version
export const signalUnread = (): Set<string> => unread
export const signalConnected = (): boolean => connected

export const subscribeSignal = (listener: Listener): (() => void) => {
  listeners.add(listener)

  return () => {
    listeners.delete(listener)
  }
}

export const markChatRead = (chatId: string): void => {
  if (unread.has(chatId)) {
    const through = Math.max(0, ...(cache[chatId] ?? []).map(m => m.timestamp))

    if (!updateChatState(chatId, { readThrough: through, unread: false })) {
      return
    }

    unread = new Set(unread)
    unread.delete(chatId)
    notify()
  }
}

// Record a message locally (outbound sends / optimistic echo). Persisted +
// broadcast; deduped by appendMessage so a later inbound copy is a no-op.
export const recordSignalMessage = (msg: SignalMessage): void => {
  const next = appendMessage(cache, msg)

  if (next !== cache) {
    cache = next

    if (!saveSignalCache(cache)) {
      $messagingStorageError.set('Messages are visible but could not be saved. Check profile permissions.')
    }

    notify()
  }
}

// Start (or re-target) the single receive stream. Idempotent: a no-op if it is
// already streaming from the same daemon URL; switches cleanly when the daemon
// URL changes (e.g. after a daemon restart).
export const startSignalReceiver = (cfg: null | SignalConfig): void => {
  if (!cfg) {
    return
  }

  if (stop && currentUrl === `${cfg.httpUrl}|${cfg.account}`) {
    return
  }

  const generation = ++receiverGeneration
  stop?.()
  currentUrl = `${cfg.httpUrl}|${cfg.account}`
  stop = openReceiveStream(
    cfg,
    msg => {
      if (generation !== receiverGeneration) {
        return
      }

      const next = appendMessage(cache, msg)

      if (next === cache) {
        return // duplicate
      }

      cache = next

      if (!msg.fromMe) {
        unread = new Set(unread).add(msg.chatId)
        updateChatState(msg.chatId, { unread: true })
      }

      if (!saveSignalCache(cache)) {
        $messagingStorageError.set('Messages are visible but could not be saved. Check profile permissions.')
      }

      notify()
    },
    isConnected => {
      if (generation !== receiverGeneration) {
        return
      }

      if (isConnected !== connected) {
        connected = isConnected
        notify()
      }
    }
  )
}

export const stopSignalReceiver = (): void => {
  receiverGeneration += 1
  stop?.()
  stop = null
  currentUrl = ''
  connected = false
  notify()
}
