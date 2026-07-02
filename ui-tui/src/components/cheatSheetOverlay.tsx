import { Box, Text, useInput } from '@hermes/ink'

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

export function CheatSheetOverlay({ activeView, cols, onClose, rows, t }: CheatSheetOverlayProps) {
  useInput((ch, key) => {
    // Owns the keyboard while open — rendered as its own body branch, so the
    // view/composer beneath are unmounted (see GlobalChromePane).
    if (key.escape || ch === 'q' || ch === '?' || (key.ctrl && ch === 'c')) {
      onClose()
    }
  })

  const viewRows = PER_VIEW_KEYS[activeView] ?? PER_VIEW_KEYS.home ?? []

  const labelW = Math.min(
    16,
    Math.max(...GLOBAL_KEYS.map(([k]) => k.length), ...viewRows.map(([k]) => k.length), 6)
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
      footerHint="Esc / q / ? close"
      maxHeight={GLOBAL_KEYS.length + viewRows.length + 10}
      maxWidth={78}
      rows={rows}
      t={t}
      title="Keyboard cheat sheet"
    >
      <Box flexDirection="column">
        <Text bold color={t.color.accent}>
          Global
        </Text>
        {rowsOf(GLOBAL_KEYS)}

        <Box marginTop={1}>
          <Text bold color={t.color.accent}>
            {`This view — ${labelFor(activeView)}`}
          </Text>
        </Box>
        {rowsOf(viewRows)}
      </Box>
    </ModalOverlay>
  )
}
