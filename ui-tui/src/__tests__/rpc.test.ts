import { describe, expect, it } from 'vitest'

import { asRpcResult, GatewayRpcError, isCommandHandoff, rpcErrorMessage } from '../lib/rpc.js'

describe('asRpcResult', () => {
  it('keeps plain object payloads', () => {
    expect(asRpcResult({ ok: true, value: 'x' })).toEqual({ ok: true, value: 'x' })
  })

  it('rejects missing or non-object payloads', () => {
    expect(asRpcResult(undefined)).toBeNull()
    expect(asRpcResult(null)).toBeNull()
    expect(asRpcResult('oops')).toBeNull()
    expect(asRpcResult(['bad'])).toBeNull()
  })
})

describe('rpcErrorMessage', () => {
  it('prefers Error messages', () => {
    expect(rpcErrorMessage(new Error('boom'))).toBe('boom')
  })

  it('falls back for unknown errors', () => {
    expect(rpcErrorMessage('broken')).toBe('broken')
    expect(rpcErrorMessage({ code: 500 })).toBe('request failed')
  })
})

describe('isCommandHandoff', () => {
  it('supports a native host without the legacy slash method', () => {
    expect(isCommandHandoff(new GatewayRpcError('method not found', -32601))).toBe(true)
  })

  it('accepts explicit non-execution metadata', () => {
    expect(isCommandHandoff(new GatewayRpcError('handoff', 4018, {
      dispatch: 'command.dispatch', execution_started: false
    }))).toBe(true)
  })

  it.each([null, [], {}, { dispatch: 'command.dispatch', execution_started: true }])(
    'does not use legacy text to override invalid explicit metadata: %j', data => {
      expect(isCommandHandoff(new GatewayRpcError('skill command: use command.dispatch', 4018, data))).toBe(false)
    }
  )

  it('accepts only the established legacy pre-execution handoff', () => {
    expect(isCommandHandoff(new GatewayRpcError('skill command: use command.dispatch', 4018))).toBe(true)
    expect(isCommandHandoff(new GatewayRpcError('skill command: use command.dispatch', 5030))).toBe(false)
    expect(isCommandHandoff(new Error('skill command: use command.dispatch'))).toBe(false)
  })
})
