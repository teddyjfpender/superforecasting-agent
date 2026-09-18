import { PassThrough } from 'node:stream'

import { Box, render } from '@superforecasting/ink'
import { expect, it, vi } from 'vitest'

import { resetOverlayState } from '../app/overlayStore.js'
import { ForecastInterview } from '../components/forecastInterview.js'
import { stripAnsi } from '../lib/text.js'
import type { InterviewQuestion, InterviewRecord } from '../protocol/generated.js'
import { waitForText } from '../testing/settle.js'
import { DARK_THEME } from '../theme.js'

function fixture(): InterviewRecord {
  return {
    interview_id: 'draft',
    revision: 1,
    request_id: 'begin',
    actor: 'agent',
    digest: 'fixture',
    created_at: '2030-01-01T00:00:00Z',
    document: {
      schema_version: 1,
      seed: null,
      evidence_refs: [],
      generations: [],
      mode: 'create',
      question_id: null,
      baseline_forecast_id: null,
      title: 'Example forecast',
      status: 'draft',
      answers: [],
      scenarios: [],
      assumptions: [
        {
          id: 'health',
          statement: 'Candidate remains healthy',
          actor: 'user',
          probability: null,
          uncertainty: 'mixed',
          evidence_refs: [],
          rationale: ''
        }
      ],
      questions: [
        {
          id: 'title',
          section: 'define',
          prompt: 'What event?',
          rationale: 'Name the outcome.',
          kind: 'text',
          required: true,
          allow_custom: true,
          choices: [],
          assumption_ids: []
        }
      ]
    }
  }
}

async function screen(request: (method: string, params: any) => Promise<any>, cols = 80, rows = 24) {
  resetOverlayState()
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const app = await render(
    <Box height={rows} width={cols}>
      <ForecastInterview gw={{ request } as never} onClose={() => {}} t={DARK_THEME} />
    </Box>,
    { stdout, stdin, debug: true, patchConsole: false, exitOnCtrlC: false }
  )

  return {
    press: (keys: string) => {
      output = ''
      stdin.write(keys)
    },
    text: () => stripAnsi(output),
    wait: (text: string) => waitForText(() => stripAnsi(output), text),
    clear: () => {
      output = ''
    },
    close: () => {
      app.unmount()
      app.cleanup()
      stdin.destroy()
      stdout.destroy()
    }
  }
}

it.each([
  [80, 24],
  [60, 18],
  [120, 40]
])('offers budgeted generation with retry identity and cancellation at %s×%s', async (cols, rows) => {
  const record = fixture()
  let job: any = null
  let fail = true

  const request = vi.fn(async (method: string, params: any) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.generation_status') {
      return { found: job !== null, job }
    }

    if (method === 'forecast.interview.generate') {
      if (fail) {
        fail = false
        throw new Error('Lost start response; retry')
      }

      job = {
        job_id: 'job_interview',
        type: 'forecast_interview',
        status: 'running',
        spec: params,
        cancel_requested: false
      }

      return { job_id: job.job_id }
    }

    if (method === 'jobs.cancel') {
      job = { ...job, status: 'cancelled', cancel_requested: true }

      return { found: true, cancelled: true, job_id: job.job_id }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request, cols, rows)

  try {
    await ui.wait('What event?')
    ui.press('\x07')
    await ui.wait('Questions: up to 8')
    ui.press('\x1b[C')
    await ui.wait('Questions: up to 12')

    for (let at = 0; at < 5; at++) {
      ui.press('\x1b[B')
      await new Promise(resolve => setTimeout(resolve, 15))
    }

    await ui.wait('Generate follow-ups')
    ui.press('\r')
    await ui.wait('Lost start response')
    ui.press('\r')
    await ui.wait('Last job: running')
    const starts = request.mock.calls.filter(([method]) => method === 'forecast.interview.generate')
    expect(starts).toHaveLength(2)
    expect(starts[0][1]).toEqual(starts[1][1])
    expect(starts[0][1].options).toMatchObject({ max_questions: 12, max_tokens: 4000, timeout_seconds: 90 })
    ui.press('\x18')
    await ui.wait('Last job: cancelled')
    expect(request).toHaveBeenCalledWith('jobs.cancel', { job_id: 'job_interview' })
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.answer')).toBe(false)
  } finally {
    ui.close()
  }
})

