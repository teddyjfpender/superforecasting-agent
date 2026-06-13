// Shared tail-audit derivations for the forecasts desk.
//
// The engine's categorical probability-mass audit (forecasting/tail_audit.py)
// rides on each categorical snapshot's `metadata.tail_audit`. This module turns
// that blob into the small, glanceable facts the desk renders in two places —
// the visual detail pane (forecastsWorkspace.tsx) and the textual heuristics
// (forecastPanel.ts) — so the chart, the chips, and the rail/book/status text
// all agree. Pure functions only; no rendering, no theme.

import type {
  ForecastQuestionPacket,
  ForecastQuestionPacketSnapshot,
  ForecastTailAudit,
  ForecastTailClassification,
  ForecastTailOutcome
} from '../gatewayTypes.js'

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// The current snapshot is the last in the history list (oldest-first), matching
// `packetCurrentSnapshot` in forecastPanel.ts and `_snapshot_to_dict` ordering.
export const currentSnapshot = (
  packet: ForecastQuestionPacket | null | undefined
): ForecastQuestionPacketSnapshot | null => {
  const history = packet?.forecast_history ?? []

  return history.length ? (history[history.length - 1] ?? null) : null
}

const isAudit = (value: unknown): value is ForecastTailAudit =>
  !!value && typeof value === 'object' && !Array.isArray(value)

// The tail audit on a snapshot's metadata, or null. A snapshot with no
// `tail_audit` (older snapshots, non-categorical questions) yields null so the
// caller shows nothing — never a fabricated zero-mass audit.
export const snapshotTailAudit = (
  snapshot: ForecastQuestionPacketSnapshot | null | undefined
): ForecastTailAudit | null => {
  const meta = snapshot?.metadata

  if (!meta || typeof meta !== 'object') {
    return null
  }

  const audit = (meta as { tail_audit?: unknown }).tail_audit

  return isAudit(audit) ? audit : null
}

// The tail audit for the current snapshot of a packet, or null.
export const packetTailAudit = (
  packet: ForecastQuestionPacket | null | undefined
): ForecastTailAudit | null => snapshotTailAudit(currentSnapshot(packet))

// An audit is a "finding" the desk must surface (not bury) when its
// `unearned_mass` clears the audit's own threshold, or it explicitly did not
// pass. `passes` is the engine's verdict; we honor it but also treat material
// unearned mass as a finding even if `passes` was omitted.
export const tailAuditFails = (audit: ForecastTailAudit | null | undefined): boolean => {
  if (!audit) {
    return false
  }

  if (audit.passes === false) {
    return true
  }

  const unearned = audit.unearned_mass
  const threshold = finite(audit.threshold) ? audit.threshold : 0

  return finite(unearned) && unearned > threshold
}

// Outcomes flagged `unearned` by the engine (material mass with no named path,
// not a capped residual). These are what colour error/warn and seed the chip.
export const unearnedOutcomes = (audit: ForecastTailAudit | null | undefined): ForecastTailOutcome[] =>
  (audit?.outcomes ?? []).filter(outcome => outcome?.unearned)

// Severity of one outcome row for the detail-pane colouring:
//   'error' — unearned mass with no path (the offender).
//   'warn'  — present but weak (unpriced/remote_tail/edge_case/live_ish).
//   'ok'    — a live, evidenced path.
//   'muted' — residual / negligible.
export type TailSeverity = 'error' | 'muted' | 'ok' | 'warn'

export const outcomeSeverity = (outcome: ForecastTailOutcome | null | undefined): TailSeverity => {
  if (!outcome) {
    return 'muted'
  }

  if (outcome.unearned) {
    return 'error'
  }

  const classification = (outcome.classification ?? '') as ForecastTailClassification | string

  if (classification === 'live') {
    return 'ok'
  }

  if (classification === 'residual') {
    return 'muted'
  }

  if (classification === 'unpriced' || classification === 'remote_tail' || classification === 'edge_case') {
    return 'warn'
  }

  if (classification === 'live_ish') {
    return 'warn'
  }

  return 'muted'
}

// A percent string for tail masses ("1.7%"). Keeps one decimal so a 1.7% tail
// never rounds to a misleading "2%".
export const tailPct = (value: number | null | undefined): string => {
  if (!finite(value)) {
    return '—'
  }

  const percent = value * 100
  const text = Math.abs(percent - Math.round(percent)) < 0.05 ? percent.toFixed(0) : percent.toFixed(1)

  return `${text}%`
}

// The unearned-mass headline ("unearned tail mass 1.7% (over 0.5%)") or null
// when the audit is clean / absent.
export const unearnedHeadline = (audit: ForecastTailAudit | null | undefined): string | null => {
  if (!audit || !finite(audit.unearned_mass) || audit.unearned_mass <= 0) {
    return null
  }

  const overThreshold = finite(audit.threshold) ? ` (over ${tailPct(audit.threshold)})` : ''

  return `unearned tail mass ${tailPct(audit.unearned_mass)}${overThreshold}`
}

// The null-model comparison line:
//   "no-path tail 4.0% vs simple-null 0.6% (6.7x)"
// Returns null when no null model rode along.
export const nullModelLine = (audit: ForecastTailAudit | null | undefined): string | null => {
  const nm = audit?.null_model

  if (!nm) {
    return null
  }

  const agent = tailPct(nm.agent_tail)
  const nullTail = tailPct(nm.null_tail)
  const ratio = finite(nm.ratio) ? (Number.isFinite(nm.ratio) ? `${nm.ratio.toFixed(1)}x` : '∞') : '—'

  return `no-path tail ${agent} vs simple-null ${nullTail} (${ratio})`
}

// The single inline chip that sits next to the analyst quick-read so the
// commentary and the audit never contradict each other:
//   "tail audit: FAIL — Conway 1.7% unpriced"     (a failing audit)
//   "tail audit: PASS"                             (a passing audit)
// Returns null when there is no audit at all (non-categorical / older snapshot).
export const tailAuditChip = (audit: ForecastTailAudit | null | undefined): string | null => {
  if (!audit) {
    return null
  }

  if (!tailAuditFails(audit)) {
    return 'tail audit: PASS'
  }

  const offenders = unearnedOutcomes(audit)
  const lead = offenders[0]

  if (lead && lead.name) {
    const classification = lead.classification ? ` ${lead.classification}` : ''
    const extra = offenders.length > 1 ? ` +${offenders.length - 1}` : ''

    return `tail audit: FAIL — ${lead.name} ${tailPct(lead.probability)}${classification}${extra}`
  }

  const headline = unearnedHeadline(audit)

  return headline ? `tail audit: FAIL — ${headline}` : 'tail audit: FAIL'
}

// A market source slug looks like "polymarket:...", "kalshi:...", etc. Used to
// hint a market component whose weight was discounted for being thin/stale.
const MARKET_PREFIXES = ['polymarket:', 'kalshi:', 'manifold:', 'metaculus:']

export const looksLikeMarketSource = (source: string | null | undefined): boolean => {
  const slug = (source ?? '').toLowerCase()

  return MARKET_PREFIXES.some(prefix => slug.startsWith(prefix))
}
