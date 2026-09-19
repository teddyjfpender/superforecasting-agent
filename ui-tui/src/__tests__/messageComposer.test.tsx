import { PassThrough } from 'node:stream'

import React, { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { MessageComposer, messageComposerRows } from '../components/messageComposer.js'
import { waitForText } from '../testing/settle.js'
import { DARK_THEME } from '../theme.js'

it('grows for wrapped and multiline text while reserving room for history', () => {
  expect(messageComposerRows('', 50, 20)).toBe(1)
  expect(messageComposerRows('one\ntwo', 50, 20)).toBe(2)
  expect(messageComposerRows('word '.repeat(300), 40, 13)).toBe(3)
  expect(messageComposerRows('word '.repeat(300), 80, 40)).toBe(6)
})
it.each([false, true])('keeps the framed editor and submit action visible (multiline=%s)', async multiline => {
  const { Box, render } = await import('@superforecasting/ink')
  const { stripAnsi } = await import('../lib/text.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: 60, rows: 20, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const send = vi.fn(),
    back = vi.fn()

  function Editor() {
    const [value, setValue] = useState('')

    return (
      <Box width={56}>
        <MessageComposer
          active
          busy={false}
          columns={52}
          inputRows={2}
          multiline={multiline}
          onBack={back}
          onChange={setValue}
          onSend={send}
          t={DARK_THEME}
          text={value}
        />
      </Box>
    )
  }

  const app = await render(<Editor />, {
    stdout: stdout,
    stdin: stdin,
    patchConsole: false,
    exitOnCtrlC: false
  })

  try {
    await waitForText(() => stripAnsi(output), multiline ? '[Ctrl+Enter send]' : '[Enter send]')
    expect(stripAnsi(output)).toContain('╰')
    stdin.write('hello')
    await waitForText(() => stripAnsi(output), 'hello')
    stdin.write(multiline ? '\x1b[13;5u' : '\r')
    await vi.waitFor(() => expect(send).toHaveBeenCalledWith('hello'))
    expect(back).not.toHaveBeenCalled()
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }
})
