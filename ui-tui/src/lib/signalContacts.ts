import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'

// Persisted address book for the personal Signal client: the identity/label
// layer for each conversation — display name, number, and when it was added —
// keyed by chatId. signal-cli only resolves contact names while the daemon is
// reachable, so we save what we learn (and any number you start a chat with)
// here, so names survive restarts and offline sessions. Chat HISTORY is a
// separate concern (signal_cache.json).
//
// Stored at ~/.superforecasting-agent/signal_contacts.json — owner-only (0600)
// and written atomically (temp file + rename) so a crash mid-write can't leave
// a half-written/corrupt book.

export interface SavedContact {
  addedAt: number
  chatId: string
  name?: string
  number?: string
  /** Explicit user labels outrank later Signal profile updates. */
  nameSource?: 'local' | 'signal'
  aliases?: string[]
}

export type ContactBook = Record<string, SavedContact>

const contactsFile = (dir = forecastHomeDir()) => join(dir, 'signal_contacts.json')

// Keep only digits + a single leading '+', so "+1 (267) 455-3945" → "+12674553945".
export const normalizeNumber = (raw: string): string => {
  const cleaned = raw.trim().replace(/[^\d+]/g, '')
  const hasPlus = cleaned.startsWith('+')

  return (hasPlus ? '+' : '') + cleaned.replace(/\+/g, '')
}

// Signal recipients are E.164: a leading '+' and 7–15 digits.
export const isValidNumber = (raw: string): boolean =>
  /^[+\d() .-]+$/.test(raw.trim()) && /^\+\d{7,15}$/.test(normalizeNumber(raw))

export const loadContactBook = (path = contactsFile()): ContactBook => {
  try {
    const data: unknown = JSON.parse(readFileSync(path, 'utf8'))

    if (!data || typeof data !== 'object') {
      return {}
    }

    const out: ContactBook = {}

    for (const [chatId, value] of Object.entries(data as Record<string, unknown>)) {
      if (value && typeof value === 'object') {
        const c = value as Record<string, unknown>
        out[chatId] = {
          addedAt: typeof c.addedAt === 'number' ? c.addedAt : 0,
          chatId,
          name: typeof c.name === 'string' && c.name.trim() ? c.name : undefined,
          nameSource: c.nameSource === 'signal' ? 'signal' : 'local',
          aliases: Array.isArray(c.aliases) ? c.aliases.filter((v): v is string => typeof v === 'string') : [],
          number: typeof c.number === 'string' ? c.number : undefined
        }
      }
    }

    return out
  } catch {
    return {}
  }
}

export const saveContactBook = (book: ContactBook, path = contactsFile()): boolean => {
  try {
    const dir = dirname(path)

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    const tmp = `${path}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(book), { mode: 0o600 })
    renameSync(tmp, path)

    return true
  } catch {
    return false
  }
}

// Merge a contact in without dropping fields we already have (a later, unnamed
// sighting shouldn't wipe a saved name). Returns a new book.
export const upsertContact = (book: ContactBook, entry: Partial<SavedContact> & { chatId: string }): ContactBook => {
  const prev = book[entry.chatId]

  const preserveLocal =
    entry.nameSource === 'signal' && prev?.nameSource !== 'signal' && Boolean(prev?.name && prev.name !== prev.chatId)

  const name = preserveLocal ? prev?.name : entry.name?.trim() || prev?.name

  return {
    ...book,
    [entry.chatId]: {
      addedAt: prev?.addedAt ?? entry.addedAt ?? Date.now(),
      chatId: entry.chatId,
      name,
      nameSource: preserveLocal
        ? 'local'
        : entry.name?.trim()
          ? (entry.nameSource ?? 'local')
          : (prev?.nameSource ?? 'local'),
      aliases: entry.aliases ?? prev?.aliases,
      number: entry.number ?? prev?.number
    }
  }
}
