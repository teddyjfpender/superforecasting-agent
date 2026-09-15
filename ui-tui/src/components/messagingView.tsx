import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useStdout } from '@superforecasting/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay, patchOverlayState } from '../app/overlayStore.js'
import { statusGlyph, type StatusKind } from '../lib/icons.js'
import { sendDeskMessage } from '../lib/messagingSend.js'
import { $chatState, $messagingStorageError, openQuickMessage, updateChatState } from '../lib/messagingState.js'
import { openAttachment } from '../lib/openAttachment.js'
import { attachmentLabel, checkHealth, createGroup, type SignalMessage } from '../lib/signalClient.js'
import { isValidNumber, normalizeNumber, upsertContact } from '../lib/signalContacts.js'
import { restartDaemon } from '../lib/signalDaemon.js'
import {
  $signalDirectory,
  persistDirectory,
  refreshSignalDirectory,
  watchSignalDirectory
} from '../lib/signalDirectory.js'
import {
  markChatRead,
  signalCache,
  signalConnected,
  signalUnread,
  signalVersion,
  startSignalReceiver,
  subscribeSignal
} from '../lib/signalLive.js'
import { resolveSignalConfig } from '../lib/signalStore.js'
import { useViewInput } from '../lib/useViewInput.js'
import type { Theme } from '../theme.js'

