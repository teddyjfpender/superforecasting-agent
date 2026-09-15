import { useStore } from '@nanostores/react'
import { Box, Text, useInput } from '@superforecasting/ink'
import { useEffect, useMemo, useState } from 'react'

import { $overlayState } from '../app/overlayStore.js'
import { DIRECTORY_SCOPES, type DirectoryScope, searchDirectory } from '../lib/messagingSearch.js'
import { $chatState } from '../lib/messagingState.js'
import { isValidNumber, normalizeNumber } from '../lib/signalContacts.js'
import {
  $signalDirectory,
  $signalDirectoryStatus,
  refreshSignalDirectory,
  watchSignalDirectory
} from '../lib/signalDirectory.js'
import { signalCache, subscribeSignal } from '../lib/signalLive.js'
import { resolveSignalConfig } from '../lib/signalStore.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

/** The same browse/search/select interaction for opening chats and addressing messages. */
export function ContactPicker({
  cols,
  rows,
  t,
  onSelect,
  onCancel,
  onNewGroup,
  contactsOnly = false,
  title = 'FIND CONTACT OR CHAT'
}: {
  cols: number
  rows: number
  t: Theme
  onSelect: (id: string) => void
  onCancel: () => void
  onNewGroup?: () => void
  contactsOnly?: boolean
  title?: string
}) {
  const book = useStore($signalDirectory)
  const state = useStore($chatState)
  const status = useStore($signalDirectoryStatus)
  const overlay = useStore($overlayState)
  const blocked = overlay.palette || overlay.cheatSheet
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<DirectoryScope>(contactsOnly ? 'Contacts' : 'All')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [cache, setCache] = useState(signalCache())
  useEffect(() => subscribeSignal(() => setCache(signalCache())), [])
  useEffect(() => {
    const cfg = resolveSignalConfig()

    if (cfg) {
      return watchSignalDirectory(cfg)
    }
  }, [])
  const scopes = contactsOnly ? (['Contacts'] as const) : DIRECTORY_SCOPES

  const results = [
    ...useMemo(() => searchDirectory(book, cache, state, query, scope), [book, cache, state, query, scope])
  ]

  const number = isValidNumber(query) ? normalizeNumber(query) : ''

  if (number && !results.some(r => r.id === number)) {
    // A new explicit phone number is selectable, never a guessed name/identity.
    results.push({
      id: number,
      name: number,
      aliases: [],
      category: '',
      count: 0,
      snippet: '',
      score: 0,
      lastTs: 0,
      unread: false,
      pinned: false
    })
  }

  const index = Math.max(
    0,
    results.findIndex(r => r.id === selectedId)
  )

  const active = results[index]
  const scopeIndex = scopes.indexOf(scope as never)
  const height = Math.max(8, Math.min(rows - 6, 34))
  const bodyRows = Math.max(1, height - 14)
  const start = Math.max(0, Math.min(index - Math.floor(bodyRows / 2), results.length - bodyRows))

  const choose = (id: string) => {
    if (!blocked) {
      onSelect(id)
    }
  }

  const changeScope = (next: DirectoryScope) => {
    if (!blocked) {
      setScope(next)
      setSelectedId(null)
    }
  }

  useInput(
    (input, key, event) => {
      ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()

      if (key.escape) {
        return onCancel()
      }

      if (key.ctrl && input === 'b' && onNewGroup) {
        return onNewGroup()
      }

      if (key.ctrl && input === 'r') {
        const cfg = resolveSignalConfig()

        if (cfg) {
          void refreshSignalDirectory(cfg, true)
        }

        return
      }

      if (key.tab || key.leftArrow || key.rightArrow) {
        const delta = key.shift || key.leftArrow ? -1 : 1

        return changeScope(scopes[(scopes.indexOf(scope as never) + delta + scopes.length) % scopes.length]!)
      }

      if (key.upArrow || key.downArrow || key.pageUp || key.pageDown) {
        const delta = key.upArrow ? -1 : key.pageUp ? -bodyRows : key.pageDown ? bodyRows : 1

        return setSelectedId(results[Math.max(0, Math.min(results.length - 1, index + delta))]?.id ?? null)
      }

      if (key.return && active) {
        return choose(active.id)
      }

      if (key.backspace || key.delete) {
        setQuery(v => [...v].slice(0, -1).join(''))
        setSelectedId(null)

        return
      }

      if (input && !key.ctrl && !key.meta) {
        setQuery(v => (v + [...input].filter(c => c >= ' ' && c !== '\x7f').join('')).slice(0, 200))
        setSelectedId(null)
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay cols={cols} maxHeight={34} maxWidth={110} rows={rows} t={t}>
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary} wrap="truncate-end">
            {title}
          </Text>
          <Text color={t.color.muted}>{results.length} matches</Text>
        </Box>
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.accent} wrap="truncate-end">
            Search › {query || 'name, topic, category or +number'}▌
          </Text>
        </Box>
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            Local search · names, related terms and saved messages
          </Text>
        </Box>
        <Box flexGrow={1} marginTop={1} minHeight={0} overflow="hidden">
          <Box
            borderBottom={false}
            borderColor={t.color.border}
            borderLeft={false}
            borderStyle="single"
            borderTop={false}
            flexDirection="column"
            flexShrink={0}
            width={cols < 70 ? 11 : 15}
          >
            {scopes
              .slice(Math.max(0, scopeIndex - bodyRows + 1), Math.max(0, scopeIndex - bodyRows + 1) + bodyRows)
              .map(s => (
                <Box key={s} onClick={() => changeScope(s)}>
                  <Text color={s === scope ? t.color.accent : t.color.muted}>
                    {s === scope ? '› ' : '  '}
                    {s}
                  </Text>
                </Box>
              ))}
          </Box>
          <Box flexDirection="column" flexGrow={1} minWidth={0} paddingLeft={1}>
            {results.slice(start, start + bodyRows).map((r, i) => (
              <Box key={r.id} onClick={() => choose(r.id)}>
                <Text color={start + i === index ? t.color.accent : t.color.text} wrap="truncate-end">
                  {start + i === index ? '› ' : '  '}
                  {r.unread ? '● ' : ''}
                  {r.name}
                  {r.category ? ` · ${r.category}` : ''}
                  {r.count ? ` · ${r.count} msgs` : ''}
                </Text>
              </Box>
            ))}
            {!results.length && (
              <Text color={t.color.muted}>
                No matches. Try a name, topic or full +countrycode number. Ctrl+R syncs contacts.
              </Text>
            )}
          </Box>
        </Box>
        <Box flexDirection="column" flexShrink={0}>
          <Text color={t.color.label} wrap="truncate-end">
            {active
              ? `${active.id} · ${active.count} locally saved messages${state[active.id]?.archived ? ' · archived' : ''}`
              : 'Choose a contact or conversation'}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {active?.snippet.replace(/\s+/g, ' ') ||
              'History begins with messages received by this desk; phone history is not imported.'}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {status || 'Names come from Signal or your saved labels; no inferred identities.'}
          </Text>
          <Text color={t.color.accent} wrap="truncate-end">
            ↑↓ choose · Tab scope · Enter open · ^R sync{onNewGroup ? ' · ^B group' : ''} · Esc back
          </Text>
        </Box>
      </Box>
    </ModalOverlay>
  )
}
