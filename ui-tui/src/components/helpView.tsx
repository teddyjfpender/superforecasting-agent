import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { $globalModal, patchOverlayState } from '../app/overlayStore.js'
import { HOTKEYS } from '../content/hotkeys.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

export const openHelpView = () => patchOverlayState({ help: true })
export const closeHelpView = () => patchOverlayState({ help: false })

// Full help, surfaced as a navigable view (the `?` popup stays as the quick
// inline hint). Static content — no gateway round-trip.
const VIEWS: [string, string][] = [
  ['Home', 'the chat desk — ask a forecasting question to begin'],
  ['Desk', 'the forecasts workspace (/forecast desk)'],
  ['Calendar', 'upcoming closes + resolutions, by date'],
  ['Warnings', 'open alerts, review queue, stale items, readiness gaps'],
  ['Calibration', 'reliability curve + signed-bias verdict (/calibration --visual)'],
  ['Obsidian', 'browse the vault write-ups + dossiers the desk publishes'],
  ['Agents', 'the subagent / spawn-tree view']
]

const COMMANDS: [string, string][] = [
  ['/forecast desk', 'open the forecasts workspace'],
  ['/forecast new "<q>"', 'create a scoreable question'],
  ['/quorum <id>', 'run a model-diverse quorum forecast'],
  ['/alerts', 'show open alerts'],
  ['/review --stale', 'queue stale/closing forecasts for review'],
  ['/calibration', 'calibration analytics (--visual for the chart view)'],
  ['/resume', 'resume a prior forecast session'],
  ['/clear', 'start a new session'],
  ['/copy', 'copy selection or last response'],
  ['/quit', 'exit the desk']
]

interface HelpViewProps {
  onClose: () => void
  t: Theme
}

export function HelpView({ onClose, t }: HelpViewProps) {
  const { stdout } = useStdout()
  const termRows = stdout?.rows ?? 24
  const [now, setNow] = useState(0)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)
  // While the Ctrl+K palette / `?` cheat-sheet stacks above this view, its own
  // useInput must go inert so keys don't double-handle beneath the overlay.
  const globalModal = useStore($globalModal)

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return scrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollRef.current?.scrollBy(pageSize)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  }, { isActive: !globalModal })

  const labelW = Math.min(
    24,
    Math.max(...VIEWS.map(([k]) => k.length), ...COMMANDS.map(([k]) => k.length), ...HOTKEYS.map(([k]) => k.length))
  )

  const pad = (s: string) => s + ' '.repeat(Math.max(0, labelW - s.length + 2))

  const rows = (items: [string, string][]) =>
    items.map(([k, v]) => (
      <Text key={k} wrap="truncate-end">
        <Text color={t.color.label}>{pad(k)}</Text>
        <Text color={t.color.muted}>{v}</Text>
      </Text>
    ))

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      <Box flexShrink={0} marginBottom={1}>
        <Text bold color={t.color.primary}>
          HELP
        </Text>
        <Text color={t.color.muted}>{'   click a tab up top, or type / for commands'}</Text>
      </Box>

      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <Text color={t.color.text} wrap="wrap">
              Ask a forecasting question to begin. Type {'`/`'} for commands, {'`?`'} for a quick inline hint, and click
              the tabs at the top to move between views.
            </Text>

            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Views
              </Text>
            </Box>
            {rows(VIEWS)}

            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Common commands
              </Text>
            </Box>
            {rows(COMMANDS)}

            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Hotkeys
              </Text>
            </Box>
            {rows(HOTKEYS as [string, string][])}
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>

      <Box flexShrink={0} marginTop={1}>
        <Text color={t.color.muted} wrap="truncate-end">
          ↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · Esc/q close
        </Text>
      </Box>
    </Box>
  )
}