it('restores a finished job and only opens its questions after explicit review', async () => {
  const record = fixture()

  const question: InterviewQuestion = {
    id: 'crux_followup',
    section: 'challenge',
    prompt: 'What would change your mind?',
    rationale: 'Seek counterevidence.',
    kind: 'text',
    required: false,
    allow_custom: true,
    choices: [],
    assumption_ids: []
  }

  const next = {
    ...record,
    revision: 2,
    document: { ...record.document, questions: [...record.document.questions, question] }
  }

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.generation_status') {
      return { found: true, job: { job_id: 'job_old', status: 'done', cancel_requested: false } }
    }

    if (method === 'forecast.interview.read') {
      return next
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('What event?')
    ui.press('\x07')
    await ui.wait('Last job: done')
    expect(request).not.toHaveBeenCalledWith('forecast.interview.read', expect.anything())
    ui.press('\x12')
    await ui.wait('What would change your mind?')
    expect(request).toHaveBeenCalledWith('forecast.interview.generation_status', { interview_id: 'draft' })
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.generate')).toBe(false)
  } finally {
    ui.close()
  }
})

it.each(['single', 'multiple'] as const)('saves %s custom answers without inventing choice identifiers', async kind => {
  let record = fixture()
  record.document.questions = [
    {
      ...record.document.questions[0]!,
      id: 'factors',
      kind,
      prompt: 'Which factor?',
      required: false,
      choices: [
        { id: 'health', label: 'Health' },
        { id: 'economy', label: 'Economy' }
      ]
    }
  ]

  const request = vi.fn(async (method: string, params: any) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.answer') {
      record = {
        ...record,
        revision: 2,
        document: { ...record.document, answers: [{ ...params, actor: 'user', evidence_refs: [] }] }
      }

      return record
    }

    if (method === 'forecast.interview.preview') {
      return { spec: {}, issues: [], unanswered: [], committable: false }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('Which factor?')

    if (kind === 'multiple') {
      ui.press(' ')
      await ui.wait('[x] Health')
    }

    ui.press('\x1b[B')
    await ui.wait(kind === 'multiple' ? '› [ ] Economy' : '› Economy')
    ui.press('\x1b[B')
    await ui.wait('› Other')
    ui.press('\r')
    await ui.wait('Save custom answer')
    ui.press('Court composition')
    await ui.wait('Court composition')
    ui.press('\x1b[13;5u')
    await ui.wait('Review answers')
    const answer = record.document.answers[0]!
    expect(answer.custom_text).toBe('Court composition')
    expect(answer.value).toEqual(kind === 'multiple' ? ['health'] : null)
  } finally {
    ui.close()
  }
})

it.each(['conditional', 'ablation'] as const)('saves %s selections with distinct semantics', async kind => {
  const record = fixture()

  const request = vi.fn(async (method: string, params: any) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.scenario.save') {
      return { ...record, revision: 2, document: { ...record.document, scenarios: [params.scenario] } }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request, 60, 18)

  try {
    await ui.wait('What event?')
    ui.press('\x0f')
    await ui.wait('New conditional scenario')

    if (kind === 'ablation') {
      ui.press('\x1b[B')
      await ui.wait('› New factor ablation')
    }

    ui.press('\r')
    await ui.wait(kind === 'conditional' ? '[free]' : '[include]')
    ui.press(kind === 'conditional' ? 'f' : ' ')
    await ui.wait(kind === 'conditional' ? '[false]' : '[exclude]')
    ui.press('\x1b[13;5u')
    await vi.waitFor(() =>
      expect(request.mock.calls.some(([method]) => method === 'forecast.interview.scenario.save')).toBe(true)
    )
    const scenario = request.mock.calls.find(([method]) => method === 'forecast.interview.scenario.save')![1].scenario
    expect(scenario.kind).toBe(kind)
    expect(scenario.conditions).toEqual(kind === 'conditional' ? { health: false } : {})
    expect(scenario.excluded_assumption_ids).toEqual(kind === 'ablation' ? ['health'] : [])
  } finally {
    ui.close()
  }
})

