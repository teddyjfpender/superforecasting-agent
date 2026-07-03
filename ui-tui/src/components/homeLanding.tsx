import { Box, Text } from '@hermes/ink'
import { useState } from 'react'

import type { Theme } from '../theme.js'

import { modelLabel } from './appChrome.js'

// ── Home landing chrome ───────────────────────────────────────────────────────
// The two small, self-contained pieces the redesigned Home column pins to its
// bottom, both kept apart from the AppLayout orchestration so they stay small
// and unit-testable: ONE rotating accent tip line, and a deliberately SPARSE
// status bar (exactly three items — ready-state · the single most actionable
// count · model). The dense forecast inventory (forecasts / theses / factors /
// entities / alerts / closing) is gone from here — that detail lives in the Desk
// and the status views, not on the welcoming landing.

// ── Rotating tip line ─────────────────────────────────────────────────────────

// Genuinely useful, discoverable one-liners — the single hint the operator kept
// on the landing. Rotates so a returning user meets a different one over time.
export const HOME_TIPS: readonly string[] = [
  'press p in Markets for prediction markets',
  'Ctrl+K opens the command palette — every action, one search',
  'Ctrl+T focuses Today so you can act without leaving Home'
]

// Rotate the tips deterministically by index, wrapping (and tolerating a
// negative seed) so any caller can pick a stable member.
export const pickTip = (seed: number): string => {
  const n = HOME_TIPS.length
  const idx = ((Math.trunc(seed) % n) + n) % n

  return HOME_TIPS[idx]!
}

// The landing rotates its tip once an hour: stable within a session, but a user
// returning later meets a fresh one. Seeded at mount so it never flickers.
const TIP_ROTATE_MS = 3_600_000

export function HomeTip({ t }: { t: Theme }) {
  const [tip] = useState(() => pickTip(Math.floor(Date.now() / TIP_ROTATE_MS)))

  return (
    <Box justifyContent="center" marginTop={1}>
      <Text wrap="truncate-end">
        <Text color={t.color.accent}>Tip</Text>
        <Text color={t.color.muted}>{`  ${tip}`}</Text>
      </Text>
    </Box>
  )
}

// ── Minimal status bar ────────────────────────────────────────────────────────

// The single most actionable count for the bar: how many forecasts are queued
// for review. Parsed from the already-threaded desk-status label (which carries
// "<n> to review" when > 0) so no new plumbing is needed. 0 when absent.
export const reviewCountFromDeskStatus = (deskStatus: string): number => {
  const match = /(\d[\d,]*)\s+to review/.exec(deskStatus ?? '')

  return match ? Number(match[1].replace(/,/g, '')) : 0
}

interface HomeStatusBarProps {
  cols: number
  // The far-right dim path (kept in the corner so the slim row never feels empty).
  cwdLabel: string
  deskStatus: string
  model: string
  modelFast?: boolean
  modelReasoningEffort?: string
  status: string
  statusColor: string
  t: Theme
}

export function HomeStatusBar({
  cols,
  cwdLabel,
  deskStatus,
  model,
  modelFast,
  modelReasoningEffort,
  status,
  statusColor,
  t
}: HomeStatusBarProps) {
  const reviews = reviewCountFromDeskStatus(deskStatus)
  const leftWidth = Math.max(12, cols - cwdLabel.length - 3)

  return (
    <Box height={1}>
      <Box flexShrink={1} width={leftWidth}>
        <Text wrap="truncate-end">
          <Text color={t.color.border}>{'─ '}</Text>
          <Text color={statusColor}>{status}</Text>
          <Text color={t.color.muted}>{' · '}</Text>
          <Text color={reviews > 0 ? t.color.accent : t.color.muted}>
            {reviews} to review
          </Text>
          <Text color={t.color.muted}>{' · '}</Text>
          <Text color={t.color.info}>{modelLabel(model, modelReasoningEffort, modelFast)}</Text>
        </Text>
      </Box>

      <Text color={t.color.border}> ─ </Text>
      <Text color={t.color.muted} dimColor>
        {cwdLabel}
      </Text>
    </Box>
  )
}
