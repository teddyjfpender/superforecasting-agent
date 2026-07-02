import { Box, Text, useInput } from '@hermes/ink'
import { useState } from 'react'

import { SLASH_COMMANDS } from '../app/slash/registry.js'
import type { SlashCommand } from '../app/slash/types.js'
import { rankItems } from '../lib/fuzzyRank.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { windowItems } from './overlayControls.js'

const VISIBLE = 12

// Rank the slash catalog against the typed query — name > aliases > help. An
// empty query returns the full catalog in registration order (rankItems does
// this), so the palette opens as a browsable list. Pure + exported for tests.
export const rankSlashCommands = (query: string): SlashCommand[] =>
  rankItems(SLASH_COMMANDS, query, [
    { get: c => c.name, weight: 5 },
    { get: c => c.aliases ?? [], weight: 3 },
    { get: c => c.help ?? '', weight: 1 }
  ]).map(r => r.item)

interface PaletteOverlayProps {
  cols: number
  onClose: () => void
  // Runs the command through the SAME path the composer uses for a typed
  // `/name` (see useMainApp: actions.runCommand === dispatchSubmission).
  onRun: (command: string) => void
  rows: number
  t: Theme
}

export function PaletteOverlay({ cols, onClose, onRun, rows, t }: PaletteOverlayProps) {
  const [query, setQuery] = useState('')
  const [sel, setSel] = useState(0)

  const matches = rankSlashCommands(query)
  const clampedSel = matches.length ? Math.min(sel, matches.length - 1) : 0
  const active = matches[clampedSel]

  const run = (cmd: SlashCommand | undefined) => {
    if (!cmd) {
      return
    }

    onClose()
    onRun(`/${cmd.name}`)
  }

  useInput((ch, key) => {
    // This modal owns the keyboard while open: it is rendered as its own body
    // branch (GlobalChromePane), so the view/composer beneath are unmounted and
    // the global seam no-ops in its blocked branch — nothing else consumes keys.
    if (key.escape || (key.ctrl && ch === 'c') || (key.ctrl && ch.toLowerCase() === 'k')) {
      return onClose()
    }

    if (key.return) {
      return run(active)
    }

    if (key.upArrow) {
      return setSel(i => (matches.length ? (i - 1 + matches.length) % matches.length : 0))
    }

    if (key.downArrow) {
      return setSel(i => (matches.length ? (i + 1) % matches.length : 0))
    }

    if (key.backspace || key.delete) {
      setSel(0)

      return setQuery(q => q.slice(0, -1))
    }

    // Type-to-filter: accept printable chars (single or pasted chunk). Ctrl/meta
    // chords (Ctrl+K again, etc.) are ignored so they can't leak into the query.
    if (ch && !key.ctrl && !key.meta) {
      const printable = [...ch].filter(c => c >= ' ').join('')

      if (printable) {
        setSel(0)

        return setQuery(q => q + printable)
      }
    }
  })

  const { items, offset } = windowItems(matches, clampedSel, VISIBLE)

  return (
    <ModalOverlay
      cols={cols}
      footerHint="↑/↓ select · Enter run · type to filter · Esc close"
      maxHeight={VISIBLE + 8}
      maxWidth={84}
      rows={rows}
      t={t}
      title="Command palette"
    >
      <Box flexDirection="column">
        <Text color={t.color.muted} wrap="truncate-end">
          {'/'}
          <Text color={t.color.text}>{query || ' '}</Text>
          <Text color={t.color.muted}>{`   ${matches.length} command${matches.length === 1 ? '' : 's'}`}</Text>
        </Text>

        {offset > 0 && <Text color={t.color.muted}> ↑ {offset} more</Text>}

        {matches.length === 0 ? (
          <Text color={t.color.muted}>no matching command</Text>
        ) : (
          items.map((cmd, i) => {
            const idx = offset + i
            const isSel = idx === clampedSel

            return (
              <Text
                bold={isSel}
                color={isSel ? t.color.accent : t.color.text}
                inverse={isSel}
                key={cmd.name}
                wrap="truncate-end"
              >
                {isSel ? '▸ ' : '  '}
                {`/${cmd.name}`}
                {cmd.help ? <Text color={isSel ? t.color.accent : t.color.muted}>{`  — ${cmd.help}`}</Text> : null}
              </Text>
            )
          })
        )}

        {offset + VISIBLE < matches.length && (
          <Text color={t.color.muted}> ↓ {matches.length - offset - VISIBLE} more</Text>
        )}
      </Box>
    </ModalOverlay>
  )
}
