import type { PanelRow, PanelSection } from '../types.js'

// ── Today feed ────────────────────────────────────────────────────────────────
// The Home "Today" attention panel renders the SAME desk-rail PanelSections the
// status strip already carries (uiStore.forecastDeskRailSections), but as an
// interactive, prioritised list of things that need a human. This module is the
// pure transform: rail sections → a flat, deduped, hotkeyed feed. It lives apart
// from the component so it is trivially unit-testable and reused by the keyboard
// layer (the count gates the `t` leader).

export type TodayItemKind = 'alerts' | 'command' | 'question'

export interface TodayItem {
  // Set when kind==='alerts': deep-link the Warnings view onto a specific lens
  // ('contested' → the contested triage hand-label list). Undefined opens plain.
  focus?: 'contested'
  // '1'..'9' — the per-row hotkey the panel renders and the keymap dispatches.
  hotkey: string
  kind: TodayItemKind
  // The secondary line (status / description); '' when the title says it all.
  note: string
  // Set when kind==='question': the ledger id to deep-link into the Desk.
  questionId?: string
  // Set when kind==='command': the slash command to run.
  command?: string
  // The rail section this row came from — drives the leading glyph/colour.
  section: string
  // The primary line the panel shows.
  title: string
}

// The rail sections that actually carry "needs you" work, most-urgent first.
// Everything else on the rail (Book counters, Doctor, Evidence, Live, Ensemble,
// Backtests) is steady-state health and stays OFF the Today feed.
const FEED_SECTION_ORDER = ['Triage', 'Focused Actions', 'Watchlist', 'Alerts']

const QUESTION_TARGET_RE = /^\/questions\s+(\S+)/

const truncate = (value: string, max: number) =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// The clickable/dispatchable target for a row: the explicit third element when
// present, else the key (rail question/alert rows put the command in row[2],
// triage rows put it in row[0]).
const rowTarget = (row: PanelRow): string => (row[2] ?? row[0] ?? '').trim()

// Split a rail value ("Title  status  as-of…") into its leading title segment
// and the remainder, on runs of 2+ spaces (how the rail joins its cells).
const splitValue = (value: string): { note: string; title: string } => {
  const parts = (value ?? '').split(/\s{2,}/).map(part => part.trim()).filter(Boolean)

  if (!parts.length) {
    return { note: '', title: '' }
  }

  return { note: parts.slice(1).join(' · '), title: parts[0] }
}

// Rail status strings tail into reason-label DEBRIS that reads as soup on the
// Today feed: forecastPanel's `formatReviewReason` emits 'learned error profile'
// | <reason> | 'review', and `focusedForecastContext` prefixes the set with
// "reasons …" (e.g. "reasons learned error profile"). The rail also glues rows
// with a bare "—" separator. None of that belongs on a one-line attention row.
const isNoteDebris = (segment: string): boolean =>
  /^reasons\b/i.test(segment) ||
  segment === 'learned error profile' ||
  segment === 'review' ||
  segment === '—' ||
  segment === '-'

// Clean a splitValue note (already " · "-joined) for the feed: drop reason-label
// debris and bare separators, then keep at most the FIRST TWO genuinely useful
// segments (probability+delta like "Andy Burnham 0.80 (+7)", status, "as-of …",
// "close <date>"), so a long question title never trails into metadata soup.
const sanitizeNote = (note: string): string =>
  (note ?? '')
    .split(' · ')
    .map(segment => segment.trim())
    .filter(segment => segment.length > 0 && !isNoteDebris(segment))
    .slice(0, 2)
    .join(' · ')

// The open-alerts summary row ("1250 open alerts need source or resolution
// review"): capture the leading count so the feed can thousands-separate it.
const OPEN_ALERTS_RE = /^(\d[\d,]*)\s+open alerts?\b/i

