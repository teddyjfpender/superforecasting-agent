import { Box, Text } from '@superforecasting/ink'
import { useEffect, useState } from 'react'

import type { AgentsActive } from '../app/agentsActiveStore.js'
import { sweepColor, sweepStops } from '../lib/accentSweep.js'
import type { Theme } from '../theme.js'

import { modelLabel } from './appChrome.js'
import { LiveStatus } from './liveStatus.js'

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
  'Ctrl+T focuses Today so you can act without leaving Home',
  'press h (or ?) on any view for its guide + shortcuts'
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

// ── Live-agents chip ───────────────────────────────────────────────────────────

// The Agents overlay's keyboard seam: Ctrl+G arms the view-chord leader, then `a`
// routes to Agents (see content/keymaps VIEW_CHORDS). Shown dim in the chip so the
// heuristic stays inspectable by keyboard, not just by click.
export const AGENTS_CHIP_SHORTCUT = 'Ctrl+G a'

type ChipClickEvent = { cellIsBlank?: boolean; stopPropagation?: () => void }

// The live-agents chip: a ✦ whose colour sweeps the brand accent family (the
// house animation language — deskView's working-row spinner, the review sweep)
// followed by the gateway's "N agents running · <label>" headline and a dim
// keyboard hint. Mounted ONLY while count > 0, so its bounded 500ms sweep tick
// runs only then and the bar is byte-identically chip-free at rest. The click
// seam lives on a <Box> (this Ink fork drops <Text onClick>), inert while a
// global modal is up like every interactive element.
function AgentsChip({
  gated,
  headline,
  onOpen,
  shortcut,
  t
}: {
  gated: boolean
  headline: string
  onOpen?: () => void
  shortcut: string
  t: Theme
}) {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setFrame(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const swept = sweepColor(sweepStops(t), frame)
  const click = gated || !onOpen ? undefined : onOpen

  const handleClick = click
    ? (event: ChipClickEvent) => {
        if (event.cellIsBlank) {
          return
        }

        event.stopPropagation?.()
        click()
      }
    : undefined

  return (
    <Box flexShrink={0} onClick={handleClick}>
      <Text color={t.color.muted}>{' · '}</Text>
      <Text bold color={swept}>
        {'✦ '}
      </Text>
      <Text color={t.color.accent}>{headline}</Text>
      <Text color={t.color.muted} dimColor>
        {`  ${shortcut}`}
      </Text>
    </Box>
  )
}

// SESSION VITALS for the conversation surface only (context %, live voice,
// background count) — these are chat-session awareness, not desk inventory
// (the operator's trim targeted the desk-count soup; context awareness stays,
// as it does in every serious agent TUI). All conditional/compact; the
// LANDING passes none of them and keeps the pure 3-item line.
export interface StatusVitals {
  bgCount?: number
  contextPct?: null | number
  voiceLabel?: null | string
}

interface HomeStatusBarProps {
  // The live-agents aggregate (agents.active.summary). The "✦ N agents running"
  // chip renders ONLY while count > 0; absent (or undefined) → the bar is
  // byte-identical to the pre-chip three-item line.
  agents?: AgentsActive
  // Global-modal gate: while the palette / cheat-sheet stacks above, the chip's
  // click goes inert like every other interactive element.
  agentsGated?: boolean
  agentsShortcut?: string
  // While a turn is active the leading segment becomes the live heartbeat spinner
  // + derived running status (verb · elapsed · turn tokens); idle → the plain
  // status string, byte-identical to the pre-heartbeat bar.
  busy?: boolean
  cols: number
  // The far-right dim path (kept in the corner so the slim row never feels empty).
  cwdLabel: string
  deskStatus: string
  model: string
  modelFast?: boolean
  modelReasoningEffort?: string
  onOpenAgents?: () => void
  status: string
  statusColor: string
  t: Theme
  vitals?: StatusVitals
}

export function HomeStatusBar({
  agents,
  agentsGated = false,
  agentsShortcut = AGENTS_CHIP_SHORTCUT,
  busy = false,
  cols,
  cwdLabel,
  deskStatus,
  model,
  modelFast,
  modelReasoningEffort,
  onOpenAgents,
  status,
  statusColor,
  t,
  vitals
}: HomeStatusBarProps) {
  const reviews = reviewCountFromDeskStatus(deskStatus)
  const leftWidth = Math.max(12, cols - cwdLabel.length - 3)
  const showChip = !!agents && agents.count > 0

  // The three-item core (state · the single actionable count · model) — the SAME
  // slim line the landing and the active-conversation surface now share. Kept as
  // one truncate-end Text so, at rest (no chip), the left cell is byte-identical
  // to the pre-chip bar.
  const inner = (
    <Text wrap="truncate-end">
      <LiveStatus busy={busy} status={status} statusColor={statusColor} t={t} />
      <Text color={t.color.muted}>{' · '}</Text>
      <Text color={reviews > 0 ? t.color.accent : t.color.muted}>{reviews} to review</Text>
      <Text color={t.color.muted}>{' · '}</Text>
      <Text color={t.color.info}>{modelLabel(model, modelReasoningEffort, modelFast)}</Text>
      {vitals && vitals.contextPct != null ? (
        <Text
          color={vitals.contextPct >= 90 ? t.color.error : vitals.contextPct >= 70 ? t.color.warn : t.color.muted}
        >
          {` · ${vitals.contextPct}%`}
        </Text>
      ) : null}
      {vitals?.voiceLabel ? <Text color={t.color.accent}>{` · ${vitals.voiceLabel}`}</Text> : null}
      {vitals && (vitals.bgCount ?? 0) > 0 ? <Text color={t.color.muted}>{` · ${vitals.bgCount} bg`}</Text> : null}
    </Text>
  )

  return (
    <Box height={1}>
      {showChip ? (
        // When the chip shows, the core line shrinks (minWidth 0) so the fixed
        // chip keeps its full width — the live-agents heuristic wins the space
        // fight over the quieter counts, never truncating first.
        <Box flexShrink={1} width={leftWidth}>
          <Box flexShrink={1} minWidth={0}>
            {inner}
          </Box>
          <AgentsChip
            gated={agentsGated}
            headline={agents.headline}
            onOpen={onOpenAgents}
            shortcut={agentsShortcut}
            t={t}
          />
        </Box>
      ) : (
        <Box flexShrink={1} width={leftWidth}>
          {inner}
        </Box>
      )}

      <Text color={t.color.border}> ─ </Text>
      <Text color={t.color.muted} dimColor>
        {cwdLabel}
      </Text>
    </Box>
  )
}
