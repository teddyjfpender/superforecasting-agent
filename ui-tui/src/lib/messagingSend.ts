import { sendSignalMessage, type SignalConfig } from './signalClient.js'
import { recordSignalMessage } from './signalLive.js'

// One send owner for inbox and quick compose. Never retry an ambiguous network failure.
const pending = new Set<string>()

export const sendDeskMessage = async (cfg: SignalConfig, chatId: string, text: string): Promise<string | null> => {
  const key = `${cfg.account}:${chatId}`

  if (!text.trim()) {
    return 'Write a message first.'
  }

  if (pending.has(key)) {
    return 'A message is already sending to this conversation.'
  }

  pending.add(key)

  try {
    const { error, timestamp } = await sendSignalMessage(cfg, chatId, text.trim())

    if (error) {
      return `${error}. Delivery may be uncertain; check the conversation before retrying.`
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

    return null
  } catch (error) {
    return `${String(error)}. Check delivery before retrying.`
  } finally {
    pending.delete(key)
  }
}
