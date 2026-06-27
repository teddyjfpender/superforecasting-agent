import { Box, Text, useInput } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastConfigGate,
  ForecastConfigResponse,
  ForecastConfigThreshold
} from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

// Per-forecast SETTINGS modal, painted over the Desk (press `s` on a selected
// forecast / lens). Owns its own useInput (the parent traps the keyboard while a
// modal is open). Sections: CADENCE (text), DECISION (owner/deadline/threshold),
// GATES (each hook gate: off/warn/error cycle), THRESHOLDS (each minimum-
// requirement: a number you ± and that flags when LOOSER than standard).
//
// Reads the resolved config via forecast.config on open; Save → forecast.config.set
// → onSaved() so the Desk's NEXT column reflects a cadence change.

const SEVERITIES = ['off', 'warn', 'error'] as const
type Severity = (typeof SEVERITIES)[number]

const sevLabel: Record<Severity, string> = { off: 'off', warn: 'warn', error: 'error' }

// One navigable line. `kind` drives how ←/→/typing edits it.
type FieldKind = 'cadence' | 'gate' | 'save' | 'text' | 'threshold'

interface Field {
  key: string
  kind: FieldKind
  // for gate/threshold: the index into the working arrays
  ref?: number
}

interface DraftDecision {
  action_threshold: string
  decision_deadline: string
  decision_owner: string
}

interface ForecastSettingsModalProps {
  cols: number
  gw: GatewayClient
  onClose: () => void
  onSaved?: () => void
  questionId: string
  rows: number
  t: Theme
  title?: string
}

const sevColor = (t: Theme, sev: string): string =>
  sev === 'error' ? t.color.error : sev === 'warn' ? t.color.warn : t.color.muted

const cycleSev = (current: string, dir: 1 | -1): Severity => {
  const idx = Math.max(0, SEVERITIES.indexOf((current as Severity) ?? 'warn'))
  const n = SEVERITIES.length
  return SEVERITIES[((idx + dir) % n + n) % n]
}

// Step a threshold by ±1 unit (integers) or ±5% of its range (continuous),
// clamped to its bounds and rounded sanely.
const stepThreshold = (thr: ForecastConfigThreshold, value: number, dir: 1 | -1): number => {
  const span = Math.max(0.0001, thr.maximum - thr.minimum)
  const step = thr.integer ? 1 : Math.max(0.01, Math.round(span * 0.05 * 100) / 100)
  let next = value + dir * step
  next = Math.max(thr.minimum, Math.min(thr.maximum, next))
  return thr.integer ? Math.round(next) : Math.round(next * 100) / 100
}

const fmtThr = (thr: ForecastConfigThreshold, value: number): string =>
  thr.integer ? String(Math.round(value)) : String(Math.round(value * 100) / 100)

