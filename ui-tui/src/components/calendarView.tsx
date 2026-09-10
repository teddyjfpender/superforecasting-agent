import { useStore } from '@nanostores/react'
import { Box, type ScrollBoxHandle, Text, useInput, useStdout } from '@superforecasting/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay, patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'
import { pct } from '../lib/forecastCharts.js'
import { type FieldSpec, filterRanked } from '../lib/fuzzyRank.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { type SortDir, sortIndicator, sortRows, type SortValue, useTableSort } from '../lib/tableSort.js'
import { pad, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'
import { ModalOverlay } from './modalOverlay.js'
import { windowItems } from './overlayControls.js'

export const openCalendarView = () => patchOverlayState({ calendar: true })
export const closeCalendarView = () => patchOverlayState({ calendar: false })

const DAY_MS = 86_400_000

// Below this terminal width the 7-column month grid can't breathe, so the
// calendar forces AGENDA (the dense table) as the only mode — Tab stops toggling
// and the "grid" chip is never shown, keeping every hint truthful to what's live.
const GRID_MIN_COLS = 88

type CalMode = 'agenda' | 'grid'

// Mode is remembered per SESSION (module-scope survives the view's unmount/remount
// as the overlay opens and closes). Narrow terminals override it to agenda. Tests
// reset it via `resetCalendarSession` so each mount starts from a known default.
let sessionMode: CalMode | null = null

export const resetCalendarSession = () => {
  sessionMode = null
}

// ── Event model ──────────────────────────────────────────────────────────────
// The three dated things the desk cares about, each with a distinct theme colour:
//   close   — the market/question stops taking updates (danger / red family)
//   resolve — the outcome is graded (warning / amber family)
//   review  — a scheduled autonomous re-forecast fires (accent)
export type CalKind = 'close' | 'resolve' | 'review'

export interface CalEvent {
  day: number // start-of-(local)-day epoch, the grid/agenda bucket key
  id?: string // question id → Enter deep-links to the Desk
  kind: CalKind
  prob: string
  stamp: number // exact epoch of the event
  title: string
}

const KIND_LABEL: Record<CalKind, string> = { close: 'close', resolve: 'resolve', review: 'review' }
const KIND_GLYPH: Record<CalKind, string> = { close: '●', resolve: '◆', review: '◇' }

const kindColor = (t: Theme, kind: CalKind): string =>
  kind === 'close' ? t.color.error : kind === 'resolve' ? t.color.warn : t.color.accent

// ── Pure date helpers (exported for the grid-math tests) ─────────────────────

export const startOfDay = (ms: number): number => {
  const d = new Date(ms)
  d.setHours(0, 0, 0, 0)

  return d.getTime()
}

export interface DayCell {
  day: number // 1..31
  inMonth: boolean // false for the leading/trailing days borrowed from the neighbours
  stamp: number // start-of-day epoch for this cell
}

// The Monday-first 7-column matrix for `month` (0-indexed) of `year`. The grid is
// padded with the trailing days of the previous month and the leading days of the
// next so every row holds exactly 7 cells; the number of rows is whatever it takes
// to cover the month (4 for a short aligned Feb, up to 6). Pure + timezone-stable
// in its STRUCTURE (offsets, day numbers, week count) regardless of the host TZ.
export const buildMonthMatrix = (year: number, month: number): DayCell[][] => {
  const first = new Date(year, month, 1)
  const firstWeekday = (first.getDay() + 6) % 7 // Mon=0 … Sun=6
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const weekCount = Math.ceil((firstWeekday + daysInMonth) / 7)

  const weeks: DayCell[][] = []
  const cursor = new Date(year, month, 1 - firstWeekday)

  for (let w = 0; w < weekCount; w += 1) {
    const week: DayCell[] = []

    for (let d = 0; d < 7; d += 1) {
      const cell = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate())
      week.push({ day: cell.getDate(), inMonth: cell.getMonth() === month, stamp: cell.getTime() })
      cursor.setDate(cursor.getDate() + 1)
    }

    weeks.push(week)
  }

  return weeks
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
]

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Proximity bucket for the agenda IN column: <=2d is urgent (danger), <=7d is soon
// (warning), everything further out is muted. Past events (negative days) read as
// urgent too — they are already due.
export type ProximityBucket = 'danger' | 'muted' | 'warn'
export const proximityBucket = (days: number): ProximityBucket =>
  days <= 2 ? 'danger' : days <= 7 ? 'warn' : 'muted'

