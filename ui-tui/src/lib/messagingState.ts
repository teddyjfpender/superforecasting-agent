/** Profile-local desk state. Signal transport and message history remain separate. */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { atom } from 'nanostores'

import type { FeedShare } from '../protocol/generated.js'

import { forecastHomeDir } from './forecastHome.js'

export interface ChatState {
  archived?: boolean
  category?: string
  draft?: string
  pinned?: boolean
  readThrough?: number
  unread?: boolean
}
const file = () => join(forecastHomeDir(), 'messaging_desk.json')

export const loadMessagingState = (): Record<string, ChatState> => {
  try {
    const raw: unknown = JSON.parse(readFileSync(file(), 'utf8'))

    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      return {}
    }

    return Object.fromEntries(
      Object.entries(raw)
        .filter(([, v]) => v && typeof v === 'object')
        .map(([k, v]) => {
          const c = v as Record<string, unknown>

          return [
            k,
            {
              unread: c.unread === true,
              archived: c.archived === true,
              pinned: c.pinned === true,
              category: typeof c.category === 'string' ? c.category.slice(0, 80) : '',
              draft: typeof c.draft === 'string' ? c.draft : '',
              readThrough: typeof c.readThrough === 'number' && Number.isFinite(c.readThrough) ? c.readThrough : 0
            }
          ]
        })
    )
  } catch {
    return {}
  }
}

export const $chatState = atom(loadMessagingState())
export const $messagingStorageError = atom('')

export const updateChatState = (id: string, patch: Partial<ChatState>): boolean => {
  const next = { ...$chatState.get(), [id]: { ...$chatState.get()[id], ...patch } }

  try {
    const path = file()
    mkdirSync(dirname(path), { recursive: true })
    const tmp = `${path}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(next), { mode: 0o600 })
    renameSync(tmp, path)
    $chatState.set(next)
    $messagingStorageError.set('')

    return true
  } catch {
    $messagingStorageError.set('Could not save messaging state. Check profile permissions.')

    return false
  }
}

export interface ShareItem {
  chartUnavailable?: string
  feed?: FeedShare | null
  title: string
  text: string
}
export const $shareItem = atom<ShareItem | null>(null)
export const $quickMessage = atom<{ item: ShareItem | null } | null>(null)
export const openQuickMessage = () => $quickMessage.set({ item: $shareItem.get() })
