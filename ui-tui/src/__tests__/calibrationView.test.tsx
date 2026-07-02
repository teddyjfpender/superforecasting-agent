import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { ForecastCalibrationBias, ForecastCalibrationResponse } from '../gatewayTypes.js'
import { clearOverlayCache } from '../lib/overlayCache.js'

// The overlay cache is a process-lived singleton; reset it so one test's
// fixture doesn't bleed into the next (e.g. the empty-state case).
beforeEach(() => clearOverlayCache())

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const curveRow = (
  bucket: string,
  count: number,
  predicted: null | number,
  observed: null | number
): NonNullable<NonNullable<ForecastCalibrationResponse['summary']>['calibration_curve']>[number] => ({
  bucket,
  calibration_gap: count && predicted !== null && observed !== null ? Math.abs(observed - predicted) : null,
  count,
  mean_predicted: predicted,
  observed_frequency: observed,
  sample_status: !count ? 'empty' : count < 5 ? 'low_sample' : 'ok'
})

const biasFixture = (overrides: Partial<ForecastCalibrationBias> = {}): ForecastCalibrationBias => ({
  advisory_text: 'forecasts in the 60-80% band resolve YES more often than stated',
  direction: 'under',
  ece: 0.052,
  ess: 18.4,
  ess_min: 12,
  n: 21,
  sce_shrunk: -0.061,
  scope_ref: null,
  scope_type: 'global',
  status: 'underconfident',
  ...overrides
})

