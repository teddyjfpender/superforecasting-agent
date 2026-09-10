import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

import type { ModelOptionsResponse } from '../gatewayTypes.js'
import { type Match, waitForQuiet, waitForSettled, waitForText } from '../testing/settle.js'

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

// A model.options payload with one reasoning-capable (codex) provider, one
// plain chat-completions provider that does NOT take an effort dial, and a
// MIXED xAI provider whose lineup pairs an effort-capable grok with a
// non-capable one (per-model gating must skip the dead step for the latter).
const options = (): ModelOptionsResponse => ({
  model: 'gpt-5.4',
  provider: 'openai-codex',
  providers: [
    {
      authenticated: true,
      is_current: true,
      models: ['gpt-5.4', 'gpt-5.4-mini'],
      name: 'OpenAI OAuth (ChatGPT)',
      reasoning_effort_models: ['gpt-5.4', 'gpt-5.4-mini'],
      reasoning_efforts: ['low', 'medium', 'high', 'xhigh'],
      slug: 'openai-codex',
      supports_reasoning_effort: true,
      total_models: 2
    },
    {
      authenticated: true,
      models: ['deepseek-chat'],
      name: 'DeepSeek',
      reasoning_effort_models: [],
      reasoning_efforts: [],
      slug: 'deepseek',
      supports_reasoning_effort: false,
      total_models: 1
    },
    {
      authenticated: true,
      models: ['grok-4', 'grok-3-mini'],
      name: 'xAI',
      // Only grok-3-mini accepts reasoning.effort; grok-4 does not.
      reasoning_effort_models: ['grok-3-mini'],
      reasoning_efforts: ['low', 'medium', 'high', 'xhigh'],
      slug: 'xai',
      supports_reasoning_effort: true,
      total_models: 2
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
    import('@superforecasting/ink'),
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

  const read = () => normalize(stdout.text(), stripAnsi)

  // model.options is async: a fixed `tick(80)` asserted against the
  // `loading models…` frame under load. Wait for the provider stage to render.
  await waitForSettled(read, 'Select provider', { label: 'the provider stage to render' })

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      // Wait for the repaint the key caused rather than a fixed 40ms, so a
      // staged picker never receives the next key before it has advanced.
      const before = read()

      stdin.stream.write(keys)

      try {
        await waitForText(read, value => value !== before, { label: 'the keypress repaint', timeout: 2000 })
      } catch {
        // Some keys only commit (onSelect) without repainting.
      }

      await waitForQuiet(read, { quietFor: 24, timeout: 1000 })
    },
    selected,
    text: () => read(),
    waitFor: (match: Match, label?: string) => waitForText(read, match, { label })
  }
}

describe('ModelPicker reasoning-effort step', () => {
  it('shows the effort step for a codex model and commits the chosen level', async () => {
    const m = await mountPicker(options())
    // Provider stage → openai-codex is highlighted (is_current). Enter → model.
    await m.press('\r')
    // Model stage → first model (gpt-5.4) highlighted. Enter → effort step.
    await m.press('\r')
    expect(await m.waitFor('Select reasoning effort (step 3/3)', 'the effort stage')).toContain(
      'Select reasoning effort (step 3/3)'
    )
    // Move from medium (preselected) up to high, then commit.
    await m.press(`${ESC}[B`) // medium → high
    await m.press('\r')
    expect(m.selected.length).toBe(1)
    expect(m.selected[0].value).toContain('gpt-5.4 --provider openai-codex')
    expect(m.selected[0].value).toContain('--global')
    expect(m.selected[0].effort).toBe('high')
    m.cleanup()
  })

  it('can toggle the picker back to a session-only model switch', async () => {
    const m = await mountPicker(options())
    await m.press('g')
    expect(await m.waitFor('persist: session', 'the session-only toggle')).toContain('persist: session')
    await m.press('\r')
    await m.press('\r')
    await m.press('\r')
    expect(m.selected[0].value).toContain('--tui-session')
    expect(m.selected[0].value).not.toContain('--global')
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

  // MINOR 1 — gating is per-MODEL, not per-provider.
  it('skips the effort step for a non-effort model inside an effort-capable provider', async () => {
    const m = await mountPicker(options())
    // Provider stage: codex(0) → deepseek(1) → xai(2).
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[B`)
    await m.press('\r')
    // Model stage: first model grok-4 is NOT effort-capable even though the
    // xAI provider is (grok-3-mini is). Enter commits immediately, no step.
    await m.press('\r')
    expect(m.text()).not.toContain('Select reasoning effort')
    expect(m.selected.length).toBe(1)
    expect(m.selected[0].value).toContain('grok-4 --provider xai')
    expect(m.selected[0].effort).toBeUndefined()
    m.cleanup()
  })

  it('shows the effort step for the effort-capable model in the same mixed lineup', async () => {
    const m = await mountPicker(options())
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[B`)
    await m.press('\r')
    // Model stage: move from grok-4 (0) to grok-3-mini (1), which IS capable.
    await m.press(`${ESC}[B`)
    await m.press('\r')
    expect(await m.waitFor('Select reasoning effort (step 3/3)', 'the effort stage')).toContain(
      'Select reasoning effort (step 3/3)'
    )
    expect(m.selected.length).toBe(0)
    m.cleanup()
  })

  // MINOR 2 — a "none" option keeps reasoning disabled across a model switch.
  it('offers a none option on the effort step', async () => {
    const m = await mountPicker(options())
    await m.press('\r')
    await m.press('\r')
    const text = m.text()
    expect(text).toContain('Select reasoning effort')
    expect(text).toContain('none')
    expect(text).toContain('disable reasoning')
    m.cleanup()
  })

  it('preselects none and commits keeping reasoning disabled when current=none', async () => {
    const payload = options()
    payload.reasoning_effort = 'none'
    const m = await mountPicker(payload)
    await m.press('\r')
    await m.press('\r')
    expect(m.text()).toContain('Select reasoning effort')
    // "none" is preselected (current=none); Enter without moving commits it.
    await m.press('\r')
    expect(m.selected.length).toBe(1)
    expect(m.selected[0].value).toContain('gpt-5.4 --provider openai-codex')
    expect(m.selected[0].effort).toBe('none')
    m.cleanup()
  })
})
