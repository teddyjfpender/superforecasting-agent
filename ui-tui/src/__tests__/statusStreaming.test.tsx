import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

// STREAMING LIVE-TAIL PIN.
//
// The heartbeat fixes the STATUS row; this guards the OTHER liveness path — the
// transcript live-tail. The real StreamingAssistant subscribes to the turn store,
// so response deltas must repaint the tail on their own (independent of AppLayout
// re-renders). This proves the render-isolation arc did not freeze that path too.

process.env.FORECAST_TUI_INLINE = '1'

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const writeStream = (columns: number, rows: number) => {
  const stream = new PassThrough() as any
  let output = ''
  Object.assign(stream, { columns, isTTY: false, rows })
  stream.on('data', (c: Buffer) => (output += c.toString()))

  return { clear: () => (output = ''), stream, text: () => output }
}

describe('streaming assistant: the live tail keeps updating on deltas', () => {
  it('repaints as response text streams in — not frozen by isolation', async () => {
    const { render } = await import('@superforecasting/ink')
    const { StreamingAssistant } = await import('../components/streamingAssistant.js')
    const { patchTurnState, resetTurnState } = await import('../app/turnStore.js')
    const { resetUiState } = await import('../app/uiStore.js')

    resetUiState()
    resetTurnState()

    const out = writeStream(80, 8)

    const inst: any = await render(
      React.createElement(StreamingAssistant, {
        cols: 80,
        compact: false,
        detailsMode: 'collapsed',
        detailsModeCommandOverride: false,
        progress: { showProgressArea: false },
        sections: {}
      } as never),
      { exitOnCtrlC: false, patchConsole: false, stdout: out.stream as never }
    )

    await tick(60)

    // First delta lands.
    patchTurnState({ streaming: 'The answer begins' })
    await tick(60)
    expect(out.text()).toContain('The answer begins')

    // A later delta must extend the tail without a fresh mount.
    out.clear()
    patchTurnState({ streaming: 'The answer begins and then continues onward' })
    await tick(60)
    expect(out.text()).toContain('continues onward')

    inst.unmount?.()
  })
})
