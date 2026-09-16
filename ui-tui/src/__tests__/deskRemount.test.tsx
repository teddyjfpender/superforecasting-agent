import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import type { GatewayClient } from '../gatewayClient.js'
import { waitForText } from '../testing/settle.js'

it('real Markets and News remounts paint retained data without reacquiring feeds', async () => {
  const root = mkdtempSync(join(tmpdir(), 'desk-remount-'))
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', root)
  const { MarketsView } = await import('../components/marketsView.js')
  const { NewsView } = await import('../components/newsView.js')
  const { resetOverlayState } = await import('../app/overlayStore.js')
  const { Box, render } = await import('@superforecasting/ink')
  const { DARK_THEME } = await import('../theme.js')
  const { stripAnsi } = await import('../lib/text.js')
  resetOverlayState()
  const raw = JSON.parse(readFileSync(new URL('../../../forecasting/marketdata/catalog.json', import.meta.url), 'utf8'))
  // Catalog defaults are filled by Python in production.
  raw.series = raw.series.map((s: object) => ({ tags: [], line: null, ...s }))

  const request = vi.fn(async (method: string) => {
    if (method === 'market.catalog') {
      return {
        catalog: raw,
        catalog_revision: '1',
        configured_providers: ['ibge'],
        selection: {
          series_ids: ['ibge:1737/63'],
          categories: [],
          custom: [],
          watchlist: [],
          pm_saved: [],
          providers: ['ibge'],
          server_side: null,
          revision: '1',
          state: 'custom'
        }
      }
    }

    if (method === 'market.quotes') {
      return {
        quotes: [
          {
            provider: 'ibge',
            symbol: '1737/63',
            name: 'Brazil · IPCA monthly inflation',
            category: 'inflation',
            unit: '% monthly change',
            value: -0.32,
            asOf: Date.parse('2026-08-01'),
            retrieved_at: new Date().toISOString(),
            refresh_seconds: 21600,
            change: -0.39,
            changePct: null
          }
        ],
        statuses: []
      }
    }

    if (method === 'news.desk') {
      return {
        feeds: [{ url: 'https://example.com/rss', title: 'Example', category: 'Economics' }],
        starter: [],
        state: 'configured'
      }
    }

    if (method === 'news.feed') {
      return {
        xml: '<rss><channel><item><title>Retained inflation story</title><description>Inflation details</description></item></channel></rss>',
        url: 'https://example.com/rss'
      }
    }

    return {}
  })

  const gw = { request, on: vi.fn(), off: vi.fn() } as unknown as GatewayClient

  const stdout = new PassThrough(),
    stdin = new PassThrough()

  Object.assign(stdout, { columns: 110, rows: 32, isTTY: false })
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const market = (
    <Box height={32} width={110}>
      <MarketsView gw={gw} onClose={() => {}} t={DARK_THEME} />
    </Box>
  )

  const news = (
    <Box height={32} width={110}>
      <NewsView gw={gw} onClose={() => {}} t={DARK_THEME} />
    </Box>
  )

  const app = await render(market, {
    stdout: stdout as never,
    stdin: stdin as never,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false
  })

  try {
    await waitForText(() => stripAnsi(output), '-0.32')
    app.rerender(news)
    await waitForText(() => stripAnsi(output), 'Retained inflation story')
    output = ''
    app.rerender(market)
    await waitForText(() => stripAnsi(output), '-0.32')
    output = ''
    app.rerender(news)
    await waitForText(() => stripAnsi(output), 'Retained inflation story')
    expect(request.mock.calls.filter(([method]) => method === 'market.quotes')).toHaveLength(1)
    expect(request.mock.calls.filter(([method]) => method === 'news.feed')).toHaveLength(1)
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
    vi.unstubAllEnvs()
    rmSync(root, { recursive: true, force: true })
  }
})