it('shows paused approval status and restores cancellation without starting another call', async () => {
  const record = fixture()
  let job = { job_id: 'job_approval', status: 'awaiting_approval', cancel_requested: false }

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.generation_status') {
      return { found: true, job }
    }

    if (method === 'jobs.cancel') {
      job = { ...job, status: 'cancelled', cancel_requested: true }

      return { found: true, cancelled: true, job_id: job.job_id }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('What event?')
    ui.press('\x07')
    await ui.wait('Paused by your spend policy')
    ui.press('\x18')
    await ui.wait('Last job: cancelled')
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.generate')).toBe(false)
  } finally {
    ui.close()
  }
})

it('requires confirmation before removing a saved scenario', async () => {
  const record = fixture()
  record.document.scenarios = [
    {
      id: 'saved',
      name: 'Healthy case',
      actor: 'user',
      kind: 'conditional',
      conditions: { health: true },
      excluded_assumption_ids: []
    }
  ]

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.scenario.delete') {
      return { ...record, revision: 2, document: { ...record.document, scenarios: [] } }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('What event?')
    ui.press('\x0f')
    await ui.wait('New conditional scenario')
    ui.press('\x1b[B')
    await ui.wait('› New factor ablation')
    ui.press('\x1b[B')
    await ui.wait('› Healthy case')
    ui.press('\x04')
    await ui.wait('Delete “Healthy case”?')
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.scenario.delete')).toBe(false)
    ui.press('\r')
    await vi.waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        'forecast.interview.scenario.delete',
        expect.objectContaining({ scenario_id: 'saved', expected_revision: 1 })
      )
    )
  } finally {
    ui.close()
  }
})

it('allows typing a provider override without the modal swallowing editor keys', async () => {
  const record = fixture()

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.generation_status') {
      return { found: false, job: null }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('What event?')
    ui.press('\x07')
    await ui.wait('Questions: up to 8')

    for (const label of ['Output budget', 'Deadline', 'Provider']) {
      ui.press('\x1b[B')
      await ui.wait(`› ${label}`)
    }

    ui.press('\r')
    await ui.wait('provider identifier')
    ui.press('anthropic')
    await ui.wait('anthropic')
    ui.press('\r')
    await ui.wait('Provider: anthropic')
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.generate')).toBe(false)
  } finally {
    ui.close()
  }
})

it('supports naming a scenario and inspecting the full assumption before saving', async () => {
  const record = fixture()
  record.document.assumptions[0]!.rationale = 'Review medical disclosures; do not infer health from unrelated evidence.'

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request)

  try {
    await ui.wait('What event?')
    ui.press('\x0f')
    await ui.wait('New conditional scenario')
    ui.press('\r')
    await ui.wait('[free]')
    ui.press('\r')
    await ui.wait('ASSUMPTION DETAILS')
    await ui.wait('Review medical disclosures')
    ui.press('\x1b')
    await ui.wait('[free]')
    ui.press('n')
    await ui.wait('[Enter Set name]')
    // Append to the existing name; the name editor must receive ordinary keys.
    ui.press(' test')
    await ui.wait('Conditional scenario 1 test')
    ui.press('\r')
    await ui.wait('Conditional scenario 1 test · [n Rename]')
    expect(request.mock.calls.some(([method]) => method === 'forecast.interview.scenario.save')).toBe(false)
  } finally {
    ui.close()
  }
})

