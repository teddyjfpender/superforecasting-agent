import { Box, type ScrollBoxHandle, Text, useInput } from '@hermes/ink'
import { useEffect, useRef, useState } from 'react'

import { NAV_TABS } from '../app/navRoutes.js'
import { GLOBAL_KEYS, PER_VIEW_KEYS } from '../content/keymaps.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

interface CheatSheetOverlayProps {
  // NAV_TABS key of the active view — selects the "This view" section.
  activeView: string
  cols: number
  onClose: () => void
  rows: number
  t: Theme
}

const labelFor = (key: string) => NAV_TABS.find(tab => tab.key === key)?.label ?? 'Home'

// Every registered view that owns key rows, in top-bar order — the exhaustive
// "all views" wall Tab expands into (opt-in, so the default stays two sections).
const ALL_VIEW_KEYS: [string, [string, string][]][] = NAV_TABS.flatMap(tab => {
  const keys = PER_VIEW_KEYS[tab.key]

  return keys?.length ? [[tab.key, keys] as [string, [string, string][]]] : []
})

export function CheatSheetOverlay({ activeView, cols, onClose, rows, t }: CheatSheetOverlayProps) {
  // Default is TWO sections: Global + the CURRENTLY ACTIVE view (derived by the
  // caller from the overlay/nav state). Tab expands to the full registry (every
  // view's keys — the wall) for those who want it; Tab again folds back. The
  // content is scrollable so the expanded wall never overflows the modal.
  const [showAll, setShowAll] = useState(false)
  // Bumped on every scroll/toggle so the scrollbar thumb re-renders in step with
  // the (imperative) ScrollBox — no persistent interval to leak in tests.
  const [tick, setTick] = useState(0)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)

  const bump = () => setTick(v => v + 1)

  const scrollBy = (delta: number) => {
    scrollRef.current?.scrollBy(delta)
    bump()
  }

  // Reset to the top after a mode flip — done in a layout effect (not inline in the
  // Tab handler) so scrollTo runs AFTER the taller/shorter content has laid out;
  // the ScrollBox otherwise anchors the expanded wall to its bottom.
  useEffect(() => {
    scrollRef.current?.scrollTo(0)
  }, [showAll])

  useInput((ch, key) => {
    // Owns the keyboard while open — rendered as its own body branch, so the
    // view/composer beneath are unmounted (see GlobalChromePane).
    if (key.escape || ch === 'q' || ch === '?' || (key.ctrl && ch === 'c')) {
      return onClose()
    }

    // Tab toggles the full registry (all views) ⇄ the two-section default.
    // The scroll reset rides the [showAll] layout effect below.
    if (key.tab) {
      return setShowAll(v => !v)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollBy(-8)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollBy(8)
    }

    if (ch === 'g') {
      scrollRef.current?.scrollTo(0)

      return bump()
    }

    if (ch === 'G') {
      scrollRef.current?.scrollToBottom?.()

      return bump()
    }
  })

  const viewRows = PER_VIEW_KEYS[activeView] ?? PER_VIEW_KEYS.home ?? []

  const widthOf = (items: [string, string][]) => items.map(([k]) => k.length)

  const labelW = Math.min(
    16,
    Math.max(
      ...widthOf(GLOBAL_KEYS),
      ...(showAll ? ALL_VIEW_KEYS.flatMap(([, keyRows]) => widthOf(keyRows)) : widthOf(viewRows)),
      6
    )
  )

  const pad = (s: string) => s + ' '.repeat(Math.max(0, labelW - s.length + 2))

  const rowsOf = (items: [string, string][]) =>
    items.map(([k, v]) => (
      <Text key={k} wrap="truncate-end">
        <Text color={t.color.label}>{pad(k)}</Text>
        <Text color={t.color.muted}>{v}</Text>
      </Text>
    ))

  return (
    <ModalOverlay
      cols={cols}
      footerHint={showAll ? 'Tab this view · Esc close' : 'Tab all views · Esc close'}
      maxHeight={showAll ? 40 : GLOBAL_KEYS.length + viewRows.length + 10}
      maxWidth={78}
      rows={rows}
      scrollRef={scrollRef}
      t={t}
      tick={tick}
      title="Keyboard cheat sheet"
    >
      <Box flexDirection="column">
        <Text bold color={t.color.accent}>
          Global
        </Text>
        {rowsOf(GLOBAL_KEYS)}

        {showAll ? (
          ALL_VIEW_KEYS.map(([key, keyRows]) => (
            <Box flexDirection="column" key={key} marginTop={1}>
              <Text bold color={t.color.accent}>
                {labelFor(key)}
              </Text>
              {rowsOf(keyRows)}
            </Box>
          ))
        ) : (
          <>
            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                {`This view — ${labelFor(activeView)}`}
              </Text>
            </Box>
            {rowsOf(viewRows)}
          </>
        )}
      </Box>
    </ModalOverlay>
  )
}