export function ForecastSettingsModal({
  cols,
  gw,
  onClose,
  onSaved,
  questionId,
  rows,
  t,
  title
}: ForecastSettingsModalProps) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState(0)
  const aliveRef = useRef(true)

  // working draft (mutated locally, written on Save)
  const [cadence, setCadence] = useState('')
  const [decision, setDecision] = useState<DraftDecision>({
    action_threshold: '',
    decision_deadline: '',
    decision_owner: ''
  })
  const [gates, setGates] = useState<ForecastConfigGate[]>([])
  const [thresholds, setThresholds] = useState<ForecastConfigThreshold[]>([])

  useEffect(() => {
    aliveRef.current = true
    setLoading(true)
    gw.request<unknown>('forecast.config', { id: questionId })
      .then(raw => {
        if (!aliveRef.current) return
        const cfg = asRpcResult<ForecastConfigResponse>(raw)
        if (!cfg) {
          setError('forecast.config returned no data')
          setLoading(false)
          return
        }
        setCadence(cfg.cadence ?? '')
        setDecision({
          action_threshold: cfg.decision?.action_threshold ?? '',
          decision_deadline: cfg.decision?.decision_deadline ?? '',
          decision_owner: cfg.decision?.decision_owner ?? ''
        })
        setGates(cfg.gates ?? [])
        setThresholds(cfg.thresholds ?? [])
        setError('')
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (!aliveRef.current) return
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })

    return () => {
      aliveRef.current = false
    }
  }, [gw, questionId])

  // The flat, ordered list of navigable fields.
  const fields = useMemo<Field[]>(() => {
    const out: Field[] = [
      { key: 'cadence', kind: 'cadence' },
      { key: 'decision_owner', kind: 'text' },
      { key: 'decision_deadline', kind: 'text' },
      { key: 'action_threshold', kind: 'text' }
    ]
    gates.forEach((_, i) => out.push({ key: `gate_${i}`, kind: 'gate', ref: i }))
    thresholds.forEach((_, i) => out.push({ key: `thr_${i}`, kind: 'threshold', ref: i }))
    out.push({ key: 'save', kind: 'save' })
    return out
  }, [gates, thresholds])

  const clampedSel = Math.min(sel, Math.max(0, fields.length - 1))
  const current = fields[clampedSel]

  const save = () => {
    if (busy) return
    setBusy(true)
    setStatus('saving…')
    setError('')
    // Build the overrides map: only gates whose severity differs from the standard
    // default are written (so an unchanged gate stays profile-driven). Thresholds:
    // only the keys that differ from the registry default are written.
    const overrides: Record<string, string> = {}
    for (const g of gates) {
      if (g.severity && g.default && g.severity !== g.default) {
        overrides[g.id] = g.severity
      }
    }
    const thrOut: Record<string, number> = {}
    for (const thr of thresholds) {
      if (thr.value !== thr.default) {
        thrOut[thr.key] = thr.value
      }
    }
    const params: Record<string, unknown> = {
      decision: {
        action_threshold: decision.action_threshold,
        decision_deadline: decision.decision_deadline,
        decision_owner: decision.decision_owner
      },
      hooks: { overrides, thresholds: thrOut },
      id: questionId,
      review_cadence: cadence
    }
    gw.request('forecast.config.set', params)
      .then(() => {
        if (!aliveRef.current) return
        setBusy(false)
        setStatus('saved')
        onSaved?.()
        onClose()
      })
      .catch((err: unknown) => {
        if (!aliveRef.current) return
        setBusy(false)
        setStatus('')
        setError(err instanceof Error ? err.message : String(err))
      })
  }

  const editText = (apply: (prev: string) => string) => {
    if (current.key === 'cadence') return setCadence(apply)
    setDecision(prev => ({ ...prev, [current.key]: apply(prev[current.key as keyof DraftDecision]) }))
  }

  const adjust = (dir: 1 | -1) => {
    if (current.kind === 'gate' && current.ref !== undefined) {
      const i = current.ref
      setGates(prev => prev.map((g, gi) => (gi === i ? { ...g, severity: cycleSev(g.severity, dir), source: 'override' } : g)))
      return
    }
    if (current.kind === 'threshold' && current.ref !== undefined) {
      const i = current.ref
      setThresholds(prev =>
        prev.map((thr, ti) => (ti === i ? { ...thr, value: stepThreshold(thr, thr.value, dir), source: 'override' } : thr))
      )
    }
  }

  useInput((ch, key) => {
    if (busy) {
      if (key.escape) onClose()
      return
    }
    if (key.escape) return onClose()

    if (key.upArrow || (ch === 'k' && current.kind !== 'cadence' && current.kind !== 'text')) {
      return setSel(i => Math.max(0, i - 1))
    }
    if (key.downArrow) {
      return setSel(i => Math.min(fields.length - 1, i + 1))
    }
    if (key.tab) {
      return setSel(i => (i + 1) % fields.length)
    }

    if (current.kind === 'save') {
      if (key.return) return save()
      return
    }

    if (current.kind === 'gate' || current.kind === 'threshold') {
      if (key.leftArrow || ch === 'h' || ch === '-') return adjust(-1)
      if (key.rightArrow || ch === 'l' || ch === '+' || ch === ' ') return adjust(1)
      if (key.return) return setSel(i => Math.min(fields.length - 1, i + 1))
      return
    }

    // text / cadence fields capture typing
    if (key.return) {
      return setSel(i => Math.min(fields.length - 1, i + 1))
    }
    if (key.backspace || key.delete) {
      return editText(s => s.slice(0, -1))
    }
    if (ch && !key.ctrl && !key.meta) {
      const printable = [...ch].filter(c => c >= ' ').join('')
      if (printable) editText(s => s + printable)
    }
  })

  const modalW = Math.max(54, Math.min(cols - 4, 96))
  const modalH = Math.max(18, Math.min(rows - 4, 38))

  const cursorFor = (key: string) => (current.key === key ? '› ' : '  ')
  const labelColor = (key: string) => (current.key === key ? t.color.accent : t.color.label)

  const textRow = (key: string, label: string, value: string, placeholder: string) => {
    const active = current.key === key
    return (
      <Text key={key} wrap="truncate-end">
        <Text color={active ? t.color.accent : t.color.muted}>{cursorFor(key)}</Text>
        <Text color={labelColor(key)}>{label.padEnd(16)}</Text>
        <Text color={t.color.text}>{value || ''}</Text>
        {active ? (
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
        ) : null}
        {!value && !active ? <Text color={t.color.muted}>{placeholder}</Text> : null}
      </Text>
    )
  }

  const gateRow = (g: ForecastConfigGate, i: number) => {
    const key = `gate_${i}`
    const active = current.key === key
    const looser = g.looser
    return (
      <Text key={key} wrap="truncate-end">
        <Text color={active ? t.color.accent : t.color.muted}>{cursorFor(key)}</Text>
        <Text color={active ? t.color.accent : t.color.text}>{(g.label ?? g.id).padEnd(38).slice(0, 38)}</Text>
        <Text color={sevColor(t, g.severity)}>{` ${sevLabel[(g.severity as Severity) ?? 'warn'] ?? g.severity}`.padEnd(7)}</Text>
        {g.source === 'override' ? <Text color={t.color.info}>{' (set)'}</Text> : null}
        {looser ? <Text color={t.color.warn}>{' ⚠ looser'}</Text> : null}
      </Text>
    )
  }

  const thrRow = (thr: ForecastConfigThreshold, i: number) => {
    const key = `thr_${i}`
    const active = current.key === key
    return (
      <Text key={key} wrap="truncate-end">
        <Text color={active ? t.color.accent : t.color.muted}>{cursorFor(key)}</Text>
        <Text color={active ? t.color.accent : t.color.text}>{thr.label.padEnd(30).slice(0, 30)}</Text>
        <Text color={t.color.text}>{` ${fmtThr(thr, thr.value)}`.padEnd(8)}</Text>
        <Text color={t.color.muted}>{`(def ${fmtThr(thr, thr.default)})`}</Text>
        {thr.looser ? <Text color={t.color.warn}>{' ⚠ looser'}</Text> : null}
      </Text>
    )
  }

  const sectionHead = (label: string) => (
    <Box flexShrink={0} marginTop={1}>
      <Text bold color={t.color.primary}>
        {label}
      </Text>
    </Box>
  )

  const saveActive = current.kind === 'save'

  const body = loading ? (
    <Text color={t.color.muted}>Loading settings…</Text>
  ) : (
    <Box flexDirection="column">
      {sectionHead('CADENCE')}
      {textRow('cadence', 'Review every', cadence, 'e.g. weekly / 3d / every 2 weeks')}

      {sectionHead('DECISION CARD')}
      {textRow('decision_owner', 'Owner', decision.decision_owner, 'who owns the decision')}
      {textRow('decision_deadline', 'Deadline', decision.decision_deadline, 'ISO-8601 timestamp')}
      {textRow('action_threshold', 'Action threshold', decision.action_threshold, "e.g. 'act if P > 0.7'")}

      {sectionHead('GATES (←/→ off · warn · error)')}
      {gates.map((g, i) => gateRow(g, i))}

      {sectionHead('THRESHOLDS (←/→ adjust)')}
      {thresholds.map((thr, i) => thrRow(thr, i))}

      <Box flexShrink={0} marginTop={1}>
        <Text color={saveActive ? t.color.accent : t.color.muted}>{saveActive ? '› ' : '  '}</Text>
        <Text bold color={saveActive ? t.color.ok : t.color.label}>
          [ Save settings ]
        </Text>
        <Text color={t.color.muted}>{'  (⏎ on this row)'}</Text>
      </Box>
    </Box>
  )

  const footer = busy
    ? 'saving…'
    : current.kind === 'gate' || current.kind === 'threshold'
      ? '↑↓ field · ←/→ change · ⏎ next · Esc cancel'
      : current.kind === 'save'
        ? '⏎ save · ↑↓ field · Esc cancel'
        : 'type to edit · ↑↓/⏎ field · Esc cancel'

  return (
    <ModalOverlay cols={cols} maxHeight={modalH} maxWidth={modalW} rows={rows} t={t}>
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary} wrap="truncate-end">
            {title ? `Settings · ${title}` : 'Forecast settings'}
          </Text>
          <Text color={t.color.muted}>config</Text>
        </Box>
        <Box flexDirection="column" flexGrow={1} marginTop={1} minHeight={0} overflow="hidden">
          {body}
          {error ? (
            <Box flexShrink={0} marginTop={1}>
              <Text color={t.color.error} wrap="wrap">
                {error}
              </Text>
            </Box>
          ) : null}
          {status && !error ? (
            <Box flexShrink={0} marginTop={1}>
              <Text color={t.color.ok}>{status}</Text>
            </Box>
          ) : null}
        </Box>
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            {footer}
          </Text>
        </Box>
      </Box>
    </ModalOverlay>
  )
}
