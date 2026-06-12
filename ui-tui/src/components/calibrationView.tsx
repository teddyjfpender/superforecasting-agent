import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastCalibrationBias,
  ForecastCalibrationBreakdownRow,
  ForecastCalibrationCurveRow,
  ForecastCalibrationResponse,
  ForecastCalibrationSummary
} from '../gatewayTypes.js'
import { bandChart, type BandPoint, pct } from '../lib/forecastCharts.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

export const openCalibrationView = () => patchOverlayState({ calibration: true })

export const closeCalibrationView = () => patchOverlayState({ calibration: false })

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

/** `0.052` → `"5.2%"` for error metrics (one decimal keeps small ECEs visible). */
const errPct = (value: number | null | undefined): string => (finite(value) ? `${(value * 100).toFixed(1)}%` : '—')

/** Signed SCE in probability points: `-0.06` → `"−6.0pt"`. */
const scePts = (value: number | null | undefined): string => {
  if (!finite(value)) {
    return '—'
  }

  const pts = value * 100

  return `${pts > 0 ? '+' : pts < 0 ? '−' : ''}${Math.abs(pts).toFixed(1)}pt`
}

/** `"0.6-0.7"` → `"60-70%"`; unknown labels pass through. */
export const bucketLabel = (bucket: string | undefined): string => {
  const match = (bucket ?? '').match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$/)

  if (!match) {
    return bucket ?? '—'
  }

  const lo = Number(match[1])
  const hi = Number(match[2])

  if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo > 1 || hi > 1) {
    return bucket ?? '—'
  }

  return `${Math.round(lo * 100)}-${Math.round(hi * 100)}%`
}

/**
 * Reliability curve → band-chart points. One column per decile (x: forecast
 * probability 0→1): the marker is the OBSERVED frequency and the band spans
 * observed↔predicted, so the visible ░ height IS the calibration gap. Empty
 * deciles stay null gaps — no fake zeros.
 */
export const reliabilityBandPoints = (curve: ForecastCalibrationCurveRow[] | undefined): BandPoint[] =>
  (curve ?? []).map(row => {
    const observed = row.observed_frequency
    const predicted = row.mean_predicted

    if (!row.count || !finite(observed)) {
      return { y: null }
    }

    if (!finite(predicted)) {
      return { y: observed }
    }

    return { hi: Math.max(observed, predicted), lo: Math.min(observed, predicted), y: observed }
  })

export interface CalibrationVerdict {
  text: string
  tone: 'error' | 'muted' | 'ok' | 'warn'
}

/**
 * The plain-language headline read. Bias-led when the signed loop produced a
 * verdict; honest about thin data otherwise. Never invents a direction the
 * engine did not measure.
 */
export const calibrationVerdict = (
  summary: ForecastCalibrationSummary | undefined,
  bias: ForecastCalibrationBias | null | undefined
): CalibrationVerdict => {
  const curveSamples = summary?.calibration_curve_sample_count ?? 0

  if (!bias) {
    if (!curveSamples) {
      return { text: 'no reliability signal yet — resolved binary forecasts feed the curve', tone: 'muted' }
    }

    return { text: 'signed bias check unavailable for this ledger — showing unsigned calibration only', tone: 'muted' }
  }

  if (bias.status === 'underconfident' || bias.status === 'overconfident') {
    const word = bias.status === 'underconfident' ? 'under-confident' : 'over-confident'

    const detail =
      bias.advisory_text ||
      `stated probabilities sit ~${Math.abs((bias.sce_shrunk ?? 0) * 100).toFixed(0)}pt too ${
        bias.status === 'underconfident' ? 'close to 50%' : 'far from 50%'
      }`

    return { text: `${word} — ${detail}`, tone: bias.status === 'overconfident' ? 'error' : 'warn' }
  }

  if (bias.status === 'calibrated') {
    return {
      text: `calibrated — observed frequencies match stated probabilities within noise (SCE ${scePts(bias.sce_shrunk)})`,
      tone: 'ok'
    }
  }

  // insufficient_evidence: say how far the sample is from a stable read.
  const need = Math.max(1, Math.ceil((bias.ess_min ?? 0) - (bias.ess ?? 0)))

  return {
    text: `not enough resolved forecasts for a signed read — need ~${need} more resolution${need === 1 ? '' : 's'} (effective sample ${(
      bias.ess ?? 0
    ).toFixed(1)} of ${bias.ess_min ?? 0})`,
    tone: 'muted'
  }
}

