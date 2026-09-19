import { beforeEach, expect, it, vi } from 'vitest'

import { createSlashHandler } from '../app/createSlashHandler.js'
import { getGatewayLink, markLinkReconnecting } from '../app/gatewayLinkStore.js'
import type { SlashHandlerContext } from '../app/interfaces.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import type { CommandDispatchResponse } from '../protocol/generated.js'
import { RpcFixtures } from '../testing/rpcFixtures.js'
import type { Msg } from '../types.js'

function context(provider: RpcFixtures) {
  return {
    composer: {
      enqueue: vi.fn(), hasSelection: false, paste: vi.fn(), queueRef: { current: [] as string[] },
      selection: { copySelection: vi.fn(async () => '') }, setInput: vi.fn()
    },
    gateway: {
      gw: {
        request: provider.request.bind(provider), getLogTail: () => '',
        isRestartPending: () => true, reconnect: vi.fn()
      },
      rpc: provider.request.bind(provider)
    },
    local: {
      catalog: null, getHistoryItems: (): Msg[] => [], getLastUserMsg: () => '',
      maybeWarn: vi.fn(), setCatalog: vi.fn()
    },
    session: {
      closeSession: async () => null, die: vi.fn(), dieWithCode: vi.fn(),
      guardBusySessionSwitch: () => false, newSession: vi.fn(), resetVisibleHistory: vi.fn(),
      resumeById: vi.fn(), setSessionStartedAt: vi.fn()
    },
    slashFlightRef: { current: 0 },
    transcript: {
      page: vi.fn(), panel: vi.fn(), send: vi.fn(), setHistoryItems: vi.fn(), sys: vi.fn(),
      trimLastExchange: (items: Msg[]) => items
    },
    voice: { setVoiceEnabled: vi.fn(), setVoiceRecordKey: vi.fn() }
  } satisfies SlashHandlerContext
}

beforeEach(() => { resetUiState() })

it('uses only declared capabilities and rejects a late command result after session replacement', async () => {
  let finish: (result: CommandDispatchResponse) => void = () => {}
  const pending = new Promise<CommandDispatchResponse>(resolve => { finish = resolve })
  const provider = new RpcFixtures().handle('command.dispatch', () => pending)
  const ctx = context(provider)
  patchUiState({ sid: 'original' })
  createSlashHandler(ctx)('/external')
  patchUiState({ sid: 'replacement' })
  finish({ type: 'exec', output: 'Old session output' })
  await pending
  await Promise.resolve()
  expect(ctx.transcript.sys).not.toHaveBeenCalled()
  expect(ctx.transcript.page).not.toHaveBeenCalled()
})

it('reports an unregistered backend method as failure instead of a successful empty result', async () => {
  const ctx = context(new RpcFixtures())
  createSlashHandler(ctx)('/external')
  await vi.waitFor(() => expect(ctx.transcript.sys).toHaveBeenCalledWith(
    expect.stringContaining('Unregistered fixture RPC: command.dispatch')
  ))
  expect(ctx.transcript.send).not.toHaveBeenCalled()
})

it('requests reconnect through the host capability without constructing or killing a client', () => {
  const ctx = context(new RpcFixtures())
  markLinkReconnecting({ attempt: 1, detail: 'disconnected', max: 3, nextRetryMs: 1000, sid: 'original' })
  createSlashHandler(ctx)('/reconnect')
  expect(ctx.gateway.gw.reconnect).toHaveBeenCalledOnce()
  expect(getGatewayLink().phase).toBe('starting')
  expect(getGatewayLink().resumeSid).toBe('original')
})

it('bounds backend alias cycles without another request or outgoing message', async () => {
  const names: string[] = []

  const provider = new RpcFixtures().handle('command.dispatch', request => {
    names.push(request.name)

    return { type: 'alias', target: request.name === 'first' ? 'second' : 'first' }
  })

  const ctx = context(provider)
  const handler = createSlashHandler(ctx)
  handler('/first')
  await vi.waitFor(() => expect(ctx.transcript.sys).toHaveBeenCalledWith('error: command alias cycle: /first'))
  expect(names).toEqual(['first', 'second'])
  expect(ctx.transcript.send).not.toHaveBeenCalled()
  ctx.transcript.sys.mockClear()
  handler('/first')
  await vi.waitFor(() => expect(ctx.transcript.sys).toHaveBeenCalledWith('error: command alias cycle: /first'))
  expect(names).toEqual(['first', 'second', 'first', 'second'])
})

it('bounds acyclic backend alias chains too', async () => {
  let calls = 0
  const provider = new RpcFixtures().handle('command.dispatch', () => ({ type: 'alias', target: `step${++calls}` }))
  const ctx = context(provider)
  createSlashHandler(ctx)('/start')
  await vi.waitFor(() => expect(ctx.transcript.sys).toHaveBeenCalledWith('error: command alias limit exceeded: /step32'))
  expect(calls).toBe(32)
})

it('rejects a catalog alias cycle before contacting the backend', () => {
  const provider = new RpcFixtures()
  const request = vi.spyOn(provider, 'request')
  const ctx: SlashHandlerContext = context(provider)
  ctx.local.catalog = {
    canon: { '/first': '/second', '/second': '/first' }, categories: [], pairs: [], skillCount: 0, sub: {}
  }
  createSlashHandler(ctx)('/first')
  expect(ctx.transcript.sys).toHaveBeenCalledWith('error: command alias cycle: /first')
  expect(request).not.toHaveBeenCalled()
})
