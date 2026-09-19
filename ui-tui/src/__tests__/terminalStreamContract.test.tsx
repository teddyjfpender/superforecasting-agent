import { PassThrough } from 'node:stream'

import { render, Text } from '@superforecasting/ink'
import { expect, it } from 'vitest'

import { waitForText } from '../testing/settle.js'

it('renders to borrowed streams without requiring socket or raw-mode capabilities', async () => {
  const stdin = new PassThrough()
  const stdout = new PassThrough()
  let output = ''
  stdout.on('data', chunk => { output += String(chunk) })

  const instance = await render(<Text>Borrowed output</Text>, {
    stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false
  })

  try {
    await waitForText(() => output, 'Borrowed output')
    instance.unmount()
    instance.unmount()
    await instance.waitUntilExit()
    expect(stdin.destroyed).toBe(false)
    expect(stdout.destroyed).toBe(false)
  } finally {
    instance.cleanup()
    stdin.destroy()
    stdout.destroy()
  }
})

it('preserves the original exit error for late observers', async () => {
  const { renderSync } = await import('../../packages/forecast-ink/src/ink/root.js')
  const stdin = new PassThrough()
  const stdout = new PassThrough()
  stdout.resume()

  const instance = renderSync(<Text>Failure</Text>, {
    stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false
  })

  const failure = new Error('Original failure')

  try {
    instance.unmount(failure)
    instance.unmount(new Error('Duplicate shutdown'))
    await expect(instance.waitUntilExit()).rejects.toBe(failure)
    await expect(instance.waitUntilExit()).rejects.toBe(failure)
  } finally {
    instance.cleanup()
    stdin.destroy()
    stdout.destroy()
  }
})

it('does not deregister a replacement root when an old handle is cleaned up', async () => {
  const { forceRedraw, renderSync } = await import('../../packages/forecast-ink/src/ink/root.js')
  const stdin = new PassThrough()
  const stdout = new PassThrough()
  stdout.resume()
  const options = { stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false }
  const old = renderSync(<Text>Old root</Text>, options)
  old.unmount()
  const replacement = renderSync(<Text>Replacement</Text>, options)

  try {
    old.cleanup()
    old.unmount()
    expect(forceRedraw(stdout)).toBe(true)
    replacement.unmount()
    await replacement.waitUntilExit()
    expect(forceRedraw(stdout)).toBe(false)
  } finally {
    replacement.cleanup()
    stdin.destroy()
    stdout.destroy()
  }
})
