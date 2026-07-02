import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@hermes/ink'
import { type RefObject, useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { SessionListItem, SessionListResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

// A ChatGPT-style left rail of recent conversations, shown on the Home/landing
// screen alongside the Outrider hero. Click "New chat" to start fresh (the hero
// stays); click a past conversation to re-enter it. The list lives in its own
// ScrollBox: scroll it by hovering the rail with the wheel (routed by pointer
// column in useInputHandlers). Press Tab (or ← on an empty composer) to hand the
// keyboard to the rail — then ↑↓ move the selection and Enter opens it; Tab/→/Esc
// return to the conversation. The full keyboard session browser stays at
// /sessions.

// A one-line conversation label: prefer the title, else the first-message
// preview; collapse whitespace and strip a leading injected system-reminder
// block (e.g. "[IMPORTANT: ...]", often unclosed in a truncated preview) so the
// rail shows the real conversation, not prompt scaffolding.
const cleanLabel = (title?: string, preview?: string): string => {
  const s = (title?.trim() || preview?.trim() || '')
    .replace(/\s+/g, ' ')
    .replace(/^\[[^\]]*\]?\s*/, '')
    .trim()

  return s || '(untitled)'
}

interface ConversationsRailProps {
  currentSid: null | string
  // True when the rail holds keyboard focus (↑↓ navigate, Enter opens).
  focused?: boolean
  gw: GatewayClient
  // False while a global overlay (palette / cheat-sheet) paints above the
  // still-mounted home body: gates the rail's row clicks so they can't leak past
  // the overlay (the keyboard is gated separately via `focused`).
  interactive?: boolean
  onNewChat: () => void
  // Called after the rail acts on Enter, to hand focus back to the conversation.
  onExitFocus?: () => void
  onSelect: (id: string) => void
  // Bump to force a re-fetch (e.g. the active session changed).
  refreshKey?: string
  // Scroll handle for the list, so wheel-over-rail can scroll it independently.
  scrollRef: RefObject<null | ScrollBoxHandle>
  t: Theme
  width?: number
}

export function ConversationsRail({
  currentSid,
  focused = false,
  gw,
  interactive = true,
  onNewChat,
  onExitFocus,
  onSelect,
  refreshKey,
  scrollRef,
  t,
  width = 30
}: ConversationsRailProps) {
  const [items, setItems] = useState<SessionListItem[]>([])
  // Track the row the user clicked: resuming a session mints a NEW sid that
  // won't match the list id, so the parent's currentSid can't mark the active
  // chat — this can. Cleared on "New chat".
  const [clickedId, setClickedId] = useState<null | string>(null)
  // Keyboard selection. Row 0 is "New chat"; rows 1..items.length are the recent
  // conversations. Persists across focus toggles (and after click/Enter) so
  // re-entering the rail returns to where you left off, not the top.
  const [cursor, setCursor] = useState(0)
  const sel = Math.max(0, Math.min(cursor, items.length))

  const select = (index: number) => {
    setCursor(index)

    if (index === 0) {
      setClickedId(null)
      onNewChat()
    } else {
      const s = items[index - 1]

      if (s) {
        setClickedId(s.id)
        onSelect(s.id)
      }
    }

    // Opening a conversation (by click or Enter) hands focus back to it.
    onExitFocus?.()
  }

  // Land the cursor on the first conversation once the list first loads (so the
  // initial Tab-in lands on a real chat, not New chat). After that the cursor is
  // owned by the user — never auto-repositioned on focus changes.
  const positioned = useRef(false)

  useEffect(() => {
    if (positioned.current || !items.length) {
      return
    }

    positioned.current = true
    setCursor(1)
    // The ScrollBox auto-follows the bottom when content grows from an at-max
    // state, and the empty placeholder → loaded list is exactly that, so Recents
    // opened scrolled to the OLDEST chat. Pinning to the top on THIS tick loses
    // to that grow (the stick layout pass runs after this effect); pin on the
    // NEXT tick instead — by then the content height is settled (prevMaxScroll >
    // 0) so scrollTo(0) holds. (The ScrollBox is also remounted via `key` on the
    // empty→loaded flip, so the common case never sticks in the first place.)
    const id = setTimeout(() => scrollRef.current?.scrollTo(0), 0)

    return () => clearTimeout(id)
  }, [items.length, scrollRef])

  // Keep the selected conversation visible inside the list's ScrollBox (each
  // row is a single line, so the cursor index maps directly to a scroll line).
  useEffect(() => {
    if (!focused || sel < 1) {
      return
    }

    const s = scrollRef.current

    if (!s) {
      return
    }

    const line = sel - 1
    const top = s.getScrollTop()
    const vp = s.getViewportHeight()

    if (line < top) {
      s.scrollTo(line)
    } else if (vp > 0 && line >= top + vp) {
      s.scrollTo(line - vp + 1)
    }
  }, [focused, scrollRef, sel])

  useInput(
    (ch, key) => {
      if (key.upArrow || ch === 'k') {
        setCursor(c => Math.max(0, c - 1))

        return
      }

      if (key.downArrow || ch === 'j') {
        setCursor(c => Math.min(items.length, c + 1))

        return
      }

      if (key.return) {
        select(sel)
      }
    },
    { isActive: focused }
  )

  useEffect(() => {
    let alive = true
    gw.request<SessionListResponse>('session.list', { limit: 50 })
      .then(raw => {
        const r = asRpcResult<SessionListResponse>(raw)

        if (alive && r) {
          setItems(r.sessions ?? [])
        }
      })
      .catch(() => {
        /* a missing list just shows the empty state */
      })

    return () => {
      alive = false
    }
  }, [gw, refreshKey])

  return (
    <Box
      borderBottom={false}
      borderColor={focused ? t.color.primary : t.color.border}
      borderLeft={false}
      borderRight
      borderStyle="single"
      borderTop={false}
      flexDirection="column"
      flexShrink={0}
      minHeight={0}
      paddingRight={1}
      width={width}
    >
      <Box flexShrink={0} marginBottom={1}>
        <Text bold color={t.color.primary}>
          {t.brand.icon} {t.brand.name}
        </Text>
      </Box>

      <Box flexShrink={0} onClick={interactive ? () => select(0) : undefined}>
        <Text bold color={(focused ? sel === 0 : clickedId === null) ? t.color.accent : t.color.muted}>
          {(focused ? sel === 0 : clickedId === null) ? '▸ ✎ New chat' : '  ✎ New chat'}
        </Text>
      </Box>

      <Box flexShrink={0} marginTop={1}>
        <Text color={focused ? t.color.label : t.color.muted}>Recent{focused ? ' ▸' : ''}</Text>
      </Box>

      <ScrollBox
        // decstbm={false}: the rail scrolls beside the conversation, so its
        // hardware scroll must not disturb the conversation's rows.
        decstbm={false}
        flexDirection="column"
        flexGrow={1}
        flexShrink={1}
        // Remount once when the list goes empty→loaded. The ScrollBox auto-
        // follows the bottom when content GROWS from an at-max state, and the
        // empty placeholder (1 line, max 0) → tall list is exactly that, so the
        // rail opened scrolled to the oldest chat. A fresh instance renders the
        // full list in its FIRST measurement (prevScrollHeight == scrollHeight ⇒
        // not at-bottom), so it starts at the top. Keyed on the boolean, not the
        // count, so adding a chat later doesn't remount / lose scroll position.
        key={items.length > 0 ? 'loaded' : 'empty'}
        minHeight={0}
        ref={scrollRef}
      >
        {items.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            No conversations yet.
          </Text>
        ) : (
          items.map((s, i) => {
            const on = focused
              ? sel === i + 1
              : clickedId !== null
                ? s.id === clickedId
                : currentSid !== null && s.id === currentSid

            return (
              <Box flexShrink={0} key={s.id} onClick={interactive ? () => select(i + 1) : undefined} width="100%">
                <Text bold={on} color={on ? t.color.accent : t.color.text} wrap="truncate-end">
                  {on ? '▸ ' : '  '}
                  {cleanLabel(s.title, s.preview)}
                </Text>
              </Box>
            )
          })
        )}
      </ScrollBox>
    </Box>
  )
}
