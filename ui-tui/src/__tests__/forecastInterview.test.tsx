import { PassThrough } from 'node:stream'

import { Box, render } from '@superforecasting/ink'
import { expect, it, vi } from 'vitest'

import { resetOverlayState } from '../app/overlayStore.js'
import { ForecastInterview } from '../components/forecastInterview.js'
import { stripAnsi } from '../lib/text.js'
import type { InterviewRecord } from '../protocol/generated.js'
import { RpcFixtures } from '../testing/rpcFixtures.js'
import { waitForText } from '../testing/settle.js'
import { DARK_THEME } from '../theme.js'

it.each([
  [80, 24],
  [120, 40],
  [60, 18]
])('resumes, saves explicit answers and retains retry identity at %sx%s', async (cols, rows) => {
  resetOverlayState()

  let record: InterviewRecord = {
    interview_id: 'draft',
    revision: 1,
    request_id: 'begin',
    actor: 'agent',
    digest: 'fixture',
    created_at: '2030-01-01T00:00:00Z',
    document: {
      schema_version: 1,
      generations: [],
      seed: null,
      evidence_refs: [],
      mode: 'create',
      question_id: null,
      baseline_forecast_id: null,
      context_digest: null,
      parent_interview: null,
      title: 'Example forecast',
      status: 'draft',
      answers: [],
      assumptions: [],
      scenarios: [],
      questions: [
        {
          id: 'title',
          section: 'define',
          prompt: 'What event?',
          rationale: 'Define an observable outcome.',
          kind: 'text',
          required: true,
          allow_custom: true,
          choices: [],
          assumption_ids: []
        },
        {
          id: 'belief',
          section: 'beliefs',
          prompt: 'Your probability?',
          rationale: 'Give a probability from 0 to 1.',
          kind: 'probability',
          required: false,
          allow_custom: true,
          choices: [],
          assumption_ids: []
        }
      ]
    }
  }

  let fail = true

  const fixture = new RpcFixtures()
    .handle('forecast.interview.list', () => ({ interviews: [record] }))
    .handle('forecast.interview.answer', params => {
      if (fail) {
        fail = false
        throw new Error('Connection lost; retry')
      }

      record = {
        ...record,
        revision: record.revision + 1,
        document: {
          ...record.document,
          answers: [
            ...record.document.answers,
            {
              question_id: params.question_id,
              value: params.value ?? null,
              status: params.status,
              note: '',
              custom_text: null,
              evidence_refs: [],
              actor: 'user'
            }
          ]
        }
      }

      return record
    })
    .handle('forecast.interview.preview', () => ({ spec: {}, issues: [], unanswered: [], committable: false }))

  const request = vi.spyOn(fixture, 'request')

  const stdout = new PassThrough()
  const stdin = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })
  const close = vi.fn()

  const app = await render(
    <Box height={rows} width={cols}>
      <ForecastInterview gw={fixture} onClose={close} t={DARK_THEME} />
    </Box>,
    { stdout, stdin, debug: true, patchConsole: false, exitOnCtrlC: false }
  )

  try {
    await waitForText(() => stripAnsi(output), 'What event?')
    expect(request).not.toHaveBeenCalledWith('forecast.interview.begin', expect.anything())
    stdin.write('Will it rain on Friday?')
    await waitForText(() => stripAnsi(output), 'Will it rain')
    stdin.write('\x1b[13;5u')
    await waitForText(() => stripAnsi(output), 'Connection lost')
    stdin.write('\x1b[13;5u')
    await waitForText(() => stripAnsi(output), 'Your probability?')
    const saves = request.mock.calls.filter(([method]) => method === 'forecast.interview.answer')
    expect(saves).toHaveLength(2)
    expect(saves[0][1]).toEqual(saves[1][1])
    expect(saves[0][1]).toMatchObject({ value: 'Will it rain on Friday?' })
    stdin.write('\x15') // Ctrl+U records Unknown; it must not become a numeric zero.
    await waitForText(() => stripAnsi(output), 'Review answers')
    const unknown = record.document.answers.at(-1)
    expect(unknown?.status).toBe('unknown')
    expect(unknown?.value).toBeNull()
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.commit')).toBe(false)
    stdin.write('\x1b')
    await vi.waitFor(() => expect(close).toHaveBeenCalledOnce())
  } finally {
    app.unmount()
    app.cleanup()
    stdin.destroy()
    stdout.destroy()
  }
})
