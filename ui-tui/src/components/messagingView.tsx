import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import { ICON, statusGlyph, type StatusKind } from '../lib/icons.js'
import {
  checkHealth,
  listContacts,
  listGroups,
  openReceiveStream,
  sendSignalMessage,
  type SignalContact,
  type SignalGroup
} from '../lib/signalClient.js'
import {
  type ContactBook,
  isValidNumber,
  loadContactBook,
  normalizeNumber,
  saveContactBook,
  upsertContact
} from '../lib/signalContacts.js'
import {
  appendMessage,
  loadSignalCache,
  resolveSignalConfig,
  saveSignalCache,
  type SignalCache
} from '../lib/signalStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'
import { SignalSetupModal } from './signalSetupModal.js'

export const openMessagingView = () => patchOverlayState({ messaging: true })
export const closeMessagingView = () => patchOverlayState({ messaging: false })

// Messaging — your personal Signal client. Talks to a signal-cli daemon (the
// same one the agent bridge uses) so you can read and send your own
// conversations as yourself. Telegram is deferred (its bot API can't read a
// personal account). The agent bridge (deployers messaging the system) is a
// separate concern that lives in the full `gateway run` daemon.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const relTime = (ms: number): string => {
  if (!ms) {
    return ''
  }

  const diff = Date.now() - ms

  if (diff < 0) {
    return 'now'
  }

  const m = Math.floor(diff / 60_000)

  if (m < 1) {
    return 'now'
  }

  if (m < 60) {
    return `${m}m`
  }

  const h = Math.floor(m / 60)

  if (h < 24) {
    return `${h}h`
  }

  const d = Math.floor(h / 24)

  if (d < 7) {
    return `${d}d`
  }

  return new Date(ms).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

const clock = (ms: number): string =>
  ms ? new Date(ms).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : ''

// Which messages get a sender/time header: the first, any sender change, or a
// gap longer than `gapMs` (default 5 min). A run from one person within the gap
// reads as a single block (standard messaging-app grouping).
export const GROUP_GAP_MS = 5 * 60 * 1000

export const messageHeaders = (
  messages: { author?: string; fromMe: boolean; timestamp: number }[],
  gapMs = GROUP_GAP_MS
): boolean[] =>
  messages.map((m, i) => {
    const prev = messages[i - 1]

    if (!prev) {
      return true
    }

    const sameSender = prev.fromMe === m.fromMe && (m.fromMe || prev.author === m.author)

    return !(sameSender && m.timestamp - prev.timestamp < gapMs)
  })

// Human label for a conversation: the resolved contact/group name when we have
// one, otherwise a tidy fallback — a phone number as-is, a group placeholder, or
// a shortened opaque id (so a raw UUID doesn't dominate the rail).
const displayName = (chatId: string, resolved?: string): string => {
  const name = resolved?.trim()

  if (name) {
    return name
  }

  if (chatId.startsWith('group:')) {
    return 'Signal group'
  }

  if (/^\+\d{6,}$/.test(chatId)) {
    return chatId
  }

  return chatId.length > 16 ? `${chatId.slice(0, 13)}…` : chatId
}

const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

interface Conversation {
  chatId: string
  hasMessages: boolean
  lastText: string
  lastTs: number
  name: string
}

interface MessagingViewProps {
  onClose: () => void
  t: Theme
}

