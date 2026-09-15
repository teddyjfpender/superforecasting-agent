import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useMemo, useRef, useState } from 'react'

import { sendDeskMessage } from '../lib/messagingSend.js'
import { $chatState, $messagingStorageError, $quickMessage, updateChatState } from '../lib/messagingState.js'
import { isValidNumber, loadContactBook, normalizeNumber } from '../lib/signalContacts.js'
import { signalCache } from '../lib/signalLive.js'
import { resolveSignalConfig } from '../lib/signalStore.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

export function QuickMessage({ cols, rows, t }: { cols: number; rows: number; t: Theme }) {
  const request = useStore($quickMessage)
  const state = useStore($chatState)
  const storageError = useStore($messagingStorageError)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const [recipient, setRecipient] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [includeItem, setIncludeItem] = useState(true)
  const sending = useRef(false)
  const inputRef = useRef<ScrollBoxHandle>(null)
  const book = useMemo(() => loadContactBook(), [])

  const targets = [...new Set([...Object.keys(book), ...Object.keys(signalCache()), ...Object.keys(state)])]
    .filter(id =>
      `${book[id]?.name ?? ''} ${id} ${state[id]?.category ?? ''}`.toLowerCase().includes(query.toLowerCase())
    )
    .sort(
      (a, b) =>
        Number(Boolean(state[b]?.pinned)) - Number(Boolean(state[a]?.pinned)) ||
        (book[a]?.name ?? a).localeCompare(book[b]?.name ?? b)
    )

  if (isValidNumber(query) && !targets.includes(normalizeNumber(query))) {
    targets.unshift(normalizeNumber(query))
  }

  const targetRows = Math.min(5, Math.max(2, rows - 22))
  const draftRows = Math.max(2, Math.min(6, rows - 20))
  const index = Math.min(selected, Math.max(0, targets.length - 1))

  const choose = () => {
    const id = targets[index]

    if (!id) {
      return
    }

    setRecipient(id)
    setDraft(state[id]?.draft || '')
  }

  const send = async (value = draft) => {
    const cfg = resolveSignalConfig()

    if (!cfg) {
      setError('Signal is not configured. Open Messaging → Set up.')

      return
    }

    if (!recipient || sending.current) {
      return
    }

    const id = recipient

    const text = [
      value.trim(),
      includeItem && request?.item ? `${request.item.title}\n${request.item.text.replace(/\s+/g, ' ')}` : ''
    ]
      .filter(Boolean)
      .join('\n\n')

    sending.current = true
    setBusy(true)
    const failure = await sendDeskMessage(cfg, id, text)
    sending.current = false
    setBusy(false)

    if (failure) {
      setError(failure)

      return
    }

    if ($chatState.get()[id]?.draft === value) {
      updateChatState(id, { draft: '' })
    }

    $quickMessage.set(null)
  }

  useInput((input, key, event) => {
    if (!recipient || key.escape || key.tab || sending.current || (key.ctrl && input.toLowerCase() === 'r')) {
      ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
    }

    if (sending.current) {
      return
    }

    if (key.escape) {
      $quickMessage.set(null)

      return
    }

    if (key.tab) {
      setRecipient(null)

      return
    }

    if (key.ctrl && input.toLowerCase() === 'r') {
      setIncludeItem(value => !value)

      return
    }

    if (recipient) {
      return
    } else {
      if (key.upArrow) {
        setSelected(v => Math.max(0, v - 1))

        return
      }

      if (key.downArrow) {
        setSelected(v => Math.min(targets.length - 1, v + 1))

        return
      }

      if (key.return) {
        choose()

        return
      }

      if (key.backspace || key.delete) {
        setQuery(v => v.slice(0, -1))
        setSelected(0)

        return
      }

      if (input && !key.ctrl && !key.meta) {
        setQuery(v => v + input)
        setSelected(0)
      }
    }
  })

  return (
    <ModalOverlay
      cols={cols}
      footerHint="Ctrl+Enter send · Tab to · Ctrl+R forward · Esc keep draft"
      maxHeight={24}
      maxWidth={88}
      rows={rows}
      t={t}
      title="MESSAGE"
    >
      <Box flexShrink={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          Signal · {busy ? 'Sending…' : 'Review recipient and content before sending'}
        </Text>
      </Box>
      <Box flexShrink={0}>
        <Text color={t.color.accent} wrap="truncate-end">
          To: {recipient ? book[recipient]?.name || recipient : `${query}▌`}
        </Text>
      </Box>
      {recipient ? (
        <ScrollBox
          decstbm={false}
          flexDirection="column"
          flexShrink={0}
          followContent={false}
          height={draftRows}
          ref={inputRef}
        >
          <TextInput
            columns={Math.min(76, cols - 8)}
            focus={!busy}
            immediateChange
            multiline
            onChange={value => {
              setDraft(value)
              updateChatState(recipient, { draft: value })
            }}
            onCursorLine={line => inputRef.current?.scrollTo(Math.max(0, line - draftRows + 1))}
            onSubmit={value => void send(value)}
            placeholder="Write a message…"
            value={draft}
          />
        </ScrollBox>
      ) : (
        <Box flexDirection="column" flexShrink={0} height={targetRows}>
          {targets
            .slice(Math.max(0, index - targetRows + 1), Math.max(0, index - targetRows + 1) + targetRows)
            .map(id => (
              <Box
                key={id}
                onClick={() => {
                  setRecipient(id)
                  setDraft(state[id]?.draft || '')
                }}
              >
                <Text color={id === targets[index] ? t.color.accent : t.color.text}>
                  {id === targets[index] ? '› ' : '  '}
                  {book[id]?.name || id}
                  {id.startsWith('group:') ? ' · group' : ''}
                </Text>
              </Box>
            ))}
          {!targets.length && (
            <Text color={t.color.muted}>Search a saved contact, category, group or enter +countrycode number.</Text>
          )}
        </Box>
      )}
      {includeItem && request?.item && (
        <Box flexDirection="column" flexShrink={0} marginTop={1}>
          <Text color={t.color.label} wrap="truncate-end">
            FORWARD · {request.item.title}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {request.item.text.replace(/\s+/g, ' ')}
          </Text>
        </Box>
      )}
      {(error || storageError) && (
        <Text color={t.color.error} wrap="truncate-end">
          {error || storageError}
        </Text>
      )}
      <Box
        flexShrink={0}
        marginTop={1}
        onClick={() => {
          if (!sending.current) {
            void send()
          }
        }}
      >
        <Text bold color={t.color.accent}>
          [ Send message ]
        </Text>
      </Box>
    </ModalOverlay>
  )
}
