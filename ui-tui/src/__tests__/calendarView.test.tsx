import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { getOverlayState, resetOverlayState } from '../app/overlayStore.js'
import {
  buildMonthMatrix,
  parseCalEvents,
  proximityBucket,
  relIn,
  resetCalendarSession,
  startOfDay
} from '../components/calendarView.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const UP = `${ESC}[A`
const DOWN = `${ESC}[B`
const RIGHT = `${ESC}[C`
const LEFT = `${ESC}[D`

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
]

// ── Pure grid / proximity / parse helpers ────────────────────────────────────

describe('calendar grid math (buildMonthMatrix)', () => {
  it('lays leap February 2024 (29 days) into 5 Monday-first weeks', () => {
    const weeks = buildMonthMatrix(2024, 1) // Feb 2024, Feb 1 is a Thursday
    expect(weeks.length).toBe(5)
    // Feb 1 sits at column index 3 (Mon..Thu), the three leading cells are Jan.
    expect(weeks[0][3].day).toBe(1)
    expect(weeks[0][3].inMonth).toBe(true)
    expect(weeks[0][0].inMonth).toBe(false)
    // Exactly 29 in-month cells and the 29th is present + in-month.
    const inMonth = weeks.flat().filter(c => c.inMonth)
    expect(inMonth.length).toBe(29)
    expect(inMonth.some(c => c.day === 29)).toBe(true)
  })

  it('a 28-day February that starts on Monday collapses to exactly 4 weeks', () => {
    const weeks = buildMonthMatrix(2021, 1) // Feb 2021, Feb 1 is a Monday
    expect(weeks.length).toBe(4)
    expect(weeks[0][0].day).toBe(1)
    expect(weeks[0][0].inMonth).toBe(true)
    expect(weeks.flat().filter(c => c.inMonth).length).toBe(28)
  })

  it('pads leading + trailing neighbour days so every row holds 7 cells', () => {
    const weeks = buildMonthMatrix(2026, 6) // July 2026, starts Wednesday

    for (const week of weeks) {
      expect(week.length).toBe(7)
    }

    // The trailing days of the final week belong to the next month.
    const last = weeks[weeks.length - 1]
    expect(last[6].inMonth).toBe(false)
    // July has 31 in-month days.
    expect(weeks.flat().filter(c => c.inMonth).length).toBe(31)
  })

  it('startOfDay zeroes the clock', () => {
    const noon = new Date(2026, 6, 3, 13, 45, 12).getTime()
    const start = startOfDay(noon)
    expect(new Date(start).getHours()).toBe(0)
    expect(new Date(start).getDate()).toBe(3)
  })
})

describe('proximity + relative-in helpers', () => {
  it('proximityBucket boundaries: <=2 danger, <=7 warn, else muted', () => {
    expect(proximityBucket(-1)).toBe('danger')
    expect(proximityBucket(0)).toBe('danger')
    expect(proximityBucket(2)).toBe('danger')
    expect(proximityBucket(3)).toBe('warn')
    expect(proximityBucket(7)).toBe('warn')
    expect(proximityBucket(8)).toBe('muted')
  })

  it('relIn is compact days → weeks → months, past collapses to "now"', () => {
    expect(relIn(-5)).toBe('now')
    expect(relIn(0)).toBe('now')
    expect(relIn(2)).toBe('2d')
    expect(relIn(13)).toBe('13d')
    expect(relIn(14)).toBe('2w')
    expect(relIn(21)).toBe('3w')
    expect(relIn(60)).toBe('2mo')
  })
})

