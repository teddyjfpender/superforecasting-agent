import { PassThrough } from 'stream'

import React from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import { selectNavView } from '../app/navRoutes.js'
import { $overlayState, resetOverlayState } from '../app/overlayStore.js'
import { AGENTS_CHIP_SHORTCUT, HomeStatusBar } from '../components/homeLanding.js'
import { stripAnsi } from '../lib/text.js'
import { fromSkin } from '../theme.js'

const ESC = String.fromCharCode(27)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')

const theme = fromSkin({}, {}, '', '', '', '', undefined)

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & { columns: number; isTTY: boolean; rows: number }
  let output = ''

  Object.assign(stream, {
    columns,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: () => undefined,
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

const renderBar = async (props: Partial<React.ComponentProps<typeof HomeStatusBar>>) => {
  const { renderSync } = await import('@hermes/ink')
  const stdout = writeStream(140, 8)
  const stdin = writeStream(140, 8, true)
  const stderr = writeStream(140, 8)

  const instance = renderSync(
    React.createElement(HomeStatusBar, {
      cols: 140,
      cwdLabel: '~/x',
      deskStatus: '2 forecasts · 1 to review · 1 alert',
      model: 'local/forecast-model',
      status: 'ready',
      statusColor: 'green',
      t: theme,
      ...props
    }),
    {
      patchConsole: false,
      stderr: stderr.stream as never,
      stdin: stdin.stream as never,
      stdout: stdout.stream as never
    }
  )

  instance.unmount()
  instance.cleanup()

  return stripAnsi(stdout.text().replace(CSI_RE, ''))
}

describe('HomeStatusBar agents chip', () => {
  beforeEach(() => {
    resetOverlayState()
  })

  it('renders the "✦ N agents running · <label>" chip with its keyboard hint when count > 0', async () => {
    const out = await renderBar({
      agents: { count: 2, headline: '2 agents running · reforecast · 5 questions' },
      onOpenAgents: () => undefined
    })

    expect(out).toContain('✦')
    expect(out).toContain('2 agents running · reforecast · 5 questions')
    // The Agents-view keyboard seam is shown dim so the heuristic is inspectable.
    expect(out).toContain(AGENTS_CHIP_SHORTCUT)
    expect(AGENTS_CHIP_SHORTCUT).toBe('Ctrl+G a')
    // The three-item core is still present alongside the chip.
    expect(out.replace(/\s+/g, '')).toContain('ready·1toreview·forecastmodel')
  })

  it('is byte-identical at rest — count 0 renders no chip and matches agents=undefined', async () => {
    const atRest = await renderBar({ agents: { count: 0, headline: '' } })
    const undefinedAgents = await renderBar({ agents: undefined })

    // No chip glyph, no keyboard hint at rest.
    expect(atRest).not.toContain('✦')
    expect(atRest).not.toContain(AGENTS_CHIP_SHORTCUT)
    // Just the slim three-item bar.
    expect(atRest.replace(/\s+/g, '')).toContain('ready·1toreview·forecastmodel')
    // A count-0 summary is indistinguishable from no summary at all.
    expect(atRest).toBe(undefinedAgents)
  })

  it('the chip / shortcut both open the Agents overlay via the shared selectNavView seam', () => {
    expect($overlayState.get().agents).toBe(false)

    // onOpenAgents (the chip click) and the Ctrl+G a chord both route through this.
    selectNavView('agents')

    expect($overlayState.get().agents).toBe(true)
  })
})
