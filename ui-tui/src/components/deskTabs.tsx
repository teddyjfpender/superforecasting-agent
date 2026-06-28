import { Box, NoSelect, Text } from '@hermes/ink'

import { type DeskTab, tabWindow } from '../lib/deskGroups.js'
import type { Theme } from '../theme.js'

// The horizontal category strip for the redesigned Desk — mirrors the Markets
// tab strip (marketsView.tsx:1197) but windows around the active tab since the
// Desk's tab count is variable (theses + factors + tag groups + All). Clickable
// for mouse parity; ‹ › markers signal off-screen tabs.

function labelFor(tab: DeskTab, max = 22): string {
  let name = tab.label
  if (name.length > max) name = `${name.slice(0, max - 1)}…`
  const count = tab.kind === 'tag' || tab.kind === 'all' || tab.kind === 'bench' ? ` ${tab.forecastIds.length}` : ''
  return `${name}${count}`
}

export function DeskTabs({
  tabs,
  active,
  t,
  width,
  onSelect,
}: {
  tabs: DeskTab[]
  active: number
  t: Theme
  width: number
  onSelect: (i: number) => void
}) {
  if (tabs.length === 0) return null
  const labels = tabs.map((tab) => labelFor(tab))
  const widths = labels.map((l) => l.length)
  const { start, end } = tabWindow(widths, active, Math.max(20, width))
  const shown = tabs.slice(start, end)
  return (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box flexWrap="nowrap" overflow="hidden" width={Math.max(20, width)}>
        {start > 0 ? <Text color={t.color.muted}>{'‹ '}</Text> : null}
        {shown.map((tab, idx) => {
          const i = start + idx
          return (
            <Box key={tab.key} flexShrink={0} onClick={() => onSelect(i)}>
              {idx > 0 ? <Text color={t.color.border}>{' · '}</Text> : null}
              <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
                {labels[i]}
              </Text>
            </Box>
          )
        })}
        {end < tabs.length ? <Text color={t.color.muted}>{' ›'}</Text> : null}
      </Box>
    </NoSelect>
  )
}