import { ContactPicker } from './contactPicker.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import { ModalOverlay } from './modalOverlay.js'
import { SignalSetupModal } from './signalSetupModal.js'
import { TextInput } from './textInput.js'

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
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  const [cfg, setCfg] = useState<ReturnType<typeof resolveSignalConfig>>(() => resolveSignalConfig())
  const [setup, setSetup] = useState(false)

  const [reachable, setReachable] = useState<boolean | null>(cfg ? null : false)
  // Selection is by chatId (stable), not list index — the list re-sorts by
  // recency when you send/receive, so an index would jump to another chat.
  const [selectedChatId, setSelectedChatId] = useState<null | string>(null)
  const [tick, setTick] = useState(0)
  const [flash, setFlash] = useState('')
  const [draft, setDraft] = useState('')
  const desk = useStore($chatState)
  const storageError = useStore($messagingStorageError)
  const [filter, setFilter] = useState('Inbox')
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [categoryEdit, setCategoryEdit] = useState<string | null>(null)
  const sendingRef = useRef(false)

  const filters = [
    'Inbox',
    'Unread',
    'Pinned',
    'Groups',
    'Archived',
    ...new Set(
      Object.values(desk)
        .map(c => c.category)
        .filter((v): v is string => Boolean(v))
    )
  ]

  // Focus: the chat LIST, or an open THREAD. In a thread the composer is ALWAYS
  // active (you can type the moment you open a chat — no extra keystroke), and
  // arrows/wheel scroll the history. `threadScroll` counts messages scrolled up
  // from the latest.
  const [focus, setFocus] = useState<'list' | 'thread'>('list')
  const [threadScroll, setThreadScroll] = useState(0)
  const threadRef = useRef<ScrollBoxHandle>(null)
  const composeRef = useRef<ScrollBoxHandle>(null)
  const composing = focus === 'thread'

  // Persisted address book (names/numbers) + the "new message" composer.
  const contactBook = useStore($signalDirectory)
  const [memberPicker, setMemberPicker] = useState(false)
  const [newChat, setNewChat] = useState(false)
  const [newMode, setNewMode] = useState<'direct' | 'group'>('direct')
  // Reused across modes: in 'direct' newNumber=recipient, newName=contact name;
  // in 'group' newNumber=member-being-typed, newName=group name, groupMembers=added.
  const [newNumber, setNewNumber] = useState('')
  const [newName, setNewName] = useState('')
  const [newField, setNewField] = useState<'name' | 'number'>('number')
  const [groupMembers, setGroupMembers] = useState<string[]>([])

  // Contact card (press c): view + rename the highlighted chat's contact.
  const [contactView, setContactView] = useState(false)
  const [editName, setEditName] = useState('')

  // The message cache + unread set live in the app-level singleton receiver
  // (so nothing is lost when this view is closed). Mirror its version into local
  // state so this view re-renders when a message lands while it's open.
  const [cacheVersion, setCacheVersion] = useState(signalVersion())
  const streaming = signalConnected()
  const unread = signalUnread()
  const aliveRef = useRef(true)

  useEffect(() => subscribeSignal(() => setCacheVersion(signalVersion())), [])

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  // Receive before directory synchronization, then poll without overlapping calls:
  // a phone may deliver its contact response well after the initial RPC returns.
  useEffect(() => {
    if (!cfg) {
      return
    }

    let alive = true
    const unwatch = watchSignalDirectory(cfg)

    const refresh = async () => {
      const ok = await checkHealth(cfg)

      if (!alive) {
        return
      }

      setReachable(ok)

      if (ok) {
        startSignalReceiver(cfg)
      }
    }

    void refresh()

    const timer = setInterval(() => {
      void refresh()
    }, 15000)

    return () => {
      alive = false
      clearInterval(timer)
      unwatch()
    }
  }, [cfg])

  const conversations = useMemo<Conversation[]>(() => {
    const cache = signalCache()
    const nameById = new Map<string, string>()

    // The persisted book fills in names the live daemon didn't resolve (and
    // surfaces chats — e.g. a number you just started — that have no history).
    for (const [id, c] of Object.entries(contactBook)) {
      if (c.name) {
        nameById.set(id, c.name)
      }
    }

    const ids = new Set<string>([...Object.keys(desk), ...Object.keys(contactBook), ...Object.keys(cache)])

    const list: Conversation[] = [...ids].map(chatId => {
      const msgs = cache[chatId] ?? []
      const last = msgs[msgs.length - 1]
      const preview = last ? `${last.fromMe ? 'You: ' : ''}${last.text || attachmentLabel(last)}` : ''

      return {
        chatId,
        hasMessages: msgs.length > 0,
        lastText: preview,
        lastTs: last?.timestamp ?? 0,
        name: displayName(chatId, nameById.get(chatId))
      }
    })

    list.sort(
      (a, b) =>
        Number(Boolean(desk[b.chatId]?.pinned)) - Number(Boolean(desk[a.chatId]?.pinned)) ||
        b.lastTs - a.lastTs ||
        a.name.localeCompare(b.name)
    )

    return list.filter(c => {
      const meta = desk[c.chatId]

      if (filter === 'Archived' ? !meta?.archived : meta?.archived) {
        return false
      }

      if (filter === 'Unread' && !unread.has(c.chatId) && !(focus === 'thread' && c.chatId === selectedChatId)) {
        return false
      }

      if (filter === 'Pinned' && !meta?.pinned) {
        return false
      }

      if (filter === 'Groups' && !c.chatId.startsWith('group:')) {
        return false
      }

      if (!['Inbox', 'Unread', 'Pinned', 'Groups', 'Archived'].includes(filter) && meta?.category !== filter) {
        return false
      }

      return `${c.name} ${c.chatId} ${meta?.category || ''} ${c.lastText}`.toLowerCase().includes(query.toLowerCase())
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contactBook, cacheVersion, desk, filter, query, focus, selectedChatId])

  const foundIndex = conversations.findIndex(c => c.chatId === selectedChatId)
  const clampedSel = foundIndex >= 0 ? foundIndex : 0
  const activeConv = conversations[clampedSel]
  const threadMessages = activeConv ? (signalCache()[activeConv.chatId] ?? []) : []

  const activeChatId = activeConv?.chatId
  useEffect(() => {
    setDraft(activeChatId ? $chatState.get()[activeChatId]?.draft || '' : '')
  }, [activeChatId])

  const editDraft = (update: string | ((previous: string) => string)) => {
    const next = typeof update === 'function' ? update(draft) : update
    setDraft(next)

    if (activeConv) {
      updateChatState(activeConv.chatId, { draft: next })
    }
  }

  // Layout + thread-window geometry (needed by both the key handler and render).
  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(6, termRows - (cols >= 110 ? 9 : 11))
  const railWidth = Math.min(40, Math.max(26, Math.floor(width * 0.34)))
  const railRows = Math.max(3, contentHeight - 2)
  // Rows available for messages: header + marginTop + (composer when writing).
  const composerRows = composing ? 3 : 0
  const msgRows = Math.max(1, contentHeight - 2 - composerRows)
  useEffect(() => {
    if (threadScroll === 0) {
      threadRef.current?.scrollToBottom()
    }
  }, [cacheVersion, threadScroll, activeChatId])

  // Reset the scroll to the latest whenever the open conversation changes.
  useEffect(() => {
    setThreadScroll(0)
    threadRef.current?.scrollToBottom()
  }, [activeConv?.chatId])

  // Opening / viewing a chat clears its unread flag (also when a new message
  // lands while it's open — hence the cacheVersion dep).
  useEffect(() => {
    if (
      focus !== 'thread' ||
      !activeConv ||
      threadScroll !== 0 ||
      globalModal ||
      setup ||
      newChat ||
      contactView ||
      categoryEdit !== null
    ) {
      return
    }

    markChatRead(activeConv.chatId)
  }, [activeConv, cacheVersion, focus, threadScroll, globalModal, setup, newChat, contactView, categoryEdit])

  // Start a conversation with a typed number: validate, save it to the address
  // book (so the name persists), then select + open it (chatId selection means
  // it resolves as soon as the book update lands it in the list).
  // Open the new-message composer fresh (direct mode, empty fields).
  const openNewChat = () => {
    setNewMode('direct')
    setMemberPicker(false)
    setNewNumber('')
    setNewName('')
    setNewField('number')
    setGroupMembers([])
    setNewChat(true)
  }

  // Add the typed number to the pending group's member list (deduped, valid).
  const addGroupMember = () => {
    const number = normalizeNumber(newNumber)

    if (!isValidNumber(number)) {
      setFlash('enter a valid number, e.g. +12674553945')

      return
    }

    setGroupMembers(ms => (ms.includes(number) ? ms : [...ms, number]))
    setNewNumber('')
  }

  // Create the group via signal-cli, then open it. Saves the name to the book.
  const createGroupChat = () => {
    const name = newName.trim()

    if (!name) {
      setFlash('group needs a name')

      return
    }

    if (groupMembers.length === 0) {
      setFlash('add at least one member')

      return
    }

    if (!cfg) {
      setFlash('connect Signal first')

      return
    }

    const members = [...groupMembers]
    const activeCfg = cfg
    setNewChat(false)
    setNewName('')
    setNewNumber('')
    setGroupMembers([])
    setNewField('number')
    setNewMode('direct')
    setFlash('creating group…')

    void (async () => {
      const { error, groupId } = await createGroup(activeCfg, name, members)

      if (!aliveRef.current) {
        return
      }

      if (error || !groupId) {
        setFlash(`group failed: ${error ?? 'unknown'}`)

        return
      }

      const chatId = `group:${groupId}`
      const book = upsertContact(contactBook, { chatId, name })

      if (!persistDirectory(book)) {
        setFlash('Could not save contact')

        return
      }

      setSelectedChatId(chatId)
      setThreadScroll(0)
      setFocus('thread')
      setFlash(`group created · ${name}`)
    })()
  }

  // Contact card: prefill the editable name with the saved one (blank = unnamed).
  const openContact = () => {
    if (!activeConv) {
      return
    }

    setEditName(contactBook[activeConv.chatId]?.name ?? '')
    setContactView(true)
  }

  const saveContact = () => {
    if (activeConv) {
      const book = upsertContact(contactBook, { chatId: activeConv.chatId, name: editName })

      if (!persistDirectory(book)) {
        setFlash('Could not save contact')

        return
      }

      setFlash(`contact saved${editName.trim() ? ` · ${editName.trim()}` : ''}`)
    }

    setContactView(false)
  }

  // Open a message's first attachment in the OS default app (signal-cli saved
  // it on receive). Clickable in the thread; Ctrl+O opens the latest.
  const openMessageAttachment = (m: SignalMessage) => {
    const file = (m.files ?? []).find(f => f.id)

    if (!file?.id) {
      setFlash('attachment not available to open')

      return
    }

    const { error } = openAttachment(file.id)
    setFlash(error ? `open failed: ${error}` : `opening ${file.name || 'attachment'}…`)
  }

  const openLatestAttachment = () => {
    for (let i = threadMessages.length - 1; i >= 0; i--) {
      if ((threadMessages[i].files ?? []).some(f => f.id)) {
        return openMessageAttachment(threadMessages[i])
      }
    }

    setFlash('no attachments in this chat')
  }

  const sendDraft = (value = draft) => {
    const text = value.trim()

    if (!text || !activeConv || !cfg || sendingRef.current) {
      return
    }

    const id = activeConv.chatId
    sendingRef.current = true
    setFlash('sending…')
    void sendDeskMessage(cfg, id, text).then(error => {
      sendingRef.current = false

      if (!error && $chatState.get()[id]?.draft?.trim() === text) {
        updateChatState(id, { draft: '' })
      }

      if (!aliveRef.current) {
        return
      }

      setFlash(error || 'sent')

      if (!error) {
        setDraft(current => (current.trim() === text ? '' : current))
        setThreadScroll(0)
      }
    })
  }

  // Force-restart the daemon: recovers a stalled receiver that still answers
  // /api/v1/check (so `r` reconnect alone can't fix it) — the common "stopped
  // receiving" cause. Re-resolves cfg afterwards so the receive stream re-opens
  // against the fresh daemon.
  const restartDaemonAndReconnect = () => {
    if (!cfg) {
      return
    }

    setFlash('restarting daemon…')

    void (async () => {
      const { error } = await restartDaemon(cfg.account)

      if (!aliveRef.current) {
        return
      }

      if (error) {
        setFlash(`restart failed: ${error}`)

        return
      }

      setFlash('daemon restarted — reconnecting')
      setReachable(null)
      setCfg(resolveSignalConfig())
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
        startSignalReceiver(cfg)
        await refreshSignalDirectory(cfg, true)

        if (aliveRef.current) {
          setFlash('directory refreshed; phone sync may take a moment')
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

  const handleFooterKey = useViewInput(
    (ch, key) => {
      // While the setup modal is open it owns all input.
      if (setup) {
        return
      }

      // New-message composer: Direct (a number) or Group (name + members).
      // Tab/←→ switch mode, ↑↓ switch field, Enter acts per mode/field.
      if (newChat && (newMode === 'direct' || memberPicker)) {
        return
      }

      if (newChat) {
        if (key.ctrl && ch === 'f') {
          return setMemberPicker(true)
        }

        if (key.escape) {
          return setNewChat(false)
        }

        if (key.tab || key.leftArrow || key.rightArrow) {
          const next = newMode === 'direct' ? 'group' : 'direct'
          setNewMode(next)
          setNewField(next === 'group' ? 'name' : 'number')

          return
        }

        if (key.upArrow || key.downArrow) {
          return setNewField(f => (f === 'number' ? 'name' : 'number'))
        }

        if (key.return) {
          // Group: name → member, then type+⏎ adds, empty ⏎ creates.
          if (newField === 'name') {
            return setNewField('number')
          }

          return newNumber.trim() ? addGroupMember() : createGroupChat()
        }

        if (key.backspace || key.delete) {
          // Empty member field + Backspace removes the last added member.
          if (newMode === 'group' && newField === 'number' && !newNumber) {
            return setGroupMembers(ms => ms.slice(0, -1))
          }

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

      // Contact card: edit the saved name for the highlighted chat.
      if (contactView) {
        if (key.escape) {
          return setContactView(false)
        }

        if (key.return) {
          return saveContact()
        }

        if (key.backspace || key.delete) {
          return setEditName(s => s.slice(0, -1))
        }

        if (ch && !key.ctrl && !key.meta) {
          const printable = [...ch].filter(c => c >= ' ').join('')

          if (printable) {
            setEditName(s => s + printable)
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
          return setFocus('list')
        }

        if (key.pageUp || key.wheelUp) {
          threadRef.current?.scrollBy(key.pageUp ? -msgRows : -3)

          return setThreadScroll(1)
        }

        if (key.pageDown || key.wheelDown) {
          const delta = key.pageDown ? msgRows : 3
          threadRef.current?.scrollBy(delta)

          if (
            (threadRef.current?.getScrollTop() || 0) + msgRows + delta >=
            (threadRef.current?.getScrollHeight() || 0)
          ) {
            setThreadScroll(0)
          }

          return
        }

        if (key.ctrl && ch.toLowerCase() === 'o') {
          return openLatestAttachment()
        }

        return
      }

      if (categoryEdit !== null) {
        if (key.escape) {
          return setCategoryEdit(null)
        }

        if (key.return && activeConv) {
          updateChatState(activeConv.chatId, { category: categoryEdit.trim() })
          setCategoryEdit(null)

          return
        }

        if (key.backspace || key.delete) {
          return setCategoryEdit(v => v?.slice(0, -1) || '')
        }

        if (ch && !key.ctrl && !key.meta) {
          setCategoryEdit(v => (v + ch).slice(0, 80))
        }

        return
      }

      if (searching) {
        if (key.escape) {
          setSearching(false)
          setQuery('')

          return
        }

        if (key.return) {
          return setSearching(false)
        }

        if (key.backspace || key.delete) {
          return setQuery(v => v.slice(0, -1))
        }

        if (ch && !key.ctrl && !key.meta) {
          setQuery(v => v + ch)
        }

        return
      }

      if (ch === '/') {
        return setSearching(true)
      }

      if (ch === 'm') {
        return openQuickMessage()
      }

      if (ch === 'p' && activeConv) {
        updateChatState(activeConv.chatId, { pinned: !desk[activeConv.chatId]?.pinned })

        return
      }

      if (ch === 'x' && activeConv) {
        updateChatState(activeConv.chatId, { archived: !desk[activeConv.chatId]?.archived })

        return
      }

      if (ch === 'C' && activeConv) {
        return setCategoryEdit(desk[activeConv.chatId]?.category || '')
      }

      if (key.tab || key.leftArrow || ch === '[' || ch === ']') {
        const delta = key.shift || key.leftArrow || ch === '[' ? -1 : 1
        setFilter(filters[(filters.indexOf(filter) + delta + filters.length) % filters.length]!)

        return
      }

      // List focus.
      if (ch === 'q' || key.escape) {
        return onClose()
      }

      // `h` opens the unified Help modal — consistent on every view (list focus;
      // the setup / new-chat / contact / composer guards above already returned).
      if (ch === 'h' || ch === '?') {
        return openHelpOverlay()
      }

      // Setup is only reachable when not connected — so an accidental 's' can't
      // relaunch onboarding mid-session.
      if (ch === 's' && !connected) {
        return setSetup(true)
      }

      if (ch === 'r') {
        return reconnect()
      }

      if (ch === 'R') {
        return restartDaemonAndReconnect()
      }

      if (ch === 'c' && activeConv) {
        return openContact()
      }

      if (ch === 'n' || ch === 'f') {
        return openNewChat()
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
    },
    { isActive: !globalModal }
  )

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
        <Text color={t.color.muted}> · {unread.size} unread chats</Text>
        {cfg ? <Text color={t.color.muted}>{`  ${cfg.account}`}</Text> : null}
      </Text>
    </Box>
  )

  // ---- Setup modal (press s) — overlays the body --------------------------
  // SignalSetupModal renders THROUGH ModalOverlay itself + owns its own keyboard.
  const setupOverlay = setup ? (
    <SignalSetupModal cols={cols} onCancel={() => setSetup(false)} onConnected={onConnected} rows={termRows} t={t} />
  ) : null

  // ---- New-message composer (press n): Direct message or new Group -------
  // Built as ModalOverlay children (a form — no scrollRef); the view's useInput
  // owns its keys (Tab/↑↓/⏎/Esc) while `newChat` is open.
  const newChatOverlay = (() => {
    if (!newChat) {
      return null
    }

    if (newMode === 'direct' || memberPicker) {
      return (
        <ContactPicker
          cols={cols}
          contactsOnly={memberPicker}
          onCancel={() => (memberPicker ? setMemberPicker(false) : setNewChat(false))}
          onNewGroup={
            memberPicker
              ? undefined
              : () => {
                  setNewMode('group')
                  setNewField('name')
                }
          }
          onSelect={id => {
            if (memberPicker) {
              setGroupMembers(ms => (ms.includes(id) ? ms : [...ms, id]))
              setMemberPicker(false)

              return
            }

            if (!persistDirectory(upsertContact(contactBook, { chatId: id }))) {
              return
            }

            setFilter(desk[id]?.archived ? 'Archived' : 'Inbox')
            setQuery('')
            setSelectedChatId(id)
            setThreadScroll(0)
            setFocus('thread')
            setNewChat(false)
          }}
          rows={termRows}
          t={t}
          title={memberPicker ? 'ADD GROUP MEMBER' : 'FIND CONTACT OR CHAT'}
        />
      )
    }

    const memberRows = Math.max(1, Math.min(8, termRows - 19))

    return (
      <ModalOverlay
        cols={cols}
        footerHint="^F find members · Enter add/create · ↑↓ field · Tab direct · Esc cancel"
        maxHeight={26}
        maxWidth={100}
        rows={termRows}
        t={t}
        title="NEW SIGNAL GROUP"
      >
        <Box flexDirection="column" flexGrow={1} minHeight={0}>
          <Text color={newField === 'name' ? t.color.accent : t.color.muted} wrap="truncate-end">
            Name › {newName || 'Group name'}
            {newField === 'name' ? '▌' : ''}
          </Text>
          <Text color={newField === 'number' ? t.color.accent : t.color.muted} wrap="truncate-end">
            Member › {newNumber || 'Ctrl+F to find, or type +number'}
            {newField === 'number' ? '▌' : ''}
          </Text>
          <Box flexDirection="column" flexGrow={1} marginTop={1} minHeight={0} overflow="hidden">
            <Text bold color={t.color.label}>
              MEMBERS · {groupMembers.length}
            </Text>
            {groupMembers.slice(-memberRows).map(id => (
              <Text color={t.color.text} key={id} wrap="truncate-end">
                {contactBook[id]?.name || id} · {id}
              </Text>
            ))}
            {!groupMembers.length && (
              <Text color={t.color.muted}>
                Choose contacts with Ctrl+F. Nothing is sent until you create the group.
              </Text>
            )}
          </Box>
          <Text color={t.color.warn} wrap="truncate-end">
            {flash || 'Enter with an empty member field creates the group.'}
          </Text>
        </Box>
      </ModalOverlay>
    )
  })()

  // ---- Contact card (press c) ---------------------------------------------
  // Contact card — an overlay (NOT a body replacement) so the conversation stays
  // visible behind it, consistent with the rest of the views.
  const contactOverlay =
    contactView && activeConv
      ? (() => {
          const saved = contactBook[activeConv.chatId]

          const row = (label: string, value: string, color = t.color.text) => (
            <Text wrap="truncate-end">
              <Text color={t.color.label}>{label.padEnd(9)}</Text>
              <Text color={value ? color : t.color.muted}>{value || '—'}</Text>
            </Text>
          )

          return (
            <ModalOverlay
              cols={cols}
              footerHint="⏎ save name · Esc cancel"
              maxHeight={16}
              maxWidth={90}
              rows={termRows}
              t={t}
              title="Contact"
            >
              <Box flexDirection="column">
                <Box>
                  <Text bold color={t.color.accent}>
                    {'Name'.padEnd(9)}
                  </Text>
                  <Text color={t.color.muted}>{'› '}</Text>
                  <Text color={t.color.text}>{editName}</Text>
                  {live ? (
                    <Text color={t.color.text} inverse>
                      {' '}
                    </Text>
                  ) : (
                    <Text> </Text>
                  )}
                  {!editName ? <Text color={t.color.muted}> (no name set)</Text> : null}
                </Box>
                {row('Signal', saved?.aliases?.join(' · ') || '')}
                {row('Name from', saved?.nameSource === 'signal' ? 'Signal profile/contact' : 'Saved local label')}
                {row('Number', activeConv.chatId.startsWith('group:') ? '' : saved?.number || activeConv.chatId)}
                {row(activeConv.chatId.startsWith('group:') ? 'Group' : 'Chat id', activeConv.chatId, t.color.muted)}
                {row(
                  'Added',
                  saved?.addedAt
                    ? new Date(saved.addedAt).toLocaleDateString('en-US', {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric'
                      })
                    : '',
                  t.color.muted
                )}
              </Box>
            </ModalOverlay>
          )
        })()
      : null

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
          <FooterChips
            chips={[
              { k: 's', label: 'Set up', run: () => setSetup(true) },
              { k: 'h', label: 'Help', run: openHelpOverlay },
              { k: 'q', label: 'Close', run: onClose }
            ]}
            disabled={setup || globalModal}
            onKey={handleFooterKey}
            t={t}
          />
          {storageError && <Text color={t.color.error}>{storageError}</Text>}
          {flash ? (
            <Text color={t.color.accent} wrap="truncate-end">
              {flash}
            </Text>
          ) : null}
        </Box>
        {/* Modals overlay even the not-configured prompt (setup opens from here). */}
        {categoryEdit !== null && (
          <ModalOverlay
            cols={cols}
            footerHint="Enter save · Esc cancel · empty removes category"
            maxHeight={10}
            rows={termRows}
            t={t}
            title="CHAT CATEGORY"
          >
            <Text color={t.color.text}>{categoryEdit}▌</Text>
          </ModalOverlay>
        )}
        {setup ? setupOverlay : newChat ? newChatOverlay : null}
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
          // Single line per chat — name then a dim message preview right after
          // (no big gap), with an unread dot + highlight. One line keeps the
          // fixed-height window from desyncing/ghosting on scroll.
          windowedConvs.map((conv, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            const isUnread = unread.has(conv.chatId)
            const nameMax = Math.min(16, Math.max(8, Math.floor(railWidth * 0.42)))
            const previewW = Math.max(0, railWidth - 2 - nameMax - 1)
            const prefix = on ? '▸ ' : isUnread ? '● ' : '  '

            return (
              <Box
                key={conv.chatId}
                onClick={() => {
                  if (setup || newChat || contactView || globalModal) {
                    return
                  }

                  setSelectedChatId(conv.chatId)
                  setThreadScroll(0)
                  setFocus('thread')
                }}
                width="100%"
              >
                <Text wrap="truncate-end">
                  <Text bold={isUnread} color={on ? t.color.accent : isUnread ? t.color.ok : t.color.border}>
                    {prefix}
                  </Text>
                  <Text bold={on || isUnread} color={on || isUnread ? t.color.text : t.color.label}>
                    {truncate(conv.name, nameMax).padEnd(nameMax)}
                  </Text>
                  {previewW > 4 && conv.lastText ? (
                    <Text color={isUnread ? t.color.muted : t.color.border}> {truncate(conv.lastText, previewW)}</Text>
                  ) : null}
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

  const thread = (
    <Box
      flexDirection="column"
      flexGrow={1}
      flexShrink={1}
      height={contentHeight}
      marginLeft={1}
      minWidth={0}
      overflow="hidden"
    >
      <Text bold={threadFocused} color={threadFocused ? t.color.accent : t.color.label} wrap="truncate-end">
        {threadFocused ? '▸ ' : ''}
        {activeConv ? truncate(activeConv.name, 32) : 'SIGNAL'}
        {activeConv?.chatId.startsWith('group:') ? <Text color={t.color.muted}> · group</Text> : null}
        {threadFocused && threadScroll > 0 ? <Text color={t.color.muted}> · reading history</Text> : null}
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
        <ScrollBox
          decstbm={false}
          flexDirection="column"
          flexShrink={0}
          followContent={false}
          height={msgRows}
          marginTop={1}
          ref={threadRef}
        >
          {threadMessages.length === 0 ? (
            <Text color={t.color.muted} wrap="wrap">
              No locally saved messages. Phone history is not imported; new messages appear while the desk is connected.
            </Text>
          ) : (
            threadMessages.map((m, i) => {
              const gi = i
              const showHeader = headerForMsg[gi]

              const label = m.fromMe
                ? 'You'
                : truncate(
                    activeConv?.chatId.startsWith('group:')
                      ? contactBook[m.author]?.name || m.authorName || m.author
                      : (activeConv?.name ?? m.author),
                    24
                  )

              return (
                <Box
                  flexDirection="column"
                  flexShrink={0}
                  key={`${m.timestamp}:${gi}`}
                  marginTop={showHeader && i > 0 ? 1 : 0}
                >
                  {showHeader ? (
                    <Text wrap="truncate-end">
                      <Text bold color={m.fromMe ? t.color.ok : t.color.accent}>
                        {label}
                      </Text>
                      <Text color={t.color.muted}>{`  ${clock(m.timestamp)}`}</Text>
                    </Text>
                  ) : null}
                  {m.text ? (
                    <Text color={t.color.text} wrap="wrap">
                      {m.text}
                    </Text>
                  ) : null}
                  {m.attachments > 0 ? (
                    <Box
                      onClick={() => {
                        if (!setup && !newChat && !contactView && !globalModal) {
                          openMessageAttachment(m)
                        }
                      }}
                    >
                      <Text color={t.color.accent} wrap="truncate-end">
                        {attachmentLabel(m)}
                        {(m.files ?? []).some(f => f.id) ? <Text color={t.color.muted}> · open</Text> : null}
                      </Text>
                    </Box>
                  ) : null}
                </Box>
              )
            })
          )}
        </ScrollBox>
      )}

      {/* Native bottom composer — sits below the history, doesn't overlap it. */}
      {composing ? (
        <ScrollBox decstbm={false} flexShrink={0} followContent={false} height={3} ref={composeRef}>
          <TextInput
            columns={Math.max(15, cols - railWidth - (cols >= 110 ? 18 : 0) - 7)}
            focus={!globalModal && !setup && !newChat && !contactView}
            immediateChange
            key={activeChatId}
            onChange={editDraft}
            onCursorLine={line => composeRef.current?.scrollTo(Math.max(0, line - 2))}
            onSubmit={sendDraft}
            placeholder="Write a message…"
            value={draft}
          />
        </ScrollBox>
      ) : null}
    </Box>
  )

  // One chips row carries every live key — including the daemon controls (r / R)
  // and attachment-open (^O) the old prose row had to spell out separately.
  const chips: FooterChip[] = composing
    ? [
        { k: '⏎', label: 'Send', run: () => sendDraft() },
        { k: 'PgUp/Dn', label: 'History' },
        { k: '^O', label: 'Attachment', run: openLatestAttachment },
        { k: '⎋', label: 'Back', run: () => setFocus('list') }
      ]
    : [
        { k: '↑↓', label: 'Chats' },
        { k: '⏎', label: 'Open', run: () => activeConv && setFocus('thread') },
        { k: 'p', label: 'Pin' },
        { k: 'x', label: 'Archive' },
        { k: 'C', label: 'Category' },
        { k: 'm', label: 'Message', run: openQuickMessage },
        { k: 'c', label: 'Contact', run: openContact },
        { k: 'n', label: 'New / group', run: openNewChat },
        { k: 'f', label: 'Find', run: openNewChat },
        { k: 'r', label: 'Reconnect', run: reconnect },
        { k: 'R', label: 'Restart', run: restartDaemonAndReconnect },
        ...(connected ? [] : [{ k: 's', label: 'Set up', run: () => setSetup(true) }]),
        { k: 'h', label: 'Help', run: openHelpOverlay },
        { k: 'q', label: 'Close', run: onClose }
      ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips
        chips={chips}
        disabled={setup || newChat || contactView || globalModal || categoryEdit !== null}
        onKey={handleFooterKey}
        t={t}
      />
      {storageError || flash ? (
        <Text color={storageError ? t.color.error : t.color.accent} wrap="truncate-end">
          {storageError || flash}
        </Text>
      ) : null}
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexShrink={0} marginBottom={1}>
        <Text color={t.color.accent}>{filter}</Text>
        <Text color={t.color.muted}>
          {' '}
          · Tab collections · / search {query ? ` · ${query}` : ''}
          {searching ? '▌' : ''}
        </Text>
      </Box>
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {cols >= 110 && (
          <Box flexDirection="column" flexShrink={0} paddingRight={1} width={18}>
            <Text bold color={t.color.label}>
              COLLECTIONS
            </Text>
            {filters.map(name => (
              <Box
                key={name}
                onClick={() => {
                  if (!globalModal && !composing && !setup && !newChat && !contactView && categoryEdit === null) {
                    setFilter(name)
                  }
                }}
              >
                <Text bold={filter === name} color={filter === name ? t.color.accent : t.color.muted}>
                  {filter === name ? '› ' : '  '}
                  {name}
                </Text>
              </Box>
            ))}
          </Box>
        )}
        {rail}
        {thread}
      </Box>
      {footer}
      {/* Modals overlay the body (stacked LAST + absolutely positioned by
          ModalOverlay). The keyboard is trapped by the `if (setup)`/`if (newChat)`/
          `if (contactView)` early-returns in useInput; body mouse handlers gated above. */}
      {categoryEdit !== null && (
        <ModalOverlay
          cols={cols}
          footerHint="Enter save · Esc cancel · empty removes category"
          maxHeight={10}
          rows={termRows}
          t={t}
          title="CHAT CATEGORY"
        >
          <Text color={t.color.text}>{categoryEdit}▌</Text>
        </ModalOverlay>
      )}
      {setup ? setupOverlay : newChat ? newChatOverlay : contactView ? contactOverlay : null}
    </Box>
  )
}
