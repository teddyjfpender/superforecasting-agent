import { Box, Text } from '@hermes/ink'

import type { Theme } from '../theme.js'

// A row of bracketed keybinding chips — `[s Search] [v Select] …` — matching
// the Obsidian view's footer. Chips with a `run` are clickable (mouse parity
// with the key); the rest are display-only indicators so the available
// shortcuts are obvious on every route.

export interface FooterChip {
  k: string
  label: string
  run?: () => void
}

const onChipClick =
  (run: () => void) => (event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
    if (event.cellIsBlank) {
      return
    }

    event.stopPropagation?.()
    run()
  }

export function FooterChips({ chips, t }: { chips: FooterChip[]; t: Theme }) {
  return (
    <Box>
      {chips.map(chip => (
        <Box key={`${chip.k}:${chip.label}`} marginRight={2} onClick={chip.run ? onChipClick(chip.run) : undefined}>
          <Text color={t.color.muted}>[</Text>
          <Text bold color={t.color.accent}>
            {chip.k}
          </Text>
          <Text color={t.color.label}>{` ${chip.label}`}</Text>
          <Text color={t.color.muted}>]</Text>
        </Box>
      ))}
    </Box>
  )
}