it.each([
  [60, 18],
  [100, 32]
])('opens budgeted scenario comparison and restores cancellation at %s×%s', async (cols, rows) => {
  const record = fixture()
  record.document.scenarios = [
    {
      id: 'healthy',
      name: 'Healthy candidate',
      kind: 'conditional',
      actor: 'user',
      conditions: { health: true },
      excluded_assumption_ids: []
    }
  ]
  let job: any = null
  let receipt: string | null = null

  const request = vi.fn(async (method: string, params: any) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.evaluation_status') {
      return { found: !!job, job, request_id: receipt, report: null, stale: false }
    }

    if (method === 'forecast.interview.evaluate') {
      receipt = params.request_id
      job = { job_id: 'evaluation', status: 'running', done_count: 0, total: 2, cancel_requested: false }

      return { job_id: 'evaluation' }
    }

    if (method === 'jobs.cancel') {
      job = { ...job, status: 'cancelled', cancel_requested: true }

      return {}
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request, cols, rows)

  try {
    await ui.wait('What event?')
    ui.press('\x05')
    await ui.wait('EVALUATE SCENARIOS')
    await ui.wait('Healthy candidate')
    expect(ui.text()).toContain('8,000 output tokens')

    for (let index = 0; index < 5; index++) {
      ui.press('\x1b[B')
    }

    await ui.wait('Run comparison')
    ui.press('\r')
    await ui.wait('running')
    const start = request.mock.calls.find(([method]) => method === 'forecast.interview.evaluate')
    expect(start?.[1].options.scenario_ids).toEqual(['healthy'])
    expect(start?.[1].options.repetitions).toBe(1)
    ui.press('\x18')
    await ui.wait('cancelled')
    expect(request.mock.calls.some(([method]) => method === 'jobs.cancel')).toBe(true)
  } finally {
    ui.close()
  }
})

it('keeps historical comparison results closed until requested and uses frozen scenario labels', async () => {
  const record = fixture()

  const report = {
    scenarios: [
      {
        id: 'healthy',
        name: 'Original health scenario',
        kind: 'conditional',
        conditions: { health: true },
        excluded_assumption_ids: []
      }
    ],
    assumptions: record.document.assumptions,
    comparisons: [
      {
        variant_id: 'healthy',
        kind: 'conditional',
        repetitions: 1,
        dimensions: { probability: { mean: 0.7, paired_delta: 0.2, model_dispersion: null } }
      }
    ],
    results: [
      {
        variant_id: 'healthy',
        repetition: 0,
        response_model: 'controlled',
        estimate: {
          outcome_type: 'binary',
          rationale: 'Frozen analysis text',
          evidence_refs: [],
          unresolved_questions: ['Check the source'],
          units: null
        }
      }
    ],
    limitation: 'Model dispersion is not calibration.'
  }

  const request = vi.fn(async (method: string) => {
    if (method === 'forecast.interview.list') {
      return { interviews: [record] }
    }

    if (method === 'forecast.interview.evaluation_status') {
      return { found: true, job: { status: 'done', done_count: 2, total: 2 }, report, stale: true }
    }

    throw new Error(`Unexpected ${method}`)
  })

  const ui = await screen(request, 100, 32)

  try {
    await ui.wait('What event?')
    ui.press('\x05')
    await ui.wait('done')
    expect(ui.text()).not.toContain('Frozen analysis text')
    ui.press('\x12')
    await ui.wait('SCENARIO COMPARISON')
    await ui.wait('Original health scenario')
    expect(ui.text()).toContain('Historical result')
    expect(ui.text()).toContain('Candidate remains healthy: true')
    expect(ui.text()).toContain('dispersion not measured')
    expect(ui.text()).toContain('70.0%')
    expect(ui.text()).toContain('+20.0 pp')
    expect(ui.text()).toContain('Frozen analysis text')
  } finally {
    ui.close()
  }
})
