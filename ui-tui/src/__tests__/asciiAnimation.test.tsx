import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BernardAnimation } from '../content/bernardAnimation.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

// Two tiny frames so we can prove the timer swaps them.
const FIXTURE: BernardAnimation = {
  fps: 20,
  frames: [
    [[{ c: 0, t: 'AAA' }]],
    [[{ c: 1, t: 'BBB' }]]
  ],
  height: 1,
  palette: ['#c778ff', '#1afabc'],
  width: 3
}

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isRaw?: boolean
    isTTY: boolean
    ref?: () => PassThrough
    rows: number
    setRawMode?: (mode: boolean) => void
    unref?: () => PassThrough
  }
  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (mode: boolean) => {
      stream.isRaw = mode
    },
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const renderAnim = async (props: { active?: boolean } = {}) => {
  const [{ render }, { AsciiAnimation }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/asciiAnimation.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(40, 10)
  const stdin = writeStream(40, 10, true)
  const instance = render(
    React.createElement(AsciiAnimation, { animation: FIXTURE, ...props }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  const read = () =>
    stripAnsi(stdout.text().replace(OSC_RE, '').replace(CSI_RE, '')).trim()

  return { instance, read }
}

afterEach(() => {
  delete process.env.FORECAST_TUI_DESK_ANIMATION
})

describe('AsciiAnimation', () => {
  it('renders the first frame', async () => {
    const a = await renderAnim()
    await tick(40)
    expect(a.read()).toContain('AAA')
    a.instance.unmount?.()
  })

  it('advances to the next frame on the timer', async () => {
    const a = await renderAnim()
    await tick(40)
    expect(a.read()).toContain('AAA')
    // fps 20 → ~50ms/frame; after ~70ms it should have swapped to BBB.
    await tick(90)
    expect(a.read()).toContain('BBB')
    a.instance.unmount?.()
  })

  it('does not advance when inactive', async () => {
    const a = await renderAnim({ active: false })
    await tick(120)
    expect(a.read()).toContain('AAA')
    expect(a.read()).not.toContain('BBB')
    a.instance.unmount?.()
  })
})