export function MessagingView({ onClose, t }: MessagingViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [cfg, setCfg] = useState<ReturnType<typeof resolveSignalConfig>>(() => resolveSignalConfig())
  const [setup, setSetup] = useState(false)

  const [reachable, setReachable] = useState<boolean | null>(cfg ? null : false)
  const [streaming, setStreaming] = useState(false)
  const [contacts, setContacts] = useState<SignalContact[]>([])
  const [groups, setGroups] = useState<SignalGroup[]>([])
  // Selection is by chatId (stable), not list index — the list re-sorts by
  // recency when you send/receive, so an index would jump to another chat.
  const [selectedChatId, setSelectedChatId] = useState<null | string>(null)
  const [tick, setTick] = useState(0)
  const [flash, setFlash] = useState('')
  const [draft, setDraft] = useState('')

  // Focus: the chat LIST, or an open THREAD. In a thread the composer is ALWAYS
  // active (you can type the moment you open a chat — no extra keystroke), and
  // arrows/wheel scroll the history. `threadScroll` counts messages scrolled up
  // from the latest.
  const [focus, setFocus] = useState<'list' | 'thread'>('list')
  const [threadScroll, setThreadScroll] = useState(0)
  const composing = focus === 'thread'

  // Persisted address book (names/numbers) + the "new message" composer.
  const [contactBook, setContactBook] = useState<ContactBook>(() => loadContactBook())
  const [newChat, setNewChat] = useState(false)
  const [newNumber, setNewNumber] = useState('')
  const [newName, setNewName] = useState('')
  const [newField, setNewField] = useState<'name' | 'number'>('number')

  const cacheRef = useRef<SignalCache>(loadSignalCache())
  const [cacheVersion, setCacheVersion] = useState(0)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

  // Connect: health check → load contacts/groups → open the receive stream.
  useEffect(() => {
    if (!cfg) {
      return
    }

    let stop = () => {}
    void (async () => {
      const ok = await checkHealth(cfg)

      if (!aliveRef.current) {
        return
      }

      setReachable(ok)

      if (!ok) {
        return
      }

      const [cs, gs] = await Promise.all([listContacts(cfg), listGroups(cfg)])

      if (!aliveRef.current) {
        return
      }

      setContacts(cs)
      setGroups(gs)
      setContactBook(prev => {
        let book = prev

        for (const c of cs) {
          // Skip when the daemon's "name" is just the id/number — don't let it
          // clobber a real name you've saved.
          if (c.name?.trim() && c.name.trim() !== c.id) {
            book = upsertContact(book, { chatId: c.id, name: c.name })
          }
        }

        for (const g of gs) {
          if (g.name?.trim()) {
            book = upsertContact(book, { chatId: `group:${g.id}`, name: g.name })
          }
        }

        if (book !== prev) {
          saveContactBook(book)
        }

        return book
      })
      stop = openReceiveStream(
        cfg,
        msg => {
          cacheRef.current = appendMessage(cacheRef.current, msg)
          saveSignalCache(cacheRef.current)

          if (aliveRef.current) {
            setCacheVersion(v => v + 1)
          }
        },
        connected => {
          if (aliveRef.current) {
            setStreaming(connected)
          }
        }
      )
    })()

    return () => stop()
  }, [cfg])

  const conversations = useMemo<Conversation[]>(() => {
    const cache = cacheRef.current
    const nameById = new Map<string, string>()

    for (const c of contacts) {
      nameById.set(c.id, c.name)
    }

    for (const g of groups) {
      nameById.set(`group:${g.id}`, g.name)
    }

    // The persisted book fills in names the live daemon didn't resolve (and
    // surfaces chats — e.g. a number you just started — that have no history).
    for (const [id, c] of Object.entries(contactBook)) {
      if (c.name && !nameById.get(id)?.trim()) {
        nameById.set(id, c.name)
      }
    }

    const ids = new Set<string>([
      ...contacts.map(c => c.id),
      ...groups.map(g => `group:${g.id}`),
      ...Object.keys(contactBook),
      ...Object.keys(cache)
    ])

    const list: Conversation[] = [...ids].map(chatId => {
      const msgs = cache[chatId] ?? []
      const last = msgs[msgs.length - 1]
      const preview = last ? `${last.fromMe ? 'You: ' : ''}${last.text || (last.attachments ? `${ICON.attach} attachment` : '')}` : ''

      return {
        chatId,
        hasMessages: msgs.length > 0,
        lastText: preview,
        lastTs: last?.timestamp ?? 0,
        name: displayName(chatId, nameById.get(chatId))
      }
    })

    list.sort((a, b) => b.lastTs - a.lastTs || a.name.localeCompare(b.name))

    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contacts, groups, contactBook, cacheVersion])

  const foundIndex = conversations.findIndex(c => c.chatId === selectedChatId)
  const clampedSel = foundIndex >= 0 ? foundIndex : 0
  const activeConv = conversations[clampedSel]
  const threadMessages = activeConv ? cacheRef.current[activeConv.chatId] ?? [] : []

  // Layout + thread-window geometry (needed by both the key handler and render).
  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 7)
  const railWidth = Math.min(40, Math.max(26, Math.floor(width * 0.34)))
  const railRows = Math.max(3, contentHeight - 2)
  // Rows available for messages: header + marginTop + (composer when writing).
  const composerRows = composing ? 3 : 0
  const msgRows = Math.max(1, contentHeight - 2 - composerRows)
  // ~2 rows per message (sender line + text); window by message for scrolling.
  const threadVisible = Math.max(1, Math.floor(msgRows / 2))
  const maxThreadScroll = Math.max(0, threadMessages.length - threadVisible)
  const threadScrollClamped = Math.min(threadScroll, maxThreadScroll)

  // Reset the scroll to the latest whenever the open conversation changes.
  useEffect(() => {
    setThreadScroll(0)
  }, [activeConv?.chatId])

  // Start a conversation with a typed number: validate, save it to the address
  // book (so the name persists), then select + open it (chatId selection means
  // it resolves as soon as the book update lands it in the list).
  const createNewChat = () => {
    const number = normalizeNumber(newNumber)

    if (!isValidNumber(number)) {
      setFlash('enter a valid number, e.g. +12674553945')

      return
    }

    const book = upsertContact(contactBook, { chatId: number, name: newName, number })
    setContactBook(book)
    saveContactBook(book)
    setNewChat(false)
    setNewNumber('')
    setNewName('')
    setNewField('number')
    setSelectedChatId(number)
    setThreadScroll(0)
    setFocus('thread')
    setFlash(`new chat · ${newName.trim() || number}`)
  }

  const sendDraft = () => {
    const text = draft.trim()
    setDraft('') // clear, but stay in the thread so you can keep typing
    setThreadScroll(0) // jump to the latest so the sent message is visible

    if (!text || !activeConv || !cfg) {
      return
    }

    setFlash('sending…')

    void (async () => {
      const { error, timestamp } = await sendSignalMessage(cfg, activeConv.chatId, text)

      if (!aliveRef.current) {
        return
      }

      if (error) {
        setFlash(`send failed: ${error}`)

        return
      }

      cacheRef.current = appendMessage(cacheRef.current, {
        attachments: 0,
        author: 'me',
        chatId: activeConv.chatId,
        fromMe: true,
        text,
        timestamp: timestamp || Date.now()
      })
      saveSignalCache(cacheRef.current)
      setCacheVersion(v => v + 1)
      setFlash('sent')
    })()
  }

  const reconnect = () => {
    if (!cfg) {
      return
    }

    setFlash('reconnecting…')

    void (async () => {
      const ok = await checkHealth(cfg)

      if (!aliveRef.current) {
        return
      }

      setReachable(ok)

      if (ok) {
        const [cs, gs] = await Promise.all([listContacts(cfg), listGroups(cfg)])

        if (aliveRef.current) {
          setContacts(cs)
          setGroups(gs)
          setContactBook(prev => {
            let book = prev

            for (const c of cs) {
              if (c.name?.trim()) {
                book = upsertContact(book, { chatId: c.id, name: c.name })
              }
            }

            for (const g of gs) {
              if (g.name?.trim()) {
                book = upsertContact(book, { chatId: `group:${g.id}`, name: g.name })
              }
            }

            if (book !== prev) {
              saveContactBook(book)
            }

            return book
          })
          setFlash('refreshed')
        }
      }
    })()
  }

  const connected = reachable === true

  // The setup modal finished provisioning + started the daemon and wrote
  // signal.json — re-resolve config so the connect effect fires and we attach.
  const onConnected = () => {
    setSetup(false)
    setReachable(null)
    setCfg(resolveSignalConfig())
    setFlash('connected')
  }

  useInput((ch, key) => {
    // While the setup modal is open it owns all input.
    if (setup) {
      return
    }

    // New-message composer: number + optional name, Tab switches field.
    if (newChat) {
      if (key.escape) {
        return setNewChat(false)
      }

      if (key.return) {
        return createNewChat()
      }

      if (key.tab) {
        return setNewField(f => (f === 'number' ? 'name' : 'number'))
      }

      if (key.backspace || key.delete) {
        return newField === 'number' ? setNewNumber(s => s.slice(0, -1)) : setNewName(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          return newField === 'number' ? setNewNumber(s => s + printable) : setNewName(s => s + printable)
        }
      }

      return
    }

    // Open thread: the composer is always active here (type immediately).
    // Enter sends, arrows/wheel scroll history, Esc returns to the list. All
    // other printable keys (incl. q/s/r/n) go into the draft — no global
    // shortcuts while typing.
    if (focus === 'thread') {
      if (key.escape) {
        setDraft('')

        return setFocus('list')
      }

      if (key.return) {
        return sendDraft()
      }

      if (key.upArrow || key.wheelUp) {
        return setThreadScroll(s => Math.min(maxThreadScroll, s + 1))
      }

      if (key.downArrow || key.wheelDown) {
        return setThreadScroll(s => Math.max(0, s - 1))
      }

      if (key.backspace || key.delete) {
        return setDraft(d => d.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setDraft(d => d + printable)
        }
      }

      return
    }

    // List focus.
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 's') {
      return setSetup(true)
    }

    if (ch === 'r') {
      return reconnect()
    }

    if (ch === 'n') {
      setNewNumber('')
      setNewName('')
      setNewField('number')

      return setNewChat(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSelectedChatId(conversations[Math.max(0, clampedSel - 1)]?.chatId ?? null)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSelectedChatId(conversations[Math.min(conversations.length - 1, clampedSel + 1)]?.chatId ?? null)
    }

    // Enter / → / i open the highlighted chat — composer ready immediately.
    if ((key.return || key.rightArrow || ch === 'l' || ch === 'i') && activeConv) {
      setSelectedChatId(activeConv.chatId)
      setThreadScroll(0)

      return setFocus('thread')
    }
  })

  const live = tick % 2 === 0

  const statusDot = !cfg
    ? t.color.muted
    : reachable === null
      ? live
        ? t.color.warn
        : t.color.muted
      : connected
        ? streaming
          ? t.color.ok
          : t.color.warn
        : t.color.error

  const statusWord = !cfg
    ? 'not connected'
    : reachable === null
      ? 'connecting…'
      : connected
        ? streaming
          ? 'online'
          : 'connected'
        : 'unreachable'

  const statusKind: StatusKind = !cfg ? 'idle' : reachable === null ? 'busy' : connected ? 'live' : 'error'

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MESSAGING
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={statusDot}>{statusGlyph(statusKind, tick)}</Text>
        <Text color={t.color.muted}> {statusWord} · </Text>
        <Text color={connected ? t.color.accent : t.color.text}>Signal</Text>
        <Text color={t.color.muted}> · Telegram (soon)</Text>
        {cfg ? <Text color={t.color.muted}>{`  ${cfg.account}`}</Text> : null}
      </Text>
    </Box>
  )

  // ---- Setup modal (press s) — paints over everything ---------------------
  if (setup) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <SignalSetupModal
          cols={cols}
          onCancel={() => setSetup(false)}
          onConnected={onConnected}
          rows={termRows}
          t={t}
        />
      </Box>
    )
  }

  // ---- New-message composer (press n) -------------------------------------
  if (newChat) {
    const modalW = Math.max(40, Math.min(cols - 4, 66))
    const valid = isValidNumber(newNumber)

    const field = (label: string, value: string, active: boolean, placeholder: string) => (
      <Box>
        <Text bold={active} color={active ? t.color.accent : t.color.label}>
          {label.padEnd(8)}
        </Text>
        <Text color={t.color.muted}>{'› '}</Text>
        <Text color={t.color.text}>{value}</Text>
        {active ? (
          live ? (
            <Text color={t.color.text} inverse>
              {' '}
            </Text>
          ) : (
            <Text>{' '}</Text>
          )
        ) : null}
        {!value ? <Text color={t.color.muted}> {placeholder}</Text> : null}
      </Box>
    )

    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
          <Box borderColor={t.color.accent} borderStyle="round" flexDirection="column" paddingX={2} paddingY={1} width={modalW}>
            <Text bold color={t.color.primary}>
              New message
            </Text>
            <Box marginTop={1}>
              <Text color={t.color.border}>{'─'.repeat(modalW - 6)}</Text>
            </Box>
            <Box flexDirection="column" marginTop={1}>
              {field('Number', newNumber, newField === 'number', '+12674553945')}
              {field('Name', newName, newField === 'name', 'optional')}
            </Box>
            <Box marginTop={1}>
              <Text color={newNumber ? (valid ? t.color.ok : t.color.error) : t.color.muted} wrap="truncate-end">
                {newNumber
                  ? valid
                    ? `${ICON.ok} valid Signal number`
                    : 'needs E.164 format, e.g. +12674553945'
                  : 'Enter a phone number in E.164 format (with country code).'}
              </Text>
            </Box>
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="truncate-end">
                ⏎ start chat · Tab switch field · Esc cancel
              </Text>
            </Box>
          </Box>
        </Box>
      </Box>
    )
  }

  // ---- Not configured: prompt the in-TUI setup ----------------------------
  if (!cfg) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box alignItems="center" flexGrow={1} justifyContent="center">
          <Box flexDirection="column" width={Math.min(72, Math.max(40, cols - 8))}>
            <Text bold color={t.color.text}>
              Message on Signal, as yourself.
            </Text>
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="wrap">
                Outrider runs a local signal-cli daemon for you: installing it, linking your account (or registering a
                new number), and starting it on a free port. It all happens here; you never leave the TUI.
              </Text>
            </Box>
            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Press s
              </Text>
              <Text color={t.color.text}> to set up Signal.</Text>
            </Box>
          </Box>
        </Box>
        <Box flexDirection="column" flexShrink={0} marginTop={1}>
          <FooterChips chips={[{ k: 's', label: 'Set up', run: () => setSetup(true) }, { k: 'q', label: 'Close', run: onClose }]} t={t} />
          <Text color={t.color.muted} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
            s set up Signal · Esc/q close
          </Text>
        </Box>
      </Box>
    )
  }

  // ---- CHATS rail ----------------------------------------------------------
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(railRows / 2), conversations.length - railRows))
  const windowedConvs = conversations.slice(Math.max(0, listStart), Math.max(0, listStart) + railRows)

  const listFocused = focus === 'list'

  const rail = (
    <Box
      {...RIGHT_RULE}
      borderColor={listFocused ? t.color.accent : t.color.border}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={railWidth}
    >
      <Text bold color={listFocused ? t.color.accent : t.color.label} wrap="truncate-end">
        CHATS{conversations.length ? <Text color={t.color.muted}>{`  (${conversations.length})`}</Text> : null}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {windowedConvs.length > 0 ? (
          // Single line per chat — name + relative time. Two-line rows desync
          // the fixed-height window on scroll and ghost over each other.
          windowedConvs.map((conv, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            const time = relTime(conv.lastTs)
            const nameW = Math.max(6, railWidth - 4 - time.length)

            return (
              <Box key={conv.chatId} onClick={() => { setSelectedChatId(conv.chatId); setThreadScroll(0); setFocus('thread') }} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? t.color.accent : t.color.border}>{on ? '▸ ' : '  '}</Text>
                  <Text bold={on} color={on ? t.color.text : t.color.label}>
                    {truncate(conv.name, nameW).padEnd(nameW)}
                  </Text>
                  <Text color={t.color.border}> {time}</Text>
                </Text>
              </Box>
            )
          })
        ) : (
          <Text color={t.color.muted} wrap="wrap">
            {connected ? 'No conversations yet. Messages appear as they arrive.' : ''}
          </Text>
        )}
      </Box>
    </Box>
  )

  // ---- Thread pane ---------------------------------------------------------
  const threadFocused = focus === 'thread'
  const headerForMsg = messageHeaders(threadMessages)

  const threadEnd = Math.max(0, threadMessages.length - threadScrollClamped)
  const threadStart = Math.max(0, threadEnd - threadVisible)
  const windowMsgs = threadMessages.slice(threadStart, threadEnd)
  const olderCount = threadStart
  const newerCount = threadMessages.length - threadEnd

  const thread = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} height={contentHeight} marginLeft={1} minWidth={0} overflow="hidden">
      <Text bold={threadFocused} color={threadFocused ? t.color.accent : t.color.label} wrap="truncate-end">
        {threadFocused ? '▸ ' : ''}
        {activeConv ? truncate(activeConv.name, 32) : 'SIGNAL'}
        {activeConv?.chatId.startsWith('group:') ? <Text color={t.color.muted}> · group</Text> : null}
        {threadFocused && olderCount > 0 ? <Text color={t.color.muted}>{`  ↑ ${olderCount} older`}</Text> : null}
        {threadFocused && newerCount > 0 ? <Text color={t.color.muted}>{`  ↓ ${newerCount} newer`}</Text> : null}
      </Text>

      {!connected ? (
        <Box flexDirection="column" height={msgRows} marginTop={1}>
          <Text color={reachable === false ? t.color.error : t.color.muted} wrap="wrap">
            {reachable === false
              ? `Can't reach signal-cli at ${cfg.httpUrl}. Start the daemon (signal-cli -a ${cfg.account} daemon --http 127.0.0.1:8080) and press r.`
              : 'Connecting to signal-cli…'}
          </Text>
        </Box>
      ) : (
        <Box flexDirection="column" height={msgRows} justifyContent="flex-end" marginTop={1} overflow="hidden">
          {threadMessages.length === 0 ? (
            <Text color={t.color.muted} wrap="wrap">
              No messages yet. Press i to write one.
            </Text>
          ) : (
            windowMsgs.map((m, i) => {
              const gi = threadStart + i
              const showHeader = headerForMsg[gi]

              const label = m.fromMe
                ? 'You'
                : truncate(activeConv?.chatId.startsWith('group:') ? m.author : activeConv?.name ?? m.author, 24)

              return (
                <Box flexDirection="column" key={`${m.timestamp}:${gi}`} marginTop={showHeader && i > 0 ? 1 : 0}>
                  {showHeader ? (
                    <Text wrap="truncate-end">
                      <Text bold color={m.fromMe ? t.color.ok : t.color.accent}>
                        {label}
                      </Text>
                      <Text color={t.color.muted}>{`  ${clock(m.timestamp)}`}</Text>
                    </Text>
                  ) : null}
                  <Text color={t.color.text} wrap="wrap">
                    {m.text || (m.attachments ? `${ICON.attach} attachment` : '')}
                  </Text>
                </Box>
              )
            })
          )}
        </Box>
      )}

      {/* Native bottom composer — sits below the history, doesn't overlap it. */}
      {composing ? (
        <Box borderColor={t.color.accent} borderStyle="round" flexShrink={0} paddingX={1}>
          <Text color={t.color.muted}>{'› '}</Text>
          <Text color={t.color.text}>{draft}</Text>
          {/* Blinking block caret (toggles with the 600ms tick) so it reads as a
              live text field; the off-frame is a plain space to hold the width. */}
          {live ? (
            <Text color={t.color.text} inverse>
              {' '}
            </Text>
          ) : (
            <Text>{' '}</Text>
          )}
        </Box>
      ) : null}
    </Box>
  )

  const chips: FooterChip[] = composing
    ? [
        { k: '⏎', label: 'Send' },
        { k: '↑↓', label: 'Scroll' },
        { k: '⎋', label: 'Back', run: () => setFocus('list') }
      ]
    : [
        { k: '↑↓', label: 'Chats' },
        { k: '⏎', label: 'Open', run: () => activeConv && setFocus('thread') },
        { k: 'n', label: 'New message', run: () => { setNewNumber(''); setNewName(''); setNewField('number'); setNewChat(true) } },
        { k: 'r', label: 'Reconnect', run: reconnect },
        { k: 'q', label: 'Close', run: onClose }
      ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        {composing
          ? 'type to write · ⏎ send · ↑↓/wheel scroll history · Esc back to chats'
          : '↑↓/jk chats · ⏎/→ open & write · n new message · r reconnect · Esc/q close'}
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {rail}
        {thread}
      </Box>
      {footer}
    </Box>
  )
}
