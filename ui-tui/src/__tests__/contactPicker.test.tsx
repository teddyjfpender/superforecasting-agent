import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { waitForText } from '../testing/settle.js'

vi.mock('../lib/signalStore.js', () => ({
  resolveSignalConfig: () => null,
  loadSignalCache: () => ({}),
  saveSignalCache: () => true
}))
const roots: string[] = []
afterEach(() => {
  vi.unstubAllEnvs()
  roots.splice(0).forEach(p => rmSync(p, { recursive: true, force: true }))
})

it.each([
  [80, 24],
  [120, 40]
])('browses names, scopes and topic matches without leaking keys at %ix%i', async (cols, rows) => {
  vi.resetModules()
  const root = mkdtempSync(join(tmpdir(), 'contact-picker-'))
  roots.push(root)
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', root)
  const { $signalDirectory } = await import('../lib/signalDirectory.js')
  const { $chatState } = await import('../lib/messagingState.js')
  const { resetOverlayState } = await import('../app/overlayStore.js')
  resetOverlayState()
  $chatState.set({ ada: { category: 'Economics' }, 'group:desk': { pinned: true } })
  $signalDirectory.set({
    ada: { chatId: 'ada', name: 'Ada Lovelace', addedAt: 1 },
    'group:desk': { chatId: 'group:desk', name: 'Research desk', addedAt: 2 }
  })
  const { ContactPicker } = await import('../components/contactPicker.js')
  const { Box, render } = await import('@superforecasting/ink')
  const { DARK_THEME } = await import('../theme.js')
  const { stripAnsi } = await import('../lib/text.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const select = vi.fn(),
    cancel = vi.fn(),
    group = vi.fn()

  const app = await render(
    <Box height={rows} width={cols}>
      <ContactPicker cols={cols} onCancel={cancel} onNewGroup={group} onSelect={select} rows={rows} t={DARK_THEME} />
    </Box>,
    { stdout: stdout as never, stdin: stdin as never, debug: true, patchConsole: false, exitOnCtrlC: false }
  )

  try {
    await waitForText(() => stripAnsi(output), 'Ada Lovelace')
    expect(stripAnsi(output)).toContain('Esc back')
    stdin.write('macro')
    await waitForText(() => stripAnsi(output), '1 matches')
    stdin.write('\r')
    await vi.waitFor(() => expect(select).toHaveBeenCalledWith('ada'))
    // Group shortcut does not collide with the global Ctrl+G view chord.
    stdin.write('\x02')
    await vi.waitFor(() => expect(group).toHaveBeenCalledOnce())
    stdin.write('\x1b')
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce())
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }
})
