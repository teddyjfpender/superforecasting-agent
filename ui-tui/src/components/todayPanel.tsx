import { Box, Text, useInput } from '@superforecasting/ink'
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
// The gap between the title and the note chip ("  ").
const NOTE_GAP = 2
// The shortest title we'll leave visible while still spending width on a whole
// note — below this the note is dropped entirely so the title stays readable.
const NOTE_MIN_TITLE = 12

// Fit one Today row into `budget` cells honouring a strict contract: the TITLE
// is the only thing ever truncated (ellipsis), and the meta chip (note) is shown
// WHOLE or not at all — never a dangling half-metadata fragment. Pure + exported
// so the truncation contract is unit-testable.
export const fitTodayRow = (
  title: string,
  note: string,
  budget: number
): { note: string; title: string } => {
  const safe = Math.max(1, budget)

  // No note → just clip the title to the whole budget.
  if (!note) {
    return { note: '', title: truncate(title, safe) }
  }

  // The whole title + the whole note already fit — show both untouched.
  if (title.length + NOTE_GAP + note.length <= safe) {
    return { note, title }
  }

  // Keep the WHOLE note only if a readable (>= NOTE_MIN_TITLE) truncated title
  // still fits beside it; otherwise drop the note and give the title the budget.
  const titleRoom = safe - NOTE_GAP - note.length

  if (titleRoom >= Math.min(NOTE_MIN_TITLE, title.length)) {
    return { note, title: truncate(title, titleRoom) }
  }

  return { note: '', title: truncate(title, safe) }
}

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
  // Cap the visible rows (the landing passes 5 for a compact, well-formed block).
  // When absent the panel keeps its width-driven default (narrow 3 / wide 6).
  maxRows?: number
  onBlur: () => void
  onNewQuestion: () => void
  onOpenAlerts: (focus?: 'contested') => void
  onOpenQuestion: (id: string) => void
  onRunCommand: (command: string) => void
  // True while a global overlay (palette / cheat-sheet) paints ABOVE the
  // still-mounted landing: hard-gates the panel's keys AND clicks so nothing
  // leaks past the overlay's keyboard trap.
  overlayOpen?: boolean
  sections: PanelSection[]
  // The SOFT focus tier: the panel is mounted on the landing with rows and the
  // composer is empty, so it borrows ↑↓/⏎ WITHOUT taking the keyboard from
  // typing. Distinct from `focused` (the explicit Ctrl+T full-focus mode).
  softFocus?: boolean
  t: Theme
  width: number
}

