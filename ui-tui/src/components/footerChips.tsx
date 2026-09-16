import { Box, Text } from '@superforecasting/ink'

import { canOpenGlobalOverlay } from '../app/navRoutes.js'
import { $globalModal, $overlayState } from '../app/overlayStore.js'
import { openQuickMessage } from '../lib/messagingState.js'
import { footerKey } from '../lib/useViewInput.js'
import type { Theme } from '../theme.js'

// A row of bracketed keybinding chips — `[s Search] [v Select] …` — matching
// the document footer. Explicit callbacks or the shared view dispatcher make
// action chips clickable. Navigation hints retain the same bracketed styling.

export interface FooterChip {
  k: string
  label: string
  run?: () => void
}

const onChipClick = (run: () => void) => (event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
  if (event.cellIsBlank) {
    return
  }

  event.stopPropagation?.()
  run()
}

// `disabled` gates EVERY chip's mouse `run` (used while a modal overlay is open so
// the still-visible footer can't leak clicks past the keyboard trap).
export function FooterChips({
  chips,
  disabled = false,
  onKey,
  t
}: {
  chips: FooterChip[]
  disabled?: boolean
  onKey?: (key: string) => void
  t: Theme
}) {
  const entries = chips.some(chip => chip.run === openQuickMessage)
    ? chips
    : [
        ...chips,
        {
          k: 'Alt+M',
          label: 'Message',
          run: () => {
            if (!$globalModal.get() && canOpenGlobalOverlay($overlayState.get())) {
              openQuickMessage()
            }
          }
        }
      ]

  return (
    // flexWrap lets a crowded row (e.g. the Desk's dozen chips + `h Help`) flow
    // whole chips onto a second line instead of wrapping a single chip's label
    // mid-word (`Lens` -> `Len`). Each chip is flexShrink={0} so it stays intact.
    <Box flexWrap="wrap">
      {entries.map(chip => {
        const run = chip.run ?? (onKey && footerKey(chip.k) ? () => onKey(chip.k) : undefined)

        return (
          <Box
            flexShrink={0}
            key={`${chip.k}:${chip.label}`}
            marginRight={2}
            onClick={!disabled && run ? onChipClick(run) : undefined}
          >
            <Text color={t.color.muted}>[</Text>
            <Text bold color={t.color.accent}>
              {chip.k}
            </Text>
            <Text color={t.color.label}>{` ${chip.label}`}</Text>
            <Text color={t.color.muted}>]</Text>
          </Box>
        )
      })}
    </Box>
  )
}
