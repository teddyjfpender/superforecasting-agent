import React from 'react'
import { PassThrough } from 'stream'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AppLayoutProps } from '../app/interfaces.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'
import type { Msg } from '../types.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const forecastFixture = (): ForecastDashboardResponse => ({
  output: 'SUPERFORECASTING DESK\n\nACTIVE FORECASTS\nfq_review123456 0.63 needs update',
  summary: {
    active_count: 2,
    calibration: {
      count: 7,
      ensemble_component_contributions: [
        { count: 7, mean_contribution: 0.41, mean_probability: 0.58, mean_weight_share: 0.72, name: 'market' },
        { count: 7, mean_contribution: 0.16, mean_probability: 0.52, mean_weight_share: 0.28, name: 'base_rate' }
      ],
      mean_brier: 0.142,
      mean_log_score: -0.49,
      mean_sharpness: 0.33,
      probability_movement_count: 5
    },
    evidence_status: {
      gaps: ['live_scored_forecasts', 'agent_protocol_scored_cases'],
      next_actions: [
        {
          action: 'Resolve and score live forecasts before making stronger benchmark claims.',
          requirement_id: 'live_scored_forecasts'
        }
      ],
      score_counts: { backtest: 14, imported_baseline: 14, live: 4 },
      verdict: 'insufficient_live_evidence'
    },
    learning: {
      active_lessons: 1,
      invalidated_lessons: 0,
      tentative_lessons: 1,
      total_lessons: 2
    },
    open_alert_count: 1,
    open_assumption_count: 3,
    open_reference_class_count: 2,
    product: 'Superforecasting Agent',
    questions: [
      {
        as_of: '2026-05-25T09:00:00Z',
        baseline_count: 2,
        close_time: '2026-07-01T00:00:00Z',
        confidence: 0.72,
        delta: 0.08,
        evidence_count: 6,
        id: 'fq_watch123456',
        open_alert_count: 1,
        open_assumption_count: 2,
        open_reference_class_count: 1,
        probability: 0.63,
        stale_assumption_count: 1,
        stale_reference_class_count: 0,
        title: 'Will the tester pilot produce a scored forecast by July?'
      },
      {
        as_of: '2026-05-24T15:00:00Z',
        close_time: '2026-08-15T00:00:00Z',
        confidence: 0.58,
        delta: -0.04,
        evidence_count: 3,
        id: 'fq_macro987654',
        probability: 0.41,
        stale_reference_class_count: 1,
        title: 'Will the macro indicator cross the threshold by August?'
      }
    ],
    recent_backtests: [
      {
        agent_edge: 0.018,
        agent_mean_brier: 0.131,
        best_baseline: 'market:fixture',
        best_baseline_brier: 0.149,
        case_count: 40,
        claim_status: { message: 'Benchmark replay only.', verdict: 'benchmark_replay_only' },
        dataset: 'fixture-corpus',
        id: 'bt_fixture001',
        leakage_checks_passed: true,
        paired_agent_wins: 22,
        paired_baseline_wins: 14,
        paired_ties: 4,
        probability_sources: ['forecast-engine']
      }
    ],
    review_queue: [
      {
        as_of: '2026-05-25T09:00:00Z',
        close_time: '2026-07-01T00:00:00Z',
        id: 'fq_review123456',
        next_action: 'forecast research fq_review123456',
        priority: 1,
        probability: 0.63,
        reasons: ['review_due', 'new_evidence'],
        title: 'Will the tester pilot produce a scored forecast by July?'
      }
    ],
    review_queue_count: 1,
    stale_assumption_count: 1,
    stale_reference_class_count: 1
  }
})

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

  return {
    stream,
    text: () => output
  }
}

