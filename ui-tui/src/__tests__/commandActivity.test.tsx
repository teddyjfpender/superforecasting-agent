import { PassThrough } from 'stream'

import React from 'react'
import { expect, it } from 'vitest'

import { applyCommandEvent, clearCommands, markCommandsCancelling } from '../app/commandStore.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import { CommandActivity } from '../components/commandActivity.js'

it('renders live output and waits for confirmed cancellation at narrow terminal width', async () => {
  const { render } = await import('@superforecasting/ink')
  const output = new PassThrough() as any
  Object.assign(output, { columns: 60, rows: 8, isTTY: false })
  let text = ''
  output.on('data', (chunk: Buffer) => {
    text += chunk.toString()
  })
  const tick = () => new Promise(resolve => setTimeout(resolve, 60))
  clearCommands()
  resetUiState()
  patchUiState({ sid: 's1' })
  const instance = await render(<CommandActivity />, { stdout: output, exitOnCtrlC: false, patchConsole: false })

  try {
    applyCommandEvent({
      type: 'command.started',
      session_id: 's1',
      payload: { command_id: 'c1', request_id: 'r1', name: 'kanban' }
    })
    applyCommandEvent({
      type: 'command.output',
      session_id: 's1',
      payload: { command_id: 'c1', stream: 'stdout', text: 'Watching changes…' }
    })
    await tick()
    expect(text).toContain('Running /kanban')
    expect(text).toContain('Ctrl+C to cancel')
    expect(text).toContain('Watching changes…')
    text = ''
    markCommandsCancelling('s1', true)
    await tick()
    expect(text).toContain('Cancelling /kanban')
    text = ''
    applyCommandEvent({
      type: 'command.finished',
      session_id: 's1',
      payload: { command_id: 'c1', status: 'cancelled' }
    })
    await tick()
    expect(text).not.toContain('Running /kanban')
    expect(text).not.toContain('Cancelling /kanban')
  } finally {
    instance.unmount()
    clearCommands()
  }
})
