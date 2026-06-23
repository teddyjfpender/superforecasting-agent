import { Box, Text, useInput } from '@hermes/ink'
import { useEffect, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

// Guided author/edit flow for a user-defined forecast hook rule. Builds a flat
// all-of rule (id -> description -> [signal op value] AND-loop -> severity ->
// remediation -> live dry-run preview -> save). Validation + persistence run on
// the gateway (forecast.hooks.preview / forecast.hooks.save_rule), so the wizard
// only assembles the spec and surfaces the teaching errors it gets back.

export interface GlossarySignal {
  name: string
  kind: string
  doc: string
}

interface Condition {
  signal: string
  op: string
  value: string
}

interface PreviewResult {
  valid: boolean
  applies?: number
  would_block?: number
  failing?: string[]
  issues?: { field: string; message: string }[]
}

const SEVERITIES = ['warn', 'error', 'off']
const REMEDIATIONS = ['none', 'collect_evidence', 'run_panel', 'decompose', 'compress_tails', 'sanitize_style', 'fix_distribution', 'sharpen', 'run_quorum', 'tag_reasoning']
const NUM_OPS = ['>=', '>', '<=', '<', '==', '!=']
const BOOL_OPS = ['is_true', 'is_false']

type Step = 'id' | 'desc' | 'signal' | 'op' | 'value' | 'more' | 'severity' | 'remediation' | 'preview' | 'confirm'

function buildSpec(o: { id: string; desc: string; conditions: Condition[]; severity: string; remediation: string }): Record<string, unknown> {
  const leaf = (c: Condition): Record<string, unknown> => {
    const base: Record<string, unknown> = { signal: c.signal, op: c.op }

    if (c.op === 'is_true' || c.op === 'is_false') {
      return base
    }

    const num = Number(c.value)
    base.value = c.value !== '' && !Number.isNaN(num) ? num : c.value

    return base
  }

  const check = o.conditions.length === 1 ? leaf(o.conditions[0]!) : { all: o.conditions.map(leaf) }

  return {
    id: o.id,
    severity: o.severity,
    category: 'custom',
    description: o.desc,
    remediation_hint: o.remediation,
    check,
    message: o.desc || `${o.id} failed`,
  }
}

export function HooksWizard({
  cols,
  editId,
  gw,
  glossary,
  initial,
  onCancel,
  onSaved,
  rows,
  t,
}: {
  cols: number
  editId?: string
  gw?: GatewayClient
  glossary: GlossarySignal[]
  initial?: { id: string; desc: string; conditions: Condition[]; severity: string; remediation: string }
  onCancel: () => void
  onSaved: (id: string) => void
  rows: number
  t: Theme
}) {
  const [step, setStep] = useState<Step>('id')
  const [id, setId] = useState(initial?.id ?? '')
  const [desc, setDesc] = useState(initial?.desc ?? '')
  const [conditions, setConditions] = useState<Condition[]>(initial?.conditions ?? [])
  const [draft, setDraft] = useState<Condition>({ signal: '', op: '', value: '' })
  const [severity, setSeverity] = useState(initial?.severity ?? 'warn')
  const [remediation, setRemediation] = useState(initial?.remediation ?? 'none')
  const [text, setText] = useState(initial?.id ?? '')
  const [sel, setSel] = useState(0)
  const [error, setError] = useState('')
  const [blink, setBlink] = useState(true)
  const [preview, setPreview] = useState<null | PreviewResult>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const tid = setInterval(() => setBlink(b => !b), 500)

    return () => clearInterval(tid)
  }, [])

  const modalW = Math.max(56, Math.min(cols - 4, 104))
  const modalH = Math.max(18, Math.min(rows - 4, 32))

  const sigKind = (name: string): string => glossary.find(g => g.name === name)?.kind ?? 'number'
  const opsForDraft = draft.signal && sigKind(draft.signal) === 'bool' ? BOOL_OPS : NUM_OPS

  const runPreview = () => {
    if (!gw) {
      return
    }

    setBusy(true)
    setPreview(null)
    gw.request('forecast.hooks.preview', { rule: buildSpec({ id, desc, conditions, severity, remediation }) })
      .then(raw => setPreview((asRpcResult<PreviewResult>(raw) ?? null)))
      .catch((e: unknown) => setPreview({ valid: false, issues: [{ field: 'rpc', message: String(e) }] }))
      .finally(() => setBusy(false))
  }

  useEffect(() => {
    if (step === 'preview') {
      runPreview()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  const save = () => {
    if (!gw) {
      return
    }

    setBusy(true)
    const params: Record<string, unknown> = { rule: buildSpec({ id, desc, conditions, severity, remediation }) }

    if (editId) {
      params.edit_id = editId
    }

    gw.request('forecast.hooks.save_rule', params)
      .then(raw => {
        const res = asRpcResult<{ id?: string; ok?: boolean; error?: string; issues?: { field: string; message: string }[] }>(raw)

        if (res && res.ok === false) {
          setError(res.error ?? 'rule refused')
          setStep('preview')
          setPreview({ valid: false, issues: res.issues })

          return
        }

        onSaved(res?.id ?? id)
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setBusy(false))
  }

  // step machine
  useInput((ch, key) => {
    if (key.escape) {
      return onCancel()
    }

    if (step === 'id') {
      if (key.return) {
        if (!text.trim()) {
          return setError('a rule id is required')
        }

        setId(text.trim())
        setError('')
        setText(desc)

        return setStep('desc')
      }

      if (key.backspace || key.delete) {
        return setText(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        return setText(s => s + [...ch].filter(c => c >= ' ').join(''))
      }

      return
    }

    if (step === 'desc') {
      if (key.return) {
        setDesc(text.trim())
        setText('')
        setSel(0)

        return setStep('signal')
      }

      if (key.backspace || key.delete) {
        return setText(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        return setText(s => s + [...ch].filter(c => c >= ' ').join(''))
      }

      return
    }

    if (step === 'signal') {
      if (key.upArrow || ch === 'k') {
        return setSel(s => (s - 1 + glossary.length) % glossary.length)
      }

      if (key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % glossary.length)
      }

      if (key.return) {
        const picked = glossary[sel]

        if (!picked) {
          return
        }

        setDraft({ signal: picked.name, op: '', value: '' })
        setSel(0)

        return setStep('op')
      }

      return
    }

    if (step === 'op') {
      if (key.upArrow || ch === 'k') {
        return setSel(s => (s - 1 + opsForDraft.length) % opsForDraft.length)
      }

      if (key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % opsForDraft.length)
      }

      if (key.return) {
        const op = opsForDraft[sel]!
        const d = { ...draft, op }
        setDraft(d)
        setText('')

        if (op === 'is_true' || op === 'is_false') {
          setConditions(cs => [...cs, d])
          setSel(0)

          return setStep('more')
        }

        return setStep('value')
      }

      return
    }

    if (step === 'value') {
      if (key.return) {
        if (!text.trim()) {
          return setError('a value is required for this operator')
        }

        setConditions(cs => [...cs, { ...draft, value: text.trim() }])
        setError('')
        setText('')
        setSel(0)

        return setStep('more')
      }

      if (key.backspace || key.delete) {
        return setText(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        return setText(s => s + [...ch].filter(c => c >= ' ').join(''))
      }

      return
    }

    if (step === 'more') {
      // sel 0 = add another (AND), 1 = done
      if (key.upArrow || ch === 'k' || key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % 2)
      }

      if (key.return) {
        if (sel === 0) {
          setSel(0)

          return setStep('signal')
        }

        setSel(SEVERITIES.indexOf(severity) < 0 ? 0 : SEVERITIES.indexOf(severity))

        return setStep('severity')
      }

      return
    }

    if (step === 'severity') {
      if (key.upArrow || ch === 'k') {
        return setSel(s => (s - 1 + SEVERITIES.length) % SEVERITIES.length)
      }

      if (key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % SEVERITIES.length)
      }

      if (key.return) {
        setSeverity(SEVERITIES[sel]!)
        setSel(0)

        return setStep('remediation')
      }

      return
    }

    if (step === 'remediation') {
      if (key.upArrow || ch === 'k') {
        return setSel(s => (s - 1 + REMEDIATIONS.length) % REMEDIATIONS.length)
      }

      if (key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % REMEDIATIONS.length)
      }

      if (key.return) {
        setRemediation(REMEDIATIONS[sel]!)

        return setStep('preview')
      }

      return
    }

    if (step === 'preview') {
      if (ch === 'r') {
        return runPreview()
      }

      if (key.return) {
        if (preview && preview.valid === false) {
          return
        }

        return save()
      }

      if (ch === 'b') {
        setSel(0)

        return setStep('severity')
      }

      return
    }
  })

  const field = (placeholder: string) => (
    <Box marginTop={1} width={Math.max(20, modalW - 6)}>
      <Text wrap="wrap">
        <Text color={t.color.muted}>{'› '}</Text>
        <Text color={t.color.text}>{text}</Text>
        {blink ? (
          <Text color={t.color.accent} inverse>
            {' '}
          </Text>
        ) : (
          <Text>{' '}</Text>
        )}
        {!text ? <Text color={t.color.muted}>{placeholder}</Text> : null}
      </Text>
    </Box>
  )

  const choiceList = (items: string[], blurbs?: Record<string, string>) => (
    <Box flexDirection="column" marginTop={1}>
      {items.map((c, i) => (
        <Text color={i === sel ? t.color.accent : t.color.text} key={c} wrap="truncate-end">
          {i === sel ? '▸ ' : '  '}
          {c}
          {blurbs?.[c] ? <Text color={t.color.muted}>{`  — ${blurbs[c]}`}</Text> : null}
        </Text>
      ))}
    </Box>
  )

  const PROMPT: Record<Step, string> = {
    confirm: 'Review',
    desc: 'Description (what this rule enforces)',
    id: 'Rule id (e.g. min_three_drivers)',
    more: 'Add another condition?',
    op: `Operator for ${draft.signal}`,
    preview: 'Dry-run preview',
    remediation: 'Remediation hint (how the agent should fix it)',
    severity: 'Severity',
    signal: 'Pick a signal to test',
    value: `Value for ${draft.signal} ${draft.op}`,
  }

  const condSummary = conditions.map(c => `${c.signal} ${c.op}${c.op.startsWith('is_') ? '' : ' ' + c.value}`).join('  AND  ')

  const chips: FooterChip[] =
    step === 'preview'
      ? [{ k: '⏎', label: preview?.valid === false ? 'Fix first' : 'Save' }, { k: 'r', label: 'Re-preview' }, { k: 'b', label: 'Back' }, { k: 'Esc', label: 'Cancel' }]
      : step === 'signal' || step === 'op' || step === 'severity' || step === 'remediation' || step === 'more'
        ? [{ k: '↑↓', label: 'Choose' }, { k: '⏎', label: 'Next' }, { k: 'Esc', label: 'Cancel' }]
        : [{ k: '⏎', label: 'Next' }, { k: 'Esc', label: 'Cancel' }]

  return (
    <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
      <Box borderColor={t.color.accent} borderStyle="round" flexDirection="column" height={modalH} paddingX={2} paddingY={1} width={modalW}>
        <Text bold color={t.color.primary}>
          {editId ? `EDIT HOOK RULE · ${editId}` : 'NEW HOOK RULE'}
        </Text>
        {condSummary ? (
          <Text color={t.color.muted} wrap="truncate-end">
            {condSummary}
          </Text>
        ) : null}

        <Box flexDirection="column" flexGrow={1} marginTop={1}>
          <Text color={t.color.label}>{PROMPT[step]}</Text>

          {step === 'id' ? field('min_three_drivers') : null}
          {step === 'desc' ? field('decomposition must pool at least three drivers') : null}

          {step === 'signal' ? (
            <Box flexDirection="column" marginTop={1}>
              {glossary.map((g, i) => (
                <Text color={i === sel ? t.color.accent : t.color.text} key={g.name} wrap="truncate-end">
                  {i === sel ? '▸ ' : '  '}
                  {g.name}
                  <Text color={t.color.muted}>{`  (${g.kind})${i === sel ? '  — ' + g.doc : ''}`}</Text>
                </Text>
              ))}
            </Box>
          ) : null}

          {step === 'op' ? choiceList(opsForDraft) : null}
          {step === 'value' ? field(sigKind(draft.signal) === 'number' ? 'a number, e.g. 3' : 'a value') : null}
          {step === 'more' ? choiceList(['add another (AND)', 'done — set severity']) : null}
          {step === 'severity' ? choiceList(SEVERITIES, { error: 'blocks the commit', off: 'advisory only (no score penalty)', warn: 'scored, never blocks' }) : null}
          {step === 'remediation' ? choiceList(REMEDIATIONS) : null}

          {step === 'preview' ? (
            <Box flexDirection="column" marginTop={1}>
              <Text color={t.color.muted} wrap="truncate-end">{`${id}  [${severity}]  ·  ${condSummary || 'no conditions'}`}</Text>
              {busy ? <Text color={t.color.muted}>previewing…</Text> : null}
              {!busy && preview?.valid === false ? (
                <Box flexDirection="column" marginTop={1}>
                  <Text color={t.color.error}>rule is invalid — fix before saving:</Text>
                  {(preview.issues ?? []).map((i, idx) => (
                    <Text color={t.color.error} key={idx} wrap="wrap">{`  ${i.field}: ${i.message}`}</Text>
                  ))}
                </Box>
              ) : null}
              {!busy && preview?.valid ? (
                <Box flexDirection="column" marginTop={1}>
                  <Text color={t.color.ok}>{`valid · applies to ${preview.applies ?? 0} active forecast(s), would ${severity === 'error' ? 'block' : 'flag'} ${preview.would_block ?? 0}`}</Text>
                  {preview.failing?.length ? (
                    <Text color={t.color.muted} wrap="truncate-end">{`affected: ${preview.failing.join(', ')}`}</Text>
                  ) : null}
                </Box>
              ) : null}
            </Box>
          ) : null}

          {error ? (
            <Box marginTop={1}>
              <Text color={t.color.error} wrap="wrap">
                {error}
              </Text>
            </Box>
          ) : null}
        </Box>

        <FooterChips chips={chips} t={t} />
      </Box>
    </Box>
  )
}
