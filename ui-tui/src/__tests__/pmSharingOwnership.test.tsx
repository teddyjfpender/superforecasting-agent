import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import { type PMHookGateway, type PMSelectionData, usePmSelectionData } from '../lib/usePmMarkets.js'
import type { PmBookResponse, PmHistoryResponse, PMListItem, PMOutcomeDTO } from '../protocol/generated.js'
import { RpcFixtures } from '../testing/rpcFixtures.js'

it('hides old history immediately and ignores late replies after outcome selection changes', async () => {
  const { render } = await import('@superforecasting/ink')
  const pending = new Map<string, (value: PmHistoryResponse) => void>()
  const books = new Map<string, (value: PmBookResponse) => void>()

  const item: PMListItem = {
    event: {
      venue: 'kalshi',
      event_id: 'event',
      markets: [],
      category: null,
      close_time: null,
      is_binary: true,
      mutually_exclusive: true,
      slug: null,
      title: 'Fixture event',
      url: null,
      volume: null
    },
    distribution: {
      venue: 'kalshi',
      event_id: 'event',
      binary: true,
      close_time: null,
      headline: { close_time: null, n: 0, top_label: null, top_prob: null, total_volume: 0 },
      normalized: true,
      notes: [],
      outcomes: [],
      overround: 0,
      title: 'Fixture event',
      total_volume: 0,
      url: null
    }
  }

  const rpc = new RpcFixtures()
    .handle('pm.detail', () => item)
    .handle('pm.history', params => new Promise(resolve => pending.set(params.market_id, resolve)))
    .handle('pm.book', params => new Promise(resolve => books.set(params.market_id, resolve)))

  const gw: PMHookGateway = { request: rpc.request.bind(rpc) }

  const outcome = (market_id: string): PMOutcomeDTO => ({
    market_id,
    label: market_id,
    liquid: true,
    prob: 0.5,
    raw_prob: 0.5,
    volume: null,
    yes_ask: null,
    yes_bid: null
  })

  const book = (market_id: string): PmBookResponse => ({
    book: {
      venue: 'kalshi',
      market_id,
      bids: [],
      asks: [],
      best_ask: null,
      best_bid: null,
      mid: null,
      tick_size: null,
      timestamp: null
    }
  })

  let latest: PMSelectionData | undefined

  function Probe({ id }: { id: string }) {
    latest = usePmSelectionData(gw, true, item, outcome(id), '1w')

    return null
  }

  const stdout = new PassThrough(),
    stdin = new PassThrough()

  const app = await render(<Probe id="A" />, {
    stdout: stdout,
    stdin: stdin,
    patchConsole: false,
    exitOnCtrlC: false
  })

  try {
    await vi.waitFor(() => expect(pending.has('A')).toBe(true))
    books.get('A')!(book('A'))
    pending.get('A')!({ count: 1, points: [{ ts: 1, p: 0.2 }] })
    await vi.waitFor(() => expect(latest?.history[0]?.p).toBe(0.2))
    expect(latest?.book?.market_id).toBe('A')
    app.rerender(<Probe id="B" />)
    await vi.waitFor(() => expect(pending.has('B')).toBe(true))
    expect(latest?.history).toEqual([])
    expect(latest?.book).toBeNull()
    app.rerender(<Probe id="C" />)
    await vi.waitFor(() => expect(pending.has('C')).toBe(true))
    books.get('C')!(book('C'))
    books.get('B')!(book('B'))
    pending.get('B')!({ count: 1, points: [{ ts: 2, p: 0.9 }] })
    pending.get('C')!({ count: 1, points: [{ ts: 3, p: 0.4 }] })
    await vi.waitFor(() => expect(latest?.history).toEqual([{ ts: 3, p: 0.4 }]))
    expect(latest?.book?.market_id).toBe('C')
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }
})