export const proximityColor = (t: Theme, days: number): string => {
  const b = proximityBucket(days)

  return b === 'danger' ? t.color.error : b === 'warn' ? t.color.warn : t.color.muted
}

// Relative-days forward, compact for the narrow IN column: "now", "3d", "3w",
// "5mo". Negatives (already past/overdue) collapse to "now".
export const relIn = (days: number): string => {
  if (days <= 0) {
    return 'now'
  }

  if (days < 14) {
    return `${days}d`
  }

  if (days < 60) {
    return `${Math.round(days / 7)}w`
  }

  return `${Math.round(days / 30)}mo`
}

const daysBetween = (stamp: number, now: number): number =>
  Math.round((startOfDay(stamp) - startOfDay(now)) / DAY_MS)

// Compact agenda date label, e.g. "Jul 03".
const calDate = (stamp: number): string =>
  new Date(stamp).toLocaleDateString('en-US', { day: '2-digit', month: 'short' })

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// A question/review probability field → a short display string. Distributions
// (Record) and blanks read "—"; a bare number renders as a percent.
const probText = (p: unknown): string => {
  if (typeof p === 'number' && Number.isFinite(p)) {
    return pct(p)
  }

  if (typeof p === 'string' && p) {
    return p.length > 8 ? p.slice(0, 8) : p
  }

  return '—'
}

// ── Parse the dashboard payload into the flat event list ─────────────────────
// close_time / resolution_time come from questions[]; scheduled reviews come from
// scheduled_review_runs[].next_run_at (present in FAST mode too — the fast path
// only skips the heavy backtest/evidence walks, not the schedule). We title a
// review by its scope question when we can resolve it, else by its scope ref.
export const parseCalEvents = (data: ForecastDashboardResponse | null, now: number): CalEvent[] => {
  const summary = data?.summary
  const events: CalEvent[] = []

  const titleById = new Map<string, string>()

  for (const q of summary?.questions ?? []) {
    if (q.id) {
      titleById.set(q.id, q.title || q.id)
    }
  }

  const add = (raw: null | string | undefined, kind: CalKind, id: string | undefined, title: string, prob: unknown) => {
    if (!raw) {
      return
    }

    const stamp = Date.parse(raw)

    if (!Number.isFinite(stamp)) {
      return
    }

    events.push({ day: startOfDay(stamp), id, kind, prob: probText(prob), stamp, title })
  }

  for (const q of summary?.questions ?? []) {
    const title = q.title || q.id || '—'
    add(q.close_time, 'close', q.id, title, q.probability)
    add(q.resolution_time, 'resolve', q.id, title, q.probability)
  }

  for (const run of summary?.scheduled_review_runs ?? []) {
    const at = run.next_run_at || run.run_at
    const qId = run.scope_type === 'question' ? (run.scope_ref ?? undefined) : undefined
    const title = (qId && titleById.get(qId)) || run.scope_ref || run.cadence || 'scheduled review'
    add(at, 'review', qId, title, undefined)
  }

  events.sort((a, b) => a.stamp - b.stamp)

  return events
}

// ── Agenda sort machinery (reused D1 tableSort) ──────────────────────────────
// DATE and IN sort on the same underlying epoch; QUESTION on the title; KIND on
// the kind label; PROB on the numeric probability (missing → last).
const AGENDA_SORT_KEYS = ['date', 'in', 'q', 'kind', 'prob'] as const

const agendaSortValue = (ev: CalEvent, key: string): SortValue => {
  switch (key) {
    case 'date':

    case 'in':
      return ev.stamp

    case 'kind':
      return ev.kind
    case 'prob': {
      const n = Number.parseFloat(ev.prob)

      return Number.isFinite(n) ? n : null
    }

    case 'q':
      return ev.title

    default:
      return null
  }
}

