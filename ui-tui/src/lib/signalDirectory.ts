/** Shared, profile-local address book. Never infer an identity from message content. */
import { atom } from 'nanostores'

import { listContacts, listGroups, type SignalConfig, signalRpc } from './signalClient.js'
import {
  type ContactBook,
  loadContactBook,
  saveContactBook,
  type SavedContact,
  upsertContact
} from './signalContacts.js'

export const $signalDirectory = atom(loadContactBook())
export const $signalDirectoryStatus = atom('')

export const persistDirectory = (book: ContactBook): boolean => {
  if (!saveContactBook(book)) {
    $signalDirectoryStatus.set('Could not save contacts. Check profile permissions.')

    return false
  }

  $signalDirectory.set(book)

  return true
}

export const saveDirectoryContact = (entry: Partial<SavedContact> & { chatId: string }): boolean =>
  persistDirectory(upsertContact($signalDirectory.get(), entry))

/** One request at a time; callers retain cached contacts on failure. */
let pending: Promise<void> | null = null
let owner = ''
let generation = 0

export const refreshSignalDirectory = (cfg: SignalConfig, sync = false): Promise<void> => {
  const key = `${cfg.httpUrl}|${cfg.account}`

  if (owner === key && pending) {
    return pending
  }

  owner = key
  const current = ++generation
  $signalDirectoryStatus.set(sync ? 'Requesting contacts from your phone…' : 'Refreshing contacts…')
  pending = (async () => {
    try {
      let warning = ''

      if (sync) {
        const result = await signalRpc(cfg, 'sendSyncRequest', { account: cfg.account })
        warning = result.error ? `Phone sync: ${result.error}` : ''
      }

      const [contacts, groups] = await Promise.all([listContacts(cfg), listGroups(cfg)])

      if (current !== generation) {
        return
      }

      let book = $signalDirectory.get()

      for (const c of contacts) {
        book = upsertContact(book, {
          chatId: c.id,
          name: c.name === c.id ? undefined : c.name,
          nameSource: 'signal',
          aliases: c.aliases
        })
      }

      for (const g of groups) {
        book = upsertContact(book, { chatId: `group:${g.id}`, name: g.name, nameSource: 'signal' })
      }

      if (persistDirectory(book)) {
        $signalDirectoryStatus.set(
          warning || (sync ? 'Sync requested; names refresh as your phone responds.' : 'Contacts refreshed')
        )
      }
    } catch (error) {
      if (current === generation) {
        $signalDirectoryStatus.set(
          `${error instanceof Error ? error.message : String(error)} · cached contacts retained`
        )
      }
    } finally {
      if (current === generation) {
        pending = null
      }
    }
  })()

  return pending
}

/** Ref-counted polling shared by the desk and all pickers; never one timer per modal. */
const watchers = new Map<string, { count: number; timer: ReturnType<typeof setInterval> }>()
const synced = new Set<string>()

export const watchSignalDirectory = (cfg: SignalConfig): (() => void) => {
  const key = `${cfg.httpUrl}|${cfg.account}`
  const existing = watchers.get(key)

  if (existing) {
    existing.count++
  } else {
    const sync = !synced.has(key)
    synced.add(key)
    void refreshSignalDirectory(cfg, sync)
    watchers.set(key, {
      count: 1,
      timer: setInterval(() => {
        void refreshSignalDirectory(cfg)
      }, 15000)
    })
  }

  let stopped = false

  return () => {
    if (stopped) {
      return
    }

    stopped = true
    const current = watchers.get(key)

    if (current && --current.count === 0) {
      clearInterval(current.timer)
      watchers.delete(key)
    }
  }
}
