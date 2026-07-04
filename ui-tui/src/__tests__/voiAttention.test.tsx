import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

import type { ForecastNextAction, ForecastThesis, ForecastWorkspaceItem } from '../protocol/generated.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const writeStream = (columns: number, rows: number) => {
  const stream = new PassThrough() as PassThrough & { columns: number; isTTY: boolean; rows: number }
  let output = ''
  Object.assign(stream, { columns, isTTY: false, ref: () => stream, rows, unref: () => stream })
  stream.on('data', chunk => {
    output += chunk.toString()
  })
  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, '')).replace(/[ \t]+\n/g, '\n').trim()

// ── the sort mode ─────────────────────────────────────────────────────────────

describe('VOI desk sort', () => {
  it('deskSortValue negates the voi score so ASCENDING surfaces the highest first', async () => {
    const { deskSortValue } = await import('../components/deskView.js')
    const high: ForecastWorkspaceItem = { id: 'h', voi: { score: 0.9 } }
    const low: ForecastWorkspaceItem = { id: 'l', voi: { score: 0.1 } }
    expect(deskSortValue(high, 'voi', 0)).toBe(-0.9)
    expect(deskSortValue(low, 'voi', 0)).toBe(-0.1)
    // Ascending compares -0.9 < -0.1 → the high-VOI row lands first (most urgent).
    expect((deskSortValue(high, 'voi', 0) as number) < (deskSortValue(low, 'voi', 0) as number)).toBe(true)
    // No voi block → null (sorts last, never a fabricated 0).
    expect(deskSortValue({ id: 'x' }, 'voi', 0)).toBeNull()
  })

  it('registers a human label for the keyless voi sort mode', async () => {
    const { SORT_MODE_LABELS } = await import('../components/deskView.js')
    expect(SORT_MODE_LABELS.voi).toMatch(/value.of.information/i)
  })
})

// ── the "Next best actions" summary block ────────────────────────────────────

describe('NextBestActions block', () => {
  const render = async (actions: ForecastNextAction[]) => {
    const [{ renderSync }, { NextBestActions }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])
    const stdout = writeStream(120, 40)
    renderSync(
      React.createElement(NextBestActions, { actions, t: DARK_THEME, width: 44 }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    return normalize(stdout.text(), stripAnsi)
  }

  const sample = (): ForecastNextAction[] => [
    { action: 'update', question_id: 'q1', reason: 'Stale 9d (1.29x cadence) and moves the thesis 4.20pp', score: 0.71, title: 'Alpha race' },
    { action: 'add_sources', question_id: 'q2', reason: 'no watched sources — U would re-pool nothing; add a source first', score: 0.44, title: 'Beta race' },
    { action: 'review_due', question_id: 'q3', reason: 'Resolves now — verify the outcome', score: 0.3, title: 'Gamma race' },
    { action: 'update', question_id: 'q4', reason: 'fourth', score: 0.2, title: 'Delta race' }
  ]

  it('renders the top-3 with keystroke badges + one-sentence reasons (4th dropped)', async () => {
    const text = await render(sample())
    expect(text).toContain('Next best actions')
    expect(text).toContain('Alpha race')
    expect(text).toContain('Beta race')
    expect(text).toContain('Gamma race')
    expect(text).not.toContain('Delta race') // capped at 3
    // The action badges hint the operator's next keystroke.
    expect(text).toContain('U')
    expect(text).toContain('+src')
    expect(text).toContain('R')
    // The honest add_sources reason is carried (a single hyphenated token that a
    // space-wrap never splits).
    expect(text).toContain('re-pool')
  })

  it('renders nothing on a quiet book (no actions)', async () => {
    expect(await render([])).toBe('')
  })
})

// ── the thesis-lens sensitivity marker ───────────────────────────────────────

describe('thesis-lens sensitivity marker', () => {
  const member = (): ForecastWorkspaceItem => ({
    as_of: '2026-06-29T00:00:00Z',
    headline_kind: 'probability',
    headline_probability: 0.44,
    history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.44 }],
    id: 'fq_cpi',
    status: 'active',
    title: 'CPI-U YoY'
  })

  const thesisWithSens = (delta: number): ForecastThesis => ({
    history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.53 }],
    id: 'th_1',
    status: 'active',
    title: 'Sticky inflation',
    top_sensitivities: [{ delta_p_event: delta, member_id: 'fq_cpi' }]
  })

  const renderList = async (items: ForecastWorkspaceItem[], props: Record<string, unknown>) => {
    const [{ renderSync }, { DeskForecastList }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])
    const stdout = writeStream(112, 40)
    renderSync(
      React.createElement(DeskForecastList as never, {
        cursor: -1,
        empty: 'none',
        items,
        markedIds: new Set<string>(),
        nowMs: Math.floor(Date.now() / 60_000) * 60_000,
        onSelect: () => undefined,
        runningIds: new Set<string>(),
        sortDir: 'asc',
        sortKey: null,
        t: DARK_THEME,
        visibleRows: 12,
        width: 104,
        ...props
      } as never),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    return normalize(stdout.text(), stripAnsi)
  }

  it('shows a dim ⇅±pp marker on member rows when a thesis is pinned', async () => {
    const text = await renderList([member()], { pinnedThesis: thesisWithSens(0.042) })
    expect(text).toContain('⇅')
    expect(text).toContain('+4.20') // signed, 2dp — never a truncated value
  })

  it('omits the marker off the thesis lens (no pinned thesis → byte-identical row)', async () => {
    const text = await renderList([member()], {})
    expect(text).not.toContain('⇅')
  })

  it('omits the marker for a member with negligible (<0.01pp) sensitivity', async () => {
    const text = await renderList([member()], { pinnedThesis: thesisWithSens(0.00001) })
    expect(text).not.toContain('⇅')
  })
})