describe('parseCalEvents', () => {
  const response: ForecastDashboardResponse = {
    summary: {
      questions: [
        {
          close_time: '2026-07-10T00:00:00Z',
          id: 'fq_texas',
          probability: 0.52,
          resolution_time: '2026-11-03T00:00:00Z',
          title: 'Texas Senate'
        }
      ],
      scheduled_review_runs: [
        { id: 'sr_1', next_run_at: '2026-07-05T00:00:00Z', scope_ref: 'fq_texas', scope_type: 'question' }
      ]
    }
  }

  it('emits close + resolve + review events sorted by stamp, resolving the review title from its scope question', () => {
    const events = parseCalEvents(response, Date.parse('2026-07-01T00:00:00Z'))
    expect(events.map(e => e.kind)).toEqual(['review', 'close', 'resolve'])
    const review = events.find(e => e.kind === 'review')
    expect(review?.title).toBe('Texas Senate')
    expect(review?.id).toBe('fq_texas')
    const close = events.find(e => e.kind === 'close')
    expect(close?.prob).toBe('52%')
  })

  it('returns nothing for an empty payload', () => {
    expect(parseCalEvents(null, Date.now())).toEqual([])
    expect(parseCalEvents({ summary: { questions: [] } }, Date.now())).toEqual([])
  })
})

// ── Rendered view ────────────────────────────────────────────────────────────

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isRaw?: boolean
    isTTY: boolean
    ref?: () => PassThrough
    rows: number
    setRawMode?: (mode: boolean) => void
    unref?: () => PassThrough
  }

  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (mode: boolean) => {
      stream.isRaw = mode
    },
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// A dashboard fixture anchored on "now" so the default grid month + focused day
// both hold the close event (the grid opens on today's month and focuses today).
const nowIso = () => new Date().toISOString()
const inDaysIso = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString()

const liveFixture = (): ForecastDashboardResponse => ({
  summary: {
    questions: [
      { close_time: nowIso(), id: 'fq_texas', probability: 0.52, title: 'Texas Senate' },
      { id: 'fq_cpi', resolution_time: inDaysIso(5), title: 'CPI print' },
      { close_time: inDaysIso(3), id: 'fq_fed', probability: 0.4, title: 'Fed decision' }
    ]
  }
})

const fakeGw = (response: ForecastDashboardResponse) =>
  ({ request: () => Promise.resolve(response) }) as never

