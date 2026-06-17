import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
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
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)
  const [flash, setFlash] = useState('')
  const [composing, setComposing] = useState(false)
  const [draft, setDraft] = useState('')

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

    const ids = new Set<string>([
      ...contacts.map(c => c.id),
      ...groups.map(g => `group:${g.id}`),
      ...Object.keys(cache)
    ])

    const list: Conversation[] = [...ids].map(chatId => {
      const msgs = cache[chatId] ?? []
      const last = msgs[msgs.length - 1]
      const preview = last ? `${last.fromMe ? 'You: ' : ''}${last.text || (last.attachments ? '📎 attachment' : '')}` : ''

      return {
        chatId,
        hasMessages: msgs.length > 0,
        lastText: preview,
        lastTs: last?.timestamp ?? 0,
        name: nameById.get(chatId) || (chatId.startsWith('group:') ? 'Signal group' : chatId)
      }
    })

    list.sort((a, b) => b.lastTs - a.lastTs || a.name.localeCompare(b.name))

    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contacts, groups, cacheVersion])

  const clampedSel = Math.min(sel, Math.max(0, conversations.length - 1))
  const activeConv = conversations[clampedSel]
  const threadMessages = activeConv ? cacheRef.current[activeConv.chatId] ?? [] : []

  const sendDraft = () => {
    const text = draft.trim()
    setComposing(false)
    setDraft('')

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

    if (composing) {
      if (key.escape) {
        setComposing(false)
        setDraft('')

        return
      }

      if (key.return) {
        return sendDraft()
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

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 's') {
      return setSetup(true)
    }

    if (ch === 'r') {
      return reconnect()
    }

    if (!connected) {
      return
    }

    if ((ch === 'i' || key.return) && activeConv) {
      setDraft('')

      return setComposing(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, conversations.length - 1), i + 1))
    }
  })

  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 7)
  const live = tick % 2 === 0
  const railWidth = Math.min(32, Math.max(24, Math.floor(width * 0.32)))
  const railRows = Math.max(3, contentHeight - 2)

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

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MESSAGING
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={statusDot}>●</Text>
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

  const rail = (
    <Box
      {...RIGHT_RULE}
      borderColor={t.color.border}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={railWidth}
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        CHATS{conversations.length ? <Text color={t.color.muted}>{`  (${conversations.length})`}</Text> : null}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {windowedConvs.length > 0 ? (
          windowedConvs.map((conv, i) => {
            const idx = listStart + i
            const on = idx === clampedSel

            return (
              <Box flexDirection="column" key={conv.chatId} marginBottom={1} onClick={() => setSel(idx)}>
                <Box justifyContent="space-between" width="100%">
                  <Box>
                    <Text color={on ? t.color.accent : t.color.muted}>{on ? '▸ ' : '  '}</Text>
                    <Text bold={on} color={on ? t.color.text : t.color.label} wrap="truncate-end">
                      {truncate(conv.name, railWidth - 10)}
                    </Text>
                  </Box>
                  <Text color={t.color.border}>{relTime(conv.lastTs)}</Text>
                </Box>
                <Text color={t.color.muted} wrap="truncate-end">
                  {'     '}
                  {conv.lastText || '—'}
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
  const recent = threadMessages.slice(-60)

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
      <Text bold color={t.color.label} wrap="truncate-end">
        {activeConv ? truncate(activeConv.name, 40) : 'SIGNAL'}
        {activeConv?.chatId.startsWith('group:') ? <Text color={t.color.muted}> · group</Text> : null}
      </Text>

      {!connected ? (
        <Box flexDirection="column" flexGrow={1} marginTop={1}>
          <Text color={reachable === false ? t.color.error : t.color.muted} wrap="wrap">
            {reachable === false
              ? `Can't reach signal-cli at ${cfg.httpUrl}. Start the daemon (signal-cli -a ${cfg.account} daemon --http 127.0.0.1:8080) and press r.`
              : 'Connecting to signal-cli…'}
          </Text>
        </Box>
      ) : (
        <Box flexDirection="column" flexGrow={1} justifyContent="flex-end" marginTop={1} overflow="hidden">
          {recent.length === 0 ? (
            <Text color={t.color.muted} wrap="wrap">
              No messages in this conversation yet. Press i (or Enter) to write one.
            </Text>
          ) : (
            recent.map((m, i) => {
              const label = m.fromMe ? 'You' : truncate(activeConv?.chatId.startsWith('group:') ? m.author : activeConv?.name ?? m.author, 24)

              return (
                <Box flexDirection="column" key={`${m.timestamp}:${i}`} marginBottom={1}>
                  <Text wrap="truncate-end">
                    <Text bold color={m.fromMe ? t.color.ok : t.color.accent}>
                      {label}
                    </Text>
                    <Text color={t.color.muted}>{`  ${clock(m.timestamp)}`}</Text>
                  </Text>
                  <Text color={t.color.text} wrap="wrap">
                    {m.text || (m.attachments ? '📎 attachment' : '')}
                  </Text>
                </Box>
              )
            })
          )}
        </Box>
      )}

      {/* Compose line — only while composing, so the resting view has no cursor. */}
      {composing ? (
        <Box borderColor={t.color.accent} borderStyle="round" flexShrink={0} marginTop={1} paddingX={1}>
          <Text color={t.color.muted}>{'› '}</Text>
          <Text color={t.color.text}>{draft}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
        </Box>
      ) : null}
    </Box>
  )

  const chips: FooterChip[] = composing
    ? [
        { k: '⏎', label: 'Send' },
        { k: '⎋', label: 'Cancel' }
      ]
    : [
        { k: '↑↓', label: 'Chats' },
        { k: 'i', label: 'Write', run: () => activeConv && setComposing(true) },
        { k: 'r', label: 'Reconnect', run: reconnect },
        { k: 'q', label: 'Close', run: onClose }
      ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        {composing ? '⏎ send · Esc cancel' : '↑↓/jk chats · i/⏎ write · r reconnect · Esc/q close'}
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
