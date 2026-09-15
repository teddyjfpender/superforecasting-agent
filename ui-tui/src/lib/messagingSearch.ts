/** Private, deterministic intent search: names first, then labels and saved history.
 * No contact data or messages leave the profile to build this index.
 */
import type { ChatState } from './messagingState.js'
import type { ContactBook } from './signalContacts.js'
import type { SignalCache } from './signalStore.js'

export const DIRECTORY_SCOPES = ['All', 'Contacts', 'Chats', 'Groups', 'Unread', 'Pinned'] as const
export type DirectoryScope = (typeof DIRECTORY_SCOPES)[number]
export interface DirectoryResult {
  id: string
  name: string
  aliases: string[]
  category: string
  count: number
  snippet: string
  score: number
  lastTs: number
  unread: boolean
  pinned: boolean
}
const normalize = (value: string) => value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase()
const tokens = (value: string) => normalize(value).match(/[\p{L}\p{N}+]+/gu) ?? []

const concepts = [
  ['meeting', 'meet', 'call', 'catchup', 'appointment'],
  ['economy', 'economics', 'economic', 'macro'],
  ['inflation', 'cpi', 'prices'],
  ['stocks', 'equities', 'shares'],
  ['weather', 'storm', 'rain', 'hurricane'],
  ['travel', 'flight', 'trip', 'holiday'],
  ['family', 'relatives'],
  ['work', 'office', 'colleagues'],
  ['document', 'docs', 'report', 'paper'],
  ['unread', 'new'],
  ['group', 'groups'],
  ['pinned', 'favorite', 'favourite']
]

const variants = (word: string) => concepts.find(group => group.includes(word)) ?? [word]

const near = (a: string, b: string): boolean => {
  if (a.length < 4 || b.length < 4 || Math.abs(a.length - b.length) > 1) {
    return false
  }

  let i = 0,
    j = 0,
    errors = 0

  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i++
      j++

      continue
    }

    if (++errors > 1) {
      return false
    }

    if (a.length >= b.length) {
      i++
    }

    if (b.length >= a.length) {
      j++
    }
  }

  return errors + (a.length - i) + (b.length - j) <= 1
}

export function searchDirectory(
  book: ContactBook,
  cache: SignalCache,
  state: Record<string, ChatState>,
  query: string,
  scope: DirectoryScope = 'All'
): DirectoryResult[] {
  const words = tokens(query).filter(
    word => !['who', 'about', 'mentioned', 'discussed', 'the', 'a', 'an', 'with', 'find', 'show', 'me'].includes(word)
  )

  return [...new Set([...Object.keys(book), ...Object.keys(cache), ...Object.keys(state)])]
    .flatMap(id => {
      const messages = cache[id] ?? []
      const meta = state[id] ?? {}
      const group = id.startsWith('group:')

      if (
        (scope === 'Contacts' && group) ||
        (scope === 'Groups' && !group) ||
        (scope === 'Chats' && !messages.length) ||
        (scope === 'Unread' && !meta.unread) ||
        (scope === 'Pinned' && !meta.pinned)
      ) {
        return []
      }

      const name = book[id]?.name || id
      const aliases = book[id]?.aliases ?? []
      const names = normalize([name, ...aliases].join(' '))

      const context = normalize(
        [meta.category, group ? 'group' : 'contact', meta.unread ? 'unread' : '', meta.pinned ? 'pinned' : ''].join(' ')
      )

      const history = messages.map(m => normalize(m.text))
      let score = 0
      let match = -1

      for (const word of words) {
        if (
          names.includes(word) ||
          normalize(id).includes(word) ||
          (/^\+?\d+$/.test(word) && id.replace(/\D/g, '').includes(word.replace('+', '')))
        ) {
          score += 20

          continue
        }

        if (tokens(names).some(n => near(n, word))) {
          score += 8

          continue
        }

        const expanded = variants(word)

        if (expanded.some(w => context.includes(w))) {
          score += 6

          continue
        }

        let found = -1

        for (let i = history.length - 1; i >= 0; i--) {
          if (expanded.some(w => tokens(history[i]).some(t => t.startsWith(w)))) {
            found = i

            break
          }
        }

        if (found < 0) {
          return []
        } // every term must contribute, not just one common word

        score += 2
        match = Math.max(match, found)
      }

      if (query.trim() && normalize(name) === normalize(query.trim())) {
        score += 100
      }

      const last = messages.at(-1)

      return [
        {
          id,
          name,
          aliases,
          category: meta.category || '',
          count: messages.length,
          snippet: (match >= 0 ? messages[match]?.text : last?.text) || '',
          score,
          lastTs: last?.timestamp || 0,
          unread: Boolean(meta.unread),
          pinned: Boolean(meta.pinned)
        }
      ]
    })
    .sort(
      (a, b) =>
        b.score - a.score || Number(b.pinned) - Number(a.pinned) || b.lastTs - a.lastTs || a.name.localeCompare(b.name)
    )
}
