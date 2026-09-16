import { useStore } from '@nanostores/react'
import { Box, Text, useInput } from '@superforecasting/ink'
import { useRef, useState } from 'react'

import { $overlayState } from '../app/overlayStore.js'
import { encodeFeedMessage, presentFeedShare } from '../lib/feedShare.js'
import { sendDeskMessage } from '../lib/messagingSend.js'
import { $chatState, $messagingStorageError, $quickMessage, updateChatState } from '../lib/messagingState.js'
import { $signalDirectory } from '../lib/signalDirectory.js'
import { resolveSignalConfig } from '../lib/signalStore.js'
import type { FeedShare } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ContactPicker } from './contactPicker.js'
import { FeedShareCard } from './feedShareCard.js'
import { MessageComposer } from './messageComposer.js'
import { ModalOverlay } from './modalOverlay.js'

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
  const [chart, setChart] = useState<FeedShare['presentation']>('bar-chart')
  const [horizon, setHorizon] = useState(24)
  const [optionsFocused, setOptionsFocused] = useState(false)
  const feed = includeItem && request?.item?.feed ? presentFeedShare(request.item.feed, chart, horizon) : null
  const sending = useRef(false)
  const book = useStore($signalDirectory)
  const modalWidth = cols < 100 ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 88))

  const draftRows = Math.max(
    1,
    Math.min(6, Math.min(rows - 6, 30) - 14 - (includeItem && request?.item ? (feed ? 6 : 2) : 0))
  )

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

    let text = [
      value.trim(),
      includeItem && request?.item ? `${request.item.title}\n${request.item.text.replace(/\s+/g, ' ')}` : ''
    ]
      .filter(Boolean)
      .join('\n\n')

    if (feed) {
      try {
        text = encodeFeedMessage(text, feed)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Cannot encode feed snapshot')

        return
      }
    }

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
      if (
        optionsFocused ||
        !recipient ||
        key.escape ||
        key.tab ||
        sending.current ||
        (key.ctrl && input.toLowerCase() === 'r')
      ) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (sending.current) {
        return
      }

      if (key.tab && key.shift && feed) {
        setOptionsFocused(value => !value)

        return
      }

      if (optionsFocused && feed) {
        if (key.leftArrow || key.rightArrow) {
          setChart(value => (value === 'bar-chart' ? 'line-chart' : 'bar-chart'))
        }

        if (key.upArrow || key.downArrow) {
          setHorizon(value => {
            const choices = [6, 12, 24, 120]
            const index = choices.indexOf(value)

            return choices[(index + (key.upArrow ? 3 : 1)) % 4]!
          })
        }

        if (key.return || key.escape) {
          setOptionsFocused(false)
        }

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
      footerHint={
        optionsFocused
          ? '←/→ chart · ↑/↓ observations · Enter compose'
          : `Tab recipient · ${feed ? 'Shift+Tab chart · ' : ''}Ctrl+R forward · Esc keep draft`
      }
      maxHeight={30}
      maxWidth={88}
      rows={rows}
      t={t}
      title="MESSAGE"
      verticalMargin={rows < 30 ? 2 : 6}
    >
      <Box flexShrink={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          Signal · Review recipient and content before sending
        </Text>
      </Box>
      <Box flexShrink={0}>
        <Text color={t.color.accent} wrap="truncate-end">
          To: {book[recipient]?.name || recipient} · {recipient}
        </Text>
      </Box>
      <MessageComposer
        active={!busy && !blocked && !optionsFocused}
        busy={busy}
        columns={modalWidth - 10}
        hasAttachment={Boolean(includeItem && request?.item)}
        inputRows={draftRows}
        multiline
        onBack={() => setRecipient(null)}
        onChange={value => {
          setDraft(value)
          updateChatState(recipient, { draft: value })
        }}
        onSend={value => void send(value)}
        t={t}
        text={draft}
      />
      {feed ? (
        <Box flexDirection="column" flexShrink={0}>
          <Text color={optionsFocused ? t.color.accent : t.color.muted}>
            {chart} · latest {horizon} observations · Shift+Tab edit
          </Text>
          <FeedShareCard compact share={feed} t={t} width={modalWidth - 10} />
        </Box>
      ) : (
        includeItem &&
        request?.item && (
          <Box flexDirection="column" flexShrink={0}>
            <Text color={t.color.label} wrap="truncate-end">
              FORWARD · {request.item.title}
            </Text>
            <Text color={t.color.muted} wrap="truncate-end">
              {request.item.text.replace(/\s+/g, ' ')}
            </Text>
          </Box>
        )
      )}
      {(error || storageError) && (
        <Text color={t.color.error} wrap="truncate-end">
          {error || storageError}
        </Text>
      )}
    </ModalOverlay>
  )
}
