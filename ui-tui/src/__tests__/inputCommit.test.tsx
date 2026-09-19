import { PassThrough } from 'node:stream'

import { render, Text } from '@superforecasting/ink'
import { useLayoutEffect } from 'react'
import { expect, it, vi } from 'vitest'

import StdinContext from '../../packages/forecast-ink/src/ink/components/StdinContext.js'
import { EventEmitter } from '../../packages/forecast-ink/src/ink/events/emitter.js'
import { InputEvent } from '../../packages/forecast-ink/src/ink/events/input-event.js'
import useInput from '../../packages/forecast-ink/src/ink/hooks/use-input.js'
import { INITIAL_STATE, parseMultipleKeypresses } from '../../packages/forecast-ink/src/ink/parse-keypress.js'

it('installs input handlers at commit, reads current state and retains propagation order after reactivation', async () => {
  const emitter = new EventEmitter()
  const hits: string[] = []
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })
  Object.assign(stdout, { columns: 80, rows: 24, isTTY: false })

  const context = {
    stdin: process.stdin,
    setRawMode: vi.fn(),
    isRawModeSupported: false,
    exitOnCtrlC: false,
    inputEmitter: emitter,
    querier: null
  }

  function Probe({ version, active }: { version: number; active: boolean }) {
    useInput(
      (_input, _key, event) => {
        hits.push(`first:${version}`)
        event.stopImmediatePropagation()
      },
      { isActive: active }
    )
    useInput(() => {
      hits.push(`second:${version}`)
    })
    // An event at the end of this layout commit must already see both newly
    // mounted listeners and their committed closures, without a passive tick.
    useLayoutEffect(() => {
      const [keys] = parseMultipleKeypresses(INITIAL_STATE, 'x')
      const key = keys[0]!

      if (key.kind !== 'key') {
        throw new Error('Expected a key event')
      }

      emitter.emit('input', new InputEvent(key))
    }, [version])

    return <Text>{version}</Text>
  }

  const view = (version: number, active: boolean) => (
    <StdinContext.Provider value={context}>
      <Probe active={active} version={version} />
    </StdinContext.Provider>
  )

  const app = await render(view(1, true), { stdout, stdin, debug: true, patchConsole: false, exitOnCtrlC: false })

  try {
    await vi.waitFor(() => expect(hits, output).toEqual(['first:1']))
    app.rerender(view(2, false))
    await vi.waitFor(() => expect(hits).toEqual(['first:1', 'second:2']))
    app.rerender(view(3, true))
    await vi.waitFor(() => expect(hits).toEqual(['first:1', 'second:2', 'first:3']))
  } finally {
    app.unmount()
    app.cleanup()
    stdout.destroy()
    stdin.destroy()
  }

  expect(emitter.listenerCount('input')).toBe(0)
})
