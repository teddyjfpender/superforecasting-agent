import { Box, Text, useInput } from '@hermes/ink'

import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

// A small, reusable "Information" modal (open with `i`) so a view can surface
// warnings and tips WITHOUT a persistent header line that steals footer rows.
// The trigger view shows a compact [!] on its header row and lists the details
// here. Markers are ASCII-only: emoji glyphs (⚠/ℹ) render 2 cells wide but
// measure as 1, desyncing the line and leaving stale cells uncleared.

export interface InfoItem {
  detail?: string
  label: string
  tone?: 'info' | 'warn'
}

interface InfoModalProps {
  cols: number
  items: InfoItem[]
  onClose: () => void
  rows: number
  subtitle?: string
  t: Theme
  title: string
}

export function InfoModal({ cols, items, onClose, rows, subtitle, t, title }: InfoModalProps) {
  const sem = semantics(t)

  useInput((ch, key) => {
    if (key.escape || key.return || ch === 'h' || ch === 'i' || ch === 'q') {
      onClose()
    }
  })

  const modalW = Math.max(48, Math.min(cols - 4, 96))
  const modalH = Math.max(10, Math.min(rows - 4, 28))

  return (
    <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
      <Box
        borderColor={t.color.accent}
        borderStyle="round"
        flexDirection="column"
        height={modalH}
        paddingX={2}
        paddingY={1}
        width={modalW}
      >
        <Text bold color={t.color.primary}>
          {title}
        </Text>
        {subtitle ? (
          <Text color={t.color.muted} wrap="wrap">
            {subtitle}
          </Text>
        ) : null}

        <Box flexDirection="column" flexGrow={1} marginTop={1} overflow="hidden">
          {items.length === 0 ? (
            <Text color={sem.up}>✓ Everything's configured — no warnings for this view.</Text>
          ) : (
            items.map((it, i) => (
              <Box flexDirection="column" key={i} marginBottom={1}>
                <Text wrap="truncate-end">
                  <Text color={it.tone === 'warn' ? sem.star : t.color.accent}>{it.tone === 'warn' ? '[!] ' : '[i] '}</Text>
                  <Text bold color={t.color.text}>
                    {it.label}
                  </Text>
                </Text>
                {it.detail ? (
                  <Text color={t.color.muted} wrap="wrap">
                    {'   '}
                    {it.detail}
                  </Text>
                ) : null}
              </Box>
            ))
          )}
        </Box>

        <Text color={t.color.muted}>Esc close</Text>
      </Box>
    </Box>
  )
}
