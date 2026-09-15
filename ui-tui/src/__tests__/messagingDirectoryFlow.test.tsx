import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import type * as SignalClient from '../lib/signalClient.js'
import { waitForText } from '../testing/settle.js'

vi.mock('../lib/signalClient.js', async importOriginal => ({
  ...(await importOriginal<typeof SignalClient>()),
  checkHealth: async () => true,
  listContacts: async () => [{ id: '+15550000001', name: 'Ada Lovelace', aliases: ['Ada'] }],
  listGroups: async () => [],
  signalRpc: async () => ({ result: null, error: null }),
  openReceiveStream: () => () => {}
}))
it('refreshes names in the real messaging view, opens f search and enters a chat without sending', async () => {
  const root = mkdtempSync(join(tmpdir(), 'messaging-flow-'))
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', root)
  vi.stubEnv('SIGNAL_ACCOUNT', '+15550000999')
  const { MessagingView } = await import('../components/messagingView.js')
  const { stopSignalReceiver } = await import('../lib/signalLive.js')
  const { resetOverlayState } = await import('../app/overlayStore.js')
  resetOverlayState()
  const { Box, render } = await import('@superforecasting/ink')
  const { DARK_THEME } = await import('../theme.js')
  const { stripAnsi } = await import('../lib/text.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: 100, rows: 32, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const app = await render(
    <Box height={32} width={100}>
      <MessagingView onClose={() => {}} t={DARK_THEME} />
    </Box>,
    { stdout: stdout as never, stdin: stdin as never, debug: true, patchConsole: false, exitOnCtrlC: false }
  )

  try {
    await waitForText(() => stripAnsi(output), 'Ada Lovelace')
    stdin.write('f')
    await waitForText(() => stripAnsi(output), 'FIND CONTACT OR CHAT')
    stdin.write('ada')
    await waitForText(() => stripAnsi(output), 'Search › ada')
    output = ''
    stdin.write('\r')
    await waitForText(() => stripAnsi(output), 'Write a message')
    expect(stripAnsi(output)).not.toContain('FIND CONTACT OR CHAT')
  } finally {
    app.unmount()
    app.cleanup()
    stopSignalReceiver()
    stdout.destroy()
    stdin.destroy()
    vi.unstubAllEnvs()
    rmSync(root, { recursive: true, force: true })
  }
})