const AGENDA_SEARCH_FIELDS: FieldSpec<CalEvent>[] = [
  { get: e => e.title, weight: 1 },
  { get: e => e.kind, weight: 0.4 }
]

interface CalendarViewProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

export function CalendarView({ gw, onClose, t }: CalendarViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const wide = cols >= GRID_MIN_COLS
  const globalModal = useStore($globalModal)

  const [data, setData] = useState<ForecastDashboardResponse | null>(
    () => getOverlayCache<ForecastDashboardResponse>('forecast.dashboard') ?? null
  )

  const [loading, setLoading] = useState(!data)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)

  // Mode: narrow terminals are agenda-only; wide terminals honour the remembered
  // session mode (default grid). The state seeds from that resolution.
  const [mode, setMode] = useState<CalMode>(() => (wide ? (sessionMode ?? 'grid') : 'agenda'))
  const effectiveMode: CalMode = wide ? mode : 'agenda'

  // Grid focus: an anchor month + a focused day stamp. Agenda: a row cursor.
  const wallNow = Date.now()

  const [anchor, setAnchor] = useState(() => {
    const d = new Date(wallNow)

    return { m: d.getMonth(), y: d.getFullYear() }
  })

  const [focusStamp, setFocusStamp] = useState(() => startOfDay(wallNow))
  const [sel, setSel] = useState(0)
  const [query, setQuery] = useState('')
  const [filtering, setFiltering] = useState(false)
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [popoverSel, setPopoverSel] = useState(0)
  const popoverScrollRef = useRef<null | ScrollBoxHandle>(null)

  const agendaSort = useTableSort(AGENDA_SORT_KEYS)

  // Keep the SELECTED event under the cursor across an agenda re-sort (track by id,
  // not index) — mirrors deskView/marketsView. A sort action stashes the current
  // event id; once the re-sorted order lands, the cursor jumps to where that event
  // now sits. Only sort arms this, so a filter change / reload leaves it null and
  // the index-based cursor logic there is untouched.
  const pendingReselect = useRef<null | string>(null)

  const load = (announce = false) => {
    setLoading(!data)
    // fast: the calendar reads only questions[].{title,id,close_time,resolution_time}
    // + the schedule runs, all carried in fast mode — so skip the heavy dashboard build.
    gw.request<unknown>('forecast.dashboard', { fast: true, limit: 200 })
      .then(raw => {
        const result = asRpcResult<ForecastDashboardResponse>(raw)

        if (!result) {
          setError('forecast.dashboard returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('forecast.dashboard', result)
        setData(result)
        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const events = useMemo(() => parseCalEvents(data, wallNow), [data, wallNow])

  const eventsByDay = useMemo(() => {
    const map = new Map<number, CalEvent[]>()

    for (const ev of events) {
      const list = map.get(ev.day) ?? []
      list.push(ev)
      map.set(ev.day, list)
    }

    return map
  }, [events])

  const weeks = useMemo(() => buildMonthMatrix(anchor.y, anchor.m), [anchor])
  const todayStamp = startOfDay(wallNow)

  // Month-scoped counts for the grid header summary line.
  const monthCounts = useMemo(() => {
    let deadlines = 0
    let reviews = 0

    for (const ev of events) {
      const d = new Date(ev.stamp)

      if (d.getFullYear() !== anchor.y || d.getMonth() !== anchor.m) {
        continue
      }

      if (ev.kind === 'review') {
        reviews += 1
      } else {
        deadlines += 1
      }
    }

    return { deadlines, reviews }
  }, [events, anchor])

  // Agenda: filter then sort (default order is already DATE-asc — the parse sorts
  // by stamp — so an unsorted table reads chronologically).
  const filtered = useMemo(() => filterRanked(events, query, AGENDA_SEARCH_FIELDS), [events, query])

  const agendaRows = useMemo(
    () => sortRows(filtered, agendaSort.state.key, agendaSort.state.dir, agendaSortValue),
    [filtered, agendaSort.state.key, agendaSort.state.dir]
  )

  const clampedSel = Math.min(sel, Math.max(0, agendaRows.length - 1))
  const selectedRow = agendaRows[clampedSel] ?? null

  useEffect(() => {
    const id = pendingReselect.current

    if (id == null) {
      return
    }

    pendingReselect.current = null
    const idx = agendaRows.findIndex(r => r.id === id)

    if (idx >= 0) {
      setSel(idx)
    }
  }, [agendaRows])

  const armReselect = () => {
    pendingReselect.current = selectedRow?.id ?? null
  }

  // The focused day's events (grid popover source).
  const focusEvents = eventsByDay.get(focusStamp) ?? []

  // ── Navigation actions ────────────────────────────────────────────────────
  const moveFocus = (deltaDays: number) => {
    // Step by CIVIL days, not fixed 24h epoch-ms multiples: on a DST transition a
    // local day is 23h/25h long, so `focusStamp + n*DAY_MS` would under/overshoot
    // the next midnight (stranding the focus on a fall-back day, or skipping a
    // spring-forward day). setDate advances one calendar day either way — matching
    // the Date-constructor math shiftMonth/buildMonthMatrix already use.
    const stepped = new Date(focusStamp)
    stepped.setDate(stepped.getDate() + deltaDays)
    const next = startOfDay(stepped.getTime())
    setFocusStamp(next)
    const d = new Date(next)

    if (d.getMonth() !== anchor.m || d.getFullYear() !== anchor.y) {
      setAnchor({ m: d.getMonth(), y: d.getFullYear() })
    }
  }

  const shiftMonth = (delta: number) => {
    const base = new Date(anchor.y, anchor.m + delta, 1)
    const y = base.getFullYear()
    const m = base.getMonth()
    setAnchor({ m, y })
    // Keep the same day-of-month where possible; clamp into the new month.
    const dom = new Date(focusStamp).getDate()
    const daysInMonth = new Date(y, m + 1, 0).getDate()
    setFocusStamp(startOfDay(new Date(y, m, Math.min(dom, daysInMonth)).getTime()))
  }

  const jumpToday = () => {
    const d = new Date(Date.now())
    setAnchor({ m: d.getMonth(), y: d.getFullYear() })
    setFocusStamp(startOfDay(Date.now()))
  }

  const toggleMode = () => {
    if (!wide) {
      return
    }

    const next: CalMode = effectiveMode === 'grid' ? 'agenda' : 'grid'
    sessionMode = next
    setMode(next)
  }

  const deepLink = (id: string | undefined, label: string) => {
    if (!id) {
      setFlash(`${label} has no linked forecast`)

      return
    }

    patchOverlayState({ calendar: false, forecasts: true, forecastsInitialId: id })
  }

  // Reset popover selection each time it opens.
  useEffect(() => {
    if (popoverOpen) {
      setPopoverSel(0)
      popoverScrollRef.current?.scrollTo?.(0)
    }
  }, [popoverOpen])

  useInput((ch, key) => {
    // ── Popover (grid day agenda) owns input while open ──────────────────────
    if (popoverOpen) {
      if (key.escape || ch === 'q') {
        return setPopoverOpen(false)
      }

      if (key.upArrow || ch === 'k') {
        return setPopoverSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || ch === 'j') {
        return setPopoverSel(i => Math.min(Math.max(0, focusEvents.length - 1), i + 1))
      }

      if (key.return) {
        const ev = focusEvents[popoverSel]

        if (ev) {
          return deepLink(ev.id, KIND_LABEL[ev.kind])
        }

        return
      }

      return
    }

    // ── Agenda filter text-entry mode ────────────────────────────────────────
    if (filtering) {
      if (key.return) {
        return setFiltering(false)
      }

      if (key.escape) {
        setQuery('')

        return setFiltering(false)
      }

      if (key.backspace || key.delete) {
        return setQuery(q => q.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setSel(0)

          return setQuery(q => q + printable)
        }
      }

      return
    }

    // ── Shared keys ──────────────────────────────────────────────────────────
    if (ch === 'q') {
      return onClose()
    }

    if (key.escape) {
      if (query) {
        return setQuery('')
      }

      return onClose()
    }

    if (ch === 'r') {
      return load(true)
    }

    // `h` (and the `?` alias) open the unified Help modal — consistent everywhere.
    if (ch === 'h' || ch === '?') {
      return openHelpOverlay()
    }

    // Tab toggles modes — but ONLY when the grid is available (wide).
    if (key.tab && wide) {
      return toggleMode()
    }

    if (effectiveMode === 'grid') {
      // ← moves the day focus left; `h` is now Help (handled above), so the vim
      // alias is retired. `l` still moves right.
      if (key.leftArrow) {
        return moveFocus(-1)
      }

      if (key.rightArrow || ch === 'l') {
        return moveFocus(1)
      }

      if (key.upArrow) {
        return moveFocus(-7)
      }

      if (key.downArrow) {
        return moveFocus(7)
      }

      if (key.pageUp || ch === '[') {
        return shiftMonth(-1)
      }

      if (key.pageDown || ch === ']') {
        return shiftMonth(1)
      }

      if (ch === 't') {
        return jumpToday()
      }

      if (key.return) {
        if (focusEvents.length) {
          return setPopoverOpen(true)
        }

        return
      }

      return
    }

    // ── Agenda mode ──────────────────────────────────────────────────────────
    if (ch === '/') {
      setQuery('')

      return setFiltering(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, agendaRows.length - 1), i + 1))
    }

    if (ch === 'g') {
      return setSel(0)
    }

    if (ch === 'G') {
      return setSel(Math.max(0, agendaRows.length - 1))
    }

    if (ch === 'o') {
      armReselect()

      return agendaSort.cycle()
    }

    if (ch === 'O') {
      armReselect()

      return agendaSort.toggle()
    }

    if (key.return) {
      if (selectedRow) {
        return deepLink(selectedRow.id, KIND_LABEL[selectedRow.kind])
      }

      return
    }
  }, { isActive: !globalModal })

  const width = Math.max(40, cols - 4)

  // ── Header ────────────────────────────────────────────────────────────────
  const header = effectiveMode === 'grid'
    ? (
        <Box flexShrink={0} marginBottom={1}>
          <Text wrap="truncate-end">
            <Text bold color={t.color.primary}>
              {`${MONTH_NAMES[anchor.m]} ${anchor.y}`}
            </Text>
            <Text color={t.color.muted}>{'  ·  '}</Text>
            <Text color={monthCounts.deadlines > 0 ? t.color.warn : t.color.label}>{monthCounts.deadlines}</Text>
            <Text color={t.color.muted}> deadline{monthCounts.deadlines === 1 ? '' : 's'} · </Text>
            <Text color={monthCounts.reviews > 0 ? t.color.accent : t.color.label}>{monthCounts.reviews}</Text>
            <Text color={t.color.muted}> review{monthCounts.reviews === 1 ? '' : 's'}</Text>
          </Text>
        </Box>
      )
    : (
        <Box flexShrink={0} marginBottom={1}>
          {filtering || query ? (
            <Text wrap="truncate-end">
              <Text bold color={t.color.primary}>CALENDAR</Text>
              <Text color={t.color.muted}>{'   '}</Text>
              <Text color={t.color.primary}>{'⌕ '}</Text>
              <Text color={t.color.text}>{query}</Text>
              {filtering ? <Text color={t.color.primary} inverse>{' '}</Text> : null}
              <Text color={t.color.muted}>
                {`   ${query ? `${filtered.length} matches · ` : ''}${filtering ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
              </Text>
            </Text>
          ) : (
            <Text wrap="truncate-end">
              <Text bold color={t.color.primary}>CALENDAR</Text>
              <Text color={t.color.muted}>{'   '}</Text>
              <Text color={t.color.text}>{events.length}</Text>
              <Text color={t.color.muted}> dated events · agenda</Text>
            </Text>
          )}
        </Box>
      )

  // ── Body ──────────────────────────────────────────────────────────────────
  let body

  if (loading && !data) {
    body = <Text color={t.color.muted}>Loading calendar…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load calendar: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (events.length === 0) {
    body = (
      <Text color={t.color.muted} wrap="wrap">
        No dated forecasts yet — set a close or resolution time on a question and it will show up here.
      </Text>
    )
  } else if (effectiveMode === 'grid') {
    body = (
      <MonthGrid
        eventsByDay={eventsByDay}
        focusStamp={focusStamp}
        rows={termRows}
        t={t}
        todayStamp={todayStamp}
        weeks={weeks}
        width={width}
      />
    )
  } else {
    body = (
      <AgendaTable
        cursor={clampedSel}
        onSelect={i => { if (!popoverOpen && !globalModal) {setSel(i)} }}
        onSort={popoverOpen || globalModal ? undefined : (key: string) => { armReselect(); agendaSort.sortByKey(key) }}
        query={query}
        rows={agendaRows}
        sortDir={agendaSort.state.dir}
        sortKey={agendaSort.state.key}
        t={t}
        visibleRows={Math.max(3, termRows - 10)}
        wallNow={wallNow}
        width={width}
      />
    )
  }

  // ── Footer chips — only the keys that are LIVE in this mode ────────────────
  const chips: FooterChip[] = effectiveMode === 'grid'
    ? [
        { k: '◀▶', label: 'Move' },
        { k: 'PgUp/Dn', label: 'Month', run: () => shiftMonth(1) },
        { k: 't', label: 'Today', run: () => jumpToday() },
        { k: '⏎', label: 'Day', run: () => { if (focusEvents.length) {setPopoverOpen(true)} } },
        ...(wide ? [{ k: '⇥', label: 'Agenda', run: () => toggleMode() }] : []),
        { k: 'r', label: 'Refresh', run: () => load(true) },
        { k: 'h', label: 'Help', run: openHelpOverlay },
        { k: 'q', label: 'Close', run: onClose }
      ]
    : [
        { k: '↑↓', label: 'Select' },
        { k: '⏎', label: 'Open', run: () => { if (selectedRow) {deepLink(selectedRow.id, KIND_LABEL[selectedRow.kind])} } },
        { k: 'o', label: 'Sort', run: () => { armReselect(); agendaSort.cycle() } },
        { k: '/', label: 'Filter', run: () => { setSel(0); setQuery(''); setFiltering(true) } },
        ...(wide ? [{ k: '⇥', label: 'Grid', run: () => toggleMode() }] : []),
        { k: 'r', label: 'Refresh', run: () => load(true) },
        { k: 'h', label: 'Help', run: openHelpOverlay },
        { k: 'q', label: 'Close', run: onClose }
      ]

  // Empty-state teaching line under the grid when THIS month is bare (the agenda
  // never hits this — an empty agenda already showed the no-events body above).
  const gridEmptyHint =
    effectiveMode === 'grid' && !loading && !error && events.length > 0 && monthCounts.deadlines === 0 && monthCounts.reviews === 0

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {gridEmptyHint ? (
        <Text color={t.color.muted} wrap="truncate-end">
          No deadlines this month — <Text color={t.color.accent}>]</Text> next month
        </Text>
      ) : null}
      <FooterChips chips={chips} disabled={popoverOpen || globalModal} t={t} />
      {flash ? <Text color={t.color.accent} wrap="truncate-end">{flash}</Text> : null}
    </Box>
  )

  // ── Day popover (grid Enter) ───────────────────────────────────────────────
  const popover = popoverOpen ? (
    <ModalOverlay
      cols={cols}
      footerHint="↑↓ select · ⏎ open on the Desk · Esc/q close"
      maxHeight={Math.min(20, focusEvents.length + 8)}
      maxWidth={64}
      rows={termRows}
      scrollRef={popoverScrollRef}
      t={t}
      tick={now}
      title={new Date(focusStamp).toLocaleDateString('en-US', { day: 'numeric', month: 'long', weekday: 'long', year: 'numeric' })}
    >
      <Box flexDirection="column">
        {focusEvents.map((ev, i) => {
          const active = i === popoverSel
          const days = daysBetween(ev.stamp, wallNow)

          return (
            <Box key={`${ev.id ?? ''}-${ev.kind}-${i}`} onClick={globalModal ? undefined : () => { setPopoverSel(i); deepLink(ev.id, KIND_LABEL[ev.kind]) }}>
              <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                <Text color={active ? t.color.accent : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                <Text color={kindColor(t, ev.kind)}>{`${KIND_GLYPH[ev.kind]} ${pad(KIND_LABEL[ev.kind], 8, 'left')}`}</Text>
                <Text color={t.color.text}>{truncate(ev.title, 34)}</Text>
                <Text color={proximityColor(t, days)}>{`  ${relIn(days)}`}</Text>
                {ev.id ? <Text color={t.color.accent}>{'  ⏎'}</Text> : null}
              </Text>
            </Box>
          )
        })}
      </Box>
    </ModalOverlay>
  ) : null

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
      {popover}
    </Box>
  )
}

// ── Month grid ───────────────────────────────────────────────────────────────
// Columns are packed manually (one <Text> line per grid row with 7 nested spans)
// rather than nested flex boxes — the same proven pattern the dense Desk table
// uses, so it renders precisely (and testably) even outside a real TTY.
function MonthGrid({
  eventsByDay,
  focusStamp,
  rows,
  t,
  todayStamp,
  weeks,
  width
}: {
  eventsByDay: Map<number, CalEvent[]>
  focusStamp: number
  rows: number
  t: Theme
  todayStamp: number
  weeks: DayCell[][]
  width: number
}) {
  const sem = semantics(t)
  const inner = Math.max(35, width)
  const cellW = Math.max(9, Math.floor((inner - 1) / 7))
  // Vertical budget: header lines already spent (~5), split the rest across weeks
  // and cap each cell at a day-number line + up to 3 marker lines.
  const cellRows = Math.max(2, Math.min(4, Math.floor((rows - 8) / Math.max(1, weeks.length))))
  const markerSlots = cellRows - 1

  return (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflow="hidden">
      {/* Weekday header. */}
      <Text bold color={sem.heading} wrap="truncate-end">
        {WEEKDAYS.map(d => pad(d, cellW, 'left')).join('')}
      </Text>
      {weeks.map((week, wi) => (
        <Box flexDirection="column" key={`w:${wi}`}>
          {Array.from({ length: cellRows }, (_, r) => (
            <Text key={`w:${wi}:r:${r}`} wrap="truncate-end">
              {week.map((cell, di) => {
                const focused = cell.stamp === focusStamp
                const isToday = cell.stamp === todayStamp
                const dayEvents = eventsByDay.get(cell.stamp) ?? []
                const bg = focused ? t.color.selectionBg : undefined

                // Row 0 = the day number.
                if (r === 0) {
                  const numColor = focused
                    ? t.color.text
                    : isToday
                      ? t.color.accent
                      : cell.inMonth
                        ? t.color.text
                        : t.color.muted

                  const label = `${isToday ? '•' : ' '}${cell.day}`

                  return (
                    <Text backgroundColor={bg} bold={isToday || focused} color={numColor} key={`d:${di}`}>
                      {pad(label, cellW, 'left')}
                    </Text>
                  )
                }

                // Marker rows.
                const idx = r - 1
                const overflow = dayEvents.length > markerSlots

                if (overflow && idx === markerSlots - 1) {
                  const hidden = dayEvents.length - (markerSlots - 1)

                  return (
                    <Text backgroundColor={bg} color={t.color.muted} key={`d:${di}`}>
                      {pad(`  +${hidden}`, cellW, 'left')}
                    </Text>
                  )
                }

                const ev = dayEvents[idx]

                if (!ev) {
                  return (
                    <Text backgroundColor={bg} key={`d:${di}`}>{pad('', cellW, 'left')}</Text>
                  )
                }

                return (
                  <Text backgroundColor={bg} color={kindColor(t, ev.kind)} key={`d:${di}`}>
                    {pad(` ${KIND_GLYPH[ev.kind]} ${truncate(ev.title, Math.max(2, cellW - 4))}`, cellW, 'left')}
                  </Text>
                )
              })}
            </Text>
          ))}
        </Box>
      ))}
      {/* A muted legend keying the marker colours (the grid itself is
          month-scoped by `weeks`; the month name already lives in the header). */}
      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="truncate-end">
          <Text color={t.color.error}>● close</Text>
          <Text color={t.color.muted}>{'  '}</Text>
          <Text color={t.color.warn}>◆ resolve</Text>
          <Text color={t.color.muted}>{'  '}</Text>
          <Text color={t.color.accent}>◇ review</Text>
          <Text color={t.color.muted}>{'   ⏎ opens the focused day'}</Text>
        </Text>
      </Box>
    </Box>
  )
}

// ── Agenda table ─────────────────────────────────────────────────────────────
// DATE | IN | QUESTION | KIND | PROB — desk-grade density with a header rule and
// click-to-sort headers. Reuses windowItems for scrolling and the shared pad().
interface AgendaCol {
  align: 'left' | 'right'
  key: string
  label: string
  w: number
}

function AgendaTable({
  cursor,
  onSelect,
  onSort,
  query,
  rows,
  sortDir,
  sortKey,
  t,
  visibleRows,
  wallNow,
  width
}: {
  cursor: number
  onSelect: (i: number) => void
  onSort?: (key: string) => void
  query: string
  rows: CalEvent[]
  sortDir: SortDir
  sortKey: null | string
  t: Theme
  visibleRows: number
  wallNow: number
  width: number
}) {
  const sem = semantics(t)
  const avail = Math.max(30, width - 2)
  const cDate = 7
  const cIn = 5
  const cKind = 8
  const cProb = 6
  const fixed = cDate + 1 + cIn + 1 + cKind + 1 + cProb + 1
  const qW = Math.max(12, avail - fixed - 2)

  const cols: AgendaCol[] = [
    { align: 'left', key: 'date', label: 'DATE', w: cDate },
    { align: 'right', key: 'in', label: 'IN', w: cIn },
    { align: 'left', key: 'q', label: 'QUESTION', w: qW },
    { align: 'left', key: 'kind', label: 'KIND', w: cKind },
    { align: 'right', key: 'prob', label: 'PROB', w: cProb }
  ]

  if (!rows.length) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted} wrap="wrap">
          {query ? `No events match "${query}".` : 'No dated events — set a close or resolution time on a question.'}
        </Text>
      </Box>
    )
  }

  const { items: windowed, offset } = windowItems(rows, Math.max(0, cursor), visibleRows)

  return (
    <Box flexDirection="column" flexGrow={0} flexShrink={0} minHeight={0} overflow="hidden">
      <Box>
        <Text bold color={sem.heading}>{'  '}</Text>
        {cols.map(c => {
          const active = sortKey === c.key
          const ind = active ? ` ${sortIndicator({ dir: sortDir, key: sortKey }, c.key)}` : ''

          return (
            <Box key={c.key} onClick={onSort ? () => onSort(c.key) : undefined}>
              <Text bold color={active ? t.color.accent : sem.heading}>
                {`${pad(`${c.label}${ind}`, c.w, c.align)} `}
              </Text>
            </Box>
          )
        })}
      </Box>
      <Text color={sem.rule}>{'─'.repeat(avail)}</Text>
      {windowed.map((ev, i) => {
        const index = offset + i
        const active = index === cursor
        const days = daysBetween(ev.stamp, wallNow)

        return (
          <Box key={`${ev.id ?? ''}-${ev.kind}-${index}`} onClick={() => onSelect(index)} width={width}>
            <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
              <Text bold={active} color={active ? sem.cursor : sem.faint}>{active ? '▸ ' : '  '}</Text>
              <Text color={t.color.muted}>{`${pad(calDate(ev.stamp), cDate, 'left')} `}</Text>
              <Text color={proximityColor(t, days)}>{`${pad(relIn(days), cIn, 'right')} `}</Text>
              <Text bold={active} color={active ? sem.selectionFg : t.color.text}>{`${pad(truncate(ev.title, qW), qW, 'left')} `}</Text>
              <Text color={kindColor(t, ev.kind)}>{`${pad(KIND_LABEL[ev.kind], cKind, 'left')} `}</Text>
              <Text color={t.color.muted}>{pad(ev.prob, cProb, 'right')}</Text>
            </Text>
          </Box>
        )
      })}
      {rows.length > windowed.length ? (
        <Text color={t.color.muted}>{`  ${offset + windowed.length}/${rows.length}`}</Text>
      ) : null}
    </Box>
  )
}
