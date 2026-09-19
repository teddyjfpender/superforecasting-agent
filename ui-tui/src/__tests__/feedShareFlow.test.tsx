import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import { decodeFeedMessage, shareQuote } from '../lib/feedShare.js'
import type * as SignalClient from '../lib/signalClient.js'
import { waitForText } from '../testing/settle.js'

const transport = vi.hoisted(() => vi.fn().mockResolvedValue({ error: null, timestamp: 123 }))
vi.mock('../lib/signalClient.js', async importOriginal => ({
  ...(await importOriginal<typeof SignalClient>()),
  checkHealth: async () => true,
  sendSignalMessage: transport,
  listContacts: async () => [{ id: '+15550000001', name: 'Ada', aliases: [] }],
  listGroups: async () => [],
  openReceiveStream: () => () => {}
}))

it.each([
  [100, 30],
  [80, 24]
])(
  'previews and sends a feed at %ix%i with visible shortcuts',
  async (cols, rows) => {
    transport.mockClear()
    const root = mkdtempSync(join(tmpdir(), 'feed-share-flow-'))
    vi.stubEnv('SUPERFORECASTING_AGENT_HOME', root)
    vi.stubEnv('SIGNAL_ACCOUNT', '+15550000999')
    const { QuickMessage } = await import('../components/quickMessage.js')
    const { MessagingView } = await import('../components/messagingView.js')
    const { stopSignalReceiver } = await import('../lib/signalLive.js')
    const { $quickMessage } = await import('../lib/messagingState.js')
    const { resetOverlayState } = await import('../app/overlayStore.js')
    const { Box, render } = await import('@superforecasting/ink')
    const { DARK_THEME } = await import('../theme.js')
    const { stripAnsi } = await import('../lib/text.js')
    resetOverlayState()

    const fixture = JSON.parse(
      readFileSync(new URL('../../../tests/fixtures/feed_share/v1.json', import.meta.url), 'utf8')
    )

    // Exercise the quote-to-share boundary too: Yahoo returns timestamped closes,
    // unlike the calendar-date wire fixture used by economics feeds.
    const feed = shareQuote({
      provider: 'yahoo',
      symbol: '^GSPC',
      name: 'S&P 500',
      category: 'indices',
      unit: 'index points',
      asOf: Date.parse('2026-09-16T14:00:00Z'),
      value: -0.32,
      change: null,
      changePct: null,
      dated_history: fixture.feeds[0].points.map((point: { end: string; value: number | null }) => ({
        period_start: `${point.end}T14:00:00+00:00`,
        period_end: `${point.end}T14:00:00+00:00`,
        value: point.value,
        published_at: null,
        status: null
      }))
    })

    expect(feed).not.toBeNull()
    $quickMessage.set({ item: { title: 'S&P 500', text: 'Daily closes', feed } })

    const stdout = new PassThrough(),
      stdin = new PassThrough()

    Object.assign(stdout, { columns: cols, rows, isTTY: false })
    Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
    let output = ''
    stdout.on('data', chunk => {
      output += String(chunk)
    })

    const app = await render(
      <Box height={rows} width={cols}>
        <QuickMessage cols={cols} rows={rows} t={DARK_THEME} />
      </Box>,
      { stdout: stdout, stdin: stdin, patchConsole: false, exitOnCtrlC: false }
    )

    try {
      await waitForText(() => stripAnsi(output), 'Ada')
      stdin.write('\r')
      await waitForText(() => stripAnsi(output), '[Shift+Tab chart/horizon]')
      expect(stripAnsi(output)).toContain('[Ctrl+Enter send]')
      expect(stripAnsi(output)).toContain('zero baseline')
      expect(stripAnsi(output)).toContain('█')
      stdin.write('\x1b[Z')
      await waitForText(() => stripAnsi(output), 'Enter compose')
      stdin.write('\x1b[C')
      await waitForText(() => stripAnsi(output), 'line-chart')
      stdin.write('\x1b[A')
      await waitForText(() => stripAnsi(output), 'latest 12 observations')
      output = ''
      stdin.write('\r')
      await waitForText(() => stripAnsi(output), 'Tab recipient')
      stdin.write('\x1b[13;5u')
      await vi.waitFor(() => expect(transport).toHaveBeenCalledTimes(1))
      const shared = decodeFeedMessage(transport.mock.calls[0]![2])
      expect(shared.share?.presentation).toBe('line-chart')
      expect(shared.share?.feeds[0]?.points).toHaveLength(3)
      expect($quickMessage.get()).toBeNull()
      app.rerender(
        <Box height={rows} width={cols}>
          <MessagingView onClose={() => {}} t={DARK_THEME} />
        </Box>
      )
      await waitForText(() => stripAnsi(output), 'Shared snapshot')
      expect(stripAnsi(output)).toContain('-0.32')
      expect(stripAnsi(output)).not.toContain('```sfa-feed')
    } finally {
      stopSignalReceiver()
      app.unmount()
      app.cleanup()
      stdout.destroy()
      stdin.destroy()
      vi.unstubAllEnvs()
      rmSync(root, { recursive: true, force: true })
    }
  },
  15000
)
