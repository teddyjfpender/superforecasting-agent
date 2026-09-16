import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import type * as SignalClient from '../lib/signalClient.js'
import { waitForText } from '../testing/settle.js'

const transport = vi.hoisted(() => vi.fn())
vi.mock('../lib/signalClient.js', async importOriginal => ({
  ...(await importOriginal<typeof SignalClient>()),
  checkHealth: async () => true,
  sendSignalMessage: transport,
  listContacts: async () => [{ id: '+15550000001', name: 'Ada Lovelace', aliases: ['Ada'] }],
  listGroups: async () => [{ id: 'empty', name: 'Empty group', memberCount: 2 }],
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
    const { $signalDirectory } = await import('../lib/signalDirectory.js')
    await vi.waitFor(() => expect($signalDirectory.get()['+15550000001']?.name).toBe('Ada Lovelace'))
    await waitForText(() => stripAnsi(output), 'No conversations yet.')
    expect(stripAnsi(output)).not.toContain('Ada Lovelace')
    expect(stripAnsi(output)).not.toContain('Empty group')
    stdin.write('f')
    await waitForText(() => stripAnsi(output), 'FIND CONTACT OR CHAT')
    stdin.write('ada')
    await waitForText(() => stripAnsi(output), 'Search › ada')
    output = ''
    stdin.write('\r')
    await waitForText(() => stripAnsi(output), 'Write a message')
    expect(stripAnsi(output)).not.toContain('FIND CONTACT OR CHAT')
    expect(stripAnsi(output)).not.toContain('CHATS  (1)')
    output = ''
    stdin.write('\x1b[D')
    await waitForText(() => stripAnsi(output), 'No conversations yet.')
    stdin.write('f')
    await waitForText(() => stripAnsi(output), 'FIND CONTACT OR CHAT')
    stdin.write('ada')
    await waitForText(() => stripAnsi(output), 'Search › ada')
    output = ''
    stdin.write('\r')
    await waitForText(() => stripAnsi(output), 'Write a message')
    // Cursor navigation edits text; Left at the boundary returns to the rail.
    stdin.write('abc')
    const { $chatState } = await import('../lib/messagingState.js')
    await vi.waitFor(() => expect($chatState.get()['+15550000001']?.draft).toBe('abc'))
    output = ''
    stdin.write('\x1b[D')
    await new Promise(resolve => setTimeout(resolve, 60))
    expect(stripAnsi(output)).not.toContain('New / group')
    stdin.write('\x1b[D\x1b[D\x1b[D')
    await waitForText(() => stripAnsi(output), 'New / group')
    expect($chatState.get()['+15550000001']?.draft).toBe('abc')
    output = ''
    stdin.write('\x1b[C')
    await waitForText(() => stripAnsi(output), 'Shift+Enter newline')
    let finish!: (value: { error: null; timestamp: number }) => void
    transport.mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finish = resolve
        })
    )
    output = ''
    stdin.write('\r')
    await waitForText(() => stripAnsi(output), '◷')
    expect(stripAnsi(output)).not.toContain('sending…')
    output = ''
    finish({ error: null, timestamp: Date.now() })
    await waitForText(() => stripAnsi(output), 'abc ✓')
    await vi.waitFor(() => expect($chatState.get()['+15550000001']?.draft).toBe(''))
    output = ''
    stdin.write('\x1b[D')
    await waitForText(() => stripAnsi(output), 'New / group')
    output = ''
    stdin.write('\x1b[C')
    await waitForText(() => stripAnsi(output), 'Write a message')
    stdin.write('test failure')
    await vi.waitFor(() => expect($chatState.get()['+15550000001']?.draft).toBe('test failure'))
    transport.mockResolvedValueOnce({ error: 'offline', timestamp: 0 })
    stdin.write('\r')
    await waitForText(() => stripAnsi(output), 'Delivery unconfirmed')
    expect($chatState.get()['+15550000001']?.draft).toBe('test failure')
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
