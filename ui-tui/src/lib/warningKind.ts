// Client-side mirror of forecasting/warnings.py:classify_warning — maps an alert
// `reason` to the resolution KIND that governs it, plus an honest, human-readable
// description of what resolving it WILL actually do. The Warnings overlay + the
// resolve sheet use this to preview the gated work (or "surfaced, not resolved")
// before the user confirms, WITHOUT a round-trip. The Python dispatcher remains
// the source of truth; this only previews. Keep the prefixes in lockstep.

export type WarningKind =
  | 'bookkeeping'
  | 'evidence_collection'
  | 'material_change'
  | 'no_auto'
  | 'postmortem'
  | 'reforecast'
  | 'score'

// Human-judgment classes — never auto-resolved (checked FIRST, like Python).
const NO_AUTO_PREFIXES = [
  'domain_error',
  'assumption_check',
  'assumption_invalidated',
  'assumption_stale',
  'reference_class',
  'central_in_band',
  'calibration_lesson'
]
const MATERIAL_PREFIXES = ['watched_source_changed', 'watched_source_unavailable', 'trigger_fired']
const BOOKKEEPING_PREFIXES = ['autopilot_enabled', 'autopilot_source_failed', 'review_due']
// No evidence / no snapshot yet — collect evidence FIRST (the REFORECAST runner
// hard-blocks on zero evidence), so these route to their own kind. Checked before
// REFORECAST, like Python.
const EVIDENCE_COLLECTION_PREFIXES = ['no_evidence', 'no_forecast_snapshot']
const REFORECAST_PREFIXES = ['evidence_stale', 'last_update', 'new_evidence', 'close_time_within']

const startsWithAny = (text: string, prefixes: string[]): boolean => prefixes.some(p => text.startsWith(p))

export const classifyWarning = (reason: string | undefined): WarningKind => {
  const text = (reason ?? '').trim()

  if (!text) {
    return 'no_auto'
  }

  // 1. NO_AUTO — human-judgment classes, before any generic matching.
  if (startsWithAny(text, NO_AUTO_PREFIXES)) {
    return 'no_auto'
  }

  // 2. POSTMORTEM — covers postmortem_due + high_impact_postmortem_due.
  if (text.includes('postmortem_due')) {
    return 'postmortem'
  }

  // 3. MATERIAL_CHANGE — a watched source moved / a trigger fired.
  if (startsWithAny(text, MATERIAL_PREFIXES)) {
    return 'material_change'
  }

  // 4. SCORE — a resolved question due a Brier score (score_due /
  //    high_impact_score_due). Real gated work (it persists a score record),
  //    NOT a bookkeeping bare-ack. Checked after POSTMORTEM.
  if (text.includes('score_due')) {
    return 'score'
  }

  // 5. BOOKKEEPING — informational notices only.
  if (startsWithAny(text, BOOKKEEPING_PREFIXES)) {
    return 'bookkeeping'
  }

  // 6. EVIDENCE_COLLECTION — no evidence / no snapshot yet (collect, then forecast).
  if (startsWithAny(text, EVIDENCE_COLLECTION_PREFIXES)) {
    return 'evidence_collection'
  }

  // 7. REFORECAST — staleness / new-evidence / close-soon (already has evidence).
  if (startsWithAny(text, REFORECAST_PREFIXES)) {
    return 'reforecast'
  }

  // Fail-safe: unknown reason → surface, never auto-resolve.
  return 'no_auto'
}

export interface WarningResolution {
  // Whether the gateway's (non-LLM) resolve path can act on this from the TUI.
  auto: boolean
  // A one-line title for the resolution.
  label: string
  // The honest detail of what will run (or why nothing will).
  detail: string
}

// What `forecast.warnings.resolve` WILL do for this kind, in the synchronous
// gateway path (which injects the autopilot + score runners, but NOT the LLM
// reforecast runner — that is CLI `--agent` only).
export const warningResolution = (kind: WarningKind): WarningResolution => {
  switch (kind) {
    case 'score':
      return {
        auto: true,
        label: 'Score resolved question',
        detail: 'Compute + persist the Brier/log score for the confirmed resolution. Acked only if the score commits; stays OPEN if it cannot be scored yet.'
      }
    case 'postmortem':
      return {
        auto: true,
        label: 'Score + postmortem',
        detail: 'Score the resolved question, then write its postmortem. Acked only if the score commits.'
      }
    case 'material_change':
      return {
        auto: true,
        label: 'Run autopilot',
        detail: 'Re-check the watched source(s); if one moved, record a snapshot and propose an update. Stays open if the source is down.'
      }
    case 'reforecast':
      return {
        auto: false,
        label: 'Reforecast (needs agent)',
        detail: 'A fresh LLM reforecast is required — the TUI path has no agent runner, so this stays OPEN. Run `forecast warnings resolve --agent` from the CLI.'
      }
    case 'evidence_collection':
      return {
        auto: false,
        label: 'Collect evidence (needs agent)',
        detail: 'No evidence yet — an LLM/web search+import pass is required, which the TUI path has no runner for, so this stays OPEN. It acks only if it imports ≥1 new reading. Run `forecast warnings resolve --agent` from the CLI.'
      }
    case 'bookkeeping':
      return {
        auto: true,
        label: 'Acknowledge notice',
        detail: 'Informational notice — there is no forecast to move, so acking it is the correct close-out.'
      }
    case 'no_auto':
    default:
      return {
        auto: false,
        label: 'Surface for human review',
        detail: 'No safe auto-fix (domain error / assumption / reference class / recenter). Resolving here will NOT close it — it is surfaced for a human.'
      }
  }
}

const KIND_LABEL: Record<WarningKind, string> = {
  bookkeeping: 'bookkeeping',
  evidence_collection: 'evidence collection',
  material_change: 'material change',
  no_auto: 'human review',
  postmortem: 'postmortem',
  reforecast: 'reforecast',
  score: 'score'
}

export const warningKindLabel = (kind: WarningKind): string => KIND_LABEL[kind] ?? kind

// ── Resolution proposals ────────────────────────────────────────────────────
// A resolution PROPOSAL alert (raised by the auto-resolution detector OR the
// metric-threshold resolver) rides the generic NO_AUTO class in classifyWarning
// (it is human-judgment: surfaced, never auto-reconciled). But unlike other
// NO_AUTO alerts it has a concrete, ONE-KEY confirm path — routing through the
// EXISTING `forecast resolve` flow, which auto-scores + synthesizes the lesson.
// These helpers let the alerts view recognise a proposal and extract its outcome
// so it can bind that confirm without a round-trip. Keep the prefix + parse in
// lockstep with forecasting/ledger/alerts.py:resolution_proposal_outcome.
export const RESOLUTION_PROPOSAL_PREFIX = 'resolution proposed:'

export const isResolutionProposal = (reason: string | undefined): boolean =>
  (reason ?? '').trim().toLowerCase().startsWith(RESOLUTION_PROPOSAL_PREFIX)

// The proposed outcome token (first word after the prefix, lower-cased), or null.
export const resolutionProposalOutcome = (reason: string | undefined): null | string => {
  const text = (reason ?? '').trim().toLowerCase()

  if (!text.startsWith(RESOLUTION_PROPOSAL_PREFIX)) {
    return null
  }

  const tail = text.slice(RESOLUTION_PROPOSAL_PREFIX.length).trim()

  if (!tail) {
    return null
  }

  const token = tail.split(/\s+/)[0].replace(/[—-]+$/, '').trim()

  return token || null
}