const normalizeOutput = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const renderForecastDesk = async (columns: number) => {
  vi.resetModules()
  process.env.FORECAST_TUI_INLINE = '1'

  const [
    { renderSync },
    { GatewayProvider },
    { forecastDashboardSections, forecastDeskRailSections, forecastDeskStatusLabel },
    { resetOverlayState },
    { resetUiState, patchUiState },
    { AppLayout },
    { stripAnsi },
    { DEFAULT_VOICE_RECORD_KEY }
  ] = await Promise.all([
    import('@hermes/ink'),
    import('../app/gatewayContext.js'),
    import('../app/forecastPanel.js'),
    import('../app/overlayStore.js'),
    import('../app/uiStore.js'),
    import('../components/appLayout.js'),
    import('../lib/text.js'),
    import('../lib/platform.js')
  ])

  const response = forecastFixture()
  const panelSections = forecastDashboardSections(response)
  const historyItems: Msg[] = [
    { kind: 'panel', panelData: { sections: panelSections, title: 'Forecast Desk' }, role: 'system', text: '' }
  ]
  const virtualRows = historyItems.map((msg, index) => ({ index, key: `row-${index}`, msg }))
  const stdout = writeStream(columns, 32)
  const stdin = writeStream(columns, 32, true)
  const stderr = writeStream(columns, 32)

  resetUiState()
  resetOverlayState()
  patchUiState({
    forecastDeskRailSections: forecastDeskRailSections(response),
    forecastDeskStatus: forecastDeskStatusLabel(response),
    sid: 's_forecast_render',
    status: 'ready'
  })

  const noop = () => undefined
  const props: AppLayoutProps = {
    actions: {
      answerApproval: noop,
      answerClarify: noop,
      answerSecret: noop,
      answerSudo: noop,
      clearSelection: noop,
      onModelSelect: noop,
      resumeById: noop,
      setStickyPrompt: noop
    },
    composer: {
      cols: columns,
      compIdx: 0,
      completions: [],
      empty: false,
      handleTextPaste: () => null,
      input: '',
      inputBuf: [],
      pagerPageSize: 8,
      queueEditIdx: null,
      queuedDisplay: [],
      submit: noop,
      updateInput: noop,
      voiceRecordKey: DEFAULT_VOICE_RECORD_KEY
    },
    mouseTracking: false,
    progress: { showProgressArea: false },
    status: {
      cwdLabel: '~/superforecasting-agent',
      forecastPulseTick: 1,
      sessionStartedAt: Date.parse('2026-05-25T09:00:00Z'),
      showStickyPrompt: false,
      statusColor: 'green',
      stickyPrompt: '',
      turnStartedAt: null,
      voiceLabel: ''
    },
    transcript: {
      historyItems,
      scrollRef: React.createRef(),
      virtualHistory: {
        bottomSpacer: 0,
        end: virtualRows.length,
        measureRef: () => noop,
        offsets: [0, 12],
        start: 0,
        topSpacer: 0
      },
      virtualRows
    }
  }

  const instance = renderSync(
    React.createElement(
      GatewayProvider,
      { value: { gw: { request: async () => null } as never, rpc: async () => null } },
      React.createElement(AppLayout, props)
    ),
    {
      patchConsole: false,
      stderr: stderr.stream as NodeJS.WriteStream,
      stdin: stdin.stream as NodeJS.ReadStream,
      stdout: stdout.stream as NodeJS.WriteStream
    }
  )

  instance.unmount()
  instance.cleanup()

  return normalizeOutput(stdout.text(), stripAnsi)
}

describe('forecast desk Ink render', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the wide-terminal forecast rail and persistent desk actions from the real AppLayout path', async () => {
    const output = await renderForecastDesk(150)
    const compact = output.replace(/\s+/g, '')

    expect(compact).toContain('ForecastDesk')
    expect(compact).toContain('desk2active/1alert/1review/cal7/2lessons/asm3/1/refs2/1')
    expect(compact).toContain('Triage')
    expect(compact).toContain('/forecastreadiness')
    expect(compact).toContain('Watchlist')
    expect(compact).toContain('watch123P=0.630')
    expect(compact).toContain('deskactions')
    expect(compact).toContain('/forecastshowfq_review123456')
    expect(compact).not.toContain('deskbrief')
  })

  it('renders the narrow-terminal desk brief when the rail cannot fit', async () => {
    const output = await renderForecastDesk(104)
    const compact = output.replace(/\s+/g, '')

    expect(compact).toContain('ForecastDesk')
    expect(compact).toContain('deskbrief')
    expect(compact).toContain('book2active')
    expect(compact).toContain('1alerts')
    expect(compact).toContain('reviewqueue1')
    expect(compact).toContain('asm3/1')
    expect(compact).toContain('referenceclasses2/1')
    expect(compact).toContain('triage/alerts1openalert')
    expect(compact).toContain('deskactions')
    expect(compact).toContain('/forecastshowfq_review123456')
  })
})
