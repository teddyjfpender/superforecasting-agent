import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

import type { ObsidianNoteResponse, ObsidianStatusResponse } from '../gatewayTypes.js'
import { type Match, waitForQuiet, waitForSettled, waitForText } from '../testing/settle.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

// A note with frontmatter, headings (→ outline), a wikilink, bold, a list and
// some inline math — exercises every render path the user cares about.
const NOTE_BODY = `---
tags: [forecasting, method]
type: note
---

# Bayesian Updating

Update beliefs in proportion to how **diagnostic** the evidence is.

## Work in log-odds

The likelihood ratio drives the move. Math: $E = mc^2$.

- pool independent estimates
- avoid double counting

See [[Calibration and Scoring]] for the scoring side.
`

const statusFixture = (): ObsidianStatusResponse =>
  ({
    count: 2,
    exists: true,
    notes: [
      {
        excerpt: 'Update beliefs…',
        folder: 'Forecasting/Knowledge',
        links: ['Calibration and Scoring'],
        modified: 0,
        rel_path: 'Forecasting/Knowledge/Bayesian Updating.md',
        size: NOTE_BODY.length,
        title: 'Bayesian Updating'
      },
      {
        excerpt: 'Scoring…',
        folder: 'Forecasting/Knowledge',
        links: [],
        modified: 0,
        rel_path: 'Forecasting/Knowledge/Calibration and Scoring.md',
        size: 10,
        title: 'Calibration and Scoring'
      }
    ],
    vault: '/tmp/vault'
  }) as unknown as ObsidianStatusResponse

const noteFixture = (): ObsidianNoteResponse =>
  ({ content: NOTE_BODY, rel_path: 'Forecasting/Knowledge/Bayesian Updating.md', size: NOTE_BODY.length, truncated: false }) as ObsidianNoteResponse

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

