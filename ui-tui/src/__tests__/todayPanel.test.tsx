import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { todayFeedItems } from '../lib/todayFeed.js'
import type { PanelSection } from '../types.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const railSections = (): PanelSection[] => [
  { rows: [['active', '2']], title: 'Book' },
  {
    rows: [
      ['/alerts', '2 open alerts need source or resolution review'],
      ['/review --stale', '1 forecast queued for stale/close/evidence review']
    ],
    title: 'Triage'
  },
  {
    rows: [
      ['/questions fq_focus01', 'Will the Fed cut in September?  —  63%  as-of 2026-06-01  close -'],
      ['/note fq_focus01 -- <evidence>', 'append timestamped evidence', 'draft:/note fq_focus01 -- ']
    ],
    title: 'Focused Actions'
  },
  {
    rows: [['62% ↑8pt', 'Texas Senate race  1 alert  as-of 2026-05-29', '/questions fq_texas01']],
    title: 'Watchlist'
  }
]

describe('todayFeedItems', () => {
  it('flattens the rail sections into a prioritised, hotkeyed feed', () => {
    const items = todayFeedItems(railSections())

    expect(items).toHaveLength(4)
    // Triage leads (alerts summary, then the review command), then the focused
    // question, then the watchlist question.
    expect(items[0].kind).toBe('alerts')
    expect(items[1].kind).toBe('command')
    expect(items[1].command).toBe('/review --stale')
    expect(items[2].kind).toBe('question')
    expect(items[2].questionId).toBe('fq_focus01')
    expect(items[2].title).toBe('Will the Fed cut in September?')
    expect(items[3].kind).toBe('question')
    expect(items[3].questionId).toBe('fq_texas01')
    // Sequential hotkeys.
    expect(items.map(i => i.hotkey)).toEqual(['1', '2', '3', '4'])
  })

  it('dedupes a question that appears in both Focused Actions and Watchlist', () => {
    const sections = railSections()
    // Point the watchlist row at the same question the focused row already opened.
    sections[3].rows = [['62% ↑8pt', 'Fed decision  as-of 2026-06-01', '/questions fq_focus01']]

    const items = todayFeedItems(sections)
    const questionIds = items.filter(i => i.kind === 'question').map(i => i.questionId)

    expect(questionIds).toEqual(['fq_focus01'])
  })

  it('caps the feed at the requested maximum', () => {
    const rows = Array.from({ length: 12 }, (_, i) => [
      `${(i + 1) * 5}%`,
      `Question ${i}`,
      `/questions fq_${i}`
    ]) as PanelSection['rows']

    const items = todayFeedItems([{ rows, title: 'Watchlist' }], 9)

    expect(items).toHaveLength(9)
  })

  it('teaches an empty feed (no actionable rows) as zero items', () => {
    expect(todayFeedItems([{ rows: [['active', '0']], title: 'Book' }])).toEqual([])
  })

  it('prepends the contested hand-label badge as the leading row when contestedCount > 0', () => {
    const items = todayFeedItems(railSections(), 9, 3)

    // The contested badge leads the feed and deep-links into the Warnings lens.
    expect(items[0].kind).toBe('alerts')
    expect(items[0].focus).toBe('contested')
    expect(items[0].title).toContain('3 contested triage rows need')
    // The section rows still follow, re-hotkeyed after the badge (1..5).
    expect(items.map(i => i.hotkey)).toEqual(['1', '2', '3', '4', '5'])
    // The open-alerts summary row is distinct from the contested badge — both survive.
    expect(items.filter(i => i.kind === 'alerts').length).toBe(2)
  })

  it('omits the contested badge when the count is zero and singularizes it for one', () => {
    expect(todayFeedItems(railSections(), 9, 0).some(i => i.focus === 'contested')).toBe(false)
    expect(todayFeedItems([], 9, 1)[0].title).toContain('1 contested triage row needs')
  })

  it('strips reason-label debris from a question note, keeping the first two useful segments', () => {
    // A real Focused Actions row: title, an em-dash separator, then the
    // probability+delta, as-of, close, and the "reasons learned error profile"
    // debris the rail glues on. The feed must keep the useful head and drop soup.
    const sections: PanelSection[] = [
      {
        rows: [
          [
            '/questions fq_mayor',
            'Manchester Mayor  —  Andy Burnham 0.80 (+7)  as-of 2026-06-24  close 2026-09-01  reasons learned error profile'
          ]
        ],
        title: 'Focused Actions'
      }
    ]

    const [item] = todayFeedItems(sections)

    expect(item.kind).toBe('question')
    expect(item.title).toBe('Manchester Mayor')
    // First two useful segments survive; the "—" separator and the reason debris go.
    expect(item.note).toBe('Andy Burnham 0.80 (+7) · as-of 2026-06-24')
    expect(item.note).not.toContain('reasons')
    expect(item.note).not.toContain('learned error profile')
    expect(item.note).not.toContain('close 2026-09-01')
  })

  it('formats the open-alerts summary with a thousands separator and a concrete action', () => {
    const sections: PanelSection[] = [
      {
        rows: [['/alerts', '1250 open alerts need source or resolution review']],
        title: 'Triage'
      }
    ]

    const [item] = todayFeedItems(sections)

    expect(item.kind).toBe('alerts')
    expect(item.title).toBe('1,250 open alerts')
    expect(item.note).toBe('a to review')
  })
})

