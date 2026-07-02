import { Box, Text, useInput } from '@hermes/ink'
import { useEffect, useMemo, useState } from 'react'

import { setTodayCount } from '../app/homeFocusStore.js'
import { todayFeedItems, type TodayItem } from '../lib/todayFeed.js'
import type { Theme } from '../theme.js'
import type { PanelSection } from '../types.js'

// ── Home "Today" attention panel ──────────────────────────────────────────────
// The landing surfaces the SAME desk-rail sections the status strip already
// carries, but as an interactive feed of what needs a human. Each row shows a
// hotkey + the item; ⏎/click opens the relevant question in the Desk, `a` jumps
// to Alerts, `n` starts a new question. The panel yields the keyboard to the
// composer unless it explicitly holds Home focus (`focused`), so a lazy prompter
// can still just type. On narrow terminals it collapses to the top 3 rows.

const NARROW_COLS = 84
const NARROW_ROWS = 3
const WIDE_ROWS = 6
// Row prefix cells before the title: marker "▸ " (2) + hotkey (1) + " glyph " (3).
const ROW_GLYPH_COLS = 6
// Only append the muted note when at least this many cols are left after the title.
const NOTE_MIN_COLS = 12

const glyphFor = (item: TodayItem): string => {
  if (item.kind === 'alerts') {
    return '!'
  }

  if (item.kind === 'question') {
    return '›'
  }

  return '·'
}

interface TodayPanelProps {
  // Open contested triage rows awaiting a hand-label — surfaced as the leading
  // feed row (a deep-link into the Warnings view's contested lens) when > 0.
  contestedCount?: number
  focused: boolean
  onBlur: () => void
  onNewQuestion: () => void
  onOpenAlerts: (focus?: 'contested') => void
  onOpenQuestion: (id: string) => void
  onRunCommand: (command: string) => void
  sections: PanelSection[]
  t: Theme
  width: number
}

export function TodayPanel({
  contestedCount = 0,
  focused,
  onBlur,
  onNewQuestion,
  onOpenAlerts,
  onOpenQuestion,
  onRunCommand,
  sections,
  t,
  width
}: TodayPanelProps) {
  const items = useMemo(() => todayFeedItems(sections, 9, contestedCount), [sections, contestedCount])
  const narrow = width < NARROW_COLS
  const maxRows = narrow ? NARROW_ROWS : WIDE_ROWS
  const visible = items.slice(0, maxRows)
  const hidden = Math.max(0, items.length - visible.length)

  const [sel, setSel] = useState(0)
  const clampedSel = Math.min(sel, Math.max(0, visible.length - 1))

  // Report the actionable count so the global keymap knows whether the Ctrl+T
  // leader should grab focus. Keep the two concerns in SEPARATE effects: the
  // count-sync effect must have NO cleanup, because a cleanup keyed on
  // [items.length] fires on every count change and setTodayCount(0) would flip
  // Home focus back to the composer mid-navigation (ejecting a user who is
  // browsing the panel when a background rail refresh changes the row count).
  useEffect(() => {
    setTodayCount(items.length)
  }, [items.length])

  // Release focus only on a REAL unmount (empty deps), so `t`/Ctrl+T types
  // normally again once the panel is gone.
  useEffect(() => () => setTodayCount(0), [])

  const activate = (item: TodayItem | undefined) => {
    if (!item) {
      return
    }

    if (item.kind === 'question' && item.questionId) {
      return onOpenQuestion(item.questionId)
    }

    if (item.kind === 'alerts') {
      return onOpenAlerts(item.focus)
    }

    if (item.kind === 'command' && item.command) {
      return onRunCommand(item.command)
    }
  }

  useInput(
    (ch, key) => {
      if (!focused) {
        return
      }

      if (key.escape || key.tab || ch === 'q') {
        return onBlur()
      }

      if (key.upArrow || ch === 'k') {
        return setSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || ch === 'j') {
        return setSel(i => Math.min(Math.max(0, visible.length - 1), i + 1))
      }

      if (ch === 'a') {
        return onOpenAlerts()
      }

      if (ch === 'n') {
        return onNewQuestion()
      }

      if (ch && ch >= '1' && ch <= '9') {
        const hit = visible.find(item => item.hotkey === ch)

        if (hit) {
          return activate(hit)
        }

        return
      }

      if (key.return) {
        return activate(visible[clampedSel])
      }
    },
    { isActive: focused }
  )

  const inner = Math.max(20, width - 2)

  return (
    <Box flexDirection="column" flexShrink={0} marginBottom={1} width={width}>
      <Text wrap="truncate-end">
        <Text bold color={focused ? t.color.accent : t.color.primary}>
          TODAY
        </Text>
        <Text color={t.color.muted}>{'   what needs you'}</Text>
        {!focused && items.length ? (
          <Text color={t.color.muted}>
            {'   '}
            <Text color={t.color.accent}>Ctrl+T</Text> focus
          </Text>
        ) : null}
      </Text>

      {items.length === 0 ? (
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            {`Nothing needs you — ask a question below, or press `}
            <Text color={t.color.accent}>n</Text>
            {` to track a new one.`}
          </Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={1}>
          {visible.map((item, i) => {
            const active = focused && i === clampedSel
            const glyph = glyphFor(item)

            const glyphColor =
              item.kind === 'alerts' ? t.color.statusBad : item.kind === 'question' ? t.color.accent : t.color.muted

            // Give the TITLE priority (mirror how deskView reserves the trailing
            // trend only once QUESTION is comfortable): append the muted note only
            // when the title leaves comfortable room on the line, and clip it to the
            // leftover width so a long title never shares its row with rail status.
            const noteRoom = inner - ROW_GLYPH_COLS - item.title.length - 2
            const noteText = item.note && noteRoom >= NOTE_MIN_COLS ? truncate(item.note, noteRoom) : ''

            return (
              <Box key={`${item.kind}:${item.questionId ?? item.command ?? item.title}:${i}`} onClick={() => activate(item)}>
                <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                  <Text color={active ? t.color.accent : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                  <Text bold color={t.color.accent}>{item.hotkey}</Text>
                  <Text color={glyphColor}>{` ${glyph} `}</Text>
                  <Text bold={active} color={t.color.text}>
                    {item.title}
                  </Text>
                  {noteText ? <Text color={t.color.muted}>{`  ${noteText}`}</Text> : null}
                </Text>
              </Box>
            )
          })}

          {hidden > 0 ? (
            <Text color={t.color.muted} wrap="truncate-end">{`  +${hidden} more · /desk`}</Text>
          ) : null}

          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="truncate-end">
              {focused
                ? '↑↓ select · ⏎ open · a alerts · n new · Esc back'
                : truncate(`⏎/click opens in the Desk · a alerts · n new`, inner)}
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  )
}

const truncate = (value: string, max: number) =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value