const renderView = async () => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { ObsidianView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/obsidianView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 50)
  const stdin = writeStream(120, 50, true)

  const fakeGw = {
    off: () => undefined,
    on: () => undefined,
    request: (method: string) =>
      method === 'obsidian.note' ? Promise.resolve(noteFixture()) : Promise.resolve(statusFixture())
  } as unknown as Parameters<typeof ObsidianView>[0]['gw']

  const instance = render(
    React.createElement(ObsidianView, { gw: fakeGw, onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  const read = () => normalize(stdout.text(), stripAnsi)

  // The view resolves obsidian.status THEN obsidian.note before it can paint the
  // note. A fixed `tick(80)` asserted against whatever was on screen at 80ms,
  // which under parallel load was the "not connected / Loading…" frame — the
  // cause of this file's intermittent failures.
  //
  // Wait for the LAST thing the note produces, not the first: the `Outline` pane
  // title paints as soon as the note pane exists, while the markdown body is
  // still rendering, so waiting on it left the body assertions racing.
  await waitForSettled(read, 'pool independent estimates', { label: 'the note body to render' })

  const text = read()

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    // Send a key and wait for the repaint it caused (bounded, so a key with no
    // visual effect does not hang). Used where a step has no distinctive text
    // of its own to wait for — sending keys back-to-back lets the view coalesce
    // or drop them under load.
    press: async (keys: string) => {
      const before = read()

      stdin.stream.write(keys)

      try {
        await waitForText(read, value => value !== before, { label: 'the keypress repaint', timeout: 2000 })
      } catch {
        // No visual change for this key — carry on.
      }

      await waitForQuiet(read, { quietFor: 24, timeout: 1000 })
    },
    read,
    stdin: stdin.stream,
    text,
    waitFor: (match: Match, label?: string) => waitForText(read, match, { label })
  }
}

describe('ObsidianView render', () => {
  it('renders markdown, an outline of headings, LaTeX and wikilinks for the open note', async () => {
    const { cleanup, text } = await renderView()

    // Frontmatter is stripped (no raw --- rule, no `type: note` line in the body)
    expect(text).not.toContain('type: note')

    // Outline pane lists the markdown headings
    expect(text).toContain('Outline')
    expect(text).toContain('Bayesian Updating')
    expect(text).toContain('Work in log-odds')

    // Markdown body content renders (bold word survives, list item present)
    expect(text).toContain('diagnostic')
    expect(text).toContain('pool independent estimates')

    // LaTeX is converted to unicode (mc² rather than the raw $E = mc^2$)
    expect(text).toContain('²')
    expect(text).not.toContain('$E = mc^2$')

    // The inline [[wikilink]] renders as a styled, clickable link (glyph +
    // label), not raw brackets — and there's no redundant Links index now.
    expect(text).toContain('↗Calibration and Scoring')
    expect(text).not.toContain('[[Calibration and Scoring]]')
    expect(text).not.toContain('click to open')

    cleanup()
  })

  it('opens the centered search modal on "s"', async () => {
    const { cleanup, stdin, waitFor } = await renderView()

    stdin.write('s')
    // Wait for the modal to paint rather than for a fixed 60ms — under load the
    // keypress pipeline alone can outlast that.
    const text = await waitFor('Search the vault', 'the search modal')

    expect(text).toContain('Search the vault')
    expect(text).toContain('Type to search')

    cleanup()
  })

  it('selects a multi-line range (v then move) and cites it as a range, not L1', async () => {
    const { cleanup, press, waitFor } = await renderView()

    // Each key waits for its own repaint, so the next one is never sent into a
    // view that has not processed the previous one (which is how this test used
    // to lose a keystroke under load and assert against a 1-line selection).
    await press('v') // start a visual selection at the cursor (line 1)
    await press('j') // extend down a block
    await press('j') // extend further
    await press('c') // comment on the selection

    const text = await waitFor(/comment on L1-\d/, 'the comment prompt')

    // The comment prompt cites a line range (L1-N), not a single line.
    expect(text).toMatch(/comment on L1-\d/)

    cleanup()
  })

  it('moves pane focus left with ← (doc → outline → notes)', async () => {
    const { cleanup, stdin, waitFor } = await renderView()

    // Default focus is the doc; left arrow steps doc → outline → notes.
    stdin.write('[D') // ← arrow
    expect(await waitFor('▸ Outline', 'focus to move to the outline')).toContain('▸ Outline')

    stdin.write('[D') // ← arrow again
    expect(await waitFor('▸ Notes', 'focus to move to the notes list')).toContain('▸ Notes')

    cleanup()
  })

  it('flips the notes list to a flat ranked Results pane on "/" filter', async () => {
    const { cleanup, stdin, waitFor } = await renderView()

    stdin.write('/') // open the inline filter
    await waitFor('⌕', 'the inline filter to open')
    stdin.write('cal') // matches "Calibration and Scoring"
    // The flat Results pane is the settled state; the negative assertion below
    // is only meaningful once it has painted.
    const text = await waitFor('Results', 'the flat ranked Results pane')

    // Header shows the live filter query; the left pane switches tree → Results.
    expect(text).toContain('⌕ cal')
    expect(text).toContain('Results')
    expect(text).toContain('Calibration and Scoring')
    // The non-matching note drops out of the flat results.
    expect(text).not.toMatch(/Results \(1\)[\s\S]*Bayesian Updating[\s\S]*Forecasting\/Knowledge\/Bayesian/)

    cleanup()
  })

  it('surfaces the sort column in the header on "o"', async () => {
    const { cleanup, stdin, waitFor } = await renderView()

    stdin.write('o') // cycle sort → name ascending
    expect(await waitFor('name ▲', 'the ascending sort header')).toContain('name ▲')

    stdin.write('O') // toggle direction → descending
    expect(await waitFor('name ▼', 'the descending sort header')).toContain('name ▼')

    cleanup()
  })

  it('opens the in-Obsidian chat modal on "a"', async () => {
    const { cleanup, stdin, waitFor } = await renderView()

    stdin.write('a')
    const text = await waitFor('Ask the desk', 'the in-Obsidian chat modal')

    expect(text).toContain('Ask the desk')
    expect(text).toContain('⏎ send')

    cleanup()
  })
})