const classify = (
  row: PanelRow,
  section: string
): null | Omit<TodayItem, 'hotkey'> => {
  const target = rowTarget(row)
  const value = row[1] ?? ''
  const { note, title } = splitValue(value)

  // The open-alerts summary (Triage `/alerts`) OR any Alerts-section row: a
  // single "jump to Alerts" entry (deduped by the shared 'alerts' key upstream).
  if (target === '/alerts' || section === 'Alerts') {
    const alertTitle = section === 'Alerts' ? splitValue(value).title || title : title || value
    const openAlerts = OPEN_ALERTS_RE.exec(alertTitle)

    // The open-alerts summary: thousands-separate the count and keep the note
    // SELF-DESCRIBING (what kind of review), never a key claim — the panel's
    // action keys are only live while it holds focus, so the focus-aware footer
    // is the one honest place to teach them.
    if (openAlerts) {
      const count = Number(openAlerts[1].replace(/,/g, ''))

      return {
        kind: 'alerts',
        note: 'source/resolution review',
        section,
        title: `${count.toLocaleString('en-US')} open alert${count === 1 ? '' : 's'}`
      }
    }

    return {
      kind: 'alerts',
      note: sanitizeNote(section === 'Alerts' ? note : note || ''),
      section,
      title: truncate(alertTitle || 'open alerts', 72)
    }
  }

  const questionMatch = QUESTION_TARGET_RE.exec(target)

  if (questionMatch) {
    return {
      kind: 'question',
      note: truncate(sanitizeNote(note), 96),
      questionId: questionMatch[1],
      section,
      title: truncate(title || value || questionMatch[1], 72)
    }
  }

  // A runnable slash command (Triage rows like /review --stale, /forecast
  // readiness). Skip placeholder-bearing commands (<id>, […]) — they can't be
  // dispatched as-is.
  if (target.startsWith('/') && !/(?:<[^>]+>|\[[^\]]+\]|\.\.\.)/.test(target)) {
    return {
      command: target,
      kind: 'command',
      note: truncate(target, 72),
      section,
      title: truncate(title || value || target, 72)
    }
  }

  return null
}

const dedupeKey = (item: Omit<TodayItem, 'hotkey'>): string => {
  if (item.kind === 'alerts') {
    return 'alerts'
  }

  if (item.kind === 'question') {
    return `q:${item.questionId}`
  }

  return `cmd:${item.command}`
}

// The contested-triage badge row: a hand-label loop is open only the operator
// can clear (the auto-labeler disputed these), so it LEADS the feed and deep-links
// straight into the Warnings view's contested lens. Built here (not from a rail
// section) so the count can come from the forecast.triage.contested RPC.
const contestedItem = (count: number): Omit<TodayItem, 'hotkey'> => ({
  focus: 'contested',
  kind: 'alerts',
  note: 'auto-labeler disputed — you decide',
  section: 'Contested',
  title: `${count} contested triage ${count === 1 ? 'row needs' : 'rows need'} a hand-label`
})

/**
 * Flatten the desk-rail PanelSections into a prioritised, deduped, hotkeyed
 * attention feed for the Home "Today" panel. Returns at most `max` items,
 * most-urgent first (contested triage → triage → focused → watchlist → alerts).
 * `contestedCount` (> 0) prepends the contested hand-label badge.
 */
export const todayFeedItems = (sections: PanelSection[], max = 9, contestedCount = 0): TodayItem[] => {
  const byTitle = new Map<string, PanelSection>()

  for (const section of sections) {
    if (section.title && !byTitle.has(section.title)) {
      byTitle.set(section.title, section)
    }
  }

  const collected: Omit<TodayItem, 'hotkey'>[] = []
  const seen = new Set<string>()

  // The contested badge leads (a human-only hand-label loop) — its own identity,
  // so it never collides with the open-alerts summary row below.
  if (contestedCount > 0) {
    collected.push(contestedItem(contestedCount))
  }

  for (const sectionTitle of FEED_SECTION_ORDER) {
    const section = byTitle.get(sectionTitle)

    for (const row of section?.rows ?? []) {
      if (collected.length >= max) {
        break
      }

      const classified = classify(row, sectionTitle)

      if (!classified) {
        continue
      }

      const key = dedupeKey(classified)

      if (seen.has(key)) {
        continue
      }

      seen.add(key)
      collected.push(classified)
    }

    if (collected.length >= max) {
      break
    }
  }

  // Assign the per-row hotkeys last, over the final ordered list (contested first).
  return collected.slice(0, max).map((item, idx) => ({ ...item, hotkey: String(idx + 1) }))
}
