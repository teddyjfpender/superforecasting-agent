import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createSlashHandler } from '../app/createSlashHandler.js'
import { getOverlayState, resetOverlayState } from '../app/overlayStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import { TUI_SESSION_MODEL_FLAG } from '../domain/slash.js'

describe('createSlashHandler', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
  })

  it('opens the resume picker locally', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/resume')).toBe(true)
    expect(getOverlayState().picker).toBe(true)
  })

  it('handles /redraw locally without slash worker fallback', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/redraw')).toBe(true)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('ui redrawn')
  })

  it('handles /heuristic locally as the forecast-native maxim command', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/heuristic daily')).toBe(true)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith(expect.stringMatching(/^(P|CAL) /))
  })

  it('keeps /fortune as a compatibility alias for forecast maxims', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/fortune daily')).toBe(true)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith(expect.stringMatching(/^(P|CAL) /))
  })

  it('handles /style locally while preserving the personality backend key', async () => {
    patchUiState({ sid: 'sid-abc' })
    const rpc = vi.fn(() => Promise.resolve({ value: 'quant' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/style quant')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('config.set', { key: 'personality', session_id: 'sid-abc', value: 'quant' })
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('style: quant')
    })
  })

  it('exits locally for /quit', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/quit')).toBe(true)
    expect(ctx.session.die).toHaveBeenCalledTimes(1)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('handles /update locally and exits with code 42 via dieWithCode', () => {
    vi.useFakeTimers()
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/update')).toBe(true)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('exiting TUI to run update...')

    // Advance past the 100ms setTimeout
    vi.advanceTimersByTime(150)
    expect(ctx.session.dieWithCode).toHaveBeenCalledWith(42)

    vi.useRealTimers()
  })

  it('routes /status to live forecast session.status instead of slash worker', async () => {
    patchUiState({ sid: 'sid-abc' })
    const rpc = vi.fn(() => Promise.resolve({ output: 'Superforecasting Agent TUI Status' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/status')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('session.status', { session_id: 'sid-abc' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(ctx.transcript.page).toHaveBeenCalledWith('Superforecasting Agent TUI Status', 'Forecast Desk Status')
    })
  })

  it('routes bare /forecast to the native forecast dashboard RPC', async () => {
    const rpc = vi.fn((method: string) => {
      if (method === 'forecast.dashboard') {
        return Promise.resolve({
          output: 'ACTIVE FORECASTS',
          summary: {
            active_count: 1,
            open_alert_count: 0,
            product: 'Superforecasting Agent',
            questions: [
              {
                close_time: '2026-09-30T00:00:00Z',
                baseline_count: 1,
                confidence: 0.61,
                delta: -0.04,
                evidence_count: 3,
                id: 'fq_default001',
                open_alert_count: 0,
                open_assumption_count: 1,
                probability: 0.21,
                as_of: '2026-08-01T00:00:00Z',
                stale_assumption_count: 0,
                title: 'Will company Y default?'
              }
            ]
          }
        })
      }

      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/forecast')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 20 })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(getUiState().forecastDeskStatus).toBe('desk 1 active / asm 1/0')
      expect(getUiState().forecastDeskRailSections).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ title: 'Book' }),
          expect.objectContaining({
            rows: expect.arrayContaining([
              [
                'default0 P=0.210 Δ=-0.040',
                'active  as-of 2026-08-01  close 2026-09-30  conf 0.61  Will company Y default?',
                '/forecast show fq_default001'
              ]
            ]),
            title: 'Watchlist'
          })
        ])
      )
      expect(ctx.transcript.panel).toHaveBeenCalledWith(
        'Forecast Desk',
        expect.arrayContaining([
          expect.objectContaining({ title: 'Desk' }),
          expect.objectContaining({
            rows: [
              [
                'default0  P=0.210  Δ=-0.040',
                'as-of 2026-08-01  close 2026-09-30  conf 0.61  ev 3  base 1  refs 0/0  asm 1/0  active  Will company Y default?',
                '/forecast show fq_default001'
              ]
            ],
            title: 'Active Forecasts'
          })
        ])
      )
    })
  })

  it('routes numeric /forecast args to the dashboard limit', async () => {
    const rpc = vi.fn(() => Promise.resolve({ output: 'ACTIVE FORECASTS' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/forecast 5')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 5 })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('renders /questions as a numbered forecast summary without requiring ids', async () => {
    const rpc = vi.fn((method: string) => {
      if (method === 'forecast.dashboard') {
        return Promise.resolve({
          summary: {
            active_count: 1,
            open_alert_count: 0,
            product: 'Superforecasting Agent',
            questions: [
              {
                as_of: '2026-05-24T00:00:00Z',
                close_time: '2026-06-30T00:00:00Z',
                confidence: 0.62,
                delta: 0.08,
                evidence_count: 4,
                id: 'fq_inflation001',
                open_alert_count: 0,
                probability: 0.61,
                title: 'Will the CPI release exceed consensus?'
              }
            ],
            review_queue_count: 0
          }
        })
      }

      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/questions')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 20 })
    await vi.waitFor(() => {
      expect(ctx.transcript.panel).toHaveBeenCalledWith(
        'Forecast Book',
        expect.arrayContaining([
          expect.objectContaining({
            rows: expect.arrayContaining([
              [
                '1. P=0.610 Δ=+0.080',
                expect.stringContaining('Will the CPI release exceed consensus?'),
                '/questions 1'
              ]
            ]),
            title: 'Forecast Questions'
          }),
          expect.objectContaining({
            rows: [['/questions 1', 'open full details for Will the CPI release exceed consensus?']],
            title: 'Drill Down'
          })
        ])
      )
    })
  })

  it('opens a forecast from /questions by numbered row', async () => {
    const rpc = vi.fn((method: string, params: Record<string, unknown>) => {
      if (method === 'forecast.dashboard') {
        return Promise.resolve({
          summary: {
            active_count: 2,
            open_alert_count: 0,
            product: 'Superforecasting Agent',
            questions: [
              { id: 'fq_first', probability: 0.4, title: 'First forecast' },
              { id: 'fq_second', probability: 0.6, title: 'Second forecast' }
            ],
            review_queue_count: 0
          }
        })
      }
      if (method === 'forecast.command') {
        return Promise.resolve({ code: 0, output: `opened ${params.arg}` })
      }

      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/questions 2')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 20 })
    await vi.waitFor(() => {
      expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'show fq_second' })
      expect(ctx.transcript.sys).toHaveBeenCalledWith('opened show fq_second')
    })
  })

  it('keeps /book as a forecast-question shortcut alias', async () => {
    const rpc = vi.fn(() =>
      Promise.resolve({
        summary: {
          active_count: 0,
          open_alert_count: 0,
          product: 'Superforecasting Agent',
          questions: [],
          review_queue_count: 0
        }
      })
    )
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/book')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 20 })
  })

  it('routes /forecast lifecycle subcommands to the forecast command RPC', async () => {
    const rpc = vi.fn((method: string) => {
      if (method === 'forecast.command') {
        return Promise.resolve({ code: 0, output: 'created forecast question fq_123' })
      }
      if (method === 'forecast.dashboard') {
        return Promise.resolve({
          summary: {
            active_count: 2,
            open_alert_count: 1,
            product: 'Superforecasting Agent',
            questions: [],
            review_queue_count: 1
          }
        })
      }

      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/forecast new "Will X happen?" --resolution-criteria "Resolved by source"')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'new "Will X happen?" --resolution-criteria "Resolved by source"'
    })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('created forecast question fq_123')
      expect(rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 8 })
      expect(getUiState().forecastDeskStatus).toBe('desk 2 active / 1 alert / 1 review')
    })
  })

  it('routes forecast-native review shortcuts to the forecast command RPC', async () => {
    const rpc = vi.fn((method: string) => {
      if (method === 'forecast.command') {
        return Promise.resolve({ code: 0, output: 'No forecasts need review.' })
      }

      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/review')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'review --stale' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('No forecasts need review.')
    })
  })

  it('routes forecast lifecycle shortcuts to the forecast command RPC', () => {
    const rpc = vi.fn(() => Promise.resolve({ code: 0, output: 'ok' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })
    const handler = createSlashHandler(ctx)

    expect(handler('/new-forecast "Will X happen?" --resolution-criteria "Resolved by source"')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'new "Will X happen?" --resolution-criteria "Resolved by source"'
    })
    expect(handler('/ingest https://example.com/question')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'ingest https://example.com/question' })
    expect(handler('/evidence add fq_123 "new source"')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'evidence add fq_123 "new source"' })
    expect(handler('/research fq_123 https://example.com/source')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'research fq_123 https://example.com/source' })
    expect(
      handler('/base-rate fq_123 --name similar-events --inclusion-criteria "similar events" --base-rate 0.42')
    ).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'base-rate fq_123 --name similar-events --inclusion-criteria "similar events" --base-rate 0.42'
    })
    expect(handler('/model-run fq_123 --type bayesian_update')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'model fq_123 --type bayesian_update' })
    expect(handler('/forecast-model fq_123 --type time_series')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'model fq_123 --type time_series' })
    expect(handler('/trend-model fq_123 --series-json \'[[0,10],[1,12]]\' --target-x 2')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: "model fq_123 --series-json '[[0,10],[1,12]]' --target-x 2 --type trend_projection"
    })
    expect(handler('/update-forecast fq_123 --probability 0.62 --rationale "new evidence"')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'update fq_123 --probability 0.62 --rationale "new evidence"'
    })
    expect(handler('/resolve fq_123 --outcome yes --confirmed')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'resolve fq_123 --outcome yes --confirmed' })
    expect(handler('/score fq_123')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'score fq_123' })
    expect(handler('/postmortem fq_123 --lesson "discount noisy signals"')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'postmortem fq_123 --lesson "discount noisy signals"' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('routes forecast-native analytics shortcuts with args', async () => {
    const rpc = vi.fn(() => Promise.resolve({ code: 0, output: 'count: 12' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/calibration')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'calibration --by-origin' })
    expect(createSlashHandler(ctx)('/calibration --domain macro')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'calibration --domain macro' })
    expect(createSlashHandler(ctx)('/performance --last 3')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'performance --last 3' })
    expect(createSlashHandler(ctx)('/readiness --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'readiness --json' })
    expect(createSlashHandler(ctx)('/doctor --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'doctor --json' })
    expect(createSlashHandler(ctx)('/pilot-report --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'pilot-report --json' })
    expect(createSlashHandler(ctx)('/pilot')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'pilot-report' })
    expect(createSlashHandler(ctx)('/pilot-cohort cohort.csv --dry-run')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'pilot-cohort cohort.csv --dry-run' })
    expect(createSlashHandler(ctx)('/pilot-bundle --include-export')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'pilot-bundle --include-export' })
    expect(createSlashHandler(ctx)('/export-packet all --format json --output .pilot/tester-export.json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'export all --format json --output .pilot/tester-export.json'
    })
    expect(createSlashHandler(ctx)('/packet-export fq_123 --format markdown')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'export fq_123 --format markdown'
    })
    expect(createSlashHandler(ctx)('/import-packet tester-a-export.json --conflict skip')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'import packet tester-a-export.json --conflict skip'
    })
    expect(createSlashHandler(ctx)('/packet-import tester-b-export.json --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'import packet tester-b-export.json --json'
    })
    expect(createSlashHandler(ctx)('/pilot-aggregate tester-a.json tester-b.json --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'pilot-aggregate tester-a.json tester-b.json --json'
    })
    expect(createSlashHandler(ctx)('/lessons --active')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'lesson list --active' })
    expect(createSlashHandler(ctx)('/backtest')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'backtest --benchmarks' })
    expect(createSlashHandler(ctx)('/backtest --list')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'backtest --list' })
    expect(createSlashHandler(ctx)('/sources')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'sources' })
    expect(createSlashHandler(ctx)('/sources --json')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'sources --json' })
    expect(createSlashHandler(ctx)('/adapters')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'sources' })
    expect(createSlashHandler(ctx)('/schedule')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'schedule list' })
    expect(createSlashHandler(ctx)('/schedule run --auto-score')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', { arg: 'schedule run --auto-score' })
    expect(createSlashHandler(ctx)('/autopilot enable fq_123 --source bls:CUUR0000SA0 --cadence 1d')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('forecast.command', {
      arg: 'autopilot enable fq_123 --source bls:CUUR0000SA0 --cadence 1d'
    })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('keeps typed /model switches session-scoped by default', async () => {
    patchUiState({ sid: 'sid-abc' })

    const ctx = buildCtx({
      gateway: {
        ...buildGateway(),
        rpc: vi.fn(() => Promise.resolve({ value: 'x-model' }))
      }
    })

    expect(createSlashHandler(ctx)('/model x-model')).toBe(true)
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'model',
      session_id: 'sid-abc',
      value: 'x-model'
    })
  })

  it('honors TUI picker session scope without adding --global', async () => {
    patchUiState({ sid: 'sid-abc' })

    const ctx = buildCtx({
      gateway: {
        ...buildGateway(),
        rpc: vi.fn(() => Promise.resolve({ value: 'anthropic/claude-sonnet-4.6' }))
      }
    })

    expect(
      createSlashHandler(ctx)(`/model anthropic/claude-sonnet-4.6 --provider openrouter ${TUI_SESSION_MODEL_FLAG}`)
    ).toBe(true)
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'model',
      session_id: 'sid-abc',
      value: 'anthropic/claude-sonnet-4.6 --provider openrouter'
    })
  })

  it('does not duplicate --global for explicit persistent model switches', () => {
    patchUiState({ sid: 'sid-abc' })
    const ctx = buildCtx()

    createSlashHandler(ctx)('/model x-model --global')
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'model',
      session_id: 'sid-abc',
      value: 'x-model --global'
    })
  })

  it('applies /reasoning hide to the thinking section immediately', async () => {
    patchUiState({ sections: { thinking: 'expanded' }, showReasoning: true, sid: 'sid-abc' })
    const ctx = buildCtx({
      gateway: {
        ...buildGateway(),
        rpc: vi.fn(() => Promise.resolve({ value: 'hide' }))
      }
    })

    expect(createSlashHandler(ctx)('/reasoning hide')).toBe(true)

    await vi.waitFor(() => {
      expect(getUiState().showReasoning).toBe(false)
      expect(getUiState().sections.thinking).toBe('hidden')
    })
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'reasoning',
      session_id: 'sid-abc',
      value: 'hide'
    })
  })

  it('applies /reasoning show to the thinking section immediately', async () => {
    patchUiState({ sections: { thinking: 'hidden' }, showReasoning: false, sid: 'sid-abc' })
    const ctx = buildCtx({
      gateway: {
        ...buildGateway(),
        rpc: vi.fn(() => Promise.resolve({ value: 'show' }))
      }
    })

    expect(createSlashHandler(ctx)('/reasoning show')).toBe(true)

    await vi.waitFor(() => {
      expect(getUiState().showReasoning).toBe(true)
      expect(getUiState().sections.thinking).toBe('expanded')
    })
  })

  it('opens the skills hub locally for bare /skills', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/skills')).toBe(true)
    expect(getOverlayState().skillsHub).toBe(true)
    expect(ctx.gateway.rpc).not.toHaveBeenCalled()
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('routes /skills install <name> to skills.manage without opening overlay', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/skills install foo')).toBe(true)
    expect(getOverlayState().skillsHub).toBe(false)
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('skills.manage', {
      action: 'install',
      query: 'foo'
    })
  })

  it('routes /skills inspect <name> to skills.manage', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/skills inspect my-skill')
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('skills.manage', {
      action: 'inspect',
      query: 'my-skill'
    })
  })

  it('routes /skills search <query> to skills.manage', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/skills search vibe')
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('skills.manage', {
      action: 'search',
      query: 'vibe'
    })
  })

  it('routes /skills browse [page] to skills.manage with a numeric page', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/skills browse 3')
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('skills.manage', {
      action: 'browse',
      page: 3
    })
  })

  it('delegates non-native /skills subcommands to slash.exec', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/skills check')
    expect(ctx.gateway.rpc).not.toHaveBeenCalled()
    expect(ctx.gateway.gw.request).toHaveBeenCalledWith('slash.exec', {
      command: 'skills check',
      session_id: null
    })
  })

  it('passes /new <title> through to the session lifecycle', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/new sprint planning')
    getOverlayState().confirm?.onConfirm()

    expect(ctx.session.newSession).toHaveBeenCalledWith('new forecast session started', 'sprint planning')
    expect(ctx.gateway.rpc).not.toHaveBeenCalled()
  })

  it('reloads skills in the live gateway and refreshes the catalog', async () => {
    const rpc = vi.fn((method: string) => {
      if (method === 'skills.reload') {
        return Promise.resolve({ output: '42 skill(s) available' })
      }
      if (method === 'commands.catalog') {
        return Promise.resolve({ canon: { '/new-skill': '/new-skill' }, pairs: [['/new-skill', 'demo']] })
      }
      return Promise.resolve({})
    })
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    createSlashHandler(ctx)('/reload-skills')

    expect(rpc).toHaveBeenCalledWith('skills.reload', {})
    await vi.waitFor(() => {
      expect(ctx.transcript.page).toHaveBeenCalledWith('42 skill(s) available', 'Reload Skills')
      expect(ctx.local.setCatalog).toHaveBeenCalledWith(
        expect.objectContaining({ canon: { '/new-skill': '/new-skill' }, pairs: [['/new-skill', 'demo']] })
      )
    })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  // Regressions from Copilot review on #19835: /voice output + frontend
  // binding state must both track the gateway's fresh ``record_key`` on
  // every response, or a config edit shows the new shortcut in text
  // while push-to-talk still fires the old one until the next mtime
  // poll (~5s).
  it('/voice status renders the gateway record_key and pushes it into frontend state', async () => {
    const rpc = vi.fn(() => Promise.resolve({ enabled: true, record_key: 'ctrl+space', tts: false }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/voice status')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('  Record key: Ctrl+Space')
    })
    expect(ctx.voice.setVoiceRecordKey).toHaveBeenCalledWith(
      expect.objectContaining({ ch: 'space', mod: 'ctrl', named: 'space' })
    )
  })

  it('/voice on renders the configured binding for the start/stop hint', async () => {
    const rpc = vi.fn(() => Promise.resolve({ enabled: true, record_key: 'alt+r', tts: false }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/voice on')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('Voice mode enabled')
      expect(ctx.transcript.sys).toHaveBeenCalledWith('  Alt+R to start/stop recording')
    })
    expect(ctx.voice.setVoiceRecordKey).toHaveBeenCalledWith(expect.objectContaining({ ch: 'r', mod: 'alt' }))
  })

  it('/voice falls back to Ctrl+B when the gateway response omits record_key', async () => {
    const rpc = vi.fn(() => Promise.resolve({ enabled: false, tts: false }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/voice status')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('  Record key: Ctrl+B')
    })
  })

  // Round-2 Copilot review on #19835: a response missing ``record_key``
  // (e.g. the old tts branch, or any future branch that forgets to
  // include it) MUST NOT clobber the user's cached binding back to
  // Ctrl+B. The label still renders the default for display; the
  // frontend state keeps whatever was last authoritatively set.
  it('/voice tts without record_key does not clobber cached frontend binding', async () => {
    const rpc = vi.fn(() => Promise.resolve({ enabled: true, tts: true }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/voice tts')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('Voice TTS enabled.')
    })
    expect(ctx.voice.setVoiceRecordKey).not.toHaveBeenCalled()
  })

  it('cycles details mode and persists it', async () => {
    const ctx = buildCtx()

    expect(getUiState().detailsMode).toBe('collapsed')
    expect(createSlashHandler(ctx)('/details toggle')).toBe(true)
    expect(getUiState().detailsMode).toBe('expanded')
    expect(getUiState().detailsModeCommandOverride).toBe(true)
    expect(getUiState().sections).toEqual({
      thinking: 'expanded',
      tools: 'expanded',
      subagents: 'expanded',
      activity: 'expanded'
    })
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'details_mode',
      value: 'expanded'
    })
    expect(ctx.transcript.sys).toHaveBeenCalledWith('details: expanded')
  })

  it('sets a per-section override and persists it under details_mode.<section>', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/details activity hidden')).toBe(true)
    expect(getUiState().sections.activity).toBe('hidden')
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('config.set', {
      key: 'details_mode.activity',
      value: 'hidden'
    })
    expect(ctx.transcript.sys).toHaveBeenCalledWith('details activity: hidden')
  })

  it('clears a per-section override on /details <section> reset', () => {
    const ctx = buildCtx()
    createSlashHandler(ctx)('/details tools expanded')
    expect(getUiState().sections.tools).toBe('expanded')

    createSlashHandler(ctx)('/details tools reset')
    expect(getUiState().sections.tools).toBeUndefined()
    expect(ctx.gateway.rpc).toHaveBeenLastCalledWith('config.set', {
      key: 'details_mode.tools',
      value: ''
    })
    expect(ctx.transcript.sys).toHaveBeenCalledWith('details tools: reset')
  })

  it('rejects unknown section modes with a usage hint', () => {
    const ctx = buildCtx()
    createSlashHandler(ctx)('/details tools blink')
    expect(getUiState().sections.tools).toBeUndefined()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('usage: /details <section> [hidden|collapsed|expanded|reset]')
  })

  it('shows tool enable usage when names are missing', () => {
    const ctx = buildCtx()

    expect(createSlashHandler(ctx)('/tools enable')).toBe(true)
    expect(ctx.transcript.sys).toHaveBeenNthCalledWith(1, 'usage: /tools enable <name> [name ...]')
    expect(ctx.transcript.sys).toHaveBeenNthCalledWith(2, 'built-in toolset: /tools enable web')
    expect(ctx.transcript.sys).toHaveBeenNthCalledWith(3, 'MCP tool: /tools enable github:create_issue')
  })

  it.each([
    ['/browser status', 'browser.manage', { action: 'status', session_id: null }],
    ['/browser connect', 'browser.manage', { action: 'connect', session_id: null, url: 'http://127.0.0.1:9222' }],
    ['/reload-mcp', 'reload.mcp', { session_id: null }],
    ['/reload', 'reload.env', {}],
    ['/stop', 'process.stop', {}],
    ['/fast status', 'config.get', { key: 'fast', session_id: null }],
    ['/busy status', 'config.get', { key: 'busy' }],
    ['/indicator', 'config.get', { key: 'indicator' }]
  ])('routes %s through native RPC (no slash worker)', (command, method, params) => {
    const rpc = vi.fn(() => Promise.resolve({}))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)(command)).toBe(true)
    expect(rpc).toHaveBeenCalledWith(method, params)
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('renders browser connect progress messages from the gateway', async () => {
    const rpc = vi.fn(() =>
      Promise.resolve({
        connected: false,
        messages: [
          "Chromium-family browser isn't running with remote debugging — attempting to launch...",
          'Browser not connected — start a Chromium-family browser with remote debugging and retry /browser connect'
        ],
        url: 'http://127.0.0.1:9222'
      })
    )

    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/browser connect')).toBe(true)
    expect(ctx.transcript.sys).toHaveBeenCalledWith('checking Chromium-family browser remote debugging at http://127.0.0.1:9222...')

    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith(
        "Chromium-family browser isn't running with remote debugging — attempting to launch..."
      )
      expect(ctx.transcript.sys).toHaveBeenCalledWith(
        'Browser not connected — start a Chromium-family browser with remote debugging and retry /browser connect'
      )
      expect(ctx.transcript.sys).not.toHaveBeenCalledWith('browser connect failed')
    })
  })

  it('routes /rollback through native RPC when a session is active', () => {
    patchUiState({ sid: 'sid-abc' })
    const rpc = vi.fn(() => Promise.resolve({}))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/rollback')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('rollback.list', { session_id: 'sid-abc' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('hot-swaps the live indicator when /indicator <style> succeeds', async () => {
    const rpc = vi.fn(() => Promise.resolve({ value: 'markers' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/indicator markers')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('config.set', { key: 'indicator', value: 'markers' })
    await vi.waitFor(() => expect(getUiState().indicatorStyle).toBe('markers'))
  })

  it('accepts the legacy kaomoji indicator name as a markers alias', async () => {
    const rpc = vi.fn(() => Promise.resolve({ value: 'markers' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/indicator kaomoji')).toBe(true)
    expect(rpc).toHaveBeenCalledWith('config.set', { key: 'indicator', value: 'markers' })
    await vi.waitFor(() => expect(getUiState().indicatorStyle).toBe('markers'))
  })

  it('rejects unknown indicator styles before hitting the gateway', () => {
    const rpc = vi.fn(() => Promise.resolve({}))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    expect(createSlashHandler(ctx)('/indicator sparkle')).toBe(true)
    expect(rpc).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('usage: /indicator [ascii|emoji|markers|unicode]')
  })

  it('drops stale slash.exec output after a newer slash', async () => {
    let resolveLate: (v: { output?: string }) => void
    let slashExecCalls = 0

    const ctx = buildCtx({
      gateway: {
        gw: {
          getLogTail: vi.fn(() => ''),
          request: vi.fn((method: string) => {
            if (method === 'slash.exec') {
              slashExecCalls += 1

              if (slashExecCalls === 1) {
                return new Promise<{ output?: string }>(res => {
                  resolveLate = res
                })
              }

              return Promise.resolve({ output: 'fresh' })
            }

            return Promise.resolve({})
          })
        },
        rpc: vi.fn(() => Promise.resolve({}))
      }
    })

    const h = createSlashHandler(ctx)
    expect(h('/slow')).toBe(true)
    expect(h('/later')).toBe(true)
    resolveLate!({ output: 'too late' })
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalled()
    })

    expect(ctx.transcript.sys).not.toHaveBeenCalledWith('too late')
  })

  it('dispatches command.dispatch with typed alias', async () => {
    const ctx = buildCtx({
      gateway: {
        gw: {
          getLogTail: vi.fn(() => ''),
          request: vi.fn((method: string) => {
            if (method === 'slash.exec') {
              return Promise.reject(new Error('no'))
            }

            if (method === 'command.dispatch') {
              return Promise.resolve({ type: 'alias', target: 'help' })
            }

            return Promise.resolve({})
          })
        },
        rpc: vi.fn(() => Promise.resolve({}))
      }
    })

    const h = createSlashHandler(ctx)
    expect(h('/zzz')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.panel).toHaveBeenCalledWith(expect.any(String), expect.any(Array))
    })
  })

  it('resolves unique local aliases through the catalog', () => {
    const ctx = buildCtx({
      local: {
        catalog: {
          canon: {
            '/h': '/help',
            '/help': '/help'
          }
        }
      }
    })

    expect(createSlashHandler(ctx)('/h')).toBe(true)
    expect(ctx.transcript.panel).toHaveBeenCalledWith(expect.any(String), expect.any(Array))
  })

  it('lets exact catalog commands win over longer prefix matches', async () => {
    const ctx = buildCtx({
      local: {
        catalog: {
          canon: {
            '/profile': '/profile',
            '/plugins': '/plugins'
          }
        }
      }
    })

    expect(createSlashHandler(ctx)('/profile')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.gateway.gw.request).toHaveBeenCalledWith('slash.exec', {
        command: 'profile',
        session_id: null
      })
    })
    expect(ctx.transcript.sys).not.toHaveBeenCalledWith(expect.stringContaining('ambiguous command'))
  })

  it('keeps ambiguous prefix handling when there is no exact catalog match', () => {
    const ctx = buildCtx({
      local: {
        catalog: {
          canon: {
            '/status': '/status',
            '/statusbar': '/statusbar'
          }
        }
      }
    })

    expect(createSlashHandler(ctx)('/stat')).toBe(true)
    expect(ctx.transcript.sys).toHaveBeenCalledWith('ambiguous command: /status, /statusbar')
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('falls through to command.dispatch for skill commands and sends the message', async () => {
    const skillMessage = 'Use this skill to do X.\n\n## Steps\n1. First step'

    const ctx = buildCtx({
      gateway: {
        gw: {
          getLogTail: vi.fn(() => ''),
          request: vi.fn((method: string) => {
            if (method === 'slash.exec') {
              return Promise.reject(new Error('skill command: use command.dispatch'))
            }

            if (method === 'command.dispatch') {
              return Promise.resolve({ type: 'skill', message: skillMessage, name: 'hermes-agent-dev' })
            }

            return Promise.resolve({})
          })
        },
        rpc: vi.fn(() => Promise.resolve({}))
      }
    })

    const h = createSlashHandler(ctx)
    expect(h('/hermes-agent-dev')).toBe(true)
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('⚡ loading skill: hermes-agent-dev')
    })
    expect(ctx.transcript.send).toHaveBeenCalledWith(skillMessage)
  })

  it('/history pages the current TUI research transcript', () => {
    const ctx = buildCtx({
      local: {
        ...buildLocal(),
        getHistoryItems: vi.fn(() => [
          { role: 'user', text: 'hello' },
          { role: 'system', text: 'ignore me' },
          { role: 'assistant', text: 'hi there' },
          { role: 'user', text: 'test' }
        ])
      }
    })

    createSlashHandler(ctx)('/history')
    expect(ctx.transcript.page).toHaveBeenCalledTimes(1)

    const [body, title] = ctx.transcript.page.mock.calls[0]!

    expect(title).toBe('History')
    expect(body).toContain('[You #1]')
    expect(body).toContain('hello')
    expect(body).toContain('[Forecast Desk #2]')
    expect(body).toContain('hi there')
    expect(body).toContain('[You #3]')
    expect(body).not.toContain('ignore me')
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
  })

  it('/history reports empty state without paging', () => {
    const ctx = buildCtx()

    createSlashHandler(ctx)('/history')
    expect(ctx.transcript.page).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('no forecast transcript yet')
  })

  it('/save forwards to session.save RPC and reports the returned file', async () => {
    patchUiState({ sid: 'sid-abc' })

    const rpc = vi.fn(() => Promise.resolve({ file: '/tmp/forecast_transcript_test.json' }))

    const ctx = buildCtx({
      gateway: { ...buildGateway(), rpc },
      local: {
        ...buildLocal(),
        getHistoryItems: vi.fn(() => [
          { role: 'system', text: 'intro' },
          { role: 'user', text: 'hello' },
          { role: 'assistant', text: 'hi there' }
        ])
      }
    })

    createSlashHandler(ctx)('/save')

    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(rpc).toHaveBeenCalledWith('session.save', { session_id: 'sid-abc' })

    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('forecast transcript saved to: /tmp/forecast_transcript_test.json')
    })
  })

  it('/save reports empty state without calling the RPC or slash worker', () => {
    const rpc = vi.fn(() => Promise.resolve({}))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    createSlashHandler(ctx)('/save')

    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    expect(rpc).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('no forecast transcript yet')
  })

  it('/save without an active session tells the user instead of hitting the RPC', () => {
    // sid stays null (default) but there IS visible forecast transcript
    const rpc = vi.fn(() => Promise.resolve({}))

    const ctx = buildCtx({
      gateway: { ...buildGateway(), rpc },
      local: {
        ...buildLocal(),
        getHistoryItems: vi.fn(() => [{ role: 'user', text: 'hello' }])
      }
    })

    createSlashHandler(ctx)('/save')

    expect(rpc).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('no active forecast session — nothing to save')
  })

  it('/rollback without an active session tells the user instead of hitting the RPC', () => {
    const rpc = vi.fn(() => Promise.resolve({}))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    createSlashHandler(ctx)('/rollback')

    expect(rpc).not.toHaveBeenCalled()
    expect(ctx.transcript.sys).toHaveBeenCalledWith('no active forecast session — nothing to rollback')
  })

  it('/title <name> uses session.title RPC and bypasses slash.exec', async () => {
    patchUiState({ sid: 'sid-abc' })
    const rpc = vi.fn(() => Promise.resolve({ pending: false, title: 'my title' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    createSlashHandler(ctx)('/title my title')

    expect(rpc).toHaveBeenCalledWith('session.title', { session_id: 'sid-abc', title: 'my title' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('forecast session title set: my title')
    })
  })

  it('/title with no args fetches and displays the current title', async () => {
    patchUiState({ sid: 'sid-abc' })
    const rpc = vi.fn(() => Promise.resolve({ title: 'demo title' }))
    const ctx = buildCtx({ gateway: { ...buildGateway(), rpc } })

    createSlashHandler(ctx)('/title')

    expect(rpc).toHaveBeenCalledWith('session.title', { session_id: 'sid-abc' })
    expect(ctx.gateway.gw.request).not.toHaveBeenCalled()
    await vi.waitFor(() => {
      expect(ctx.transcript.sys).toHaveBeenCalledWith('title: demo title')
    })
  })
})

const buildCtx = (overrides: Partial<Ctx> = {}): Ctx => ({
  ...overrides,
  slashFlightRef: overrides.slashFlightRef ?? { current: 0 },
  composer: { ...buildComposer(), ...overrides.composer },
  gateway: { ...buildGateway(), ...overrides.gateway },
  local: { ...buildLocal(), ...overrides.local },
  session: { ...buildSession(), ...overrides.session },
  transcript: { ...buildTranscript(), ...overrides.transcript },
  voice: { ...buildVoice(), ...overrides.voice }
})

const buildComposer = () => ({
  enqueue: vi.fn(),
  hasSelection: false,
  paste: vi.fn(),
  queueRef: { current: [] as string[] },
  selection: { copySelection: vi.fn(async () => '') },
  setInput: vi.fn()
})

const buildGateway = () => ({
  gw: {
    getLogTail: vi.fn(() => ''),
    kill: vi.fn(),
    request: vi.fn(() => Promise.resolve({}))
  },
  rpc: vi.fn(() => Promise.resolve({}))
})

const buildLocal = () => ({
  catalog: null,
  getHistoryItems: vi.fn(() => []),
  getLastUserMsg: vi.fn(() => ''),
  maybeWarn: vi.fn(),
  setCatalog: vi.fn()
})

const buildSession = () => ({
  closeSession: vi.fn(() => Promise.resolve(null)),
  die: vi.fn(),
  dieWithCode: vi.fn(),
  guardBusySessionSwitch: vi.fn(() => false),
  newSession: vi.fn(),
  resetVisibleHistory: vi.fn(),
  resumeById: vi.fn(),
  setSessionStartedAt: vi.fn()
})

const buildTranscript = () => ({
  page: vi.fn(),
  panel: vi.fn(),
  send: vi.fn(),
  setHistoryItems: vi.fn(),
  sys: vi.fn(),
  trimLastExchange: vi.fn(items => items)
})

const buildVoice = () => ({
  setVoiceEnabled: vi.fn(),
  setVoiceRecordKey: vi.fn()
})

interface Ctx {
  slashFlightRef: { current: number }
  composer: ReturnType<typeof buildComposer>
  gateway: ReturnType<typeof buildGateway>
  local: ReturnType<typeof buildLocal>
  session: ReturnType<typeof buildSession>
  transcript: ReturnType<typeof buildTranscript>
  voice: ReturnType<typeof buildVoice>
}