/** Compact bias verdict for a breakdown row: direction word or data state. */
export const biasShortLabel = (bias: ForecastCalibrationBias | null | undefined): string => {
  if (!bias) {
    return '—'
  }

  if (bias.status === 'underconfident') {
    return `under-confident ${scePts(bias.sce_shrunk)}`
  }

  if (bias.status === 'overconfident') {
    return `over-confident ${scePts(bias.sce_shrunk)}`
  }

  if (bias.status === 'calibrated') {
    return 'calibrated'
  }

  return 'thin data'
}

interface CalibrationViewProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

export function CalibrationView({ gw, onClose, t }: CalibrationViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [data, setData] = useState<ForecastCalibrationResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)

  const load = (announce = false) => {
    setLoading(true)
    gw.request<unknown>('forecast.calibration', {})
      .then(raw => {
        const result = asRpcResult<ForecastCalibrationResponse>(raw)

        if (!result) {
          setError('forecast.calibration returned no data')
          setLoading(false)

          return
        }

        setData(result)
        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // Start each load (open or refresh) reading from the top — the ScrollBox
  // otherwise keeps the previous visit's offset.
  useEffect(() => {
    scrollRef.current?.scrollTo(0)
  }, [data])

  useEffect(() => {
    // Drives OverlayScrollbar reflow detection (content height settles async).
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'r') {
      return load(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return scrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollRef.current?.scrollBy(pageSize)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  })

  const width = Math.max(40, cols - 4)

  let body

  if (loading && !data) {
    body = <Text color={t.color.muted}>Loading calibration…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load calibration: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (!data?.summary || !(data.summary.count ?? 0)) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.muted} wrap="wrap">
          no resolved forecasts to calibrate against yet — resolve some questions first
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            calibration needs closed loops: /resolve {'<id>'} --outcome yes|no --confirmed, then /score {'<id>'}. Each
            scored resolution adds one point to the reliability curve.
          </Text>
        </Box>
      </Box>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <CalibrationBody data={data} t={t} width={width} />
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    )
  }

  const summary = data?.summary

  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          CALIBRATION
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={t.color.text}>{summary?.count ?? 0}</Text>
        <Text color={t.color.muted}> scored · </Text>
        <Text color={t.color.text}>{summary?.calibration_curve_sample_count ?? 0}</Text>
        <Text color={t.color.muted}> on the reliability curve · all origins</Text>
      </Text>
    </Box>
  )

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        ↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
    </Box>
  )
}

// ── Body sections ────────────────────────────────────────────────────────────

function SectionTitle({ children, t }: { children: string; t: Theme }) {
  return (
    <Box marginTop={1}>
      <Text bold color={t.color.accent}>
        {children}
      </Text>
    </Box>
  )
}

const toneColor = (t: Theme, tone: CalibrationVerdict['tone']): string =>
  tone === 'ok' ? t.color.ok : tone === 'warn' ? t.color.warn : tone === 'error' ? t.color.error : t.color.muted

function CalibrationBody({ data, t, width }: { data: ForecastCalibrationResponse; t: Theme; width: number }) {
  const summary = data.summary ?? {}
  const bias = data.bias ?? null
  const verdict = calibrationVerdict(summary, bias)
  const curve = summary.calibration_curve ?? []
  const curveSamples = summary.calibration_curve_sample_count ?? 0

  const points = useMemo(() => reliabilityBandPoints(summary.calibration_curve), [summary.calibration_curve])
  const hasCurve = points.some(point => finite(point.y))

  const chart = useMemo(
    () =>
      hasCurve
        ? bandChart(points, { height: 9, width: Math.min(56, Math.max(20, width - 1)), yMax: 1, yMin: 0 })
        : null,
    [hasCurve, points, width]
  )

  return (
    <Box flexDirection="column">
      {/* Headline metrics: the unsigned gap (ECE/MCE), accuracy (Brier), and the signed direction (SCE). */}
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>ECE </Text>
        <Text bold color={t.color.primary}>
          {errPct(summary.expected_calibration_error)}
        </Text>
        <Text color={t.color.muted}>{'  ·  MCE '}</Text>
        <Text color={t.color.text}>{errPct(summary.max_calibration_error)}</Text>
        <Text color={t.color.muted}>{'  ·  Brier '}</Text>
        <Text color={t.color.text}>{finite(summary.mean_brier) ? summary.mean_brier.toFixed(3) : '—'}</Text>
        <Text color={t.color.muted}>{'  ·  SCE '}</Text>
        <Text bold color={toneColor(t, verdict.tone)}>
          {scePts(bias?.sce_shrunk)}
        </Text>
      </Text>
      <Box marginTop={1} paddingLeft={2}>
        <Text color={toneColor(t, verdict.tone)} wrap="wrap">
          {verdict.text}
        </Text>
      </Box>

      {chart ? (
        <>
          <SectionTitle t={t}>reliability curve (observed vs predicted)</SectionTitle>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
          <Text color={t.color.label} wrap="truncate-end">
            {'  forecast 0% → 100%  ● observed frequency  ░ gap to predicted'}
          </Text>
        </>
      ) : (
        <>
          <SectionTitle t={t}>reliability curve</SectionTitle>
          <Text color={t.color.muted} wrap="wrap">
            {curveSamples
              ? 'curve unavailable — scored forecasts carry no binary reliability points'
              : 'no resolved binary forecasts yet — the curve needs yes/no outcomes to compare against stated probabilities'}
          </Text>
        </>
      )}

      {curve.length ? <BucketTable curve={curve} t={t} /> : null}

      {(data.domains ?? []).length ? (
        <BreakdownSection label="by domain" rows={data.domains ?? []} t={t} width={width} />
      ) : null}
      {(data.origins ?? []).length ? (
        <BreakdownSection label="by origin" rows={data.origins ?? []} t={t} width={width} />
      ) : null}
    </Box>
  )
}