const fixture = (): ForecastCalibrationResponse => ({
  bias: biasFixture(),
  domains: [
    {
      bias: biasFixture({ advisory_text: 'under-confident in macro', scope_ref: 'macro', scope_type: 'domain' }),
      count: 12,
      domain: 'macro',
      expected_calibration_error: 0.062,
      mean_brier: 0.21
    },
    {
      bias: biasFixture({ sce_shrunk: 0.004, scope_ref: 'geopolitics', scope_type: 'domain', status: 'calibrated' }),
      count: 9,
      domain: 'geopolitics',
      expected_calibration_error: 0.031,
      mean_brier: 0.15
    },
    { bias: biasFixture({ ess: 2, scope_ref: 'tech', scope_type: 'domain', status: 'insufficient_evidence' }), count: 2, domain: 'tech' }
  ],
  origins: [
    { count: 14, expected_calibration_error: 0.048, mean_brier: 0.17, origin: 'live' },
    { count: 7, expected_calibration_error: 0.06, mean_brier: 0.2, origin: 'backtest' }
  ],
  summary: {
    calibration_curve: [
      curveRow('0.0-0.1', 0, null, null),
      curveRow('0.1-0.2', 0, null, null),
      curveRow('0.2-0.3', 3, 0.24, 0.33),
      curveRow('0.3-0.4', 0, null, null),
      curveRow('0.4-0.5', 0, null, null),
      curveRow('0.5-0.6', 0, null, null),
      curveRow('0.6-0.7', 10, 0.64, 0.7),
      curveRow('0.7-0.8', 8, 0.74, 0.88),
      curveRow('0.8-0.9', 0, null, null),
      curveRow('0.9-1.0', 0, null, null)
    ],
    calibration_curve_sample_count: 21,
    count: 21,
    expected_calibration_error: 0.052,
    max_calibration_error: 0.14,
    mean_brier: 0.183
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

  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const renderView = async (response: ForecastCalibrationResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { CalibrationView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/calibrationView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(110, 50)
  const stdin = writeStream(110, 50, true)

  const fakeGw = {
    request: (_method: string, _params: Record<string, unknown>) => Promise.resolve(response)
  } as unknown as Parameters<typeof CalibrationView>[0]['gw']

  const instance = render(
    React.createElement(CalibrationView, { gw: fakeGw, onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(60)
  const text = normalize(stdout.text(), stripAnsi)
  instance.unmount?.()
  instance.cleanup?.()

  return text
}

describe('calibration pure helpers', () => {
  it('bucketLabel converts decile labels to percent ranges and passes unknowns through', async () => {
    const { bucketLabel } = await import('../components/calibrationView.js')
    expect(bucketLabel('0.6-0.7')).toBe('60-70%')
    expect(bucketLabel('0.0-0.1')).toBe('0-10%')
    expect(bucketLabel('0.9-1.0')).toBe('90-100%')
    expect(bucketLabel('7-30')).toBe('7-30')
    expect(bucketLabel(undefined)).toBe('—')
  })

  it('reliabilityBandPoints marks observed and spans the gap to predicted; empty deciles stay null', async () => {
    const { reliabilityBandPoints } = await import('../components/calibrationView.js')
    const points = reliabilityBandPoints(fixture().summary!.calibration_curve)
    expect(points).toHaveLength(10)
    // empty decile → null gap, never a fake zero
    expect(points[0]!.y).toBeNull()
    // populated decile: marker at observed, band spanning observed↔predicted
    expect(points[6]!.y).toBeCloseTo(0.7, 5)
    expect(points[6]!.lo).toBeCloseTo(0.64, 5)
    expect(points[6]!.hi).toBeCloseTo(0.7, 5)
    expect(reliabilityBandPoints(undefined)).toEqual([])
  })

  it('calibrationVerdict leads with the signed bias verdict when one exists', async () => {
    const { calibrationVerdict } = await import('../components/calibrationView.js')
    const under = calibrationVerdict(fixture().summary, biasFixture())
    expect(under.tone).toBe('warn')
    expect(under.text).toContain('under-confident')
    expect(under.text).toContain('60-80% band')

    const over = calibrationVerdict(fixture().summary, biasFixture({ advisory_text: null, sce_shrunk: 0.08, status: 'overconfident' }))
    expect(over.tone).toBe('error')
    expect(over.text).toContain('over-confident')
    expect(over.text).toContain('8pt')

    const calibrated = calibrationVerdict(fixture().summary, biasFixture({ sce_shrunk: 0.004, status: 'calibrated' }))
    expect(calibrated.tone).toBe('ok')
    expect(calibrated.text).toContain('within noise')
  })

  it('calibrationVerdict is honest about thin or missing data', async () => {
    const { calibrationVerdict } = await import('../components/calibrationView.js')
    const thin = calibrationVerdict(fixture().summary, biasFixture({ ess: 7.5, ess_min: 12, status: 'insufficient_evidence' }))
    expect(thin.tone).toBe('muted')
    expect(thin.text).toContain('need ~5 more resolution')

    const noBias = calibrationVerdict(fixture().summary, null)
    expect(noBias.tone).toBe('muted')
    expect(noBias.text).toContain('unavailable')

    const nothing = calibrationVerdict({ calibration_curve_sample_count: 0, count: 0 }, null)
    expect(nothing.text).toContain('no reliability signal yet')
  })

  it('biasShortLabel compresses the verdict for breakdown rows', async () => {
    const { biasShortLabel } = await import('../components/calibrationView.js')
    expect(biasShortLabel(biasFixture())).toBe('under-confident −6.1pt')
    expect(biasShortLabel(biasFixture({ sce_shrunk: 0.05, status: 'overconfident' }))).toBe('over-confident +5.0pt')
    expect(biasShortLabel(biasFixture({ status: 'calibrated' }))).toBe('calibrated')
    expect(biasShortLabel(biasFixture({ status: 'insufficient_evidence' }))).toBe('thin data')
    expect(biasShortLabel(null)).toBe('—')
  })
})

describe('CalibrationView render', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the headline metrics, verdict, curve, buckets, and breakdowns', async () => {
    const text = await renderView(fixture())
    expect(text).toContain('CALIBRATION')
    expect(text).toContain('21 scored')
    // headline metrics
    expect(text).toContain('ECE 5.2%')
    expect(text).toContain('MCE 14.0%')
    expect(text).toContain('Brier 0.183')
    expect(text).toContain('SCE −6.1pt')
    // plain-language verdict
    expect(text).toContain('under-confident')
    expect(text).toContain('60-80% band')
    // reliability curve chart + legend
    expect(text).toContain('reliability curve')
    expect(text).toContain('● observed frequency')
    expect(text).toContain('░ gap to predicted')
    // bucket table with percent labels and gap column
    expect(text).toContain('buckets (forecast probability deciles)')
    expect(text).toContain('60-70%')
    expect(text).toContain('low sample')
    // domain breakdown carries the per-domain bias verdict
    expect(text).toContain('by domain')
    expect(text).toContain('macro')
    expect(text).toContain('under-confident −6.1pt')
    expect(text).toContain('thin data')
    // origin breakdown
    expect(text).toContain('by origin')
    expect(text).toContain('live')
    expect(text).toContain('backtest')
    // footer keys
    expect(text).toContain('r refresh')
  })

  it('renders the rolling-Brier trend row and the lessons-correcting-this section when the payload carries them', async () => {
    const base = fixture()

    const text = await renderView({
      ...base,
      lessons: [
        {
          coverage: { applied_count: 4, application_rate: 0.8, in_scope_count: 5 },
          dormant: false,
          lesson: 'shade macro-rate forecasts 5pt toward the base rate',
          lesson_id: 'lsn_macro01',
          recommended_adjustment: { shade_pct: -5 },
          scope: 'domain:macro'
        },
        {
          coverage: { applied_count: 0, application_rate: 0, in_scope_count: 3 },
          dormant: true,
          lesson: 'never yet applied at a commit',
          lesson_id: 'lsn_dormant01',
          scope: 'domain:tech'
        }
      ],
      summary: {
        ...base.summary,
        calibration_trend: {
          direction: 'improving',
          windows: [
            { brier: 0.24, n: 8, period: 'older' },
            { brier: 0.183, n: 13, period: 'recent' }
          ]
        }
      }
    })

    // rolling-Brier trend row (oldest → newest + direction word)
    expect(text).toContain('0.240')
    expect(text).toContain('0.183')
    expect(text).toContain('improving')
    // lessons-correcting-this section: active + dormant rows
    expect(text).toContain('lessons correcting this')
    expect(text).toContain('active')
    expect(text).toContain('DORMANT')
    expect(text).toContain('shade macro-rate forecasts')
  })

  it('shows an honest empty state when nothing has resolved yet', async () => {
    const text = await renderView({ bias: null, domains: [], origins: [], summary: { calibration_curve: [], calibration_curve_sample_count: 0, count: 0 } })
    expect(text).toContain('no resolved forecasts to calibrate against yet — resolve some questions first')
    expect(text).toContain('/score')
    expect(text).not.toContain('ECE')
  })

  it('explains a missing curve when scores exist but no binary forecasts resolved', async () => {
    const base = fixture()

    const text = await renderView({
      ...base,
      bias: biasFixture({ status: 'insufficient_evidence' }),
      summary: { ...base.summary, calibration_curve: [], calibration_curve_sample_count: 0, count: 4 }
    })

    expect(text).toContain('no resolved binary forecasts yet')
  })
})
