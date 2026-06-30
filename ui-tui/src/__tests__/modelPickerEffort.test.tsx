import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

import type { ModelOptionsResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

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

// A model.options payload with one reasoning-capable (codex) provider and one
// plain chat-completions provider that does NOT take an effort dial.
const options = (): ModelOptionsResponse => ({
  model: 'gpt-5.4',
  provider: 'openai-codex',
  providers: [
    {
      authenticated: true,
      is_current: true,
      models: ['gpt-5.4', 'gpt-5.4-mini'],
      name: 'OpenAI OAuth (ChatGPT)',
      reasoning_efforts: ['low', 'medium', 'high', 'xhigh'],
      slug: 'openai-codex',
      supports_reasoning_effort: true,
      total_models: 2
    },
    {
      authenticated: true,
      models: ['deepseek-chat'],
      name: 'DeepSeek',
      reasoning_efforts: [],
      slug: 'deepseek',
      supports_reasoning_effort: false,
      total_models: 1
    }
  ],
  reasoning_effort: 'medium'
})

const fakeGw = (payload: ModelOptionsResponse) =>
  ({
    request: (method: string) => {
      if (method === 'model.options') {
        return Promise.resolve(payload)
      }
      return Promise.resolve({})
    }
  }) as never

const mountPicker = async (payload: ModelOptionsResponse) => {
  const selected: { effort?: string; value?: string }[] = []

  const [{ Box, render }, { ModelPicker }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/modelPicker.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 40)
  const stdin = writeStream(120, 40, true)

  const instance = render(
    React.createElement(
      Box,
      { flexDirection: 'column', height: 40, width: 120 },
      React.createElement(ModelPicker, {
        gw: fakeGw(payload),
        onCancel: () => undefined,
        onSelect: (value: string, effort?: string) => {
          selected.push({ effort, value })
        },
        sessionId: 'sess-1',
        t: DARK_THEME
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(80)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(40)
    },
    selected,
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('ModelPicker reasoning-effort step', () => {
  it('shows the effort step for a codex model and commits the chosen level', async () => {
    const m = await mountPicker(options())
    // Provider stage → openai-codex is highlighted (is_current). Enter → model.
    await m.press('\r')
    // Model stage → first model (gpt-5.4) highlighted. Enter → effort step.
    await m.press('\r')
    expect(m.text()).toContain('Select reasoning effort (step 3/3)')
    // Move from medium (preselected) up to high, then commit.
    await m.press(`${ESC}[B`) // medium → high
    await m.press('\r')
    expect(m.selected.length).toBe(1)
    expect(m.selected[0].value).toContain('gpt-5.4 --provider openai-codex')
    expect(m.selected[0].effort).toBe('high')
    m.cleanup()
  })

  it('preselects the current effort and lists low/medium/high/xhigh', async () => {
    const m = await mountPicker(options())
    await m.press('\r')
    await m.press('\r')
    const text = m.text()
    expect(text).toContain('low')
    expect(text).toContain('medium')
    expect(text).toContain('high')
    expect(text).toContain('xhigh')
    // Enter without moving commits the preselected current effort (medium).
    await m.press('\r')
    expect(m.selected[0].effort).toBe('medium')
    m.cleanup()
  })

  it('skips the effort step for a non-reasoning model and commits on model select', async () => {
    const m = await mountPicker(options())
    // Provider stage → move to deepseek (second provider), Enter → model.
    await m.press(`${ESC}[B`)
    await m.press('\r')
    // Model stage → only deepseek-chat. Enter commits immediately, no effort step.
    await m.press('\r')
    expect(m.text()).not.toContain('Select reasoning effort')
    expect(m.selected.length).toBe(1)
    expect(m.selected[0].value).toContain('deepseek-chat --provider deepseek')
    expect(m.selected[0].effort).toBeUndefined()
    m.cleanup()
  })
})
