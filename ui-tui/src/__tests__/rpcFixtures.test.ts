import { describe, expect, it } from 'vitest'

import { RpcFixtures } from '../testing/rpcFixtures.js'

describe('typed RPC fixtures', () => {
  it('binds request parameters and response to the registered method', async () => {
    const fixture = new RpcFixtures().handle('forecast.interview.list', params => {
      expect(params.question_id).toBe('fq_example')

      return { interviews: [] }
    })

    await expect(fixture.request('forecast.interview.list', { question_id: 'fq_example' })).resolves.toEqual({ interviews: [] })
  })

  it('does not turn an unregistered method or handler failure into success', async () => {
    const fixture = new RpcFixtures()
    await expect(fixture.request('forecast.interview.list')).rejects.toThrow('Unregistered fixture RPC')
    fixture.handle('forecast.interview.list', () => { throw new Error('provider unavailable') })
    await expect(fixture.request('forecast.interview.list')).rejects.toThrow('provider unavailable')
  })
})

// Compiled by tsconfig.tests.json. Each directive must consume a real error;
// removing the contract or weakening it to any makes these assertions fail.
function rejectedContracts() {
  const fixture = new RpcFixtures()
  // @ts-expect-error Method identities are closed by the generated catalog.
  fixture.handle('made.up.method', () => ({}))
  // @ts-expect-error An interview list is not a number.
  fixture.handle('forecast.interview.list', () => ({ interviews: 3 }))
  // @ts-expect-error A numeric question ID must not reach the handler.
  void fixture.request('forecast.interview.list', { question_id: 2 })
}

void rejectedContracts
