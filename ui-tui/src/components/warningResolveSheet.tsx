import { Box, Text, useInput } from '@hermes/ink'
import { useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { ForecastDashboardAlert, ForecastWarningsResolveResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import { classifyWarning, warningKindLabel, warningResolution } from '../lib/warningKind.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

// Per-alert RESOLVE sheet, painted over the Warnings overlay (press Enter on a
// selected question-scoped alert). Modeled on ForecastSettingsModal: it owns its
// own useInput (the parent traps the keyboard while a sheet is open) and shows the
// alert's reason + recommended_action + the resolution that WILL run, then calls
// forecast.warnings.resolve on confirm. The load-bearing rule is honoured by the
// dispatcher behind the RPC — this sheet NEVER bare-acks; it just drives the gated
// path and reports the real per-alert status back (resolved / surfaced / failed /
// skipped). A NO_AUTO alert is shown as "surfaced for human review" so the user
// knows confirming will not close it.

const sevColor = (t: Theme, severity: string | undefined): string => {
  const s = (severity || '').toLowerCase()

  if (/crit|alert|fail|block|error|high/.test(s)) {
    return t.color.error
  }

  if (/warn|medium|review|stale|due|gap/.test(s)) {
    return t.color.warn
  }

  return t.color.muted
}

interface WarningResolveSheetProps {
  alert: ForecastDashboardAlert
  cols: number
  gw: GatewayClient
  onClose: () => void
  // Called with the resolved status (e.g. 'resolved' | 'surfaced' | 'failed' |
  // 'skipped') + a human detail so the parent can flash + refresh.
  onResolved: (status: string, detail: string) => void
  rows: number
  t: Theme
}

export function WarningResolveSheet({ alert, cols, gw, onClose, onResolved, rows, t }: WarningResolveSheetProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const aliveRef = useRef(true)

  const kind = classifyWarning(alert.reason)
  const plan = warningResolution(kind)

  const confirm = () => {
    if (busy || !alert.id) {
      if (!alert.id) {
        setError('this alert has no id to resolve')
      }

      return
    }

    aliveRef.current = true
    setBusy(true)
    setError('')
    gw.request<unknown>('forecast.warnings.resolve', { alert_id: alert.id })
      .then(raw => {
        if (!aliveRef.current) {
          return
        }

        const res = asRpcResult<ForecastWarningsResolveResponse>(raw)
        const first = res?.results?.[0]
        const status = first?.status ?? 'failed'
        const detail = first?.detail ?? 'no result returned'
        setBusy(false)
        onResolved(status, detail)
        onClose()
      })
      .catch((err: unknown) => {
        if (!aliveRef.current) {
          return
        }

        setBusy(false)
        setError(err instanceof Error ? err.message : String(err))
      })
  }

  useInput((ch, key) => {
    if (busy) {
      if (key.escape) {
        aliveRef.current = false
        onClose()
      }

      return
    }

    if (key.escape || ch === 'n' || ch === 'q') {
      return onClose()
    }

    if (key.return || ch === 'y') {
      return confirm()
    }
  })

  const modalW = Math.max(50, Math.min(cols - 4, 88))
  const modalH = Math.max(14, Math.min(rows - 4, 28))

  const row = (label: string, value: string, color?: string) => (
    <Box flexShrink={0} marginTop={1}>
      <Text wrap="wrap">
        <Text color={t.color.label}>{label.padEnd(13)}</Text>
        <Text color={color ?? t.color.text}>{value}</Text>
      </Text>
    </Box>
  )

  const footer = busy
    ? 'resolving…'
    : plan.auto
      ? '⏎/y resolve · Esc/n cancel'
      : '⏎/y run anyway (will surface) · Esc/n cancel'

  return (
    <ModalOverlay cols={cols} maxHeight={modalH} maxWidth={modalW} rows={rows} t={t}>
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary} wrap="truncate-end">
            Resolve alert
          </Text>
          <Text color={sevColor(t, alert.severity)}>{(alert.severity || 'alert').toLowerCase()}</Text>
        </Box>

        <Box flexDirection="column" flexGrow={1} marginTop={1} minHeight={0} overflow="hidden">
          {alert.scope_ref ? row('Scope', alert.scope_ref, t.color.text) : null}
          {alert.reason ? row('Reason', alert.reason, t.color.text) : null}
          {alert.recommended_action ? row('Suggested', alert.recommended_action, t.color.muted) : null}

          <Box flexShrink={0} marginTop={1}>
            <Text bold color={t.color.primary}>
              {`WILL RUN · ${warningKindLabel(kind)}`}
            </Text>
          </Box>
          <Box flexShrink={0}>
            <Text color={plan.auto ? t.color.ok : t.color.warn} wrap="wrap">
              {plan.label}
            </Text>
          </Box>
          <Box flexShrink={0}>
            <Text color={t.color.muted} wrap="wrap">
              {plan.detail}
            </Text>
          </Box>

          {error ? (
            <Box flexShrink={0} marginTop={1}>
              <Text color={t.color.error} wrap="wrap">
                {error}
              </Text>
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
