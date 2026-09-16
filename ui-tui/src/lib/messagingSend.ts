import { atom } from 'nanostores'

import { sendSignalMessage, type SignalConfig } from './signalClient.js'
import { recordSignalMessage } from './signalLive.js'

// One send owner for inbox and quick compose. Never retry an ambiguous network failure.
const pending = new Set<string>()
export interface SendAttempt {
  text: string
  startedAt: number
  status: 'sending' | 'uncertain'
  error?: string
}
export const $messageSendAttempts = atom<Record<string, SendAttempt>>({})
export const messageSendKey = (cfg: SignalConfig, chatId: string): string => `${cfg.account}:${chatId}`

const setAttempt = (key: string, attempt?: SendAttempt): void => {
  const next = { ...$messageSendAttempts.get() }

  if (attempt) {
    next[key] = attempt
  } else {
    delete next[key]
  }

  $messageSendAttempts.set(next)
}

export const sendDeskMessage = async (cfg: SignalConfig, chatId: string, text: string): Promise<string | null> => {
  const key = messageSendKey(cfg, chatId)

  if (!text.trim()) {
    return 'Write a message first.'
  }

  if (pending.has(key)) {
    return 'A message is already sending to this conversation.'
  }

  pending.add(key)
  const attempt: SendAttempt = { text: text.trim(), startedAt: Date.now(), status: 'sending' }
  setAttempt(key, attempt)

  const uncertain = (error: string): string => {
    setAttempt(key, { ...attempt, status: 'uncertain', error })

    return error
  }

  try {
    const { error, timestamp } = await sendSignalMessage(cfg, chatId, text.trim())

    if (error) {
      return uncertain(`${error}. Delivery unconfirmed; check the conversation before retrying.`)
    }

    recordSignalMessage({
      attachments: 0,
      author: 'me',
      chatId,
      files: [],
      fromMe: true,
      text: text.trim(),
      timestamp: timestamp || Date.now()
    })

    setAttempt(key)

    return null
  } catch (error) {
    return uncertain(`${String(error)}. Delivery unconfirmed; check before retrying.`)
  } finally {
    pending.delete(key)
  }
}
