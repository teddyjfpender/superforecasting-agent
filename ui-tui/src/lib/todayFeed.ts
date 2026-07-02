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

    return {
      kind: 'alerts',
      note: section === 'Alerts' ? note : note || '',
      section,
      title: truncate(alertTitle || 'open alerts', 72)
    }
  }

  const questionMatch = QUESTION_TARGET_RE.exec(target)

  if (questionMatch) {
    return {
      kind: 'question',
      note: truncate(note, 96),
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

/**
 * Flatten the desk-rail PanelSections into a prioritised, deduped, hotkeyed
 * attention feed for the Home "Today" panel. Returns at most `max` items,
 * most-urgent first (triage → focused → watchlist → alerts).
 */
export const todayFeedItems = (sections: PanelSection[], max = 9): TodayItem[] => {
  const byTitle = new Map<string, PanelSection>()

  for (const section of sections) {
    if (section.title && !byTitle.has(section.title)) {
      byTitle.set(section.title, section)
    }
  }

  const items: TodayItem[] = []
  const seen = new Set<string>()

  for (const sectionTitle of FEED_SECTION_ORDER) {
    const section = byTitle.get(sectionTitle)

    for (const row of section?.rows ?? []) {
      if (items.length >= max) {
        return items
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
      items.push({ ...classified, hotkey: String(items.length + 1) })
    }
  }

  return items
}
