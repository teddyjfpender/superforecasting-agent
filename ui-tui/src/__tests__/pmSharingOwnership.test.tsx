import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import { type PMHookGateway, type PMSelectionData, usePmSelectionData } from '../lib/usePmMarkets.js'
import type { PMListItem, PMOutcomeDTO } from '../protocol/generated.js'

it('hides old history immediately and ignores late replies after outcome selection changes', async () => {
  const { render } = await import('@superforecasting/ink')
  const pending = new Map<string, (value: unknown) => void>()

  const gw: PMHookGateway = {
    request: (async (method: string, params: Record<string, unknown>) => {
      if (method === 'pm.history') {
        return new Promise(resolve => pending.set(String(params.market_id), resolve))
      }

      return {}
    }) as PMHookGateway['request']
  }

  let latest: PMSelectionData | undefined
  const item = { event: { venue: 'kalshi', event_id: 'event', markets: [] } } as unknown as PMListItem

  function Probe({ id }: { id: string }) {
    latest = usePmSelectionData(gw, true, item, { market_id: id } as PMOutcomeDTO, '1w')

    return null
  }

  const stdout = new PassThrough(),
    stdin = new PassThrough()

  const app = await render(<Probe id="A" />, {
    stdout: stdout as never,
    stdin: stdin as never,
    patchConsole: false,
    exitOnCtrlC: false
  })

  try {
    await vi.waitFor(() => expect(pending.has('A')).toBe(true))
    pending.get('A')!({ points: [{ ts: 1, p: 0.2 }] })
    await vi.waitFor(() => expect(latest?.history[0]?.p).toBe(0.2))
    app.rerender(<Probe id="B" />)
    await vi.waitFor(() => expect(pending.has('B')).toBe(true))
    expect(latest?.history).toEqual([])
    app.rerender(<Probe id="C" />)
    await vi.waitFor(() => expect(pending.has('C')).toBe(true))
    pending.get('B')!({ points: [{ ts: 2, p: 0.9 }] })
    pending.get('C')!({ points: [{ ts: 3, p: 0.4 }] })
    await vi.waitFor(() => expect(latest?.history).toEqual([{ ts: 3, p: 0.4 }]))
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }
})
