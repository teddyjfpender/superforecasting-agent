import { randomUUID } from 'node:crypto'

import { Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { InterviewAssumption, InterviewAssumptionSaveRequest, InterviewRecord } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

const uncertaintyTypes: InterviewAssumption['uncertainty'][] = [
  'epistemic',
  'aleatoric',
  'measurement',
  'mixed',
  'unclassified'
]

const explanations = {
  epistemic: 'Missing knowledge: research may reduce uncertainty.',
  aleatoric: 'Outcome variability: more research cannot eliminate it.',
  measurement: 'Ambiguity or noise in how the outcome is observed.',
  mixed: 'Several uncertainty sources; keep their causes explicit.',
  unclassified: 'Uncertainty has not yet been classified.'
}

export function InterviewAssumptionEditor({
  gw,
  record,
  assumption,
  cols,
  rows,
  t,
  blocked,
  onClose,
  onSaved
}: {
  gw: GatewayClient
  record: InterviewRecord
  assumption: InterviewAssumption
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
  onSaved: (record: InterviewRecord) => void
}) {
  const [field, setField] = useState(0)
  const [statement, setStatement] = useState(assumption.statement)

  const [probability, setProbability] = useState(
    assumption.probability === null ? '' : String(assumption.probability * 100)
  )

  const [uncertainty, setUncertainty] = useState(assumption.uncertainty)
  const [rationale, setRationale] = useState(assumption.rationale)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const locked = useRef(false)
  const pending = useRef<InterviewAssumptionSaveRequest | null>(null)
  useEffect(
    () => () => {
      alive.current = false
    },
    []
  )

  const save = async () => {
    if (locked.current) {return}
    const numeric = probability.trim() === '' ? null : Number(probability)

    if (
      !statement.trim() ||
      statement.length > 3000 ||
      rationale.length > 10000 ||
      (numeric !== null &&
        (!/^\d+(\.\d+)?$/.test(probability.trim()) || !Number.isFinite(numeric) || numeric < 0 || numeric > 100))
    ) {
      setError('Use a statement (1–3000 characters), probability 0–100 or blank, and rationale up to 10000 characters.')

      return
    }

    const fields = {
      interview_id: record.interview_id,
      expected_revision: record.revision,
      assumption: {
        ...assumption,
        actor: 'user' as const,
        statement: statement.trim(),
        probability: numeric === null ? null : numeric / 100,
        uncertainty,
        rationale
      }
    }

    const previous = pending.current

    const request =
      previous && JSON.stringify({ ...previous, request_id: '' }) === JSON.stringify({ ...fields, request_id: '' })
        ? previous
        : { ...fields, request_id: randomUUID() }

    pending.current = request
    locked.current = true
    setBusy(true)
    setError('')

    try {
      const next = await gw.request('forecast.interview.assumption.save', request)

      if (alive.current) {onSaved(next)}
    } catch (cause) {
      if (alive.current) {setError(cause instanceof Error ? cause.message : String(cause))}
    } finally {
      locked.current = false

      if (alive.current) {setBusy(false)}
    }
  }

  useInput(
    (input, key, event) => {
      if (key.escape || key.tab || (key.ctrl && key.return) || field === 2 || busy) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (busy) {return}

      if (key.escape) {onClose()}
      else if (key.tab) {setField(value => (value + (key.shift ? 3 : 1)) % 4)}
      else if (key.ctrl && key.return) {void save()}
      else if (field === 2 && (input === ' ' || key.leftArrow || key.rightArrow)) {
        setUncertainty(value => uncertaintyTypes[(uncertaintyTypes.indexOf(value) + (key.leftArrow ? 4 : 1)) % 5]!)
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint="[Tab Field] [Space Type] [Ctrl+Enter Save] [Esc Cancel]"
      maxHeight={28}
      maxWidth={100}
      rows={rows}
      t={t}
      title="EDIT ASSUMPTION"
      verticalMargin={2}
    >
      <Text color={t.color.muted}>Changes are attributed to you; earlier revisions remain available.</Text>
      <Text bold color={t.color.accent}>
        {['Statement', 'Probability (%) · blank means unknown', 'Uncertainty type', 'Rationale'][field]}
      </Text>
      {field === 2 ? (
        <Text color={t.color.primary}>
          {uncertainty} · {explanations[uncertainty]}
        </Text>
      ) : (
        <TextInput
          columns={Math.max(20, Math.min(cols - 10, 90))}
          focus={!blocked && !busy}
          key={field}
          onChange={field === 0 ? setStatement : field === 1 ? setProbability : setRationale}
          onSubmit={() => setField(value => (value + 1) % 4)}
          value={field === 0 ? statement : field === 1 ? probability : rationale}
        />
      )}
      <Text color={t.color.muted}>
        Evidence links retained: {assumption.evidence_refs.length}. Active forecast unchanged.
      </Text>
      <Text color={error ? t.color.error : t.color.muted}>
        {error || (busy ? 'Saving assumption…' : `${field + 1}/4 · Save applies all fields.`)}
      </Text>
    </ModalOverlay>
  )
}
