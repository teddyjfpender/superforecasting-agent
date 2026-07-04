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

// `disabled` gates EVERY chip's mouse `run` (used while a modal overlay is open so
// the still-visible footer can't leak clicks past the keyboard trap).
export function FooterChips({ chips, disabled = false, t }: { chips: FooterChip[]; disabled?: boolean; t: Theme }) {
  return (
    // flexWrap lets a crowded row (e.g. the Desk's dozen chips + `h Help`) flow
    // whole chips onto a second line instead of wrapping a single chip's label
    // mid-word (`Lens` -> `Len`). Each chip is flexShrink={0} so it stays intact.
    <Box flexWrap="wrap">
      {chips.map(chip => (
        <Box flexShrink={0} key={`${chip.k}:${chip.label}`} marginRight={2} onClick={!disabled && chip.run ? onChipClick(chip.run) : undefined}>
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