// Predicted vs observed per decile. Empty deciles print as faint placeholders
// so the table shape is stable; low-sample rows are flagged rather than hidden.
function BucketTable({ curve, t }: { curve: ForecastCalibrationCurveRow[]; t: Theme }) {
  return (
    <>
      <SectionTitle t={t}>buckets (forecast probability deciles)</SectionTitle>
      <Text color={t.color.label}>{`${'bucket'.padEnd(9)}${'n'.padStart(4)}  ${'pred'.padStart(5)}  ${'obs'.padStart(5)}  ${'gap'.padStart(5)}`}</Text>
      {curve.map((row, i) => {
        const empty = !row.count

        if (empty) {
          return (
            <Text color={t.color.muted} key={row.bucket ?? i}>
              {`${bucketLabel(row.bucket).padEnd(9)}${'0'.padStart(4)}  ${'·'.padStart(5)}  ${'·'.padStart(5)}  ${'·'.padStart(5)}`}
            </Text>
          )
        }

        const gap = row.calibration_gap
        const gapText = finite(gap) ? `${Math.round(gap * 100)}pt` : '—'
        const gapColor = !finite(gap) ? t.color.muted : gap >= 0.1 ? t.color.error : gap >= 0.05 ? t.color.warn : t.color.ok

        return (
          <Text key={row.bucket ?? i} wrap="truncate-end">
            <Text color={t.color.text}>{bucketLabel(row.bucket).padEnd(9)}</Text>
            <Text color={t.color.text}>{String(row.count ?? 0).padStart(4)}</Text>
            <Text color={t.color.label}>{`  ${pct(row.mean_predicted).padStart(5)}`}</Text>
            <Text color={t.color.text}>{`  ${pct(row.observed_frequency).padStart(5)}`}</Text>
            <Text color={gapColor}>{`  ${gapText.padStart(5)}`}</Text>
            {row.sample_status === 'low_sample' ? <Text color={t.color.muted}>{'  low sample'}</Text> : null}
          </Text>
        )
      })}
    </>
  )
}

function BreakdownSection({
  label,
  rows,
  t,
  width
}: {
  label: string
  rows: ForecastCalibrationBreakdownRow[]
  t: Theme
  width: number
}) {
  const nameW = Math.max(8, Math.min(16, width - 44))

  return (
    <>
      <SectionTitle t={t}>{label}</SectionTitle>
      {rows.map((row, i) => {
        const name = row.domain ?? row.origin ?? '—'
        const display = name.length > nameW ? `${name.slice(0, nameW - 1)}…` : name.padEnd(nameW)
        const biasLabel = row.domain !== undefined ? biasShortLabel(row.bias) : null

        const biasColor =
          row.bias?.status === 'overconfident'
            ? t.color.error
            : row.bias?.status === 'underconfident'
              ? t.color.warn
              : row.bias?.status === 'calibrated'
                ? t.color.ok
                : t.color.muted

        return (
          <Text key={name + i} wrap="truncate-end">
            <Text color={t.color.text}>{display}</Text>
            <Text color={t.color.muted}>{'  n '}</Text>
            <Text color={t.color.text}>{String(row.count ?? 0).padStart(3)}</Text>
            <Text color={t.color.muted}>{'  brier '}</Text>
            <Text color={t.color.text}>{finite(row.mean_brier) ? row.mean_brier.toFixed(3) : '—'}</Text>
            <Text color={t.color.muted}>{'  ece '}</Text>
            <Text color={t.color.text}>{errPct(row.expected_calibration_error)}</Text>
            {biasLabel ? <Text color={biasColor}>{`  ${biasLabel}`}</Text> : null}
          </Text>
        )
      })}
    </>
  )
}
