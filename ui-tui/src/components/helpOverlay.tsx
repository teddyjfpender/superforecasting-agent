import { Box, type ScrollBoxHandle, Text, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { NAV_TABS } from '../app/navRoutes.js'
import { $uiBuild } from '../app/uiStore.js'
import { GLOBAL_KEYS, guideFor, PER_VIEW_KEYS } from '../content/keymaps.js'
import { buildSummaryLine, isBuildStale, staleRemedy } from '../lib/buildInfo.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

// THE one shared Help modal. It UNIFIES the three help surfaces that used to
// drift apart: the keymaps registry (PER_VIEW_KEYS), the old `?` cheat-sheet,
// and Markets' bespoke InfoModal helpItems. Opened with `h` (or the `?` alias)
// on EVERY view via the global `cheatSheet` overlay flag, it paints, per the
// active view: a short "how to use this" guide (prose, wrapped — no truncation),
// then the grouped shortcut table (Global keys + this view's keys, Tab expands
// to every view). Esc / q / h / ? close it.

interface HelpOverlayProps {
  // NAV route key of the active view — selects the guide + the "This view" keys.
  activeView: string
  cols: number
  onClose: () => void
  rows: number
  t: Theme
}

const labelFor = (key: string) => NAV_TABS.find(tab => tab.key === key)?.label ?? 'Home'

// Every registered view that owns key rows, in top-bar order — the exhaustive
// "all views" wall Tab expands into (opt-in, so the default stays focused).
const ALL_VIEW_KEYS: [string, [string, string][]][] = NAV_TABS.flatMap(tab => {
  const keys = PER_VIEW_KEYS[tab.key]

  return keys?.length ? [[tab.key, keys] as [string, [string, string][]]] : []
})

export function HelpOverlay({ activeView, cols, onClose, rows, t }: HelpOverlayProps) {
  // Default shows the ACTIVE view's guide + keys (plus the Global keys). Tab
  // expands to the full registry (every view's keys) for the completists; Tab
  // again folds back. The whole body scrolls so neither the guide prose nor the
  // expanded wall can overflow the modal.
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

  // Reset to the top after a mode flip — in a layout effect (not inline in the
  // Tab handler) so scrollTo runs AFTER the taller/shorter content lays out; the
  // ScrollBox otherwise anchors the expanded wall to its bottom.
  useEffect(() => {
    scrollRef.current?.scrollTo(0)
  }, [showAll])

  useInput((ch, key) => {
    // Owns the keyboard while open — rendered as its own body branch, so the
    // view/composer beneath are unmounted (see GlobalChromePane). `h` closes it
    // too (press-again-to-dismiss), matching the `?` alias.
    if (key.escape || ch === 'q' || ch === 'h' || ch === '?' || (key.ctrl && ch === 'c')) {
      return onClose()
    }

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

  const guide = guideFor(activeView)
  const viewRows = PER_VIEW_KEYS[activeView] ?? PER_VIEW_KEYS.home ?? []
  // The build banner. This modal is the ONE surface reachable with `h` / `?` from
  // every view, so it is where "which build am I running?" has to be answerable
  // mid-session — the Home hero's copy scrolls away the moment a conversation
  // starts. Empty (and unmounted) until gateway.ready lands the build.
  const build = useStore($uiBuild)
  const buildLine = buildSummaryLine(build)
  const buildStale = isBuildStale(build)
  const buildRemedy = staleRemedy(build)

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

  // Keys render as keycaps (bold, label-coloured), the verb muted beside them.
  const rowsOf = (items: [string, string][]) =>
    items.map(([k, v]) => (
      <Text key={k} wrap="truncate-end">
        <Text bold color={t.color.label}>
          {pad(k)}
        </Text>
        <Text color={t.color.muted}>{v}</Text>
      </Text>
    ))

  return (
    <ModalOverlay
      cols={cols}
      footerHint={showAll ? 'Tab this view · Esc close' : 'Tab all views · ↑↓ scroll · Esc close'}
      maxHeight={showAll ? 40 : 36}
      maxWidth={82}
      rows={rows}
      scrollRef={scrollRef}
      t={t}
      tick={tick}
      title={`${labelFor(activeView)} · Help`}
    >
      <Box flexDirection="column">
        {/* Which build this is — first line of the modal, warn-coloured with the
            concrete remedy when the gateway says it is behind a release. */}
        {buildLine ? (
          <Box flexDirection="column" marginBottom={1}>
            <Text color={buildStale ? t.color.warn : t.color.muted} wrap="truncate-end">
              {buildStale ? `⚠ ${buildLine}` : buildLine}
            </Text>
            {buildRemedy ? (
              <Text color={t.color.warn} dimColor wrap="truncate-end">
                {`  run: ${buildRemedy}`}
              </Text>
            ) : null}
          </Box>
        ) : null}

        {/* The "how to use this view" guide — wrapped prose, never truncated. */}
        {guide.map((para, i) => (
          <Box key={`g${i}`} marginBottom={1}>
            <Text color={t.color.text} wrap="wrap">
              {para}
            </Text>
          </Box>
        ))}

        <Text bold color={t.color.accent}>
          Global keys
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