export function TodayPanel({
  contestedCount = 0,
  focused,
  maxRows: maxRowsProp,
  onBlur,
  onNewQuestion,
  onOpenAlerts,
  onOpenQuestion,
  onRunCommand,
  overlayOpen = false,
  sections,
  softFocus = false,
  t,
  width
}: TodayPanelProps) {
  const items = useMemo(() => todayFeedItems(sections, 9, contestedCount), [sections, contestedCount])
  const narrow = width < NARROW_COLS
  const maxRows = maxRowsProp ?? (narrow ? NARROW_ROWS : WIDE_ROWS)
  const visible = items.slice(0, maxRows)
  const hidden = Math.max(0, items.length - visible.length)

  const [sel, setSel] = useState(0)
  const clampedSel = Math.min(sel, Math.max(0, visible.length - 1))

  // Soft-focus highlight index. null = resting / no highlight — the initial
  // state AND the post-Esc state; the first ↑/↓ engages it at row 0, Esc clears
  // it back to null. Kept SEPARATE from `sel` (the Ctrl+T full-focus cursor) so
  // the two focus tiers never cross-contaminate.
  const [softSel, setSoftSel] = useState<null | number>(null)

  // Soft focus is live only while the parent says so (`softFocus`), the panel
  // isn't in full Ctrl+T mode, and there's actually a row to highlight. Mutually
  // exclusive with `focused` by construction (the parent gates softFocus on the
  // conversation pane), but guarded defensively.
  const softActive = softFocus && !focused && visible.length > 0
  const softIdx = softSel === null ? -1 : Math.min(softSel, Math.max(0, visible.length - 1))

  // Drop the soft-focus highlight the moment soft focus ends (a char typed, an
  // overlay opened, Ctrl+T taken) so a later re-entry always starts resting.
  useEffect(() => {
    if (!softFocus) {
      setSoftSel(null)
    }
  }, [softFocus])

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
      if (focused) {
        // FULL Ctrl+T focus — the panel owns the keyboard: ↑↓/jk select, ⏎ open,
        // a alerts, n new, digits jump, Tab/Esc/q hand focus back.
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

        return
      }

      // SOFT focus — the panel borrows ONLY the non-typing nav keys. Every
      // printable char (a, n, digits, j/k, …) is deliberately left unhandled so
      // it flows to the still-active composer: typing always wins, the panel
      // never eats the first letter of a message. The first ↑/↓ engages the
      // highlight at row 0, then arrows move it (shift+arrow is reserved for
      // transcript scroll); ⏎ opens the highlighted row (same path as full
      // focus); Esc clears the highlight back to the resting composer.
      if (!softActive) {
        return
      }

      if (key.escape) {
        if (softSel !== null) {
          setSoftSel(null)
        }

        return
      }

      if (key.upArrow && !key.shift) {
        return setSoftSel(s => (s === null ? 0 : Math.max(0, s - 1)))
      }

      if (key.downArrow && !key.shift) {
        return setSoftSel(s => (s === null ? 0 : Math.min(Math.max(0, visible.length - 1), s + 1)))
      }

      if (key.return && softSel !== null) {
        return activate(visible[Math.min(softSel, Math.max(0, visible.length - 1))])
      }
    },
    { isActive: (focused || softActive) && !overlayOpen }
  )

  const inner = Math.max(20, width - 2)

  return (
    <Box flexDirection="column" flexShrink={0} marginBottom={1} width={width}>
      <Text wrap="truncate-end">
        <Text bold color={focused ? t.color.accent : t.color.primary}>
          TODAY
        </Text>
        <Text color={t.color.muted}>{' · what needs you'}</Text>
        {!focused && items.length ? (
          <Text color={t.color.muted}>
            {' · '}
            <Text color={t.color.accent}>Ctrl+T</Text>
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
            const active = focused ? i === clampedSel : softActive && i === softIdx
            const glyph = glyphFor(item)

            const glyphColor =
              item.kind === 'alerts' ? t.color.statusBad : item.kind === 'question' ? t.color.accent : t.color.muted

            // Give the TITLE priority: the title is the only thing ever
            // truncated, and the note chip is shown WHOLE or dropped — never a
            // dangling half-metadata fragment (the fitTodayRow contract).
            const { note: shownNote, title: shownTitle } = fitTodayRow(
              item.title,
              item.note,
              inner - ROW_GLYPH_COLS
            )

            return (
              <Box
                key={`${item.kind}:${item.questionId ?? item.command ?? item.title}:${i}`}
                onClick={overlayOpen ? undefined : () => activate(item)}
              >
                <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                  <Text color={active ? t.color.accent : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                  <Text bold color={t.color.accent}>{item.hotkey}</Text>
                  <Text color={glyphColor}>{` ${glyph} `}</Text>
                  <Text bold={active} color={t.color.text}>
                    {shownTitle}
                  </Text>
                  {shownNote ? <Text color={t.color.muted}>{`  ${shownNote}`}</Text> : null}
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
                : softActive && softSel !== null
                  ? '↑↓ · ⏎ open · type to ask · Ctrl+T actions'
                  : truncate(`Ctrl+T to act · click opens in the Desk`, inner)}
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  )
}

const truncate = (value: string, max: number) =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value
