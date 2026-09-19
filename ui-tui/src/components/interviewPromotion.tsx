import { ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { InterviewPromotionPreviewResponse, ScenarioReport } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

export function InterviewPromotion({
  gw,
  jobId,
  report,
  cols,
  rows,
  t,
  blocked,
  onClose
}: {
  gw: GatewayClient
  jobId: string
  report: ScenarioReport
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
}) {
  const baselines = report.results.filter(item => item.kind === 'baseline' && item.variant_id === 'baseline')
  const [index, setIndex] = useState(0)
  const [preview, setPreview] = useState<InterviewPromotionPreviewResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const alive = useRef(true)
  const locked = useRef(false)
  const scroll = useRef<ScrollBoxHandle>(null)
  const selected = baselines[index]
  useEffect(() => {
    alive.current = true

    return () => {
      alive.current = false
    }
  }, [])

  const act = async (commit: boolean) => {
    if (locked.current || !selected) {
      return
    }

    locked.current = true
    setBusy(true)
    setError('')

    try {
      if (commit && preview?.would_commit) {
        const result = await gw.request('forecast.interview.promote', {
          job_id: jobId,
          repetition: selected.repetition,
          preview_digest: preview.preview_digest
        })

        if (alive.current) {
          setSaved(result.forecast_id)
        }
      } else {
        const result = await gw.request('forecast.interview.promotion_preview', {
          job_id: jobId,
          repetition: selected.repetition
        })

        if (alive.current) {
          setPreview(result)
          setSaved(result.promoted_forecast_id ?? '')

          if (result.promoted_forecast_id)
            {setIndex(
              Math.max(
                0,
                baselines.findIndex(item => item.repetition === result.repetition)
              )
            )}
        }
      }
    } catch (cause) {
      if (alive.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      locked.current = false

      if (alive.current) {
        setBusy(false)
      }
    }
  }

  useInput(
    (input, key, event) => {
      ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()

      if (key.escape) {
        onClose()

        return
      }

      if (busy || saved) {
        return
      }

      if (key.pageDown || key.pageUp) {
        scroll.current?.scrollBy(key.pageDown ? 5 : -5)

        return
      }

      if (key.leftArrow || key.rightArrow) {
        setIndex(value => Math.max(0, Math.min(baselines.length - 1, value + (key.leftArrow ? -1 : 1))))
        setPreview(null)
        setError('')

        return
      }

      if (key.return && key.ctrl && preview?.would_commit) {
        void act(true)
      } else if (key.return) {
        void act(false)
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint={saved ? '[Esc Back]' : '[←→ Run] [Enter Preview] [^Enter Confirm] [PgUp/Dn Read] [Esc]'}
      maxHeight={30}
      maxWidth={105}
      rows={rows}
      t={t}
      title="PROMOTE UNCONDITIONAL FORECAST"
      verticalMargin={2}
    >
      <ScrollBox
        decstbm={false}
        flexDirection="column"
        followContent={false}
        height={Math.max(3, Math.min(rows - 2, 30) - 7)}
        ref={scroll}
      >
        <Text bold color={t.color.primary}>
          Unconditional baseline · run {(selected?.repetition ?? 0) + 1} of {baselines.length}
        </Text>
        <Text color={t.color.muted}>
          This changes the active forecast. Conditional and ablation results cannot be promoted here.
        </Text>
        <Text color={t.color.primary}>{selected?.estimate.rationale ?? 'No unconditional baseline is available.'}</Text>
        {preview ? (
          <>
            <Text bold color={t.color.accent}>
              Ledger candidate:{' '}
              {typeof preview.candidate === 'number'
                ? `${(preview.candidate * 100).toFixed(1)}%`
                : JSON.stringify(preview.candidate)}
            </Text>
            <Text color={t.color.muted}>
              The ledger preview includes any configured probability clamp. Review this exact value before confirming.
            </Text>
            {preview.blockers.map((item, at) => (
              <Text color={t.color.error} key={at}>
                {item}
              </Text>
            ))}
            {preview.would_commit && !saved ? (
              <Text color={t.color.accent}>
                Ready. Ctrl+Enter explicitly accepts this candidate as the active forecast.
              </Text>
            ) : null}
          </>
        ) : (
          <Text color={t.color.muted}>
            Enter checks evidence, resolution contract and the current baseline without saving a forecast.
          </Text>
        )}
        {saved ? <Text color={t.color.accent}>Forecast saved: {saved}</Text> : null}
        {busy ? <Text color={t.color.accent}>Checking durable ledger state…</Text> : null}
        {error ? <Text color={t.color.error}>{error}</Text> : null}
      </ScrollBox>
    </ModalOverlay>
  )
}