// The component reads its width from useStdout(), which the ink build maps to
// process.stdout (NOT the injected stream) — so drive the grid/agenda mode switch
// by setting process.stdout.columns for the mount, restoring it after.
const mount = async (columns: number, response: ForecastDashboardResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'
  ;(process.stdout as unknown as { columns: number }).columns = columns

  const [{ render }, { CalendarView }, { DARK_THEME }, { stripAnsi }, { clearOverlayCache }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/calendarView.js'),
    import('../theme.js'),
    import('../lib/text.js'),
    import('../lib/overlayCache.js')
  ])

  clearOverlayCache()
  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const instance = render(
    React.createElement(CalendarView, { gw: fakeGw(response), onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(60)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(60)
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('CalendarView (grid + agenda redesign)', () => {
  const originalColumns = (process.stdout as unknown as { columns?: number }).columns
  beforeEach(() => {
    resetCalendarSession()
    resetOverlayState()
  })
  afterEach(() => {
    resetOverlayState()
    delete process.env.FORECAST_TUI_INLINE
    ;(process.stdout as unknown as { columns?: number }).columns = originalColumns
  })

  it('defaults to the MONTH GRID when wide, with the month summary + weekday header', async () => {
    const cal = await mount(140, liveFixture())
    const text = cal.text()
    const monthName = MONTH_NAMES[new Date().getMonth()]
    expect(text).toContain(monthName)
    // Weekday header row (Monday-first).
    expect(text).toContain('Mon')
    expect(text).toContain('Sun')
    // Summary line words.
    expect(text).toMatch(/deadline/)
    expect(text).toMatch(/review/)
    // A today event marker surfaces its (short) title in the grid.
    expect(text).toContain('Texas Senate')
    cal.cleanup()
  })

  it('forces AGENDA on a narrow terminal (grid never renders)', async () => {
    const cal = await mount(80, liveFixture())
    const text = cal.text()
    expect(text).toContain('CALENDAR')
    // Dense agenda columns.
    expect(text).toContain('DATE')
    expect(text).toContain('QUESTION')
    expect(text).toContain('KIND')
    expect(text).toContain('PROB')
    // No 7-column weekday header in agenda mode.
    expect(text).not.toContain('Mon Tue')
    cal.cleanup()
  })

  it('Tab toggles grid ↔ agenda on a wide terminal', async () => {
    const cal = await mount(140, liveFixture())
    // Default is grid.
    expect(cal.text()).toContain(MONTH_NAMES[new Date().getMonth()])
    // Tab → agenda: the dense table header appears.
    await cal.press('\t')
    expect(cal.text()).toContain('QUESTION')
    // Tab → back to grid: the weekday header returns.
    await cal.press('\t')
    expect(cal.text()).toContain('Mon')
    cal.cleanup()
  })

  it('grid month navigation: ] steps to next month, [ steps back', async () => {
    const cal = await mount(140, liveFixture())
    const now = new Date()
    const nextName = MONTH_NAMES[(now.getMonth() + 1) % 12]
    await cal.press(']')
    expect(cal.text()).toContain(nextName)
    // Back two → previous month.
    await cal.press('[')
    await cal.press('[')
    const prevName = MONTH_NAMES[(now.getMonth() + 11) % 12]
    expect(cal.text()).toContain(prevName)
    cal.cleanup()
  })

  it('day-focus arrow nav crosses the month edge (six ↑ = 42 days back changes the anchor month)', async () => {
    const cal = await mount(140, liveFixture())

    for (let i = 0; i < 6; i += 1) {
      await cal.press(UP)
    }

    const back = new Date(Date.now() - 42 * 86_400_000)
    expect(cal.text()).toContain(MONTH_NAMES[back.getMonth()])
    cal.cleanup()
  })

  it('grid Enter opens the focused-day popover, and Enter on an event deep-links to the Desk', async () => {
    const cal = await mount(140, liveFixture())
    // Today is focused and holds the Texas close event → Enter opens the popover.
    await cal.press('\r')
    expect(cal.text()).toContain('open on the Desk') // popover footer hint (popover-only)
    // Body still visible behind the overlay.
    expect(cal.text()).toContain(MONTH_NAMES[new Date().getMonth()])
    // Enter on the selected event deep-links.
    await cal.press('\r')
    expect(getOverlayState().forecasts).toBe(true)
    expect(getOverlayState().forecastsInitialId).toBe('fq_texas')
    expect(getOverlayState().calendar).toBe(false)
    cal.cleanup()
  })

  it('agenda Enter deep-links the selected row to the Desk', async () => {
    const cal = await mount(80, liveFixture())
    // Default agenda sort is DATE asc; row 0 is the earliest event (Texas, today).
    await cal.press('\r')
    expect(getOverlayState().forecasts).toBe(true)
    expect(getOverlayState().forecastsInitialId).toBe('fq_texas')
    cal.cleanup()
  })

  it('agenda o sorts the DATE column and marks the header with ▲', async () => {
    const cal = await mount(80, liveFixture())
    await cal.press('o')
    expect(cal.text()).toContain('DATE ▲')
    cal.cleanup()
  })

  it('agenda / filter narrows the visible events', async () => {
    const cal = await mount(80, liveFixture())
    await cal.press('/')
    await cal.press('fed')
    const text = cal.text()
    expect(text).toContain('⌕')
    expect(text).toContain('1 matches')
    expect(text).toContain('Fed decision')
    cal.cleanup()
  })

  it('teaches an empty state when there are no dated events at all', async () => {
    const cal = await mount(140, { summary: { questions: [] } })
    expect(cal.text()).toContain('No dated forecasts yet')
    cal.cleanup()
  })
})
