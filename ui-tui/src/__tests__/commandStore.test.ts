import { beforeEach, describe, expect, it } from 'vitest'

import { $commands, applyCommandEvent, clearCommands, markCommandsCancelling } from '../app/commandStore.js'
import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import type { GatewayEvent } from '../gatewayTypes.js'

const event = (type: string, payload: Record<string, unknown>, session_id = 's1') =>
  ({ type, payload: { command_id: 'c1', ...payload }, session_id }) as GatewayEvent

beforeEach(() => {
  clearCommands()
  resetUiState()
})

describe('native command activity', () => {
  it('tracks sessions independently and waits for terminal acknowledgement after cancellation', () => {
    applyCommandEvent(event('command.started', { name: 'kanban' }))
    applyCommandEvent(event('command.started', { name: 'kanban' }, 's2'))
    markCommandsCancelling('s1', true)
    expect($commands.get().map(command => command.cancelling)).toEqual([true, false])
    applyCommandEvent(event('command.finished', { status: 'cancelled' }))
    expect($commands.get().map(command => command.sessionId)).toEqual(['s2'])
    applyCommandEvent(event('command.started', { name: 'kanban' }))
    expect($commands.get()).toHaveLength(1)
  })

  it('bounds output and rejects orphan output and invalid terminal status', () => {
    applyCommandEvent(event('command.output', { text: 'orphan' }))
    expect($commands.get()).toEqual([])
    applyCommandEvent(event('command.started', { name: 'kanban' }))
    applyCommandEvent(event('command.output', { text: 'x'.repeat(20_000) + 'tail' }))
    expect($commands.get()[0]?.output).toHaveLength(4096)
    expect($commands.get()[0]?.output.endsWith('tail')).toBe(true)
    applyCommandEvent(event('command.finished', { status: 'imaginary' }))
    expect($commands.get()).toHaveLength(1)
    clearCommands()
    expect($commands.get()).toEqual([])
  })

  it('consumes a terminal event after switching the displayed session', () => {
    const handler = createGatewayEventHandler({
      gateway: {},
      composer: {},
      session: {},
      submission: {},
      system: {},
      transcript: {},
      voice: {}
    } as any)

    patchUiState({ sid: 's1' })
    handler(event('command.started', { name: 'kanban' }))
    patchUiState({ sid: 's2' })
    handler(event('command.finished', { status: 'finished' }))
    expect($commands.get()).toEqual([])
  })
})