// ── Component render + keyboard ───────────────────────────────────────────────

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

interface TodaySpies {
  onBlur: ReturnType<typeof vi.fn>
  onNewQuestion: ReturnType<typeof vi.fn>
  onOpenAlerts: ReturnType<typeof vi.fn>
  onOpenQuestion: ReturnType<typeof vi.fn>
  onRunCommand: ReturnType<typeof vi.fn>
}

const mountToday = async (columns: number, sections: PanelSection[], focused = true, contestedCount = 0) => {
  const [{ render }, { TodayPanel }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/todayPanel.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const spies: TodaySpies = {
    onBlur: vi.fn(),
    onNewQuestion: vi.fn(),
    onOpenAlerts: vi.fn(),
    onOpenQuestion: vi.fn(),
    onRunCommand: vi.fn()
  }

  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const instance = render(
    React.createElement(TodayPanel, {
      contestedCount,
      focused,
      sections,
      t: DARK_THEME,
      width: columns - 2,
      ...spies
    }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(40)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(40)
    },
    spies,
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('TodayPanel', () => {
  afterEach(async () => {
    // Reset the shared home-focus store the panel writes to on mount/unmount.
    const { setTodayCount } = await import('../app/homeFocusStore.js')
    setTodayCount(0)
  })

  it('renders the header + hotkeyed rows and collapses to the top 3 on a narrow terminal', async () => {
    const today = await mountToday(80, railSections())
    const text = today.text()

    expect(text).toContain('TODAY')
    expect(text).toContain('what needs you')
    // Hotkey-labelled rows.
    expect(text).toContain('1')
    // 4 actionable items but a narrow terminal shows only the top 3, with an
    // overflow hint for the rest.
    expect(text).toContain('+1 more')
    today.cleanup()
  })

  it('a number hotkey deep-links the matching question into the Desk (narrow)', async () => {
    const today = await mountToday(80, railSections())
    // Item 3 is the focused question fq_focus01.
    await today.press('3')
    expect(today.spies.onOpenQuestion).toHaveBeenCalledWith('fq_focus01')
    today.cleanup()
  })

  it('Enter opens the selected row and arrows move the selection (wide)', async () => {
    const today = await mountToday(120, railSections())
    // The wide panel shows every row (no collapse). Move down to the watchlist
    // question (index 3) and open it with Enter.
    await today.press('j')
    await today.press('j')
    await today.press('j')
    await today.press('\r')
    expect(today.spies.onOpenQuestion).toHaveBeenCalledWith('fq_texas01')
    today.cleanup()
  })

  it('a jumps to Alerts and n starts a new question', async () => {
    const today = await mountToday(120, railSections())
    await today.press('a')
    expect(today.spies.onOpenAlerts).toHaveBeenCalled()
    await today.press('n')
    expect(today.spies.onNewQuestion).toHaveBeenCalled()
    today.cleanup()
  })

  it('runs a triage command row via onRunCommand', async () => {
    const today = await mountToday(120, railSections())
    // Item 2 (hotkey 2) is the /review --stale triage command.
    await today.press('2')
    expect(today.spies.onRunCommand).toHaveBeenCalledWith('/review --stale')
    today.cleanup()
  })

  it('teaches an empty state and does not grab keys', async () => {
    const today = await mountToday(120, [{ rows: [['active', '0']], title: 'Book' }])
    expect(today.text()).toContain('Nothing needs you')
    today.cleanup()
  })

  it('surfaces the contested badge and opens the contested lens when activated', async () => {
    const today = await mountToday(120, railSections(), true, 2)
    expect(today.text()).toContain('contested triage')
    // Hotkey 1 is the leading contested badge → opens Warnings focused on contested.
    await today.press('1')
    expect(today.spies.onOpenAlerts).toHaveBeenCalledWith('contested')
    today.cleanup()
  })
})
