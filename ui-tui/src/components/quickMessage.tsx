import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useRef, useState } from 'react'

import { $overlayState } from '../app/overlayStore.js'
import { sendDeskMessage } from '../lib/messagingSend.js'
import { $chatState, $messagingStorageError, $quickMessage, updateChatState } from '../lib/messagingState.js'
import { $signalDirectory } from '../lib/signalDirectory.js'
import { resolveSignalConfig } from '../lib/signalStore.js'
import type { Theme } from '../theme.js'

import { ContactPicker } from './contactPicker.js'
import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

export function QuickMessage({ cols, rows, t }: { cols: number; rows: number; t: Theme }) {
  const overlay = useStore($overlayState)
  const blocked = overlay.palette || overlay.cheatSheet
  const request = useStore($quickMessage)
  const state = useStore($chatState)
  const storageError = useStore($messagingStorageError)
  const [recipient, setRecipient] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [includeItem, setIncludeItem] = useState(true)
  const sending = useRef(false)
  const inputRef = useRef<ScrollBoxHandle>(null)
  const book = useStore($signalDirectory)
  const draftRows = Math.max(2, Math.min(6, rows - 20))

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

  useInput(
    (input, key, event) => {
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
    },
    { isActive: Boolean(recipient) && !blocked }
  )

  if (!recipient) {
    return (
      <ContactPicker
        cols={cols}
        onCancel={() => $quickMessage.set(null)}
        onSelect={id => {
          setRecipient(id)
          setDraft(state[id]?.draft || '')
        }}
        rows={rows}
        t={t}
        title="MESSAGE · CHOOSE RECIPIENT"
      />
    )
  }

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
          To: {book[recipient]?.name || recipient} · {recipient}
        </Text>
      </Box>
      {
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
            focus={!busy && !blocked}
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
      }
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
          if (!sending.current && !blocked) {
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
