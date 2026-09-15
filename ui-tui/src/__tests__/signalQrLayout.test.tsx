import { PassThrough } from 'node:stream'

import React from 'react'
import { expect, it, vi } from 'vitest'

import { waitForText } from '../testing/settle.js'

const fake = vi.hoisted(() => ({
  uri: 'sgnl://linkdevice?uuid=12345678-1234-1234-1234-123456789012&pub_key=' + 'a'.repeat(64),
  cancel: vi.fn()
}))

vi.mock('../lib/signalDaemon.js', () => ({
  findSignalCli: () => ({ found: true, path: '/fake/signal-cli', version: '1' }),
  findJava: () => ({ found: true, path: '/fake/java', version: '21' }),
  parseMajorVersion: () => 21,
  startDaemon: vi.fn()
}))
vi.mock('../lib/signalOnboard.js', () => ({
  runLink: (_name: string, callbacks: { onUri: (uri: string) => void }) => {
    callbacks.onUri(fake.uri)

    return { cancel: fake.cancel }
  },
  CAPTCHA_URL: '',
  brewInstall: vi.fn(),
  listAccounts: vi.fn(),
  registerNumber: vi.fn(),
  verifyNumber: vi.fn()
}))

it('keeps the link alive through resize and renders every QR row once it fits', async () => {
  const { Box, render } = await import('@superforecasting/ink')
  const { SignalSetupModal } = await import('../components/signalSetupModal.js')
  const { qrLines, signalQrLayout } = await import('../lib/qrRender.js')
  const { stripAnsi } = await import('../lib/text.js')
  const { DARK_THEME } = await import('../theme.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: 80, rows: 24, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const view = (cols: number, rows: number) => (
    <Box height={rows} width={cols}>
      <SignalSetupModal cols={cols} onCancel={() => {}} onConnected={() => {}} rows={rows} t={DARK_THEME} />
    </Box>
  )

  const app = await render(view(80, 24), {
    stdout: stdout as never,
    stdin: stdin as never,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false
  })

  try {
    await waitForText(() => stripAnsi(output), 'l link · n register')
    stdin.write('l')
    await waitForText(() => stripAnsi(output), 'Resize to at least')
    expect(output).not.toContain('▀')
    const lines = qrLines(fake.uri)
    const size = signalQrLayout(lines, 80, 24)
    output = ''
    Object.assign(stdout, { columns: size.minCols, rows: size.minRows })
    app.rerender(view(size.minCols, size.minRows))
    await waitForText(() => stripAnsi(output), 'Waiting for phone')

    const rendered = stripAnsi(output)
      .split('\n')
      .map(line => line.trim())

    for (const line of lines.filter(line => line.trim())) {
      expect(rendered.some(row => row.includes(line.trim()))).toBe(true)
    }

    expect(fake.cancel).not.toHaveBeenCalled()
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }
}, 15000)
