import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

import type { ObsidianNoteResponse, ObsidianStatusResponse } from '../gatewayTypes.js'

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
    import('@hermes/ink'),
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

  await tick(80)

  const read = () => normalize(stdout.text(), stripAnsi)
  const text = read()

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    read,
    stdin: stdin.stream,
    text
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
    const { cleanup, read, stdin } = await renderView()

    stdin.write('s')
    await tick(60)
    const text = read()

    expect(text).toContain('Search the vault')
    expect(text).toContain('Type to search')

    cleanup()
  })

  it('selects a multi-line range (v then move) and cites it as a range, not L1', async () => {
    const { cleanup, read, stdin } = await renderView()

    stdin.write('v') // start a visual selection at the cursor (line 1)
    await tick(20)
    stdin.write('j') // extend down a block
    await tick(20)
    stdin.write('j') // extend further
    await tick(20)
    stdin.write('c') // comment on the selection
    await tick(40)
    const text = read()

    // The comment prompt cites a line range (L1-N), not a single line.
    expect(text).toMatch(/comment on L1-\d/)

    cleanup()
  })

  it('moves pane focus left with ← (doc → outline → notes)', async () => {
    const { cleanup, read, stdin } = await renderView()

    // Default focus is the doc; left arrow steps doc → outline → notes.
    stdin.write('[D') // ← arrow
    await tick(20)
    expect(read()).toContain('▸ Outline')

    stdin.write('[D') // ← arrow again
    await tick(20)
    expect(read()).toContain('▸ Notes')

    cleanup()
  })

  it('opens the in-Obsidian chat modal on "a"', async () => {
    const { cleanup, read, stdin } = await renderView()

    stdin.write('a')
    await tick(60)
    const text = read()

    expect(text).toContain('Ask the desk')
    expect(text).toContain('⏎ send')

    cleanup()
  })
})
